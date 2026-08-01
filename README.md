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
- 群成员入群数学题验证
- 群广告识别、警告与阶梯撤回
- 多机器人独立凭证和 Access Token 缓存

Access Token 由后端在调用 OpenAPI 时自动获取、缓存，并在失效后重新申请。管理台不提供手动刷新操作。

## 入群验证

“功能开发 → 入群验证”提供按机器人启用的群成员验证功能：

1. 收到 `GROUP_MEMBER_ADD` 后创建永久待验证记录，并向群内发送一道简单加减法题。
2. 用户无需 @ 机器人，直接发送纯数字答案。
3. 收到 `GROUP_MESSAGE_CREATE` 时，答案正确则标记通过；错误答案、普通聊天、图片或文件等消息会调用群消息撤回接口。
4. 待验证状态没有自动超时，会持续到用户答对、收到 `GROUP_MEMBER_REMOVE`，或管理员在开发台结束记录。
5. 所有机器人发送到群里的题目、通过提示和管理员操作提示都会在后端统一压缩为单行文本，不包含换行。

启用前需要在 QQ 管理端开通并实际推送：

- `GROUP_MEMBER_ADD`
- `GROUP_MESSAGE_CREATE`
- `GROUP_MEMBER_REMOVE`

机器人还需要在目标群中具备撤回成员消息所需的管理员权限。验证会话、撤回计数和操作日志保存在 Docker 数据卷内的 `group_verification.db`，容器重启后保留。

## 群消息治理

“功能开发 → 群消息治理”用于处理群内广告：

- 检测中国大陆手机号、带区号座机以及 400/800 电话。
- 检测带联系方式语义的微信号，例如“加微信 abc123”。普通讨论“微信支付”不会仅因出现“微信”二字触发。
- 检测可配置的消息广告词，例如发票、代开、贷款、放款、套现和办证。
- 检测昵称广告词；昵称持续违规时，当前处罚期内只撤回，不会因每次发言自动升级。
- 首次命中后撤回触发消息并发送单行警告；处罚期内该成员后续所有群消息均自动撤回。
- 默认阶梯为 10 分钟、1 小时、24 小时、7 天，第 5 次明确违规后永久撤回。
- 处罚期内的普通聊天不会加级；再次明确发送广告且超过升级冷却时间才进入下一阶。
- 群主和管理员默认豁免；后台可以解除处罚、清零次数、手动永久治理或加入白名单。

启用前需要开通 `GROUP_MESSAGE_CREATE`，并确保机器人在目标群中具备撤回群成员消息的管理员权限。治理状态、消息去重和日志保存在 `group_moderation.db`。

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
- 后端：FastAPI、SQLite
- 部署：Docker Compose、Nginx
- 配置存储：Docker 数据卷中的 `bots.json`
- 入群验证状态：Docker 数据卷中的 `group_verification.db`
- 群消息治理状态：Docker 数据卷中的 `group_moderation.db`

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
- `GET /api/group-verification/status?bot_id=...`
- `PUT /api/group-verification/settings/{bot_id}`
- `POST /api/group-verification/sessions/{session_id}/verify`
- `POST /api/group-verification/sessions/{session_id}/reset`
- `POST /api/group-verification/sessions/{session_id}/close`
- `GET /api/group-moderation/status?bot_id=...`
- `PUT /api/group-moderation/settings/{bot_id}`
- `POST /api/group-moderation/members/{member_id}/release`
- `POST /api/group-moderation/members/{member_id}/permanent`
- `POST /api/group-moderation/members/{member_id}/trust`
- `POST /api/group-moderation/members/{member_id}/untrust`

## 安全

- Key 和 Access Token 不返回前端。
- OpenAPI 调用由后端代理，浏览器只传机器人内部 ID。
- Access Token 由后端自动管理，不提供前端手动刷新接口。
- `backend/data/bots.json`、`backend/data/group_verification.db*` 和 `backend/data/group_moderation.db*` 不应提交到 Git。
- 功能管理接口当前面向自用开发台；公开部署前必须增加登录、权限控制和操作审计。

QQ 官方要求在服务端使用 `AppID + ClientSecret` 获取 Access Token，并通过 `Authorization: QQBot ACCESS_TOKEN` 调用 OpenAPI。不要把 Access Token 放到浏览器端。
