# RuTracker Release Checker

Local web app for tracking RuTracker search queries and spotting new 1080p-or-better releases with enough seeders.

The app stores state in SQLite, shows `N new` counters per query, and can send Telegram notifications when newly matching torrents appear. It does not download torrents or magnet links.

## Quick Start

Double-click `RutrackerChecker.exe` if it is present in this folder. It starts the local server and opens the UI in your browser.

On first launch, fill in RuTracker username/password in the Settings panel and click `Save settings`. The credentials are saved locally in `data/app.db`. Leave password/token fields empty later to keep saved values.

If the launcher is not present, start the app from PowerShell:

```powershell
.\run.ps1
```

Open http://127.0.0.1:9876.

## Optional .env Setup

`.env` is still supported as a fallback, but it is no longer required for normal use.

1. Copy `.env.example` to `.env`.
2. Optionally fill in:
   - `RUTRACKER_USERNAME`
   - `RUTRACKER_PASSWORD`
   - optional `TELEGRAM_BOT_TOKEN`
   - optional `TELEGRAM_CHAT_ID`

## Usage

- Add a title and a RuTracker search query, for example `Drama 2025`.
- By default, searches run across all RuTracker sections, matching the normal site search.
- Set the minimum number of seeders and minimum size in GB.
- Click `Check` for one query or `Check all` for all enabled queries.
- Click a title to open the RuTracker search page.
- Review new result links manually, then click `Reset new` to clear the badge.

## Background Checks

The UI server only checks while its process is running. For unattended checks without keeping the UI open, install the Windows Startup background loop:

```powershell
.\install_startup.ps1
```

This starts `background_loop.py` and a tray icon at Windows logon. The tray icon shows whether the background checker is running, paused, or stale, and its menu can open the UI, run a check now, or pause/resume automatic checks. The loop runs `check_once.py` using the interval from Settings, logs each run to `data/checks.log`, and shows a clickable Windows toast notification when new matching releases appear. Clicking the notification opens the UI, starting the local server first if needed. Temporary check errors are written to the log without showing a notification. If the computer is off, checks do not run while it is off; after the next logon, the loop resumes and unseen topic ids will still be marked as new.

To remove the Startup entry and stop the loop:

```powershell
.\uninstall_startup.ps1
```

If you prefer Windows Task Scheduler instead, `install_task.ps1` and `uninstall_task.ps1` are included, but some Windows policies require elevated permissions for scheduled tasks.

## Configuration

- `DEFAULT_MIN_SEEDERS`: default minimum active seeders for new items.
- `DEFAULT_MIN_SIZE_GB`: default minimum torrent size in GB for new items.
- `DEFAULT_REQUIRE_1080P`: `1` filters out releases below 1080p by title/row metadata.
- `DEFAULT_BACKGROUND_ENABLED`: `1` keeps automatic background checks enabled; set to `0` for manual-only checks.
- `DEFAULT_CHECK_INTERVAL_MINUTES`: background check interval. Set to `0` to disable scheduled checks.
- `DEFAULT_REMINDER_INTERVAL_HOURS`: pending-release reminder interval. Set to `0` to disable reminders.
- `MAX_SEARCH_PAGES`: how many RuTracker result pages to scan per query.
- `AUTO_SHUTDOWN_WHEN_IDLE`: `1` stops the server after all UI tabs are closed.
- `AUTO_SHUTDOWN_GRACE_SECONDS`: idle close delay; default is `45`.
- `APP_HOST` and `APP_PORT`: local server address.

## Tests

```powershell
.\run.ps1 -Test
```

The tests cover RuTracker HTML parsing, filtering, SQLite idempotency, and reset behavior.

## Build Launcher

```powershell
dotnet publish .\launcher\RutrackerChecker.Launcher.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o .
```
