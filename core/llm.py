"""LLM 客户端：AstrBot provider / 手填 OpenAI 兼容接口 + 规则解析降级。

对外只暴露 ``LLMClient``：
- ``parse_task`` / ``generate_plan`` / ``chat`` / ``complete_json`` / ``test``
- ``list_providers`` / ``select`` / ``save_manual`` / ``manual_info``

密钥：手填 Key 用 Fernet 加密存 ``llm_config.api_key_enc``，密钥文件在
``<data_dir>/secret.key``；任何接口都不回明文。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from string import Template
from typing import Any

from .errors import invalid
from .util import get_tz, iso, loads, local_now, parse_iso, utcnow

PROMPT_DIR = Path(__file__).resolve().parent / "ai" / "prompts"
LLM_TIMEOUT_DEFAULT = 60


class LLMError(RuntimeError):
    """AI 不可用/调用失败：调用方应降级，不要 500。"""


# ---------------------------------------------------------------- 规则解析


DATE_WORDS = {
    "今天": 0,
    "今日": 0,
    "明天": 1,
    "明日": 1,
    "后天": 2,
    "大后天": 3,
}
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
PERIODS = {
    "凌晨": "am_early",
    "早上": "am",
    "早晨": "am",
    "上午": "am",
    "中午": "noon",
    "下午": "pm",
    "傍晚": "pm",
    "晚上": "pm",
    "夜里": "pm",
    "晚": "pm",
}

_FILLERS = re.compile(r"(提醒我|记一下|记录一下|帮我|安排一下|安排|我要|我想|需要|去)")

_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
NUM_TOKEN = r"(\d{1,3}|[零一二两三四五六七八九十]{1,3})"


def _to_int(token: str | None) -> int | None:
    """把 ``3`` / ``三`` / ``十`` / ``十二`` / ``二十`` 转成整数。"""
    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if "十" not in token:
        value = 0
        for char in token:
            if char not in _CN_DIGITS:
                return None
            value = value * 10 + _CN_DIGITS[char]
        return value if token else None
    head, _, tail = token.partition("十")
    tens = _CN_DIGITS.get(head, 1) if head else 1
    ones = _CN_DIGITS.get(tail, 0) if tail else 0
    return tens * 10 + ones


def rule_parse(text: str, tz: str, *, now: datetime | None = None) -> dict[str, Any]:
    """纯正则解析：没有 AI 也要能用（覆盖中文常见说法 + 少量英文）。"""
    raw = (text or "").strip()
    local = (now or utcnow()).astimezone(get_tz(tz))
    today = local.date()
    day: date | None = None

    for word, offset in DATE_WORDS.items():
        if word in raw:
            day = today + timedelta(days=offset)
            break
    if day is None:
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
        if m:
            try:
                day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                day = None
    if day is None:
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", raw)
        if m:
            month, dom = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            try:
                day = date(year, month, dom)
            except ValueError:
                day = None
    if day is None:
        m = re.search(r"(下+|这|本)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])", raw)
        if m:
            week_offset = 1 if m.group(1) else 0
            target = WEEKDAYS[m.group(2)]
            start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
            day = start + timedelta(days=target)
            if week_offset == 0 and day < today:
                day += timedelta(days=7)
    if day is None:
        m = re.search(r"(\d+)\s*天\s*(?:后|以后)", raw)
        if m:
            day = today + timedelta(days=int(m.group(1)))

    hour: int | None = None
    minute = 0
    period: str | None = None
    for word, kind in PERIODS.items():
        if word in raw:
            period = kind
            break
    m = re.search(r"(\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*[点时](?:\s*(半|\d{1,2})\s*分?)?", raw)
    if m:
        hour = _to_int(m.group(1))
        tail = m.group(2)
        if tail == "半":
            minute = 30
        elif tail and tail.isdigit():
            minute = int(tail)
    else:
        m = re.search(r"(\d{1,2})\s*:\s*(\d{2})", raw)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
    if hour is not None and not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = None, 0
    if hour is not None and period:
        if period in ("pm", "noon") and hour < 12:
            hour += 12
        elif period == "am_early" and hour == 12:
            hour = 0

    duration = 30
    m = re.search(
        r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)\s*个?\s*(?:小时|钟头)(?:\s*(\d{1,2}))?\s*分?",
        raw,
    )
    if m:
        hours = m.group(1)
        if hours[0].isdigit():
            duration = int(float(hours) * 60)
        else:
            duration = (_to_int(hours) or 1) * 60
        if m.group(2):
            duration += int(m.group(2))
    elif "一个半小时" in raw:
        duration = 90
    elif "半小时" in raw or "半个小时" in raw:
        duration = 30
    else:
        m = re.search(r"(\d{1,3})\s*分钟", raw)
        if m:
            duration = int(m.group(1))
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hour|hours)\b", raw, re.IGNORECASE)
            if m:
                duration = int(float(m.group(1)) * 60)
            else:
                m = re.search(r"(\d{1,3})\s*(?:m|min|mins|minutes)\b", raw, re.IGNORECASE)
                if m:
                    duration = int(m.group(1))
    duration = max(5, min(duration, 600))

    start_at = None
    end_at = None
    if day is not None and hour is not None:
        start_local = datetime.combine(day, dtime(hour, minute), tzinfo=get_tz(tz))
        start_at = iso(start_local)
        end_at = iso(start_local + timedelta(minutes=duration))

    title = _clean_title(raw)
    if not title:
        title = raw[:30]
    return {
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "all_day": False,
        "priority": 2,
        "remind_offsets": [30, 0],
        "duration_min": duration,
        "confidence": 0.55 if start_at else 0.2,
        "source": "rule",
        "tz": tz,
    }


def _clean_title(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"(\d{4}-\d{1,2}-\d{1,2})", " ", cleaned)
    cleaned = re.sub(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]", " ", cleaned)
    cleaned = re.sub(r"(下+|这|本)?\s*(?:周|星期|礼拜)\s*[一二三四五六日天]", " ", cleaned)
    cleaned = re.sub(r"(今天|今日|明天|明日|后天|大后天)", " ", cleaned)
    cleaned = re.sub(r"\d+\s*天\s*(?:后|以后)", " ", cleaned)
    cleaned = re.sub(
        r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|晚)?\s*"
        r"(\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*[点时](?:\s*(半|\d{1,2})\s*分?)?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\d{1,2}\s*:\s*\d{2}", " ", cleaned)
    cleaned = re.sub(
        r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)\s*个?\s*(?:小时|钟头)(?:\s*\d{1,2})?\s*分?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\d{1,3}\s*分钟", " ", cleaned)
    cleaned = cleaned.replace("一个半小时", " ").replace("半个小时", " ").replace("半小时", " ")
    cleaned = _FILLERS.sub(" ", cleaned)
    cleaned = re.sub(r"^[\s,，。;；:：\-—]+|[\s,，。;；:：\-—]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:30]


# ---------------------------------------------------------------- 提示词


def render_prompt(name: str, lang: str, **values: Any) -> str:
    """读取 ``core/ai/prompts/<name>.<lang>.md``；缺文件回退中文。"""
    safe = {key: ("" if value is None else str(value)) for key, value in values.items()}
    for candidate in (f"{name}.{lang}.md", f"{name}.zh-CN.md"):
        path = PROMPT_DIR / candidate
        if path.is_file():
            template = Template(path.read_text(encoding="utf-8"))
            try:
                return template.safe_substitute(**safe)
            except ValueError:  # pragma: no cover - 模板异常时退化为原文
                return path.read_text(encoding="utf-8")
    return ""


def extract_json(text: str) -> Any:
    """从模型输出里抠 JSON：容忍 ```json 包裹与前后废话。"""
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.strip().startswith("```")]
        candidate = "\n".join(lines).strip()
    try:
        return json.loads(candidate)
    except ValueError:
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except ValueError:
            return None
    start, end = candidate.find("["), candidate.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- 主类


