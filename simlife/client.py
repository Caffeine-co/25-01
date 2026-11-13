"""可交互使用的 HTTP CLI 客户端：通过受保护接口操作正在运行的世界。"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4


def call(base: str, token: str, method: str, path: str, data: dict | None = None) -> dict | list:
    if not (base.startswith('http://127.0.0.1:') or
            base.startswith('http://localhost:') or base.startswith('https://')):
        raise ValueError('只允许本地 HTTP 或 HTTPS 远端服务')
    payload = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    request = Request(base.rstrip('/') + path, data=payload, method=method,
                      headers={'Authorization':'Bearer '+token,
                               'Content-Type':'application/json',
                               'Idempotency-Key':str(uuid4())})
    try:
        with urlopen(request, timeout=30) as resp:
            return json.loads(resp.read(2_000_000))
    except HTTPError as ex:
        body=ex.read(3000).decode('utf-8',errors='replace')
        raise ValueError(f'HTTP {ex.code}: {body}') from ex


def main() -> None:
    parser = argparse.ArgumentParser(description='连接 WorldLife 正在运行的本地服务')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    actor_state=sub.add_parser('actor');actor_state.add_argument('actor')
    ev=sub.add_parser('events');ev.add_argument('--limit',type=int,default=20)
    advance=sub.add_parser('advance');advance.add_argument('minutes',type=int)
    chat=sub.add_parser('chat');chat.add_argument('actor');chat.add_argument('message');chat.add_argument('--author',default='user')
    refl=sub.add_parser('reflect');refl.add_argument('actor')
    project=sub.add_parser('project');project.add_argument('actor');project.add_argument('json_file')
    cancel=sub.add_parser('cancel');cancel.add_argument('actor');cancel.add_argument('project_id')
    args=parser.parse_args()
    token=os.environ.get('WORLDLIFE_SERVER_TOKEN','')
    if not token:
        parser.error('请先设置 WORLDLIFE_SERVER_TOKEN 环境变量')
    if args.command=='status':
        out=call(args.url,token,'GET','/v1/state')
    elif args.command=='actor':
        from urllib.parse import quote
        out=call(args.url,token,'GET','/v1/state?actor='+quote(args.actor))
    elif args.command=='events':
        out=call(args.url,token,'GET',f'/v1/events?limit={args.limit}')
    else:
        routes={'advance':'/v1/advance','chat':'/v1/chat','project':'/v1/project',
                'cancel':'/v1/project/cancel','reflect':'/v1/reflect'}
        if args.command=='advance':body={'minutes':args.minutes}
        elif args.command=='chat':body={'actor':args.actor,'author':args.author,'message':args.message}
        elif args.command=='project':body={'actor':args.actor,'project':json.loads(Path(args.json_file).read_text(encoding='utf-8'))}
        elif args.command=='cancel':body={'actor':args.actor,'project_id':args.project_id}
        else:body={'actor':args.actor}
        out=call(args.url,token,'POST',routes[args.command],body)
    print(json.dumps(out,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
