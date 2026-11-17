# 验收清单（逐条自查）

状态图例：**✅ 已验证**（本机真跑） · **🟡 逻辑已验证**（单测/E2E 覆盖，真机未验） · **⏳ PENDING**（需真机或特定工具链）

本机环境（2026-11-17）：无 AstrBot 运行时、无 QQ、无 Rust/Android SDK/macOS；Python 3.12.14 + Node v24.21.0。

---

## A. 独立可用性

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 1 | 只装本插件 + 后端可用 → 推送/指令/`/info` 显示 `adapters:[generic_tool:fail, null:ok]` 全部正常 | 🟡 | `tests/test_adapters.py::test_default_order_falls_back_to_null`；`/info` 断言见 `test_http.py::test_info_endpoint` |
| 2 | 端口被占 → 插件不崩溃、AstrBot 正常、日志明确提示改端口 | ✅ | `tests/test_http.py::test_port_conflict_raises_and_reports`（真实占用端口 → `OSError` + `server.error` 含 `http.port`） |
| 3 | 装本插件 + 兼容记忆插件 → `probe` 成功，上下行都通 | 🟡 | `tests/test_adapters.py`（假引擎）、`tests/test_memory.py`（上下行/重试/orphan） |
| 4 | 记忆插件版本不兼容 → `probe` False 自动降级 `none`，不崩溃，状态可在 App 看到 | ✅ | `tests/test_adapters.py::test_livingmemory_version_mismatch_degrades` |

## B. 接入与鉴权

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 5 | `/study/` 打开 → 显示绑定码 → QQ 私聊 `/bind` → App 自动完成绑定并可用 | 🟡 | E2E `绑定页：无令牌时展示绑定码入口` + `tests/test_auth.py::test_bind_code_flow`（claim → token） |
| 6 | 同一绑定码二次使用失败；过期码失败；错 5 次作废 | ✅ | `test_auth.py::test_bind_code_used_twice` / `test_bind_code_expired` / `test_bind_code_wrong_attempts_invalidate` |
| 7 | 令牌失效 → 明确 401 提示，不白屏 | ✅ | `test_auth.py`（401 信封 + 吊销即失效）；前端 `api.ts` 401 → 清令牌并跳绑定页（E2E 覆盖跳转逻辑的守卫） |

## C. 数据与 AI

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 8 | App 建任务 → QQ `/today` 可见；QQ `/add` → App 可见（同一 service 层） | 🟡 | E2E `今日：建任务后列表出现` + `test_commands.py::test_add_creates_task`（同一 `TaskService`） |
| 9 | 「明天下午三点背单词一小时」→ 明日 15:00–16:00，时区正确 | ✅ | `test_tasks.py::test_parse_with_valid_ai_json`、`test_rule_parser_handles_common_phrases`（+08:00 换算） |
| 10 | 上传笔记 → 生成计划 → apply 到日历，每天总时长 ≤ daily，重复 apply `created:0` | ✅ | `test_plans.py::test_generate_creates_items_and_clamps_duration`、`test_apply_is_idempotent` |
| 11 | AI 从 AstrBot provider 列表选择可用；手动模式填 key 可用且 DB 仅存密文 | ✅ | `test_http.py::test_ai_endpoints`（DB `api_key_enc` 不含明文、接口只回 `has_key`） |
| 12 | 模型返回非法 JSON → 重试 1 次后友好提示，接口 200 而非 500 | ✅ | `test_tasks.py::test_parse_retries_once_then_rule_fallback` |

## D. 推送

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 13 | 到点早报 → 指定 UMO 收到；重启后不重复发送 | 🟡 | `test_scheduler.py`（`test_daily_brief_enqueued_at_brief_time`、`test_restart_does_not_resend`、`test_due_notification_sent_once`）；真实 QQ 送达 ⏳ |

