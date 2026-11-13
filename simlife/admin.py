"""离线维护工具。必须停止对应服务后才允许运行迁移或直接操作数据库。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .store import SQLiteStore
from .config import load_scenario


def main():
    parser=argparse.ArgumentParser(description='WorldLife 存档维护')
    sub=parser.add_subparsers(dest='command',required=True)
    backup=sub.add_parser('backup',help='SQLite 在线一致性备份')
    backup.add_argument('--db',required=True)
    backup.add_argument('--out',required=True)
    inspect=sub.add_parser('inspect',help='查看存档版本及世界时间，需要当前规则场景')
    inspect.add_argument('scenario');inspect.add_argument('--db',required=True)
    args=parser.parse_args()
    with SQLiteStore(args.db) as store:
        if args.command=='backup':
            print(store.backup(args.out))
        else:
            w=store.load_or_create(load_scenario(args.scenario))
            print(json.dumps({'minute':w.minute,'revision':w._store_revision,
                              'world':w.scenario.world.id,'actors':sorted(w.lives),
                              'resources':w.resources,'events':store.count_events()},
                             ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
