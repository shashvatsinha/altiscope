FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY prompts ./prompts
COPY migrations ./migrations
RUN uv pip install --system --no-cache .
USER 65532:65532
ENTRYPOINT ["altiscope"]
CMD ["--help"]
