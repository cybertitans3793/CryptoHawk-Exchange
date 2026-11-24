"""Shared fixtures: a throwaway SQLite db and a fake TBA, so tests never touch the network."""

import copy
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASS", "test-pass")

import main  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise main.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return copy.deepcopy(self._payload)


class FakeTBA:
    """Stands in for main.TBA. Set .matches / .teams, or .down = True to simulate an outage."""

    def __init__(self):
        self.matches = []
        self.teams = []
        self.down = False
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        if self.down:
            raise main.requests.ConnectionError("TBA unreachable")
        if url.endswith("/teams/keys"):
            return FakeResponse(self.teams)
        if url.endswith("/matches"):
            return FakeResponse(self.matches)
        raise AssertionError(f"unexpected TBA url {url}")


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def qm(number, rp, team="frc8726", color="red", time=None, scored=True, dq=False):
    """A minimal TBA qual-match object with `team` on `color` earning `rp` (alliance RP)."""
    other = "blue" if color == "red" else "red"
    alliances = {
        color: {"team_keys": [team, "frc1", "frc2"], "dq_team_keys": [team] if dq else []},
        other: {"team_keys": ["frc3", "frc4", "frc5"], "dq_team_keys": []},
    }
    breakdown = {color: {"rp": rp}, other: {"rp": 0}} if scored else None
    return {
        "comp_level": "qm",
        "match_number": number,
        "time": time if time is not None else 1_700_000_000 + number * 600,
        "alliances": alliances,
        "score_breakdown": breakdown,
    }


@pytest.fixture
def tba(monkeypatch):
    fake = FakeTBA()
    monkeypatch.setattr(main, "TBA", fake)
    return fake


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh db and empty caches for every test."""
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "_market", {"result": None, "ts": 0.0, "ok_ts": 0.0})
    monkeypatch.setattr(main, "_teams", {"keys": None, "ts": 0.0})
    monkeypatch.setattr(main, "REPLAY_MODE", False)
    monkeypatch.setattr(main, "ADMIN_USER", "admin")
    monkeypatch.setattr(main, "ADMIN_PASS", "test-pass")
    monkeypatch.setattr(main, "TBA_WEBHOOK_SECRET", "")


@pytest.fixture
def client(tba):
    with TestClient(main.app) as c:  # `with` runs the lifespan, which creates the tables
        yield c