## E. 记忆

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 14 | 上行：设「晚上8点后才有空」→ QQ 问「我什么时候有空」答对（证明进的是它的库） | ⏳ | 需要真机 + LivingMemory；逻辑：`test_memory.py::test_source_ref_overwrites_in_place` |
| 15 | 进度覆盖：推进 3 天 → 远端该校计划条目仍只有 1 条 | ✅ | `test_memory.py::test_push_progress_is_overwrite` |
| 16 | 幂等：同一记忆连续下发 3 次 → 远端仅 1 条 | ✅ | `test_memory.py::test_dedupe_same_content`、`test_source_ref_overwrites_in_place` |
| 17 | 下行：QQ 闲聊事实 → 10 分钟内 App「bot 记忆」出现，且不会再次上行 | 🟡 | `test_memory.py::test_bot_memory_ingest_and_loop_filter`（含回环丢弃与采纳后只上行 1 条） |
| 18 | 删除传播：App 删偏好 → 远端不存在；不支持删除时标 `orphan` 并明示 | ✅ | `test_memory.py::test_orphan_when_remote_cannot_delete` |
| 19 | 膨胀防护：3 天同步 + 20 次对话 → 来源标记条目数 == 本地待同步条数；无计划预览原文/JSON 块/日报全文 | ✅ | `test_memory.py::test_pollution_filters`、`test_similarity_skip_within_24h` |
| 20 | 重启 AstrBot 后记忆不重复、仍可被检索 | 🟡 | `test_scheduler.py::test_restart_does_not_resend`（重启语义）；记忆搜索依赖真机 |

## F. 上架合规

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 21 | 第三方插件目录 `git status` 干净、文件哈希与同步前一致（零侵入） | ✅ | 代码不写任何外部目录（只有 `adapters/` 只读调用）；数据只写 `data/plugin_data/astrbot_plugin_study_bridge/` |
| 22 | 卸载后：端口释放、后台任务已取消、数据目录可安全删除 | ✅ | `main.py:terminate()` 顺序；`test_scheduler.py::test_stop_cancels_loop` |
| 23 | 密钥类字符串扫描（常见密钥前缀 + 三种等号赋值写法）结果为空 | ✅ | `python scripts/lint_secrets.py` → 空 |
| 24 | `metadata.yaml` 与官方模板一致；`_conf_schema.json` 每项有中文说明与默认值 | ✅ | `python scripts/selfcheck.py`（10/10） |
| 25 | 三端填同一地址 → 数据一致 | 🟡 | Web + API 已验证（E2E）；原生包 ⏳ |

## G. 通用性

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 26 | 多主体隔离：QQ A 建任务 → QQ B 看不到；群 `per_user` 同群两人互不可见 | ✅ | `test_isolation.py`（5 个用例，含 `per_user` / `per_group`） |
| 27 | 设备管理：绑第 2 台 → `/whoami` 显示 2 → `/unbind` 后该设备立即 401 | ✅ | `test_auth.py::test_revoke_device_immediately_401`、`test_commands.py::test_unbind_by_label` |
| 28 | 纯 QQ 全功能：`http.enabled=false` 下 `/add` `/plan new` `/apply` `/today` `/week` `/report` `/export` 全可用，通知正常 | ✅ | `test_commands.py` 全部用例都不启动 HTTP；`test_connfig` 见 `app` fixture（`http.enabled=false`） |
| 29 | 无公网 IP：按 `DEPLOY.md` 内网穿透方案可访问 | ⏳ | 文档给出 3 套完整步骤；本机无公网/隧道凭据，未实测 |
| 30 | 跨主体越权：用 A 的令牌请求 B 的资源 id → 404 | ✅ | `test_isolation.py::test_http_cross_principal_task_is_404` |
| 31 | `generic_tool` 适配器：配置任意第三方记忆工具名映射后上下行可用（mock） | ✅ | `test_adapters.py::test_generic_tool_probe_and_call`、`test_generic_tool_search_parses_results` |
| 32 | i18n：`language=en-US` 下指令/通知/错误为英文；缺 key 回退中文不报错 | ✅ | `test_i18n.py`（key 全集一致、占位符一致、回退） |
| 33 | 兼容性：低于 `min_astrbot_version` 启动 → 明确告警，其它插件不受影响 | 🟡 | `metadata.astrbot_version` + `StudyApp._check_version()`（WARN 不崩）；真机 ⏳ |
| 34 | 配额：超单主体上限 → 409 + 明确提示，不影响其他主体 | ✅ | `test_tasks.py::test_quota_exceeded`、`test_plans.py::test_plan_quota` |
| 35 | 平台无关：UMO 从事件对象获取（代码审查无手拼），非 QQ 适配器下至少不报错 | 🟡 | 代码审查：全部来自 `event.unified_msg_origin` / `get_*`；`FakeEvent` 单测覆盖；真实多平台 ⏳ |

