# KNOWN_ISSUES — 未完成项与规避方式

> 原则：**没有验证过的不写"已验证"**。下面每条都写清「为什么没做」「怎么绕」「真机怎么验」。

环境事实（2026-11-17，1.1.5 时更新）：本机 **没有** AstrBot 运行时、没有 QQ 平台、没有 Rust、没有 macOS、
没有实体安卓手机；**有** Android SDK（emulator 37.x + android-34/google_apis/x86_64 镜像，AEHD 可加速）与 JDK 17，因此安卓端可以真跑模拟器（含 Android 7.0 的旧 WebView）；
Node 用 DSH 自带版本（v24.x + pnpm），不装全局。

> 关于用户真机：如果你的手机还是白屏，先看 App 自己给出的诊断页（WebView 版本 / JS 报错 / 资源状态），
> 版本低于 Chrome 61 请先更新系统里的「Android System WebView」或 Chrome。

---

## PENDING（需要真机/特定工具链）

### 1. AstrBot 真机加载与指令注册

- **状态**：未在本机验证（本机无 AstrBot 实例）
- **已做的替代验证**：
  - 读源码确认 API 形状（见 `docs/RESEARCH.md`，带文件+行号）；
  - `core/bridge.py` 让同一份 `main.py` 在无 AstrBot 时也能导入并被测试直接调用；
  - `pytest` 覆盖指令层逻辑（`tests/test_commands.py`）；
  - 注意点已落实：**指令装饰器必须写在 `main.py` 模块的类里**，因为 AstrBot 按
    `handler_module_path == 插件 main 模块路径` 精确匹配激活 handler（`star_manager.py:1274-1279`）。
- **真机执行步骤**：
  1. 装 AstrBot 4.24.2+，把插件放进 `data/plugins/`；
  2. 重载插件，日志应出现 `学习桥梁已就绪`；
  3. 私聊发 `/help`，应看到中文指令列表；
  4. 面板「插件」页应显示 `astrbot_plugin_study_bridge 1.0.0`。
- **规避**：纯 QQ 与 HTTP 两条链路都不依赖真机即可自测（`python -m core.standalone`）。

### 2. LivingMemory 真机联调

- **状态**：仅做结构级单测（假引擎），未在装了 LivingMemory 2.13.0 的实例上验证
- **风险**：其 `initializer.memory_engine.add_memory` 的参数可能在未来版本变化
- **已做的防护**：版本白名单 `SUPPORTED_VERSIONS={"2.13.0"}`、`getattr` 探测、全部 `try/except`、
  失败降级到 `none` 且 `/info` 如实显示原因
- **真机步骤**：见 `docs/MEMORY_SYNC.md §8`

### 3. 真实 QQ 推送到达

- **状态**：调度与发送逻辑有单测（sender 为 mock），未在真实 QQ 上验证到点送达
- **已做**：`dedupe_key` 唯一索引 + `__job:*` 标记 → 重启不重发（单测覆盖）；失败重试 3 次后置 `failed`
- **真机步骤**：
  1. App「推送目标」加一个 UMO（或 QQ `/umo` 拿）；
  2. 把 `notify.early_brief_time` 改成 2 分钟后；
  3. 等待，应收到早报；重启 AstrBot 后今天不应再收到第二条。

### 4. Windows（Tauri）打包与 iOS

- **Android（1.1.5）**：`android/build_apk.ps1` 用本机 Android SDK（build-tools 34.0.0 + platform 34）
  免 Gradle 打包，产出 `dist/StudyBridge.apk`（517.8 KB / v1.1.5 / versionCode 16），
  `aapt2 dump badging` 与 `apksigner verify` 均通过。
  **已在安卓模拟器上逐屏实测**：
  - Android 14 / WebView Chrome 113：首次配置 → 连接 → 绑定页 → 今日 → 设置 → 换服务器地址 →
    诊断页（25 秒超时 / ERR_CONNECTION_REFUSED）→ 换回好地址恢复；
  - Android 7.0 / 系统自带旧内核（切到 `com.google.android.webview`，Chrome/53.0.2785.124，
    没有 `type=module`、没有 `AbortController`、没有 flex `gap`）：页面走 legacy 包正常渲染，
    测试连接返回「连接正常 · 插件 1.1.5」，生成绑定码可得 6 位码并倒计时，设置页能拉起原生的
    「换服务器地址」弹窗。
  - **仍未在实体手机上手测**（本机无实体设备）；真机差异主要在厂商 ROM 的 WebView 版本与网络策略。
- **Windows 仍未产出**：`frontend/src-tauri/` 配置齐全，但本机没有 Rust 工具链。
- **iOS 仍未产出**：需要 macOS + Xcode。
- **安卓真机验证步骤**：
  1. 把 `dist/StudyBridge.apk` 传到手机，允许"安装未知来源"后安装；
  2. 首次打开填 `http://<电脑内网IP>:6188`；
  3. 页面应加载出「绑定与自检」，生成 6 位码 → QQ `/bind`；
  4. 断网/填错地址时应看到中文诊断页（地址、WebView 版本、JS 报错、HTTP 状态）与
     「重新加载 / 在系统浏览器里打开 / 换一个地址 / 复制诊断信息」。
- **Windows 打包命令**：

```bash
cd frontend && pnpm install && pnpm add -D @tauri-apps/cli
pnpm exec tauri build          # 产物在 frontend/src-tauri/target/release/bundle/
```

