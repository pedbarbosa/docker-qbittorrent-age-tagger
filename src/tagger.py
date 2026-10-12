#!/usr/bin/env python3
"""Tag qBittorrent torrents older than a set age, and untag newer ones."""

import logging
import os
import signal
import sys
import threading
import time

import requests

QB_URL = os.environ.get("QB_URL", "http://127.0.0.1:8090").rstrip("/")
CONFIG_FILE = os.environ.get("QB_CONFIG_FILE", "/run/secrets/qbit.conf")
HEARTBEAT_FILE = os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat")

AGE_DAYS = int(os.environ.get("AGE_DAYS", "15"))
AGE_SECONDS = AGE_DAYS * 24 * 60 * 60
TAG = os.environ.get("AGE_TAG", f"older-than-{AGE_DAYS}-days")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "3600"))  # One hour

# A cycle makes up to three API requests with a 30 second timeout each, so a
# heartbeat older than this means the loop has stopped
HEARTBEAT_MAX_AGE = CHECK_INTERVAL + 120


class ConfigError(Exception):
    """The API key can't be read from qBittorrent's config file."""


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

                    raise ConfigError(f"WebUI\\APIKey is empty in {config_file}")

    except OSError as exc:
        raise ConfigError(
            f"Cannot read qBittorrent config file: {config_file} ({exc.strerror})"
        ) from exc

    raise ConfigError(
        f"WebUI\\APIKey not found in {config_file}"
    )


def plan_tags(torrents, now):
    """Return the hashes of the torrents to tag and to untag."""
    cutoff = int(now) - AGE_SECONDS
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

    return to_add, to_remove


def sync_tags(session):
    """Synchronize the age tag across all torrents."""
    response = session.get(
        f"{QB_URL}/api/v2/torrents/info",
        params={"filter": "all"},
        timeout=30,
    )
    response.raise_for_status()
    torrents = response.json()

    to_add, to_remove = plan_tags(torrents, time.time())

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


def write_heartbeat(heartbeat_file=HEARTBEAT_FILE):
    """Record that the loop completed a cycle, for the healthcheck."""
    try:
        with open(heartbeat_file, "w", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\n")
    except OSError:
        logging.exception("Cannot write heartbeat file %s", heartbeat_file)


def healthcheck(heartbeat_file=HEARTBEAT_FILE, max_age=HEARTBEAT_MAX_AGE):
    """Return 0 when the loop has completed a cycle recently, 1 otherwise."""
    try:
        age = time.time() - os.path.getmtime(heartbeat_file)
    except OSError:
        print(f"No heartbeat at {heartbeat_file} yet")
        return 1

    if age > max_age:
        print(f"Last heartbeat was {age:.0f}s ago, more than {max_age}s")
        return 1

    print(f"Last heartbeat was {age:.0f}s ago")
    return 0


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Running as PID 1, SIGTERM is ignored unless handled, so 'docker stop'
    # would wait for its timeout and kill the container
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    logging.info("qBittorrent age tagger started")
    logging.info("Target tag: %s", TAG)
    logging.info("Age threshold: %d days", AGE_DAYS)
    logging.info("Checking %s every %d seconds", QB_URL, CHECK_INTERVAL)

    session = requests.Session()

    while not stop.is_set():
        try:
            # Read on every cycle, so a new API key is picked up without a restart
            session.headers["Authorization"] = f"Bearer {read_api_key(CONFIG_FILE)}"
            sync_tags(session)
        except ConfigError as exc:
            logging.error("%s", exc)
        except requests.RequestException:
            logging.exception("qBittorrent API request failed")
        except Exception:
            logging.exception("Tag synchronization failed")

        write_heartbeat()
        stop.wait(CHECK_INTERVAL)

    logging.info("qBittorrent age tagger stopped")


if __name__ == "__main__":
    if sys.argv[1:] == ["healthcheck"]:
        sys.exit(healthcheck())
    main()
