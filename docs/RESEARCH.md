# RESEARCH — 调研结论与依据

> 调研时间：2026-11-17（Asia/Shanghai）
> 调研方式：**读源码**（不靠记忆、不靠博客）。
> - AstrBot：`AstrBotDevs/AstrBot` `master` 分支快照，HTTP 下载于 2026-11-17，版本号 `4.30.0-alpha.1`（`pyproject.toml:2`）。本地解压路径 `_ref/AstrBot-master/`，下文行号均指该快照。
> - LivingMemory：`lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory` `master` 快照，下载于 2026-11-17，`metadata.yaml` 声明 `version: 2.13.0`。本地路径 `_ref/astrbot_plugin_livingmemory-master/`。
> - 若某结论只有文档没有源码，会单独标注「文档依据」。

---

## 1. AstrBot 平台

### 1.1 插件基类与生命周期

| 结论 | 依据 |
|---|---|
| 插件类继承 `astrbot.api.star.Star` | `astrbot/core/star/base.py:18` `class Star(CommandParserMixin, PluginKVStoreMixin)` |
| 构造签名 `Star(context, config)`，`config` 是 `_conf_schema.json` 对应的配置字典 | `base.py:27` `def __init__(self, context: Context, config: dict \| None = None)` |
| 激活钩子 `async def initialize(self) -> None` | `base.py:141` |
| 卸载/重载钩子 `async def terminate(self) -> None` | `base.py:144` |
| `self.context` 是 `Context` 实例（唯一对外接口面） | `base.py:28` |
| 插件有独立 logger `self.logger` | `base.py:39-43`（`LogManager.get_plugin_logger`） |

### 1.2 注册方式（当前版本）

| 结论 | 依据 |
|---|---|
| **不需要**任何装饰器；继承 `Star` 即被识别 | `base.py:53-64` `__init_subclass__` 自动写入 `star_registry` / `star_map` |
| `@register(name, author, desc, version, repo)` 已废弃，会在未来移除 | `astrbot/core/star/register/star.py:8-22`（docstring 明确 `[DEPRECATED]` + `DeprecationWarning`） |
| 插件的「帮助信息」= 插件类 docstring | `register/star.py:28-35` |
| **本插件结论**：不使用 `@register`，只继承 `Star`；名称/作者/版本放 `metadata.yaml` | — |

### 1.3 指令注册与事件过滤

| 结论 | 依据 |
|---|---|
| `from astrbot.api.event import filter`；`@filter.command("xxx")` 装饰实例方法 | `astrbot/api/event/filter/__init__.py:16` 把 `register_command` 导出为 `command` |
| 装饰器实现与参数 | `astrbot/core/star/register/star_handler.py:76` `register_command(...)`，内部把 handler 写入 `star_map` |
| handler 签名 `async def h(self, event: AstrMessageEvent, ...)`；可为 `async generator`，用 `yield event.plain_result(...)` | `astrbot/api/event/__init__.py:1-17`；`astr_message_event.py:491` `plain_result` |
| 按会话类型过滤：`@filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)` | `star/filter/event_message_type.py`；导出见 `api/event/filter/__init__.py:19` |
| 按权限过滤：`@filter.permission_type(filter.PermissionType.ADMIN)` | `api/event/filter/__init__.py:40`；`star/filter/permission.py` |
| 正则触发：`@filter.regex(...)` | `api/event/filter/__init__.py:44` |
| **群聊 `per_user` 模式所需的群号**：`event.get_group_id()` / `event.is_private_chat()` | `astr_message_event.py:282`、`:347` |
| **UMO 只能从事件对象取**：`event.unified_msg_origin`（属性） | `astr_message_event.py:175` `def unified_msg_origin(self)` |
| 发送者 id：`event.get_sender_id()` | `astr_message_event.py:290` |

### 1.4 插件配置项 schema（`_conf_schema.json`）

