# Load test results

Measured with [Locust](https://locust.io) (`loadtest/locustfile.py`). Two sessions are recorded: the first was
run before request logging existed, the second (6 Nov 2026) re-ran everything with logging on **and** off.

## Method

- **Traffic mix:** 95% `GET /{code}` (redirect, not followed) / 5% `POST /shorten` (new URL each time). 200 links are seeded first.
- **Load:** 50 concurrent users, no think time, 30 s measured after a 5 s warm-up, fresh stack (empty DB) per run.
- **Rate limiter** raised to effectively unlimited for the test (`RATE_LIMIT_PER_MINUTE=100000000`).
- **Stack:** API + Postgres 15 + Redis 7 in Docker Compose. Redirects use a primary-key lookup.
- **Hardware:** MacBook (Apple M1, 8 cores), Docker Desktop VM with 4 CPUs / ~5 GB. Locust ran on the same machine.
- **Configurations:** A = no cache, 1 worker; B = Redis cache, 1 worker; C = Redis cache, 4 workers (`WEB_CONCURRENCY=4`).
- **Logging on** = `LOG_LEVEL=INFO` (one JSON access-log line per request to stdout, collected by Docker). **Logging off** = `LOG_LEVEL=WARNING` (verified: 0 access-log lines emitted).

## Results

Redirect latency is for `GET /{code}`. Every run below had **0 failed requests**.

### Session 2: with logging middleware (6 Nov 2026), same machine state for both blocks

| Config | Logging | Total req/s | Redirect p50 | Redirect p95 | Redirect p99 |
|---|---|---|---|---|---|
| A. No cache, 1 worker | on | 373 | 92 ms | 260 ms | 620 ms |
| A. No cache, 1 worker | off | 423 | 89 ms | 210 ms | 320 ms |
| B. Cache, 1 worker | on | 621 | 54 ms | 130 ms | 230 ms |
| B. Cache, 1 worker | off | 626 | 51 ms | 140 ms | 240 ms |
| C. Cache, 4 workers | on | 702 | 37 ms | 120 ms | 280 ms |
| C. Cache, 4 workers | off | 999 | 29 ms | 67 ms | 140 ms |

### Session 1: before logging existed (5 Nov 2026)

| Config | Total req/s | Redirect p50 | Redirect p95 | Redirect p99 |
|---|---|---|---|---|
| A. No cache, 1 worker | 554 | 73 ms | 140 ms | 180 ms |
| B. Cache, 1 worker | 910 | 41 ms | 69 ms | 100 ms |
| C. Cache, 4 workers | 1,256 | 24 ms | 59 ms | 110 ms |

## What the results show

- **The cache helps, consistently.** Redirect throughput with cache vs. without (1 worker): **+64%** in session 1, **+67%** in session 2 with logging, **+48%** in session 2 without logging. Redirect p95 falls by roughly a third to a half in all three comparisons. A reasonable summary is "about +50-65% redirect throughput and about 35-50% lower p95".
- **More workers help, with diminishing returns.** 4 workers vs. 1 (cache on): +38% (session 1), +13% (session 2, logging on), +60% (session 2, logging off).
- **Logging overhead is real but not cleanly measured.** Same-session, logging on vs. off: roughly -12% (config A), ~0% (B, within noise) and -30% (C, 4 workers) in total throughput. I ran each configuration once, so I can't separate the overhead from run-to-run noise, and the largest effect (C) may also reflect the single Docker log pipe being shared by four workers. Setting `LOG_LEVEL=WARNING` disables access logs if throughput matters more than request logs.

## Reading these numbers honestly

- **Absolute numbers are not comparable across sessions.** The no-logging control in session 2 (423 / 626 / 999 req/s) is 20-30% lower than session 1 (554 / 910 / 1,256) even though the code path is the same apart from logging being off. Docker Desktop had just been restarted and the laptop state differed. Only compare numbers from the same session (same table block).
- **Closed-loop test:** 50 users with no think time keep the server saturated, so latency is mostly queueing time (Little's law: latency is roughly concurrency / throughput). It shows relative differences, not what a user sees at normal load.
- **Cache benefit is probably understated:** the table is tiny, so the Postgres lookup is already fast.
- **Single run per cell**, with Locust, Docker, Postgres, Redis and the API sharing the same CPUs. Treat differences under ~10-15% as noise.
- `POST /shorten` is slower than redirects (it writes to Postgres and calls Redis for rate limiting), but it is only 5% of traffic.
- A first attempt at the session-2 run was discarded because Docker Desktop stopped mid-run and every request failed; the numbers above are from a clean re-run.

## Reproduce

```bash
pip install -r requirements-loadtest.txt
RATE_LIMIT_PER_MINUTE=100000000 CACHE_ENABLED=true WEB_CONCURRENCY=1 LOG_LEVEL=INFO docker compose up -d --build
locust -f loadtest/locustfile.py --headless -u 50 -r 50 -t 30s --host http://localhost:8000
```
