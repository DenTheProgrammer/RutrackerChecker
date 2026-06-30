from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

from app import CHECKER, CHECK_ALL_MAX_WORKERS, CLIENT, DB


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be at least 0")
    return parsed


def run_once(workers: int, warm_login: bool) -> dict[str, Any]:
    if warm_login:
        CLIENT.login()

    items = [item for item in DB.list_items() if item["enabled"]]
    started = time.perf_counter()
    summary = CHECKER.check_all(
        notify=False,
        items=items,
        max_workers=workers,
    )
    elapsed = time.perf_counter() - started
    errors = [
        result
        for result in summary.get("results", [])
        if result.get("error")
    ]
    return {
        "seconds": elapsed,
        "items_checked": int(summary.get("items_checked", 0)),
        "total_new": int(summary.get("total_new", 0)),
        "total_pending_new": int(summary.get("total_pending_new", 0)),
        "total_pending_new_item_count": int(summary.get("total_pending_new_item_count", 0)),
        "errors": len(errors),
        "error_items": [
            str((result.get("item") or {}).get("title") or (result.get("item") or {}).get("query") or "")
            for result in errors
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure full RuTracker check-all wall-clock time."
    )
    parser.add_argument("--repeats", type=positive_int, default=3)
    parser.add_argument("--workers", type=positive_int, default=CHECK_ALL_MAX_WORKERS)
    parser.add_argument("--max-errors", type=non_negative_int, default=0)
    parser.add_argument(
        "--include-login",
        action="store_true",
        help="Include the first RuTracker login in the measured time.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full measurement record as JSON after the parseable metric line.",
    )
    args = parser.parse_args()

    runs = []
    warm_login = not args.include_login
    for _ in range(args.repeats):
        runs.append(run_once(args.workers, warm_login=warm_login))

    seconds = [float(run["seconds"]) for run in runs]
    error_count = sum(int(run["errors"]) for run in runs)
    items_checked = [int(run["items_checked"]) for run in runs]
    record = {
        "metric": "mean_wall_clock_seconds",
        "mean_wall_clock_seconds": statistics.fmean(seconds),
        "median_wall_clock_seconds": statistics.median(seconds),
        "min_wall_clock_seconds": min(seconds),
        "max_wall_clock_seconds": max(seconds),
        "repeats": args.repeats,
        "workers": args.workers,
        "include_login": args.include_login,
        "items_checked_min": min(items_checked) if items_checked else 0,
        "items_checked_max": max(items_checked) if items_checked else 0,
        "errors": error_count,
        "runs": runs,
    }

    print(
        "mean_wall_clock_seconds={mean_wall_clock_seconds:.6f} "
        "errors={errors} repeats={repeats} workers={workers} "
        "items_checked_min={items_checked_min} items_checked_max={items_checked_max}".format(
            **record
        )
    )
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))

    return 1 if error_count > args.max_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
