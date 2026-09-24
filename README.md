# 香港二手 iPhone 交易平台

面向香港市场的二手 iPhone B2C 交易平台，首发站为香港，首版采用 B2C，并由平台代收货
款。平台负责商家与个人卖家资格、库存、商品页、订单、账本和履约状态；实际收款、退款和
商户结算由香港持牌支付服务商（PSP）处理，平台不自建钱包，也不直接沉淀用户资金。

当前代码已具备用户与角色、Cookie 登录、商家、库存、平台销售商品、公开商店、订单、
付款回调、履约、退款、商家结算、复式账本和运营台闭环。开发环境默认使用内置 mock PSP
完成端到端验证；生产环境禁止 mock，必须配置真实持牌 PSP。Stripe Checkout 适配器和签名
回调契约已实现并有自动化覆盖，但尚未使用真实 Stripe 凭证和账户完成沙箱验收。C2C、个人
卖家自主发布和商家自助入驻在后续阶段开放。

当前实现采用“模块化单体 + 异步采集 Worker”：

- FastAPI 提供公开行情、商店与订单 API、账户会话 API 和内部运营 API。
- Celery + Redis 执行来源采集、重试、死信记录和定时维护。
- PostgreSQL 是商品、观测历史、估值、提醒和审计的事实来源。
- OpenSearch 是可选的搜索投影，未配置或暂时不可用时自动回退 PostgreSQL。
- S3 或 MinIO 保存短期原始快照，本地开发也可使用文件目录。
- Next.js 提供公开商店、行情搜索、买家注册登录和内部运营台。

## 架构

```text
公开来源 / 合作数据
        |
Celery Beat -> Collection Queue -> Browser Worker / HTTP Worker
        |
来源运行记录 -> 原始快照 -> 清洗归一化 -> 分类与地点映射
        |
跨来源去重聚类 -> PostgreSQL 商品主数据 -> OpenSearch 搜索投影
        |
估值 / 机会评分 / 提醒 / 全港 18 区行情统计
        |
平台商家 -> 库存与验机资料 -> 平台销售商品
        |
公开商店 + 买家账户 + 内部运营台

订单 -> 持牌 PSP 代收 -> 确认收貨 -> 商家结算与复式账本
```

关键边界：

- `source`：来源、频率、登录要求和健康状态。
- `listing`：来源内唯一商品，唯一键为 `(source_key, source_listing_id)`。
- `listing_snapshot`：每次观测到的价格、状态、地区和采集时间。
- `listing_cluster`：跨来源疑似重复记录，不合并或丢失原始来源。
- `phone_variant`：机型、代际、容量和别名。
- `valuation`：估值版本、区间、置信度、样本和费用假设。
- `watchlist` / `alert`：订阅条件、触发记录和通知状态。
- `user` / `user_role` / `auth_session`：买家、商家与内部员工的账户和 Cookie 会话。
- `merchant`：平台自营、B2C 商家，以及为后续 C2C 预留的个人卖家类型。
- `inventory_item`：SKU、成色、电池、维修记录、配件、成本和库存状态。
- `seller_listing`：平台实际销售商品；草稿发布后才出现在公开商店。
- `order` / `order_event`：订单状态、幂等下单、库存预留和完整状态轨迹。
- `payment_intent` / `payment_event`：PSP 付款请求、签名回调和回调去重。
- `refund`：退款幂等键、PSP 退款引用和退款状态。
- `merchant_settlement`：买家确认收貨后的商家应收和平台佣金。
- `ledger_account` / `ledger_journal` / `ledger_entry`：付款、结算和退款复式账本。
- `audit_log`：重新采集、数据修正、权限和运营操作。

所有写入必须幂等。单来源失败不会阻塞其他来源，原始采集、标准化和估值结果均保留版本信息，方便回溯与重算。

## 目录

```text
iphone_market/platform/      平台领域模型、仓储、API、采集、估值和任务
iphone_market/collectors/    Carousell HK、DCFever 及保留的旧来源适配器
migrations/                  Alembic 数据库迁移
tests/                       后端契约、幂等、权限、估值和采集测试
web/                         Next.js 公众站和内部运营台
design-system/               已确认的产品与视觉约束
docker-compose.yml           本地完整依赖栈
Dockerfile                   API、Worker、Beat 共用后端镜像
```

## 使用 Docker Compose

### 环境要求

- Docker Engine 24+
- Docker Compose v2
- 建议至少 6 GB 可用内存，OpenSearch 默认占用约 512 MB 至 1 GB

### 启动

