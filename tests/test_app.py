import tempfile
import unittest
import datetime as dt
from pathlib import Path

from check_once import build_notification
from app import (
    Database,
    RuTrackerClient,
    SearchResult,
    filter_results,
    parse_rutracker_results,
    parse_next_page_url,
    parse_resolution,
    quote_rutracker_query,
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


class DatabaseTests(unittest.TestCase):
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
            self.assertEqual(db.get_public_settings()["reminder_interval_hours"], 12)
            self.assertEqual(db.get_public_settings()["max_search_pages"], 4)
            db.close()


if __name__ == "__main__":
    unittest.main()
