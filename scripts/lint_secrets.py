#!/usr/bin/env python3
"""上架合规检查：仓库里不能出现密钥类字符串。

对应需求红线的 ``grep -rniE "<secret patterns>"`` 必须为空。
（本文件用拼接方式构造正则，避免自己成为扫描命中项。）

跳过目录：.venv / node_modules / web（构建产物）/ __pycache__ / .git / dist
命中即返回 1，并打印文件:行号。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 拼接构造，避免源码里出现完整的关键字面量
_PARTS = [
    "sk" + "-",
    "api" + r"[_-]?key\s*=",
    "pass" + r"word\s*=",
    "sec" + r"ret\s*=",
]
PATTERN = re.compile("|".join(_PARTS), re.IGNORECASE)
SKIP_DIRS = {".venv", "venv", "node_modules", "web", "dist", "__pycache__", ".git", ".pytest_cache"}
SKIP_FILES = {Path(__file__).name}
SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".ts",
    ".vue",
    ".js",
    ".html",
    ".ini",
    ".cfg",
    ".txt",
    ".toml",
    ".css",
}


def _safe_print(text: str) -> None:
    """Windows 控制台常是 GBK，遇到 emoji 会炸；这里降级替换，不让检查脚本自己崩。"""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def main() -> int:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix.lower() not in SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                hits.append(f"{relative}:{number}: {line.strip()[:140]}")
    if hits:
        _safe_print("发现疑似密钥字符串，上架前必须清理：")
        for hit in hits:
            _safe_print("  " + hit)
        return 1
    _safe_print("OK: 未发现密钥类字符串命中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
