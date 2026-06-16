from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app import CHECKER, DB, DEFAULT_REMINDER_INTERVAL_HOURS


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_PATH = DATA_DIR / "checks.log"
NOTIFY_SCRIPT = BASE_DIR / "scripts" / "show-toast.ps1"
LAST_PENDING_REMINDER_SETTING = "last_pending_reminder_at"


def summarize_result(
    result: dict[str, Any],
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    rows = []
    for entry in result.get("results", []):
        item = entry.get("item") or {}
        rows.append(
            {
                "title": item.get("title") or item.get("query"),
                "query": item.get("query"),
                "raw": entry.get("raw", 0),
                "matched": entry.get("matched", 0),
                "new": entry.get("new", 0),
                "pending_new": entry.get("pending_new", 0),
                "pruned_new": entry.get("pruned_new", 0),
                "error": entry.get("error"),
            }
        )
    return {
        "timestamp": now.isoformat(),
        "items_checked": result.get("items_checked", 0),
        "total_new": result.get("total_new", 0),
        "total_pending_new": result.get("total_pending_new", 0),
        "results": rows,
    }


def append_log(record: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def notify_windows(title: str, message: str) -> None:
    if not NOTIFY_SCRIPT.exists():
        return
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(NOTIFY_SCRIPT),
                "-Title",
                title,
                "-Message",
                message,
            ],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError:
        return


def parse_timestamp(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def pending_reminder_due(
    last_sent_at: str,
    interval_hours: int,
    now: dt.datetime,
) -> bool:
    if interval_hours <= 0:
        return False

    last_sent = parse_timestamp(last_sent_at)
    if last_sent is None:
        return True

    return now - last_sent >= dt.timedelta(hours=interval_hours)


def build_pending_reminder(record: dict[str, Any]) -> tuple[str, str] | None:
    pending_rows = [
        row for row in record["results"] if int(row.get("pending_new") or 0) > 0
    ]
    if not pending_rows:
        return None

    titles = [
        str(row.get("title") or row.get("query") or "Untitled")
        for row in pending_rows
    ]
    visible = titles[:2]
    suffix = ""
    if len(titles) > len(visible):
        suffix = f", +{len(titles) - len(visible)}"
    return "RuTracker Checker", "Уже доступно для просмотра: " + ", ".join(visible) + suffix


def build_notification(
    record: dict[str, Any],
    reminder_interval_hours: int = 0,
    last_pending_reminder_at: str = "",
    now: dt.datetime | None = None,
) -> tuple[str, str] | None:
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    new_rows = [row for row in record["results"] if int(row.get("new") or 0) > 0]

    if new_rows:
        parts = [f"{row['query']}: {row['new']}" for row in new_rows]
        return "RuTracker Checker", "New releases: " + ", ".join(parts)

    if pending_reminder_due(last_pending_reminder_at, reminder_interval_hours, now):
        return build_pending_reminder(record)

    return None


def main(quiet: bool = False) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    result = CHECKER.check_all(notify=True)
    record = summarize_result(result, now)
    append_log(record)

    notification = build_notification(
        record,
        DB.get_setting_int("reminder_interval_hours", DEFAULT_REMINDER_INTERVAL_HOURS),
        DB.get_setting(LAST_PENDING_REMINDER_SETTING),
        now,
    )
    if notification:
        notify_windows(*notification)
        DB.set_setting(LAST_PENDING_REMINDER_SETTING, now.isoformat())

    if not quiet:
        print(json.dumps(record, ensure_ascii=False))
    return 1 if any(row.get("error") for row in record["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