| 结论 | 依据 |
|---|---|
| 根是 `{"键": {"type": ...}}`；`type` 取值：`string` `text` `int` `float` `bool` `list` `dict` `file` `object` `template_list` | `docs/zh/dev/star/guides/plugin-config.md:43-487` |
| 通用可选字段：`description` `default` `hint` `obvious_hint` `invisible` | 同上 `:489-500` |
| `string` + `secret: true` 只做遮罩、**不加密存储**（重要：不要把真密钥交给它） | 同上 `:114-127` |
| `object.items` 做分组，`collapsed: true` 默认收起 | 同上 `:291-315` |
| 配置落盘位置 `data/config/<插件目录名>_config.json` | 同上 `:512` |
| 插件里可 `self.config["k"] = v; self.config.save_config()` | 同上 `:503-510` |
| **本插件结论**：所有配置项写在 `_conf_schema.json`，每项带中文 `description` + `default`；高风险项加 `hint`/`obvious_hint`。手填 API Key 不放配置（配置是明文 JSON），只走 App 的 `PUT /ai/manual` 加密入库 | — |

### 1.5 插件市场官方要求

| 结论 | 依据 |
|---|---|
| 通过 **AstrBot Cloud 发布页** `https://cloud.astrbot.app/publish` 发布（不是提 PR 到某个仓库） | `docs/zh/dev/star/plugin-publish.md:3-9` |
| 发布物是 GitHub 仓库 + 一个 zip；zip **≤ 16MB**，超限 CI 直接拒绝 | 同上 `:33-44` |
| `metadata.yaml` 必填：`name` `desc` `version` `author`；常用可选：`display_name` `short_desc` `repo` `astrbot_version` `support_platforms` `social_link` `tags` | 同上 `:13-29`；代码侧校验 `astrbot/core/star/star_manager.py:491-565`、必填字段常量 `astrbot/core/star/updater.py:29` |
| 仓库命名惯例 `astrbot_plugin_<name>`（与 `name` 字段一致） | 同上示例 `:14`；AstrBot 插件目录名即仓库名 |
| 版本号遵循语义化版本 | 同上 `:19` |
| **本插件结论**：仓库名 `astrbot_plugin_study_bridge`；`name` 同名；`astrbot_version: ">=4.24.2,<5"`；zip 打包脚本排除 `.venv`/`node_modules`/`frontend`/`tests` 以控制体积 | — |

### 1.6 插件能否把自定义 Web 路由挂到 AstrBot 自带服务？（决定端口方案）

**结论：能注册，但当前版本无法匿名访问，因此不能作为 App 的主路径。**

证据链：

1. 有公开注册接口：`Context.register_web_api(route, view_handler, methods, desc)`
   → `astrbot/core/star/context.py:791-813`，存入 `registered_web_apis`（`context.py:138`）。
2. 路由被挂在 **Dashboard（FastAPI，默认 6185）** 上，且**强制 Dashboard 鉴权**：
   - `astrbot/dashboard/api/plugins.py:398-440`：`/plugins/extensions/{plugin_path:path}` 的 GET/POST/PUT/PATCH/DELETE 全部 `auth: AuthContext = Depends(require_plugin_scope)`。
   - 兼容旧路径 `astrbot/dashboard/api/plugins.py:1485-1491`：`/api/plug/{plugin_path:path}` 也 `Depends(require_dashboard_user)`。
3. 匹配规则（`plugins.py:189-222`）：`<name>` 匹配单段、`<path:name>` 匹配剩余路径；`_call_plugin_extension` 把 `{path_params}` 传给 handler。
4. 插件静态页面（`views`/`pages`）同样在 Dashboard 下并受鉴权（`plugins.py:885-920`、`:1159-1193`）。

**推论**：App 只有本插件的「绑定码换来的 Bearer 令牌」，没有 AstrBot Dashboard 的 JWT，因此**不可能**直接调用挂在 `/api/plug/...` 下的接口；把 App 数据面暴露在 Dashboard 上还会把用户管理面与服务面耦合在一起。

**采纳方案**：自建 `aiohttp` 服务（第 5.1 节兜底方案），同源托管 `/study/` 静态页 + `/api/study/*` API。同时在 `docs/KNOWN_ISSUES.md` 记录「上游未来若提供匿名插件路由，可切换为挂载模式」的演进路径。为降低误配代价，`http.host` 默认 `0.0.0.0`、`http.port` 默认 `6188`，与 Dashboard 的 `6185` 错开。

### 1.7 Provider 列表与 LLM 调用

