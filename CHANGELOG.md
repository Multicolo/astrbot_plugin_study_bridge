# CHANGELOG

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [1.1.3] - 2026-11-17

用户反馈「白屏时没有退出的地方，而且不要等三十秒才给界面」，同时 `upload_to_astrbot.ps1`
在他的 Windows PowerShell 上直接**解析报错**（脚本里有中文）。这一版都修掉。

### 修复

- **白屏立刻有出口**：加载面板一出现就带「看原因」和「退出 App」两个按钮（0 秒可用，不用等任何超时）；
  诊断页和长按菜单也各加了「退出 App」。
- **不再等三十秒**：加载 5 秒提示"网络慢/机器没响应"，**12 秒**（原 25 秒）直接给诊断页；
  首屏渲染检查提前到 1.2s，失败再补 2s、3s（最迟约 6 秒出结论，原为 2.5/7.5/16.5 秒）。
- **把"空壳页面"也算白屏**：`#app` 有子节点但 HTML 长度小于 200 时也判为没渲染
  （以前只判 `children == 0`，某些内核会留下一个空壳导致一直空白）。
- **`scripts/upload_to_astrbot.ps1` 改成纯 ASCII**：Windows PowerShell 5.1 按 ANSI 读 `.ps1`，
  文件里的中文注释/字符串会让它把整个脚本读崩（`表达式或语句中包含意外的标记")"`）。
  现在脚本 0 个非 ASCII 字节，已用 PowerShell 5.1 的 Parser 验证可解析；中文说明留在 README/docs。
  顺手修了服务器没有 `unzip` 时 python 解压路径被转义成 `'\'` 的 bug；`-Restart` 现在会顺带打印
  `docker port astrbot` 与 `/api/study/health`，装完即可自证版本。
- **主机参数改名 `-Host` → `-TargetHost`**：PowerShell 里 `$Host` 是只读自动变量，
  `param([string]$Host)` 一绑定就抛 `无法覆盖变量 Host，因为该变量为只读变量或常量`。
  现在用 `-TargetHost`（兼容别名 `-HostName` / `-Server`），并在脚本头部写明原因。
- **scp/ssh 失败会打印真实原因**：以前把子进程的 stderr 吞掉，只剩一句
  `scp failed (check Host / Key / network)`；现在原样回显 scp/ssh 输出，并提示
  「查 key 权限」和「先用 ssh 试登录」两条自检命令。
  （PS 5.1 下 `$ErrorActionPreference=Stop` 会把原生程序的 stderr 当成终止错误，
  所以捕获时临时切成 `Continue`，否则提示根本打不出来。）
- **临时 key 副本改用唯一文件名**：之前固定用 `%TEMP%\sb_upload_key` 并收紧成只读，
  下一次运行 `Copy-Item -Force` 覆盖时会被拒绝（用户实测报“访问被拒绝”）。
  现在每次用 `sb_upload_key_<guid>`，清理前先 `icacls /grant:r 本人:(F)` 恢复删除权限。
- **远端解压修正（两处）**：
  1. **真因 CRLF**：这个 `.ps1` 是 Windows 换行，PowerShell 的 here-string 会把 `\r\n` 原样带进
     远端命令，远端 `sh` 收到的第一行变成 `set -eu\r` → dash 报非法选项并**以状态 2 直接退出**，
     脚本一行都没跑（所以 plugins 根其实没被污染，`astrbot_plugin_study_bridge/` 仍是用户 17:01
     自己装的那份）。现在发送前把 CRLF 归一成 LF，实测 payload 里 CR 字节为 0。
  2. **扁平 zip 的隐患**：`package_plugin.py` 产出的是**扁平 zip**（`main.py` / `core` / `web`
     直接在压缩包根，没有外层目录），直接 `unzip` 到 plugins 目录会把文件倒进 plugins 根。
     现在先隔离上一次的平铺残留到 `plugins/.sb_quarantine_<时间戳>/`（移动不删除、可恢复）、
     再解到暂存目录 `plugins/.sb_staging_<pid>/`、最后把 payload 移成
     `plugins/astrbot_plugin_study_bridge/`；`metadata.yaml` 缺失会明确 `exit 3`。
     这个逻辑用本地模拟“已被污染 + 有其它插件”的目录验证过：版本 1.1.3、`main.py`/`web/index.html`
     就位、其它插件不受影响、plugins 根无残留。
