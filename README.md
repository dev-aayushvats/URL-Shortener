# URL Shortener Service

Internship Assignment for LOBB

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (only needed for local development; the Docker image bundles 3.12)

### Installation

**Option A: everything in Docker (simplest)**

```bash
git clone https://github.com/dev-aayushvats/URL-Shortener.git && cd URL-Shortener
docker compose up -d --build     # API + Postgres + Redis; migrations run on startup
```

**Option B: local development with auto-reload**

```bash
python3 -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d postgres redis
alembic upgrade head                                  # apply DB migrations
fastapi dev app/main.py
```

Open http://localhost:8000 (UI) or http://localhost:8000/docs (interactive API docs).

### Tests and lint

```bash
pytest        # 35 fast tests: in-memory SQLite + fake cache, no Docker (integration tests skip)
ruff check . && ruff format --check .
```

The full suite (55 tests) also runs concurrency, migration, Redis, live-HTTP and browser tests
against real Postgres and Redis. Set `TEST_DATABASE_URL` and `TEST_REDIS_URL`, run
`playwright install chromium` once, then `pytest`. Exact commands are in [TESTING.md](TESTING.md).

Full test and verification report: [TESTING.md](TESTING.md). Load test results and how to reproduce them: [docs/LOAD_TEST.md](docs/LOAD_TEST.md).

CI (GitHub Actions) runs lint, tests and a Docker build on every push and PR.

Changing the schema: edit `app/models.py`, then `alembic revision --autogenerate -m "describe change"` and `alembic upgrade head`.

## Usage

### Web Interface

The URL shortener includes a user-friendly web interface. To use it:

1. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

2. Enter the URL you want to shorten in the input field
3. Click the "Shorten URL" button
4. The result will show both the JSON response and a clickable short URL link

### API Usage

The URL shortener provides the following REST API endpoints:

| Endpoint | Method | Description | Request Body | Response |
|----------|--------|-------------|--------------|----------|
| `/` | GET | HTML interface for the URL shortener | None | HTML page |
| `/shorten` | POST | Create a short URL (rate limited: 10/min per IP) | `{"target_url": "...", "custom_alias": "optional", "expires_in_seconds": 3600}` | JSON with short code, URL, `expires_at` |
| `/{short_code}` | GET | Redirect to original URL | None | HTTP redirect to target URL |

#### Create a Short URL

**Endpoint:** `/shorten`  
**Method:** POST  
**Content-Type:** application/json

Request Body:
```json
{
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened"
}
```

Response (200 OK):
```json
{
  "short_code": "AbCdEf12",
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened",
  "short_url": "http://localhost:8000/AbCdEf12",
  "expires_at": null
}
```

Example with curl:
```bash
curl -X 'POST' \
  'http://localhost:8000/shorten' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "target_url": "https://example.com/very/long/url/that/needs/to/be/shortened"
}'
```

#### Custom alias and expiry (both optional)

```bash
curl -X POST localhost:8000/shorten -H 'Content-Type: application/json' \
  -d '{"target_url": "https://example.com/x", "custom_alias": "my-link", "expires_in_seconds": 86400}'
```

| Status | Meaning |
|---|---|
| 409 | Alias already taken |
| 422 | Invalid/reserved alias, or expiry outside 60s - 1 year |
| 429 | Rate limit exceeded (see `Retry-After` header) |
| 410 | (on redirect) link has expired |

#### Use a Short URL

**Endpoint:** `/{short_code}`  
**Method:** GET  
**Response:** HTTP 302 redirect (404 if unknown) to the original URL

Simply visit the short URL in your browser:
```
http://localhost:8000/AbCdEf12
```

Or use curl:
```bash
curl -L 'http://localhost:8000/AbCdEf12'
```

## Architecture

