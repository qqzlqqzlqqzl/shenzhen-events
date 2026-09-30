# Shenzhen Events Radar

一个部署在私人服务器上的深圳线下活动聚合器。目标不是“收集尽可能多的链接”，而是把公开活动源统一成可搜索、可去重、可收藏、可订阅日历的活动数据，并尽量减少人工筛选。

## 当前能力

- 独立页面：`/events/`，不与个人信息箱、NewAPI、博客前端混合。
- 九个公开来源：联谱、TechEvent、本地宝、柴火官网、活动行 RSSHub、豆瓣同城、Meetup、柴火公众号 RSSHub、搜狗微信发现。
- 证据优先：文章发布时间不会被当成活动日期；AI 不能证明的日期/地点保持“待确认”。
- 跨源去重：日期 + 标题/地点保守匹配，并支持精确 URL/date 别名处理品牌标题漂移。
- 标准活动类型：采用 Schema.org Event taxonomy；会议、黑客松、展览、音乐、戏剧、喜剧/脱口秀、体育、社交等不再混成自定义一级分类。
- 主题标签与活动类型分离：AI/开源、机器人、硬件创客、汽车等只作为主题；活动类型和主题均支持多选组合。
- 收藏、搜索、免费/区域/多选类型与主题过滤、周末视图、FullCalendar 月历、私人 ICS。
- 来源健康、失败退避、模型日预算、日志截断、数据库/日志存储上限。
- 可选高德 Web 服务辅助补全“有场馆但缺行政区”的活动；只补 district，原始地点保持不变。
- 手机和桌面浏览器验收。

## 架构

```text
公开网页 / RSS / 搜狗
        ↓
RSSHub + bounded source adapters
        ↓
normalize → evidence checks → conservative dedupe
        ↓
optional AMap district enrichment (cached + bounded)
        ↓
SQLite (WAL)
        ↓
Schema.org event type + subject tags
        ↓
incremental AI classification (new/changed only)
        ↓
FastAPI :8093
        ↓
Nginx /events/
        ↓
独立 Web UI + FullCalendar + ICS
```

## 运行边界

- 不绕过登录、验证码或访问限制；遇到限制记录为 `blocked` 并退避。
- 搜狗搜索只用于发现线索；候选公众号不自动当成可信活动源。
- 抓取任务为 systemd oneshot timer，不常驻浏览器、Redis 或第二套数据库。
- 公开来源变更时保留上次可用数据，并在“来源状态”里显示失败。
- `.private/`、数据库、日志、密钥、环境变量文件均不进入 Git。

## 目录

- `radar/collectors.py`：公开源适配器。
- `radar/core.py`：标准化、SQLite、去重与查询。
- `radar/worker.py`：定时采集、AI 分类、预算、保留策略。
- `radar/api.py`：私有 API 与静态站点。
- `radar/calendar.py`：ICS 导出。
- `radar/geocode.py`：可选高德地理编码/POI 区域补全；私有 Key 从 `.private/amap.key` 读取。
- `static/`：独立活动雷达前端。
- `sources.json`：来源与抓取频率。
- `dedupe_aliases.json`：有官方证据的精确跨源别名。
- `deploy/install.py`：仅安装本项目服务/路由并提供回滚。
- `tests/`：单元、接口与生产浏览器验收。

## 部署

项目运行于 `/home/ubuntu/shenzhen-events`。依赖使用锁定的 `requirements.lock.txt`。部署脚本只操作 `shenzhen-events*` systemd 单元、`/events/` Nginx snippet 和统一门户中的第 4 张卡片；不会重启信息箱、NewAPI 或博客相关服务。

## 开发流程

本项目遵循：

`Issue → feature branch → tests → PR → review → production acceptance → merge`

生产验收至少覆盖：

- `/`、`/inbox/`、`/newapi`、`/blog`、`/events/` 回归；
- 未登录 API 拒绝访问；
- 桌面/手机无横向溢出；
- 搜索、过滤、收藏、详情来源链接；
- FullCalendar 与 ICS；
- 浏览器 console/page error 为零。

## 上游与设计来源

本项目优先复用成熟组件而不是重复造轮子：

- RSSHub：已有活动行、微信公众号等采集基础设施。
- Community Calendar：参考其“来源适配 → ICS/标准化 → 跨源去重 → 来源归因”的成熟设计；本仓库实现针对深圳与现有服务器栈做了独立适配。
- FullCalendar：前端日历组件，MIT License，许可证保存在 `static/vendor/FullCalendar-LICENSE.md`。
- 搜狗微信：低频关键词发现；验证码出现时停止，不绕过验证。

详见 `THIRD_PARTY.md`。

## License

Apache-2.0。第三方组件按各自许可证使用。
