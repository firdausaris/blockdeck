FROM alpine:3.21

RUN apk add --no-cache bash curl unzip tzdata icu-libs libstdc++ libgcc

# uNmINeD CLI (musl build for Alpine) — renders Bedrock worlds to web maps
RUN mkdir -p /opt/unmined \
    && curl -fsSL "https://unmined.net/download/unmined-cli-linux-musl-x64-dev/" -o /tmp/unmined.tgz \
    && tar -xzf /tmp/unmined.tgz -C /opt/unmined --strip-components=1 \
    && rm /tmp/unmined.tgz \
    && chmod +x /opt/unmined/unmined-cli

COPY entrypoint.sh /usr/local/bin/entrypoint
COPY render-map.sh /usr/local/bin/render-map
RUN chmod +x /usr/local/bin/entrypoint /usr/local/bin/render-map

ENTRYPOINT ["/usr/local/bin/entrypoint"]
