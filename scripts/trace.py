"""按模拟时间查询审计事件，方便沿真实行为流逐条理解。"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description='浏览 WorldLife SQLite 事件')
    p.add_argument('db', type=Path)
    p.add_argument('--from-minute', type=int, default=0)
    p.add_argument('--to-minute', type=int, default=10**9)
    p.add_argument('--actor', default=None)
    p.add_argument('--limit', type=int, default=200)
    args = p.parse_args()
    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro', uri=True) as con:
        sql = ('SELECT minute,type,actor,details_json FROM events '
               'WHERE minute BETWEEN ? AND ? ')
        params = [args.from_minute, args.to_minute]
        if args.actor:
            sql += 'AND actor = ? '
            params.append(args.actor)
        sql += 'ORDER BY id LIMIT ?'
        params.append(args.limit)
        for minute, event, actor, details in con.execute(sql, params):
            parsed = json.loads(details)
            print(f't={minute:>6} | {event:<22} | {(actor or "-"):<15} | '
                  f'{json.dumps(parsed, ensure_ascii=False)}')

if __name__ == '__main__':
    main()
