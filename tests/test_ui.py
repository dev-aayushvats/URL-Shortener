"""Lightweight checks of the served UI (no browser). Catches broken wiring, not rendering."""


def test_index_served_with_form_controls(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for element_id in ("urlInput", "aliasInput", "expiryInput", "shortUrlLink"):
        assert f'id="{element_id}"' in r.text


def test_ui_calls_same_origin_api(client):
    html = client.get("/").text
    assert "fetch('/shorten'" in html
    assert "localhost:8000" not in html  # a hard-coded host would break any deployment


def test_ui_sends_fields_the_api_accepts(client):
    html = client.get("/").text
    for field in ("target_url", "custom_alias", "expires_in_seconds"):
        assert field in html
    # And the API accepts exactly that payload shape.
    r = client.post(
        "/shorten",
        json={
            "target_url": "https://example.com",
            "custom_alias": None,
            "expires_in_seconds": None,
        },
    )
    assert r.status_code == 200
