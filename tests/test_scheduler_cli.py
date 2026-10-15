import os
import tempfile
import unittest
from datetime import datetime

from x_trends_digest.cli import main
from x_trends_digest.scheduler import CronSchedule, run_forever


class CronTest(unittest.TestCase):
    def test_daily_nine(self):
        s = CronSchedule("0 9 * * *")
        self.assertEqual(s.next_after(datetime(2026, 1, 1, 8, 30)), datetime(2026, 1, 1, 9, 0))
        self.assertEqual(s.next_after(datetime(2026, 1, 1, 9, 0)), datetime(2026, 1, 2, 9, 0))

    def test_step_and_range(self):
        s = CronSchedule("*/15 9-10 * * *")
        self.assertEqual(s.next_after(datetime(2026, 1, 1, 9, 50)), datetime(2026, 1, 1, 10, 0))
        self.assertEqual(s.next_after(datetime(2026, 1, 1, 10, 50)), datetime(2026, 1, 2, 9, 0))

    def test_weekday(self):
        # 2026-01-05 是周一；"0 8 * * 1" 之后的下一次是下周一
        s = CronSchedule("0 8 * * 1")
        self.assertEqual(s.next_after(datetime(2026, 1, 5, 8, 0)), datetime(2026, 1, 12, 8, 0))

    def test_sunday_zero_and_seven(self):
        a = CronSchedule("0 0 * * 0").next_after(datetime(2026, 1, 1))
        b = CronSchedule("0 0 * * 7").next_after(datetime(2026, 1, 1))
        self.assertEqual(a, b)
        self.assertEqual(a.weekday(), 6)

    def test_invalid(self):
        for bad in ("* * * *", "61 * * * *", "*/0 * * * *", "a * * * *"):
            with self.assertRaises(ValueError):
                CronSchedule(bad)


class RunForeverTest(unittest.TestCase):
    def test_runs_job_and_survives_errors(self):
        clock = [datetime(2026, 1, 1, 8, 59)]
        slept = []

        def sleep(sec):
            slept.append(sec)
            clock[0] = clock[0].fromtimestamp(clock[0].timestamp() + sec)

        calls, errors = [], []

        def job():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

        n = run_forever(CronSchedule("* * * * *"), job, now=lambda: clock[0],
                        sleep=sleep, max_runs=2, on_error=errors.append)
        self.assertEqual(n, 2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(slept[0], 60)


class CliTest(unittest.TestCase):
    def test_run_once_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("XTD_OUTPUT_DIR")
            os.environ["XTD_OUTPUT_DIR"] = d
            try:
                rc = main(["--env-file", os.path.join(d, "none.env"), "run-once"])
            finally:
                if old is None:
                    del os.environ["XTD_OUTPUT_DIR"]
                else:
                    os.environ["XTD_OUTPUT_DIR"] = old
            names = os.listdir(d)
        self.assertEqual(rc, 0)
        self.assertEqual(len([n for n in names if n.endswith(".html")]), 1)
        self.assertEqual(len([n for n in names if n.endswith(".txt")]), 1)


if __name__ == "__main__":
    unittest.main()
