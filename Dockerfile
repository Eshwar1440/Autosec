# syntax=docker/dockerfile:1

# Build stage: official Python 3.13 on Debian 13, same minor version as the runtime.
FROM python:3.13-slim@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1 AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .

RUN pip install --no-compile --target /deps -r requirements.txt

# Runtime stage: distroless, so no shell, no apt, no perl, no util-linux, no ncurses.
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:c3ed2b61f3c4e410685565ceb3c818197b552832521b39d53eca5d2d9d0dc1e1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/deps
COPY --from=builder /deps /deps
WORKDIR /srv
COPY --chown=root:root app ./app
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/usr/bin/python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
ENTRYPOINT ["/usr/bin/python3"]
CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
