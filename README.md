# x-trends-digest

抓取 X 热点 → 生成摘要 → 定时推送。三块功能都是可替换的接口，目前只有 mock 实现，本地开发和测试不会访问 X 或任何外部接口。

## 结构

```
src/x_trends_digest/
  models.py           数据结构：Trend / Post / Snapshot / Digest
  interfaces.py       三个接口：Fetcher / Summarizer / Publisher
  fetchers/mock.py    固定的示例趋势和帖子
  summarizers/
    mock.py           透传：把按 chat 格式构造的 user 消息原样放进摘要
    openai_compatible.py  OpenAI 兼容 chat completions 真实实现（urllib，需 key）
  publishers/
    file.py           写 markdown 文件到 XTD_OUTPUT_DIR
    stdout.py         打印到标准输出
  config.py           从环境变量（及可选 .env）读取配置
  factory.py          按配置名选择实现，未知名称直接报错
  pipeline.py         run_once：抓取 → 摘要 → 推送
  scheduler.py        内置 5 段 cron 调度（仅标准库）
  cli.py              命令行：run-once / schedule
tests/                unittest 测试，全部 mock
deploy/               systemd 与 cron 示例
```

摘要接口按 chat completions 消息格式设计：`build_messages` 生成 `[{"role": "system"...}, {"role": "user"...}]`，`complete(messages)` 返回文本。

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
- 错误面向用户给出一行说明：401/403 认证失败，429 限流（有 `Retry-After` 时会提示），5xx 服务端错误，超时，无法连接，返回格式不符。`run-once` 遇到这些错误退出码为 1。
- 密钥不会出现在日志、异常信息或 `repr(config)` 中；其他 4xx 的响应片段若含 key 会被替换为 `***`。
- `base_url` 必须是 https（仅 localhost 允许 http），避免 key 明文传输；不跟随重定向，避免把 Authorization 头转发到别处。
- 没有自动重试：429 和 5xx 只报错。`schedule` 模式下单次失败会打印错误并等下一次触发。

测试全部用注入的假 opener，不产生真实网络请求。

## 运行

需要 Python 3.9+，无第三方依赖。

```bash
cp .env.example .env          # 可选，默认值已是 mock
export PYTHONPATH=src

python3 -m x_trends_digest run-once                 # 只跑一次，默认写入 out/
XTD_PUBLISHER=stdout python3 -m x_trends_digest run-once   # 改为打印
python3 -m x_trends_digest schedule --cron "*/5 * * * *"   # 常驻调度
```

配置项（环境变量）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| XTD_FETCHER | mock | 目前只支持 mock |
| XTD_SUMMARIZER | mock | mock / openai / deepseek |
| XTD_PUBLISHER | file | file 或 stdout |
| XTD_CRON | 0 9 * * * | 5 段 cron，本地时区 |
| XTD_OUTPUT_DIR | out | file 推送目录 |
| DEEPSEEK_API_KEY | 空 | 使用 openai/deepseek 时必填 |
| DEEPSEEK_BASE_URL | https://api.deepseek.com | 必须 https |
| DEEPSEEK_MODEL | deepseek-chat | |
| DEEPSEEK_TIMEOUT | 30 | 请求超时（秒） |

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

- 真实 X 抓取来源：需要决定用官方 API、第三方数据服务还是其他合规来源，并实现 `Fetcher`，处理限流、鉴权和失败重试。
- 真实模型：代码已实现，但没有用真实 key 联调过（只有 mock HTTP 测试）。上线前需用真实 key 验证一次，确认模型名、base_url 和返回格式，并按需补重试。
- 真实推送渠道：实现 `Publisher`（邮件、Telegram、飞书、钉钉等），并处理失败重试与去重。
- 密钥管理：生产环境的密钥只放在服务器的 `.env` 或密钥管理系统中，不进入仓库。
- 监控告警：任务失败目前只打印日志，需要接入告警。
