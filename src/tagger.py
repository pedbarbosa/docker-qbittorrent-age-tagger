#!/usr/bin/env python3

import os
import time
import logging
import requests

QB_URL = os.environ["QB_URL"].rstrip("/")
CONFIG_FILE = "/run/secrets/qbit.conf"

TAG = "older-than-15-days"
AGE_SECONDS = 15 * 24 * 60 * 60
CHECK_INTERVAL = 3600  # One hour


def read_api_key(config_file):
    """Read the WebUI API key from qBittorrent's config file."""
    try:
        with open(config_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                key, separator, value = line.partition("=")
                if separator and key.strip() == r"WebUI\APIKey":
                    api_key = value.strip()

                    if api_key:
                        return api_key

                    raise ValueError("WebUI API key is empty")

    except OSError as exc:
        raise RuntimeError(
            f"Cannot read qBittorrent config file: {config_file}"
        ) from exc

    raise RuntimeError(
        f"WebUI\\APIKey not found in {config_file}"
    )


QB_API_KEY = read_api_key(CONFIG_FILE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {QB_API_KEY}"
})


def sync_tags():
    """Synchronize the age tag across all torrents."""
    response = session.get(
        f"{QB_URL}/api/v2/torrents/info",
        params={"filter": "all"},
        timeout=30,
    )
    response.raise_for_status()
    torrents = response.json()

    cutoff = int(time.time()) - AGE_SECONDS
    to_add = []
    to_remove = []

    for torrent in torrents:
        torrent_hash = torrent["hash"]
        tags = {
            tag.strip()
            for tag in torrent.get("tags", "").split(",")
            if tag.strip()
        }

        added_on = int(torrent.get("added_on", 0))
        is_old = added_on > 0 and added_on <= cutoff
        has_tag = TAG in tags

        if is_old and not has_tag:
            to_add.append(torrent_hash)
        elif not is_old and has_tag:
            to_remove.append(torrent_hash)

    if to_add:
        response = session.post(
            f"{QB_URL}/api/v2/torrents/addTags",
            data={
                "hashes": "|".join(to_add),
                "tags": TAG,
            },
            timeout=30,
        )
        response.raise_for_status()

    if to_remove:
        response = session.post(
            f"{QB_URL}/api/v2/torrents/removeTags",
            data={
                "hashes": "|".join(to_remove),
                "tags": TAG,
            },
            timeout=30,
        )
        response.raise_for_status()

    logging.info(
        "Checked %d torrents; added tag to %d, removed from %d",
        len(torrents),
        len(to_add),
        len(to_remove),
    )


def main():
    logging.info("qBittorrent age tagger started")
    logging.info("Target tag: %s", TAG)
    logging.info("Age threshold: 14 days")

    while True:
        try:
            sync_tags()
        except requests.RequestException:
            logging.exception("qBittorrent API request failed")
        except Exception:
            logging.exception("Tag synchronization failed")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

