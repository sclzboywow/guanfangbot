# QQ 官方机器人开发台

这是一个面向**自有 QQ 官方机器人开发**的轻量管理台，不做机器人市场、账号运营或多租户平台。

## 核心流程

新增机器人时只填写三项：

1. `AppID`
2. `AppSecret / Key`
3. 公网 `Callback URL`

添加后进入开发工具：

- QQ OpenAPI 请求调试
- 43 项完整事件清单
- HTTP 回调验证、签名校验与事件日志
- 回调验证状态与事件实际接收状态
- 多机器人独立凭证和 Access Token 缓存

Access Token 由后端在调用 OpenAPI 时自动获取、缓存，并在失效后重新申请。管理台不提供手动刷新操作。

## 事件状态检测

事件页完整列出当前 QQ 管理端中的单聊、群、频道和互动事件，共 43 项。

检测状态分为：

- **QQ 已验证**：QQ 平台已向回调地址发送 `op=13` 验证请求，并收到正确签名响应。
- **已收到**：该事件已经真实推送到本服务，页面显示最后接收时间。
- **已记录**：该事件已在本平台的开发清单中勾选，但尚未真实收到。
- **未观察到**：没有收到该事件，不代表 QQ 管理端一定没有开通。

QQ Webhook 当前没有公开接口可读取管理端已经勾选的事件列表，因此本平台不会伪造“已开通”状态。最终订阅项仍需在 QQ 管理端核对；本平台通过回调验证和真实事件到达提供可验证状态。验证时间和事件最后接收时间持久化在 `bots.json`，容器重启后保留。

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

例如：

```text
https://bot.yzdoc.cn/api/events/callback/机器人A的AppID
https://bot.yzdoc.cn/api/events/callback/机器人B的AppID
```

AppID 不是密钥，可以用于区分回调路径。真正需要保密的是 AppSecret / Key。

兼容入口仍保留：

```text
https://你的域名/api/events/callback
```

统一入口仅建议用于单机器人，或由请求头明确提供 AppID 的场景。多机器人正式使用时应采用独立地址，避免回调验签串用凭证。

## API

- `GET /api/bots`
- `POST /api/bots`
- `GET /api/bots/{bot_id}`
- `PATCH /api/bots/{bot_id}`
- `DELETE /api/bots/{bot_id}`
- `GET /api/qqbot/credential-status?bot_id=...`
- `POST /api/qqbot/openapi`
- `GET /api/events/status?bot_id=...`
- `GET /api/events/recent?bot_id=...`
- `POST /api/events/callback/{app_id}`

## 安全

- Key 和 Access Token 不返回前端。
- OpenAPI 调用由后端代理，浏览器只传机器人内部 ID。
- Access Token 由后端自动管理，不提供前端手动刷新接口。
- `backend/data/bots.json` 不应提交到 Git。
- 当前文件存储适合个人开发台；正式多人使用前应增加登录、权限、数据库加密和审计。

QQ 官方要求在服务端使用 `AppID + ClientSecret` 获取 Access Token，并通过 `Authorization: QQBot ACCESS_TOKEN` 调用 OpenAPI。不要把 Access Token 放到浏览器端。
