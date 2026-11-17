# MEMORY_SYNC — 记忆互通与适配器

目标：**零侵入**地跟第三方记忆插件互通；**没装任何记忆插件也必须正常可用**。

---

## 1. 三种状态，永不崩

| 场景 | 适配器 | `/info` 显示 | 插件状态 |
|---|---|---|---|
| 没装记忆插件 | `none` | `{"name":"none","ok":true,"degraded":true}` | **正常**（不是异常） |
| 装了兼容插件 | `generic_tool` / `livingmemory` | `{"name":"livingmemory","ok":true,"version":"2.13.0"}` | 正常，上下行可用 |
| 装了不兼容版本 | 降级到 `none` | `{"name":"livingmemory","ok":false,"reason":"版本不兼容：1.9.0…"}` + 下一个适配器 `ok:true` | 正常，只是没有远端 |

探测顺序由 `memory.adapter_order` 决定，默认 `["generic_tool","livingmemory","none"]`，**首个 `probe()` 成功者生效**。
每个 `probe()` 都必须 `try/except` 且永不抛异常。

---

## 2. 适配器接口

```python
# adapters/base.py（节选）
class MemoryAdapter(ABC):
    name: str
    version: str
    supports_delete: bool = False     # 远端能不能真删
    supports_export: bool = False     # 远端能不能导出（下行同步用）

    async def probe(self) -> bool: ...
    async def upsert(self, *, source_ref: str, content: str,
                     tags: list[str] | None = None, importance: int = 3) -> str: ...
    async def delete(self, source_ref: str) -> bool: ...
    async def export(self, cursor: str | None = None) -> tuple[list[dict], str | None]: ...
    async def search(self, query: str, limit: int = 5) -> list[dict]:  # 可选
        return []
```

约定：

- `upsert` 返回远端引用；返回空串表示"没有远端"（`none` 适配器就是这么做的）；
- `delete` 返回 `False` 表示**远端不支持删除** → 上层标 `orphan` 并在 App 明示；
- 所有方法都不许让异常冒到主流程。

---

## 3. 为任意记忆插件写适配器（20 行模板）

把下面这段复制到 `adapters/my_plugin.py`，改 4 个地方即可：

```python
from .base import AdapterStatus, MemoryAdapter


class MyMemoryAdapter(MemoryAdapter):
    name = "my_plugin"
    version = "1"
    supports_delete = False

    async def probe(self) -> bool:
        ctx = self.app.context
        star = ctx.get_registered_star("astrbot_plugin_xxx") if ctx else None   # ① 插件名
        if star is None or not getattr(star, "star_cls", None):
            return False
        self._plugin = star.star_cls
        self._store = getattr(star.star_cls, "store", None)                     # ② 公开属性/方法
        ok = self._store is not None and hasattr(self._store, "add_memory")
        self.status = AdapterStatus(name=self.name, ok=ok,
                                    reason="ok" if ok else "结构不匹配", version=self.version)
        return ok

    async def upsert(self, *, source_ref, content, tags=None, importance=3) -> str:
        if self._store is None:
            return ""
        return str(await self._store.add_memory(content, metadata={"src": source_ref}))  # ③ 写入

    async def delete(self, source_ref: str) -> bool:
        return False                                                             # ④ 不支持就 False

    async def export(self, cursor: str | None = None):
        return [], None
```

然后在 `adapters/__init__.py` 的 `ADAPTER_TYPES` 里登记 `"my_plugin": MyMemoryAdapter`，
用户把 `memory.adapter_order` 改成 `["my_plugin","none"]` 即可。

**要求**：

1. 只调**公开方法 / 公开 tool / 公开存储模块**；不要 monkey patch、不要改别人的表；
2. 用 `getattr` + `hasattr` 探测结构，任何异常都转成 `probe()` 的 `False`；
3. 若必须读非下划线但属实现细节的属性（如 LivingMemory 的 `initializer.memory_engine`）：
   `try/except` + **版本白名单** + 文档标注（见下）；
4. 在 `SUPPORTED_VERSIONS` 里写清**已验证版本**，版本不符只 WARN，不崩。

---

## 4. LivingMemory 适配（已验证 2.13.0）

| 项 | 值 |
|---|---|
| 插件名 | `astrbot_plugin_livingmemory` |
| 已验证版本 | **2.13.0**（其 `metadata.yaml` 声明 `astrbot_version: ">=4.24.2,<5"`） |
| 写入入口（P1） | `plugin.initializer.memory_engine.add_memory(content, session_id=..., persona_id=..., importance=0~1, metadata={"topics":[...], "source_ref":...})` |
| 检索 | `memory_engine.search_memories(query, k=5, persona_id=...)` |
| 删除 | `memory_engine.delete_memory(int(doc_id)) -> bool`（支持删除，所以不产生 orphan） |
| 导出 | `list_memories_page(offset, limit)`（存在才用，否则不支持下行） |
| 依据 | `core/page_api.py:735`（它自己的 Page API 也是这么取引擎）、`core/managers/memory_engine_crud.py:63`、`core/managers/memory_engine_recall.py:72`、`crud.py:493` |

