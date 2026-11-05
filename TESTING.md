# Testing and Verification Report

This document records every kind of check performed on the project, what each one **means**, what it **measures**, which **tool** was used, and what the **outcome** was. All results are from runs on 5 Nov 2026 on a MacBook (Apple M1, 8 cores) with Docker Desktop (4 CPUs, ~5 GB).

## Summary

| # | Check | Tool | What it proves | Outcome |
|---|---|---|---|---|
| 1 | Fast unit/integration tests (SQLite + fake cache) | pytest + FastAPI TestClient | Application logic behaves correctly | 35 / 35 passed |
| 2 | Concurrency tests on real Postgres | pytest + threads + Postgres | DB constraints hold under simultaneous requests | 3 / 3; mutation-checked |
| 3 | Migration tests on real Postgres | pytest + Alembic + Postgres | Migrations match the models, keep data, and reverse | 3 / 3 |
| 4 | **Real Redis tests** | pytest + Redis 7 | Cache TTLs, atomic counters and expiry behave on real Redis | 6 / 6; mutation-checked |
| 5 | **Live HTTP tests (real server, real DB, real Redis)** | pytest + uvicorn subprocess + httpx | The whole deployed app is correct under concurrent HTTP traffic | 5 / 5; mutation-checked |
| 6 | **Browser UI tests** | Playwright + headless Chromium | The page actually works for a user | 3 / 3 |
| 7 | **Structured logging tests** | pytest | Logs are JSON with a correlation id | 5 / 5 (inside the 35) |
| 8 | Code coverage | pytest-cov | How much of `app/` the tests execute | 93%, gated at 85% in CI |
| 9 | Lint and formatting | ruff | Clean, consistent, no common bugs | 0 issues |
| 10 | Manual real-infrastructure end-to-end check | Docker Compose + curl | Full container stack works | All steps passed |
| 11 | Load test | Locust | Throughput and latency, value of the cache | 0 failures |
| 12 | Continuous integration | GitHub Actions | All of the above on every push | Configured (Postgres + Redis + Chromium), **not yet run on GitHub** |

Total: **55 tests**: 35 run anywhere with no setup, and 20 more run when `TEST_DATABASE_URL` and `TEST_REDIS_URL` point at test databases (skipped otherwise).

---|---|---|---|---|
| 1 | Unit/integration tests (fast, SQLite + fake cache) | pytest + FastAPI TestClient | Application logic behaves correctly | 30 / 30 passed |
| 2 | **Concurrency tests on real Postgres** | pytest + threads + Postgres | The DB constraints hold under simultaneous requests | 3 / 3 passed; **mutation-checked** |
| 3 | **Migration tests on real Postgres** | pytest + Alembic + Postgres | Migrations build the schema the models declare, keep data, and reverse | 3 / 3 passed |
| 4 | **Code coverage** | pytest-cov | How much of `app/` the tests execute | 92%, gated at 85% in CI |
| 5 | Lint and formatting | ruff | Code is clean, consistent, free of common bugs | 0 issues |
| 6 | Manual real-infrastructure end-to-end check | Docker Compose + curl | Full stack works with real Postgres, Redis and the container image | All steps passed |
| 7 | Load test | Locust | Throughput and latency, and the value of the cache | 0 failures; numbers below |
| 8 | Continuous integration | GitHub Actions | Checks 1-5 plus a Docker build run on every push | Configured (now with Postgres), **not yet run on GitHub** |

Total: **36 tests** (30 run anywhere; 6 more run when `TEST_DATABASE_URL` points at a Postgres test database, and are skipped otherwise).

---|---|---|---|---|
| 1 | Automated unit/integration tests | pytest + FastAPI TestClient | Application logic behaves correctly | 22 / 22 passed |
| 2 | Lint and formatting | ruff | Code is clean, consistent, free of common bugs | 0 issues |
| 3 | Real-infrastructure end-to-end check | Docker Compose + curl | It works with real Postgres and Redis, not just test doubles | All steps passed |
| 4 | Database migration check | Alembic + Postgres | Schema upgrades, downgrades and keeps data | Passed |
| 5 | Load test | Locust | Throughput and latency, and the value of the cache | 0 failures; numbers below |
| 6 | Continuous integration | GitHub Actions | Checks 1 and 2 plus a Docker build run on every push | Configured, **not yet run on GitHub** |

---

## 1. Automated tests (pytest, fast)