- **远端安装改成可诊断的一次性脚本**：脚本 base64 编码后用 `base64 -d > /tmp/sb_install.sh && sh -x`
  执行（`-x` 打印每一步），STEP 0 比对远端 zip 大小与本地产物（截断/旧包立刻 `exit 4`），
  STEP 3 优先 `python3 zipfile`（不依赖 unzip 的退出码语义）、失败时打印 `testzip` 与文件大小，
  STEP 5 校验 `metadata.yaml` 与 `main.py`。

### 变更

- 版本 1.1.2 → **1.1.3**（`metadata.yaml` / `core/app.py` / 安卓 `versionName` 三处同步，versionCode 14）。
  本轮只动安卓外壳与部署脚本，后端与 Web 前端无功能变化（`web/` 未重建）。

## [1.1.2] - 2026-11-17

这一版是"手机上真的能用"的收尾：第一次在安卓模拟器上把 APK 装起来跑，
在 **Android 14 / WebView Chrome 113** 与 **Android 7.0 / WebView Chrome 53（旧内核）** 两台机器上
逐屏验证，修掉了旧内核上"能显示但一点就错"和"没地方换地址"两个真问题。

### 修复

- **旧 WebView 上接口全挂**：`api.ts` 直接用 `new AbortController()` 做超时，而 Chrome < 66 没有这个 API，
  旧内核上每次请求都抛 `AbortController is not defined`——页面能显示，但点「测试连接」「生成绑定码」全失败。
  现在按能力降级：没有 AbortController 时用 `Promise.race` 超时，并给旧内核补上
  `es.string.pad-start`、`es.object.entries` 两个运行时 polyfill（旧内核上倒计时与报表会用到）。
- **旧 WebView 上间距全丢**：flex 的 `gap` 到 Chrome 84 才有，旧内核上按钮和文字贴在一起。
  `main.ts` 启动时做特性检测，只有不支持时才给 `<html>` 加 `no-flex-gap` / `no-css-grid`，
  用 margin 补齐间距、用 flex 兜住日历网格；现代浏览器完全不受影响。
- **旧内核上进设置页会被系统黄框"选中"**：按钮 focus 默认轮廓在旧 WebView 点一下就会出现，
  现在只在 `:focus-visible`（键盘操作）时显示。
- **换服务器地址没有可靠入口**：长按菜单在旧 WebView 上会被系统长按选词吃掉。
  新增 JS 窄接口 `StudyBridgeShell`（只暴露「换服务器地址」「重新加载」两个动作），
  网页「设置 → App 服务器地址 → 换服务器地址」直接拉起原生弹窗。**原来旧机型换了 IP 就只能重装 App。**
- **白屏诊断更靠谱**：
  - 加载期间显示「正在打开 …」，12 秒换成"网络慢/没响应"的提示，25 秒还没开就直接给诊断页
    （以前会一直停在空白或"正在打开"）；
  - 首屏渲染检查改为 2.5s / 7.5s / 16.5s 三次，慢手机不再被误判成白屏；
  - 诊断页把结论统一写成「检测结论：…」，WebView < Chrome 61 时额外提示去更新系统 WebView。
- **未绑定设备误报「令牌已失效」**：绑定页在没令牌时也会请求 `/info`（必然 401），
  以前会在「安装自检」里显示红色错误让人以为坏了；现在未绑定就保持空态。

### 变更