- **FastAPI**: Modern, fast web framework for building APIs
- **PostgreSQL**: Persistent storage for URL mappings
- **Redis**: Cache-aside store for redirects (24 h TTL, never longer than a link's remaining lifetime) and the rate-limit counters.
- **Alembic**: Versioned schema migrations (applied automatically when the container starts).
- **Docker Compose**: Runs the API, Postgres and Redis together, with healthchecks.
- **Tooling**: pytest, Playwright, Locust, ruff, GitHub Actions (see [TESTING.md](TESTING.md)).

Code layout: `app/main.py` (routes), `services.py` (create/dedupe logic), `cache.py`, `ratelimit.py`, `middleware.py` + `logging_config.py` (request logging), `models.py`, `schemas.py`, `config.py`; `migrations/`, `tests/`, `loadtest/`.

## Database Schema

The `urls` table stores mappings between short codes and target URLs:

| Column       | Type         | Description                                                                 |
|--------------|--------------|-----------------------------------------------------------------------------|
| short_code   | String(32)   | Primary key: random base62 code (8 chars) or a custom alias                  |
| target_url   | Text         | Original URL to redirect to                                                 |
| target_hash  | String(64)   | SHA-256 of `target_url`; `UNIQUE`, set only for default links (else NULL)    |
| expires_at   | DateTime (tz)| Optional expiry; NULL means never                                           |
| created_at   | DateTime (tz)| Timestamp when the URL was shortened                                        |

## Configuration

All settings are environment variables (or a `.env` file; see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Prefix used when building `short_url` |
| `DATABASE_URL` | local Postgres | SQLAlchemy URL (`postgresql+psycopg://...`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache and rate-limit store |
| `CACHE_ENABLED` | `true` | `false` disables the Redis cache (used to benchmark) |
| `CACHE_TTL_SECONDS` | `86400` | Default cache lifetime |
| `SHORT_CODE_LENGTH` | `8` | Length of generated codes |
| `RATE_LIMIT_PER_MINUTE` | `10` | `POST /shorten` limit per client IP |
| `MIN_EXPIRY_SECONDS` / `MAX_EXPIRY_SECONDS` | `60` / 1 year | Allowed `expires_in_seconds` range |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | Logging (`json` or `text`); `WARNING` turns off per-request access logs |
| `WEB_CONCURRENCY` | `1` | Number of uvicorn worker processes (read by uvicorn) |

## Design notes

- **Idempotent creation under concurrency:** `target_hash` (SHA-256 of the URL) has a `UNIQUE` constraint, and the short code is the primary key. The service inserts first and handles `IntegrityError`, rather than check-then-insert (which races).
- **Short codes:** 8 random base62 chars from `secrets` (~218 trillion combinations); collisions are caught by the DB and retried.
- **Cache-aside:** Redis is consulted first; any Redis failure degrades to a cache miss instead of an error.
- **302 redirects** so browsers don't permanently cache the mapping (keeps expiry/analytics possible).
- **Config** via environment variables (`pydantic-settings`); `.env` is git-ignored, `.env.example` is committed.
- **Aliases and expiry:** default links are deduplicated (same URL, same code). Custom/expiring links always create a new mapping, so `target_hash` is only set for default links (NULL otherwise; the UNIQUE constraint ignores NULLs).
- **Expiry is enforced in the cache too:** cached entries get `min(24h, remaining lifetime)` as TTL, so an expired link can never be served from Redis.
- **Rate limiting:** fixed-window counter in Redis (`INCR` + `EXPIRE NX` in one transaction), per client IP, on `POST /shorten` only. It fails open if Redis is down. Behind a proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>`. Fixed windows allow up to 2x bursts at window edges; a sliding window or token bucket would be the upgrade.
- **Measured** (95% redirects / 5% creates, 50 concurrent users, laptop): about 620-910 req/s on one worker and 700-1,250 on four, depending on session and whether access logging is on; the Redis cache gave roughly +50-65% redirect throughput and 35-50% lower p95 latency vs. no cache. Absolute numbers vary between sessions, so see [docs/LOAD_TEST.md](docs/LOAD_TEST.md) for method, both result sets and caveats.
- **Observability:** JSON logs (one line per request with `request_id`, status, duration) and an `X-Request-ID` header for tracing. `LOG_LEVEL` and `LOG_FORMAT` (`json`/`text`) are configurable.
