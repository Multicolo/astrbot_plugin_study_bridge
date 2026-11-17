"""独立运行模式：不依赖 AstrBot 也能起服务，用于本地调试与 E2E。

用法::

    python -m core.standalone --data-dir ./data --port 6188 --print-token
    python scripts/standalone.py --data-dir ./data

它会：
1. 建库 + 跑迁移；
2. 起 HTTP 服务（``/study/`` 静态页 + ``/api/study/*``）；
3. 起调度器（没有真实平台时推送会失败并如实记录，不影响其它功能）；
4. 打印一个可直接用的 Bearer 令牌（仅限本地调试，生产不要用这个模式）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # 允许直接 python core/standalone.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .app import PLUGIN_NAME, StudyApp  # noqa: E402
from .config import Settings  # noqa: E402
from .http_server import HttpServer  # noqa: E402
from .principal import get_or_create, issue_token  # noqa: E402
from .scheduler import Scheduler  # noqa: E402


async def serve(
    *,
    data_dir: Path,
    host: str | None,
    port: int | None,
    print_token: bool,
    config: dict[str, Any] | None = None,
) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    raw = dict(config or {})
    if host:
        raw.setdefault("http", {})["host"] = host
    if port:
        raw.setdefault("http", {})["port"] = port
    cfg = Settings(raw)
    app = StudyApp(data_dir=data_dir, cfg=cfg, context=None, astrbot_version="standalone")

    async def sender(umo: str, text: str) -> bool:
        # 没有平台时把消息写到日志，方便本地验证调度是否触发
        app.logger.info("[standalone push] %s -> %s", umo, text)
        return False

    app.sender = sender
    await app.startup()
    http = HttpServer(app)
    try:
        await http.start()
    except OSError as exc:
        print(f"HTTP 启动失败：{exc}", file=sys.stderr)
        await app.shutdown()
        return 2
    scheduler = Scheduler(app)
    scheduler.start()

    if print_token:
        principal = await get_or_create(
            app.db, kind="owner", external_id="standalone", display_name="本地调试"
        )
        token, _ = await issue_token(app.db, principal_id=principal.id, label="standalone")
        base = f"http://127.0.0.1:{http.bound_port}"
        print("\n==== 本地调试 ====", flush=True)
        print(f"网页：      {base}/study/", flush=True)
        print(f"健康检查：  {base}/api/study/health", flush=True)
        print(f"Bearer：    {token}", flush=True)
        print(f"数据目录：  {data_dir.resolve()}", flush=True)
        print("==================\n", flush=True)

    print(f"{PLUGIN_NAME} 已启动，Ctrl+C 退出")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await scheduler.stop()
        await http.stop()
        await app.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习桥梁独立调试服务")
    parser.add_argument("--data-dir", default="data", help="数据目录（默认 ./data）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=6188, help="监听端口（默认 6188）")
    parser.add_argument("--print-token", action="store_true", help="打印一个调试用令牌")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(
            serve(
                data_dir=Path(args.data_dir),
                host=args.host,
                port=args.port,
                print_token=args.print_token,
            )
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
