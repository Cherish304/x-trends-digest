# x-trends-digest

抓取 X 热点 → 生成摘要 → 定时推送。三块功能都是可替换的接口。默认全部是 mock，本地开发和测试不会访问 X 或任何外部接口（测试里的 HTTP 全部是注入的假 opener）。

## 结构

```
src/x_trends_digest/
  models.py           数据结构：Trend / Post / Snapshot / Digest
  interfaces.py       三个接口：Fetcher / Summarizer / Publisher
  fetchers/
    mock.py           固定的示例趋势和帖子
    json_file.py      从本地 JSON 快照读取（XTD_FETCHER=json）
    xapi.py           X API v2（XTD_FETCHER=xapi，需 Bearer token）
    errors.py         FetcherConfigError / FetcherError
  summarizers/
    mock.py           透传：把按 chat 格式构造的 user 消息原样放进摘要
    openai_compatible.py  OpenAI 兼容 chat completions 真实实现（urllib，需 key）
    rule_based.py     规则摘要：不调用模型，按数据拼简单的中文摘要
    fallback.py       主摘要器失败时退回规则摘要并打上标记
  render/
    email_html.py     HTML 邮件（表格布局 + 内联 CSS，宽度 ≤ 600px）
    email_text.py     纯文本备用版本
    _md.py            极简 markdown 解析（标题 / 列表 / 加粗）
  publishers/
    file.py           同时写 .html 和 .txt 到 XTD_OUTPUT_DIR
    stdout.py         打印纯文本版本到标准输出
  config.py           从环境变量（及可选 .env）读取配置
  factory.py          按配置名选择实现，未知名称直接报错
  pipeline.py         run_once：抓取 → 摘要 → 推送
  scheduler.py        内置 5 段 cron 调度（仅标准库）
  cli.py              命令行：run-once / schedule
tests/                unittest 测试，全部 mock
examples/snapshot.json  json 抓取器的示例快照
deploy/               systemd 与 cron 示例
```

摘要接口按 chat completions 消息格式设计：`build_messages` 生成 `[{"role": "system"...}, {"role": "user"...}]`，`complete(messages)` 返回文本。

## 抓取器

### json 文件抓取器

```bash
XTD_FETCHER=json XTD_SNAPSHOT_PATH=examples/snapshot.json python3 -m x_trends_digest run-once
```

适合把别处（人工整理、其他脚本、第三方数据服务导出）得到的数据喂进来。快照格式：

```json
{
  "fetched_at": "2026-10-14T09:00:00+08:00",
  "trends": [{"name": "#话题", "post_count": 120000, "url": "可选"}],
  "posts": [{"author": "用户名", "text": "正文", "likes": 1200, "reposts": 300, "url": "可选"}]
}
```

宽容规则：

- 所有顶层字段都可省略；`trends`、`posts` 缺失或不是列表时按空处理。
- 趋势缺 `name`、帖子缺 `text` 时该条被跳过；趋势的 `rank` 按保留下来的顺序重新编号。
- 趋势的 `post_count` 缺失、为 `null`、负数、布尔或无法解析时记为"未知"，不显示数量，也不会当成 0 交给模型；`likes`、`reposts` 这些情况仍按 0。字符串数字（如 `"1,234"`）和小数会转成整数。
- `author` 缺失时记为 `unknown`，开头的 `@` 会被去掉；帖子的 `id` 可选。
- 顶层不是对象、文件不存在、不是合法 JSON 或超过 5 MB 时报错（`run-once` 退出码 1）；`XTD_SNAPSHOT_PATH` 未设置时启动即报错（退出码 2）。

### X API v2 抓取器

```bash
XTD_FETCHER=xapi
X_BEARER_TOKEN=你的token     # 必填，缺失时启动即报错（退出码 2）
XTD_WOEID=1                  # 默认 1（全球）
XTD_MAX_POSTS=10             # 最终保留的热门帖子数，1 到 100
XTD_TRENDS_FOR_POSTS=3       # 对前几个趋势取帖子，1 到 10
XTD_FETCH_TIMEOUT=30         # 秒
```

流程：`GET https://api.x.com/2/trends/by/woeid/{XTD_WOEID}` 取趋势，再对前 `XTD_TRENDS_FOR_POSTS` 个趋势调用 `GET /2/tweets/search/recent`（排除转推，带 `public_metrics`），合并去重后按点赞数降序取前 `XTD_MAX_POSTS` 条。