`initializer` 不是下划线属性但仍属实现细节 → 本插件按红线 6 处理：`getattr` 探测 + 版本白名单
+ `try/except` + 本节标注。用户可用 `memory.livingmemory.allow_private_attrs=false` 关掉这条路径
（此时会退到 tool 通道或 `none`）。

**importance 映射**：本插件 1–5 → 远端 0.0–1.0，`{1:0.3, 2:0.5, 3:0.7, 4:0.85, 5:0.95}`。

---

## 5. 通用 tool 适配（`generic_tool`）

不绑定具体插件：读 AstrBot 的 tool 注册表，按配置的名字找工具，**直接调函数**（不经过模型）。

```json
{"memory": {"generic_tool": {
  "write_tool": "remember", "search_tool": "recall",
  "write_arg": "text", "search_arg": "query"
}}}
```

- 兼容两种签名：`handler(event, **kwargs)` 与 `handler(**kwargs)`（依次尝试）；
- 兼容 async 函数与 async generator（取最后一个 yield）；
- 未配置删除工具时 `supports_delete=false` → 删除会标 `orphan`，**不报成功**；
- 单测用 mock 工具覆盖（`tests/test_adapters.py`）。

---

## 6. 同步语义

| 方向 | 内容 | 规则 |
|---|---|---|
| **上行**（学习 → bot） | 偏好、目标、计划进度、重要日期、薄弱点 | ≤120 字第三人称陈述句 + 来源标记 `[src:study:<id>]`；写完即 `upsert`；失败进 `sync_outbox`，指数退避重试，最多 10 次 |
| **下行**（bot → 学习） | bot 在闲聊里记下的关于用户的事实 | 每 30 分钟 `export(cursor)` 增量 → `bot_memory_mirror`（`origin='bot'`，**永不再次上行**），App 灰显只读，可「采纳」 |

计划进度用**固定 `source_ref`**：`study:plan-progress:{plan_id}` → 覆盖式写入，远端永远只有 1 条。

**禁止同步**：每日日程明细、统计数值、系统注入内容、工具回显、计划预览原文。

配置：

```json
{"memory": {"sync_mode": "off | upload_only | bidirectional"}}
```

默认 `upload_only`。选 `bidirectional` 意味着**bot 的聊天记忆会被读取并同步到 App**，
`_conf_schema.json` 的说明里已明确写出这一点。

---

## 7. 防污染与防回环（8 条，均有单测）

1. 长度 > 200 字 → 拒绝；
2. 含 ``` 代码块 → 拒绝；
3. 含 `{}` / `[]` 结构化块（排除自己的来源标记）→ 拒绝；
4. `source in ('injected','assistant','tool')` → 拒绝；
5. 与最近 24h 已同步条目相似度 > 0.95 → 跳过（标 `synced` + 原因）；
6. 下行 ingest 丢弃带自己来源标记的条目（防回环）；
7. 同一 `source_ref` 远端只留一条；进度类固定 `study:plan-progress:{plan_id}`；
8. 删除能力缺失 → 标 `orphan` 并在 App 明示（`/memory/sync-status` 的 `orphan` 计数）。

另外：每周日 03:10 对账（本地 `importance>=3 且未删除` 逐条核对，缺失补写）；
冲突不自动覆盖（两条都保留，App 内提示用户裁决）。

---

## 8. 实测与未测

| 项 | 状态 | 说明 |
|---|---|---|
| `none` 降级 | ✅ 单测 | 没装插件时 `ok:true, degraded:true` |
| `generic_tool` 映射 | ✅ 单测（mock 工具） | 真实第三方工具需真机联调 |
| `livingmemory` 结构探测 / 版本不符 | ✅ 单测（假引擎） | 真机联调步骤见下 |
| `livingmemory` 真实写入/删除 | ⏳ PENDING | 需要装了 LivingMemory 2.13.0 的 AstrBot 实例 |
| 下行导出 | ✅ 单测（假导出）；真实 `list_memories_page` | 参数可能随版本变化，代码已 try/except |

**真机联调步骤（LivingMemory）**

1. 装 `astrbot_plugin_livingmemory` 2.13.0，确认其 `initializer.memory_engine` 可用；
2. 本插件 `memory.adapter_order=["livingmemory","none"]`，重载；
3. `GET /info` 应看到 `memory.active = {"name":"livingmemory","ok":true,"version":"2.13.0"}`；
4. App「记忆中心」新增一条偏好 → 在 LivingMemory 里能搜到（带 `[src:study:…]` 标记）；
5. 重复下发同一 `source_ref` 3 次 → 远端仍只有 1 条；
6. App 删除该记忆 → 远端 `delete_memory` 生效，`sync-status` 不出现 orphan；
7. 把 `adapter_order` 里版本改成不匹配 → 重载后应降级并 WARN，AstrBot 不崩。
