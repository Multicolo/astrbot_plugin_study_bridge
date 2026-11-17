# DEPLOY — 四种部署形态

目标：**没有开发者后端**，每个用户的数据只在自己的 AstrBot 机器上；**没有公网 IP 也能用**。

先记住一个判断表：

| 你的情况 | 用哪种形态 | App 里填什么 |
|---|---|---|
| 只想要 QQ，不装 App | A 纯 QQ | — |
| 手机和 AstrBot 机器在同一个 WiFi | B 局域网 | `http://<内网IP>:6188` |
| 有域名 + 想上 HTTPS（推荐） | C 反代 | `https://study.example.com` |
| 家宽没公网 IP | D 内网穿透 | 穿透服务给你的域名 |
| VPS + 公网 IP | C 或直接 `http://ip:6188`（不推荐明文） | 你的地址 |

---

## 0. 安装插件

1. 把插件目录放到 AstrBot 的 `data/plugins/astrbot_plugin_study_bridge/`（或在面板里装 zip）；
2. 确认目录里有 `main.py` / `metadata.yaml` / `web/index.html`；
3. 面板里重载插件，日志应出现：

```
学习桥梁已启动：data_dir=... schema=v2 adapter=none
学习桥梁 HTTP 服务已监听 http://0.0.0.0:6188/study/
学习桥梁已就绪：v1.0.0（要求 AstrBot>=4.24.2，当前 4.30.0）
```

4. **第一步永远是**：私聊机器人发 `/bind <App 上显示的 6 位码>`。没有这一步 App 拿不到令牌。

常见安装错误：

| 日志 | 原因 | 处理 |
|---|---|---|
| `HTTP 服务启动失败：… 无法监听` | 端口被占用 | 改 `http.port` 后重载；或改用纯 QQ 模式 |
| `metadata 校验失败` | `metadata.yaml` 缺必填字段 | 对照 `docs/MARKETPLACE.md` |
| `迁移 … 失败，已回滚，拒绝启动` | 数据库文件损坏/权限不足 | 备份后删除 `study.db`，或修权限 |

---

## A. 纯 QQ（不装 App）

配置：

```json
{"http": {"enabled": false}}
```

可用能力（**全部**）：

- `/add` `/done` `/del` `/today` `/tomorrow` `/week`
- `/plan new` `/apply` `/plan list` `/plan show`
- `/report week|month` `/export`
- `/memory` `/forget` `/reset`
- 早报 / 提醒 / 督促 / 周报（推送到 `/umo` 显示的会话）
- AI 排计划、自然语言解析

限制：没有网页/App 界面；`/addr` 会提示如何开启 HTTP。

---

## B. 局域网

1. 插件配置：`http.enabled=true`、`http.host=0.0.0.0`、`http.port=6188`；
2. 查机器内网 IP：
   - Windows：`ipconfig` → IPv4 地址（如 `192.168.1.23`）
   - Linux：`ip -4 addr show | grep inet`
3. 手机浏览器打开 `http://192.168.1.23:6188/study/`；
4. `allowed_origins` 保持 `["*"]`（局域网调试够用）；
5. Windows 防火墙放行 6188（首次运行会弹窗，选"允许专用网络"）。

> 手机和电脑必须在同一网段；公司/学校 WiFi 常开 AP 隔离，会连不上。

---

## C. 反代 + 域名 + HTTPS（推荐）

假设：域名 `study.example.com` 已解析到你的服务器，AstrBot 在同一台机器。

### C1. Nginx

```nginx
server {
    listen 80;
    server_name study.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name study.example.com;

    ssl_certificate     /etc/letsencrypt/live/study.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/study.example.com/privkey.pem;

    client_max_body_size 8m;

    location / {
        proxy_pass         http://127.0.0.1:6188;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

### C2. certbot 签证书

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo certbot --nginx -d study.example.com --redirect -m you@example.com --agree-tos
sudo nginx -t && sudo systemctl reload nginx
```

自动续期检查：`sudo certbot renew --dry-run`

### C3. 插件侧配置

```json
{
  "http": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 6188,
    "public_base_url": "https://study.example.com",
    "allowed_origins": ["https://study.example.com"]
  }
}
```

- `host` 改成 `127.0.0.1`：只让本机 Nginx 访问，别把 6188 暴露到公网；
- `public_base_url` 让 `/addr` 直接返回正确地址；
- 生产环境**不要**让 `allowed_origins` 保持 `*`。

### C4. 校验

```bash
curl -s https://study.example.com/api/study/health
# {"ok": true, "data": {"name": "...", "version": "1.0.0", "status": "ok"}}
```

证书不信任时 App 会明确提示「HTTPS 证书不被信任」，而不是白屏。

---

