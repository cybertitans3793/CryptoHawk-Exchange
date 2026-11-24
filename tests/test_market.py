"""Price formula and TBA-reliability behavior (V1.5: price *= 0.9 + 0.1 * RP per scored qual match)."""

import pytest
from conftest import load_fixture, qm

import main


def test_real_event_2025mdbob(tba):
    # 8726 at 2025mdbob: quals 2, 9, 13, 18, 21 earned 6, 1, 1, 1, 2 RP
    tba.matches = load_fixture("2025mdbob_frc8726_matches.json")
    m = main.get_market()
    assert m["labels"] == ["Start", "Q2", "Q9", "Q13", "Q18", "Q21"]
    assert m["history"] == [1.0, 1.5, 1.5, 1.5, 1.5, 1.65]
    assert m["price"] == 1.65
    assert m["scored"] == m["total_scored"] == 5
    assert m["online"] is True


@pytest.mark.parametrize(
    "rp, multiplier",
    [(0, 0.9), (1, 1.0), (2, 1.1), (4, 1.3), (6, 1.5), (9, 1.5), (-1, 0.9)],
)
def test_rp_multiplier_is_clamped_to_0_to_6(tba, rp, multiplier):
    tba.matches = [qm(1, rp)]
    assert main.get_market()["price"] == pytest.approx(multiplier)


def test_ignores_playoffs_and_sorts_by_time(tba):
    playoff = {**qm(99, 6), "comp_level": "sf"}
    tba.matches = [qm(5, 2, time=500), playoff, qm(3, 0, time=300)]
    m = main.get_market()
    assert m["labels"] == ["Start", "Q3", "Q5"]
    assert m["price"] == pytest.approx(0.9 * 1.1)


def test_blue_alliance_side_is_read(tba):
    tba.matches = [qm(1, 6, color="blue")]
    assert main.get_market()["price"] == 1.5


def test_unscored_matches_are_skipped(tba):
    tba.matches = [qm(1, 2), qm(2, 0, scored=False), qm(3, 2)]
    m = main.get_market()
    assert m["scored"] == 2
    assert m["price"] == pytest.approx(1.21)


def test_price_floor_is_0_1(tba):
    tba.matches = [qm(i, 0) for i in range(1, 40)]  # 0.9**39 ~= 0.016
    assert main.get_market()["price"] == 0.1


def test_keeps_last_good_price_when_tba_goes_down(tba):
    tba.matches = [qm(1, 6)]
    assert main.get_market()["price"] == 1.5
    tba.down = True
    m = main.get_market(force=True)
    assert m["price"] == 1.5
    assert m["online"] is False


def test_never_answered_means_no_market(tba):
    tba.down = True
    assert main.get_market() is None


def test_market_is_cached(tba):
    tba.matches = [qm(1, 2)]
    main.get_market()
    main.get_market()
    assert tba.calls == 1
    main.get_market(force=True)
    assert tba.calls == 2


@pytest.mark.xfail(strict=True, reason="V2 decision: a DQ'd team earns 0 RP; V1.5 still gives it the alliance RP")
def test_dq_team_earns_zero_rp(tba):
    tba.matches = [qm(1, 4, dq=True)]
    assert main.get_market()["price"] == 0.9


def test_replay_mode_counts_only_first_n(client, tba, monkeypatch):
    monkeypatch.setattr(main, "REPLAY_MODE", True)
    tba.matches = load_fixture("2025mdbob_frc8726_matches.json")
    main.set_setting("replay_n", 1)
    m = main.get_market()
    assert (m["scored"], m["total_scored"], m["price"]) == (1, 5, 1.5)
