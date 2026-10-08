import aiosqlite
import asyncio
import json
from src.plugins.living.config import chat_cfg, debug_status_snapshot
from src.plugins.living.utils import delete_temp_image


_session_db_write_lock = asyncio.Lock()

_session_cache_memory: set[tuple[str, int]] = set()

def _connect_session_db() -> aiosqlite.Connection:
    return aiosqlite.connect(
        chat_cfg["session_info_db_path"],
        timeout=30.0
    )

async def init_session_info_db() -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS session_cache (
                    type TEXT NOT NULL,
                    id INTEGER NOT NULL,
                    PRIMARY KEY (type, id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS group_info (
                    group_id INTEGER PRIMARY KEY,
                    group_name TEXT,
                    member_count INTEGER
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS friend_info (
                    user_id INTEGER PRIMARY KEY,
                    nickname TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS session_activity (
                    session_type TEXT NOT NULL,
                    session_id INTEGER NOT NULL,
                    has_at_me INTEGER DEFAULT 0,
                    last_open_time INTEGER DEFAULT 0,
                    last_chat_time INTEGER DEFAULT 0,
                    PRIMARY KEY (session_type, session_id)
                )
                """
            )
            cursor = await db.execute(
                """
                SELECT type, id
                FROM session_cache
                """
            )
            rows = await cursor.fetchall()
            _session_cache_memory.clear()
            _session_cache_memory.update((row[0], row[1]) for row in rows)
            await db.commit()

async def get_group_info(group_id: int) -> dict:
    async with _connect_session_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                group_name,
                member_count
            FROM group_info
            WHERE group_id = ?
            """,
            (group_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_friend_info(user_id: int) -> dict:
    async with _connect_session_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT nickname
            FROM friend_info
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_session_activity(session: dict) -> dict:
    async with _connect_session_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                last_open_time,
                last_chat_time,
                has_at_me
            FROM session_activity
            WHERE session_type = ?
              AND session_id = ?
            """,
            (
                session["type"],
                session["id"]
            )
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_session_cache() -> list[dict]:
    async with _connect_session_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT type, id
            FROM session_cache
            ORDER BY type, id
            """
        )
        rows = await cursor.fetchall()
        return [{"type": row["type"], "id": row["id"]} for row in rows]

async def cache_session(session: dict) -> None:
    session_key = (session["type"], session["id"])
    if session_key in _session_cache_memory:
        return
    async with _session_db_write_lock:
        if session_key in _session_cache_memory:
            return
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO session_cache (type, id)
                VALUES (?, ?)
                ON CONFLICT(type, id) DO NOTHING
                """,
                session_key
            )
            await db.commit()
        _session_cache_memory.add(session_key)

async def refresh_session_cache(session_list: list[dict]) -> None:
    session_keys = {(session["type"], session["id"]) for session in session_list}
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute("DELETE FROM session_cache")
            # if session_list:
            if session_keys:
                await db.executemany(
                    """
                    INSERT INTO session_cache (type, id)
                    VALUES (?, ?)
                    """,
                    # ON CONFLICT(type, id) DO NOTHING
                    # [(session["type"], session["id"]) for session in session_list]
                    session_keys
                )
            await db.commit()
        _session_cache_memory.clear()
        _session_cache_memory.update(session_keys)

async def update_group_info(group_id: int, group_name: str, member_count: int) -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO group_info (
                    group_id,
                    group_name,
                    member_count
                )
                VALUES (?, ?, ?)
                ON CONFLICT(group_id)
                DO UPDATE SET
                    group_name = excluded.group_name,
                    member_count = excluded.member_count
                """,
                (
                    group_id,
                    group_name,
                    member_count
                )
            )
            await db.commit()

async def update_friend_info(user_id: int, nickname: str) -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO friend_info (
                    user_id,
                    nickname
                )
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET nickname = excluded.nickname
                """,
                (
                    user_id,
                    nickname
                )
            )
            await db.commit()

async def update_session_open_time(session: dict, last_open_time: int) -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO session_activity (
                    session_type,
                    session_id,
                    last_open_time
                )
                VALUES (?, ?, ?)
                ON CONFLICT(session_type, session_id)
                DO UPDATE SET
                    last_open_time = excluded.last_open_time
                """,
                (
                    session["type"],
                    session["id"],
                    last_open_time
                )
            )
            await db.commit()

async def update_session_chat_time(session: dict, last_chat_time: int) -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO session_activity (
                    session_type,
                    session_id,
                    last_chat_time
                )
                VALUES (?, ?, ?)
                ON CONFLICT(session_type, session_id)
                DO UPDATE SET
                    last_chat_time = excluded.last_chat_time
                """,
                (
                    session["type"],
                    session["id"],
                    last_chat_time
                )
            )
            await db.commit()

async def update_session_at_me(session: dict, has_at_me: bool) -> None:
    async with _session_db_write_lock:
        async with _connect_session_db() as db:
            await db.execute(
                """
                INSERT INTO session_activity (
                    session_type,
                    session_id,
                    has_at_me
                )
                VALUES (?, ?, ?)
                ON CONFLICT(session_type, session_id)
                DO UPDATE SET
                    has_at_me = excluded.has_at_me
                """,
                (
                    session["type"],
                    session["id"],
                    int(has_at_me)
                )
            )
            await db.commit()


_msg_db_write_lock = asyncio.Lock()

_inited_msg_tables: set[str] = set()

def _connect_msg_db() -> aiosqlite.Connection:
    """
    创建 message.db 连接。

    timeout 会传递给 sqlite3.connect，
    当数据库暂时被其他连接占用时最多等待 30 秒，
    而不是立即抛出 database is locked。
    """
    return aiosqlite.connect(
        chat_cfg["message_db_path"],
        timeout=30.0
    )

async def _init_group_msg_table(db: aiosqlite.Connection, group_id: int) -> None:
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS group_{group_id} (
            id INTEGER PRIMARY KEY,
            time INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            nickname TEXT,
            content TEXT,
            image_data TEXT,
            from_me INTEGER DEFAULT 0,
            read_state INTEGER DEFAULT 0
        )
        """
    )

async def _init_friend_msg_table(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS friend_{user_id} (
            id INTEGER PRIMARY KEY,
            time INTEGER,
            message_id INTEGER,
            content TEXT,
            image_data TEXT,
            from_me INTEGER DEFAULT 0,
            read_state INTEGER DEFAULT 0
        )
        """
    )

async def _init_msg_table(session: dict) -> None:
    """
    确保某个消息表在本进程生命周期中完成初始化。

    第一次访问时执行 CREATE TABLE，
    后续读取和写入不再执行 DDL。
    """
    table = f"{session['type']}_{session['id']}"
    if table in _inited_msg_tables:
        return
    async with _msg_db_write_lock:
        # 等锁期间可能已经由另一个协程初始化。
        if table in _inited_msg_tables:
            return
        async with _connect_msg_db() as db:
            match session['type']:
                case "group":
                    await _init_group_msg_table(db, session["id"])
                case "friend":
                    await _init_friend_msg_table(db, session["id"])
                case _:
                    raise ValueError(f"Unsupported message table type: {session['type']}")
            await db.commit()
        _inited_msg_tables.add(table)

async def init_message_db() -> None:
    """
    初始化 message.db 的数据库级配置。

    WAL 允许 reader 与 writer 更好地并行工作。
    Python 进程内部的多个 writer 仍然由
    _msg_db_write_lock 串行化。
    """
    async with _msg_db_write_lock:
        async with _connect_msg_db() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()

async def cleanup_msg(db: aiosqlite.Connection, table_name: str) -> None:
    db.row_factory = aiosqlite.Row
    cursor = await db.execute(
        f"""
        SELECT id, image_data
        FROM {table_name}
        WHERE id NOT IN (
            SELECT id
            FROM {table_name}
            ORDER BY id DESC
            LIMIT ?
        )
        """,
        (chat_cfg["max_msg_reserve_num"],)
    )
    rows = await cursor.fetchall()
    if not rows:
        return
    for row in rows:
        image_data = json.loads(row["image_data"])
        for image in image_data:
            await delete_temp_image(image)
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    await db.execute(
        f"""
        DELETE FROM {table_name}
        WHERE id IN ({placeholders})
        """,
        ids
    )

async def record_received_group_msg(group_id: int, message: dict) -> None:
    await _init_msg_table({"type": "group", "id": group_id})
    async with _msg_db_write_lock:
        async with _connect_msg_db() as db:
            await db.execute(
                f"""
                INSERT INTO group_{group_id} (
                    time,
                    message_id,
                    user_id,
                    nickname,
                    content,
                    image_data
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message["time"],
                    message["message_id"],
                    message["user_id"],
                    message["nickname"],
                    message["content"],
                    message["image_data"]
                )
            )
            await cleanup_msg(db, f"group_{group_id}")
            await db.commit()

async def record_received_friend_msg(user_id: int, message: dict) -> None:
    await _init_msg_table({"type": "friend", "id": user_id})
    async with _msg_db_write_lock:
        async with _connect_msg_db() as db:
            await db.execute(
                f"""
                INSERT INTO friend_{user_id} (
                    time,
                    message_id,
                    content,
                    image_data
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    message["time"],
                    message["message_id"],
                    message["content"],
                    message["image_data"]
                )
            )
            await cleanup_msg(db, f"friend_{user_id}")
            await db.commit()

async def record_self_msg(session: dict, message: dict) -> None:
    await _init_msg_table({"type": session["type"], "id": session["id"]})
    async with _msg_db_write_lock:
        async with _connect_msg_db() as db:
            await db.execute(
                f"""
                INSERT INTO {session["type"]}_{session["id"]} (
                    time,
                    message_id,
                    content,
                    image_data,
                    from_me,
                    read_state
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message["time"],
                    message["message_id"],
                    message["content"],
                    "[]",
                    1,
                    1
                )
            )
            await cleanup_msg(db, f"{session['type']}_{session['id']}")
            await db.commit()

async def get_group_msg_list(group_id: int) -> dict:
    await _init_msg_table({"type": "group", "id": group_id})
    async with _connect_msg_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                user_id,
                nickname,
                content,
                image_data,
                from_me,
                read_state
            FROM group_{group_id}
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_cfg["max_msg_provide_num"],)
        )
        rows = await cursor.fetchall()
    rows = reversed(rows)
    msg_list = [dict(row) for row in rows]
    read_msg = []
    unread_msg = []
    for msg in msg_list:
        match msg["read_state"]:
            case 0:
                unread_msg.append(msg)
            case 1:
                read_msg.append(msg)
    return {
        "read_msg": read_msg,
        "unread_msg": unread_msg
    }

