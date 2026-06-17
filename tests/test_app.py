import base64
import json
import subprocess
import tempfile
import threading
import time
import unittest
import datetime as dt
import sqlite3
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import app
from check_once import build_notification
from app import (
    CheckerService,
    Database,
    RequestHandler,
    RuTrackerClient,
    SearchResult,
    TransientRuTrackerError,
    duplicate_similarity,
    fetch_movie_metadata,
    filter_results,
    parse_rutracker_results,
    parse_next_page_url,
    parse_resolution,
    quote_rutracker_query,
    refresh_item_metadata,
)


SAMPLE_HTML = """
<html>
  <body>
    <table id="tor-tbl">
      <tr class="hl-tr">
        <td class="t-title-col">
          <a class="torTopic" href="viewtopic.php?t=111">Drama / Драма (2025) WEB-DL 1080p</a>
        </td>
        <td class="tor-size">4.32 GB</td>
        <td class="seedmed">12</td>
      </tr>
      <tr class="hl-tr">
        <td class="t-title-col">
          <a class="torTopic" href="./viewtopic.php?t=222">Drama / Драма (2025) WEB-DL 720p</a>
        </td>
        <td class="tor-size">8.4 GB</td>
        <td class="seedmed">99</td>
      </tr>
      <tr class="hl-tr">
        <td class="t-title-col">
          <a class="torTopic" href="viewtopic.php?t=333">Drama / Драма (2025) UHD 2160p</a>
        </td>
        <td class="tor-size">2.34 GB</td>
        <td class="seedmed">2</td>
      </tr>
    </table>
  </body>
</html>
"""


class ParserTests(unittest.TestCase):
    def test_extracts_topic_title_link_seeders(self):
        results = parse_rutracker_results(SAMPLE_HTML)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].topic_id, "111")
        self.assertEqual(results[0].title, "Drama / Драма (2025) WEB-DL 1080p")
        self.assertEqual(results[0].seeders, 12)
        self.assertEqual(results[0].resolution, "1080p")
        self.assertEqual(results[0].size_label, "4.32 GB")
        self.assertTrue(results[0].url.endswith("viewtopic.php?t=111"))

    def test_filters_size_seeders_and_1080p(self):
        results = filter_results(
            parse_rutracker_results(SAMPLE_HTML),
            min_seeders=5,
            min_size_gb=5,
            require_1080p=True,
        )

        self.assertEqual([result.topic_id for result in results], [])

    def test_can_allow_720p_when_quality_filter_off(self):
        results = filter_results(
            parse_rutracker_results(SAMPLE_HTML),
            min_seeders=5,
            min_size_gb=5,
            require_1080p=False,
        )

        self.assertEqual([result.topic_id for result in results], ["222"])

    def test_quotes_cyrillic_query_for_rutracker(self):
        self.assertEqual(quote_rutracker_query("Драма 2025"), "%C4%F0%E0%EC%E0%202025")

    def test_search_url_can_include_movie_forum(self):
        self.assertEqual(
            RuTrackerClient.search_url("Drama 2025"),
            "https://rutracker.org/forum/tracker.php?nm=Drama%202025",
        )

    def test_parses_next_page_url(self):
        html = '<a href="tracker.php?nm=Iron%20Man%202008&amp;start=50">След.</a>'

        self.assertEqual(
            parse_next_page_url(
                html,
                "https://rutracker.org/forum/tracker.php?nm=Iron%20Man%202008",
            ),
            "https://rutracker.org/forum/tracker.php?nm=Iron%20Man%202008&start=50",
        )

    def test_detects_common_1080_and_better_labels(self):
        self.assertEqual(parse_resolution("Movie WEB-DL 1080"), "1080p")
        self.assertEqual(parse_resolution("Movie 1920x1080"), "1080p")
        self.assertEqual(parse_resolution("Movie UHD"), "2160p")
        self.assertIsNone(parse_resolution("Movie 720p"))


class NotificationTests(unittest.TestCase):
    def test_notifies_pending_reminder_when_due(self):
        now = dt.datetime(2026, 6, 17, 12, 0, tzinfo=dt.timezone.utc)
        record = {
            "results": [
                {"title": "Movie A", "query": "movie a", "new": 0, "pending_new": 2},
                {"title": "Movie B", "query": "movie b", "new": 0, "pending_new": 1},
                {"title": "Movie C", "query": "movie c", "new": 0, "pending_new": 1},
            ]
        }

        self.assertEqual(
            build_notification(
                record,
                reminder_interval_hours=12,
                last_pending_reminder_at="2026-06-16T23:59:00+00:00",
                now=now,
            ),
            ("RuTracker Checker", "Уже доступно для просмотра: Movie A, Movie B, +1"),
        )

    def test_does_not_notify_pending_reminder_before_interval(self):
        now = dt.datetime(2026, 6, 17, 12, 0, tzinfo=dt.timezone.utc)
        record = {
            "results": [
                {"title": "Movie A", "query": "movie a", "new": 0, "pending_new": 2}
            ]
        }

        self.assertIsNone(
            build_notification(
                record,
                reminder_interval_hours=12,
                last_pending_reminder_at="2026-06-17T01:00:00+00:00",
                now=now,
            )
        )

    def test_does_not_notify_pending_reminder_when_disabled(self):
        now = dt.datetime(2026, 6, 17, 12, 0, tzinfo=dt.timezone.utc)
        record = {
            "results": [
                {"title": "Movie A", "query": "movie a", "new": 0, "pending_new": 2}
            ]
        }

        self.assertIsNone(
            build_notification(
                record,
                reminder_interval_hours=0,
                last_pending_reminder_at="",
                now=now,
            )
        )

    def test_does_not_notify_pending_reminder_without_pending_new(self):
        now = dt.datetime(2026, 6, 17, 12, 0, tzinfo=dt.timezone.utc)
        record = {
            "results": [
                {"title": "Movie A", "query": "movie a", "new": 0, "pending_new": 0}
            ]
        }

        self.assertIsNone(
            build_notification(
                record,
                reminder_interval_hours=12,
                last_pending_reminder_at="",
                now=now,
            )
        )

    def test_notifies_new_results(self):
        record = {
            "results": [
                {"query": "Drama 2026", "new": 2, "error": None},
                {"query": "Iron Man 2008", "new": 0, "error": "HTTP Error 521: <none>"},
            ]
        }

        self.assertEqual(
            build_notification(record),
            ("RuTracker Checker", "New releases: Drama 2026: 2"),
        )

    def test_does_not_notify_check_errors(self):
        record = {
            "results": [
                {"query": "Iron Man 2008", "new": 0, "error": "HTTP Error 521: <none>"}
            ]
        }

        self.assertIsNone(build_notification(record))


