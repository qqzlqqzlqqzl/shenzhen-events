# 运维手册

写给接手维护的人（包括 AI 助手）。先看“线上部署一览”，再按需查后面的操作。

## 线上部署一览

| 项目 | 现状 |
|---|---|
| 访问 | <https://lylme.cn/events/>（也可用 <https://106.53.40.6/events/>）；Nginx 路由在 `/etc/nginx/toolbox/events.conf` |
| 服务 | 系统级 `shenzhen-events.service`（uvicorn，`127.0.0.1:8093`，用户 `ubuntu`） |
| 运行目录 | `/home/ubuntu/shenzhen-events` → `~/website-release-20261004/events-release-bd9d171-r2/view` |
| 代码与数据 | `view/radar/`、`view/static/` 是发布时复制的真实文件；其余（`data/`、`.private/`、`.venv/`、`sources.json`、`scripts/`、文档等）都是软链接，指向 `~/shenzhen-events.before-20261004-fullcycle/` |
| Git 工作副本 | `~/shenzhen-events.before-20261004-fullcycle`，带推送用的部署密钥（`core.sshCommand`）。**它的工作树同时是线上 `sources.json` 等文件的来源，不要随手 `git pull`** |
| 数据库 | `data/events.sqlite3`（SQLite WAL，约 26 MB） |
| 私有配置 | `.private/settings.json`（模型、预算、会话密钥、ICS token）、`.private/radar-ai.env`（模型 API Key）、`.private/amap.key`（可选高德 Key）。权限 0600，不进 Git，不要打印 |
| 登录 | 不单独建账号：`/events/api/login` 把用户名和密码转给信息箱的 Miniflux（`127.0.0.1:8091/mf/v1/me`）验证，成功后签发 14 天会话 |

### 定时任务

| 单元 | 频率 | 做什么 |
|---|---|---|
| `shenzhen-events-collect.timer`（系统级） | 每小时 | `radar.worker collect --limit 120`：按来源频率采集、标准化、去重 |
| `shenzhen-events-retry.timer`（系统级） | 每分钟 | `radar.worker retry`：消费“单源重试”队列（来源页上点“重试”） |
| `radar-analyze.timer`（用户级） | 每 15 分钟 | `radar.worker analyze --limit 120`：AI 分析待处理条目 |
| `radar-posters.timer`（用户级） | 每 30 分钟 | `radar.poster_cache --limit 40`：预先下载近期活动的配图 |
| `shenzhen-events-analyze.timer`（系统级） | **已停用** | 被上面的用户级单元取代；它只读 `settings.json`，拿不到 API Key |

用户级单元在 `~/.config/systemd/user/radar-analyze.{service,timer}`（只加载 `.private/radar-ai.env`）和 `radar-posters.{service,timer}`。

### AI 分析

- 走服务器上的 New API（`http://127.0.0.1:18767/v1`），模型 `claude-haiku-4-5`。
- 每日上限写在 `settings.json`：`daily_calls`（当前 200）和 `daily_tokens`（当前 1,500,000），按北京时间日界重置；用量记在数据库 `budget` 表。
- 关掉分析：把 `analysis_enabled` 改成 `false`。采集和重试不受影响。
- 模型返回的 JSON 坏了（例如中文引号没转义）：先自动修复；整批仍失败就逐条重试；单条还失败标为 `model_error` 跳过。网络或接口错误则停止本轮，下一轮再来。

### 图片与缓存

