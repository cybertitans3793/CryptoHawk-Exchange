"""Claim flow, names, leaderboards and admin access."""

import pytest
from conftest import load_fixture, qm

import main

AUTH = ("admin", "test-pass")


@pytest.fixture
def event(tba):
    tba.teams = ["frc8726", "frc1629", "frc346"]
    tba.matches = [qm(1, 6)]  # price 1.5
    return tba


def claim(client, team):
    client.cookies.clear()  # each claim is a new browser
    return client.post("/claim", data={"team_num": team}, follow_redirects=False)


def test_claim_creates_account_and_cookie(client, event):
    r = claim(client, "8726")
    assert r.status_code == 303 and r.headers["location"] == "/me?new=1"
    token = r.cookies[main.COOKIE_NAME]
    conn = main.get_db()
    acct = conn.execute("SELECT * FROM accounts WHERE token=?", (token,)).fetchone()
    conn.close()
    assert acct["team_number"] == "8726"
    assert acct["buy_price"] == 1.5
    assert acct["hb"] == pytest.approx(main.INVEST_TALONS / 1.5, abs=1e-4)
    assert acct["name"] in main.STEM_NAMES


def test_claim_strips_leading_zeros(client, event):
    assert claim(client, " 08726 ").headers["location"] == "/me?new=1"


@pytest.mark.parametrize("team, error", [("abc", "badteam"), ("   ", "badteam"), ("9999", "notatevent")])
def test_claim_rejects_bad_teams(client, event, team, error):
    r = claim(client, team)
    assert f"error={error}" in r.headers["location"]
    assert main.COOKIE_NAME not in r.cookies


def test_claim_empty_field_is_422(client, event):
    # the HTML input is `required`, so only a hand-made request gets here
    assert claim(client, "").status_code == 422


def test_claim_refused_when_tba_never_answered(client, tba):
    tba.down = True
    assert "error=offline" in claim(client, "8726").headers["location"]


def test_second_claim_from_same_browser_is_ignored(client, event):
    claim(client, "8726")
    r = client.post("/claim", data={"team_num": "1629"}, follow_redirects=False)
    assert r.headers["location"] == "/me"
    conn = main.get_db()
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    conn.close()


def test_pick_name_uses_suffix_once_list_is_used_up(client):
    conn = main.get_db()
    for i, n in enumerate(main.STEM_NAMES):
        conn.execute(
            "INSERT INTO accounts (token, name, team_number, hb, buy_price, created) VALUES (?, ?, '1', 1, 1, 0)",
            (f"t{i}", n),
        )
    conn.commit()
    assert main.pick_name(conn).endswith(" II")
    conn.close()


def test_team_leaderboard_ranks_by_average_not_total(client):
    # Team 1111 has 5 small accounts; 2222 has one big trader. Ranking uses the average, so headcount alone doesn't win.
    conn = main.get_db()
    rows = [("1111", 10)] * 5 + [("2222", 20)]
    for i, (team, hb) in enumerate(rows):
        conn.execute(
            "INSERT INTO accounts (token, name, team_number, hb, buy_price, created) VALUES (?, ?, ?, ?, 1, ?)",
            (f"t{i}", f"N{i}", team, hb, i),
        )
    conn.commit()
    conn.close()
    people, teams = main.leaderboards(price=2.0)
    assert [t["team"] for t in teams] == ["2222", "1111"]
    assert teams[1]["members"] == 5 and teams[1]["total"] == 100 and teams[1]["avg"] == 20
    assert people[0]["name"] == "N5" and people[0]["value"] == 40


@pytest.mark.parametrize("path", ["/", "/tv", "/display"])
def test_public_pages_render(client, event, path):
    claim(client, "8726")
    client.cookies.clear()
    assert client.get(path).status_code == 200


def test_me_page_renders_for_account(client, event):
    claim(client, "8726")
    assert client.get("/me").status_code == 200


def test_public_pages_render_with_tba_down(client, tba):
    tba.down = True
    for path in ["/", "/tv", "/display"]:
        assert client.get(path).status_code == 200


def test_admin_requires_login(client, event):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    assert client.get("/admin", auth=AUTH).status_code == 200


def test_admin_disabled_without_configured_password(client, event, monkeypatch):
    monkeypatch.setattr(main, "ADMIN_PASS", "")
    assert client.get("/admin", auth=("admin", "")).status_code == 401


def test_admin_post_from_other_site_refused(client, event):
    r = client.post("/admin/purge", auth=AUTH, headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403


def test_replay_steps_and_resets(client, tba, monkeypatch):
    monkeypatch.setattr(main, "REPLAY_MODE", True)
    tba.matches = load_fixture("2025mdbob_frc8726_matches.json")
    for _ in range(7):  # stepping past the end stops at the last scored match
        client.post("/admin/replay", data={"action": "next"}, auth=AUTH)
    assert main.get_setting("replay_n") == "5"
    assert main.get_market()["price"] == 1.65
    client.post("/admin/replay", data={"action": "reset"}, auth=AUTH)
    assert main.get_market()["price"] == 1.0


# --- TBA webhook ---
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402

SECRET = "hook-secret"


def post_hook(client, msg, secret=SECRET):
    body = json.dumps(msg).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/tba/webhook", content=body, headers={"X-TBA-HMAC": sig, "Content-Type": "application/json"})


@pytest.fixture
def hook(monkeypatch):
    monkeypatch.setattr(main, "TBA_WEBHOOK_SECRET", SECRET)


def test_webhook_disabled_without_secret(client):
    assert post_hook(client, {"message_type": "ping"}).status_code == 404


def test_webhook_rejects_bad_signature(client, hook):
    assert post_hook(client, {"message_type": "ping"}, secret="wrong").status_code == 401
    assert client.post("/tba/webhook", content=b"{}").status_code == 401


def test_webhook_ping_ok(client, hook):
    r = post_hook(client, {"message_type": "ping", "message_data": {"title": "Test Message", "desc": "x"}})
    assert r.status_code == 200


def test_webhook_verification_code_shown_on_admin(client, hook, event):
    post_hook(client, {"message_type": "verification", "message_data": {"verification_key": "abc123"}})
    assert main.get_setting("tba_verification_key") == "abc123"
    assert "abc123" in client.get("/admin", auth=AUTH).text


def test_match_score_for_our_event_refreshes_price(client, hook, event, monkeypatch):
    monkeypatch.setattr(main, "EVENT_KEY", "2026test")
    assert main.get_market()["price"] == 1.5
    event.matches = [qm(1, 6), qm(2, 6)]
    assert main.get_market()["price"] == 1.5  # still cached
    post_hook(
        client, {"message_type": "match_score", "message_data": {"event_key": "2026test", "match_key": "2026test_qm2"}}
    )
    assert main.get_market()["price"] == 2.25


def test_match_score_for_other_event_ignored(client, hook, event, monkeypatch):
    monkeypatch.setattr(main, "EVENT_KEY", "2026test")
    main.get_market()
    calls = event.calls
    post_hook(client, {"message_type": "match_score", "message_data": {"event_key": "2026other"}})
    main.get_market()
    assert event.calls == calls
