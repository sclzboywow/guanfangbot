# QQ 官方机器人开发台

这是一个面向**自有 QQ 官方机器人开发**的轻量管理台，不做机器人市场、账号运营或多租户平台。

## 核心能力

新增机器人时只填写：

1. `AppID`
2. `AppSecret / Key`
3. 公网 `Callback URL`

开发台提供：

- QQ OpenAPI 请求调试
- 43 项完整事件清单
- HTTP 回调验证、签名校验与事件日志
- 群成员入群数学题验证
- 群广告识别、警告与阶梯撤回
- SQLite 共享文库检索和百度网盘自动发货
- 多机器人独立 QQ 凭证和 Access Token 缓存

QQ Access Token 由后端在调用 OpenAPI 时自动获取、缓存并续期，不提供前端手动刷新操作。

## 入群验证

“功能开发 → 入群验证”提供按机器人启用的群成员验证：

1. 收到 `GROUP_MEMBER_ADD` 后创建永久待验证记录，并向群内发送一道简单加减法题。
2. 用户无需 @ 机器人，直接发送纯数字答案。
3. 收到 `GROUP_MESSAGE_CREATE` 时，答案正确则标记通过；错误答案、普通聊天、图片或文件等消息会调用群消息撤回接口。
4. 待验证状态没有自动超时，会持续到用户答对、收到 `GROUP_MEMBER_REMOVE`，或管理员在开发台结束记录。
5. 所有机器人发送到群里的题目、通过提示和管理员操作提示都会压缩为单行文本。

需要在 QQ 管理端开通：

- `GROUP_MEMBER_ADD`
- `GROUP_MESSAGE_CREATE`
- `GROUP_MEMBER_REMOVE`

机器人还需要在目标群中具备撤回成员消息所需的管理员权限。验证状态保存在 Docker 数据卷内的 `group_verification.db`。

## 群消息治理

“功能开发 → 群消息治理”用于处理群内广告：

- 检测手机号、带区号座机以及 400/800 电话。
- 检测带联系方式语义的微信号。
- 检测可配置的消息广告词和昵称广告词。
- 首次命中后撤回触发消息并发送单行警告；处罚期内该成员后续消息自动撤回。
- 默认阶梯为 10 分钟、1 小时、24 小时、7 天，第 5 次明确违规后永久撤回。
- 群主和管理员默认豁免；后台可以解除处罚、清零次数、手动永久治理或加入白名单。

需要开通 `GROUP_MESSAGE_CREATE`，并确保机器人具备群管理员撤回权限。治理状态保存在 `group_moderation.db`。

## 共享文库发货

“功能开发 → 共享文库”使用服务器上的 SQLite 数据库检索标题：

1. 用户发送 `@机器人 + 标题关键词`。
2. 机器人返回匹配总数和前 5 个结果。
3. 同一用户在同一群直接回复 `1` 到 `5`。
4. 后端使用对应 `fsid` 创建百度网盘分享，并发送标题、链接、4 位提取码和有效期。

资料库和百度账号均由服务端统一持有。QQ群用户只有检索和发货能力，不能访问数据库、绑定自己的网盘账号或获取任何凭证。

百度授权使用设备码扫码流程：

- 百度应用 AppKey 与 SecretKey 只配置在 `backend/.env`。
- 前端只显示授权二维码，不填写或读取 Access Token。
- 后端保存 Access Token、Refresh Token 和过期时间。
- 创建分享前自动检查并刷新 Token；鉴权失败时自动刷新并重试一次。
- 全部机器人共用这一份后端百度网盘授权。

服务器环境变量：

```dotenv
BAIDU_PAN_APP_KEY=你的AppKey
BAIDU_PAN_SECRET_KEY=你的SecretKey
BAIDU_OAUTH_BASE=https://openapi.baidu.com
BAIDU_OAUTH_TIMEOUT=15
```

设备码流程不使用百度应用的 AppID 或 SignKey。不要把 AppKey、SecretKey、SignKey 或 Token 提交到 Git。

默认数据库映射：

```text
数据库：/app/data/library.sqlite3
表：新网盘资料
字段：标题、分类、大小、fsid、网盘地址
```

需要在 QQ 管理端开通：

- `GROUP_AT_MESSAGE_CREATE`
- `GROUP_MESSAGE_CREATE`

详细部署和扫码说明见 `docs/shared-library-delivery.md`。

## 事件状态检测

事件页完整列出单聊、群、频道和互动事件，共 43 项。

状态分为：

- **QQ 已验证**：QQ 平台已完成 `op=13` 回调验证。
- **已收到**：该事件已经真实推送到本服务。
- **已记录**：该事件已在本平台的开发清单中勾选，但尚未真实收到。
- **未观察到**：没有收到该事件，不代表 QQ 管理端一定没有开通。

QQ Webhook 当前没有公开接口可读取管理端已经勾选的事件列表，因此最终订阅项仍需在 QQ 管理端核对。

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：FastAPI、SQLite
- 部署：Docker Compose、Nginx
- 机器人配置：`bots.json`
- 入群验证：`group_verification.db`
- 群消息治理：`group_moderation.db`
- 文库会话与日志：`library_delivery.db`
- 百度授权：`baidu_oauth.db`

这些运行文件都位于 Docker 数据卷 `/app/data` 中，不应提交到 Git。

## 启动

```bash
cp backend/.env.example backend/.env
docker compose up -d --build
```

默认访问：

```text
http://服务器IP:5173
```

生产环境建议使用 HTTPS，并由宿主机 Nginx 或云负载均衡转发到 `127.0.0.1:5173`。

## 多机器人回调

推荐每个机器人使用带 AppID 的独立地址：

```text
https://你的域名/api/events/callback/{AppID}
```

兼容入口仍保留：

```text
https://你的域名/api/events/callback
```

多机器人正式使用时应采用独立地址，避免回调验签串用凭证。

## 主要 API

- `GET /api/bots`
- `POST /api/bots`
- `GET /api/bots/{bot_id}`
- `PATCH /api/bots/{bot_id}`
- `DELETE /api/bots/{bot_id}`
- `POST /api/qqbot/openapi`
- `GET /api/events/status?bot_id=...`
- `GET /api/events/recent?bot_id=...`
- `POST /api/events/callback/{app_id}`
- `GET /api/group-verification/status?bot_id=...`
- `PUT /api/group-verification/settings/{bot_id}`
- `GET /api/group-moderation/status?bot_id=...`
- `PUT /api/group-moderation/settings/{bot_id}`
- `GET /api/library-delivery/status?bot_id=...`
- `PUT /api/library-delivery/settings/{bot_id}`
- `POST /api/library-delivery/test-search`
- `POST /api/library-delivery/oauth/start?bot_id=...`
- `POST /api/library-delivery/oauth/poll/{session_id}`
- `GET /api/library-delivery/oauth/qr/{session_id}`

## 安全

- QQ Key、百度 SecretKey、Access Token 和 Refresh Token 不返回前端。
- OpenAPI 与百度网盘分享调用都由后端代理。
- SQLite 资料库使用只读模式打开。
- `.env`、`backend/data/*.json` 和 `backend/data/*.db*` 不应提交到 Git。
- 当前功能管理接口面向自用开发台。公开部署前必须增加登录、访问控制和操作审计。
- 扫码授权页面尤其需要管理员访问控制，否则未授权人员可能尝试替换后端绑定的百度网盘账号。
