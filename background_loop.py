from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import check_once
from app import DB, DEFAULT_CHECK_INTERVAL_MINUTES, UPDATE_SERVICE


DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_PATH = DATA_DIR / "checks.log"
RUNTIME_STATUS_PATH = DATA_DIR / "runtime_status.json"
LOCK_PATH = DATA_DIR / "background_loop.lock"
LAUNCHER_PATH = DATA_DIR.parent / "RutrackerChecker.exe"


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def write_runtime_status(**updates: object) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        current = json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(
        {
            "pid": os.getpid(),
            "last_heartbeat_at": iso_now(),
            **updates,
        }
    )
    tmp_path = RUNTIME_STATUS_PATH.with_name(f"{RUNTIME_STATUS_PATH.stem}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        # Readers (UI server, tray) may briefly hold the target open, which blocks replace on Windows.
        for attempt in range(5):
            try:
                tmp_path.replace(RUNTIME_STATUS_PATH)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)
    except OSError as exc:
        # The heartbeat is best effort; a missed write must not fail the check itself.
        print(f"Runtime status write failed: {exc}")
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_single_instance_lock(timeout_seconds: float = 10) -> object | None:
    DATA_DIR.mkdir(exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            # A replaced instance may still be releasing the lock while it exits.
            if time.monotonic() >= deadline:
                handle.close()
                return None
            time.sleep(0.5)


def log_loop_error(exc: Exception) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    record = {
        "timestamp": iso_now(),
        "loop_error": str(exc),
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    check_once.notify_windows("RuTracker Checker error", str(exc))


def current_interval_seconds() -> int:
    minutes = DB.get_setting_int("check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES)
    if minutes <= 0:
        return 0
    return max(5 * 60, minutes * 60)


def background_enabled() -> bool:
    return DB.get_setting("background_enabled", "1") == "1"


def sleep_with_heartbeat(seconds: int, status: str = "waiting") -> bool:
    deadline = utc_now() + dt.timedelta(seconds=seconds)
    while True:
        remaining = (deadline - utc_now()).total_seconds()
        if remaining <= 0:
            return True
        if not background_enabled():
            write_runtime_status(
                status="paused",
                next_check_at=None,
                last_check_status="manual_only",
                last_check_message="Background checks are disabled",
            )
            return False
        write_runtime_status(status=status, next_check_at=deadline.isoformat())
        time.sleep(min(30, max(1, remaining)))


def run_check_with_heartbeat() -> None:
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["exit_code"] = check_once.main(quiet=True)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    while thread.is_alive():
        write_runtime_status(status="checking", next_check_at=None)
        thread.join(timeout=30)

    error = result.get("error")
    if isinstance(error, Exception):
        raise error


def refresh_rutracker_session_if_required() -> bool:
    if DB.get_setting("rutracker_auth_required") != "1":
        return False
    if not DB.get_rutracker_session_cookies() or not LAUNCHER_PATH.exists():
        return False

    write_runtime_status(status="refreshing_auth", next_check_at=None)
    try:
        result = subprocess.run(
            [str(LAUNCHER_PATH), "--refresh-auth"],
            cwd=DATA_DIR.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Automatic RuTracker login failed: {exc}")
        return False
    return result.returncode == 0 and DB.get_setting("rutracker_auth_required") != "1"


def run_check_with_auth_refresh() -> bool:
    if DB.get_setting("rutracker_auth_required") == "1" and not refresh_rutracker_session_if_required():
        return False

    run_check_with_heartbeat()
    if DB.get_setting("rutracker_auth_required") == "1":
        if not refresh_rutracker_session_if_required():
            return False
        run_check_with_heartbeat()
    return DB.get_setting("rutracker_auth_required") != "1"


def refresh_update_status() -> None:
    try:
        UPDATE_SERVICE.get_status(force_fetch=False)
    except Exception as exc:
        print(f"Update check failed: {exc}")


def main() -> int:
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        print("Another background loop is already running")
        return 0

    while True:
        if not background_enabled():
            write_runtime_status(
                status="paused",
                next_check_at=None,
                last_check_status="manual_only",
                last_check_message="Background checks are disabled",
            )
            return 0

        interval_seconds = current_interval_seconds()
        if interval_seconds <= 0:
            write_runtime_status(
                status="manual_only",
                next_check_at=None,
                last_check_status="manual_only",
                last_check_message="Check interval is 0",
            )
            time.sleep(15)
            continue

        try:
            write_runtime_status(status="checking", next_check_at=None)
            auth_ok = run_check_with_auth_refresh()
            refresh_update_status()
            next_check_at = utc_now() + dt.timedelta(seconds=interval_seconds)
            write_runtime_status(
                status="waiting",
                last_check_at=iso_now(),
                last_check_status="ok" if auth_ok else "auth_required",
                last_check_message=(
                    "Last automatic check finished"
                    if auth_ok else "Waiting for RuTracker browser login"
                ),
                next_check_at=next_check_at.isoformat(),
            )
        except Exception as exc:
            log_loop_error(exc)
            next_check_at = utc_now() + dt.timedelta(seconds=interval_seconds)
            write_runtime_status(
                status="waiting",
                last_check_at=iso_now(),
                last_check_status="error",
                last_check_message=str(exc),
                next_check_at=next_check_at.isoformat(),
            )
        if not sleep_with_heartbeat(interval_seconds):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
