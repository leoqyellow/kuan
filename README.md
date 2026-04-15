# 酷安话题瀑布流（实时版）

## 现在支持
- 瀑布流卡片（头像/机型/正文/图片/互动）
- 自动实时刷新（默认 15 秒）+ 手动刷新 + 暂停刷新
- 查看评论（弹窗）
  - 评论数据来源：`api2.coolapk.com/v6/feed/replyList`
  - 数据字段保存在 `data/feeds.json` 的 `commentsByFeedId`
  - 若缓存缺失，前端会调用 `/live/replies` 即时拉取并回填
  - 支持分页“加载更多评论”
- 查看帖子（弹窗）
  - 帖子详情来源：`api2.coolapk.com/v6/feed/detail`
  - 数据字段保存在 `data/feeds.json` 的 `detailsByFeedId`
  - 若缓存缺失，前端会调用 `/live/detail` 即时拉取并回填
- 图片代理加载（同域 `/img/...`），减少外链防盗链导致的图片加载失败
- 多话题抓取：自动从热门话题页发现多个话题并抓取动态
- 图片默认左下角缩略，点击原地展开，再点恢复缩略

## 你的问题：未登录 HAR 能否解决 Cookie
可以明显缓解。
- 你这个 `sdktmp.hubcloud.com.cn_2026_04_14_23_02_20.har` 里，`replyList` 请求只带了 `ddid=...`，没有登录 `uid/token`。
- 这类 Cookie 属于设备标识，稳定性比登录态好很多，适合服务端轮询。
- 但仍可能过期或被风控，失效时需要重新抓一次 HAR。

## 本地运行

### 1) 一次性提取（离线）
```bash
python scripts/extract_feeds.py sdktmp.hubcloud.com.cn_2026_04_14_23_02_20.har
```

### 2) 实时同步（持续更新 feeds.json）
```bash
python scripts/live_sync.py --har sdktmp.hubcloud.com.cn_2026_04_14_23_02_20.har --interval 30 --comments-limit 25 --comment-rows 20
```

## Docker Compose 部署（推荐）

### 1) 启动
```bash
docker compose up -d
```

启动前请确认 HAR 文件在项目根目录（和 `docker-compose.yml` 同级），默认文件名：
`sdktmp.hubcloud.com.cn_2026_04_14_23_02_20.har`

### 2) 查看日志
```bash
docker compose logs -f sync
docker compose logs -f web
```

### 3) 访问
- `http://服务器IP:8080`

### 4) 停止
```bash
docker compose down
```

## Docker 结构
- `web`：Nginx 静态站点（读取项目目录）
- `api`：实时接口（`/live/replies`、`/live/detail`），用于点击时即时拉评论/详情
- `sync`：Python 轮询酷安接口并更新 `data/feeds.json` + `data/feeds.js`
- 配置文件：`docker-compose.yml`、`deploy/nginx.docker.conf`

## 刷新无效排查（重点）
如果页面看起来一直是抓包静态数据，按下面顺序检查：

1. 看 `sync` 是否真的在拉取成功
```bash
docker compose logs -f sync
```
日志里要看到类似：
`[OK] ... updated feeds: ... comments: ...`

2. 检查容器内数据文件是否在变化
```bash
docker compose exec sync sh -c "ls -l data/feeds.json && tail -n 20 data/feeds.json"
```

3. 页面顶部看“数据版本”
- 我已加了 `数据版本：<updatedAt>(<source>)` 显示。
- 如果时间不变，说明后端没有成功写新数据。
- 如果时间在变但内容不变，可能是接口本身暂无新帖。

4. 强制重拉并重启
```bash
docker compose down
docker compose up -d --force-recreate
```

## 可调参数
在 `docker-compose.yml` 的 `sync.command` 中改：
- `--interval`：轮询秒数
- `--comments-limit`：每轮拉评论的帖子数量
- `--comment-rows`：每帖拉多少条评论
- `--detail-limit`：每轮拉详情的帖子数量
- `--topics-max`：每轮最多抓取多少个热门话题
- `--no-discover-topics`：关闭自动多话题发现

## 线上 Nginx（非 Docker）
- 参考：`deploy/nginx.coolapk-wall.conf`