| 结论 | 依据 |
|---|---|
| 取全部 provider：`context.get_all_providers() -> list[Provider]` | `context.py:504` |
| 按 id 取：`context.get_provider_by_id(provider_id)` | `context.py:473` |
| 取当前默认：`context.get_using_provider(umo=None)` | `context.py:521` |
| 一次性调用：`await context.llm_generate(chat_provider_id=..., prompt=..., system_prompt=..., contexts=...)`，返回 `LLMResponse` | `context.py:192-234` |
| provider 对象本身有 `text_chat(...)` | `context.py:225`（`prov.text_chat(prompt=..., contexts=..., system_prompt=...)`） |
| `LLMResponse.completion_text` 取文本 | `astrbot/core/provider/entities.py:543` |
| **不复制、不落库任何 Key**：`get_all_providers()` 返回的对象里可能有密钥，本插件只读 `provider_name/id/model` 等展示字段 | 本插件实现约束 |

### 1.8 主动发消息 / UMO

| 结论 | 依据 |
|---|---|
| `await context.send_message(umo_str, MessageChain([...]))`，返回 bool（是否找到平台） | `context.py:682-763`；`astrbot/core/star/star_tools.py:35-54` |
| `umo` 字符串会被 `MessageSesion.from_str()` 解析，**不要自己拼** | `context.py:703-707` |
| 组件：`astrbot.api.message_components.Plain` / `astrbot.api.event.MessageChain` | `astrbot/api/message_components.py`；`astrbot/api/event/__init__.py:1-8` |
| 平台未找到时只 WARNING 并返回 False，不抛异常 | `context.py:760-763` |

**本插件结论**：通知一律 `context.send_message(stored_umo, MessageChain([Plain(text)]))`；`stored_umo` 来自 `event.unified_msg_origin` 落库，代码中不存在手工拼接。

### 1.9 LLM tool 注册表（供 `generic_tool` 记忆适配器）

| 结论 | 依据 |
|---|---|
| `context.get_llm_tool_manager() -> FunctionToolManager` | `context.py:414` |
| `FunctionToolManager.func_list: list[FuncTool]`；`get_func(name)` 取工具 | `astrbot/core/provider/func_tool_manager.py:291-310`、`:402-412` |
| 工具对象字段：`name` / `description` / `parameters` / `handler` | `func_tool_manager.py:346-366`（`spec_to_func` 组装 `FuncTool`） |
| `@filter.llm_tool` 注册的工具，`handler` 就是原函数，签名 `(event, **kwargs)` | `func_tool_manager.py:256-267` |
| 权限包装工具（`_PermissionGuardedTool`）的 `call()` 需要 `AstrAgentContext`；插件侧**不**走这条路径 | `func_tool_manager.py:216-288` |
| **本插件结论**：`generic_tool` 适配器用 `get_llm_tool_manager().get_func(name)` 拿到工具后**直接调 `tool.handler(event, **kwargs)`**（有 event 时）或 `tool.handler(**kwargs)`（无 event 时，try/except 两种签名都试），不经过模型、不碰权限包装 | — |

### 1.10 插件数据目录

| 结论 | 依据 |
|---|---|
| `StarTools.get_data_dir()` → `data/plugin_data/<插件名>/`，且会自动创建 | `astrbot/core/star/star_tools.py:244-298`（`286-287` 拼路径） |
| 根路径由 `get_astrbot_data_path()` 决定 | `star_tools.py:16`、`:286` |
| **本插件结论**：DB、导出、日志只写 `data/plugin_data/astrbot_plugin_study_bridge/`；对外 `--data-dir` 参数仅用于测试/独立运行 | — |

### 1.11 最低 AstrBot 版本

- `metadata.yaml` 支持 `astrbot_version`（PEP 440 区间），加载时校验，不满足**拒绝加载该插件**但不影响其它插件：`star_manager.py:674-703`、`:1216-1217`、`:2114-2115`。
- AstrBot 本体 4.30.x 要求 Python `>=3.12`（`pyproject.toml:5`）。
- LivingMemory 2.13.0 声明 `>=4.24.2,<5`（其 `metadata.yaml`）。
- **本插件声明 `astrbot_version: ">=4.24.2,<5"`**，与「首个适配对象」保持一致，避免出现「能装但适配层一定崩」的版本组合；同时代码内部仍有运行时降级（版本不符 → `probe()` False + WARN）。

