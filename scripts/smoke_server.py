"""真实启动 WorldLife 服务子进程，检查认证状态、聊天、项目、手动推进和重启。

只连接本机，不使用云服务和密钥；临时数据库不污染正式 data/。
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def http(url: str, token: str, payload: dict | None = None, key: str | None = None) -> dict:
    import json
    headers={'Authorization':'Bearer '+token}
    if payload is not None:
        headers.update({'Content-Type':'application/json','Idempotency-Key':key or 'smoke-request'})
    request=Request(url, data=json.dumps(payload).encode('utf-8') if payload is not None else None,
                    headers=headers,method='POST' if payload is not None else 'GET')
    with urlopen(request,timeout=2) as response:
        return json.loads(response.read())


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'smoke.db'
        server_port=port()
        url=f'http://127.0.0.1:{server_port}/v1'
        env={**os.environ,'WORLDLIFE_SERVER_TOKEN':'worldlife-smoke-token-'+'a'*40}
        cmd=[sys.executable,'-m','simlife.server',
             'examples/scenarios/art_project.json','--db',str(db),
             '--port',str(server_port),'--no-auto-time']
        def spawn():
            process=subprocess.Popen(cmd,cwd=ROOT,env=env,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('服务启动失败，进程提前退出')
                try:
                    reply=http(url+'/health',env['WORLDLIFE_SERVER_TOKEN'])
                    if reply['ok']:
                        return process
                except OSError:
                    time.sleep(.03)
            raise RuntimeError('服务无响应')
        process=spawn()
        try:
            health=http(url+'/health',env['WORLDLIFE_SERVER_TOKEN'])
            assert health['minute']==0
            result=http(url+'/advance',env['WORLDLIFE_SERVER_TOKEN'],{'minutes':120},'step-1')
            assert result['minute']==120
            result2=http(url+'/advance',env['WORLDLIFE_SERVER_TOKEN'],{'minutes':120},'step-1')
            assert result2==result
            chat=http(url+'/chat',env['WORLDLIFE_SERVER_TOKEN'],
                      {'actor':'resident_01','author':'tester','message':'Hello'},'chat-1')
            assert chat['model_used'] is False
            state=http(url+'/state?actor=resident_01',env['WORLDLIFE_SERVER_TOKEN'])
            assert 'art_portfolio' in state['projects']
        finally:
            process.terminate()
            process.wait(timeout=5)
        process=spawn()
        try:
            state=http(url+'/state',env['WORLDLIFE_SERVER_TOKEN'])
            assert state['minute']==120
            assert http(url+'/advance',env['WORLDLIFE_SERVER_TOKEN'],{'minutes':120},'step-1')==result
            assert http(url+'/state',env['WORLDLIFE_SERVER_TOKEN'])['minute']==120
        finally:
            process.terminate()
            process.wait(timeout=5)
    print('PASS: subprocess server / authenticated HTTP / idempotent retry / restart persistence')


if __name__=='__main__':
    main()
