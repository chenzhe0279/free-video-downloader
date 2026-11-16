# ClipNest 会员与 Stripe 验收

套餐使用人民币一次性价格。月卡 ¥19 / 30 天，年卡 ¥149 / 365 天。网站通过 Stripe Checkout 收款，收到并核验支付后开通会员。会员每天可新建 20 次 AI 视频总结，缓存命中免扣额度。退款与拒付在 Stripe 后台操作。

环境变量示例见 [backend/.env.example](../backend/.env.example)。`backend/.env` 保存本机凭据，仓库通过 `.gitignore` 显式排除该文件。Stripe API 密钥与 Webhook 签名密钥分别配置。托管收银台由后端创建，公钥可选填在 `VDS_STRIPE_PUBLISHABLE_KEY`，页面会直接跳转至 Stripe。

## 第一步：准备本机 MySQL 和依赖

使用 MySQL 8.0。开启 MySQL 服务后，用 MySQL Workbench 或 MySQL 命令行连接**你自己的实例**。用有建库和建用户权限的管理员执行以下测试库示例，将密码占位符换成独立强密码。已有同名库或用户时，先在 Workbench 中核对用途和授权。

```sql
CREATE DATABASE clipnest_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;
CREATE USER 'clipnest_test'@'localhost' IDENTIFIED BY '<替换为本机测试密码>';
GRANT ALL PRIVILEGES ON clipnest_test.* TO 'clipnest_test'@'localhost';
```

从仓库根目录打开 PowerShell。联网时完成一次依赖准备，`uv` 和 npm 会缓存下载内容。首次安装到了离线机器时，先把匹配 Python 3.12、系统架构和锁文件的依赖包与浏览器安装包带到该机器。

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ../backend
uv sync --locked
```

用编辑器打开 `backend/.env`。如果该文件不存在，先复制 `backend/.env.example`。保留已有 DeepSeek 配置，按后面的验收环境补充会员配置。数据库 URL 中的密码若含 `@`、`#` 或 `%` 等字符，需要 URL 编码。

## 方案 A：完全断网验收

在 `backend/.env` 填入下列本地设置。以下工作可以用已经安装好的依赖在断网时完成。

```dotenv
VDS_MEMBERSHIP_DB_URL=mysql+pymysql://clipnest_test:<URL编码后的密码>@127.0.0.1:3306/clipnest_test
VDS_MEMBERSHIP_ORIGIN=http://127.0.0.1:8000
VDS_MEMBERSHIP_CHECKOUT_ENABLED=true
VDS_STRIPE_MODE=mock
VDS_STRIPE_WEBHOOK_SECRET=whsec_clipnest_local_fixture
VDS_SMTP_HOST=127.0.0.1
VDS_SMTP_PORT=8103
VDS_SMTP_SECURITY=plain
VDS_SMTP_FROM=clipnest@example.com
```

在 `backend` 中执行迁移。然后开两个 PowerShell 窗口，在同一目录运行两个服务。

```powershell
uv run --offline --locked alembic upgrade head

# 窗口 1：模拟 Stripe 和测试邮箱
uv run --offline --locked uvicorn tests.membership_fixture:app --host 127.0.0.1 --port 8102

# 窗口 2：站点和 Webhook
uv run --offline --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

1. 打开 [本地站点](http://127.0.0.1:8000/)，点 **登录 → 注册账号**，输入任意测试邮箱（例如 `you@example.com`）和至少 12 字符的测试密码。
2. 打开 [本地测试邮箱](http://127.0.0.1:8102/inbox)，点验证链接，再输入注册密码。验证后登录。忘记密码可通过同一邮箱收取重置链接。
3. 点 **开通月卡** 或 **开通年卡**。本地模拟收银台有 **模拟付款成功**、**模拟银行卡拒付** 和 **返回网站**。拒绝或返回后可在「我的会员」继续同一笔订单或取消。
4. 模拟付款成功后，返回「我的会员」。最多等一个后台处理周期（约 15 秒）和一次页面轮询。确认订单显示「已付款」，有效期正确，今日剩余 20 次。
5. 退款、争议处理、真实验签、并发与额度由自动测试覆盖。测试会使用固定的视频解析结果和 AI 总结任务替身，可断网运行。要在浏览器使用真实平台视频，需要相应的平台网络和有效的 AI 服务配置。

需要使用 Vite 查看实时修改时，把 `VDS_MEMBERSHIP_ORIGIN` 设置为 `http://127.0.0.1:5173`，重启后端和测试邮箱，再在 `frontend` 运行 `npm run dev -- --host 127.0.0.1`。浏览器统一打开 [Vite 本地站点](http://127.0.0.1:5173/)，Webhook 仍由 8000 端口接收。

运行自动验收时先停止上面的本地站点和模拟服务。用一个 PowerShell 窗口进入 `backend`，将测试数据库 URL 设为刚才使用的 `clipnest_test` 连接地址。