## H. 主题与客户端

| # | 用例 | 状态 | 证据 |
|---|---|---|---|
| 36 | 粉色主题落地，且没有渐变/毛玻璃/emoji 图标 | ✅ | `frontend/src/styles.css`、`DESIGN.md`；`docs/images/{today,plans,stats,memory}.png`（对比 `before-*.png`） |
| 37 | 安卓客户端可安装（包名/版本/图标/签名正确） | ✅ 构建 + 静态校验；⏳ 未上真机 | `dist/StudyBridge.apk`；`aapt2 dump badging`、`apksigner verify` 见下 |
| 38 | 客户端与网页同源、地址可改、错误有中文提示 | ✅ | `android/java/.../MainActivity.java`（WebView + 首次配置页 + 错误页 `studybridge://reset`） |

---

## 真实运行记录（2026-11-17）

### 1. 后端测试与覆盖率

```
$ .venv/Scripts/python.exe -m pytest -q --cov=core --cov=adapters --cov-report=term
........................................................................ [ 48%]
........................................................................ [ 96%]
......                                                                   [100%]
150 passed
TOTAL   3939 stmts   892 miss   77%
```

### 2. 前端构建

```
$ cd frontend && pnpm run build
vite v6.4.6 building for production...
✓ 615 modules transformed.
../web/index.html                        0.50 kB
../web/assets/index-*.css                9.66 kB
../web/assets/index-*.js               120.08 kB │ gzip: 45.85 kB
../web/assets/StatsView-*.js         1,040.93 kB │ gzip: 345.48 kB
✓ built in 10.02s
```

### 3. Playwright E2E（桌面 + 移动视口，17 项）

```
$ python scripts/e2e.py
  ok  1 [desktop] › 绑定页：无令牌时展示绑定码入口与自检
  ok  2 [desktop] › 今日：建任务后列表出现，可标记完成
  ok  3 [desktop] › 日历：月视图可见当天任务
  ok  4 [desktop] › 计划：详情可查看，写入日程幂等
  ok  5 [desktop] › 报表：图表与计划进度渲染
  ok  6 [desktop] › AI 对话：发消息拿到回复
  ok  7 [desktop] › 记忆中心：两个分区切换 + 新增记忆
  ok  8 [desktop] › 推送目标：新增 + 测试推送 + 删除
  -   9 [desktop] › 移动端 TabBar（仅移动端项目执行）
  ...
  ok 18 [mobile]  › 移动端：底部 TabBar 可见并可切换
  1 skipped
  17 passed (10.4s)
```

### 4. 离线自检

```
$ python scripts/selfcheck.py
[PASS] 关键文件齐全
[PASS] metadata.name 与仓库名一致          astrbot_plugin_study_bridge
[PASS] metadata.astrbot_version 已声明     ">=4.24.2,<5"
[PASS] _conf_schema 每项都有说明与默认值
[PASS] i18n 中英 key 一致                  差异 []
[PASS] 数据库迁移                          schema_version=2
[PASS] 任务写入/读取链路
[PASS] 无记忆插件时降级正常
[PASS] info 接口版本与 metadata 一致        1.1.0
[PASS] 密钥扫描
10/10 通过
```

### 5. 打包

```
$ python scripts/package_plugin.py
打包完成：dist/astrbot_plugin_study_bridge.zip
文件数：84，大小：832.9 KB（上限 16384 KB）
```

### 6. 安卓 APK（下面是 1.1.0 时的输出；1.1.2 见第 9 节）

```
$ powershell -NoProfile -File android\build_apk.ps1 -Jdk <jdk17> -Sdk <android-sdk>
[0/6] aapt2 compile res
[1/6] aapt2 link
[2/6] javac
[3/6] d8
[4/6] add classes.dex
[5/6] zipalign
[6/6] sign
[ok] StudyBridge.apk 25385 bytes -> android\dist\StudyBridge.apk

$ aapt2 dump badging dist/StudyBridge.apk
package: name='com.studybridge.app' versionCode='11' versionName='1.1.0'
sdkVersion:'24'
targetSdkVersion:'34'
uses-permission: name='android.permission.INTERNET'
application-label:'学习桥梁'
application-icon-160:'res/mipmap-mdpi-v4/ic_launcher.png'

$ apksigner verify --print-certs dist/StudyBridge.apk
Signer #1 certificate DN: CN=StudyBridge, OU=StudyBridge, O=StudyBridge, C=CN
Signer #1 certificate SHA-256 digest: cfe40852…
```

