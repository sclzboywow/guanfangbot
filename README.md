# QQ 官方机器人管理台起步项目

这是一个基于 QQ 机器人管理后台视觉风格制作的独立开发项目，包含：

- Vue 3 + Vite + TypeScript 前端
- FastAPI 后端
- 机器人列表、详情管理、事件配置、开发者测试、API 调试台
- QQ Bot `access_token` 服务端缓存
- QQ OpenAPI 服务端代理（限制到官方 API 域名，避免把密钥暴露到浏览器）
- 默认模拟数据，可在没有机器人密钥时直接运行页面

> 该项目不是 QQ 官方产品，也不包含任何真实账号、头像、邮箱、AppSecret 或 Access Token。

## 目录

```text
qqbot-admin-starter/
├─ frontend/              Vue 管理台
├─ backend/               FastAPI 服务端
├─ docker-compose.yml
└─ README.md
```

## 无需安装的页面预览

直接双击打开 `standalone/index.html`，即可查看和操作仿制管理台。该版本不会发送真实 API 请求。

## 本地启动

### 1. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.example .env
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。

## 配置真实机器人

编辑 `backend/.env`：

```env
QQBOT_APP_ID=你的AppID
QQBOT_CLIENT_SECRET=你的AppSecret
QQBOT_API_BASE=https://api.bot.qq.com
QQBOT_TOKEN_URL=https://api.bot.qq.com/app/getAppAccessToken
```

密钥只能放在后端 `.env`，不要写入 Vue 文件、浏览器 LocalStorage 或提交到 Git。

## 已实现接口

- `GET /api/health`：服务健康状态
- `GET /api/bots`：机器人列表（默认模拟数据）
- `GET /api/bots/{id}`：机器人详情
- `PATCH /api/bots/{id}`：修改本地展示信息
- `GET /api/qqbot/credential-status`：检查后端是否配置凭证
- `POST /api/qqbot/token/refresh`：刷新 Access Token
- `POST /api/qqbot/openapi`：调用 QQ 官方 OpenAPI
- `GET /api/events/recent`：读取最近事件
- `POST /api/events/callback`：预留 HTTP 事件回调入口

## API 调试台请求示例

在页面“API 调试台”中填写：

```text
GET /users/@me
```

后端会自动添加：

```text
Authorization: QQBot ACCESS_TOKEN
```

## 安全说明

- OpenAPI 代理只接受相对路径，不能指定任意域名。
- Access Token 只在后端内存中缓存。
- API 调试台默认拒绝包含 `authorization`、`cookie`、`clientSecret` 等敏感自定义头。
- 当前事件回调接口仅用于开发起步；正式上线前应按官方文档加入签名校验、重放防护、持久化和权限控制。

## 后续推荐开发顺序

1. 接入真实机器人基本信息与状态。
2. 按实际场景封装单聊、群聊、频道消息函数。
3. 完成事件订阅校验和事件分发器。
4. 增加数据库，保存机器人配置、事件日志和操作审计。
5. 增加管理台登录与角色权限，禁止公开暴露调试台。