```powershell
$env:CLIPNEST_MEMBERSHIP_TEST_DB_URL = '<与 VDS_MEMBERSHIP_DB_URL 相同的测试库 URL>'
uv run --offline --locked python -m unittest discover -s tests
```

可选的浏览器自动化使用仓库现有的 Chrome DevTools 连接方式。重启本地站点和模拟服务，在 `backend` 打开第三个窗口运行以下命令。Chrome 安装在其他目录时，修改可执行文件路径。

```powershell
$clipnestProfile = Join-Path $env:TEMP ('clipnest-chrome-' + [guid]::NewGuid())
Start-Process 'C:/Program Files/Google/Chrome/Application/chrome.exe' -WindowStyle Hidden -ArgumentList @(
  '--headless=new', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222',
  "--user-data-dir=`"$clipnestProfile`""
)
uv run --offline --locked python -m tests.membership_browser_e2e
```

## 方案 B：网站在本机，联网使用 Stripe Sandbox

Stripe Dashboard、托管收银台、API 和 CLI 都需要能访问 Stripe。使用 CLI 做本地转发时，网站继续监听本机，无需买域名或开公网端口。[Stripe CLI 本地转发](https://docs.stripe.com/cli/listen) · [Stripe 官方沙盒测试](https://docs.stripe.com/testing)

1. 登录 [Stripe Sandbox](https://dashboard.stripe.com/sandboxes)，选你的测试环境。在产品目录添加“ClipNest 月卡”和“ClipNest 年卡”，分别创建 **One-off / 一次性** 的 CNY ¥19.00 和 ¥149.00 价格。复制各自的 `price_...`。
2. 在同一 Sandbox 的 API 密钥页复制 `sk_test_...`。将 `VDS_STRIPE_MODE` 改成 `sandbox`，把该密钥和两个 Price ID 填入 `VDS_STRIPE_SECRET_KEY`、`VDS_STRIPE_MONTH_PRICE_ID`、`VDS_STRIPE_YEAR_PRICE_ID`。使用独立的沙盒 MySQL 库并运行迁移。配置可用的 SMTP；可以用自己的本地 SMTP 测试工具，或使用邮件服务商的 SMTP。
3. 安装 Stripe CLI 后在单独窗口执行下面的命令。浏览器配对时选择刚才创建价格的同一个测试环境。把监听命令输出的 `whsec_...` 设置为 `VDS_STRIPE_WEBHOOK_SECRET`，然后启动或重启网站。CLI 窗口保持运行。

```powershell
stripe login
stripe listen --events checkout.session.completed,checkout.session.expired,refund.created,refund.updated,refund.failed,charge.refunded,charge.dispute.created,charge.dispute.updated,charge.dispute.closed --forward-to http://127.0.0.1:8000/api/payment/webhook
```

`POST /api/payment/webhook` 与 `POST /api/billing/stripe/webhook` 共用验签与事件处理。当前 CLI 转发命令需指定 `--events` 或 `--all-snapshot`。在本机已设置 `STRIPE_API_KEY` 时也可用该环境变量认证，避免把密钥写入命令行参数。需要预先读取签名密钥时，可为监听命令加 `--print-secret`，CLI 会在输出密钥后退出。

4. 打开站点并验证邮箱，点击购买实际套餐。使用 `4242 4242 4242 4242` 测试成功，或使用 `4000 0000 0000 0002` 测试拒绝，有效期填将来的月份，CVC 填任意三位数字。支付后核对网站订单与 Stripe Dashboard 的金额、币种和支付 ID。在沙盒 Dashboard 测试部分退款与全额退款，对比会员状态。两档都各测一次，用独立账号或先全额退款。[Stripe 测试卡](https://docs.stripe.com/testing#cards)

## 上线与对账

- 上线前在已激活的 Stripe 商户、独立生产数据库和 HTTPS 域名准备同样的正式价格。实测生产 SMTP 能发出验证和重置邮件。在 Stripe Workbench 注册同一路径的生产 Webhook，选择上面列出的 **Snapshot** 事件，配置该正式端点自己的签名密钥。把 `VDS_STRIPE_MODE` 设为 `live`，分别配置正式密钥、Price ID 和 HTTPS Origin。验收后开启 `VDS_MEMBERSHIP_CHECKOUT_ENABLED=true`。暂停新收款时改回 `false`，保留 Stripe 环境和 Webhook 配置供已发生交易继续处理。
- 日志中的「事件待重试」「订单对账失败」「需人工对账」是排查入口。按订单号运行 `uv run python -m app.membership.reconcile <订单号>`。该命令读取 Stripe 的 Checkout Session 和支付结果，重新同步订单。超过 48 小时且 Stripe 中确实找不到对应 Checkout Session 时，经 Dashboard 核查后可使用 `--close-if-missing` 关闭待人工对账的订单。历史付款与会员有效期保留在订单中，线上回滚时保留数据库与 Webhook 接收路径。