PowerShell：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少替换以下值：

```text
POSTGRES_PASSWORD
PLATFORM_API_KEY
MINIO_ROOT_PASSWORD
OBJECT_STORE_SECRET_KEY
```

如需在首次启动时创建管理员，还需设置：

```text
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_NAME=Platform Admin
BOOTSTRAP_ADMIN_PASSWORD=至少12個字元
```

然后启动：

```powershell
docker compose up --build -d
docker compose ps
```

首次启动会自动：

1. 启动 PostgreSQL、Redis、OpenSearch 和 MinIO。
2. 创建原始快照 bucket。
3. 执行 Alembic 迁移。
4. 启动 API、采集 Worker、Beat 和 Web。

首次创建管理员：

```powershell
docker compose exec api iphone-platform seed
```

也可以通过 `iphone-platform create-admin --email ... --name ...` 显式创建管理员。

服务地址：

- 公众商店与买家账户：`http://127.0.0.1:3000`
- API：`http://127.0.0.1:8000`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- OpenSearch：`http://127.0.0.1:9200`
- MinIO 控制台：`http://127.0.0.1:9001`

查看日志或停止：

```powershell
docker compose logs -f api worker beat web
docker compose down
```

删除本地数据卷并完全重建：

```powershell
docker compose down -v
```

### 首次采集

进入 API 容器执行一个来源：

```powershell
docker compose exec api iphone-platform collect-source dcfever
```

采集全部已启用来源：

```powershell
docker compose exec api iphone-platform collect-all
```

也可以登录 Web 运营台 `/ops`，点击“重新采集”。Carousell HK 可能需要首次人工登录或安全验证，生产环境应先在持久化浏览器配置目录完成授权，再交给无人值守 Worker。

### 导入现有 SQLite 历史

若已有 `data/market.sqlite3`，可在本机安装后端后执行：

```powershell
iphone-platform import-legacy data/market.sqlite3
iphone-platform refresh-valuations
```

执行前确保 `DATABASE_URL` 指向目标 PostgreSQL。

## 本地开发

### 后端使用 SQLite

不设置 `DATABASE_URL` 时，平台默认使用 `data/platform.sqlite3`。这适合测试和单机开发。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
playwright install chromium

iphone-platform migrate
iphone-platform seed
iphone-platform serve --host 127.0.0.1 --port 8000
```

Windows 默认使用：

```text
C:\Program Files\Google\Chrome\Application\chrome.exe
```

若 Chrome 位于其他位置：

```powershell
$env:IPHONE_MARKET_CHROME = "D:\Chrome\chrome.exe"
```

Linux 或容器中未设置 `IPHONE_MARKET_CHROME` 时，会使用 Playwright 安装的 Chromium。

### Web

另开一个终端：

```powershell
cd web
npm ci
npm run dev -- --hostname 127.0.0.1 --port 3000
```

本地默认配置：

```text
PLATFORM_API_URL=http://127.0.0.1:8000
```

买家登录和内部员工登录均通过后端会话 API 取得 Bearer Token，Next.js 将它写入
HttpOnly Cookie。服务端请求再通过 Cookie 读取 Token；浏览器脚本不会获得 Token。
公开注册由 `ALLOW_PUBLIC_REGISTRATION` 控制，生产环境应同时启用 HTTPS 和 OIDC。

## 主要配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | `production` 时关闭 API 文档 |
| `DATABASE_URL` | `sqlite:///data/platform.sqlite3` | PostgreSQL 示例：`postgresql+psycopg://...` |
| `AUTO_CREATE_SCHEMA` | `true` | 生产应设为 `false`，由 Alembic 管理结构 |
| `AUTH_MODE` | `disabled` | 可设为 `api_key` 或 `oidc` |
| `PLATFORM_API_KEY` | 空 | `api_key` 模式的内部访问凭证 |
| `SESSION_TTL_HOURS` | `336` | Cookie 会话有效小时数，默认 14 天 |
| `ALLOW_PUBLIC_REGISTRATION` | `true` | 是否开放买家自助注册 |
| `BOOTSTRAP_ADMIN_EMAIL` | 空 | 可选，首次初始化管理员邮箱 |
| `BOOTSTRAP_ADMIN_NAME` | `Platform Admin` | 初始化管理员显示名称 |
| `BOOTSTRAP_ADMIN_PASSWORD` | 空 | 初始化管理员密码，生产至少 12 个字符 |
| `OIDC_ISSUER` | 空 | OIDC Issuer |
| `OIDC_AUDIENCE` | 空 | OIDC Audience |
| `OIDC_JWKS_URL` | 空 | OIDC JWKS 地址 |
| `INTERNAL_ROLES` | `admin,operator,analyst` | 可进入内部接口的角色 |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` | Celery Broker |
| `CELERY_RESULT_BACKEND` | `redis://127.0.0.1:6379/1` | Celery 结果后端 |
| `COLLECTION_LIMIT` | `30` | 每个来源和机型的采集上限 |
| `BROWSER_MAX_CONCURRENCY` | `2` | 跨 Worker 的浏览器并发槽 |
| `COLLECTION_SCHEDULE_HOUR` | `8` | 香港时间每日采集小时 |
| `OPENSEARCH_URL` | 空 | 留空时搜索回退 PostgreSQL |
| `OPENSEARCH_INDEX` | `hk-iphone-listings` | OpenSearch 索引 |
| `OBJECT_STORE_BACKEND` | `local` | `local` 或 `s3` |
| `OBJECT_STORE_SSE` | `AES256` | S3 服务端加密，本地 MinIO 可留空 |
| `RAW_CAPTURE_RETENTION_DAYS` | `30` | 原始快照短期保留天数 |
| `LISTING_STALE_HOURS` | `36` | 超过该时间未再观测则标记逾时 |
| `PAYMENT_PROVIDER` | `mock` | 开发使用 `mock`，生产必须改为真实持牌 PSP 适配器 |
| `PAYMENT_API_KEY` | 空 | 真实 PSP API 凭证，Stripe 适配器使用 |
| `PAYMENT_WEBHOOK_SECRET` | 开发默认值 | PSP 回调签名密钥，生产必须使用独立强密钥 |
| `PAYMENT_RETURN_URL` | 买家订单页 | 付款完成后的 HTTPS 返回地址 |
| `PAYMENT_API_BASE_URL` | `https://api.stripe.com` | PSP API 基础地址 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | 配置后启用 FastAPI OTel 链路 |

