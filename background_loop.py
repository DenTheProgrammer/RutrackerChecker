from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import check_once
from app import DB, DEFAULT_CHECK_INTERVAL_MINUTES


DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_PATH = DATA_DIR / "checks.log"


def log_loop_error(exc: Exception) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    record = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "loop_error": str(exc),
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    check_once.notify_windows("RuTracker Checker error", str(exc))


def current_interval_seconds() -> int:
    minutes = DB.get_setting_int("check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES)
    if minutes <= 0:
        minutes = DEFAULT_CHECK_INTERVAL_MINUTES
    return max(5 * 60, minutes * 60)


def main() -> int:
    while True:
        try:
            check_once.main(quiet=True)
        except Exception as exc:
            log_loop_error(exc)
        time.sleep(current_interval_seconds())


if __name__ == "__main__":
    raise SystemExit(main())
