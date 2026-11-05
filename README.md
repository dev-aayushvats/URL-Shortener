# URL Shortener Service

Internship Assignment for LOBB

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.8+

### Installation

**Option A: everything in Docker (simplest)**

```bash
git clone https://github.com/dev-aayushvats/URL-Shortener.git && cd URL-Shortener
docker compose up -d --build     # API + Postgres + Redis; migrations run on startup
```

**Option B: local development with auto-reload**

```bash
python3 -m venv venv && source venv/bin/activate      # Windows: venv\\Scripts\\activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d postgres redis
alembic upgrade head                                  # apply DB migrations
fastapi dev app/main.py
```

Open http://localhost:8000 (UI) or http://localhost:8000/docs (interactive API docs).

### Tests and lint

```bash
pytest        # fast tests: in-memory SQLite + fake cache, no Docker (integration tests skip)
# Full suite incl. concurrency + migration tests on real Postgres: see TESTING.md
ruff check . && ruff format --check .
```

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
  "short_url": "http://localhost:8000/AbCdEf12"
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
- **Redis**: In-memory caching for URLs which are frequently requested. Cached items expire after 24 hours.
- **Docker**: Running the Postgres and Redis instances in docker containers for easy and quick access.

## Database Schema

The `urls` table stores mappings between short codes and target URLs:

| Column      | Type      | Description                       |
|-------------|-----------|-----------------------------------|
| url_id      | String    | Primary key, unique short code    |
| target_url  | String    | Original URL to redirect to       |
| created_at  | DateTime  | Timestamp when URL was shortened  |

## Design notes

- **Idempotent creation under concurrency:** `target_hash` (SHA-256 of the URL) has a `UNIQUE` constraint, and the short code is the primary key. The service inserts first and handles `IntegrityError`, rather than check-then-insert (which races).
- **Short codes:** 8 random base62 chars from `secrets` (~218 trillion combinations); collisions are caught by the DB and retried.
- **Cache-aside:** Redis is consulted first; any Redis failure degrades to a cache miss instead of an error.
- **302 redirects** so browsers don't permanently cache the mapping (keeps expiry/analytics possible).
- **Config** via environment variables (`pydantic-settings`); `.env` is git-ignored, `.env.example` is committed.
- **Aliases and expiry:** default links are deduplicated (same URL, same code). Custom/expiring links always create a new mapping, so `target_hash` is only set for default links (NULL otherwise; the UNIQUE constraint ignores NULLs).
- **Expiry is enforced in the cache too:** cached entries get `min(24h, remaining lifetime)` as TTL, so an expired link can never be served from Redis.
- **Rate limiting:** fixed-window counter in Redis (`INCR` + `EXPIRE NX` in one transaction), per client IP, on `POST /shorten` only. It fails open if Redis is down. Behind a proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>`. Fixed windows allow up to 2x bursts at window edges; a sliding window or token bucket would be the upgrade.
- Settings: `RATE_LIMIT_PER_MINUTE`, `MIN_EXPIRY_SECONDS`, `MAX_EXPIRY_SECONDS` (env vars).
- **Measured:** ~910 req/s on one worker and ~1,250 req/s on four (95% redirects / 5% creates, laptop); the Redis cache gave +64% redirect throughput and halved p95 latency vs. no cache. See [docs/LOAD_TEST.md](docs/LOAD_TEST.md) for method and caveats.
