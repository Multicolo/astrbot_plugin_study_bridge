# 使用指南 · Study Bridge

> 面向**使用者**的完整说明：从安装到每天怎么用，以及出问题时怎么查。
> 面向开发者/部署的内容看 [DEPLOY.md](DEPLOY.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[API.md](API.md)、[QQ_COMMANDS.md](QQ_COMMANDS.md)。

---

## 目录

1. [它是什么](#1-它是什么)
2. [准备](#2-准备)
3. [安装](#3-安装)
4. [必须改的三项配置](#4-必须改的三项配置)
5. [让手机/网页连得上](#5-让手机网页连得上)
6. [第一次绑定](#6-第一次绑定)
7. [网页端怎么用](#7-网页端怎么用)
8. [安卓 App 怎么用](#8-安卓-app-怎么用)
9. [QQ 里怎么用](#9-qq-里怎么用)
10. [AI 怎么配](#10-ai-怎么配)
11. [记忆同步（可选）](#11-记忆同步可选)
12. [提醒与推送](#12-提醒与推送)
13. [数据、备份、卸载](#13-数据备份卸载)
14. [升级](#14-升级)
15. [排障表](#15-排障表)
16. [English quick start](#16-english-quick-start)

---

## 1. 它是什么

给 AstrBot 加一套「学习日程 + AI 计划 + 记忆同步」的能力，三个入口共用同一份数据：

```
        QQ 私聊/群聊                    网页                   安卓 App
   /add /today /plan /bind ...    http://<你的机器>:6188/study/   同地址，套壳 WebView
              └─────────────────────┬─────────────────────┘
                        AstrBot 机器上的插件（SQLite）
                           data 全在你自己的机器里
```

- **只有 QQ 也能闭环**：不装 App、不开 HTTP 也能用全部日程/报表/计划功能。
- **不依赖任何第三方后端**：没有开发者服务器，插件只连你自己的 AstrBot 与（可选的）你配置的 AI。
- **数据可带走**：SQLite 单库 + `/export` 全量 JSON。

---

## 2. 准备

| 项 | 要求 |
|---|---|
| AstrBot | `>= 4.24.2, < 5`（面板「关于」里可看版本） |
| 平台 | aiocqhttp（NapCat / LLOneBot 等）已验证；Telegram/Discord 等只用公开接口，理论兼容但未实测 |
| 网络 | 纯 QQ 用法不需要开放任何端口；要用网页/App 才需要能访问 `6188` |
| 安卓 | Android 7.0（API 24）及以上；WebView 越新越好（Chrome 53 已实测可用） |

---

## 3. 安装

### 方式 A：面板装 zip（推荐）

1. 下载 [dist/astrbot_plugin_study_bridge.zip](../dist/astrbot_plugin_study_bridge.zip)；
2. AstrBot 面板 → **插件** → 安装 → 选择该 zip → 等待解压完成；
3. 回到插件列表点**重载**（或重启 AstrBot）。

> **Docker 部署注意**：zip 里的文件是**扁平**的（`main.py`、`core/`、`web/` 直接在压缩包根）。
> 面板安装会自己解到 `data/plugins/astrbot_plugin_study_bridge/`；如果你**手动 scp 解压**，
> 一定要先建子目录再解压，否则文件会散落到 `plugins/` 根目录：
>
> ```bash
> cd /opt/astrbot/data/plugins        # 换成你的 plugins 目录
> rm -rf astrbot_plugin_study_bridge && mkdir astrbot_plugin_study_bridge
> unzip -oq /tmp/astrbot_plugin_study_bridge.zip -d astrbot_plugin_study_bridge
> ```

### 方式 B：手动放目录

把仓库里除 `frontend/`、`tests/`、`android/`、`dist/` 之外的内容（`main.py`、`core/`、`adapters/`、`web/`、`i18n/`、`metadata.yaml`、`_conf_schema.json`、`requirements.txt`）放进：

```
<AstrBot>/data/plugins/astrbot_plugin_study_bridge/
```

### 方式 C：只要 QQ

装完把配置 `http.enabled` 设为 `false` 即可：网页/App 关闭，但指令、AI、计划、推送全部照常。

安装成功的标志（日志）：

```
学习桥梁已就绪（v1.1.3）
学习桥梁 HTTP 服务已监听 http://0.0.0.0:6188/study/
```

---

## 4. 必须改的三项配置

面板 → 插件 → 学习桥梁 → 配置：

| 配置 | 默认 | 为什么必须改 |
|---|---|---|
| `scope.allowed_qq` | `[]` | 留空 = **只有机器人主人**能用指令。要把插件给家人/同学用，在这里填他们的 QQ 号 |
| `http.host` / `http.port` | `0.0.0.0` / `6188` | 只本机用填 `127.0.0.1`；端口被占插件会报 ERROR 而不是偷偷换端口 |
| `default_timezone` | `Asia/Shanghai` | 影响所有时间解析；用户可用 `/settings tz` 单独覆盖 |

生产环境建议再改一项：

| 配置 | 默认 | 建议 |
|---|---|---|
| `http.allowed_origins` | `["*"]` | 改成你的站点，例如 `["https://study.example.com"]`。默认 `*` 只适合本地调试 |

其余可选项（AI、记忆、推送、配额、限流）见 [第 10](#10-ai-怎么配)、[11](#11-记忆同步可选)、[12](#12-提醒与推送) 节，或直接看面板里每一项的中文说明。

---

## 5. 让手机/网页连得上

插件默认监听 `0.0.0.0:6188`，你能不能访问取决于网络形态。四种常见做法：

| 形态 | 你需要做 | App 里填 |
|---|---|---|
| **局域网**（推荐先试这个） | 确保防火墙放行 6188（Windows 首次运行会弹窗，选「允许」） | `http://<电脑内网IP>:6188` |
| **公网直连** | 云安全组 + `ufw` 放行 `6188/tcp` | `http://<公网IP>:6188` |
| **反向代理 HTTPS**（推荐长期） | nginx 把 `/study/` 与 `/api/study/` 代理到 `127.0.0.1:6188` | `https://你的域名` |
| **内网穿透** | 用 frp / Cloudflare Tunnel / Tailscale 暴露 6188 | 穿透给你的地址 |

### Docker 部署必须先发布端口

AstrBot 跑在容器里时，容器内的 6188 **不会自动映射到宿主机**。在 compose 目录加一个覆盖文件：

```yaml
# docker-compose.study.yml（不要改原来的 compose）
services:
  astrbot:
    ports:
      - "127.0.0.1:6188:6188"   # 只给本机/nginx 用
      # - "0.0.0.0:6188:6188"   # 直接对公网开放（明文 HTTP，慎用）
```

```bash
docker compose -f docker-compose.yml -f docker-compose.study.yml up -d
docker port astrbot                 # 应出现 6188/tcp -> 127.0.0.1:6188
curl -s http://127.0.0.1:6188/api/study/health   # {"version":"1.1.3"}
```

### nginx 反代片段（HTTPS）

```nginx
location /study/ {
    proxy_pass http://127.0.0.1:6188;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
}
location /api/study/ {
    proxy_pass http://127.0.0.1:6188;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
}
```

配好后 `nginx -t && systemctl reload nginx`，再在配置里把 `http.public_base_url` 填成 `https://你的域名`，
这样 QQ 里发 `/addr` 会直接返回正确地址。

### 自检命令（不用装 App 就能确认服务端）

```bash
curl -s http://<地址>:6188/api/study/health     # {"ok":true,...,"version":"1.1.3"}
curl -s -o /dev/null -w '%{http_code}\n' http://<地址>:6188/study/   # 200
```

`503` = 前端资源没构建/没随插件上传；连接被拒 = 服务没起 / 端口没放行 / `http.enabled=false`。

---

## 6. 第一次绑定

网页/App 打开后是「绑定与安装自检」页，按顺序：

1. **填服务地址**：App 里首次启动就填；网页版通常留空（同源）。
2. **测试连接** → 应显示「连接正常 · 插件 1.1.3」。
3. **生成绑定码** → 得到一个 **6 位数字，5 分钟内有效、只能用一次**。
4. 到 QQ **私聊**机器人发送：`/bind 123456`（群里发会被拒绝，避免令牌泄露）。
5. App/网页会自动轮询完成绑定，然后进入「今日」。

绑定后可在这页看到「当前身份 / 设备数 / 解除本机绑定」，以及安装自检（插件版本、迁移版本、记忆适配器、AI 状态、HTTP 状态）。

> 令牌只保存在本机浏览器/App 的 localStorage，不会上传到任何第三方；换设备重新绑定，旧设备可用「设备管理」或 QQ `/unbind <标签>` 吊销。

---

## 7. 网页端怎么用

地址：`http://<你的机器>:6188/study/`（桌面端左侧导航；手机浏览器/App 是底部 TabBar）。

| 页面 | 用来做什么 |
|---|---|
| **今日** | 一句话加日程（解析→预览→写入）、今天/明天任务、标记完成、删除 |
| **日历** | 月视图看安排，点某天看当天清单 |
| **计划** | 用 AI 拆学习计划 → 预览 → 确认写入日程（幂等，可回滚） |
| **资料** | 存链接/笔记等学习资料 |
| **报表** | 完成率、趋势、来源占比、计划进度（echarts 图表） |
| **AI 对话** | 和机器人聊学习相关的事（可带工具：查日程、加任务） |
| **记忆中心** | 学习记忆（可编辑/删除）+ bot 记忆（可选采纳） |
| **推送目标** | 管理早报/提醒推送到的会话（UMO），可发测试推送 |
| **通知记录** | 每次推送的成败与失败原因 |
| **AI 设置** | 选 AstrBot 里的模型，或手填 OpenAI 兼容接口 / API Key（密文存储，只回 `has_key`） |
| **设备管理** | 查看/吊销已绑定设备 |
| **设置** | 时区、早报时间、计划督促、提醒偏移、默认时长；导出全量 JSON；**App 服务器地址**（换 IP 不用重装） |

**小技巧**

- 加日程不用打全：`明天下午三点背单词一小时` 就够了；解析结果不对就改一句话再解析。
- 计划是两步：`/plan new` 或网页「计划」只生成草稿，**确认后**才写日程。
- 报表页的「本周 / 本月 / 今日」切换决定统计区间。

---

## 8. 安卓 App 怎么用

1. 下载 [dist/StudyBridge.apk](../dist/StudyBridge.apk)（v1.1.3，versionCode 14，minSdk 24）。
2. 传到手机安装（允许「安装未知来源应用」）。
3. 打开 → 填地址（如 `http://192.168.1.10:6188`）→ **连接** → 生成绑定码 → QQ `/bind`。

**这版 App 的几个要点**

- **加载中就有出口**：点连接后立刻显示「正在打开 …」+「看原因」+「退出 App」，不用干等。
- **12 秒没响应自动出诊断页**：写明地址、WebView 版本、JS 报错、失败资源与 HTTP 状态，并可
  「重新加载 / 在系统浏览器里打开 / 换一个地址 / 复制诊断信息 / 退出 App」。
- **换地址不用重装**：「更多 → 设置 → App 服务器地址 → 换服务器地址」；长按页面也有菜单。
- **旧手机也能用**：内置 legacy 兼容包，Android 7 自带 WebView（Chrome 53）已实测通过。
- **深色模式不会把粉色界面反相**（已关闭系统强制深色）；状态栏跟随粉色主题。

> 如果 App 打开是白屏：先看它自己的诊断页，再用「在系统浏览器里打开」对照。
> 浏览器能开 → 问题在 App（把诊断信息发出来）；浏览器也打不开 → 服务端/端口/防火墙问题。

---

## 9. QQ 里怎么用

最常用的 8 条（完整表 + 示例回复见 [QQ_COMMANDS.md](QQ_COMMANDS.md)）：

| 指令 | 作用 |
|---|---|
| `/add 明天下午三点背单词一小时` | 自然语言加日程（AI 解析，失败自动用规则解析） |
| `/today` / `/tomorrow` / `/week` | 看安排 |
| `/done 2` 或 `/done 背单词` | 标记完成 |
| `/plan new 考研数学 14 天冲刺` → `/apply` | AI 拆计划 → 确认写日程 |
| `/report week` | 纯文本报表 |
| `/memory` / `/forget 3` | 看/删记忆 |
| `/bind 123456` | 只在私聊，绑定 App |
| `/addr` / `/umo` / `/whoami` | 服务地址 / 当前会话 UMO / 我是谁 |

- 所有指令都有等价的长写法 `/study add ...`：短指令和其他插件冲突时用它。
- 越权使用会**静默忽略**并留 `command_log`，不会打扰群里其他人。
- 群里每个人数据是否互通由 `scope.group_mode` 决定（`per_user` 互相独立 / `per_group` 整群共用）。

---

## 10. AI 怎么配

| 模式 | 说明 |
|---|---|
| `astrbot`（默认） | 直接用 AstrBot 里已配好的模型，可在「AI 设置」里选具体 provider；插件不复制、不落库任何 Key |
| `manual` | 在网页「AI 设置」里手填 OpenAI 兼容的 `base_url` / 模型名 / API Key；Key 加密存库，接口只回 `has_key` |

- **AI 不可用时不会假装成功**：自动降级为规则解析，回复里会标注「（AI 不可用，已用规则解析）」。
- `ai.allow_principal_ai=false` 可限制只有主人能用 AI，其他人一律走规则解析。
- 超时 `ai.timeout_seconds`（默认 60s）、单次最多工具轮次 `ai.max_tool_rounds`（默认 6）。
- 限流：单 IP 每分钟 120 请求；鉴权失败每分钟 20 次后封 10 分钟（可配）。

---

## 11. 记忆同步（可选）

默认 `adapter_order = [generic_tool, livingmemory, none]`、`sync_mode = upload_only`：

| sync_mode | 行为 |
|---|---|
| `off` | 完全不向第三方记忆插件写入 |
| `upload_only`（默认） | 只把学习偏好**上行**给记忆插件；不读它的内容 |
| `bidirectional` | 额外读取 bot 侧记忆并展示在「记忆中心 · bot 记忆」（需你明确开启） |

- 探测失败会**降级为 `none`**（本地记忆照常工作），并在 `/info` 与网页自检里如实显示原因。
- 也支持 `file` 适配器：把记忆镜像成 JSONL（`memory.file_adapter_path`，留空用插件数据目录）。
- 防回环：写入远端时带 `memory.source_tag_prefix` 标记（默认 `[src:study:`），改这个值会让旧条目被当成外部条目。
- 详细机制与「20 行适配器模板」见 [MEMORY_SYNC.md](MEMORY_SYNC.md)。

---

## 12. 提醒与推送

| 项 | 默认 | 说明 |
|---|---|---|
| 早报 | 08:00 | 今天的安排 + 完成率 |
| 计划督促 | 21:00 | 计划进度落后的提醒 |
| 周报 | 周一 09:00 | 本周统计 |
| 默认提醒偏移 | `[30, 0]` | 未指定时：提前 30 分钟 + 开始时各提醒一次 |
| 失败重试 | 3 次 | 仍失败则记 `failed` 并在「通知记录」里显示原因 |

**怎么设置推送目标**：在 QQ 里对目标会话发 `/umo` 拿到 UMO（如 `qq:FriendMessage:10001`），
到网页「推送目标」添加并点一次「测试推送」；每个用户也可以 `/settings brief 07:30` 单独改时间。

> 重启不会重复推送：`dedupe_key` 唯一索引 + `__job:*` 标记保证「今天推过就不再推」。

---

## 13. 数据、备份、卸载

| 项 | 位置 |
|---|---|
| 数据库（SQLite，WAL） | `<AstrBot>/data/plugin_data/astrbot_plugin_study_bridge/study.db` |
| 备份 | 复制该目录；或网页「导出全量 JSON」/ QQ `/export` / `GET /api/study/export` |
| 迁移机器 | 停 AstrBot → 复制整个插件数据目录 → 新机器装插件 → 启动 |
| 卸载 | 删除插件目录 + 上述数据目录（数据全部清空，没有远端残留） |

- 数据按「主体」隔离：私聊是每个 QQ 一份；群聊按 `group_mode` 决定。
- 配额（单主体，可配）：任务 2000 / 计划 200 / 通知记录 5000。
- 隐私：没有开发者后端；API Key 只以密文形式存在库里；令牌只在你自己的浏览器/手机上。

---

## 14. 升级

1. **插件**：面板 → 插件 → 安装 → 选新 zip 覆盖 → 重载。数据目录不动，升级只跑数据库迁移。
2. **网页**：随插件包更新（`web/` 在插件里），重装 zip 即生效；浏览器强刷 `Ctrl+F5` 清旧缓存。
3. **App**：装新 APK 覆盖（同一签名，无需卸载）。App 只是套壳，**前端升级不用重装 App**。
4. 版本号在 `metadata.yaml` / `core/app.py:PLUGIN_VERSION` / 安卓 `versionName` 三处保持一致。

---

## 15. 排障表

| 症状 | 最可能的原因 | 处理 |
|---|---|---|
| 网页/App **白屏** | 服务端 404/503、端口不通、旧 WebView 解析失败 | App 1.1.3 会在 12 秒内给诊断页；先看「检测结论」，再点「在系统浏览器里打开」对照 |
| 诊断页显示 `ERR_CONNECTION_REFUSED/TIMED_OUT` | 插件没起 / 端口没发布 / 防火墙或安全组没放行 | `curl http://<地址>:6188/api/study/health`；Docker 看 `docker port astrbot` 是否有 6188 |
| 诊断页显示 `HTTP 503` | `web/` 没随插件上传（打包不完整） | 重新用 `dist/*.zip` 覆盖安装 |
| 诊断页显示 `HTTP 404` | 路径拼错（不要带 `/study/` 以外的后缀）或反代路径没配 | 地址只填到端口，App 会自己加 `/study/` |
| 页面能开但接口全 401 | 令牌失效/被清 | 网页「绑定与自检」重新生成绑定码 → QQ `/bind` |
| 页面样式错乱 / 按钮点不动 | WebView 太旧（< Chrome 53） | 更新系统「Android System WebView」或 Chrome；仍不行把诊断信息发出来 |
| `/bind` 没反应 | 在群里发的 / 绑定码过期（5 分钟）/ 码打错 | 私聊发；重新生成；注意一次性 |
| QQ 指令无响应 | `scope.allowed_qq` 没放行 | 把 QQ 号加进白名单，或先用机器人主人账号试 |
| `/plan new` 没写日程 | 设计如此：只有预览 | 确认后发 `/apply` |
| AI 报超时 / 降级 | 模型不可用、Key 错、网络问题 | 「AI 设置」里换 provider 或用 `manual` 填自己的接口；插件会标注降级为规则解析 |
| 早报没收到 | 时间不对 / 推送目标没配 / 平台限制主动消息 | 网页「推送目标」点「测试推送」，并看「通知记录」里的失败原因 |
| 记忆显示「降级 none」 | 没装记忆插件 / 版本不在白名单 | 正常状态；需要互通就装 LivingMemory 2.13.0 或配 `file` 适配器 |
| 端口被占用 | 6188 已被别的程序用 | 改 `http.port`，或停掉占用进程；插件不会静默换端口 |

更多边界与未验证项见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。

---

## 16. English quick start

1. Install the zip (panel → plugins → install) or drop the folder into `data/plugins/astrbot_plugin_study_bridge/`.
2. Set `scope.allowed_qq` to the QQ numbers allowed to use it (empty = bot owner only).
3. Optional web/app access: the plugin serves `/study/` on port `6188`. Publish that port
   (Docker: add a compose override; cloud: open the security group) or reverse-proxy it behind HTTPS.
4. Open `http://<host>:6188/study/` (or the Android APK), click **生成绑定码 / Generate code**,
   then send `/bind 123456` to the bot **in a private chat**.
5. Daily use: `/add tomorrow 3pm vocabulary 1h`, `/today`, `/plan new <goal>` + `/apply`, `/report week`.
6. AI is optional: use AstrBot's models (`ai.mode=astrbot`) or your own OpenAI-compatible endpoint
   (`manual`). When AI is unavailable the plugin falls back to rule-based parsing and says so.

Full command reference: [QQ_COMMANDS.md](QQ_COMMANDS.md). Deployment details: [DEPLOY.md](DEPLOY.md).