- **海报预缓存**：`radar/poster_cache.py` 把近期活动（以及 30 天内结束的）每个最多 4 张配图下载下来，用 Pillow 缩到宽 960 像素以内、转成 webp，存进 `static/posters/<sha256>.webp`，清单写在 `data/poster-cache.json`。卡片封面和详情海报只读这些本机文件，不会去原站加载。宽或高小于 100 像素的是图标，记为“不是海报”，以后不再下载；真正下载失败的图片按 1 小时、2 小时……最长 7 天退避重试；活动过期 30 天后，对应文件会自动删除。人工审核过的海报仍写在 `static/posters/manifest.json`，优先级更高，不会被自动删除。
- **静态资源缓存**：首页里的每个脚本和样式链接都带内容哈希（`?v=<哈希>`），由 `radar/api.py` 在返回首页时计算；哈希对得上的请求缓存一年，海报按文件名哈希同样缓存一年。所以发布新版本后不用手动改版本号，浏览器会自动拿到新文件。接口返回的数据一律不缓存。
- **月历组件**（FullCalendar，约 280 KB）只在第一次打开月历时才下载。

## 常用操作

以下命令在服务器上以 `ubuntu` 用户执行。

**看状态**

```bash
systemctl status shenzhen-events
systemctl list-timers 'shenzhen-events-*'
systemctl --user list-timers radar-analyze.timer
journalctl --user -u radar-analyze -n 50 --no-pager
curl -s http://127.0.0.1:8093/events/api/health
```

**手动跑一次**

```bash
cd ~/shenzhen-events
.venv/bin/python -m radar.worker collect --source <来源ID> --force
systemctl --user start radar-analyze.service
```

**修复数据**（脚本默认只预览，确认后加 `--apply`）

```bash
.venv/bin/python scripts/repair_districts.py
.venv/bin/python scripts/repair_districts.py --apply
```

`repair_districts.py` 用最新的地名表重新推断仍为“待确认”的行政区。剩下的大多是线上活动、“报名后可知”或海外城市，属于正常。

## 发布新版本

线上目录不是 Git 工作副本，发布方式是“把审过的改动直接打到线上文件，再同步到 GitHub”：

1. 在本地或临时克隆里改代码、跑测试（见 README）。
2. 生成补丁：`git format-patch -1`。
3. 在服务器上先备份要改的文件，再把补丁打进线上目录。只动 `radar/`、`static/` 这些真实文件；补丁涉及软链接目录时，用 `--include` 限定：

   ```bash
   cd ~/website-release-20261004/events-release-bd9d171-r2/view
   git apply --check --include='static/*' 补丁文件
   git apply --include='static/*' 补丁文件
   ```

4. 改了 `radar/*.py` 要重启：`sudo systemctl restart shenzhen-events`。只改 `static/` 不用重启：首页每次都按文件内容重新计算版本号，刷新就能拿到新文件。
5. 核对线上文件的 sha256 和本地一致后，在临时克隆里 `git am` 同一个补丁，借部署密钥推到 `main`：

   ```bash
   KEY=~/shenzhen-events.before-20261004-fullcycle
   git -c core.sshCommand="$(git -C $KEY config core.sshCommand)" \
     push "$(git -C $KEY remote get-url origin)" HEAD:refs/heads/main
   ```

服务器直连 GitHub 很慢，git 操作前可先 `export HTTPS_PROXY=http://127.0.0.1:17890`（信息箱的 mihomo 代理）。

`deploy/install.py` 是首次安装用的（需要 sudo）：写 systemd 单元和 Nginx 路由，并提供回滚。日常发布用不到。

## 排查

| 现象 | 先看 |
|---|---|
| 页面打不开 / 502 | `systemctl status shenzhen-events`、`journalctl -u shenzhen-events -n 100` |
| 登录失败 | 信息箱的 Miniflux 是否正常：`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/mf/healthcheck` |
| 某个来源一直失败 | 页面右上“数据来源”看失败原因；受限（`blocked`）会自动退避，不要硬绕 |
| AI 分析不动 | `journalctl --user -u radar-analyze`；检查当天预算是否用完、`analysis_enabled` 是否为 `true`、New API 是否在线 |
| 待分析积压 | 每轮最多 120 条、每 15 分钟一轮；积压几千条要一两天才能消化，属正常 |