### 1.12 其它被本插件依赖的平台事实

| 结论 | 依据 |
|---|---|
| `context.get_registered_star(name)` 可拿到别的插件的 `StarMetadata`（含 `star_cls` 实例） | `context.py:404-409`；`StarMetadata` 字段 `astrbot/core/star/star.py:17-88` |
| `StarMetadata.plugin_id` = `author/name`（小写） | `star.py:78-82` |
| 平台适配器 id 集合可从 `context.platform_manager.get_insts()` 取 | `star_tools.py:125-134` |
| 插件异常不会拖垮 AstrBot：加载失败被捕获并记录为 failed plugin | `star_manager.py:870-880` |

---

## 2. 第三方记忆插件：LivingMemory

已验证版本：**2.13.0**（`metadata.yaml` `version: 2.13.0`；仓库 `HEAD` 快照 2026-11-17）。

### 2.1 写入入口优先级（实测源码）

| 级别 | 入口 | 是否可用 | 依据 |
|---|---|---|---|
| **P1 公开方法** | `plugin.initializer.memory_engine` → `MemoryEngine` | ✅ | 插件自身 Page API 也这么取：`core/page_api.py:735` `"memory_engine": self.plugin.initializer.memory_engine`；`plugin_initializer.py:524` 创建 |
| P1 写入 | `await engine.add_memory(content, session_id=None, persona_id=None, importance=0.5, metadata=None, atoms=None, preserve_create_time=False, source_messages=None, *, embedding=None) -> int` | ✅ 返回 doc_id | `core/managers/memory_engine_crud.py:63-72` |
| P1 检索 | `await engine.search_memories(query, k=5, session_id=None, persona_id=None, *, extra_scopes=None) -> list[HybridResult]` | ✅ | `core/managers/memory_engine_recall.py:72-80` |
| P1 删除 | `await engine.delete_memory(memory_id: int) -> bool`；另有 `archive_memories(ids)` 软归档 | ✅ **支持删除** | `core/managers/memory_engine_crud.py:493`；`core/external_api.py:865` `archive_memories` |
| P2 工具函数 | `plugin.initializer` 注册的 `FunctionTool`：`memorize_long_term_memory`（写）、`recall_long_term_memory`（读）、`forget_long_term_memory`（删）、`read_memory_evidence`、`update_user_profile` | ⚠️ 依赖 `AstrAgentContext`，且需要 `event` 与人格/作用域上下文 | 工具名见 `core/tools/memory_memorize_tool.py:39`、`memory_search_tool.py:30`、`memory_forget_tool.py:49`；执行入口 `core/tools/memory_memorize_tool.py:106-160` |
| P3 内部存储类 | `storage/atom_store.py`（`insert(MemoryAtom)` / `search_fts`）、`storage/db_migration.py` | ⚠️ 需自算 embedding、自己处理 FTS/图索引一致 | `storage/atom_store.py:245`、`:357` |
| P4 不可写 | — | 本版本不是 P4 | — |
| 额外公开面 | **External Memory API**（HTTP，默认关闭，`127.0.0.1:7801`，需要插件内建 API Key） | ⚠️ 需用户先开启 `external_api.enabled` 并建 Key | `docs/external-api.md:5-11`、`:45-56` |

**本插件采纳**：P1（`initializer.memory_engine.add_memory / delete_memory`）+ P3 只读导出（默认关）。
`initializer` 是**非下划线**属性但属于实现细节 → 按红线 6 处理：`getattr` + 版本白名单 + `try/except` + 本节文档标注。

### 2.2 记忆数据结构

| 项 | 结论 | 依据 |
|---|---|---|
| 存储单元 | 文档级 memory + 可选 memory atom（带 TTL/decay） | `core/models/memory_atom.py:9-35`、`:55-70` |
| 作用域 | `session_id`（完整 UMO）+ `persona_id` + `extra_scopes`；有频道级作用域概念 | `core/memory_scope.py:313-357`、`merge_memory_scopes` |
| importance | **float 0.0–1.0**，默认 0.5 | `memory_engine_crud.py:66` |
| metadata | 自由 dict，内部会补 `adapter_id`、`persona_id` 等 | `memory_engine_crud.py:100-125` |
| 长度上限 | 未在 `add_memory` 内硬截断；外部 API 请求体上限 256 KiB | `docs/external-api.md:23` |
| 二次摘要阈值 | 由 consolidation 管理 | `core/managers/consolidation_manager.py` |
| tags | 以工具参数 `topics`（≤5）表达；引擎层走 `metadata`/atom topics | `core/tools/memory_memorize_tool.py:55-62` |

