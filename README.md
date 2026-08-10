# QQ 官方机器人开发台

这是一个面向**自有 QQ 官方机器人开发**的轻量管理台，不做机器人市场、账号运营或多租户平台。

## 核心能力

新增机器人时只填写：

1. `AppID`
2. `AppSecret / Key`
3. 公网 `Callback URL`

开发台提供：

- QQ OpenAPI 请求调试
- 44 项完整事件清单（含 `GROUP_JOIN_REQUEST`）
- HTTP 回调验证、签名校验与事件日志
- QQ 官方入群审批、自动审批策略与成员禁言
- 群成员入群后数学题与自定义问题验证
- 群广告识别、撤回与QQ官方阶梯禁言
- SQLite 共享文库检索和百度网盘自动发货
- 多机器人独立 QQ 凭证和 Access Token 缓存

QQ Access Token 由后端在调用 OpenAPI 时自动获取、缓存并续期，不提供前端手动刷新操作。

## QQ 官方群管理

“功能开发 → 官方群管理”面向不熟悉接口的用户，所有操作均使用表单完成：

- 实时接收 `GROUP_JOIN_REQUEST`，并可从自动识别的群列表同步遗漏申请；
- 通过、拒绝、填写拒绝原因或拒绝并加入群黑名单；
- 人工审批和白名单自动审批分别提供独立开关；
- 从群台账直接选择群 OpenID 创建自动审批策略，不再要求用户手填群标识；
- 启停策略、修改到期时间和备注、增删关联群；
- 批量新增或删除白名单QQ号，后台按官方每批 10000 个的限制自动分批；
- 执行现有申请扫描，并明确提示该任务由QQ异步处理；
- 从事件和申请记录直接选择成员，查询、新增、修改或解除官方禁言。

机器人必须是目标群管理员，并在QQ开放平台勾选 `GROUP_JOIN_REQUEST`。平台内的一键启用只会将事件加入本地清单，不能代替QQ开放平台授权。

群管理状态保存在 Docker 数据卷内的 `group_management.db`。群台账会从事件及官方群信息接口自动保存群 OpenID、可获得的群号、群名、简介、分类、标签和人数。QQ官方接口仍是审批、策略和禁言状态的事实来源，本地数据库保存群台账、事件申请、功能开关和操作审计。白名单是唯一仍需用户提供标识的地方，因为官方接口要求真实QQ号，不能由成员 OpenID 反推。

已接入的官方能力：

| 用户操作 | 官方接口 |
| --- | --- |
| 同步入群申请 | [`GET join_request_list`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_join_request_list.get.html) |
| 通过、拒绝、拒绝并拉黑 | [`POST approval_join_request`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post.html) |
| 查询成员与全员禁言状态 | [`GET restrict_chat_setting`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_restrict_chat_setting.get.html) |
| 单个或批量新增、修改、解除成员禁言 | [`POST restrict_chat_setting`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_restrict_chat_setting.post.html) |
| 查询与创建自动审批策略 | [`GET strategy`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy.get.html) / [`POST strategy`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy.post.html) |
| 修改与删除策略 | [`PATCH strategy`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy_strategy_id.patch.html) / [`DELETE strategy`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy_strategy_id.delete.html) |
| 扫描现有申请 | [`POST execute`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy_strategy_id_execute.post.html) |
| 批量增删白名单QQ号 | [`POST whitelist_users`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_join_approval_strategy_strategy_id_whitelist_users.post.html) |

## 入群后验证

“官方群管理 → 入群后验证”与入群前审批相互独立：

1. 数学题和自定义问题各有独立开关；同时开启时可要求两种都答对，也可随机选择一种。
2. 收到 `GROUP_MEMBER_ADD` 后创建限时验证记录；答题阶段不预先禁言。
3. 用户无需 @ 机器人，直接发送当前问题的答案；正确后立即通过，其他消息会调用群消息撤回接口。
4. 达到最大错误次数或验证超时后，调用QQ官方成员禁言接口；默认超时3分钟、最多错误3次、失败禁言24小时，均可配置。
5. 管理员重新出题或手动通过时，会先调用官方解除禁言，再更新本地验证状态。
6. 验证禁言、广告治理禁言和管理台人工禁言按来源分别记录；解除验证禁言不会误解除仍生效的治理处罚。
7. 所有机器人发送到群里的题目、通过提示和管理员操作提示都会压缩为单行文本。

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
- 合并转发与群名片可分别选择“仅撤回”或“撤回并官方禁言”，并填写专项禁言时长。
- 首次命中后撤回触发消息，并优先调用QQ官方成员禁言接口；可关闭官方群禁言并回退为连续撤回。
- 默认阶梯为 10 分钟、1 小时、24 小时、7 天，第 5 次明确违规后进入长期治理。
- 群主和管理员默认豁免；后台可以解除处罚、清零次数、手动长期治理或加入白名单。

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

事件页完整列出单聊、群、频道和互动事件，共 44 项。

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
- 官方群管理：`group_management.db`
- 入群验证：`group_verification.db`
- 群消息治理：`group_moderation.db`
- 多来源禁言协调：`group_mute_leases.db`
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
- `GET /api/group-management/status?bot_id=...`
- `PUT /api/group-management/settings/{bot_id}`
- `POST /api/group-management/join-requests/sync`
- `POST /api/group-management/join-requests/decision`
- `GET|POST /api/group-management/mutes`
- `GET|POST /api/group-management/strategies`
- `PATCH|DELETE /api/group-management/strategies/{strategy_id}`
- `POST /api/group-management/strategies/{strategy_id}/execute`
- `POST /api/group-management/strategies/{strategy_id}/whitelist`
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
