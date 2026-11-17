#!/usr/bin/env python3
"""生成文档截图：起一个带种子数据的服务，用 Playwright 截图到 docs/images/。

用法::

    python scripts/shots.py
    python scripts/shots.py --node "C:/path/node.exe"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app import StudyApp  # noqa: E402
from core.config import Settings  # noqa: E402
from core.http_server import HttpServer  # noqa: E402

from scripts.e2e import StubLLM, seed  # noqa: E402

SHOT_SCRIPT = """
import { chromium } from '@playwright/test'

const token = process.env.STUDY_TOKEN
const base = process.env.STUDY_BASE
const outDir = process.env.SHOT_DIR

const pages = [
  ['setup', '/study/setup'],
  ['today', '/study/today'],
  ['plans', '/study/plans'],
  ['stats', '/study/stats'],
  ['memory', '/study/memory'],
]

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1280, height: 860 } })
await context.addInitScript((t) => {
  localStorage.setItem('study.token', t)
  localStorage.removeItem('study.server')
}, token)
const page = await context.newPage()
for (const [name, path] of pages) {
  await page.goto(base + path, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: false })
  console.log('shot', name)
}
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true })
await mobile.addInitScript((t) => localStorage.setItem('study.token', t), token)
const mpage = await mobile.newPage()
await mpage.goto(base + '/study/today', { waitUntil: 'networkidle' })
await mpage.waitForTimeout(700)
await mpage.screenshot({ path: `${outDir}/mobile-today.png` })
console.log('shot mobile-today')
await browser.close()
"""


async def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    if data_dir.exists():
        import shutil

        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_dir = ROOT / "docs" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings({"http": {"enabled": True, "host": "127.0.0.1", "port": args.port}})
    app = StudyApp(data_dir=data_dir, cfg=settings, context=None, astrbot_version="shots")
    app.llm = StubLLM(app)
    await app.startup()
    token = await seed(app)
    http = HttpServer(app)
    await http.start()
    try:
        # 脚本必须放在 frontend/ 下，node 才能从 frontend/node_modules 解析 playwright
        script = ROOT / "frontend" / ".shots.mjs"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(SHOT_SCRIPT, encoding="utf-8")
        env = dict(os.environ)
        env.update(
            {
                "STUDY_BASE": f"http://127.0.0.1:{args.port}",
                "STUDY_TOKEN": token,
                "SHOT_DIR": str(out_dir),
                "TEMP": str(script.parent),
                "TMP": str(script.parent),
            }
        )
        process = await asyncio.create_subprocess_exec(
            args.node, str(script), cwd=str(ROOT / "frontend"), env=env
        )
        return await process.wait()
    finally:
        await http.stop()
        await app.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default=os.environ.get("NODE_BIN", "node"))
    parser.add_argument("--port", type=int, default=6198)
    parser.add_argument("--data-dir", default=str(ROOT / ".shots-data"))
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
