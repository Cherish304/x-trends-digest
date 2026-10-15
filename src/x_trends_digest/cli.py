"""命令行入口：run-once / schedule。"""

import argparse
import os
import sys
from typing import List, Optional

from .config import load_config, load_dotenv
from .factory import build_fetcher, build_publisher, build_summarizer
from .pipeline import build_digest, run_once
from .publishers.file import write_email_files
from .render import render_email
from .scheduler import CronSchedule, run_forever
from .fetchers import FetcherError
from .summarizers import SummarizerError


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="x-trends-digest")
    parser.add_argument("--env-file", default=".env", help="可选的 .env 路径")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once", help="只执行一次：抓取 -> 摘要 -> 推送")
    p_render = sub.add_parser(
        "render-email",
        help="只渲染邮件：抓取 -> 摘要 -> 写出一份 .html 和一份 .txt，不做推送，供外部发送",
    )
    p_render.add_argument("--out-dir", help="输出目录，默认 XTD_OUTPUT_DIR")
    p_render.add_argument("--name", default="digest", help="文件名前缀，默认 digest")
    p_sched = sub.add_parser("schedule", help="按 cron 表达式常驻调度")
    p_sched.add_argument("--cron", help="覆盖 XTD_CRON")
    args = parser.parse_args(argv)

    load_dotenv(args.env_file, os.environ)
    try:
        cfg = load_config()
        fetcher = build_fetcher(cfg)
        summarizer = build_summarizer(cfg)  # key 缺失在这里立即报错
        publisher = build_publisher(cfg)
    except ValueError as exc:
        print("配置错误: %s" % exc, file=sys.stderr)
        return 2

    def job() -> str:
        dest = run_once(fetcher, summarizer, publisher)
        print("已推送: %s" % dest, flush=True)
        return dest

    if args.command == "render-email":
        try:
            snapshot, digest = build_digest(fetcher, summarizer)
        except FetcherError as exc:
            print("抓取失败: %s" % exc, file=sys.stderr)
            return 1
        except SummarizerError as exc:
            print("摘要失败: %s" % exc, file=sys.stderr)
            return 1
        email = render_email(digest, snapshot)
        html_path, txt_path = write_email_files(
            email, args.out_dir or cfg.output_dir, args.name
        )
        print("主题: %s" % email.subject)
        print("HTML: %s" % html_path)
        print("TEXT: %s" % txt_path)
        return 0

    if args.command == "run-once":
        try:
            job()
        except FetcherError as exc:
            print("抓取失败: %s" % exc, file=sys.stderr)
            return 1
        except SummarizerError as exc:
            print("摘要失败: %s" % exc, file=sys.stderr)
            return 1
        return 0

    expr = args.cron or cfg.cron
    schedule = CronSchedule(expr)
    print("调度已启动，cron=%r" % expr, flush=True)
    run_forever(schedule, job)
    return 0


if __name__ == "__main__":
    sys.exit(main())