完整示例见 `.env.example` 和 `web/.env.example`。

## 数据链路

标准流程：

1. Celery Beat 按香港时间创建每日采集任务。
2. 每个来源独立获得任务、浏览器槽和重试次数。
3. Collector 输出原始字段，平台保存受控原始快照。
4. 标准化层统一机型、容量、成色、状态、货币和地点。
5. 同一来源使用稳定来源键和观测键幂等写入。
6. 跨来源聚类只建立疑似重复关系，不覆盖原始商品。
7. PostgreSQL 提交后更新 OpenSearch 投影。
8. 估值、机会评分、降价与提醒服务读取统一主数据。
9. 维护任务标记逾时商品、清理过期快照并刷新统计。

香港本地规则：

- 统计币种固定为 `HKD`，同时保留原币价格和汇率日期。
- 系统时区固定为 `Asia/Hong_Kong`。
- 地点映射到香港 18 区和主要港铁站。
- 搜索支持繁体中文、英文和常见机型别名。
- 公众响应不包含原始 HTML、内部元数据或非必要卖家个人信息。

## API

公众接口：

```text
GET /healthz
POST /v1/auth/register
POST /v1/auth/login
GET  /v1/auth/me
POST /v1/auth/logout
GET /v1/listings
GET /v1/listings/{id}
GET /v1/listings/{id}/history
GET /v1/market/summary
GET /v1/valuations
GET /v1/opportunities
GET /v1/sources
GET /v1/meta
GET /v1/store/listings
GET /v1/store/listings/{id_or_slug}
POST /v1/store/orders
GET  /v1/orders
GET  /v1/orders/{order_id}
POST /v1/orders/{order_id}/cancel
POST /v1/orders/{order_id}/payment-intent
POST /v1/orders/{order_id}/confirm-receipt
GET  /v1/payments/mock/checkout/{reference}
POST /v1/payments/{provider}/webhook
```

行情列表支持机型、容量、价格、地区、来源、状态、更新时间和游标分页；平台商店支持机型、
容量、成色、价格和分页。公开商品响应不包含成本、内部库存主键或卖家联系方式。建立订单
必须提供 `Idempotency-Key`；付款回调必须通过 PSP 签名校验，并按 PSP 事件编号去重。

内部接口：