- 安卓外壳：状态栏改成粉色 `#FFF7FA` + 深色图标（以前是深灰条压在白页上）；
  API 33+ 关闭系统"强制深色"，避免粉色界面被反相成脏灰；版本 1.1.1 → **1.1.2**（versionCode 13）。
- 插件版本 1.1.1 → **1.1.2**（`metadata.yaml` / `core/app.py` / 安卓 `versionName` 三处同步）。

### 验证

- 模拟器实测（本机 Android SDK + AEHD 加速，两个 AVD）：
  - Android 14 / Chrome 113：安装 → 首次配置 → 连接 → 绑定页 → 今日 → 设置 → 换地址 → 诊断页 → 恢复，全部通过；
  - Android 7.0 / Chrome 53（切换 WebView 提供方到系统旧内核）：`typeof System === 'object'`（走 legacy 包）、
    `#app` 有渲染、测试连接返回「连接正常 · 插件 1.1.2」、生成绑定码可得 6 位码并倒计时。
  - 证据截图：`docs/images/android-*.png`。
- `pytest` 150 passed；Playwright E2E 19 passed / 1 skipped（新增"未绑定测试连接不报令牌失效"一条）；
  `scripts/selfcheck.py` 10/10。

## [1.1.1] - 2026-11-17

### 修复

- **在 AstrBot 4.29.x 上加载失败**：`main.py` 原先用 `logging.getLogger("astrbot.plugin.study_bridge")`，
  而 AstrBot 的日志队列处理器只给已注册的 plugin logger 注入 `plugin_tag` 字段，插件自己建的 logger
  记录格式化成 `[%(plugin_tag)s]` 时抛 `Formatting field not found in record: 'plugin_tag'`，
  直接把插件加载打断（真机实测：AstrBot 4.29.3）。改为优先使用官方 `astrbot.api.logger`
  （按调用方模块解析到本插件自己的日志器），取不到时才回退到原来的 getLogger。
- **安卓客户端白屏**：前端原来只产出 `type="module"` 的现代包，手机系统 WebView 停在 Chrome 6x/7x 时
  不支持 module 与 `??`/`?.`，表现就是**白屏且没有任何报错**。现在用 `@vitejs/plugin-legacy`
  （targets `android>=7 / chrome>=61`）同时产出 `nomodule` + `System.register` 旧版包与 `polyfills-legacy`，
  老 WebView 自动走兼容路径。
- **白屏不再"没法查"**：安卓外壳在页面加载后检查 `#app` 是否真的渲染出内容，为空则切到诊断页，
  显示 WebView 版本、JS 报错、HTTP 失败的具体资源 URL，并提供
  「重新加载 / 在系统浏览器里打开 / 换地址 / 复制诊断信息」；首次配置页也会显示 WebView 版本。
  另外打开 `WebView.setWebContentsDebuggingEnabled(true)`，可用 chrome://inspect 远程调试，
  长按页面有「刷新 / 换地址 / 用浏览器打开 / 清缓存重载」菜单。

## [1.1.0] - 2026-11-17

主题改成粉色 + 交付安卓客户端。

### 变更

- **粉色浅色主题**：`#FFF7FA` 底 + 玫瑰红 `#D6336C` 强调色；去掉紫蓝渐变、毛玻璃与重投影
- **统一图标**：导航/TabBar/按钮里的 emoji 全部换成 Lucide（`lucide-vue-next`），空态统一用一个图标
- **字号收敛到四档**（26/18/15/12），圆角统一 12/10/999，交互只保留即时反馈
- **新增 `DESIGN.md`**：记录"粉色、不要渐变、不要 emoji 当图标、最多一层投影"等约定与原因
- **新增安卓客户端**：`android/` 免 Gradle 原生外壳（WebView + 服务器地址页），
  产出 `dist/StudyBridge.apk`（25 KB，minSdk 24 / target 34）
- **新增上传脚本**：`scripts/upload_to_astrbot.ps1`，支持 SSH 与 AstrBot OpenAPI 两种方式

