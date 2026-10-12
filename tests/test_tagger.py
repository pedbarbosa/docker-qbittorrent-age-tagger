"""Unit tests for tagger.py, run by './test' inside the image.

Locally: TAGGER_DIR=src python -m unittest discover tests
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.environ.get("TAGGER_DIR", "/app"))

import requests  # noqa: E402

import tagger  # noqa: E402

DAY = 24 * 60 * 60
NOW = 1_800_000_000


class ReadApiKeyTest(unittest.TestCase):
    def write_config(self, content, encoding="utf-8"):
        f = tempfile.NamedTemporaryFile("w", encoding=encoding, suffix=".conf", delete=False)
        self.addCleanup(os.remove, f.name)
        with f:
            f.write(content)
        return f.name

    def test_reads_key(self):
        path = self.write_config("[Preferences]\nWebUI\\Port=8090\nWebUI\\APIKey=abc123\n")
        self.assertEqual(tagger.read_api_key(path), "abc123")

    def test_strips_whitespace(self):
        path = self.write_config("WebUI\\APIKey = abc123 \r\n")
        self.assertEqual(tagger.read_api_key(path), "abc123")

    def test_reads_key_after_byte_order_mark(self):
        path = self.write_config("WebUI\\APIKey=abc123\n", encoding="utf-8-sig")
        self.assertEqual(tagger.read_api_key(path), "abc123")

    def test_ignores_similar_keys(self):
        path = self.write_config("WebUI\\APIKeyOld=old\nWebUI\\APIKey=abc123\n")
        self.assertEqual(tagger.read_api_key(path), "abc123")

    def test_empty_key(self):
        path = self.write_config("WebUI\\APIKey=\n")
        with self.assertRaisesRegex(tagger.ConfigError, "empty"):
            tagger.read_api_key(path)

    def test_missing_key(self):
        path = self.write_config("[Preferences]\nWebUI\\Port=8090\n")
        with self.assertRaisesRegex(tagger.ConfigError, "not found"):
            tagger.read_api_key(path)

    def test_missing_file(self):
        with self.assertRaisesRegex(tagger.ConfigError, "Cannot read"):
            tagger.read_api_key("/nonexistent/qbit.conf")


def torrent(torrent_hash, age_days, tags=""):
    added_on = NOW - int(age_days * DAY) if age_days is not None else 0
    return {"hash": torrent_hash, "added_on": added_on, "tags": tags}


class PlanTagsTest(unittest.TestCase):
    def plan(self, *torrents):
        return tagger.plan_tags(list(torrents), NOW)

    def test_tags_old_torrent(self):
        self.assertEqual(self.plan(torrent("a", 20)), (["a"], []))

    def test_leaves_tagged_old_torrent(self):
        self.assertEqual(self.plan(torrent("a", 20, tagger.TAG)), ([], []))

    def test_untags_new_torrent(self):
        self.assertEqual(self.plan(torrent("a", 1, tagger.TAG)), ([], ["a"]))

    def test_leaves_untagged_new_torrent(self):
        self.assertEqual(self.plan(torrent("a", 1)), ([], []))

    def test_torrent_exactly_at_threshold_is_old(self):
        self.assertEqual(self.plan(torrent("a", tagger.AGE_DAYS)), (["a"], []))

    def test_torrent_just_under_threshold_is_new(self):
        self.assertEqual(self.plan(torrent("a", tagger.AGE_DAYS - 1 / DAY)), ([], []))

    def test_unknown_added_on_is_new(self):
        self.assertEqual(self.plan(torrent("a", None, tagger.TAG)), ([], ["a"]))

    def test_finds_tag_among_others(self):
        tags = f"movies, {tagger.TAG} ,keep"
        self.assertEqual(self.plan(torrent("a", 20, tags), torrent("b", 1, tags)), ([], ["b"]))

    def test_does_not_match_partial_tag(self):
        self.assertEqual(self.plan(torrent("a", 20, f"{tagger.TAG}-old")), (["a"], []))

    def test_missing_tags_field(self):
        self.assertEqual(self.plan({"hash": "a", "added_on": NOW - 20 * DAY}), (["a"], []))

    def test_mixed(self):
        plan = self.plan(
            torrent("old", 30),
            torrent("old-tagged", 30, tagger.TAG),
            torrent("new", 2),
            torrent("new-tagged", 2, tagger.TAG),
        )
        self.assertEqual(plan, (["old"], ["new-tagged"]))


class FakeResponse:
    def __init__(self, json_data=None, status=200):
        self.json_data = json_data
        self.status = status

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")


class FakeSession:
    def __init__(self, torrents, post_status=200):
        self.torrents = torrents
        self.post_status = post_status
        self.posts = []

    def get(self, url, params=None, timeout=None):
        self.get_call = (url, params)
        return FakeResponse(self.torrents)

    def post(self, url, data=None, timeout=None):
        self.posts.append((url.rsplit("/", 1)[-1], data))
        return FakeResponse(status=self.post_status)


class SyncTagsTest(unittest.TestCase):
    def test_adds_and_removes_tags(self):
        now = time.time()
        session = FakeSession([
            {"hash": "old1", "added_on": int(now - 20 * DAY), "tags": ""},
            {"hash": "old2", "added_on": int(now - 30 * DAY), "tags": "movies"},
            {"hash": "new", "added_on": int(now - DAY), "tags": tagger.TAG},
        ])
        tagger.sync_tags(session)

        self.assertEqual(session.get_call, (f"{tagger.QB_URL}/api/v2/torrents/info", {"filter": "all"}))
        self.assertEqual(session.posts, [
            ("addTags", {"hashes": "old1|old2", "tags": tagger.TAG}),
            ("removeTags", {"hashes": "new", "tags": tagger.TAG}),
        ])

    def test_no_requests_when_nothing_changes(self):
        session = FakeSession([{"hash": "new", "added_on": int(time.time()), "tags": ""}])
        tagger.sync_tags(session)
        self.assertEqual(session.posts, [])

    def test_raises_on_failed_request(self):
        session = FakeSession([{"hash": "old", "added_on": 1, "tags": ""}], post_status=403)
        with self.assertRaises(requests.HTTPError):
            tagger.sync_tags(session)


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.heartbeat = os.path.join(directory.name, "heartbeat")

    def test_healthy_after_heartbeat(self):
        tagger.write_heartbeat(self.heartbeat)
        self.assertEqual(tagger.healthcheck(self.heartbeat, max_age=60), 0)

    def test_unhealthy_without_heartbeat(self):
        self.assertEqual(tagger.healthcheck(self.heartbeat, max_age=60), 1)

    def test_unhealthy_with_stale_heartbeat(self):
        tagger.write_heartbeat(self.heartbeat)
        stale = time.time() - 120
        os.utime(self.heartbeat, (stale, stale))
        self.assertEqual(tagger.healthcheck(self.heartbeat, max_age=60), 1)

    def test_max_age_allows_for_a_full_cycle(self):
        self.assertGreater(tagger.HEARTBEAT_MAX_AGE, tagger.CHECK_INTERVAL + 3 * 30)


if __name__ == "__main__":
    unittest.main()
