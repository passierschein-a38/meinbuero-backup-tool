# Firebird 3 reads the gbak formats written by Firebird 2.x (Mein Buero up to 2019).
FROM debian:bookworm-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        firebird3.0-server firebird3.0-utils python3 python3-pip sqlite3 \
 && pip3 install --no-cache-dir --break-system-packages fdb datasette \
 && rm -rf /var/lib/apt/lists/*

COPY mbtool.py /usr/local/bin/mbtool
RUN chmod +x /usr/local/bin/mbtool

VOLUME ["/out"]
EXPOSE 8001
ENTRYPOINT ["mbtool"]
CMD ["--help"]
