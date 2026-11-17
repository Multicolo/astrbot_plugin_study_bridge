# MARKETPLACE — 上架要求与兼容性

## 1. 官方要求（逐条对照）

依据：AstrBot 官方文档 `docs/zh/dev/star/plugin-publish.md`（本地快照 2026-11-17）与
`astrbot/core/star/{star_manager,updater}.py`。

| 要求 | 本插件 | 证据 |
|---|---|---|
| 仓库名 `astrbot_plugin_<name>`，且与 `metadata.yaml` 的 `name` 一致 | ✅ `astrbot_plugin_study_bridge` | `metadata.yaml:1` |
| `metadata.yaml` 位于仓库根目录 | ✅ | 仓库根 |
| 必填字段 `name` `desc` `version` `author` | ✅ | `metadata.yaml`；校验常量见 `star_manager.py:29` |
| 版本号语义化 | ✅ `1.0.0` | `metadata.yaml:20` |
| `desc` 支持多行 Markdown | ✅ | |
| `astrbot_version` 版本区间 | ✅ `">=4.24.2,<5"` | 与 LivingMemory 2.13.0 对齐，避免"装了必崩" |
| 通过 AstrBot Cloud 发布页提交（不是提 PR） | 已按该流程准备 | `https://cloud.astrbot.app/publish` |
| 插件图标 | ✅ 仓库根目录 `logo.png`（256×256），AstrBot 自动读取 | `star_manager.py: logo_fname = "logo.png"` |
| zip ≤ 16MB | ✅ 约 0.4 MB | `python scripts/package_plugin.py` 会打印大小 |
| 不包含 `__pycache__` / `node_modules` / `.git` | ✅ 打包脚本显式排除 | `scripts/package_plugin.py` |
| 插件可被禁用/卸载而不残留 | ✅ `terminate()` 取消调度、关 HTTP、关 DB | `main.py:terminate` |
| 插件加载失败不影响其它插件 | ✅ 异常全部被捕获并记录 | `main.py:initialize` / `star_manager.py:870` |

发布前自检命令：

```bash
python scripts/selfcheck.py       # 文件/元数据/schema/i18n/运行期/密钥
python scripts/lint_secrets.py    # 红线：grep 必须为空
make test                         # 后端 150 个用例
make build                        # 前端产物到 web/
python scripts/package_plugin.py  # 打 zip 并检查 16MB
```

## 2. 配置项规范

依据 `docs/zh/dev/star/guides/plugin-config.md`：

| 要求 | 本插件 |
|---|---|
| 每个配置项必须有 `type` | ✅ |
| 每个配置项有 `description`（中文） | ✅ 全部中文 |
| 每个配置项有 `default` | ✅ 除 `_special` 选择器外全部有；`selfcheck.py` 会校验 |
| 高风险项加提示 | ✅ `http.enabled/host/port`（`obvious_hint`）、`allowed_qq/groups`、`scope.group_mode`、`memory.sync_mode`、`memory.adapter_order` |
| 不使用 `secret: true` 存真密钥 | ✅ 手填 Key 只走 `PUT /ai/manual` 加密入库，配置里没有 Key 字段 |

**为什么没有 `access_token` 配置项**：本插件不用「静态共享令牌」，而是「绑定码 → 一次性兑换 → 可吊销的设备令牌」。
静态令牌一旦泄漏无法只吊销某一台设备，也容易在配置里被明文复制。相关高风险项已用
`http.host` / `http.allowed_origins` 的安全提示覆盖。

## 3. 兼容性矩阵

### 3.1 AstrBot 版本

| AstrBot | 状态 | 说明 |
|---|---|---|
| `< 4.24.2` | ❌ 不加载 | `metadata.astrbot_version` 拦截；运行期再 WARN 一次（不崩） |
| `4.24.2 – 4.30.x` | ✅ 目标区间 | 依赖的公开 API：`Star` / `filter.command` / `context.send_message` / `get_all_providers` / `llm_generate` / `get_registered_star` / `get_llm_tool_manager` / `StarTools.get_data_dir` |
| `>= 5.0` | ⚠️ 未验证 | 声明里已排除；升级前请先看 CHANGELOG |

> 本机验证的是 **源码快照**（`master`，4.30.0-alpha.1）的 API 形状；真机加载属于 `KNOWN_ISSUES` 里的 PENDING 项。

