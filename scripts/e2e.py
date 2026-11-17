#!/usr/bin/env python3
"""端到端测试启动器：不需要 AstrBot，直接把插件当独立服务跑起来再跑 Playwright。

做的事：
1. 建一个临时数据目录（默认 .e2e-data，可用 --data-dir 覆盖）
2. 种测试数据：owner 主体 + 令牌、今日任务、已写入的计划、记忆、bot 记忆、推送目标
3. 起 HTTP 服务（默认 127.0.0.1:6199）
4. 用 node 跑 ``pnpm test:e2e``，把 STUDY_BASE / STUDY_TOKEN 传进去
5. 退出码透传

用法::

    python scripts/e2e.py
    python scripts/e2e.py --node "C:/path/node.exe" --pnpm "C:/path/pnpm.mjs" --project desktop
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app import StudyApp  # noqa: E402
from core.config import Settings  # noqa: E402
from core.http_server import HttpServer  # noqa: E402
from core.llm import LLMClient  # noqa: E402
from core.principal import get_or_create, issue_token  # noqa: E402
from core.util import get_tz, iso, local_date  # noqa: E402


class StubLLM(LLMClient):
    """E2E 用：不真调模型，固定回一句结构化答复。"""

    async def available(self) -> bool:
        return True

    async def reload(self) -> None:
        await super().reload()

    async def complete(self, prompt: str, *, system=None, timeout=None, json_mode=False) -> str:
        if '"items"' in prompt:
            today = local_date("Asia/Shanghai")
            return (
                '{"title":"E2E 计划 临期复习","items":['
                f'{{"seq":1,"title":"E2E 第一章","scheduled_date":"{today.isoformat()}","duration_min":30}}'
                "]}"
            )
        return '{"reply":"好的，我在。","tool_calls":[]}'


async def seed(app: StudyApp) -> str:
    principal = await get_or_create(app.db, kind="owner", external_id="e2e", display_name="E2E")
    token, _ = await issue_token(app.db, principal_id=principal.id, label="e2e")

    tz = get_tz("Asia/Shanghai")
    start = datetime.combine(local_date(tz), datetime.min.time(), tzinfo=tz).replace(hour=15)
    await app.tasks.create(
        principal,
        {
            "title": "E2E 今日任务：背单词",
            "start_at": iso(start),
            "end_at": iso(start + timedelta(hours=1)),
        },
    )
    await app.memories.save_note(
        principal, kind="preference", content="E2E 偏好：喜欢在图书馆学习", importance=4
    )
    await app.db.execute(
        "INSERT INTO bot_memory_mirror (remote_ref, owner_principal_id, content, tags, importance, "
        "source_ref, origin, adopted, remote_updated_at, synced_at) "
        "VALUES ('e2e-bot-1', ?, 'E2E bot 记忆：下周三有高数考试', '[]', 3, NULL, 'bot', 0, NULL, ?)",
        (principal.id, iso(datetime.now(tz))),
    )
    await app.notify.add_target(principal, umo="qq:FriendMessage:20001", alias="E2E 私聊")

    plan_id = "e2e-plan-1"
    today = local_date(tz)
    await app.db.execute(
        "INSERT INTO plan (id, owner_principal_id, title, goal, deadline, daily_minutes, status, "
        "origin_session_id, applied_at, created_at) VALUES (?, ?, 'E2E 计划 临期复习', 'E2E 目标', ?, 60, "
        "'active', NULL, NULL, ?)",
        (plan_id, principal.id, (today + timedelta(days=3)).isoformat(), iso(datetime.now(tz))),
    )
    await app.db.execute(
        "INSERT INTO plan_item (id, owner_principal_id, plan_id, seq, title, scheduled_date, "
        "duration_min, task_id, status) VALUES ('e2e-item-1', ?, ?, 1, 'E2E 第一章', ?, 30, NULL, 'pending')",
        (principal.id, plan_id, (today + timedelta(days=1)).isoformat()),
    )
    return token


async def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    if data_dir.exists() and args.clean:
        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        {
            "http": {
                "enabled": True,
                "host": args.host,
                "port": args.port,
                # 测试里同一个 IP 会发很多请求，抬高上限避免撞限流
                "rate_limit_per_minute": 5000,
                "auth_fail_limit_per_minute": 500,
            }
        }
    )
    app = StudyApp(data_dir=data_dir, cfg=settings, context=None, astrbot_version="e2e")
    app.llm = StubLLM(app)
    app.sender = None
    await app.startup()
    token = await seed(app)
    http = HttpServer(app)
    await http.start()
    base = f"http://{args.host}:{args.port}"

    env = dict(os.environ)
    env["STUDY_BASE"] = base
    env["STUDY_TOKEN"] = token
    # Playwright 会往 TEMP 写 transform cache；某些环境 TEMP 不可写，这里改到工作目录下
    tmp_dir = ROOT / ".e2e-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    node_bin = args.node or "node"
    cli = ROOT / "frontend" / "node_modules" / "@playwright" / "test" / "cli.js"
    if not cli.exists():
        print("[e2e] 找不到 @playwright/test，请先 cd frontend && pnpm install", flush=True)
        await http.stop()
        await app.shutdown()
        return 3
    command = [node_bin, str(cli), "test", "--reporter=list"]
    if args.project:
        command += [f"--project={args.project}"]

    print(f"[e2e] 服务已启动：{base}/study/ （数据目录 {data_dir}）", flush=True)
    print(f"[e2e] 执行：{' '.join(command)}", flush=True)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT / "frontend"),
            env=env,
        )
        code = await process.wait()
    finally:
        await http.stop()
        await app.shutdown()
    print(f"[e2e] Playwright 退出码：{code}", flush=True)
    return int(code)


def main() -> int:
    parser = argparse.ArgumentParser(description="学习桥梁 E2E")
    parser.add_argument("--data-dir", default=str(ROOT / ".e2e-data"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6199)
    parser.add_argument("--node", default=os.environ.get("NODE_BIN", ""))
    parser.add_argument("--project", default="", help="desktop / mobile")
    parser.add_argument("--keep", action="store_true", help="保留上次的数据目录")
    args = parser.parse_args()
    args.clean = not args.keep
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
