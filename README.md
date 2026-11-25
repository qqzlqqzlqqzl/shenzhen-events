# 深圳活动雷达 · Shenzhen Events Radar

把深圳（以及可以在线参加）的公开活动收集到一处：自动去重、分类、按兴趣排序，在一个私人页面里浏览、收藏和导出日历。

- 线上地址：<https://lylme.cn/events/>，用个人信息箱的账号登录
- 运维与部署：[docs/OPERATIONS.md](docs/OPERATIONS.md)
- 全部文档索引：[docs/README.md](docs/README.md)

## 能做什么

| 功能 | 说明 |
|---|---|
| 七个视图 | 为你发现、本周、本周末、全部、我的收藏、最近浏览、我的反馈 |
| 三种展示 | 卡片、列表、月历；卡片和列表按“今天 / 明天 / 本周末 / 下周……”分组；有配图的活动在卡片上显示封面 |
| 筛选 | 地区、活动类型、主题、参加方式（线下 / 线上 / 线上线下）、费用、日期范围、我的反馈；组内任一满足，组间同时满足 |
| 常用视图 | 把一组筛选条件存起来下次直接打开，只保存在当前浏览器 |
| 详情 | 时间、地点、费用、主办方、原文与报名链接、海报；上一条 / 下一条连续浏览；复制摘要或链接 |
| 收藏与反馈 | 收藏跨设备同步；反馈分“感兴趣 / 不感兴趣 / 已参加”，可附原因标签，可撤销，可导出为 JSON |
| 对比 | 勾选几个候选活动并排比较时间、地点、费用 |
| 日历 | 单个活动导出 `.ics`；收藏可通过私人 ICS 链接订阅到手机日历 |
| 数据来源页 | 每个来源的上次抓取时间、状态、条数和失败原因 |

手机和桌面都能用；支持深色模式，桌面有键盘快捷键（按 `?` 查看）。

## 数据从哪来

`sources.json` 里登记了 17 个公开来源，例如联谱、中国科技活动日历、深圳本地宝、柴火创客、活动行、豆瓣同城、Meetup、深圳会展中心、CIOE 光博会、深圳活动网、深圳会展业公共服务平台、dev.events（线上开发者活动）、电子发烧友、开放原子旋武社区、深圳湾。另外用搜狗微信做低频的线索发现，搜到的公众号不会自动当成可信来源。

```text
公开网页 / RSS / RSSHub / 搜狗微信
  → 采集：每小时一轮，按来源频率和失败退避
  → 标准化：时间、地点、费用；从地址推断行政区（例：前海 → 南山）
  → 保守去重：日期 + 标题 / 地点；已知的跨源别名写在 dedupe_aliases.json
  → AI 分析：每 15 分钟一批，判断是否深圳线下或可在线参加、活动类型、主题、推荐理由
  → SQLite → FastAPI（127.0.0.1:8093）→ Nginx /events/ → 浏览器
```

## 几条原则

- **证据优先**：文章发布时间不会被当成活动日期；无法证实的时间或地点显示“待确认”，不猜。
- **不越权采集**：不绕过登录、验证码或访问限制；遇到限制记为“受限”并退避。
- **AI 有上限**：每天的模型调用次数和 Token 都有上限；某一条模型输出格式出错时，只把这一条标为 `model_error`，不会卡住整个队列。
- **私人数据不进 Git**：`.private/`、数据库、日志、密钥都只在服务器上。

## 代码结构

| 路径 | 作用 |
|---|---|
| `radar/api.py` | FastAPI 接口与静态页面；登录走信息箱的 Miniflux 账号验证 |
| `radar/core.py` | 数据库结构、标准化、去重、查询、行政区推断 |
| `radar/worker.py` | 定时任务入口：`collect` 采集、`retry` 单源重试、`analyze` AI 分析 |
| `radar/collectors.py`、`coverage.py`、`aggregates.py`、`recurring_sources.py`、`official_sources.py`、`eefocus.py` | 各类来源的采集适配器 |
| `radar/details.py`、`source_fields.py` | 从原文中补齐主办方、费用等字段（不调用模型） |
| `radar/safety.py` | 记录来源观察结果，判断活动能否“安排 / 导出日历”（如已取消、信息冲突时禁止） |
| `radar/filtering.py`、`personal.py` | 筛选逻辑；收藏、反馈、浏览记录 |
| `radar/geocode.py` | 行政区补全：先按地名推断，再可选调用高德接口 |
| `radar/calendar.py` | ICS 日历导出 |
| `radar/poster_cache.py`、`posters.py` | 把近期活动的配图预先下载成本机的小 webp，卡片封面和详情海报直接读本机文件 |
| `static/` | 前端（原生 JS + FullCalendar），无构建步骤 |
| `sources.json`、`dedupe_aliases.json` | 来源登记、跨源别名 |
| `scripts/` | 一次性修复脚本（默认只预览，加 `--apply` 才写入）、CI 辅助脚本 |
| `deploy/install.py` | 安装 systemd 单元和 Nginx 路由 |
| `tests/` | 单元、接口、DOM（jsdom）和浏览器（Playwright）测试 |

## 开发与测试

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.lock.txt pytest httpx
.venv/bin/python -m pytest -q
```

DOM 测试需要 jsdom（CI 用 `jsdom@30.1.1`）：

```bash
npm install --prefix /tmp/radar-dom --ignore-scripts jsdom@30.1.1
NODE_PATH=/tmp/radar-dom/node_modules node tests/filter_state_dom.cjs
```

浏览器测试见 `tests/*_browser.py`，CI 配置见 `.github/workflows/validate-events.yml`。只改 `static/` 的提交会自动走较快的“仅前端”检查。

## 上游与许可

- [Community Calendar](https://github.com/judell/community-calendar)：参考了它的 ICS 导出写法（Apache-2.0）
- [FullCalendar](https://github.com/fullcalendar/fullcalendar) 6.1.19：月历组件（MIT）
- [RSSHub](https://github.com/DIYgod/RSSHub)：复用服务器上已有的实例

详见 [THIRD_PARTY.md](THIRD_PARTY.md)。本项目以 Apache-2.0 发布。