class GitUpdateServiceTests(unittest.TestCase):
    def make_service(self, tmp: str) -> app.GitUpdateService:
        root = Path(tmp)
        (root / ".git").mkdir()
        return app.GitUpdateService(root)

    def git_run(self, overrides=None, missing_git: bool = False):
        mapping = {
            ("--version",): (0, "git version 2.45.0\n", ""),
            ("branch", "--show-current"): (0, "master\n", ""),
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/master\n", ""),
            ("fetch", "--quiet"): (0, "", ""),
            ("status", "--porcelain"): (0, "", ""),
            ("rev-parse", "HEAD"): (0, "aaa\n", ""),
            ("rev-parse", "@{u}"): (0, "aaa\n", ""),
            ("merge-base", "HEAD", "@{u}"): (0, "aaa\n", ""),
            ("rev-list", "--count", "@{u}..HEAD"): (0, "0\n", ""),
            ("rev-list", "--count", "HEAD..@{u}"): (0, "0\n", ""),
        }
        if overrides:
            mapping.update(overrides)

        def fake_run(command, **kwargs):
            args = tuple(command[1:])
            if missing_git and args == ("--version",):
                raise FileNotFoundError("git")
            code, stdout, stderr = mapping.get(args, (1, "", f"unexpected git command: {args}"))
            return subprocess.CompletedProcess(command, code, stdout, stderr)

        return fake_run

    def test_status_reports_no_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = app.GitUpdateService(Path(tmp))

            status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "no_git_repo")
        self.assertFalse(status.supported)

    def test_status_reports_missing_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run(missing_git=True)):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "git_missing")
        self.assertFalse(status.supported)

    def test_status_reports_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run()):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "up_to_date")
        self.assertFalse(status.update_available)

    def test_status_reports_update_available_when_behind(self):
        overrides = {
            ("rev-parse", "@{u}"): (0, "bbb\n", ""),
            ("rev-list", "--count", "HEAD..@{u}"): (0, "2\n", ""),
        }
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run(overrides)):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "update_available")
        self.assertTrue(status.can_apply)
        self.assertEqual(status.behind_count, 2)

    def test_status_blocks_dirty_tree(self):
        overrides = {
            ("status", "--porcelain"): (0, " M app.py\n", ""),
        }
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run(overrides)):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "blocked_dirty")
        self.assertFalse(status.can_apply)

    def test_status_hides_update_prompt_for_ahead_branch(self):
        overrides = {
            ("rev-parse", "HEAD"): (0, "bbb\n", ""),
            ("merge-base", "HEAD", "@{u}"): (0, "aaa\n", ""),
            ("rev-list", "--count", "@{u}..HEAD"): (0, "1\n", ""),
        }
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run(overrides)):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "local_ahead")
        self.assertFalse(status.update_available)
        self.assertFalse(status.can_apply)

    def test_status_hides_update_prompt_for_diverged_branch(self):
        overrides = {
            ("rev-parse", "HEAD"): (0, "bbb\n", ""),
            ("rev-parse", "@{u}"): (0, "ccc\n", ""),
            ("merge-base", "HEAD", "@{u}"): (0, "aaa\n", ""),
            ("rev-list", "--count", "@{u}..HEAD"): (0, "1\n", ""),
            ("rev-list", "--count", "HEAD..@{u}"): (0, "1\n", ""),
        }
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=self.git_run(overrides)):
                status = service.get_status(force_fetch=True)

        self.assertEqual(status.state, "local_diverged")
        self.assertFalse(status.update_available)
        self.assertFalse(status.can_apply)

    def test_apply_runs_ff_only_pull_for_clean_behind_state(self):
        overrides = {
            ("rev-parse", "@{u}"): (0, "bbb\n", ""),
            ("rev-list", "--count", "HEAD..@{u}"): (0, "1\n", ""),
            ("pull", "--ff-only"): (0, "updated\n", ""),
        }
        calls = []

        def fake_run(command, **kwargs):
            calls.append(tuple(command[1:]))
            return self.git_run(overrides)(command, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=fake_run), patch.object(
                service,
                "_schedule_restart",
                return_value=True,
            ):
                payload = service.apply_update()

        self.assertTrue(payload["updated"])
        self.assertIn(("pull", "--ff-only"), calls)

    def test_apply_refuses_blocked_state_without_pull(self):
        overrides = {
            ("status", "--porcelain"): (0, " M app.py\n", ""),
        }
        calls = []

        def fake_run(command, **kwargs):
            calls.append(tuple(command[1:]))
            return self.git_run(overrides)(command, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.run", side_effect=fake_run):
                with self.assertRaises(ValueError):
                    service.apply_update()

        self.assertNotIn(("pull", "--ff-only"), calls)

    def test_restart_helper_stops_old_tray_and_background_processes(self):
        popen_calls = []

        def fake_popen(command, **kwargs):
            popen_calls.append(command)

            class FakeProcess:
                pass

            return FakeProcess()

        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(tmp)
            with patch("app.subprocess.Popen", side_effect=fake_popen):
                self.assertTrue(service._schedule_restart())

        encoded = popen_calls[0][popen_calls[0].index("-EncodedCommand") + 1]
        script = base64.b64decode(encoded).decode("utf-16le")

        self.assertIn("Stop-AppHelpers", script)
        self.assertIn("*background_loop.py*", script)
        self.assertIn("*start-tray.ps1*", script)
        self.assertIn("Stop-Process -Id $Process.ProcessId -Force", script)
        self.assertIn("Start-Process -FilePath $Exe -ArgumentList '--server-only'", script)


class DatabaseTests(unittest.TestCase):
    def test_existing_database_gets_metadata_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    query TEXT NOT NULL,
                    min_seeders INTEGER NOT NULL DEFAULT 5,
                    min_size_gb REAL NOT NULL DEFAULT 5,
                    require_1080p INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    topic_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    size_label TEXT NOT NULL DEFAULT '',
                    seeders INTEGER NOT NULL DEFAULT 0,
                    is_new INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(item_id, topic_id)
                );

                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            connection.commit()
            connection.close()

            db = Database(db_path)
            columns = {
                row[1]
                for row in db.conn().execute("PRAGMA table_info(items)").fetchall()
            }

            self.assertIn("imdb_url", columns)
            self.assertIn("poster_url", columns)
            self.assertIn("poster_updated_at", columns)
            self.assertIn("imdb_search_synced_at", columns)
            self.assertIn("sync_search_from_imdb", columns)
            db.close()

    def test_item_metadata_fields_are_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")

            item = db.create_item(
                {
                    "title": "Dune: Part Three",
                    "query": "dune part three 2026",
                    "imdb_url": "https://www.imdb.com/title/tt1234567/?ref_=fn",
                    "poster_url": "https://m.media-amazon.com/images/M/poster.jpg",
                }
            )
            updated = db.update_item(
                item["id"],
                {
                    **item,
                    "imdb_url": "https://www.imdb.com/title/tt7654321/",
                    "poster_url": "https://m.media-amazon.com/images/M/poster-2.jpg",
                },
            )

            self.assertEqual(updated["imdb_url"], "https://www.imdb.com/title/tt7654321/")
            self.assertEqual(
                updated["poster_url"],
                "https://m.media-amazon.com/images/M/poster-2.jpg",
            )
            self.assertTrue(updated["poster_updated_at"])
            self.assertEqual(item["sync_search_from_imdb"], 1)
            db.close()

    def test_refresh_metadata_syncs_search_text_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"title": "gamenight", "query": "gamenight"})

            with patch(
                "app.fetch_movie_metadata",
                return_value={
                    "imdb_url": "https://www.imdb.com/title/tt2704998/",
                    "poster_url": "https://example.com/game-night.jpg",
                    "search_text": "Game Night 2018 John Francis Daley",
                },
            ):
                payload = refresh_item_metadata(db, item["id"])

            self.assertEqual(payload["item"]["title"], "Game Night 2018 John Francis Daley")
            self.assertEqual(payload["item"]["query"], "Game Night 2018 John Francis Daley")
            self.assertEqual(payload["item"]["imdb_url"], "https://www.imdb.com/title/tt2704998/")
            self.assertTrue(payload["item"]["imdb_search_synced_at"])
            db.close()

    def test_refresh_metadata_keeps_manual_search_when_sync_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item(
                {
                    "title": "Manual Game Night",
                    "query": "manual rutracker query",
                    "sync_search_from_imdb": False,
                }
            )

            with patch(
                "app.fetch_movie_metadata",
                return_value={
                    "imdb_url": "https://www.imdb.com/title/tt2704998/",
                    "poster_url": "https://example.com/game-night.jpg",
                    "search_text": "Game Night 2018 John Francis Daley",
                },
            ):
                payload = refresh_item_metadata(db, item["id"])

            self.assertEqual(payload["item"]["title"], "Manual Game Night")
            self.assertEqual(payload["item"]["query"], "manual rutracker query")
            self.assertEqual(payload["item"]["sync_search_from_imdb"], 0)
            self.assertEqual(payload["item"]["imdb_search_synced_at"], "")
            db.close()

    def test_refresh_missing_posters_syncs_existing_imdb_search_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item(
                {
                    "title": "gamenight",
                    "query": "gamenight",
                    "imdb_url": "https://www.imdb.com/title/tt2704998/",
                    "poster_url": "https://example.com/game-night.jpg",
                }
            )

            with patch(
                "app.fetch_movie_metadata",
                return_value={
                    "imdb_url": "https://www.imdb.com/title/tt2704998/",
                    "poster_url": "https://example.com/game-night.jpg",
                    "search_text": "Game Night 2018 John Francis Daley",
                },
            ) as fetch:
                count = app.refresh_missing_posters(db)

            updated = db.get_item(item["id"])
            self.assertEqual(count, 1)
            fetch.assert_called_once()
            self.assertEqual(updated["title"], "Game Night 2018 John Francis Daley")
            self.assertEqual(updated["query"], "Game Night 2018 John Francis Daley")
            self.assertTrue(updated["imdb_search_synced_at"])
            db.close()

    def test_refresh_missing_posters_skips_already_synced_imdb_search_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item(
                {
                    "title": "Game Night 2018 John Francis Daley",
                    "query": "Game Night 2018 John Francis Daley",
                    "imdb_url": "https://www.imdb.com/title/tt2704998/",
                    "poster_url": "https://example.com/game-night.jpg",
                }
            )
            db.update_item_metadata(
                item["id"],
                "https://www.imdb.com/title/tt2704998/",
                "https://example.com/game-night.jpg",
                "Game Night 2018 John Francis Daley",
            )

            with patch("app.fetch_movie_metadata") as fetch:
                count = app.refresh_missing_posters(db)

            self.assertEqual(count, 0)
            fetch.assert_not_called()
            db.close()

    def test_refresh_metadata_keeps_item_usable_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"title": "Drama", "query": "Drama 2026"})

            with patch("app.fetch_movie_metadata", side_effect=RuntimeError("IMDb unavailable")):
                payload = refresh_item_metadata(db, item["id"])

            self.assertEqual(payload["item"]["id"], item["id"])
            self.assertEqual(payload["item"]["poster_url"], "")
            self.assertIn("IMDb unavailable", payload["metadata_error"])
            db.close()

    def test_fetch_movie_metadata_reads_imdb_suggestion_poster(self):
        def fake_fetch_json(url):
            if "query.wikidata.org" in url:
                return {
                    "results": {
                        "bindings": [
                            {
                                "directorLabel": {"value": "First Director"},
                            },
                            {
                                "directorLabel": {"value": "Second Director"},
                            },
                        ]
                    }
                }
            return {
                "d": [
                    {
                        "id": "tt1234567",
                        "l": "Drama",
                        "y": 2026,
                        "qid": "movie",
                        "i": {"imageUrl": "https://m.media-amazon.com/images/M/poster.jpg"},
                    }
                ]
            }

        with patch("app.fetch_json", side_effect=fake_fetch_json):
            metadata = fetch_movie_metadata("Drama", "https://www.imdb.com/title/tt1234567/")

        self.assertEqual(metadata["imdb_url"], "https://www.imdb.com/title/tt1234567/")
        self.assertEqual(
            metadata["poster_url"],
            "https://m.media-amazon.com/images/M/poster.jpg",
            )
        self.assertEqual(metadata["search_text"], "Drama 2026 First Director")

    def test_fetch_movie_metadata_builds_gamenight_search_with_first_director(self):
        def fake_fetch_json(url):
            if "query.wikidata.org" in url:
                return {
                    "results": {
                        "bindings": [
                            {
                                "directorLabel": {"value": "John Francis Daley"},
                            },
                            {
                                "directorLabel": {"value": "Jonathan Goldstein"},
                            },
                        ]
                    }
                }
            return {
                "d": [
                    {
                        "id": "tt2704998",
                        "l": "Game Night",
                        "y": 2018,
                        "qid": "movie",
                        "i": {"imageUrl": "https://m.media-amazon.com/images/M/game-night.jpg"},
                    }
                ]
            }

        with patch("app.fetch_json", side_effect=fake_fetch_json):
            metadata = fetch_movie_metadata("gamenight")

        self.assertEqual(metadata["imdb_url"], "https://www.imdb.com/title/tt2704998/")
        self.assertEqual(metadata["poster_url"], "https://m.media-amazon.com/images/M/game-night.jpg")
        self.assertEqual(metadata["search_text"], "Game Night 2018 John Francis Daley")

    def test_fetch_movie_metadata_tries_simplified_candidates(self):
        def fake_fetch_json(url):
            if "the_odyssey_2026" in url:
                return {
                    "d": [
                        {
                            "id": "tt33764258",
                            "l": "The Odyssey",
                            "y": 2026,
                            "qid": "movie",
                            "i": {"imageUrl": "https://m.media-amazon.com/images/M/odyssey.jpg"},
                        }
                    ]
                }
            return {"d": []}

        with patch("app.fetch_json", side_effect=fake_fetch_json):
            metadata = fetch_movie_metadata("the odyssey nolan 2026")

        self.assertEqual(metadata["imdb_url"], "https://www.imdb.com/title/tt33764258/")
        self.assertEqual(
            metadata["poster_url"],
            "https://m.media-amazon.com/images/M/odyssey.jpg",
        )

    def test_fetch_movie_metadata_falls_back_to_wikidata_by_imdb_id(self):
        def fake_fetch_json(url):
            if "query.wikidata.org" in url:
                return {
                    "results": {
                        "bindings": [
                            {
                                "image": {
                                    "value": "https://commons.wikimedia.org/wiki/Special:FilePath/Drama_poster.jpg"
                                }
                            }
                        ]
                    }
                }
            return {"d": []}

        with patch("app.fetch_json", side_effect=fake_fetch_json):
            metadata = fetch_movie_metadata("Drama", "https://www.imdb.com/title/tt1234567/")

        self.assertEqual(metadata["imdb_url"], "https://www.imdb.com/title/tt1234567/")
        self.assertEqual(
            metadata["poster_url"],
            "https://commons.wikimedia.org/wiki/Special:FilePath/Drama_poster.jpg",
        )

    def test_refresh_missing_posters_updates_only_items_without_posters(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            missing = db.create_item({"title": "Drama", "query": "Drama 2026"})
            existing = db.create_item(
                {
                    "title": "Dune",
                    "query": "Dune 2026",
                    "poster_url": "https://example.com/dune.jpg",
                }
            )

            refreshed_ids = []

            def fake_refresh(db_arg, item_id):
                refreshed_ids.append(item_id)
                return {
                    "item": db_arg.update_item_metadata(
                        item_id,
                        "",
                        f"https://example.com/{item_id}.jpg",
                    ),
                    "metadata_error": "",
                }

            with patch("app.refresh_item_metadata", side_effect=fake_refresh):
                count = app.refresh_missing_posters(db)

            self.assertEqual(count, 1)
            self.assertEqual(refreshed_ids, [missing["id"]])
            self.assertEqual(
                db.get_item(missing["id"])["poster_url"],
                f"https://example.com/{missing['id']}.jpg",
            )
            self.assertEqual(
                db.get_item(existing["id"])["poster_url"],
                "https://example.com/dune.jpg",
            )
            db.close()

    def test_metadata_backfill_can_restart_after_previous_run_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            started = threading.Event()
            release = threading.Event()
            calls = []

            def fake_refresh(db_arg):
                calls.append(db_arg)
                started.set()
                release.wait(3)
                return 0

            with patch.object(app, "DB", db), patch.object(
                app,
                "METADATA_BACKFILL_RUNNING",
                False,
            ), patch("app.refresh_missing_posters", side_effect=fake_refresh):
                try:
                    app.start_metadata_backfill()
                    self.assertTrue(started.wait(1))
                    app.start_metadata_backfill()
                    self.assertEqual(len(calls), 1)
                finally:
                    release.set()

                deadline = time.monotonic() + 3
                while app.METADATA_BACKFILL_RUNNING and time.monotonic() < deadline:
                    time.sleep(0.01)

                started.clear()
                release.clear()
                app.start_metadata_backfill()
                self.assertTrue(started.wait(1))
                release.set()
                deadline = time.monotonic() + 3
                while app.METADATA_BACKFILL_RUNNING and time.monotonic() < deadline:
                    time.sleep(0.01)

            self.assertEqual(len(calls), 2)
            db.close()

    def test_create_item_api_requires_rutracker_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            started_checks = []

            def fake_start_background_item_check(item_id):
                started_checks.append(item_id)
                return True

            with patch.object(app, "DB", db), patch(
                "app.start_background_item_check",
                side_effect=fake_start_background_item_check,
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = f"http://127.0.0.1:{server.server_port}/api/items"
                request = urllib.request.Request(
                    url,
                    data=json.dumps({"query": "Drama 2026"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                try:
                    with self.assertRaises(urllib.error.HTTPError) as context:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(context.exception.code, 400)

                    db.update_settings(
                        {
                            "rutracker_username": "alice",
                            "rutracker_password": "secret",
                        }
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

                    self.assertEqual(response.status, 201)
                    self.assertEqual(payload["query"], "Drama 2026")
                    self.assertEqual(started_checks, [payload["id"]])
                    self.assertTrue(payload["initial_check_started"])
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

    def test_opening_ui_starts_metadata_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db), patch("app.start_metadata_backfill") as backfill:
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5).read()
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

            backfill.assert_called_once()

    def test_check_all_api_starts_background_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db), patch(
                "app.start_background_check_all",
                return_value=True,
            ) as start_check_all, patch.object(
                app.CHECK_ALL,
                "is_active",
                return_value=True,
            ), patch.object(
                app.ITEM_CHECKS,
                "active_ids",
                return_value=[7],
            ), patch.object(
                app.ITEM_CHECKS,
                "queued_ids",
                return_value=[8],
            ), patch.object(
                app.ITEM_CHECKS,
                "completed_results",
                return_value=[],
            ), patch.object(
                app.CHECK_ALL,
                "completed_summary",
                return_value=None,
            ), patch.object(
                app.CHECKER,
                "check_all",
                side_effect=AssertionError("check_all must stay out of the request thread"),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/check-all",
                    method="POST",
                )

                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["check_all_started"])
            self.assertTrue(payload["check_all_running"])
            self.assertEqual(payload["checking_item_ids"], [7])
            self.assertEqual(payload["queued_item_ids"], [8])
            start_check_all.assert_called_once()

    def test_update_status_api_returns_service_payload(self):
        class FakeUpdateService:
            def get_status(self, force_fetch=False):
                self.force_fetch = force_fetch
                return app.UpdateStatus(
                    state="update_available",
                    supported=True,
                    update_available=True,
                    can_apply=True,
                    message="available",
                    checked_at="2026-06-17T00:00:00+00:00",
                    behind_count=2,
                )

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            fake_service = FakeUpdateService()
            with patch.object(app, "DB", db), patch.object(app, "UPDATE_SERVICE", fake_service):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/update/status?force=1",
                        timeout=5,
                    ) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

        self.assertEqual(response.status, 200)
        self.assertTrue(fake_service.force_fetch)
        self.assertEqual(payload["state"], "update_available")
        self.assertTrue(payload["can_apply"])
        self.assertEqual(payload["behind_count"], 2)

    def test_update_apply_api_returns_bad_request_for_blocked_state(self):
        class FakeUpdateService:
            def apply_update(self):
                raise ValueError("blocked")

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db), patch.object(app, "UPDATE_SERVICE", FakeUpdateService()):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/update/apply",
                    method="POST",
                )

                try:
                    with self.assertRaises(urllib.error.HTTPError) as context:
                        urllib.request.urlopen(request, timeout=5)
                    payload = json.loads(context.exception.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

        self.assertEqual(context.exception.code, 400)
        self.assertEqual(payload["error"], "blocked")

    def test_update_apply_api_schedules_shutdown_after_success(self):
        class FakeUpdateService:
            def apply_update(self):
                return {
                    "updated": True,
                    "restart_started": True,
                    "message": "updated",
                    "status": {"state": "up_to_date"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db), patch.object(
                app,
                "UPDATE_SERVICE",
                FakeUpdateService(),
            ), patch("app.request_shutdown") as shutdown:
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/update/apply",
                    method="POST",
                )

                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

        self.assertEqual(response.status, 200)
        self.assertTrue(payload["updated"])
        shutdown.assert_called_once_with("update applied")

    def test_app_icon_assets_are_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    for route, content_type, asset_name in [
                        ("/assets/app-icon.png", "image/png", "app-icon.png"),
                        ("/favicon.ico", "image/x-icon", "app-icon.ico"),
                    ]:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{server.server_port}{route}",
                            timeout=5,
                        ) as response:
                            payload = response.read()

                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers.get_content_type(), content_type)
                        self.assertEqual(payload, (app.ASSETS_DIR / asset_name).read_bytes())
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

    def test_items_api_does_not_start_metadata_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            with patch.object(app, "DB", db), patch("app.start_metadata_backfill") as backfill:
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/items",
                        timeout=5,
                    ).read()
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

            backfill.assert_not_called()

    def test_result_insert_is_idempotent_and_reset_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"title": "Drama", "query": "Drama 2025", "min_seeders": 5})
            result = SearchResult(
                topic_id="111",
                title="Drama 1080p",
                url="https://rutracker.org/forum/viewtopic.php?t=111",
                seeders=12,
                resolution="1080p",
                size_bytes=8 * 1024**3,
                size_label="8 GB",
            )

            first_new = db.save_results(item["id"], [result])
            second_new = db.save_results(item["id"], [result])

            self.assertEqual(len(first_new), 1)
            self.assertEqual(len(second_new), 0)
            self.assertEqual(db.list_items()[0]["new_count"], 1)
            self.assertEqual(db.count_new(item["id"]), 1)

            reset_count = db.reset_new(item["id"])
            third_new = db.save_results(item["id"], [result])

            self.assertEqual(reset_count, 1)
            self.assertEqual(len(third_new), 0)
            self.assertEqual(db.list_items()[0]["new_count"], 0)
            self.assertEqual(db.count_new(item["id"]), 0)
            self.assertEqual(len(db.list_results(item["id"])), 1)
            db.close()

    def test_list_items_puts_pending_new_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            old_clean = db.create_item({"title": "Old Clean", "query": "old clean"})
            recent_clean = db.create_item({"title": "Recent Clean", "query": "recent clean"})
            old_new = db.create_item({"title": "Old New", "query": "old new"})
            recent_new = db.create_item({"title": "Recent New", "query": "recent new"})

            db.save_results(
                old_new["id"],
                [
                    SearchResult(
                        topic_id="111",
                        title="Old New 1080p",
                        url="https://rutracker.org/forum/viewtopic.php?t=111",
                        seeders=12,
                        resolution="1080p",
                        size_bytes=8 * 1024**3,
                        size_label="8 GB",
                    )
                ],
            )
            db.save_results(
                recent_new["id"],
                [
                    SearchResult(
                        topic_id="222",
                        title="Recent New 1080p",
                        url="https://rutracker.org/forum/viewtopic.php?t=222",
                        seeders=12,
                        resolution="1080p",
                        size_bytes=8 * 1024**3,
                        size_label="8 GB",
                    )
                ],
            )
            db.conn().executemany(
                "UPDATE items SET updated_at = ? WHERE id = ?",
                [
                    ("2026-01-01 00:00:00", old_clean["id"]),
                    ("2026-01-04 00:00:00", recent_clean["id"]),
                    ("2026-01-02 00:00:00", old_new["id"]),
                    ("2026-01-03 00:00:00", recent_new["id"]),
                ],
            )
            db.conn().commit()

            self.assertEqual(
                [item["title"] for item in db.list_items()],
                ["Recent New", "Old New", "Recent Clean", "Old Clean"],
            )
            db.close()

    def test_initial_item_check_retries_transient_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"title": "Drama", "query": "Drama 2026"})

            class FlakyClient:
                def __init__(self) -> None:
                    self.calls = 0

                def search(self, query):
                    self.calls += 1
                    if self.calls < 3:
                        raise TransientRuTrackerError("RuTracker is busy")
                    return [
                        SearchResult(
                            topic_id="111",
                            title="Drama 2026 WEB-DL 1080p",
                            url="https://rutracker.org/forum/viewtopic.php?t=111",
                            seeders=10,
                            resolution="1080p",
                            size_bytes=8 * 1024**3,
                            size_label="8 GB",
                        )
                    ]

            class FakeNotifier:
                def send_new_results(self, item, rows):
                    pass

            client = FlakyClient()
            service = CheckerService(db, client, FakeNotifier())
            with patch.object(app.time, "sleep") as sleep:
                summary = service.check_new_item_with_retries(item["id"], attempts=3)

            self.assertEqual(client.calls, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(summary["attempts"], 3)
            self.assertEqual(summary["new"], 1)
            self.assertEqual(db.count_new(item["id"]), 1)
            db.close()

    def test_check_all_uses_item_retry_logic(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"title": "Drama", "query": "Drama 2026"})

            class FlakyClient:
                def __init__(self) -> None:
                    self.calls = 0

                def search(self, query):
                    self.calls += 1
                    if self.calls == 1:
                        raise TransientRuTrackerError("RuTracker is busy")
                    return [
                        SearchResult(
                            topic_id="111",
                            title="Drama 2026 WEB-DL 1080p",
                            url="https://rutracker.org/forum/viewtopic.php?t=111",
                            seeders=10,
                            resolution="1080p",
                            size_bytes=8 * 1024**3,
                            size_label="8 GB",
                        )
                    ]

            class FakeNotifier:
                def send_new_results(self, item, rows):
                    pass

            client = FlakyClient()
            service = CheckerService(db, client, FakeNotifier())
            with patch.object(app.time, "sleep") as sleep:
                summary = service.check_all(max_workers=1)

            self.assertEqual(client.calls, 2)
            self.assertEqual(sleep.call_count, 1)
            self.assertEqual(summary["items_checked"], 1)
            self.assertEqual(summary["results"][0]["attempts"], 2)
            self.assertEqual(summary["total_new"], 1)
            self.assertEqual(summary["total_pending_new_item_count"], 1)
            self.assertEqual(db.count_new(item["id"]), 1)
            db.close()

    def test_check_all_summary_counts_pending_movies_separately_from_releases(self):
        summary = app.build_check_all_summary(
            [
                {"pending_new": 2, "new": 0},
                {"pending_new": 1, "new": 0},
                {"pending_new": 0, "new": 0},
            ]
        )

        self.assertEqual(summary["total_pending_new"], 3)
        self.assertEqual(summary["total_pending_new_item_count"], 2)

    def test_background_check_all_marks_all_items_active_until_each_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            items = [
                db.create_item({"title": f"Movie {index}", "query": f"Movie {index}"})
                for index in range(3)
            ]
            release_checks = threading.Event()

            class WaitingClient:
                def search(self, query):
                    release_checks.wait(30)
                    return []

            class FakeNotifier:
                def send_new_results(self, item, rows):
                    pass

            item_checks = app.ItemCheckRegistry()
            check_all = app.CheckAllRegistry()
            with patch.object(app, "DB", db), patch.object(
                app,
                "CHECKER",
                CheckerService(db, WaitingClient(), FakeNotifier()),
            ), patch.object(app, "ITEM_CHECKS", item_checks), patch.object(
                app,
                "CHECK_ALL",
                check_all,
            ), patch.object(
                app,
                "CHECK_ALL_MAX_WORKERS",
                2,
            ):
                try:
                    self.assertTrue(app.start_background_check_all())
                    deadline = time.monotonic() + 3
                    while (
                        (len(item_checks.active_ids()) < 2 or len(item_checks.queued_ids()) != 1)
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)

                    active_ids = item_checks.active_ids()
                    queued_ids = item_checks.queued_ids()
                    self.assertEqual(len(active_ids), 2)
                    self.assertEqual(len(queued_ids), 1)
                    self.assertEqual(
                        sorted(active_ids + queued_ids),
                        sorted(item["id"] for item in items),
                    )
                finally:
                    release_checks.set()

                deadline = time.monotonic() + 3
                while check_all.is_active() and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertFalse(check_all.is_active())
                self.assertEqual(item_checks.active_ids(), [])
                self.assertEqual(item_checks.queued_ids(), [])
                summary = check_all.completed_summary()
                self.assertIsNotNone(summary)
                self.assertEqual(summary["items_checked"], 3)
            db.close()

    def test_rutracker_request_retries_read_timeout_quickly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            client = RuTrackerClient(db)

            class FakeHeaders:
                def get_content_charset(self):
                    return "utf-8"

            class FakeResponse:
                headers = FakeHeaders()

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return False

                def read(self):
                    return b"ok"

            class FakeOpener:
                def __init__(self):
                    self.calls = 0
                    self.timeouts = []

                def open(self, request, timeout):
                    self.calls += 1
                    self.timeouts.append(timeout)
                    if self.calls == 1:
                        raise TimeoutError("read timed out")
                    return FakeResponse()

            opener = FakeOpener()
            client.opener = opener

            with patch.object(app.time, "sleep") as sleep, patch.object(
                app,
                "RUTRACKER_REQUEST_TIMEOUT_SECONDS",
                2,
            ), patch.object(
                app,
                "RUTRACKER_RETRY_BASE_SECONDS",
                0,
            ):
                html = client.request("https://rutracker.org/forum/tracker.php", attempts=2)

            self.assertEqual(html, "ok")
            self.assertEqual(opener.calls, 2)
            self.assertEqual(opener.timeouts, [2, 2])
            sleep.assert_not_called()
            db.close()

    def test_pending_results_that_fail_current_filter_are_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item(
                {"query": "Iron Man 2008", "min_seeders": 5, "min_size_gb": 5, "require_1080p": True}
            )
            old_720p = SearchResult(
                topic_id="222",
                title="Iron Man BDRip 720p",
                url="https://rutracker.org/forum/viewtopic.php?t=222",
                seeders=7,
                resolution="",
                size_bytes=8 * 1024**3,
                size_label="8 GB",
            )

            db.save_results(item["id"], [old_720p])
            self.assertEqual(db.count_new(item["id"]), 1)

            cleared = db.reset_new_that_fails_filter(item["id"], 5, 5, True)

            self.assertEqual(cleared, 1)
            self.assertEqual(db.count_new(item["id"]), 0)
            db.close()

    def test_item_update_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item(
                {"query": "Drama 2025", "min_seeders": 5, "min_size_gb": 5, "require_1080p": True}
            )
            self.assertEqual(item["title"], "Drama 2025")

            updated = db.update_item(
                item["id"],
                {
                    "query": "Drama film 2025",
                    "min_seeders": 8,
                    "min_size_gb": 6.5,
                    "require_1080p": False,
                    "enabled": False,
                },
            )

            self.assertEqual(updated["title"], "Drama film 2025")
            self.assertEqual(updated["query"], "Drama film 2025")
            self.assertEqual(updated["min_seeders"], 8)
            self.assertEqual(updated["min_size_gb"], 6.5)
            self.assertEqual(updated["require_1080p"], 0)
            self.assertEqual(updated["enabled"], 0)

            db.delete_item(item["id"])
            self.assertEqual(db.list_items(), [])
            self.assertEqual(db.list_results(item["id"]), [])
            db.close()

    def test_duplicate_candidates_include_same_imdb_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            first = db.create_item(
                {
                    "query": "dark knight",
                    "imdb_url": "https://www.imdb.com/title/tt0468569/",
                }
            )
            second = db.create_item(
                {
                    "query": "The Dark Knight 2008 Christopher Nolan",
                    "imdb_url": "https://www.imdb.com/title/tt0468569/?ref_=fn_al_tt_1",
                }
            )

            candidates = db.find_duplicate_candidates(second["id"])

            self.assertEqual([candidate["item"]["id"] for candidate in candidates], [first["id"]])
            self.assertEqual(candidates[0]["score"], 1.0)
            db.close()

    def test_duplicate_candidates_ignore_empty_imdb_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            first = db.create_item({"query": "Drama 2025"})
            second = db.create_item({"query": "Comedy 2026"})

            self.assertEqual(db.find_duplicate_candidates(second["id"]), [])
            self.assertEqual(db.find_duplicate_candidates(first["id"]), [])
            db.close()

    def test_duplicate_candidates_include_similar_title_or_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            first = db.create_item({"query": "dark knight"})
            second = db.create_item({"query": "The Dark Knight 2008 Christopher Nolan"})

            candidates = db.find_duplicate_candidates(second["id"])

            self.assertEqual([candidate["item"]["id"] for candidate in candidates], [first["id"]])
            self.assertGreaterEqual(candidates[0]["score"], 0.75)
            self.assertEqual(duplicate_similarity("", ""), 0.0)
            db.close()

    def test_settings_keep_saved_secret_when_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")

            first = db.update_settings(
                {
                    "rutracker_username": "alice",
                    "rutracker_password": "secret",
                    "default_min_seeders": 7,
                    "default_min_size_gb": 6.5,
                    "default_require_1080p": False,
                    "background_enabled": False,
                    "check_interval_minutes": 30,
                    "reminder_interval_hours": 12,
                    "max_search_pages": 4,
                }
            )
            second = db.update_settings({"rutracker_password": ""})

            self.assertEqual(first["rutracker_username"], "alice")
            self.assertTrue(first["has_rutracker_password"])
            self.assertTrue(second["has_rutracker_password"])
            self.assertEqual(db.get_setting("rutracker_password"), "secret")
            self.assertEqual(db.get_setting_int("default_min_seeders", 0), 7)
            self.assertEqual(db.get_public_settings()["default_min_size_gb"], 6.5)
            self.assertFalse(db.get_public_settings()["default_require_1080p"])
            self.assertFalse(db.get_public_settings()["background_enabled"])
            self.assertEqual(db.get_public_settings()["reminder_interval_hours"], 12)
            self.assertEqual(db.get_public_settings()["max_search_pages"], 4)
            db.close()

    def test_runtime_reminder_due_now_when_interval_was_reduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            item = db.create_item({"query": "Drama 2026"})
            db.save_results(
                item["id"],
                [
                    SearchResult(
                        topic_id="111",
                        title="Drama 2026 WEB-DL 1080p",
                        url="https://rutracker.org/forum/viewtopic.php?t=111",
                        seeders=10,
                        resolution="1080p",
                        size_bytes=5_000_000_000,
                        size_label="4.66 GB",
                    )
                ],
            )
            db.set_setting("background_enabled", "1")
            db.set_setting("reminder_interval_hours", "1")
            db.set_setting(
                "last_pending_reminder_at",
                (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1, minutes=30)).isoformat(),
            )

            runtime_path = Path(tmp) / "runtime_status.json"
            with patch.object(app, "DB", db), patch.object(app, "RUNTIME_STATUS_PATH", runtime_path):
                before = dt.datetime.now(dt.timezone.utc)
                runtime = app.read_runtime_status()
                after = dt.datetime.now(dt.timezone.utc)

            next_reminder = app.parse_iso_datetime(runtime["next_reminder_at"])
            self.assertIsNotNone(next_reminder)
            self.assertGreaterEqual(next_reminder, before)
            self.assertLessEqual(next_reminder, after)
            db.close()

    def test_runtime_counts_movies_with_pending_new_separately_from_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "app.db")
            first = db.create_item({"title": "Movie A", "query": "Movie A"})
            second = db.create_item({"title": "Movie B", "query": "Movie B"})
            db.save_results(
                first["id"],
                [
                    SearchResult(
                        topic_id="111",
                        title="Movie A WEB-DL 1080p",
                        url="https://rutracker.org/forum/viewtopic.php?t=111",
                        seeders=10,
                        resolution="1080p",
                        size_bytes=5_000_000_000,
                        size_label="4.66 GB",
                    ),
                    SearchResult(
                        topic_id="112",
                        title="Movie A UHD 2160p",
                        url="https://rutracker.org/forum/viewtopic.php?t=112",
                        seeders=12,
                        resolution="2160p",
                        size_bytes=10_000_000_000,
                        size_label="9.31 GB",
                    ),
                ],
            )
            db.save_results(
                second["id"],
                [
                    SearchResult(
                        topic_id="221",
                        title="Movie B WEB-DL 1080p",
                        url="https://rutracker.org/forum/viewtopic.php?t=221",
                        seeders=8,
                        resolution="1080p",
                        size_bytes=5_000_000_000,
                        size_label="4.66 GB",
                    )
                ],
            )

            runtime_path = Path(tmp) / "runtime_status.json"
            with patch.object(app, "DB", db), patch.object(app, "RUNTIME_STATUS_PATH", runtime_path):
                runtime = app.read_runtime_status()

            self.assertEqual(runtime["pending_new_count"], 3)
            self.assertEqual(runtime["pending_new_item_count"], 2)
            db.close()

    def test_runtime_reports_startup_shortcut_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup_dir = root / "Startup"
            startup_dir.mkdir()
            target_path = root / "start_background.vbs"
            installer_path = root / "install_startup.ps1"
            target_path.write_text("' target", encoding="utf-8")
            installer_path.write_text("# installer", encoding="utf-8")
            db = Database(root / "app.db")
            db.set_setting("background_enabled", "1")

            with patch.object(app, "DB", db), patch.object(
                app,
                "RUNTIME_STATUS_PATH",
                root / "runtime_status.json",
            ), patch.object(
                app,
                "START_BACKGROUND_TARGET_PATH",
                target_path,
            ), patch.object(
                app,
                "INSTALL_STARTUP_SCRIPT_PATH",
                installer_path,
            ), patch(
                "app.get_windows_startup_dir",
                return_value=startup_dir,
            ):
                missing = app.read_runtime_status()
                (startup_dir / app.STARTUP_SHORTCUT_NAME).write_text("shortcut", encoding="utf-8")
                installed = app.read_runtime_status()

            self.assertTrue(missing["startup_supported"])
            self.assertFalse(missing["startup_installed"])
            self.assertIn("перезагрузки", missing["startup_status_message"])
            self.assertTrue(installed["startup_supported"])
            self.assertTrue(installed["startup_installed"])
            self.assertEqual(
                installed["startup_shortcut_path"],
                str(startup_dir / app.STARTUP_SHORTCUT_NAME),
            )
            db.close()

    def test_startup_install_api_runs_installer_and_returns_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            startup_dir = root / "Startup"
            startup_dir.mkdir()
            target_path = root / "start_background.vbs"
            installer_path = root / "install_startup.ps1"
            target_path.write_text("' target", encoding="utf-8")
            installer_path.write_text("# installer", encoding="utf-8")
            shortcut_path = startup_dir / app.STARTUP_SHORTCUT_NAME
            db = Database(root / "app.db")
            db.set_setting("background_enabled", "1")

            def fake_run(*args, **kwargs):
                shortcut_path.write_text("shortcut", encoding="utf-8")
                return subprocess.CompletedProcess(args[0], 0, "ok", "")

            with patch.object(app, "DB", db), patch.object(
                app,
                "RUNTIME_STATUS_PATH",
                root / "runtime_status.json",
            ), patch.object(
                app,
                "START_BACKGROUND_TARGET_PATH",
                target_path,
            ), patch.object(
                app,
                "INSTALL_STARTUP_SCRIPT_PATH",
                installer_path,
            ), patch(
                "app.get_windows_startup_dir",
                return_value=startup_dir,
            ), patch(
                "app.subprocess.run",
                side_effect=fake_run,
            ) as run_installer:
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/startup/install",
                    method="POST",
                )

                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

            self.assertEqual(response.status, 200)
            self.assertTrue(payload["installed"])
            self.assertTrue(payload["runtime"]["startup_installed"])
            self.assertTrue(shortcut_path.exists())
            run_installer.assert_called_once()

    def test_startup_install_api_returns_json_error_when_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = Database(root / "app.db")
            db.set_setting("background_enabled", "1")

            with patch.object(app, "DB", db), patch.object(
                app,
                "RUNTIME_STATUS_PATH",
                root / "runtime_status.json",
            ), patch(
                "app.get_windows_startup_dir",
                return_value=None,
            ), patch(
                "app.subprocess.run",
                side_effect=AssertionError("installer must not run"),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/startup/install",
                    method="POST",
                )

                try:
                    with self.assertRaises(urllib.error.HTTPError) as context:
                        urllib.request.urlopen(request, timeout=5)
                    body = json.loads(context.exception.read().decode("utf-8"))
                finally:
                    server.shutdown()
                    server.server_close()
                    db.close()

            self.assertEqual(context.exception.code, 502)
            self.assertIn("error", body)
            self.assertIn("runtime", body)
            self.assertFalse(body["runtime"]["startup_supported"])


if __name__ == "__main__":
    unittest.main()