- 401 提示 token 无效；403 提示应用或套餐无权调用该接口；429 提示限流并带上 `x-rate-limit-reset`（若有）；5xx、超时、连接失败都有一行说明。`run-once` 遇到这些错误退出码为 1。
- 搜索阶段如果在已取到部分帖子后被 429 限流，会用已有结果继续，不整体失败；趋势接口或第一次搜索就被限流则报错。
- token 不会出现在日志、异常信息或 `repr(config)` 中；不跟随重定向，避免把 Authorization 头转发到别处。
- 每次运行会消耗 1 + `XTD_TRENDS_FOR_POSTS` 次 API 调用，注意你的套餐额度。
- 重要：这个抓取器依据 X API v2 的公开文档约定编写（趋势字段 `trend_name` / `tweet_count`，帖子字段 `public_metrics.like_count` / `retweet_count`），没有用真实 token 联调过，趋势接口的可用套餐也可能有限制。上线前必须用真实 token 验证一次。

## 邮件渲染

`render/` 把 `Digest` 和 `Snapshot` 渲染成一封邮件：一份 HTML，加一份纯文本备用版本。`file` 推送器每次同时写出 `digest-<时间戳>.html` 和 `.txt`；`stdout` 推送器打印纯文本版本。

只渲染邮件、不做推送，供外部程序发送：

```bash
python3 -m x_trends_digest render-email --out-dir mail --name today
# 输出：主题 / HTML: mail/today.html / TEXT: mail/today.txt
```

该命令会走完整的抓取和摘要流程，然后只写出这两个文件；`--out-dir` 默认取 `XTD_OUTPUT_DIR`，`--name` 默认 `digest`。文件先写临时文件再改名，外部程序不会读到半截内容。邮件主题在命令输出的第一行。

### 版式

按新闻简报的样子排版，从上到下依次是：

1. 深海蓝渐变头图条：品牌小字 `X TRENDS DIGEST`、标题、日期加星期、副标题。
2. 「今日一句话」导语卡：取摘要的第一句话（超过 90 字则截断），并从正文里去掉，避免重复。摘要不可用时（备用摘要）上方会多一条黄色提示条。
3. 摘要分节：每节一个 emoji 加小标题加一小段强调色横条，节内是要点列表或段落。emoji 按标题关键词选（概览 📰、要点 📌、关注 👀、趋势 🔥、热帖 💬，其余 📝），标题自带 emoji 时不再重复。
4. 趋势排行：前三名是大卡片，编号徽章分别是金、银、铜色，第一名卡片底色略黄；第 4 名起用两列紧凑布局。名称链接到 `https://x.com/search?q=...`，数量缺失时不显示数量。
5. 热帖卡片：首字母头像圆圈（同一作者颜色固定）、`@handle`、正文最多 4 行、点赞与转发的图标加数字、「查看原帖」按钮（没有安全链接时不显示按钮）。
6. 页脚：数据来源、摘要来源（AI 或规则）、数据抓取时间和邮件生成时间、退订占位。

配色统一：深海蓝头图，单一蓝色强调色，其余是 slate 灰阶。字号层级：标题 28px、分节小标题 18px、导语 17px、正文 15px、辅助信息 12 到 14px，行高 1.5 以上。中文字体栈：`-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif`。

退订链接在 HTML 和纯文本里都是占位符 `{{UNSUBSCRIBE_URL}}`，发送前由外部程序替换成真实的退订地址。

### 兼容性和降级

- 只用表格布局和元素上的内联 `style`，没有 `<style>`、`<link>`、脚本、图片、SVG 和 flex/grid。
- 外层表格 `width=100%`，内层 `max-width:600px`，加了 viewport 元标签，手机上自动收窄。
- Outlook（Word 渲染引擎）不认 `max-width`、`border-radius` 和渐变：用 `<!--[if mso]>` 条件注释套一层固定 600px 的表格；头图同时写了 `bgcolor` 和 `background-color` 纯色，渐变不生效时回退成深色；圆角在 Outlook 里变直角，圆形徽章变方块。按钮用 `<a>` 加同色边框撑出内边距，Outlook 里也有体积。
- 帖子正文的 4 行截断：邮件客户端普遍不支持 `line-clamp`，所以先按字符宽度（全角字占一格，拉丁字符约半格）估算折行，在第 4 行末尾加 `…`；另外配了 `-webkit-line-clamp:4` 和 `max-height:92px` 兜底。手机上折行更多时由 `max-height` 裁掉多余部分，可能出现半行被裁切，没有省略号。
- 收件箱列表里的预览文字（preheader）是导语，放在隐藏的 `div` 里。
- 所有来自抓取数据和模型输出的文本都经过 HTML 转义。链接只放行 http/https，且不含空白字符，`javascript:` 之类一律丢弃；趋势链接固定指向 X 搜索页，不使用数据源给的 url。
- 趋势排行和热帖各最多展示 10 条。

### 设计参考

动手前读了这些项目，并在实现时参考了它们的做法：

