#!/usr/bin/env python3
"""离线自检：没有 AstrBot 真机时，尽量把能验证的都验证掉。

检查项：
1. 关键文件齐全（metadata / conf_schema / web 构建产物）
2. metadata.yaml 必填字段与版本区间
3. _conf_schema.json 每一项都有中文 description + default
4. i18n 中英 key 完全一致
5. 建库 + 迁移 + 一个完整写入/读取链路
6. 记忆适配器在"什么都不装"的环境下正常降级
7. 密钥扫描

退出码 0 = 全通过；1 = 有失败项。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))


def read_metadata() -> dict[str, str]:
    """极简 metadata.yaml 解析（只支持 key: value 与多行块），避免依赖 pyyaml。"""
    text = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    data: dict[str, str] = {}
    key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if key and buffer:
            if data.get(key, "").strip() in ("|", ">", ""):
                data[key] = "\n".join(buffer).strip()
            else:
                data[key] = (data[key] + "\n" + "\n".join(buffer)).strip()
        buffer.clear()

    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t")):
            if key:
                buffer.append(raw_line.strip())
            continue
        flush()
        if ":" in raw_line and not raw_line.lstrip().startswith("#"):
            name, _, value = raw_line.partition(":")
            key = name.strip()
            data[key] = value.strip()
        else:
            key = None
    flush()
    return data


def check_files() -> None:
    required = [
        "main.py",
        "metadata.yaml",
        "_conf_schema.json",
        "requirements.txt",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "web/index.html",
        "core/http_server.py",
        "adapters/base.py",
        "i18n/zh-CN.json",
        "i18n/en-US.json",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    check(not missing, "关键文件齐全", "缺失：" + ", ".join(missing) if missing else "")


def check_metadata() -> None:
    data = read_metadata()
    for field in ("name", "desc", "version", "author"):
        if not data.get(field):
            check(False, f"metadata.{field}", "缺失")
            return
    check(data["name"] == "astrbot_plugin_study_bridge", "metadata.name 与仓库名一致", data["name"])
    check(
        bool(data.get("astrbot_version")),
        "metadata.astrbot_version 已声明",
        data.get("astrbot_version", ""),
    )


def check_conf_schema() -> None:
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    problems: list[str] = []

    def walk(items: dict, prefix: str = "") -> None:
        for key, value in items.items():
            path = f"{prefix}{key}"
            if not isinstance(value, dict):
                problems.append(f"{path} 不是对象")
                continue
            if "description" not in value:
                problems.append(f"{path} 缺 description")
            if value.get("type") == "object":
                walk(value.get("items", {}), path + ".")
            elif "default" not in value and "_special" not in value:
                problems.append(f"{path} 缺 default")

    walk(schema)
    check(not problems, "_conf_schema 每项都有说明与默认值", "; ".join(problems[:5]))


def check_i18n() -> None:
    zh = set(json.loads((ROOT / "i18n/zh-CN.json").read_text(encoding="utf-8")))
    en = set(json.loads((ROOT / "i18n/en-US.json").read_text(encoding="utf-8")))
    check(zh == en, "i18n 中英 key 一致", f"差异 {sorted(zh ^ en)[:5]}")


async def check_runtime() -> None:
    from core.app import StudyApp
    from core.config import Settings
    from core.principal import get_or_create

    with tempfile.TemporaryDirectory() as temp:
        app = StudyApp(data_dir=Path(temp), cfg=Settings({"http": {"enabled": False}}))
        await app.startup()
        try:
            check(app.db.version >= 1, "数据库迁移", f"schema_version={app.db.version}")
            principal = await get_or_create(app.db, kind="user", external_id="selfcheck")
            task = await app.tasks.create(principal, {"title": "自检任务"})
            reloaded = await app.tasks.get(principal, task["id"])
            check(reloaded is not None and reloaded["title"] == "自检任务", "任务写入/读取链路")
            adapter = app.memory_manager.active
            check(adapter.name == "none" and adapter.status.ok, "无记忆插件时降级正常", adapter.status.reason)
            info = await app.info()
            meta_version = read_metadata().get("version", "")
            check(
                info["plugin_version"] == meta_version,
                "info 接口版本与 metadata 一致",
                info["plugin_version"],
            )
        finally:
            await app.shutdown()


def main() -> int:
    check_files()
    check_metadata()
    check_conf_schema()
    check_i18n()
    try:
        asyncio.run(check_runtime())
    except Exception as exc:  # noqa: BLE001
        check(False, "运行时自检", f"{type(exc).__name__}: {exc}")
    from scripts.lint_secrets import main as lint_main  # noqa: PLC0415

    check(lint_main() == 0, "密钥扫描")

    width = max(len(name) for _, name, _ in RESULTS)
    failures = 0
    for ok, name, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        line = f"[{mark}] {name.ljust(width)}"
        if detail:
            line += f"  {detail}"
        print(line)
    print(f"\n{len(RESULTS) - failures}/{len(RESULTS)} 通过")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
