"""Load test: realistic read-heavy mix (95% redirects, 5% creates).

Run (server must have RATE_LIMIT_PER_MINUTE set high, see README):
    locust -f loadtest/locustfile.py --headless -u 50 -r 50 -t 30s --host http://localhost:8000
"""

import random
import uuid

from locust import HttpUser, between, events, task

SEED_LINKS = 200


class Hot:
    codes: list[str] = []


@events.test_start.add_listener
def seed(environment, **_):
    """Create a pool of links up front so redirects hit existing codes."""
    import requests

    for _ in range(SEED_LINKS):
        r = requests.post(
            f"{environment.host}/shorten",
            json={"target_url": f"https://example.com/seed/{uuid.uuid4()}"},
            timeout=10,
        )
        r.raise_for_status()
        Hot.codes.append(r.json()["short_code"])


class Visitor(HttpUser):
    wait_time = between(0, 0.01)

    @task(95)
    def redirect(self):
        # Never follow the redirect: we're measuring *our* service, not example.com.
        with self.client.get(
            f"/{random.choice(Hot.codes)}",
            allow_redirects=False,
            name="GET /{code}",
            catch_response=True,
        ) as r:
            if r.status_code != 302:
                r.failure(f"expected 302, got {r.status_code}")

    @task(5)
    def create(self):
        with self.client.post(
            "/shorten",
            json={"target_url": f"https://example.com/new/{uuid.uuid4()}"},
            name="POST /shorten",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"expected 200, got {r.status_code}")