```text
GET  /internal/v1/users
POST /internal/v1/users
GET  /internal/v1/merchants
POST /internal/v1/merchants
GET  /internal/v1/inventory
POST /internal/v1/inventory
GET  /internal/v1/seller-listings
POST /internal/v1/seller-listings
POST /internal/v1/seller-listings/quick
POST /internal/v1/seller-listings/{listing_id}/publish
GET  /internal/v1/orders
POST /internal/v1/orders/{order_id}/fulfill
POST /internal/v1/orders/{order_id}/refund
POST /internal/v1/orders/{order_id}/restock
GET  /internal/v1/ledger
GET  /internal/v1/sources
GET  /internal/v1/runs
GET  /internal/v1/dead-letters
GET  /internal/v1/audit
GET  /internal/v1/raw-captures
POST /internal/v1/sources/{source_key}/collect
POST /internal/v1/clusters/rebuild
POST /internal/v1/maintenance/run
```

内部接口支持登录会话、`X-Platform-Key` 或 OIDC Bearer Token。角色分为 `admin`、
`operator`、`analyst`、`merchant` 和 `buyer`；其中只有前三者可访问内部接口。
`analyst` 只读，`operator` 可管理商家、库存和销售页，`admin` 可额外管理内部用户。

### 订单与支付运行

开发环境默认配置：

```text
PAYMENT_PROVIDER=mock
PAYMENT_WEBHOOK_SECRET=development-payment-webhook-secret
PAYMENT_RETURN_URL=http://127.0.0.1:3000/account/orders
```

下单流程为：买家提交 `Idempotency-Key` 建立订单，库存和销售页原子进入 `reserved`；买家
建立付款请求后跳转到 PSP 结账页；签名回调成功后订单进入 `paid` 并写入付款分录；运营人员
依次标记 `processing`、`shipped`；买家确认收貨后进入 `completed` 并建立商家结算分录；
运营退款成功后写入逆向退款分录；退货签收后由运营将退款订单的库存归位并重新上架。重复下单、
重复回调、重复退款和重复库存归位请求均按幂等处理。

mock PSP 只用于开发和自动测试，`/v1/payments/mock/checkout/{reference}` 会直接完成付款。
生产配置会拒绝 `PAYMENT_PROVIDER=mock`。生产接入真实 PSP 前，需要完成持牌主体及资金流
协议确认、商户号配置、Webhook 公网 URL、密钥轮换、退款和拒付沙箱验收，以及财务对账。
仓库中的 Stripe 适配器契约测试不能替代真实 PSP 沙箱和上线验收。

## 命令行

```text
iphone-platform migrate
iphone-platform seed
iphone-platform create-admin --email admin@example.com --name "Platform Admin"
iphone-platform collect-source <source_key>
iphone-platform collect-all
iphone-platform import-legacy [legacy_path]
iphone-platform refresh-valuations
iphone-platform serve
iphone-platform worker
iphone-platform beat
```

旧版采集和本地看板命令仍保留：

```powershell
python -m iphone_market collect --headed
python -m iphone_market dashboard --port 8765 --open
python -m iphone_market valuation --model "iPhone 17 Pro" --storage 256GB
```

## 测试与验收

后端：

```powershell
python -m pytest
python -m alembic upgrade head
iphone-platform --help
```

前端：

```powershell
cd web
npm run typecheck
npm run build
```

关键验收范围：

- 每个来源都通过适配器契约测试。
- 重复采集相同商品不产生重复主记录。
- 单来源失败可定位、重试和重新排队。
- 历史价格、状态和降幅计算正确。
- 搜索筛选、繁中别名和游标分页正确。
- 估值版本可回归，机会评分可解释。
- 公众响应完成脱敏，内部接口有权限和审计。
- 买家会话、公开注册开关、过期会话和登出行为正确。
- 商家、库存、草稿、发布和未发布商品 404 流程正确。
- 公开商店不包含成本等内部字段。
- 下单幂等、库存防重复售卖、订单归属和取消释放库存正确。
- 付款回调签名校验、事件去重、付款状态和账本分录一致。
- 履约状态仅允许从付款后进入备货和发货，买家确认收貨后建立结算。
- 退款使用幂等键、生成 PSP 退款引用，并写入可核对的逆向总账分录。
- 生产环境拒绝 mock PSP，真实 PSP 上线前完成沙箱、退款、拒付和对账验收。
- PostgreSQL 备份恢复通过演练。
- 浏览器并发和采集负载符合来源约束。

## 生产部署

默认建议部署在香港区域，例如 AWS `ap-east-1`：

- ECS Fargate 或 EKS：API、Worker、Beat，共用本仓库后端镜像。
- RDS PostgreSQL：主数据、历史、备份和多可用区。
- ElastiCache Redis：Broker、结果和浏览器并发槽。
- Amazon OpenSearch Service：搜索投影，可选。
- S3：受控原始快照，开启生命周期和默认加密。
- ALB + WAF：API 和 Web 入口。
- Secrets Manager：数据库、OIDC、S3 和内部 API Key。
- CloudWatch / OpenTelemetry Collector：日志、指标、链路和告警。

