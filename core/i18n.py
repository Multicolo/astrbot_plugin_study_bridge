"""极简 i18n：JSON 文件 + 进程内缓存，缺 key 一律回退中文。

为什么不用 gettext：插件只需要「中/英两套短文案」，键值对足够，且便于单测直接引用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"

DEFAULT_LANG = "zh-CN"
SUPPORTED = ("zh-CN", "en-US")


class I18n:
    def __init__(self, lang: str = DEFAULT_LANG, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else I18N_DIR
        self.lang = lang if lang in SUPPORTED else DEFAULT_LANG
        self._cache: dict[str, dict[str, str]] = {}

    def _load(self, lang: str) -> dict[str, str]:
        if lang in self._cache:
            return self._cache[lang]
        data: dict[str, str] = {}
        path = self.directory / f"{lang}.json"
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
            except (ValueError, OSError):
                data = {}
        self._cache[lang] = data
        return data

    def t(self, key: str, /, lang: str | None = None, **kwargs: Any) -> str:
        """取文案。``key`` 用位置参数传入，避免与模板里的 ``{key}`` 占位符冲突。"""
        target = lang if lang in SUPPORTED else self.lang
        text = self._load(target).get(key)
        if text is None:
            text = self._load(DEFAULT_LANG).get(key)
        if text is None:
            # 缺 key 不报错：回退成 key 本身，便于在日志里发现遗漏
            text = key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def keys(self, lang: str) -> set[str]:
        return set(self._load(lang).keys())


_DEFAULT_I18N = I18n()


def set_default(i18n: I18n) -> None:
    global _DEFAULT_I18N
    _DEFAULT_I18N = i18n


def t(key: str, **kwargs: Any) -> str:
    return _DEFAULT_I18N.t(key, **kwargs)
