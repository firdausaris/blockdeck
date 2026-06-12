FROM alpine:3.21

RUN apk add --no-cache restic openssh-client bash tzdata

COPY entrypoint.sh /usr/local/bin/entrypoint
COPY offsite-backup.sh /usr/local/bin/offsite-backup
RUN chmod +x /usr/local/bin/entrypoint /usr/local/bin/offsite-backup

ENV RESTIC_CACHE_DIR=/cache

ENTRYPOINT ["/usr/local/bin/entrypoint"]
