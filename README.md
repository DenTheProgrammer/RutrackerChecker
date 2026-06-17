# RuTracker Release Checker

Local web app for tracking RuTracker search queries and spotting new 1080p-or-better releases with enough seeders.

The app stores state in SQLite, shows `N new` counters per query, and can send Telegram notifications when newly matching torrents appear. It does not download torrents or magnet links.

## Quick Start

Double-click `RutrackerChecker.exe` if it is present in this folder. It starts the local server and opens the UI in your browser. When you close all UI tabs, the local server stops automatically after the idle grace period.

On first launch, fill in RuTracker username/password in the Settings panel and click `Save settings`. The credentials are saved locally in `data/app.db`. Leave password/token fields empty later to keep saved values.

If the launcher is not present, start the app from PowerShell:

```powershell
.\run.ps1
```

Open http://127.0.0.1:9876.

## Sharing with another user

Recommended option: share the GitHub repository link and have the other user clone it:

```powershell
git clone https://github.com/DenTheProgrammer/RutrackerChecker.git
cd RutrackerChecker
.\run.ps1
```

This keeps the folder as a Git working copy, so the built-in update button can check for new commits and install them.

You can also share the folder or a ZIP archive as a portable copy. The app will still run, but built-in updates only work if the received folder includes the hidden `.git` directory and Git is installed. A ZIP downloaded from GitHub normally does not include `.git`, so it should be treated as a manual-update copy.

## Optional .env Setup

`.env` is still supported as a fallback, but it is no longer required for normal use.

1. Copy `.env.example` to `.env`.
2. Optionally fill in:
   - `RUTRACKER_USERNAME`
   - `RUTRACKER_PASSWORD`
   - optional `TELEGRAM_BOT_TOKEN`
   - optional `TELEGRAM_CHAT_ID`

## Usage

- Add a RuTracker search query, for example `Drama 2025`. A new card is created immediately, and its first RuTracker check starts in the background.
- Use the advanced settings in the movie dialog to override the displayed title, poster, IMDb URL, or filters.
- By default, searches run across all RuTracker sections, matching the normal site search.
- Set the minimum number of seeders and minimum size in GB.
- Click `Check` for one query or `Check all` for all enabled queries. Manual `Check all` runs in the background and each card stops showing its check spinner as soon as that card's RuTracker request finishes.
- Click a title to open the RuTracker search page.
- Review new result links manually, then click `Reset new` to clear the badge.

## Background Checks

The UI server only checks while its process is running unless `Keep checking in background` is enabled in Settings. When background checks are enabled, launching `RutrackerChecker.exe` or saving the setting starts the tray icon; when the setting is disabled, the tray icon and background loop stop.

For unattended checks after Windows logon, install the Windows Startup background entry:

```powershell
.\install_startup.ps1
```

This starts the tray icon at Windows logon only when background checks are enabled. The tray icon shows whether the background checker is running or stale, and its menu can open the UI, run a check now, or pause automatic checks. The loop runs `check_once.py` using the interval from Settings, logs each run to `data/checks.log`, and shows a clickable Windows toast notification when new matching releases appear. Clicking the notification opens the UI, starting the local server first if needed. Temporary check errors are written to the log without showing a notification. If the computer is off, checks do not run while it is off; after the next logon, the loop resumes and unseen topic ids will still be marked as new.

To remove the Startup entry and stop the loop:

```powershell
.\uninstall_startup.ps1
```

If you prefer Windows Task Scheduler instead, `install_task.ps1` and `uninstall_task.ps1` are included, but some Windows policies require elevated permissions for scheduled tasks.

## Updates

The app can check for new commits in its configured Git upstream and install them with `git pull --ff-only`. This requires Git to be installed and the app folder to be a Git working copy.

For updates without a GitHub login, `https://github.com/DenTheProgrammer/RutrackerChecker.git` must be public/readable. Users only need read access; they do not need push access. If the repository is private, the user must configure GitHub authentication for Git on their machine before the update button can fetch or pull.

Updates are intentionally blocked when the working tree has uncommitted changes, the local branch has commits that are not in the upstream branch, or the branches diverged. Resolve that Git state manually, then use the update button again.

## Configuration

- `DEFAULT_MIN_SEEDERS`: default minimum active seeders for new items.
- `DEFAULT_MIN_SIZE_GB`: default minimum torrent size in GB for new items.
- `DEFAULT_REQUIRE_1080P`: `1` filters out releases below 1080p by title/row metadata.
- `DEFAULT_BACKGROUND_ENABLED`: `1` keeps automatic background checks enabled; set to `0` for manual-only checks.
- `DEFAULT_CHECK_INTERVAL_MINUTES`: background check interval. Set to `0` to disable scheduled checks.
- `DEFAULT_REMINDER_INTERVAL_HOURS`: pending-release reminder interval. Set to `0` to disable reminders.
- `MAX_SEARCH_PAGES`: how many RuTracker result pages to scan per query.
- `RUTRACKER_REQUEST_ATTEMPTS`: retry attempts for each RuTracker HTTP request; default is `8`.
- `RUTRACKER_REQUEST_TIMEOUT_SECONDS`: per-request RuTracker timeout; default is `2`.
- `RUTRACKER_RETRY_BASE_SECONDS`: base delay between RuTracker request retries; default is `0`.
- `INITIAL_ITEM_CHECK_ATTEMPTS`: attempts for the first background check after adding a new item; default is `2`.
- `INITIAL_ITEM_CHECK_RETRY_SECONDS`: delay between those new-item attempts; default is `3`.
- `CHECK_ALL_MAX_WORKERS`: simultaneous RuTracker requests for the manual "check all" action; default is `3`. All enabled cards enter the checking state immediately, but requests are limited to this worker count.
- `AUTO_SHUTDOWN_WHEN_IDLE`: `1` stops the server after all UI tabs are closed.
- `AUTO_SHUTDOWN_GRACE_SECONDS`: idle close delay; default is `45`.
- `APP_HOST` and `APP_PORT`: local server address.

## Tests

```powershell
.\run.ps1 -Test
```

The tests cover RuTracker HTML parsing, filtering, SQLite idempotency, reset behavior, background item checks, and manual check-all state tracking.

## Build Launcher

```powershell
dotnet publish .\launcher\RutrackerChecker.Launcher.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o .
```