## D. 内网穿透（家宽无公网 IP）

三选一，都只要把本地 `6188` 暴露出去。

### D1. Cloudflare Tunnel（推荐，免费 + 自动 HTTPS）

```bash
# 1) 安装
brew install cloudflared        # macOS
# Linux:
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# 2) 登录并建隧道
cloudflared tunnel login
cloudflared tunnel create study-bridge

# 3) 配置 ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<'YAML'
tunnel: study-bridge
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: study.example.com
    service: http://127.0.0.1:6188
  - service: http_status:404
YAML

# 4) 绑定域名并启动
cloudflared tunnel route dns study-bridge study.example.com
cloudflared tunnel run study-bridge       # 建议做成 systemd 服务
```

插件配置：`http.host=127.0.0.1`，`public_base_url=https://study.example.com`。

### D2. frp（需要一台有公网 IP 的服务器）

服务端 `frps.toml`：

```toml
bindPort = 7000
auth.token = "<换成随机串>"
```

客户端 `frpc.toml`（跑在 AstrBot 机器上）：

```toml
serverAddr = "<公网服务器 IP>"
serverPort = 7000
auth.token = "<同上>"

[[proxies]]
name = "study-bridge"
type = "tcp"
localIP = "127.0.0.1"
localPort = 6188
remotePort = 6188
```

公网服务器上仍建议套 Nginx + certbot（见 C），把 `127.0.0.1:6188` 换成反代上游。

### D3. Tailscale（只在你的设备之间用，最省心）

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4          # 得到 100.x.y.z
```

手机装 Tailscale 并登录同一账号，App 里填 `http://100.x.y.z:6188`。
优点：不需要域名、不需要开公网端口；缺点：只有你自己设备能用（朋友用不了）。

---

## 备份与恢复

### 备份（三种等价方式）

1. **复制数据库文件**（推荐，含全部业务数据）：

```bash
# 先让插件停一下最稳（或用 sqlite3 .backup，WAL 也能安全拷）
sqlite3 data/plugin_data/astrbot_plugin_study_bridge/study.db ".backup '/backup/study-$(date +%F).db'"
```

2. **App/接口导出全量 JSON**：`GET /api/study/export`（或 QQ `/export`）；
3. 面板里停插件 → 直接复制整个 `data/plugin_data/astrbot_plugin_study_bridge/` 目录。

> 目录里除了 `study.db` 还有 `study.db-wal` / `study.db-shm`（WAL 文件），复制时三个一起拷最安全。
> `secret.key` 是手填 API Key 的加密密钥，**丢了就要重填 Key**（数据本身不受影响）。

### 恢复

```bash
# 停插件
cp /backup/study-2026-11-17.db data/plugin_data/astrbot_plugin_study_bridge/study.db
rm -f data/plugin_data/astrbot_plugin_study_bridge/study.db-wal \
      data/plugin_data/astrbot_plugin_study_bridge/study.db-shm
# 启动插件（会自动跑迁移）
```

### 彻底删除

停插件 → 删除 `data/plugin_data/astrbot_plugin_study_bridge/` → 卸载插件。端口、后台任务、DB 连接都会随
`terminate()` 释放。

---

## 故障排查

| 现象 | 定位 | 处理 |
|---|---|---|
| App 提示"端口不通" | `curl -v http://host:6188/api/study/health` | 防火墙 / 端口 / 内网 IP / 是否 `http.enabled=false` |
| App 提示 401 | `GET /auth/me` | 令牌失效：重新绑定；设备被吊销：重新绑定 |
| 429 | 看 `http.rate_limit_per_minute` | 调大，或确认没有脚本在刷；鉴权失败过多会封 10 分钟 |
| 证书错误 | `curl -v https://…` | 证书链不完整 / 自签未信任；用 certbot 重签 |
| 早报不发 | `/info` 看 `capabilities.push`；`/notifications` 看 status | 没有推送目标 → App「推送目标」加一个；平台离线 → 检查适配器 |
| 早报重复 | 检查是否多实例/AstrBot 被复制 | `dedupe_key` 在 DB 里，只应发一次 |
| 时间不对 | `/info` 的 `timezone`；`/settings` | 改成正确 IANA 时区（`Asia/Shanghai`） |
| AI 不可用 | `/info` 的 `ai.available`；App「AI 设置」测试 | 检查 provider / 手填 Key / 网络 |
| 计划日期越界 | apply 返回 `VALIDATION_ERROR` + 条目 | 改计划日期，或重新生成 |
| 记忆状态 orphan | `/memory/sync-status` | 远端不支持删除，属如实上报，不是 bug |

日志位置：AstrBot 主日志（面板"日志"页）。插件只写 `data/plugin_data/astrbot_plugin_study_bridge/`。
