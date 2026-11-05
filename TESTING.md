# Testing and Verification Report

This document records every kind of check performed on the project, what each one **means**, what it **measures**, which **tool** was used, and what the **outcome** was. All results are from runs on 5 Nov 2026 on a MacBook (Apple M1, 8 cores) with Docker Desktop (4 CPUs, ~5 GB).

## Summary

| # | Check | Tool | What it proves | Outcome |
|---|---|---|---|---|
| 1 | Automated unit/integration tests | pytest + FastAPI TestClient | Application logic behaves correctly | 22 / 22 passed |
| 2 | Lint and formatting | ruff | Code is clean, consistent, free of common bugs | 0 issues |
| 3 | Real-infrastructure end-to-end check | Docker Compose + curl | It works with real Postgres and Redis, not just test doubles | All steps passed |
| 4 | Database migration check | Alembic + Postgres | Schema upgrades, downgrades and keeps data | Passed |
| 5 | Load test | Locust | Throughput and latency, and the value of the cache | 0 failures; numbers below |
| 6 | Continuous integration | GitHub Actions | Checks 1 and 2 plus a Docker build run on every push | Configured, **not yet run on GitHub** |

---

## 1. Automated tests (pytest)

**Tool:** [pytest](https://pytest.org) with FastAPI's `TestClient` (an in-process HTTP client from `httpx`). Run with `pytest`.

**What it means:** Each test sends real HTTP requests to the app (routing, validation, serialization, status codes are all exercised) and asserts on the response. It's an *integration-style* test of the API layer, plus a few focused unit tests of the Redis wrapper.

**Test doubles used (important to understand the limits):**
- **Database:** an in-memory **SQLite** database instead of Postgres, so tests run in about 0.2 seconds with no Docker.
- **Cache:** a `FakeCache` (a Python dict) instead of Redis. It records the TTL passed to `set` and counts `incr` calls, so tests can assert on caching and rate-limit behaviour.
- Because of these substitutes, tests prove *application logic*. They do **not** prove Postgres- or Redis-specific behaviour. That is why checks 3 and 4 exist.

**Outcome: 22 passed in about 0.2 s.**

### `tests/test_urls.py` (core behaviour)

| Test | What it measures / verifies |
|---|---|
| `test_shorten_creates_code` | POST `/shorten` returns 200, an 8-character code, and a `short_url` built from `BASE_URL` |
| `test_shorten_is_idempotent` | Shortening the same URL twice returns the same code (deduplication) |
| `test_shorten_rejects_invalid_url` | A malformed URL is rejected with 422 (input validation) |
| `test_redirect_and_cache_fill` | GET `/{code}` returns a **302** with the right `Location`, and the cache is populated afterwards |
| `test_redirect_served_from_cache` | If the code is already in the cache, the redirect is served from it (cache-aside read path) |
| `test_unknown_code_404` | An unknown code returns 404 |
| `test_invalid_code_format_422` | A code with illegal characters is rejected before touching the DB or cache |
| `test_health` | `/health` returns `{"status": "ok"}` (and successfully queries the DB) |
| `test_redis_failure_degrades_gracefully` | With Redis unreachable, `get` returns a miss and `set` doesn't raise, so the cache never takes the service down |

### `tests/test_features.py` (alias, expiry, rate limiting)

| Test | What it measures / verifies |
|---|---|
| `test_custom_alias_redirects` | A custom alias is returned as the short code and redirects correctly |
| `test_alias_taken_returns_409` | Reusing an alias returns 409 Conflict |
| `test_alias_does_not_dedupe_or_break_default_link` | Creating a vanity alias doesn't change or break the default code for the same URL |
| `test_invalid_alias_rejected` | Aliases with spaces or shorter than 3 chars are rejected (422) |
| `test_reserved_alias_rejected` | Reserved names (`health`, `docs`; case-insensitive) are rejected so they can't shadow real routes |
| `test_expiry_sets_expires_at_and_bounds_cache_ttl` | `expires_at` is returned, and the cache TTL is no longer than the link's remaining life |
| `test_expired_link_returns_410` | After the expiry time (simulated by patching the clock), the link returns **410 Gone** |
| `test_unexpired_link_still_works` | A link inside its lifetime still redirects |
| `test_expiry_bounds_validated` | Expiry below 60 s, above 1 year, or negative is rejected (422) |
| `test_expiring_links_are_not_deduplicated` | Two expiring links for the same URL get different codes |
| `test_rate_limit_returns_429_with_retry_after` | With a limit of 3, requests 4 and 5 get **429**, with a valid `Retry-After` (1–60 s) |
| `test_rate_limit_does_not_apply_to_redirects` | Redirects are never rate limited, only `POST /shorten` |
| `test_rate_limit_fails_open_when_redis_down` | If Redis fails, the counter returns `None` (callers allow the request) rather than blocking everyone |

**Not covered by automated tests (honest gaps):** a true concurrency race (two simultaneous creates of the same URL against real Postgres), the Alembic migrations in CI, and the HTML UI. The concurrency safety rests on the database `UNIQUE` constraint by design, but I have not written a test that races real threads.

---

## 2. Lint and formatting (ruff)

**Tool:** [ruff](https://docs.astral.sh/ruff/) (`ruff check .` and `ruff format --check .`).

**What it means:** Static analysis, with no code executed. It looks for unused imports, likely bugs (flake8-bugbear rules), import ordering, outdated syntax, and style inconsistency. Configured in `pyproject.toml` (rule sets `E, F, I, B, UP`, line length 100).

**Outcome:** All checks passed; all files formatted.

---

## 3. Real-infrastructure end-to-end check

**Tools:** Docker Compose (real Postgres 15 + Redis 7 + the API container built from the `Dockerfile`), `curl`, `psql`, `redis-cli`.

**What it means:** The pytest suite uses SQLite and a fake cache, so this check confirms the same behaviour on the real stack, run in an isolated Compose project (`urlshort_verify`) so none of the developer's other containers or volumes were affected.

**Checks and outcomes:**

| Check | Result |
|---|---|
| Stack starts; API waits for healthy Postgres/Redis; migrations run on boot | `/health` returned `{"status":"ok"}` |
| Create a short URL | Returned an 8-char code |
| Redirect | **302** to the original URL |
| Create the same URL again | Same short code (idempotent) |
| Cache fill | `redis-cli get <code>` returned the target URL |
| **Redis stopped**, then redirect | Still **302** (graceful degradation) |
| Custom alias `hello-1` | Created; redirect returned 302 |
| Same alias again for a different URL | **409** |
| Expiring link (`expires_in_seconds: 60`) | `expires_at` returned |
| Cache TTL of a non-expiring link | 86,400 s (24 h), as configured |
| Force-expire a row in Postgres, clear cache, request it | **410** "Short URL has expired" |
| Rate limit (10/min): 12 rapid creates after 3 earlier ones in the same minute | First 7 succeeded (the 3 earlier ones counted too), then **429** on the rest, with `Retry-After: 55` |

---

## 4. Database migration check (Alembic)

**Tool:** [Alembic](https://alembic.sqlalchemy.org) run inside the API container against real Postgres.

**What it means:** Migrations are versioned schema changes. This verifies that a database already containing data can move to the new schema, and back, without errors.

**Steps and outcome:**
1. `upgrade 0001`: created the original `urls` table. OK.
2. Inserted a row (`old12345`) under the old schema.
3. `upgrade head` (`0002`: add `expires_at`, make `target_hash` nullable, widen `short_code`). OK.
4. `downgrade 0001`: OK. The pre-existing row **survived** (`old12345` still present).
5. `upgrade head` again: OK.

**Note:** the `0002` downgrade intentionally deletes rows with a NULL hash (custom/expiring links), since they can't fit the old schema. This is documented in the migration file.

---

## 5. Load test (Locust)

**Tool:** [Locust](https://locust.io) 2.47 (`loadtest/locustfile.py`), a Python load-testing tool that simulates many concurrent users making HTTP requests and reports throughput and latency percentiles.

### What it means and measures

| Term | Meaning |
|---|---|
| **req/s (throughput / RPS)** | Requests completed per second. Higher is better; it indicates capacity. |
| **Latency p50 (median)** | Half of requests were faster than this. The "typical" experience. |
| **Latency p95 / p99** | 95% / 99% of requests were faster than this. Captures the slow tail, which matters more than the average for user experience and SLAs. |
| **Failures** | Responses that were not the expected status (302 for redirects, 200 for creates) or timed out. |
| **Concurrent users** | Simulated clients each sending requests back-to-back. |

### Setup
- **Traffic mix:** 95% `GET /{code}` (redirect), 5% `POST /shorten`, matching a typical read-heavy shortener. 200 links were seeded first. Redirects are **not followed** so only this service is measured.
- **Load:** 50 concurrent users, near-zero think time, 30 s measured after a 5 s warm-up. Fresh database per run.
- **Rate limiter** raised to effectively unlimited for the test (otherwise it would block the test itself).
- Three configurations compared (the `CACHE_ENABLED` and `WEB_CONCURRENCY` environment variables switch them).

### Results

| Configuration | Total req/s | Redirect p50 | Redirect p95 | Redirect p99 | Failures |
|---|---|---|---|---|---|
| A. No cache, 1 worker | 554 | 73 ms | 140 ms | 180 ms | 0 |
| B. Redis cache, 1 worker | 910 | 41 ms | 69 ms | 100 ms | 0 |
| C. Redis cache, 4 workers | 1,256 | 24 ms | 59 ms | 110 ms | 0 |

Per-endpoint detail:

| Config | Endpoint | Requests | req/s | p50 | p95 | p99 |
|---|---|---|---|---|---|---|
| A | GET /{code} | 15,252 | 525 | 73 | 140 | 180 |
| A | POST /shorten | 821 | 28 | 120 | 190 | 260 |
| B | GET /{code} | 25,080 | 864 | 41 | 69 | 100 |
| B | POST /shorten | 1,325 | 46 | 110 | 160 | 210 |
| C | GET /{code} | 34,879 | 1,195 | 24 | 59 | 110 |
| C | POST /shorten | 1,763 | 60 | 43 | 130 | 250 |

### Conclusions
- **Cache effect (A to B):** redirect throughput **+64%** (525 to 864 req/s); redirect p95 **-51%** (140 to 69 ms).
- **Scaling out (B to C):** four worker processes gave a further **+38%** total throughput.

### How to read these numbers honestly
- **Closed-loop test:** 50 users with no pauses keep the server permanently saturated, so latency is mostly queueing time. Use these numbers to **compare configurations**, not as the latency a real user would see at normal load.
- **Cache benefit is probably understated:** the table is tiny, so the Postgres lookup is already fast. A larger table would widen the gap.
- **Single run per configuration** on a laptop where Locust, Docker, Postgres, Redis and the API share the same CPUs. Treat differences under about 10% as noise. Scaling from 1 to 4 workers is sub-linear partly because everything competes for the same 4 CPUs.
- These are **not** production capacity numbers. Quote relative improvements, not absolute req/s, as a claim about real-world scale.

Full method and reproduction steps: [docs/LOAD_TEST.md](docs/LOAD_TEST.md).

---

## 6. Continuous integration (GitHub Actions)

**File:** `.github/workflows/ci.yml`. On every push to `main` and every pull request it runs: `ruff check`, `ruff format --check`, `pytest`, and a `docker build`.

**Status: configured but not yet executed on GitHub** (nothing has been pushed since it was added). The same commands pass locally. Pushing will confirm it works in a clean environment.

---

## How to re-run everything

```bash
# 1 + 2: tests and lint (no Docker needed)
pip install -r requirements-dev.txt
pytest
ruff check . && ruff format --check .

# 3 + 4: real stack and migrations
docker compose up -d --build
curl localhost:8000/health
docker compose run --rm api alembic upgrade head      # re-apply/inspect migrations

# 5: load test
pip install -r requirements-loadtest.txt
RATE_LIMIT_PER_MINUTE=100000000 docker compose up -d --build
locust -f loadtest/locustfile.py --headless -u 50 -r 50 -t 30s --host http://localhost:8000
```
