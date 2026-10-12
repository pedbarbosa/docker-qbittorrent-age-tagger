# Tags qBittorrent torrents by age, see README.md
FROM python:3.14-slim
LABEL org.opencontainers.image.authors="Pedro Barbosa, https://github.com/pedbarbosa"

COPY requirements.txt /tmp/requirements.txt

# For the build only, so apt doesn't try to prompt
ARG DEBIAN_FRONTEND=noninteractive

RUN \
    echo "**** update and upgrade packages ****" && \
    apt-get update --error-on=any && apt-get upgrade -y && \
    echo "**** install tzdata ****" && \
    apt-get install -y --no-install-recommends tzdata && \
    echo "**** install Python dependencies ****" && \
    pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt && \
    echo "**** create the tagger user ****" && \
    useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin tagger && \
    echo "**** clean up ****" && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

COPY src/tagger.py /app/tagger.py

ENV QB_URL=http://127.0.0.1:8090

USER tagger

# Healthy while the loop keeps completing cycles, see README.md
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "/app/tagger.py", "healthcheck"]

CMD ["python", "-u", "/app/tagger.py"]