**本插件结论**：`importance` 需要从我们的 1–5 整数映射到 0.3/0.5/0.7/0.85/0.95；`tags` 拼进 `content` 末尾不可行 → 走 `metadata={"topics":[...]}`（`add_memory` 的 `metadata` 参数）。

### 2.3 去重 / 检索 / 更新 / 删除

| 能力 | 结论 | 依据 |
|---|---|---|
| 去重 | 写入路径内有 dedup（similar pair 判定 + supersede） | `core/managers/memory_engine_crud.py:269`（`update_memory`）、`memory_engine_recall.py:670`（`find_similar_pairs`）、`:690`（`find_similar_memory`） |
| 检索 | 混合检索（向量 + BM25 + 图检索 + RRF 融合），非纯向量 | `core/retrieval/hybrid_retriever.py`、`core/retrieval/rrf_fusion.py` |
| update | ✅ `update_memory(...)` | `memory_engine_crud.py:269` |
| delete | ✅ `delete_memory`、`archive_memories` | `crud.py:493` |
| **本插件结论** | 删除传播可做到「真删除」，失败才标 `orphan`；但 `delete_memory` 只认**它自己的整型 id**，所以 `memory_sync.remote_ref` 必须存我们解析出的 doc_id（`add_memory` 返回值） | — |

### 2.4 版本锁定与降级

- 已验证版本：`2.13.0`。适配器 `SUPPORTED_VERSIONS = {"2.13.0"}`（区间内可放宽，见代码注释）。
- 版本不符：`probe()` 返回 `False` + WARN，不抛异常；`/info` 与 `GET /study/setup` 如实显示原因。
- 结构探测（`initializer.memory_engine` 不存在）同样降级到下一个适配器。

---

## 3. 调研受阻与替代方案

| 事项 | 状态 | 替代方案 |
|---|---|---|
| 本机没有 AstrBot 运行时（无 `main.py` 可启动的部署、无 QQ 平台） | 受阻滞 | 交付 `tests/harness/` 假 `astrbot` 包 + `scripts/selfcheck.py`；依赖真机的验收项在 `docs/KNOWN_ISSUES.md` 标 `PENDING` 并给出真机步骤。**不伪造** |
| 本机无 Node.js 全局安装 | 已解决 | 使用 DSH 运行时自带的 Node `v24.21.0`（`...\dependencies\node\bin\node.exe`）与 `pnpm`，路径写入 `Makefile`/文档 |
| 本机无 Rust / Android SDK / macOS（Tauri、Capacitor 打包） | 受阻滞 | `frontend/src-tauri/` 与 `capacitor.config.ts` 配置随仓库交付并文档化；`exe/apk` 产物标记 `PENDING`，给出命令与前置条件 |
| LivingMemory 全量集成测试（需要 faiss/embedding 模型） | 受阻滞 | 用「结构级 mock」覆盖适配器逻辑（`tests/test_adapters.py`）；真实联调步骤写入 `docs/MEMORY_SYNC.md` |

---

## 4. 结论汇总（决定实现的 6 条）

1. **不自造平台 API**：Star 子类 + `@filter.command` + `context.send_message` + `context.get_all_providers`，全部按上面行号实现。
2. **HTTP 必须自建**：插件路由只能在 Dashboard 鉴权后访问（`plugins.py:398-440`），App 无法只凭绑定令牌调用。
3. **UMO 只从事件取**：`event.unified_msg_origin`，落库为字符串，推送时原样回传 `context.send_message`。
4. **配置全部走 `_conf_schema.json`**，密钥绝不写进配置（明文 JSON），手填 Key 只进加密列。
5. **记忆适配器必须以 `probe()` 能力探测为中心**：没装任何记忆插件时 `null` 适配器恒可用，插件状态必须是"正常"。
6. **版本声明 `>=4.24.2,<5`**：与 LivingMemory 2.13.0 的声明对齐，避免"装了也一定崩"的组合。
