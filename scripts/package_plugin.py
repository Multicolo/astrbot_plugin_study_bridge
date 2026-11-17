#!/usr/bin/env python3
"""把插件打成可上架的 zip（≤16MB，见 docs/MARKETPLACE.md）。

只包含运行所需文件：main.py / metadata.yaml / _conf_schema.json / requirements.txt /
LICENSE / README.md / CHANGELOG.md / logo.png / core/ / adapters/ / i18n/ / web/ / docs/

显式排除：frontend/（源码）、tests/、.venv、node_modules、data、__pycache__。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE_FILES = [
    "main.py",
    "logo.png",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
]
INCLUDE_DIRS = ["core", "adapters", "i18n", "web", "docs"]
SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", "node_modules", ".venv"}
MAX_BYTES = 16 * 1024 * 1024


def iter_files() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for name in INCLUDE_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix in {".pyc", ".map"}:
                continue
            # 只留最终截图，把 before-* 这类开发对比图排除掉，控制包体积
            if path.name.startswith("before-"):
                continue
            files.append(path)
    return files


def main() -> int:
    files = iter_files()
    if not files:
        print("没有可打包的文件")
        return 1
    target = ROOT / "dist"
    target.mkdir(exist_ok=True)
    zip_path = target / "astrbot_plugin_study_bridge.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    size = zip_path.stat().st_size
    print(f"打包完成：{zip_path}")
    print(f"文件数：{len(files)}，大小：{size / 1024:.1f} KB（上限 16384 KB）")
    if size > MAX_BYTES:
        print("超过去插件市场 16MB 限制！请先压缩静态资源")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