class LLMClient:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._row: dict[str, Any] | None = None
        self._loaded = False

    # ------------------------------------------------------------ 配置
    async def _config(self) -> dict[str, Any] | None:
        if self._loaded:
            return self._row
        self._row = await self.app.db.fetch_one(
            "SELECT * FROM llm_config WHERE enabled = 1 ORDER BY created_at DESC LIMIT 1"
        )
        self._loaded = True
        return self._row

    async def reload(self) -> None:
        self._loaded = False
        self._row = None

    @property
    def mode(self) -> str:
        mode = (self._row or {}).get("mode") or self.app.cfg.get_str("ai.mode", "astrbot")
        return mode if mode in ("astrbot", "manual") else "astrbot"

    @property
    def provider_id(self) -> str:
        return (self._row or {}).get("provider_id") or self.app.cfg.get_str("ai.provider_id", "")

    @property
    def model(self) -> str:
        return (self._row or {}).get("model") or ""

    async def _secret_path(self) -> Path:
        path = Path(self.app.data_dir) / "secret.key"
        return path

    def _fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover - AstrBot 环境必有
            raise LLMError("缺少 cryptography，无法保存手填 API Key") from exc
        path = Path(self.app.data_dir) / "secret.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            path.write_bytes(key)
            try:
                os.chmod(path, 0o600)
            except OSError:  # pragma: no cover - Windows 上权限位不生效
                pass
        return Fernet(path.read_bytes())

    # ------------------------------------------------------------ provider 列表
    async def list_providers(self) -> dict[str, Any]:
        providers: list[dict[str, Any]] = []
        error = None
        ctx = self.app.context
        if ctx is None:
            error = "当前不在 AstrBot 运行时内（无法列出 provider）"
        else:
            try:
                for provider in ctx.get_all_providers():
                    meta = provider.meta()
                    providers.append(
                        {
                            "id": getattr(meta, "id", ""),
                            "model": getattr(meta, "model", "") or "",
                            "type": getattr(meta, "type", "") or "",
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - 平台异常不拖垮接口
                error = f"读取 provider 失败：{exc}"
        config = await self._config()
        return {
            "mode": self.mode,
            "providers": providers,
            "selected": {
                "provider_id": self.provider_id,
                "model": self.model or (config or {}).get("model") or "",
            },
            "error": error,
        }

    async def select(self, provider_id: str, model: str | None = None) -> dict[str, Any]:
        provider_id = (provider_id or "").strip()
        available = {item["id"] for item in (await self.list_providers())["providers"]}
        if provider_id and provider_id not in available:
            raise invalid(f"provider 不存在：{provider_id}")
        now = iso(utcnow())
        await self.app.db.execute("DELETE FROM llm_config")
        await self.app.db.execute(
            "INSERT INTO llm_config (id, mode, provider_id, base_url, api_key_enc, model, enabled, created_at) "
            "VALUES (?, 'astrbot', ?, NULL, NULL, ?, 1, ?)",
            (__import__("uuid").uuid4().hex, provider_id or None, model, now),
        )
        await self.reload()
        return {"mode": "astrbot", "provider_id": provider_id, "model": model or ""}

    async def manual_info(self) -> dict[str, Any]:
        config = await self._config()
        if not config or config.get("mode") != "manual":
            return {"configured": False, "has_key": False, "base_url": "", "model": ""}
        return {
            "configured": True,
            "base_url": config.get("base_url") or "",
            "model": config.get("model") or "",
            "has_key": bool(config.get("api_key_enc")),
        }

    async def save_manual(
        self, base_url: str, key: str | None, model: str
    ) -> dict[str, Any]:
        base_url = (base_url or "").strip().rstrip("/")
        model = (model or "").strip()
        if not base_url.startswith(("http://", "https://")):
            raise invalid("base_url 必须以 http:// 或 https:// 开头")
        if not model:
            raise invalid("model 不能为空")
        existing = await self._config()
        encrypted = (existing or {}).get("api_key_enc") if existing else None
        if key:
            encrypted = self._fernet().encrypt(key.encode("utf-8")).decode("utf-8")
        if not encrypted:
            raise invalid("首次配置必须提供 api_key")
        now = iso(utcnow())
        await self.app.db.execute("DELETE FROM llm_config")
        await self.app.db.execute(
            "INSERT INTO llm_config (id, mode, provider_id, base_url, api_key_enc, model, enabled, created_at) "
            "VALUES (?, 'manual', NULL, ?, ?, ?, 1, ?)",
            (__import__("uuid").uuid4().hex, base_url, encrypted, model, now),
        )
        await self.reload()
        return {"mode": "manual", "base_url": base_url, "model": model, "has_key": True}

    def _decrypt_key(self, encrypted: str) -> str:
        try:
            return self._fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise LLMError("API Key 解密失败（secret.key 可能被替换）") from exc

    # ------------------------------------------------------------ 可用性
    async def available(self) -> bool:
        config = await self._config()
        if config and config.get("mode") == "manual":
            return bool(config.get("base_url") and config.get("api_key_enc"))
        ctx = self.app.context
        if ctx is None:
            return False
        try:
            if self.provider_id:
                return ctx.get_provider_by_id(self.provider_id) is not None
            return ctx.get_using_provider() is not None
        except Exception:  # noqa: BLE001
            return False

    def allowed_for(self, principal: Any) -> bool:
        if getattr(principal, "can_use_ai", True) is False:
            return False
        if getattr(principal, "kind", "user") == "owner":
            return True
        return self.app.cfg.get_bool("ai.allow_principal_ai", True)

    # ------------------------------------------------------------ 调用
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        timeout: int | None = None,
        json_mode: bool = False,
    ) -> str:
        config = await self._config()
        timeout = timeout or self.app.cfg.get_int("ai.timeout_seconds", LLM_TIMEOUT_DEFAULT)
        if config and config.get("mode") == "manual":
            return await self._manual_complete(
                config, prompt, system=system, timeout=timeout, json_mode=json_mode
            )
        return await self._astrbot_complete(prompt, system=system, timeout=timeout)

    async def _astrbot_complete(
        self, prompt: str, *, system: str | None, timeout: int
    ) -> str:
        ctx = self.app.context
        if ctx is None:
            raise LLMError("AI 不可用：当前不在 AstrBot 运行时内")
        try:
            if self.provider_id:
                call = ctx.llm_generate(
                    chat_provider_id=self.provider_id,
                    prompt=prompt,
                    system_prompt=system,
                )
            else:
                provider = ctx.get_using_provider()
                if provider is None:
                    raise LLMError("AI 不可用：没有可用的对话模型")
                call = provider.text_chat(prompt=prompt, system_prompt=system)
            response = await asyncio.wait_for(call, timeout=timeout)
        except asyncio.TimeoutError:
            raise LLMError(f"AI 请求超时（>{timeout}s）") from None
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider 异常统一降级
            raise LLMError(f"AI 调用失败：{exc}") from exc
        text = getattr(response, "completion_text", None)
        if text is None and isinstance(response, str):
            text = response
        if not text:
            raise LLMError("AI 返回为空")
        return str(text)

    async def _manual_complete(
        self,
        config: dict[str, Any],
        prompt: str,
        *,
        system: str | None,
        timeout: int,
        json_mode: bool,
    ) -> str:
        import aiohttp

        base_url = (config.get("base_url") or "").rstrip("/")
        url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        key = self._decrypt_key(config["api_key_enc"])
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": config.get("model") or "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                ) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise LLMError(f"上游返回 {response.status}：{body[:200]}")
                    data = json.loads(body)
        except asyncio.TimeoutError:
            raise LLMError(f"AI 请求超时（>{timeout}s）") from None
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"AI 请求失败：{exc}") from exc
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("上游返回格式不符合 OpenAI 兼容协议") from exc

    async def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        retry: bool = True,
    ) -> tuple[dict[str, Any], str]:
        """要求模型输出 JSON；非法则重试 1 次，仍失败抛 LLMError。"""
        text = await self.complete(prompt, system=system, json_mode=True)
        data = extract_json(text)
        if isinstance(data, dict):
            return data, text
        if retry:
            retry_prompt = (
                prompt
                + "\n\n上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要任何解释或代码块。"
            )
            text = await self.complete(retry_prompt, system=system, json_mode=True)
            data = extract_json(text)
            if isinstance(data, dict):
                return data, text
        raise LLMError("模型返回的不是合法 JSON")

    # ------------------------------------------------------------ 业务封装
    async def parse_task(self, principal: Any, text: str, *, tz: str) -> dict[str, Any]:
        fallback = rule_parse(text, tz)
        if not self.allowed_for(principal) or not await self.available():
            return {
                "draft": _draft_view(fallback, tz),
                "confidence": fallback["confidence"],
                "source": "rule",
                "warnings": ["AI 不可用，已使用规则解析"],
            }
        lang = self.app.lang
        prompt = render_prompt(
            "parse_task",
            lang,
            now=iso(utcnow()),
            tz=tz,
            local_now=local_now(tz).strftime("%Y-%m-%d %H:%M"),
            text=text,
        )
        try:
            data, _raw = await self.complete_json(prompt)
        except LLMError as exc:
            return {
                "draft": _draft_view(fallback, tz),
                "confidence": fallback["confidence"],
                "source": "rule",
                "warnings": [str(exc)],
            }
        draft = _normalise_draft(data, tz, fallback=fallback)
        return {
            "draft": _draft_view(draft, tz),
            "confidence": float(draft.get("confidence") or 0.5),
            "source": "ai",
            "warnings": [],
        }

    async def generate_plan(
        self,
        principal: Any,
        *,
        goal: str,
        materials: list[dict[str, Any]],
        daily_minutes: int,
        deadline: str,
        today: str,
        tz: str,
    ) -> dict[str, Any]:
        if not self.allowed_for(principal):
            return {"items": [], "error": "该用户未开启 AI，计划拆解需要 AI 支持"}
        if not await self.available():
            return {"items": [], "error": "AI 不可用，暂时无法拆解计划"}
        material_text = _summarise_materials(materials)
        prompt = render_prompt(
            "plan_from_goal",
            self.app.lang,
            today=today,
            deadline=deadline,
            daily_minutes=daily_minutes,
            goal=goal or "（用户未填写目标，请按资料规划）",
            materials=material_text or "（无资料，按目标规划）",
        )
        try:
            data, _raw = await self.complete_json(prompt)
        except LLMError as exc:
            return {"items": [], "error": str(exc)}
        items = data.get("items")
        if not isinstance(items, list) or not items:
            return {"items": [], "error": str(data.get("error") or "模型没有给出可用的计划条目")}
        return {
            "title": str(data.get("title") or "")[:120],
            "items": items,
            "warnings": [],
            "source": "ai",
        }

    async def chat_completion(self, system: str, messages: list[dict[str, str]]) -> str:
        parts = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            parts.append(f"[{role}] {content}")
        prompt = "\n\n".join(parts)
        return await self.complete(prompt, system=system)

    async def test(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            text = await self.complete("只回复两个字：可用", timeout=20)
        except LLMError as exc:
            return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "error": str(exc)}
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "reply": text.strip()[:50],
            "mode": self.mode,
            "model": self.model,
        }