async def get_friend_msg_list(user_id: int) -> dict:
    await _init_msg_table({"type": "friend", "id": user_id})
    async with _connect_msg_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                content,
                image_data,
                from_me,
                read_state
            FROM friend_{user_id}
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_cfg["max_msg_provide_num"],)
        )
        rows = await cursor.fetchall()
    rows = reversed(rows)
    msg_list = [dict(row) for row in rows]
    read_msg = []
    unread_msg = []
    for msg in msg_list:
        match msg["read_state"]:
            case 0:
                unread_msg.append(msg)
            case 1:
                read_msg.append(msg)
    return {
        "read_msg": read_msg,
        "unread_msg": unread_msg
    }

async def update_msg_read_status(session: dict, message_id_list: list) -> None:
    if not message_id_list:
        return
    await _init_msg_table({"type": session["type"], "id": session["id"]})
    placeholders = ",".join("?" for _ in message_id_list)
    async with _msg_db_write_lock:
        async with _connect_msg_db() as db:
            await db.execute(
                f"""
                UPDATE {session["type"]}_{session["id"]}
                SET read_state = 1
                WHERE message_id IN ({placeholders})
                """,
                message_id_list
            )
            await db.commit()

async def get_latest_group_msg(group_id: int) -> dict:
    await _init_msg_table({"type": "group", "id": group_id})
    async with _connect_msg_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                user_id,
                nickname,
                content,
                image_data,
                from_me,
                read_state
            FROM group_{group_id}
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def get_latest_friend_msg(user_id: int) -> dict:
    await _init_msg_table({"type": "friend", "id": user_id})
    async with _connect_msg_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                time,
                message_id,
                content,
                image_data,
                from_me,
                read_state
            FROM friend_{user_id}
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}