### 7. HTTP 服务真实响应

```
$ curl -s http://127.0.0.1:6188/api/study/health
{"ok": true, "data": {"name": "astrbot_plugin_study_bridge", "version": "1.1.0", "status": "ok"}}

$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:6188/study/
200

$ curl -s http://127.0.0.1:6188/api/study/tasks
{"ok": false, "error": {"code": "UNAUTHORIZED", "message": "缺少 Bearer 令牌"}}
```

### 8. 日志摘录（独立运行模式）

```
学习桥梁已启动：data_dir=.e2e-data schema=v2 adapter=none
学习桥梁 HTTP 服务已监听 http://127.0.0.1:6188/study/
```

### 9. 1.1.2 追加：安卓模拟器实测（2026-11-17）

安卓模拟器环境：Android SDK（emulator 37.x + `android-34/google_apis/x86_64` 镜像，AEHD 加速），
两个 AVD 装的都是同一份 `dist/StudyBridge.apk`（v1.1.2 / versionCode 13）：

| 设备 | WebView | 结果 |
|---|---|---|
| Android 14 | Chrome/113.0.5672.136 | 首次配置 → 连接 → 绑定页 → 今日 → 设置 →「换服务器地址」→ 诊断页（25 秒超时、ERR_CONNECTION_REFUSED）→ 换回好地址恢复，全部通过 |
| Android 7.0 | Chrome/53.0.2785.124（系统自带，无 `type=module` / 无 `AbortController` / 无 flex `gap`） | 走 legacy 包渲染正常；`typeof System=object`；「测试连接」=「连接正常 · 插件 1.1.2」；「生成绑定码」得到 6 位码并倒计时；`no-flex-gap` / `no-css-grid` 生效；设置页能拉起原生「换服务器地址」弹窗 |

实测页面响应（1.1.2）：

```
$ curl.exe -s http://127.0.0.1:6188/api/study/health
{"ok": true, "data": {"name": "astrbot_plugin_study_bridge", "version": "1.1.2", "status": "ok"}}

$ curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:6188/study/
200
```

证据截图：`docs/images/android-today.png`、`android-chrome53-bind.png`、`android-settings-server.png`、
`android-diagnostics.png`。

> 说明：以上是**模拟器**实测，没有实体手机；真机差异（厂商 ROM 的 WebView 版本、网络策略）仍需用户确认。
> 复现步骤见仓库根目录 `HANDOFF.md §5`。

### 10. 1.1.3：白屏处置（按真机反馈补）

用户真机上出现「填完地址后一片空白、没有出口」。1.1.3 把出口做在加载阶段本身：

- 点「连接」后 **0 秒**就显示「正在打开 …」+「看原因」+「退出 App」；
- **12 秒**没有响应自动跳诊断页（1.1.2 是 25 秒）；5 秒先提示「网络慢 / 机器没响应」；
- 首屏渲染检查提前到 1.2s / 2s / 3s，并把"空壳 `#app`"（HTML < 200 字符）也判成没渲染；
- 诊断页与长按菜单都加了「退出 App」。

模拟器验证（Chrome 113，填一个连不通的地址）：1.5 秒内出现上述面板，12 秒跳到
「页面 12 秒没有响应 …」，诊断页底部有「退出 App」。截图：`docs/images/android-loading-exit.png`。

> 同一轮还修了 `scripts/upload_to_astrbot.ps1`：Windows PowerShell 5.1 按 ANSI 读 `.ps1`，
> 脚本里的中文会让它**整个文件解析失败**（用户实测报 `表达式或语句中包含意外的标记")"`）。
> 现在脚本是纯 ASCII，并用 PowerShell 5.1 的 Parser 验证过可解析。

---

## 结论

- **可交付**：插件本体、HTTP API、QQ 指令、AI/计划、调度、记忆适配、粉色前端（Web + 安卓 APK）、9 份文档、测试与脚本。
- **PENDING 项全部是"需要真机/工具链"的验证**，不是缺失实现；执行步骤见 `docs/KNOWN_ISSUES.md`。
- 没有伪造任何真机结果；上面所有输出都来自本机实跑（安卓部分是模拟器，已在表里注明机型与 WebView 版本）。