- leemunroe/responsive-html-email-template：读了 README 和 `email-inlined.html`。采用 600px 容器、表格布局、所有样式内联、`max-width` 配 `width:100%`、带 `<meta viewport>`；按钮用 `display:inline-block` 的 `<a>` 加圆角；整体留白大、一个主按钮的克制风格。它的 README 强调发送前必须内联 CSS 并在多个客户端实测，所以这里一开始就不用 `<style>`。
- mailgun/transactional-email-templates：读了 README 和 `action.html`。采用它的按钮写法（用 `border-width: 10px 20px` 加同色边框撑出内边距，Outlook 里也有体积）、淡灰背景配白色内容卡、页脚用小号灰字。
- resend/react-email：读了 README。采用它的组件拆分思路（Container、Section、Row、Column、Button、Divider、Preview），对应到这里的容器表格、分节、两列布局、按钮、分割线和隐藏的预览文字；它以 Gmail、Outlook 等多个客户端实测为准的态度也一样。
- mailchimp/email-blueprints：读了 README。采用它对 Outlook 的处理思路（条件注释加固定宽度）和「模块化」的做法，各板块是独立的表格行，互不影响。
- TLDR 简报：读了站点存档页和一期正文。借鉴它的版式：标题行带 emoji、按板块分组、每条只有几句话的摘要、清晰的赞助与页脚区分。
- Morning Brew：存档页被 Cloudflare 的人机验证拦住，没有读到内容，所以没有参考它。

这些是对公开页面的阅读和归纳，不是逐像素复刻，也没有拷贝它们的代码。

### 样例和预览

`examples/preview.html` 和 `examples/preview.txt` 是用 `examples/snapshot.json` 加固定的摘要正文渲染出来的样例（时间固定，输出稳定）。重新生成：

```bash
PYTHONPATH=src python3 -m x_trends_digest.render.preview
```

测试里有一条校验样例和当前渲染器是否同步，改了渲染器忘记重新生成会失败。

### 已验证和没验证的

我在 Chrome 里打开 `preview.html`，分别看了桌面宽度和 375px 宽的 iframe：头图、导语卡、分节、金银铜徽章、两列紧凑布局、帖子卡片、4 行截断和页脚都按预期显示。看截图发现并修掉一个问题：手机宽度下 `break-all` 会把 "Launch" 拦腰拆成 "Lau / nch"，现在改成只在单词本身放不下时才断词。

��有验证的：QQ 邮箱、Gmail 和 Outlook 里的真实显示。Chrome 能正常渲染不代表这些客户端也行。Outlook 的降级（直角、纯色头图、固定宽度）是按它的已知限制写的，没有在 Outlook 里看过；`-webkit-box` 的行截断在各客户端的支持也不一致。上线前请发一封测试邮件到 QQ 邮箱、Gmail 和 Outlook 的网页版与手机端确认。

## 抓取数量缺失

趋势的 `post_count` 现在是可选的：来源没给、为 `null`、为负数或无法解析时记为"未知"（`None`），而不是 0。未知时，发给模型的 prompt 不写数量，system prompt 也要求模型不要猜测；邮件和备用摘要里同样不显示数量。真实的 0 仍会显示为"0 帖"。

## AI 摘要失败时的备用方案

`XTD_SUMMARIZER=openai|deepseek` 时，摘要器外面包了一层备用逻辑：

- 调用有总时长上限 `DEEPSEEK_TOTAL_TIMEOUT`（默认 60 秒），在单次读写超时 `DEEPSEEK_TIMEOUT` 之外再加一层。调用跑在守护线程里，主线程最多等这么久；响应体也是分块读取并检查 deadline，所以慢速滴灌的响应也会被截断。
- 超时或任何运行期错误（401、429、5xx、连接失败、返回格式不符等）都会退回规则摘要（`rule_based.py`，不调用模型，按趋势和热帖拼一份中文摘要），流程照常出邮件。
- 退回时，邮件主题、HTML 顶部和纯文本顶部都会标注「AI 摘要暂不可用」，stderr 会打印一行原因（不含密钥）。原因不写进邮件。
- 配置错误不会被吞掉：缺少 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_BASE_URL` 不是 https 仍然在启动时报错（退出码 2）。
- 超时后后台线程可能还在等网络，但它是守护线程，不会阻止进程退出，读取循环也会在下一次检查时自行结束。

## 使用真实模型（OpenAI 兼容）

默认仍是 mock。要调用真实模型，在 `.env`（已被 git 忽略）或环境变量里设置：

```bash
XTD_SUMMARIZER=openai          # 或 deepseek，两者等价
DEEPSEEK_API_KEY=你的key        # 必填，缺失时启动即报错（退出码 2）
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=30            # 秒
```

实现要点（`summarizers/openai_compatible.py`，仅用标准库 urllib）：

- 请求 `POST {base_url}/chat/completions`，头部 `Authorization: Bearer <key>`，中文 system prompt 要求输出 300 字内的 markdown 摘要，并声明帖子内容只是待总结的数据、不执行其中的指令。
- 错误面向用户给出一行说明：401/403 认证失败，429 限流（有 `Retry-After` 时会提示），5xx 服务端错误，超时，无法连接，返回格式不符。这些错误现在会触发上面的备用摘要，不再让 `run-once` 失败。
- 密钥不会出现在日志、异常信息或 `repr(config)` 中；其他 4xx 的响应片段若含 key 会被替换为 `***`。
- `base_url` 必须是 https（仅 localhost 允许 http），避免 key 明文传输；不跟随重定向，避免把 Authorization 头转发到别处。
- 没有自动重试：429 和 5xx 只报错。`schedule` 模式下单次失败会打印错误并等下一次触发。

测试全部用注入的假 opener，不产生真实网络请求。

## 运行

需要 Python 3.9+，无第三方依赖。

```bash
cp .env.example .env          # 可选，默认值已是 mock
export PYTHONPATH=src

