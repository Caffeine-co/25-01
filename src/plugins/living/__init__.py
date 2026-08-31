import asyncio
import json
import logging
import random
import time
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.base import MaxInstancesReachedError
from apscheduler.job import Job
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from collections.abc import Callable
from datetime import datetime
from nonebot import get_driver, get_bot
from nonebot.adapters.onebot.v11.event import GroupMessageEvent, PrivateMessageEvent
from nonebot.log import LoguruHandler, logger
from nonebot.plugin.on import on_message
from src.plugins.living.afterprocess import handle_and_send_msg, update_friend_impression_in_chat
from src.plugins.living.client import pre_chat_request, chatting_request, status_request, memory_request
from src.plugins.living.config import chat_cfg, scheduler_cfg
from src.plugins.living.database import init_memory_db, init_session_info_db, update_msg_read_status, update_group_impression, update_group_info, update_friend_info, record_received_group_msg, record_received_friend_msg, update_user_all_memory, get_user_list_in_memory
from src.plugins.living.preprocess import get_pre_chat_input, get_chatting_input, get_status_update_input, get_memory_archive_input
from src.plugins.living.probability import active_probability
from src.plugins.living.utils import check_null_msg, format_received_msg, download_image_to_temp
from src.plugins.living.validate import CharacterStatus
from typing import Any, ParamSpec, TypeVar
from uuid import uuid5, NAMESPACE_OID


P = ParamSpec("P")
R = TypeVar("R")

JOB_PRIORITIES: dict[str, int] = {}

def priority_scheduled_job(
    trigger: str | BaseTrigger,
    *,
    job_id: str,
    priority: int = 0,
    **kwargs: Any
) -> Callable[
    [Callable[P, R]],
    Callable[P, R]
]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        JOB_PRIORITIES[job_id] = priority
        try:
            scheduler.scheduled_job(
                trigger=trigger,
                id=job_id,
                **kwargs
            )(func)
        except Exception:
            JOB_PRIORITIES.pop(job_id, None)
            raise
        return func
    return decorator

class PriorityMemoryJobStore(MemoryJobStore):
    def get_due_jobs(self, now: datetime) -> list[Job]:
        jobs = super().get_due_jobs(now)
        jobs.sort(
            key=lambda job: (
                job.next_run_time,
                -JOB_PRIORITIES.get(job.id, 0),
                job.id
            )
        )
        return jobs

class SharedLimitAsyncIOExecutor(AsyncIOExecutor):
    def __init__(self, max_instances: int = 1) -> None:
        if max_instances < 1:
            raise ValueError("max_instances 必须大于等于 1")
        super().__init__()
        self._shared_max_instances = max_instances
        self._shared_instances = 0

    def submit_job(self, job: Job, run_times: list[datetime]) -> None:
        assert self._lock is not None, "Executor 尚未启动"
        with self._lock:
            if self._instances[job.id] >= job.max_instances:
                raise MaxInstancesReachedError(job)
            if self._shared_instances >= self._shared_max_instances:
                raise MaxInstancesReachedError(job)
            self._do_submit_job(job, run_times)
            self._instances[job.id] += 1
            self._shared_instances += 1

    def _release_instance(self, job_id: str) -> None:
        self._instances[job_id] -= 1
        if self._instances[job_id] == 0:
            del self._instances[job_id]
        self._shared_instances -= 1
        if self._shared_instances < 0:
            raise RuntimeError("Executor 共享运行计数小于 0")

    def _run_job_success(self, job_id: str, events: list[Any]) -> None:
        with self._lock:
            self._release_instance(job_id)
        for event in events:
            self._scheduler._dispatch_event(event)

    def _run_job_error(self, job_id: str, exc: BaseException, traceback: Any = None) -> None:
        with self._lock:
            self._release_instance(job_id)
        exc_info = (exc.__class__, exc, traceback)
        self._logger.error("Error running job %s", job_id, exc_info=exc_info)

scheduler = AsyncIOScheduler(
    timezone="Asia/Shanghai",
    jobstores={
        "default": PriorityMemoryJobStore()
    },
    executors={
        "shared": SharedLimitAsyncIOExecutor(max_instances=1)
    }
)

aps_logger = logging.getLogger("apscheduler")
aps_logger.setLevel(logging.WARNING)
aps_logger.handlers.clear()
aps_logger.addHandler(LoguruHandler())

async def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.opt(colors=True).info("<y>Scheduler Started</y>")

async def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
        logger.opt(colors=True).info("<y>Scheduler Shutdown</y>")

driver = get_driver()
@driver.on_startup
async def _() -> None:
    await asyncio.gather(
        init_memory_db(),
        init_session_info_db(),
        start_scheduler()
    )
@driver.on_shutdown
async def _() -> None:
    await shutdown_scheduler()

