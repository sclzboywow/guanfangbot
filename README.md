# QQ 官方机器人开发台

这是一个面向**自有 QQ 官方机器人开发**的轻量管理台，不做机器人市场、账号运营或多租户平台。

## 核心流程

新增机器人时只填写三项：

1. `AppID`
2. `AppSecret / Key`
3. 公网 `Callback URL`

添加后进入开发工具：

- Access Token 状态与手动刷新
- QQ OpenAPI 请求调试
- 事件订阅记录
- HTTP 回调验证、签名校验与事件日志
- 多机器人独立凭证和 Token 缓存

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：FastAPI
- 部署：Docker Compose、Nginx
- 配置存储：Docker 数据卷中的 `bots.json`

## 启动

```bash
cp backend/.env.example backend/.env
docker compose up -d --build
```

默认访问：

```text
http://服务器IP:5173
```

生产环境建议由宿主机 Nginx 或云负载均衡将域名 HTTPS 转发到 `127.0.0.1:5173`。

## 多机器人回调

推荐每个机器人使用带 AppID 的独立地址：

```text
https://你的域名/api/events/callback/{AppID}
```

兼容入口仍保留：

```text
https://你的域名/api/events/callback
```

统一入口仅建议用于单机器人，或由请求头提供 AppID 的场景。

## API

- `GET /api/bots`
- `POST /api/bots`
- `GET /api/bots/{bot_id}`
- `PATCH /api/bots/{bot_id}`
- `DELETE /api/bots/{bot_id}`
- `GET /api/qqbot/credential-status?bot_id=...`
- `POST /api/qqbot/token/refresh?bot_id=...`
- `POST /api/qqbot/openapi`
- `GET /api/events/recent?bot_id=...`
- `POST /api/events/callback/{app_id}`

## 安全

- Key 和 Access Token 不返回前端。
- OpenAPI 调用由后端代理，浏览器只传机器人内部 ID。
- `backend/data/bots.json` 不应提交到 Git。
- 当前文件存储适合个人开发台；正式多人使用前应增加登录、权限、数据库加密和审计。

QQ 官方要求在服务端使用 `AppID + ClientSecret` 获取 Access Token，并通过 `Authorization: QQBot ACCESS_TOKEN` 调用 OpenAPI。不要把 Access Token 放到浏览器端。
