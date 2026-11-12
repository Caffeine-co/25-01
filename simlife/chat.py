"""最小聊天演示：不负责真的发消息到第三方平台。"""
from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_scenario
from .store import SQLiteStore
from .cognition import CognitionService, OfflineBackend, OpenAICompatibleBackend


def main():
    p = argparse.ArgumentParser(description="单次角色语言交互示例")
    p.add_argument("scenario", type=Path)
    p.add_argument("--db", type=Path, default=Path("data/chat.db"))
    p.add_argument("--actor", required=True)
    p.add_argument("--from", dest="author", default="user")
    p.add_argument("--message", required=True)
    p.add_argument("--provider", choices=["offline", "remote"], default="offline")
    p.add_argument("--max-calls", type=int, default=4)
    args = p.parse_args()
    backend = OpenAICompatibleBackend.from_env() if args.provider == "remote" else OfflineBackend()
    with SQLiteStore(args.db) as store:
        world = store.load_or_create(load_scenario(args.scenario))
        # 先把初始化时刻的待决策事件执行完，避免外部消息与旧唤醒相互竞争。
        world.run_until(world.minute)
        reply = CognitionService(backend, args.max_calls).interact(
            world, args.actor, args.author, args.message)
        store.save(world)
    print("人物回复：", reply.text)
    print("模型已调用：", reply.model_used,
          "| 建议动作已接收：", reply.action_accepted,
          "| 原因：", reply.reason)


if __name__ == "__main__":
    main()