async def chat_dispatch() -> None:
    active_value = active_probability(int(time.time()))
    random_value = random.random()
    if random_value > active_value:
        return
    logger.info(f"Open the software")
    status = await CharacterStatus.load()
    pre_chat_input = await get_pre_chat_input(status)
    try:
        logger.info(f"Browsing the homepage...")
        pre_chat_output = await pre_chat_request(pre_chat_input)
    except:
        logger.error(f"pre_chat_request failed completely")
        return
    await status.update(pre_chat_output["new_status"])
    session = pre_chat_output["session"]
    logger.info(f"Open the session {session['type']}_{session['id']}")
    for i in range(chat_cfg["max_session_rounds"]):
        chatting_input, unread_msg_list = await get_chatting_input(status, session)
        try:
            logger.info(f"Browsing the messages...")
            chatting_output = await chatting_request(chatting_input, session)
        except:
            logger.error(f"chatting_request failed completely")
            return
        await status.update(chatting_output["new_status"])
        await update_msg_read_status(session, unread_msg_list)
        await update_friend_impression_in_chat(session, chatting_output["user_impression"])
        if session["type"] =="group":
            await update_group_impression(session["id"], chatting_output["group_impression"], True)
        if chatting_output["chat"]:
            await handle_and_send_msg(session, chatting_output["message"])
        next_action = chatting_output["next_action"]
        match next_action["type"]:
            case "exit":
                logger.info(f"Close the software")
                break
            case "stay":
                logger.info(f"Stay in the current chat")
                await asyncio.sleep(
                    random.randint(
                        chat_cfg["stay_interval_range"]["min"],
                        chat_cfg["stay_interval_range"]["max"]
                    )
                )
            case "switch":
                session = next_action["session"]
                logger.info(f"Switch to next session {session['type']}_{session['id']}")

async def status_update() -> None:
    logger.info(f"Start updating status...")
    status = await CharacterStatus.load()
    status_input = await get_status_update_input(status)
    try:
        status_output = await status_request(status_input)
    except Exception as e:
        logger.error(f"status_request error: \n{e}]")
        return
    await status.update(status_output["new_status"])
    logger.success(f"Status update complete")

async def memory_archive() -> None:
    logger.info(f"Start archiving memory...")
    user_list = await get_user_list_in_memory()
    for i in range(0, len(user_list), chat_cfg["max_memory_user_counts"]):
        user_split = user_list[i:i + chat_cfg["max_memory_user_counts"]]
        memory_input = await get_memory_archive_input(user_split)
        try:
            memory_output = await memory_request(memory_input)
        except:
            logger.error(f"memory_request failed: users={user_split}")
            continue
        output_ids = [user["user_id"] for user in memory_output]
        if len(output_ids) != len(set(output_ids)) or set(output_ids) != set(user_split):
            logger.error(f"memory output user mismatch: expected={user_split}, returned={output_ids}")
            continue
        for user in memory_output:
            await update_user_all_memory(user["user_id"], user["portrait"], user["memory"])
    logger.success(f"Memory archive complete")

async def session_update() -> None:
    logger.info(f"Start updating session info...")
    run_mode = chat_cfg["run_mode"]
    group_list = []
    friend_list = []
    for session in chat_cfg[f"{run_mode}s"]:
        match session["type"]:
            case "group":
                group_list.append(session["id"])
            case _:
                friend_list.append(session["id"])
    bot = get_bot()
    raw_group_list = await bot.get_group_list(no_cache=True)
    raw_friend_list = await bot.get_friend_list(no_cache=True)
    for rg in raw_group_list:
        if rg["group_id"] in group_list:
            await update_group_info(rg["group_id"], rg["group_name"], rg["member_count"])
    for rf in raw_friend_list:
        if rf["user_id"] in friend_list:
            await update_friend_info(rf["user_id"], rf["nickname"])
    logger.success(f"Session info update complete")

@priority_scheduled_job(
    trigger="cron",
    job_id="chat_dispatch",
    priority=2,
    executor="shared",
    **scheduler_cfg["chat_dispatch"]
)
async def _() -> None:
    await chat_dispatch()

@priority_scheduled_job(
    trigger="cron",
    job_id="status_update",
    priority=1,
    executor="shared",
    **scheduler_cfg["status_update"]
)
async def _() -> None:
    await status_update()

@priority_scheduled_job(
    trigger="cron",
    job_id="memory_archive",
    priority=3,
    executor="shared",
    **scheduler_cfg["memory_archive"]
)
async def _() -> None:
    await memory_archive()

@scheduler.scheduled_job(
    trigger="cron",
    id="session_update",
    **scheduler_cfg["session_update"]
)
async def _() -> None:
    await session_update()

async def check_group(event: GroupMessageEvent) -> bool:
    run_mode = chat_cfg["run_mode"]
    return {"type": "group", "id": event.group_id} in chat_cfg[f"{run_mode}s"]
async def check_private(event: PrivateMessageEvent) -> bool:
    run_mode = chat_cfg["run_mode"]
    return {"type": "friend", "id": event.user_id} in chat_cfg[f"{run_mode}s"]

group_msg = on_message(rule=check_group)
private_msg = on_message(rule=check_private)

@group_msg.handle()
@private_msg.handle()
async def record(event: GroupMessageEvent | PrivateMessageEvent):
    if check_null_msg(event.original_message):
        return
    content, image_urls = await format_received_msg(event.original_message, event.self_id)
    image_names = []
    if chat_cfg["enable_vision"] and image_urls:
        for i, image_url in enumerate(image_urls):
            image_id = str(uuid5(NAMESPACE_OID, f"{event.time}_{event.message_id or 0}_{event.user_id}_{i}"))
            try:
                await download_image_to_temp(image_url, image_id)
            except Exception as e:
                logger.error(f"download message_{event.message_id}'s image_{i + 1} error: {e}")
            else:
                image_names.append(image_id)
    img_data = json.dumps(image_names, ensure_ascii=False)
    match event.message_type:
        case "group":
            await record_received_group_msg(event.group_id, {
                "time": event.time,
                "message_id": event.message_id,
                "user_id": event.user_id,
                "nickname": event.sender.card or event.sender.nickname or "未知昵称",
                "content": content,
                "image_data": img_data
            })
        case "private":
            await record_received_friend_msg(event.user_id, {
                "time": event.time,
                "message_id": event.message_id,
                "content": content,
                "image_data": img_data
            })