生产配置要点：

```text
APP_ENV=production
AUTO_CREATE_SCHEMA=false
AUTH_MODE=oidc
OBJECT_STORE_BACKEND=s3
OBJECT_STORE_SSE=AES256
OPENSEARCH_URL=https://...
PAYMENT_PROVIDER=stripe
PAYMENT_API_KEY=由密钥管理系统注入
PAYMENT_WEBHOOK_SECRET=由密钥管理系统注入
PAYMENT_RETURN_URL=https://www.example.com/account/orders
```

部署流程应始终先执行 `iphone-platform migrate`，成功后再滚动更新 API 和 Worker。Beat 只运行一个副本。Worker 按队列和浏览器并发独立扩缩容，推荐将 `collection` 与 `maintenance` 分成不同 Worker 池。

上线前必须用真实 PSP 沙箱或生产测试账户完成付款、重复 Webhook、已支付回调乱序、退款成功、
退款失败、拒付和对账测试。当前仓库没有真实 Stripe 凭证，也没有针对真实账户执行过这些
验收；代码通过适配器契约测试不等于支付通道已经获批或可用。

## 交易与支付边界

- 首版采用 B2C：平台自营和已审核商家可以在平台销售商品。
- 平台持有订单、支付状态、退款状态、账本和商家结算状态。
- 实际持卡人资金由香港持牌 PSP 代收，平台只接收支付回调与结算结果，不保存卡号。
- 订单、退款、拒付和商家结算必须使用幂等键，并保留不可变审计记录。
- 当前开发链路已经支持下单、mock PSP 代收、确认收貨、退款、商家结算和复式账本。
- 生产上线前必须换成已签约的香港持牌 PSP，并完成真实账户沙箱与资金对账验收。
- C2C 阶段才开放个人卖家自主发布、双方争议和更细的卖家风控。

## 数据合规

- 只采集公开数据或已授权接口，遵守来源条款、验证码规则和 `robots` 约束。
- 原始页面快照仅用于内部诊断，短期保留并支持删除。
- 个人数据遵循香港 PDPO，并遵循最小化、可追溯和可删除原则。
- 公众 API 不返回原始 HTML、内部聚类元数据或非必要卖家个人信息。
- 处理删除请求时，应删除主记录、历史快照、搜索投影和对象存储快照。
- 个人卖家自主发布、C2C 撮合和更多支付方式留给后续阶段，并需重新做隐私和合规评审。

## 当前阶段边界

默认按全港 10 万级活跃商品、100 万级历史快照设计。规模较小时可以缩减 PostgreSQL、OpenSearch 和 Worker 资源。

首版已完成：

- 香港首发、B2C 商家和平台自营商品管理。
- 买家注册登录、HttpOnly Cookie 会话和角色权限。
- 库存、验机资料、平台商品草稿、发布和公开商店。
- 运营台快速上架：只需商家、机型容量、成色和售价，系统自动补齐 SKU、标题和草稿发布。
- 幂等下单、库存预留、订单状态机和订单历史。
- PSP 付款请求、签名 Webhook、回调去重和付款状态。
- 运营备货、发货、买家确认收貨和商家结算。
- 运营退款、PSP 退款引用、退货后库存归位和复式账本冲销。
- mock PSP 全链路自动测试和 Stripe 适配器契约测试。

上线前仍需完成：

- 签约并验收真实香港持牌 PSP，接入生产密钥和公网 Webhook。
- 接入物流单号、争议、售后、拒付和对账运营流程。
- 商家结算打款、结算批次和财务导出。
- 监控告警、备份恢复演练、安全测试和真实设备浏览器验收。

首版暂不包含：

- C2C 个人卖家自主发布和买卖双方直接撮合。
- 商家自助注册、商家后台和自动结算门户。
- 原生 iOS 或 Android 应用。

当前改造顺序：

1. 已完成商店、账户、商家、库存和 B2C 订单闭环。
2. 已完成 mock PSP 全链路和复式账本，并增加 Stripe 适配器契约测试。
3. 下一步签约持牌 PSP，完成真实沙箱验收后切换生产支付。
4. 接入物流、争议、售后、拒付、结算打款和对账运营。
5. 完成安全、备份、监控和容量演练后，再评审 C2C 与个人卖家。
