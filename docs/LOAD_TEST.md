# Load test results

Measured with [Locust](https://locust.io) (`loadtest/locustfile.py`).

> **Note:** these runs were made before request logging (`RequestLogMiddleware`) was added, so they exclude its overhead. Re-run the load test before quoting them as current.

## Method

- **Traffic mix:** 95% `GET /{code}` (redirect, not followed) / 5% `POST /shorten` (new URL each time). 200 links are seeded first.
- **Load:** 50 concurrent users, no think time, 30 s measured after a 5 s warm-up, fresh stack (empty DB) per run.
- **Rate limiter** raised to effectively unlimited for the test (`RATE_LIMIT_PER_MINUTE=100000000`).
- **Stack:** API + Postgres 15 + Redis 7 in Docker Compose. Redirects use a primary-key lookup.
- **Hardware:** MacBook (Apple M1, 8 cores), Docker Desktop VM with 4 CPUs / ~5 GB. Locust ran on the same machine.

## Results

| Configuration | Total req/s | Redirect p50 | Redirect p95 | Redirect p99 | Failures |
|---|---|---|---|---|---|
| A. No cache, 1 worker (`CACHE_ENABLED=false`) | 554 | 73 ms | 140 ms | 180 ms | 0 |
| B. Redis cache, 1 worker | 910 | 41 ms | 69 ms | 100 ms | 0 |
| C. Redis cache, 4 workers (`WEB_CONCURRENCY=4`) | 1,256 | 24 ms | 59 ms | 110 ms | 0 |

- **Cache effect (A to B):** redirect throughput +64% (525 to 864 req/s), redirect p95 -51% (140 to 69 ms).
- **Scaling out (B to C):** a further +38% throughput (910 to 1,256 req/s total) and lower median latency from 4 workers.

## Reading these numbers honestly

- **Closed-loop test:** with 50 users and no think time the server is always saturated, so latency here is mostly queueing (Little's law: latency is roughly concurrency / throughput). Compare configurations with each other; don't read the absolute latencies as what a user sees at normal load.
- **Cache benefit is understated:** the table is tiny, so the Postgres lookup is already fast (the whole DB fits in memory). With a large table and cold pages, the gap would be wider. Postgres and Redis are both a network hop away, so the cache saves a query, not a round-trip.
- **Single run per configuration** on a laptop with the load generator sharing the CPU; expect some run-to-run variance (I'd treat differences under ~10% as noise). Scaling from 1 to 4 workers is sub-linear partly because Postgres, Redis and Locust compete for the same 4-CPU VM.
- `POST /shorten` is slower (p50 110 ms with 1 worker) because it writes to Postgres and goes through the rate-limit Redis call.

## Reproduce

```bash
pip install -r requirements-loadtest.txt
RATE_LIMIT_PER_MINUTE=100000000 CACHE_ENABLED=true WEB_CONCURRENCY=1 docker compose up -d --build
locust -f loadtest/locustfile.py --headless -u 50 -r 50 -t 30s --host http://localhost:8000
```