async def init_memory_db() -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_impression (
                group_id INTEGER PRIMARY KEY,
                impression TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id INTEGER PRIMARY KEY,
                portrait TEXT,
                memory TEXT,
                impression TEXT
            )
            """
        )
        await db.commit()

async def get_group_impression(group_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT impression
            FROM group_impression
            WHERE group_id = ?
            """,
            (group_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def get_user_list_in_memory() -> list[int]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT user_id
            FROM user_memory
            ORDER BY user_id
            """
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_user_impression(user_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT impression
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def get_user_memory(user_id: int) -> list[dict]:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT memory
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []

async def get_user_portrait(user_id: int) -> str:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        cursor = await db.execute(
            """
            SELECT portrait
            FROM user_memory
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else ""

async def get_user_all_memory(user_list: list[int]) -> list[dict]:
    if not user_list:
        return []
    placeholders = ", ".join("?" for _ in user_list)
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT
                user_id,
                impression,
                memory,
                portrait
            FROM user_memory
            WHERE user_id IN ({placeholders})
            ORDER BY user_id
            """,
            user_list
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row["user_id"],
                "portrait": row["portrait"] or "",
                "memory": json.loads(row["memory"]) if row["memory"] else [],
                "impression": json.loads(row["impression"]) if row["impression"] else []
            }
            for row in rows
        ]

async def update_group_impression(group_id: int, new_impression: list[dict], overwrite: bool) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        if overwrite:
            impression = new_impression
        else:
            cursor = await db.execute(
                """
                SELECT impression
                FROM group_impression
                WHERE group_id = ?
                """,
                (group_id,)
            )
            row = await cursor.fetchone()
            impression = json.loads(row[0]) if row and row[0] else []
            impression.extend(new_impression)
        await db.execute(
            """
            INSERT INTO group_impression (group_id, impression)
            VALUES (?, ?)
            ON CONFLICT(group_id)
            DO UPDATE SET impression = excluded.impression
            """,
            (group_id, json.dumps(impression, ensure_ascii=False))
        )
        await db.commit()

async def update_user_impression(user_id: int, new_impression: list[dict], overwrite: bool) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        if overwrite:
            impression = new_impression
        else:
            cursor = await db.execute(
                """
                SELECT impression
                FROM user_memory
                WHERE user_id = ?
                """,
                (user_id,)
            )
            row = await cursor.fetchone()
            impression = json.loads(row[0]) if row and row[0] else []
            impression.extend(new_impression)
        await db.execute(
            """
            INSERT INTO user_memory (user_id, impression)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET impression = excluded.impression
            """,
            (user_id, json.dumps(impression, ensure_ascii=False))
        )
        await db.commit()

async def update_user_all_memory(user_id: int, new_portrait: str, new_memory: list[dict]) -> None:
    async with aiosqlite.connect(chat_cfg["memory_db_path"]) as db:
        await db.execute(
            """
            UPDATE user_memory
            SET
                portrait = ?,
                memory = ?,
                impression = ?
            WHERE user_id = ?
            """,
            (
                new_portrait,
                json.dumps(new_memory, ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                user_id
            )
        )
        await db.commit()


async def init_status_snapshot() -> None:
    async with aiosqlite.connect(debug_status_snapshot["db_path"]) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                changes TEXT NOT NULL
            )
            """
        )
        await db.commit()

async def take_status_snapshot(status: str, changes: str) -> None:
    async with aiosqlite.connect(debug_status_snapshot["db_path"]) as db:
        await db.execute(
            """
            INSERT INTO snapshot (status, changes)
            VALUES (?, ?)
            """,
            (status, changes)
        )
        await db.execute(
            """
            DELETE FROM snapshot
            WHERE id NOT IN (
                SELECT id
                FROM snapshot
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (debug_status_snapshot["snapshot_max_rows"],)
        )
        await db.commit()