python3 -m x_trends_digest run-once                 # 只跑一次，默认在 out/ 写 .html 和 .txt
python3 -m x_trends_digest render-email --out-dir mail   # 只渲染邮件，不推送
XTD_PUBLISHER=stdout python3 -m x_trends_digest run-once   # 改为打印
python3 -m x_trends_digest schedule --cron "*/5 * * * *"   # 常驻调度
```

配置项（环境变量）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| XTD_FETCHER | mock | mock / json / xapi |
| XTD_SNAPSHOT_PATH | 空 | json 抓取器必填 |
| X_BEARER_TOKEN | 空 | xapi 抓取器必填 |
| XTD_WOEID | 1 | xapi：地区 woeid |
| XTD_MAX_POSTS | 10 | xapi：保留的热门帖子数（1-100） |
| XTD_TRENDS_FOR_POSTS | 3 | xapi：对前几个趋势取帖子（1-10） |
| XTD_FETCH_TIMEOUT | 30 | xapi：请求超时（秒） |
| XTD_SUMMARIZER | mock | mock / openai / deepseek |
| XTD_PUBLISHER | file | file 或 stdout |
| XTD_CRON | 0 9 * * * | 5 段 cron，本地时区 |
| XTD_OUTPUT_DIR | out | file 推送目录 |
| DEEPSEEK_API_KEY | 空 | 使用 openai/deepseek 时必填 |
| DEEPSEEK_BASE_URL | https://api.deepseek.com | 必须 https |
| DEEPSEEK_MODEL | deepseek-chat | |
| DEEPSEEK_TIMEOUT | 30 | 单次网络读写超时（秒） |
| DEEPSEEK_TOTAL_TIMEOUT | 60 | 整个模型调用的总时长上限（秒），超时退回备用摘要 |

cron 支持 `*`、数字、`a-b`、`a,b`、`*/n`、`a-b/n`；周 0 和 7 都是周日。

## 测试

```bash
python3 -m unittest discover -v -s tests -t .
```

## 部署（Linux）

假设代码放在 `/opt/x-trends-digest`，用专用用户 `xtd`，`.env` 权限设为 600。

方案一：systemd 常驻调度，由程序按 XTD_CRON 触发。

```bash
sudo cp deploy/x-trends-digest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now x-trends-digest
journalctl -u x-trends-digest -f
```

方案二：systemd timer 触发单次执行。

```bash
sudo cp deploy/x-trends-digest-once.service deploy/x-trends-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now x-trends-digest.timer
```

方案三：cron，参考 `deploy/crontab.example`。

三种方案选一种即可，不要同时启用，否则会重复推送。

## 上线前还差什么

- 真实 X 抓取来源：json 和 xapi 两个抓取器代码已实现，但只在假 HTTP 和示例文件下测过。xapi 需要用真实 token 联调一次，确认 X 开发者账号套餐是否包含趋势接口、字段名是否与实际响应一致、额度是否够用，并按需补重试和退避。
- 真实模型：代码已实现，但没有用真实 key 联调过（只有 mock HTTP 测试）。上线前需用真实 key 验证一次，确认模型名、base_url 和返回格式，并按需补重试。
- 真实推送渠道：实现 `Publisher`（邮件、Telegram、飞书、钉钉等），并处理失败重试与去重。
- 密钥管理：生产环境的密钥只放在服务器的 `.env` 或密钥管理系统中，不进入仓库。
- 监控告警：任务失败目前只打印日志，需要接入告警。