### 验证

- `pytest`：150 passed，覆盖率 77%
- `scripts/e2e.py`：17 passed（桌面 + 移动视口，粉色主题下重跑）
- `scripts/selfcheck.py`：10/10
- `aapt2 dump badging` / `apksigner verify`：APK 包名、版本、图标、签名均正确
- 安卓 APK 未上真机（本机无设备/模拟器），步骤见 `docs/KNOWN_ISSUES.md`

## [1.0.0] - 2026-11-17

首个可上架版本。

### 新增

- **插件本体**：AstrBot Star 子类，`metadata.yaml` + `_conf_schema.json` + 中文说明全覆盖
- **HTTP 服务（aiohttp）**：`/api/study/*` 全量接口 + `/study/` 同源静态托管
  - Bearer 令牌鉴权、单 IP 限流（120/min）、鉴权失败 20/min 封 10 分钟、CORS 白名单
  - 端口被占用时明确报错，不静默换端口；`http.enabled=false` 时完全不启动
- **鉴权**：6 位绑定码（5 分钟、一次性、错 5 次作废）→ 一次性兑换令牌（只存 SHA-256）→ 多设备与吊销
- **任务**：CRUD、软删、今日/明日/本周（按时区计算边界）、自然语言解析（AI + 正则兜底）、配额
- **计划**：AI 拆解 → 预览 → 幂等 `apply` → `rollback`（跳过被改过的任务）；日期越界拒绝并指出条目
- **报表**：概览/每日趋势/计划进度 + 纯文本报表（字符进度条）
- **对话**：QQ 与 App 共用 pipeline；JSON 工具协议（7 个工具）、参数错误回灌、最多 6 轮、写操作落 `ai_action_log`
- **AI**：AstrBot provider 复用 / 手填 OpenAI 兼容接口（Fernet 加密）；超时 60s；失败降级规则解析
- **记忆**：本地记忆库 + 插件化适配器（`none` / `generic_tool` / `livingmemory` / `file`）
  - 上行（固定 `source_ref` 覆盖式 + 来源标记）、下行镜像（`bidirectional` 才开）、指数退避重试
  - 污染过滤 8 条规则、`orphan` 如实上报、每周对账、相似度压缩
- **调度**：单 asyncio 循环 30s tick；早报 / 临期提醒 / 计划督促 / 周报 / consolidation / 对账；
  `dedupe_key` + 任务标记保证重启不重发
- **QQ 指令**：20 个指令，全部有 `/study <sub>` 无冲突入口；白名单 + 群模式（`per_user` / `per_group`）
- **前端**：Vue3 + TS + Vite + Pinia + Router + ECharts；13 个页面；移动端 TabBar / 桌面侧边栏
  - 绑定分流、空态/骨架/错误重试、401 全局跳绑定页、错误分类（端口/证书/401/429）
  - Tauri 2 与 Capacitor 配置随仓库提供
- **工程化**：`Makefile`（dev/build/test/lint/package）、`scripts/`（selfcheck / lint_secrets / package / e2e / shots）
- **测试**：150 个 pytest 用例（覆盖率 77%）、17 个 Playwright E2E、离线自检脚本
- **文档**：RESEARCH / ARCHITECTURE / API / DEPLOY / QQ_COMMANDS / MEMORY_SYNC / MARKETPLACE / KNOWN_ISSUES / 验收清单

### 已知限制

见 [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md)：
真机加载、LivingMemory 真机联调、Tauri/Capacitor 打包、内网穿透实测尚未在本环境完成（已给出执行步骤）。

### 设计说明（与需求的差异）

- **对话工具调用**采用统一 JSON 协议而非 provider 原生 function calling：
  跨 provider 行为一致、可离线单测；工具集、校验、重试、6 轮上限、二次确认均按需求实现。
- **`access_token` 配置项不存在**：改用「绑定码 + 可吊销设备令牌」，避免静态共享令牌无法单设备吊销。