- **注意**：`android/studybridge.jks` 是自用签名密钥（密码 `studybridge`），**正式发布请替换**。

### 5. 内网穿透实测（Cloudflare Tunnel / frp / Tailscale）

- **状态**：`docs/DEPLOY.md` 形态 D 给出完整可执行步骤，但本机没有可用的公网域名/隧道凭据，
  **未端到端实测**
- **规避**：局域网形态（B）已用真实 HTTP 服务验证过；穿透只是多一层 TCP/HTTP 转发，插件侧配置不变

### 6. 非 QQ 平台（Telegram / Discord / Slack / webchat）

- **状态**：代码只使用 `event` 的公开方法（`unified_msg_origin` / `get_sender_id` / `get_group_id` /
  `is_private_chat` / `is_admin`），没有任何平台专有 API 或 UMO 手工拼接；但**未在多平台上实测**
- **标注**：文档中一律写"理论兼容"
- **已知差异**：`qq_official` 平台对主动消息有限制，`context.send_message` 可能返回 False
  → 插件会如实记 `failed`，不会假装成功

### 7. `metadata.astrbot_version` 版本拦截的真机表现

- **状态**：依据源码注释与代码路径（`star_manager.py:674-703`）实现，未在低版本 AstrBot 上实测
- **预期**：低于 4.24.2 时插件不加载、AstrBot 与其它插件正常，运行期再 WARN 一次

---

## 设计取舍（不是 bug，但要知道）

### A. 对话用 JSON 工具协议，不是 provider 原生 function calling

- 原因：不同 provider 原生 FC 支持不一致（OpenAI 系 / Anthropic / Gemini / Ollama 差异大），
  且原生 FC 难以离线复现测试
- 影响：模型需要能稳定输出 JSON。实测建议用指令调优较好的模型；规则解析始终兜底
- 已实现的等价能力：工具集定义、参数校验、错误回灌重试 1 次、最多 6 轮、写操作二次确认、审计日志

### B. `access_token` 配置项不存在

- 需求列了「`access_token`（高风险项）」提示，但本设计**没有静态共享令牌**：
  绑定码 → 一次性兑换 → 可吊销的每设备令牌，吊销粒度到设备
- 因此 `_conf_schema.json` 里没有该键；对应的高风险提示给了 `http.host` / `http.allowed_origins`

### C. HTTP 服务不挂 AstrBot Dashboard

- 原因见 `docs/RESEARCH.md §1.6`：插件路由只能在 Dashboard 鉴权后访问，App 只有本插件令牌，用不了
- 影响：多开一个端口（默认 6188）。若宿主未来提供匿名插件路由，可切换为挂载模式

### D. 限流只作用在 `/api/study/*`

- 原因：静态资源（JS/CSS）也计入 120/min 会让一次页面加载就触发 429
- 影响：静态页本身不受限；API 仍受 120/min + 鉴权失败封禁保护

### E. 计划 apply 的默认时段是 19:00

- AI 只给「日期 + 时长」，不指定几点。落库时统一按当天 19:00 开始，避免与上课时间冲突
- 需要精确时间时：`apply` 后在 App/QQ 里改单条任务即可（`updated_at` 变化会让 rollback 跳过它，这是有意的）

### F. 单实例假设

- 限流器与绑定失败计数在进程内存里。多进程/多实例部署时这些计数不共享（数据本身仍在 SQLite 里一致）
- 如果你想跑多实例：改用共享存储做限流，或只让一个实例开 HTTP

---

## 已知小问题

| 问题 | 影响 | 规避 |
|---|---|---|
| `/export` 超长时分段但最多 10 段 | 超大账号会截断 | 用 App「导出全量 JSON」或 `GET /api/study/export` |
| 中文数字只支持 0–99（"一百分钟"不识别） | 极端说法解析失败 | 用阿拉伯数字 |
| 英文自然语言解析覆盖较窄（today/tomorrow/at 3pm/for 1 hour） | 英文体验弱于中文 | 用 AI 模式（LLM 解析） |
| `/study <sub>` 与短指令重名时短指令可能被别的插件抢走 | 指令冲突 | 用 `/study add ...` 入口 |
| 前端 echarts 单独 chunk 约 1MB | 首屏不进报表页就不加载；进入时略慢 | 可接受；后续可按需引入 echarts 子模块 |
| 通知记录只保留最近 500 条展示 | 历史不可见 | 定期导出 JSON |

---

## 如何把 PENDING 变成 PASS

```bash
# 1. 本机（无 AstrBot）
make test          # 150 passed
make e2e           # 17 passed（自带种子数据）
make selfcheck     # 10/10
make package       # 产出 zip

# 2. 真机（AstrBot + QQ）
#    - 装插件 → 看日志 → /help → /today
#    - /bind 完成 App 绑定 → 建任务 → QQ /today 可见
#    - 设早报为 2 分钟后 → 收到 → 重启不重发
#    - 装 LivingMemory 2.13.0 → /info 看 adapter → 记忆上下行
#    - 换低版本 AstrBot（<4.24.2）→ 应被 metadata 拦截且其它插件正常

# 3. 打包机（Rust / Android SDK）
pnpm exec tauri build
pnpm exec cap sync android && pnpm exec cap open android
```

把实测结果补进 `docs/README.md` 的验收表即可。
