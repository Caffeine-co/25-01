"""零第三方依赖的单机 HTTP 接口。

所有访问（含读取）都需要 Bearer Token；默认仅监听 127.0.0.1。
如需跨机服务，请使用 HTTPS 反向代理并做网络访问控制，勿直接暴露 HTTP。
"""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
from threading import Event, Thread
import time
from urllib.parse import parse_qs, urlparse

from .cognition import OpenAICompatibleBackend
from .service import RuntimeService
from .store import RequestConflict, RevisionConflict

MAX_BODY = 20_000
ROUTES = {"/v1/advance": "advance", "/v1/chat": "chat",
          "/v1/reflect": "reflect", "/v1/project": "project",
          "/v1/project/cancel": "cancel_project", "/v1/claim": "claim",
          "/v1/intent": "intent"}


def handler_factory(service: RuntimeService, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WorldLife/2.0"

        def log_message(self, format: str, *args) -> None:
            # 不能将 Authorization 或请求正文打印到日志。
            super().log_message(format, *args)

        def _json(self, status: int, body: dict | list) -> None:
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            provided = self.headers.get("Authorization", "")
            if not secrets.compare_digest(provided, "Bearer " + token):
                self._json(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path)
            query = parse_qs(path.query)
            try:
                if path.path == "/v1/health":
                    data = {"ok": True, "version": "2.0", "minute": service.state()["minute"]}
                elif path.path == "/v1/state":
                    data = service.state(query.get("actor", [None])[0])
                elif path.path == "/v1/events":
                    data = service.events(int(query.get("limit", [20])[0]))
                else:
                    self._json(404, {"error": "not_found"})
                    return
                self._json(200, data)
            except (TypeError, ValueError) as exc:
                self._json(400, {"error": "invalid_request", "reason": str(exc)})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            route = urlparse(self.path).path
            if route not in ROUTES:
                self._json(404, {"error": "not_found"})
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or not 1 <= int(length) <= MAX_BODY:
                self._json(413, {"error": "invalid_body_length"})
                return
            try:
                body = json.loads(self.rfile.read(int(length)))
                result = service.mutate(ROUTES[route], body,
                                        self.headers.get("Idempotency-Key", ""))
                self._json(200, result)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                status = 409 if isinstance(exc, RequestConflict) else 400
                self._json(status, {"error": type(exc).__name__, "reason": str(exc)[:300]})
            except RevisionConflict as exc:
                self._json(409, {"error": "revision_conflict", "reason": str(exc)})
            except Exception:
                # 服务内部错误不泄露堆栈、密钥或数据库路径。
                self._json(500, {"error": "internal_error"})

    return Handler


class AutoTicker:
    """以真实时间推进模拟。重启期间的时间不补算（避免停机后事件风暴）。"""
    def __init__(self, service: RuntimeService, period: float = 5,
                 sim_minutes_per_real_second: float = 1 / 60,
                 reflect_daily: bool = False):
        if period <= 0 or not 0 < sim_minutes_per_real_second <= 10:
            raise ValueError("时钟周期或加速倍率非法")
        self.service, self.period = service, period
        self.rate = sim_minutes_per_real_second
        self.reflect_daily = reflect_daily
        self.stop = Event()
        self.thread: Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("时钟已启动")
        self.thread = Thread(target=self._run, name="worldlife-clock", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        last = time.monotonic()
        carry = 0.0
        while not self.stop.wait(self.period):
            now = time.monotonic()
            # 限制系统冻结/暂停后的单次补算规模。
            carry += min(now - last, 60) * self.rate
            last = now
            minutes, carry = int(carry), carry % 1
            if minutes:
                try:
                    old_day = self.service.state()["minute"] // 1440
                    self.service.advance_internal(minutes)
                    new_day = self.service.state()["minute"] // 1440
                    if self.reflect_daily and new_day != old_day:
                        for actor in self.service.state()["actors"]:
                            # 反思调用位于服务层，不在 WorldRuntime 事件队列里。
                            request_id = f"auto-reflect:{actor}:{new_day}"
                            self.service.mutate("reflect", {"actor": actor}, request_id)
                except Exception as exc:
                    # 不吞没异常并无限重试：严重故障停止时钟，等待运维处理。
                    print(f"[worldlife-clock] stopped: {type(exc).__name__}: {exc}", flush=True)
                    self.stop.set()

    def shutdown(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="WorldLife 本地认证 HTTP 服务")
    parser.add_argument("scenario")
    parser.add_argument("--db", default="data/production.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--provider", choices=["offline", "remote"], default="offline")
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--tick-seconds", type=float, default=5.0)
    parser.add_argument("--sim-minutes-per-second", type=float, default=1 / 60)
    parser.add_argument("--no-auto-time", action="store_true")
    parser.add_argument("--reflect-daily", action="store_true")
    args = parser.parse_args()
    token = os.getenv("WORLDLIFE_SERVER_TOKEN", "")
    if len(token) < 24:
        parser.error("设置 WORLDLIFE_SERVER_TOKEN（至少 24 字符）")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("拒绝公网 HTTP 监听；请通过 localhost + HTTPS 反向代理部署")
    backend = OpenAICompatibleBackend.from_env() if args.provider == "remote" else None
    service = RuntimeService(args.scenario, args.db, backend=backend,
                             max_calls_per_day=args.max_calls)
    ticker = AutoTicker(service, period=args.tick_seconds,
                        sim_minutes_per_real_second=args.sim_minutes_per_second,
                        reflect_daily=args.reflect_daily) if not args.no_auto_time else None
    server = ThreadingHTTPServer((args.host, args.port), handler_factory(service, token))
    try:
        if ticker:
            ticker.start()
        print(f"WorldLife 2.0 listening on {args.host}:{args.port}", flush=True)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ticker:
            ticker.shutdown()
        service.close()


if __name__ == "__main__":
    main()