# ---------------------------------------------------------------- 辅助


def _summarise_materials(materials: list[dict[str, Any]], budget: int = 1200) -> str:
    chunks: list[str] = []
    used = 0
    for item in materials:
        text = (item.get("summary") or item.get("raw_text") or "").strip()
        if not text:
            continue
        piece = f"- {item.get('name', '资料')}：{text[:400]}"
        if used + len(piece) > budget:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks)


def _normalise_draft(
    data: dict[str, Any], tz: str, *, fallback: dict[str, Any]
) -> dict[str, Any]:
    title = str(data.get("title") or "").strip() or fallback["title"]
    start = parse_iso(data.get("start_at"))
    if start is None:
        start = parse_iso(fallback.get("start_at"))
    end = parse_iso(data.get("end_at"))
    if start and end is None:
        end = start + timedelta(minutes=int(fallback.get("duration_min") or 30))
    if start and end and end <= start:
        end = start + timedelta(minutes=30)
    offsets = data.get("remind_offsets")
    if not isinstance(offsets, list) or any(not isinstance(x, int) for x in offsets):
        offsets = [30, 0]
    try:
        priority = int(data.get("priority") or 2)
    except (TypeError, ValueError):
        priority = 2
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.85 if start else 0.2
    return {
        "title": title[:120],
        "start_at": iso(start) if start else None,
        "end_at": iso(end) if end else None,
        "all_day": bool(data.get("all_day")),
        "priority": max(1, min(3, priority)),
        "remind_offsets": offsets,
        "confidence": max(0.0, min(1.0, confidence)),
        "source": "ai",
        "tz": tz,
    }


def _draft_view(draft: dict[str, Any], tz: str) -> dict[str, Any]:
    """对外返回的草稿：附带本地时间，方便前端直接展示。"""
    start = parse_iso(draft.get("start_at"))
    end = parse_iso(draft.get("end_at"))
    zone = get_tz(tz)
    return {
        "title": draft.get("title") or "",
        "start_at": iso(start) if start else None,
        "end_at": iso(end) if end else None,
        "all_day": bool(draft.get("all_day")),
        "priority": int(draft.get("priority") or 2),
        "remind_offsets": list(draft.get("remind_offsets") or [30, 0]),
        "local_date": start.astimezone(zone).date().isoformat() if start else None,
        "local_start": start.astimezone(zone).strftime("%H:%M") if start else None,
        "local_end": end.astimezone(zone).strftime("%H:%M") if end else None,
    }


def decode_jwt_payload(token: str) -> dict[str, Any]:  # pragma: no cover - 保留调试用
    """调试辅助：解析（不验签）JWT payload。不用于任何鉴权路径。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


_ = loads  # 保持 util.loads 的导入不被裁剪（部分工具链会误判）
