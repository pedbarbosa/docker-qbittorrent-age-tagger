# qbittorrent-age-tagger

## qBittorrent age tagger on a Docker container

This repository contains a Dockerfile to build a Docker image that tags qBittorrent torrents by age. Every hour it adds the `older-than-15-days` tag to torrents added more than 15 days ago, and removes it from any newer torrent that has it.

It talks to the qBittorrent WebUI API with the API key from qBittorrent's config file (`WebUI\APIKey`), so it needs read access to `qBittorrent.conf`.

The Docker image is available in [Docker Hub](https://hub.docker.com/r/pedbarbosa/qbittorrent-age-tagger/).

### Docker compose usage example

Sharing the network of the container qBittorrent's WebUI listens in, here gluetun's:

```
services:
  qbittorrent-age-tagger:
    image: pedbarbosa/qbittorrent-age-tagger
    container_name: qbittorrent-age-tagger
    network_mode: service:gluetun
    depends_on:
      qbittorrent:
        condition: service_healthy
        restart: true
    environment:
      QB_URL: "http://127.0.0.1:8090"
      TZ: Australia/Brisbane
    volumes:
      - /path/to/qBittorrent/qBittorrent.conf:/run/secrets/qbit.conf:ro
    restart: unless-stopped
```

The image runs as user `1000`. If that user can't read `qBittorrent.conf`, run it as the user qBittorrent runs as, for example `user: "${PUID}:${PGID}"`.

### Settings

| Variable | Default | |
|---|---|---|
| `QB_URL` | `http://127.0.0.1:8090` | qBittorrent WebUI address |
| `QB_CONFIG_FILE` | `/run/secrets/qbit.conf` | qBittorrent config file holding `WebUI\APIKey` |
| `AGE_DAYS` | `15` | Age at which torrents are tagged |
| `AGE_TAG` | `older-than-<AGE_DAYS>-days` | Tag to add and remove |
| `CHECK_INTERVAL` | `3600` | Seconds between checks |
| `TZ` | UTC | Time zone for log timestamps |

The API key is read again on every check, so a new key is picked up without a restart.

### Healthcheck

After every check, successful or not, the tagger writes a heartbeat file. The container is healthy while the heartbeat is no older than `CHECK_INTERVAL` plus two minutes, so it turns unhealthy if the loop stops or hangs.

A failed check, with qBittorrent down or the API key missing, doesn't make it unhealthy: it's logged as an `ERROR` and retried at the next check. qBittorrent's own health is covered by `depends_on`.

### Building and testing

`./rebuild` builds, tests and publishes the image with [docker-image-refresh](https://gist.github.com/pedbarbosa/5a6ea23c8bcaf90f063eb0a082277d79), which runs `./test <image>` and the image's healthcheck before tagging it `latest`.

`./test` runs the unit tests in `tests/` inside the image, then starts the tagger alongside a fake qBittorrent API (`tests/fake_qbittorrent.py`) sharing its network, as with gluetun, and checks the tags it ends up with, its healthcheck and its shutdown. To run the unit tests outside Docker:

```
TAGGER_DIR=src python -m unittest discover tests
```
