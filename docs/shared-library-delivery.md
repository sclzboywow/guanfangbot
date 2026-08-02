# 共享文库发货

“功能开发 → 共享文库”使用服务器上的 SQLite 资料索引检索标题，并在用户选择后调用百度网盘创建分享链接。

## 设计边界

- SQLite 资料库由服务端统一持有，QQ群用户不能直接访问数据库。
- 百度网盘账号由服务端统一授权，全部机器人共用这一份网盘授权。
- 前端不填写、不读取、不保存 Access Token 或 Refresh Token，只显示百度设备码授权二维码。
- QQ 群成员只有“检索标题、回复编号、接收分享结果”的能力，不能绑定自己的百度网盘账号。

## 群内流程

1. 用户发送 `@机器人 不动产`。
2. 机器人检索标题，返回总数和前 5 个结果。
3. 同一用户在同一群内直接回复 `1` 到 `5`，不需要再次 @机器人。
4. 后端使用所选记录的 `fsid` 创建百度网盘分享，并发送标题、分享链接、4 位提取码和有效期。

所有群消息均压缩为单行。检索会话默认 3 分钟有效，按机器人、群和用户隔离，成功发货后立即失效。

## SQLite 数据库

默认配置：

```text
数据库路径：/app/data/library.sqlite3
表名：新网盘资料
标题字段：标题
分类字段：分类
大小字段：大小
fsid 字段：fsid
网盘路径字段：网盘地址
```

将本地数据库复制到当前运行的后端容器：

```bash
docker compose cp ./标准库.sqlite3 backend:/app/data/library.sqlite3
```

`/app/data` 使用 `qqbot_data` Docker 数据卷，重新构建容器后数据库仍然保留。复制后在管理页点击“刷新状态”或使用“测试检索”确认表和字段可读取。

资料库通过 SQLite 只读模式打开。检索会话和发货日志保存在 `/app/data/library_delivery.db`，百度授权状态保存在 `/app/data/baidu_oauth.db`。这些数据库均已加入 Git 忽略规则。

## 百度开放平台应用配置

百度应用的 AppKey 与 SecretKey 只写入服务器的 `backend/.env`：

```dotenv
BAIDU_PAN_APP_KEY=你的AppKey
BAIDU_PAN_SECRET_KEY=你的SecretKey
BAIDU_OAUTH_BASE=https://openapi.baidu.com
BAIDU_OAUTH_TIMEOUT=15
```

当前设备码扫码授权流程不使用百度应用的 AppID 或 SignKey。不要把 AppKey、SecretKey、SignKey、Access Token 或 Refresh Token 提交到 Git。

修改 `.env` 后重建后端：

```bash
docker compose up -d --build backend frontend
```

## 扫码授权流程

1. 进入“功能开发 → 共享文库”。
2. 点击“生成授权二维码”。
3. 使用百度网盘 App 扫码并确认授权。
4. 页面按百度返回的轮询间隔自动检查授权状态。
5. 后端使用设备码换取 Access Token 与 Refresh Token，并保存到持久化数据卷。
6. 创建分享前，后端检查 Access Token 有效期；接近过期或接口返回鉴权错误时，使用 Refresh Token 自动续期并重试一次。

二维码图片由后端代理到本站 `/api/library-delivery/oauth/qr/{session_id}`，避免 HTTPS 管理台加载百度 HTTP 二维码时被浏览器拦截。设备码、AppKey、SecretKey 和 Token 不写入浏览器存储。

默认分享参数：

```text
接口：https://pan.baidu.com/rest/2.0/xpan/share
method：rapidshare
有效期：7 天
分享码：每次自动生成 4 位小写字母和数字
```

有效期支持 1 天、7 天、30 天和永久。百度接口权限、账号类型或服务开通状态导致的错误会记录在后台日志中；失败时不会把检索会话标记为已完成，用户可以重新回复编号重试。

## QQ 事件

需要在 QQ 管理端开通：

```text
GROUP_AT_MESSAGE_CREATE
GROUP_MESSAGE_CREATE
```

启用共享文库时，系统会把这两个事件加入本平台的本地事件清单，但不会代替 QQ 管理端授权。

## 与现有功能的关系

- 尚未通过入群验证的成员不会使用共享文库。
- 正处于群消息治理处罚期的成员不会收到资料发货。
- QQ 重复推送同一消息时，消息 ID 去重可以避免重复搜索或重复创建分享链接。

## 安全要求

当前管理台整体仍需要登录或反向代理访问控制。尤其是扫码授权页面必须只允许管理员访问，否则未授权人员可能尝试替换后端绑定的百度网盘账号。生产部署至少应使用 HTTPS，并通过 Nginx Basic Auth、内网访问控制或后续的管理台登录模块保护 `/api/library-delivery/oauth/*` 与其他管理接口。
