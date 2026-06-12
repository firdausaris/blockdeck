FROM alpine:3.21

RUN apk add --no-cache bash curl jq docker-cli coreutils tzdata

COPY entrypoint.sh /usr/local/bin/entrypoint
COPY check-update.sh /usr/local/bin/check-update
RUN chmod +x /usr/local/bin/entrypoint /usr/local/bin/check-update

ENTRYPOINT ["/usr/local/bin/entrypoint"]
