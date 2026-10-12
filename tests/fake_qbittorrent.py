#!/usr/bin/env python3
"""A fake qBittorrent WebUI API for './test', serving the endpoints the
tagger uses. Torrents are kept in memory, and GET /state returns them along
with any rejected requests, for the test to check.

Usage: FAKE_API_KEY=<key> python fake_qbittorrent.py [port]
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DAY = 24 * 60 * 60
NOW = int(time.time())
API_KEY = os.environ["FAKE_API_KEY"]
TAG = os.environ.get("FAKE_TAG", "older-than-15-days")

TORRENTS = {
    "old": {"added_on": NOW - 20 * DAY, "tags": []},
    "old-tagged": {"added_on": NOW - 20 * DAY, "tags": ["movies", TAG]},
    "new": {"added_on": NOW - 1 * DAY, "tags": ["tv"]},
    "new-tagged": {"added_on": NOW - 1 * DAY, "tags": [TAG, "tv"]},
}
REJECTED = []


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Authorization") == f"Bearer {API_KEY}":
            return True
        REJECTED.append(f"{self.command} {self.path}")
        self.send_json({"error": "Unauthorized"}, status=401)
        return False

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/state":
            self.send_json({"torrents": TORRENTS, "rejected": REJECTED})
        elif url.path == "/api/v2/torrents/info":
            if self.authorized():
                self.send_json([
                    {"hash": h, "added_on": t["added_on"], "tags": ", ".join(t["tags"])}
                    for h, t in TORRENTS.items()
                ])
        else:
            self.send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path not in ("/api/v2/torrents/addTags", "/api/v2/torrents/removeTags"):
            self.send_json({"error": "Not found"}, status=404)
            return
        if not self.authorized():
            return

        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        tags = [t.strip() for t in form["tags"][0].split(",")]
        for torrent_hash in form["hashes"][0].split("|"):
            torrent = TORRENTS[torrent_hash]
            if url.path.endswith("addTags"):
                torrent["tags"] += [t for t in tags if t not in torrent["tags"]]
            else:
                torrent["tags"] = [t for t in torrent["tags"] if t not in tags]

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