### 3.2 平台适配器

| 平台 | 指令 | 主动推送 | 说明 |
|---|---|---|---|
| `aiocqhttp`（NapCat / LLOneBot 等） | ✅ 主路径 | ✅ | `event.unified_msg_origin` 直接用作 UMO |
| `qq_official` | ✅ 理论兼容 | ⚠️ | 官方 API 对主动消息有限制，`send_message` 可能返回 False（会如实记 failed） |
| `telegram` / `discord` / `slack` 等 | ✅ 理论兼容 | ✅ 理论兼容 | 插件只依赖 `event` 的公开方法，不拼 UMO |
| `webchat` | ✅ 理论兼容 | ✅ | — |

### 3.3 记忆插件

| 插件 | 版本 | 写入 | 删除 | 下行 | 状态 |
|---|---|---|---|---|---|
| （无） | — | 本地库 | 本地库 | 不支持 | ✅ 默认，全功能可用 |
| 任意注册了写/读 tool 的插件 | — | `tool.handler` | 不支持→orphan | 不支持 | ✅ 通用映射（单测覆盖） |
| `astrbot_plugin_livingmemory` | **2.13.0** | `initializer.memory_engine.add_memory` | `delete_memory` | `list_memories_page` | ✅ 结构级单测；真机联调 PENDING |
| `astrbot_plugin_livingmemory` | 其它版本 | — | — | — | ⚠️ 自动降级 + WARN，不崩 |

### 3.4 部署形态

| 形态 | 状态 | 备注 |
|---|---|---|
| A 纯 QQ（`http.enabled=false`） | ✅ | 指令/推送/AI/计划全可用 |
| B 局域网 | ✅ | 单测 + E2E 覆盖 HTTP 全链路 |
| C 反代 + 域名 + HTTPS | ✅ 文档完整 | 需用户侧 Nginx（未在本机实测真实域名） |
| D 内网穿透（Cloudflare / frp / Tailscale） | ✅ 文档完整 | 同上 |

### 3.5 客户端

| 端 | 构建 | 状态 |
|---|---|---|
| Web | `pnpm build` → `web/` | ✅ 已构建并在 E2E 中验证 |
| Android | `android/build_apk.ps1`（免 Gradle，aapt2/javac/d8/apksigner） | ✅ **`dist/StudyBridge.apk` 已产出**（25 KB，badging/signature 已验证；未上真机） |
| Windows（Tauri 2） | `frontend/src-tauri/` | ⏳ 需 Rust 工具链（本机没有，见 KNOWN_ISSUES） |
| iOS | Capacitor | ⏳ 需 macOS + Xcode |

> 安卓客户端是仓库自带的原生 WebView 外壳（`android/`），不是 Capacitor 产物；
> 两者并存：想用官方 Capacitor 路线时配置在 `frontend/capacitor.config.ts`。
> 三端共用同一份 `frontend/` 源码与同一个后端地址；"三端同步"不需要自建同步服务。

## 4. 审查清单（提交前）

- [x] 无硬编码密钥（`python scripts/lint_secrets.py` 为空）
- [x] 无 `threading` 常驻线程（全 asyncio）
- [x] 无 monkey patch / 无 `sys.modules` 篡改 / 不写别人的表
- [x] 无第三方记忆插件硬依赖（`none` 适配器恒可用）
- [x] 指令名可命名空间化（`/study <sub>`），不抢优先级
- [x] `terminate()` 释放端口、取消任务、关闭 DB
- [x] 数据目录只用 `data/plugin_data/astrbot_plugin_study_bridge/`
- [x] 中英文案齐备（缺 key 回退中文）
- [x] 迁移失败拒绝启动且不留半迁移状态
- [x] 越权统一 404
- [x] 日志不含明文 Key / Token / 完整内网地址

## 5. 版本兼容性维护策略

1. **AstrBot 升级**：先跑 `python scripts/selfcheck.py` + `pytest`；关注 `Star` / `context.*` 的方法签名变化；
2. **LivingMemory 升级**：把新版本号加进 `adapters/livingmemory.py` 的 `SUPPORTED_VERSIONS` 前，
   必须先确认 `initializer.memory_engine.add_memory / delete_memory` 签名没变；
3. **本插件发版**：`metadata.yaml.version`、`CHANGELOG.md`、`core/app.py:PLUGIN_VERSION` 三处同步。
