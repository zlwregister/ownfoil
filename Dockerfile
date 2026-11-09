FROM python:3.14-alpine@sha256:a18b20ad69e74df6cf6d2e1b1a260d7a1ecf5380fd83b310f83ba88c461cf894
LABEL org.opencontainers.image.source="https://github.com/zlwregister/ownfoil" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Install platform-specific build dependencies
ARG TARGETPLATFORM
RUN if [ "$TARGETPLATFORM" = "linux/arm/v6" ] || [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then \
        apk add --no-cache build-base gcc musl-dev jpeg-dev zlib-dev libffi-dev cairo-dev pango-dev gdk-pixbuf-dev; \
    fi

COPY requirements.lock /tmp/
RUN pip install --no-cache-dir --require-hashes --requirement /tmp/requirements.lock && rm /tmp/requirements.lock
RUN if [ "$TARGETPLATFORM" = "linux/arm/v6" ] || [ "$TARGETPLATFORM" = "linux/arm/v7" ]; then \
        apk del build-base gcc musl-dev jpeg-dev zlib-dev libffi-dev cairo-dev pango-dev gdk-pixbuf-dev; \
    fi

RUN mkdir /app
COPY ./app /app
COPY ./docker/run.sh /app/run.sh

RUN mkdir -p /app/data

# Override --user UID:GID for a dedicated NAS account; no runtime chown/root.
RUN addgroup -g 1000 -S ownfoil && adduser -u 1000 -G ownfoil -S ownfoil \
    && mkdir -p /app/config \
    && chown -R 1000:1000 /app \
    && chmod 755 /app/run.sh
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 1000:1000

WORKDIR /app

ENTRYPOINT [ "/app/run.sh" ]