**Tool:** [pytest](https://pytest.org) with FastAPI's `TestClient` (an in-process HTTP client from `httpx`). Run with `pytest`.

**What it means:** Each test sends real HTTP requests to the app (routing, validation, serialization, status codes are all exercised) and asserts on the response. It's an *integration-style* test of the API layer, plus a few focused unit tests of the Redis wrapper.

**Test doubles used (important to understand the limits):**
- **Database:** an in-memory **SQLite** database instead of Postgres, so tests run in about 0.2 seconds with no Docker.
- **Cache:** a `FakeCache` (a Python dict) instead of Redis. It records the TTL passed to `set` and counts `incr` calls, so tests can assert on caching and rate-limit behaviour.
- Because of these substitutes, tests prove *application logic*. They do **not** prove Postgres- or Redis-specific behaviour. That is why checks 3 and 4 exist.

**Outcome: 22 passed in about 0.2 s** (35 including the service, UI-wiring and logging tests below).

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

### `tests/test_services.py` (collision and retry paths, added later)

| Test | What it measures / verifies |
|---|---|
| `test_default_link_retries_on_random_code_collision` | If the random code is already taken, the service retries and succeeds with a new code |
| `test_expiring_link_retries_on_random_code_collision` | Same retry behaviour on the custom/expiring path |
| `test_gives_up_after_max_attempts` | If every attempt collides, it raises an error instead of looping forever, and writes nothing |
| `test_alias_taken_raises` | A duplicate alias raises `AliasTakenError` (which the API turns into 409) |
| `test_is_expired_handles_naive_datetimes` | Expiry works when the DB returns timezone-less datetimes (SQLite does) |

### `tests/test_ui.py` (UI wiring, added later)

**What it means:** these are lightweight checks of the served HTML with no browser. They catch broken wiring (missing form fields, a hard-coded `localhost:8000`, a payload the API wouldn't accept). They do **not** test visual rendering or JavaScript behaviour; that would need a browser tool such as Playwright.

| Test | What it measures / verifies |
|---|---|
| `test_index_served_with_form_controls` | `/` returns HTML containing the URL, alias, expiry and result elements |
| `test_ui_calls_same_origin_api` | The page calls `/shorten` on its own origin; no hard-coded host |
| `test_ui_sends_fields_the_api_accepts` | The page sends `target_url`, `custom_alias`, `expires_in_seconds`, and the API accepts that payload |

---

## 1b. Concurrency tests on real Postgres

**Files:** `tests/integration/test_concurrency.py`. **Tools:** pytest, Python `threading` + `ThreadPoolExecutor`, a real PostgreSQL 15 database.

**What it means:** the earlier design claim was "creating the same URL or alias at the same time is safe because the *database* enforces uniqueness, not application checks". Only a real database with truly simultaneous transactions can prove that. Each test starts 30 threads, each with its own DB session, and releases them at the same instant using a `threading.Barrier`.

| Test | What it measures / verifies | Outcome |
|---|---|---|
| `test_same_url_concurrently_yields_one_row_and_one_code` | 30 threads shorten the same URL at once (repeated for 10 different URLs). All must succeed, get the **same code**, and leave **exactly 1 row** | Passed |
| `test_same_alias_concurrently_has_exactly_one_winner` | 30 threads claim the same alias. Exactly **1 wins**, the other **29 get `AliasTakenError`** | Passed |
| `test_many_distinct_urls_concurrently_all_succeed_with_unique_codes` | 30 different URLs at once: all succeed, all codes are unique (no false conflicts) | Passed |

**Mutation check (proving the test can fail):** a test that always passes proves nothing. I removed the `UNIQUE` constraint from `target_hash` on the test database and re-ran the same race. **Result: 10 of 10 URLs ended up with duplicate rows** (one URL had 24 rows with 24 different codes). So the test detects the bug it was written for, and the passing result with the constraint in place is meaningful.

**Limits:** this exercises the service layer directly (not 30 HTTP requests), and a race test can in principle pass by luck; the 10 repetitions and the mutation result make that very unlikely, but it is not a mathematical proof.

---

## 1c. Migration tests on real Postgres

**File:** `tests/integration/test_migrations.py`. **Tools:** pytest, Alembic (run as a subprocess, like a real deploy), Postgres, and Alembic's `compare_metadata`.

**What it means:** migrations are the only way production schemas change, so they need their own tests. Each test starts from an empty schema.

| Test | What it measures / verifies | Outcome |
|---|---|---|
| `test_upgrade_head_on_empty_database_matches_models` | Running all migrations from scratch produces **exactly** the schema declared in `app/models.py`. Alembic's `compare_metadata` must report zero differences, so it catches "changed the model, forgot the migration" | Passed |
| `test_upgrade_preserves_existing_rows` | A row created under schema `0001` survives the upgrade to `0002` | Passed |
| `test_downgrade_keeps_default_links_and_drops_custom_ones` | Downgrade keeps plain links, deliberately deletes alias/expiring links (they can't fit the old schema), and the DB can upgrade again afterwards | Passed |

**Safety:** these tests wipe the `public` schema, so they refuse to run unless the database name contains `test`.

---

## 1d. Real Redis tests

**File:** `tests/integration/test_redis.py`. **Tools:** pytest + a real Redis 7 server (`TEST_REDIS_URL`, must use a non-zero DB index because the tests flush it).

**What it means:** the fast tests replace Redis with a Python dict, so they cannot prove how real Redis behaves. These tests check the cache class and the rate-limit counter against the real thing.

| Test | What it measures / verifies | Outcome |
|---|---|---|
| `test_set_get_roundtrip_with_default_ttl` | A value round-trips, and the key gets the default TTL (checked with Redis `TTL`) | Passed |
| `test_explicit_ttl_is_capped_by_default_ttl` | A shorter explicit TTL is honoured, a longer one is capped (how expiring links stay correct in cache) | Passed |
| `test_non_positive_ttl_is_not_cached` | A link with no remaining life is never cached | Passed |
| `test_miss_returns_none` | A missing key is a clean miss | Passed |
| `test_incr_counts_and_sets_expiry_once` | The counter increments, and the window expiry is set **once** (`EXPIRE NX`) and does not slide forward on later hits | Passed |
| `test_incr_is_atomic_under_threads` | 200 increments from 20 threads return exactly 1..200 with no lost or duplicate counts | Passed |

**Mutation check:** I replaced the atomic `INCR` pipeline with a non-atomic read-then-write. `test_incr_is_atomic_under_threads` **failed** (duplicate counts such as `[1, 1, 2, 2, ...]`), proving it detects the bug. The change was reverted.

---

## 1e. Live HTTP tests (the whole stack)

**File:** `tests/integration/test_live_http.py`. **Tools:** pytest, a real `uvicorn` server started as a subprocess on a free port (with Alembic migrations applied first), `httpx` as the HTTP client, real Postgres and real Redis.

**What it means:** earlier concurrency tests called the service layer. These send **real concurrent HTTP requests** to the real server, so they cover routing, validation, the rate limiter, the DB and the cache together, as in production. Threads are released simultaneously with a `threading.Barrier`.

| Test | What it measures / verifies | Outcome |
|---|---|---|
| `test_full_flow_create_redirect_cache` | Create, redirect (302), and the key appears in Redis only after the first redirect, with a ~24 h TTL | Passed |
| `test_http_race_same_url_one_row_one_code` | 30 simultaneous POSTs of one URL: all 200, one code, **one DB row** | Passed |
| `test_http_race_same_alias_one_winner` | 30 simultaneous POSTs of one alias: exactly one **200** and 29 **409** | Passed |
| `test_rate_limit_is_exact_under_concurrency` | 50 simultaneous POSTs against a limit of 10: **exactly 10 succeed and 40 get 429** (each with `Retry-After`) | Passed |
| `test_redirect_still_works_when_cache_entry_missing` | After flushing Redis (simulated eviction or restart), redirects still work from Postgres | Passed |

**Mutation check:** with the non-atomic counter above, the rate-limit test **failed: 49 of 50 requests got through a limit of 10**. So the "exactly 10" result is meaningful evidence that the limiter is race-free.

---

## 1f. Browser UI tests

**File:** `tests/integration/test_ui_browser.py`. **Tools:** [Playwright](https://playwright.dev/python/) driving headless Chromium against the live server.

**What it means:** the earlier UI tests only checked the HTML text. These load the page in a real browser, fill the form, click the button and check what the user sees, which also exercises the JavaScript.

| Test | What it measures / verifies | Outcome |
|---|---|---|
| `test_shorten_through_the_ui_and_follow_link` | Enter a URL, click Shorten, a short link appears, and navigating to it lands on the target | Passed |
| `test_custom_alias_and_expiry_through_the_ui` | Alias and expiry selections reach the API; the result shows the alias and a non-null `expires_at` | Passed |
| `test_taken_alias_shows_error_dialog` | Submitting the same alias twice shows an error dialog containing 409 / "already taken" | Passed |

**Limits:** one browser (Chromium) only, and it checks behaviour, not visual design or cross-browser layout.

---

## 1g. Structured logging tests

**Files:** `app/logging_config.py`, `app/middleware.py`, `tests/test_logging.py`. **What it means:** logs are one JSON object per line (easy to ship to CloudWatch, Datadog, etc.), and every request has a correlation id that appears in the response header and in all log lines for that request.

Example access-log line (real output):
```json
{"ts": "2026-11-05T16:19:25.687+00:00", "level": "INFO", "logger": "app.access", "message": "request", "request_id": "demo-1", "method": "GET", "path": "/health", "status": 200, "duration_ms": 6.33, "client_ip": "testclient"}
```

| Test | What it verifies |
|---|---|
| `test_request_id_generated_and_returned` | Every response carries a generated `X-Request-ID` |
| `test_safe_client_request_id_is_echoed` | A client-supplied id is reused, so traces can span services |
| `test_unsafe_request_id_is_replaced` | An id with spaces or control characters is discarded, which prevents log injection |
| `test_access_log_is_structured` | The access log record has method, path, status and duration |
| `test_json_formatter_output` | The formatter emits valid JSON including extra fields |

Settings: `LOG_LEVEL` (default `INFO`) and `LOG_FORMAT` (`json` or `text`). The middleware is pure ASGI, so it avoids the overhead of Starlette's `BaseHTTPMiddleware`. Logging every redirect at INFO has a cost at high request rates; I did not re-run the load test with logging enabled.

---

## 1h. Code coverage

**Tool:** `pytest-cov` (`pytest --cov=app`). **What it means:** the percentage of lines in `app/` executed by at least one test. It shows what is *untested*, not whether the tests are good (the mutation check above is the better evidence of quality).

**Outcome:** **93%** (was 90% before the added tests). CI fails if it drops below **85%**.

| Module | Coverage | Not covered |
|---|---|---|
| `main.py`, `models.py`, `schemas.py`, `config.py`, `ratelimit.py` | 100% | none |
| `services.py` | 98% | one defensive line |
| `logging_config.py` | 96% | the plain-text format branch |
| `cache.py` | 85% | `NullCache` and the `get_cache` wiring (the real Redis paths are covered by the integration tests, but the coverage run in the table above is the combined run with Redis enabled) |
| `middleware.py` | 86% | the unhandled-exception branch |
| `database.py` | 69% | the real `get_db` session dependency (tests override it) |

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

**File:** `.github/workflows/ci.yml`. On every push to `main` and every pull request it runs:
1. `ruff check` and `ruff format --check`
2. Service containers: **Postgres 15 and Redis 7**, with `TEST_DATABASE_URL` and `TEST_REDIS_URL` set, so the concurrency, migration, Redis, live-HTTP and browser tests all **run in CI** (they are not skipped there).
3. `playwright install --with-deps chromium` for the browser tests.
4. `pytest` with coverage, failing under 85%.
5. A separate job does a `docker build`.

**Status: configured but not yet executed on GitHub** (nothing has been pushed since it was changed). The workflow file parses as valid YAML, and the same test command passes locally against real Postgres, Redis and Chromium. The most likely first-run problems are environment differences (for example, Chromium system packages), which pushing will reveal.

---

## Remaining known gaps

- **The CI workflow has not yet run on GitHub.**
- **Browser coverage is Chromium only**, and the tests check behaviour rather than visual layout.
- **The load test was not re-run with request logging enabled**, so the published throughput numbers predate the logging middleware.
- **No click analytics** (not implemented; it needs a design decision on durability vs redirect latency).
- Race tests can in principle pass by luck; repetition and the mutation checks make that very unlikely, but it is not a formal proof.

---

## How to re-run everything

```bash
# Fast tests and lint (no Docker needed; integration tests are skipped)
pip install -r requirements-dev.txt
pytest
ruff check . && ruff format --check .

# Everything, including real-Postgres concurrency + migration tests, with coverage
docker compose up -d postgres redis
docker compose exec postgres psql -U postgres -c "create database url_shortener_test"
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/url_shortener_test
export TEST_REDIS_URL=redis://localhost:6379/15     # non-zero DB index: tests FLUSH it
playwright install chromium                          # once, for browser tests
pytest --cov=app --cov-report=term-missing

# Manual real-stack check and migrations
docker compose up -d --build
curl localhost:8000/health
docker compose run --rm api alembic upgrade head      # re-apply/inspect migrations

# Load test
pip install -r requirements-loadtest.txt
RATE_LIMIT_PER_MINUTE=100000000 docker compose up -d --build
locust -f loadtest/locustfile.py --headless -u 50 -r 50 -t 30s --host http://localhost:8000
```
