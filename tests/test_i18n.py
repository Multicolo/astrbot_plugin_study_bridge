"""i18n：中英 key 齐备、缺 key 回退中文、英文真正生效。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.i18n import I18n

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"


def _load(lang: str) -> dict[str, str]:
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_key_sets_are_identical():
    zh = set(_load("zh-CN"))
    en = set(_load("en-US"))
    missing_in_en = zh - en
    missing_in_zh = en - zh
    assert not missing_in_en, f"英文缺 key: {sorted(missing_in_en)}"
    assert not missing_in_zh, f"中文缺 key: {sorted(missing_in_zh)}"


def test_all_values_are_non_empty():
    # 列表标记里的"未完成"故意是空格，跳过这一类
    allow_blank = {"cmd.mark.pending"}
    for lang in ("zh-CN", "en-US"):
        for key, value in _load(lang).items():
            if key in allow_blank:
                assert value.strip() == ""
                continue
            assert value.strip(), f"{lang} 的 {key} 是空字符串"


def test_placeholders_match_between_languages():
    zh, en = _load("zh-CN"), _load("en-US")
    for key, value in zh.items():
        zh_fields = {part.split("}")[0] for part in value.split("{")[1:]}
        en_fields = {part.split("}")[0] for part in en[key].split("{")[1:]}
        assert zh_fields == en_fields, f"{key} 占位符不一致: {zh_fields} vs {en_fields}"


def test_switch_language():
    zh = I18n("zh-CN")
    en = I18n("en-US")
    assert "已写入" in zh.t("cmd.add.ok", title="x", start="1", end="2", source="qq")
    assert "Added" in en.t("cmd.add.ok", title="x", start="1", end="2", source="qq")


def test_missing_key_falls_back_to_chinese(tmp_path):
    (tmp_path / "zh-CN.json").write_text(
        json.dumps({"only.zh": "中文兜底", "shared": "两者都有"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "en-US.json").write_text(
        json.dumps({"shared": "both"}, ensure_ascii=False), encoding="utf-8"
    )
    i18n = I18n("en-US", directory=tmp_path)
    assert i18n.t("shared") == "both"
    assert i18n.t("only.zh") == "中文兜底"
    # 两边都没有：返回 key 本身，不抛异常
    assert i18n.t("nope.nope") == "nope.nope"


def test_bad_placeholder_does_not_crash():
    i18n = I18n("zh-CN")
    assert i18n.t("cmd.add.ok")  # 少传参数时原样返回模板，不抛 KeyError


def test_unknown_language_falls_back_to_default():
    i18n = I18n("de-DE")
    assert i18n.lang == "zh-CN"


def test_en_message_for_english_user(app):
    app.i18n = I18n("en-US")
    assert "Added" in app.t("cmd.add.ok", title="x", start="1", end="2", source="qq")
