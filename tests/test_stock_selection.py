from datetime import date, datetime
from zoneinfo import ZoneInfo

from ict_engine.market_calendar import ExchangeCalendar, TradingSession
from ict_engine.stock_selection import apply_scan_readiness, _apply_stability, _percentile_scores, rank_and_select_stocks, ranking_cycle_due
from ict_engine.stock_universe import Constituent, UniverseSnapshot

IST = ZoneInfo("Asia/Kolkata")


def test_percentile_scores_handle_ties_and_single_value():
    assert _percentile_scores({"A": 1.0, "B": 2.0, "C": 2.0}) == {"A": 0.0, "B": 75.0, "C": 75.0}
    assert _percentile_scores({"A": 5.0}) == {"A": 50.0}


def _row(symbol, bull, bear, direction=None):
    best_direction = direction or ("bullish" if bull >= bear else "bearish")
    return {"symbol": symbol, "eligible": True, "bullish_score": bull, "bearish_score": bear,
            "best_score": max(bull, bear), "best_direction": best_direction}


def test_balanced_selection_targets_two_each_and_does_not_force_weak_candidates():
    ranked = [_row("B0",90,10),_row("B1",85,15),_row("B2",80,20),_row("B3",75,25),
              _row("S0",10,90),_row("S1",15,85),_row("S2",20,80),_row("S3",25,75)]
    selected = _apply_stability(ranked, [], min_score=60, replacement_margin=8,
                                as_of=datetime(2026,10,30,10,30,tzinfo=IST))
    assert len(selected) == 4
    assert sum(x["direction"] == "bullish" for x in selected) == 2
    assert sum(x["direction"] == "bearish" for x in selected) == 2
    weak = [_row(f"W{i}", 59, 40) for i in range(8)]
    assert _apply_stability(weak, [], min_score=60, replacement_margin=8,
                            as_of=datetime(2026,10,30,10,30,tzinfo=IST)) == []


def test_high_rvol_cannot_make_directionally_neutral_stock_eligible():
    now = datetime(2026,10,30,10,45,tzinfo=IST)
    neutral = _row("NEUTRAL", 60, 60)
    neutral["bullish_bias_score"] = 50
    neutral["bearish_bias_score"] = 50
    selected = _apply_stability([neutral], [], min_score=60, replacement_margin=8, as_of=now)
    assert selected == []


def test_selection_retains_existing_stock_until_challenger_clears_margin():
    now = datetime(2026,10,30,10,45,tzinfo=IST)
    ranked = [_row("OLD",76,24),_row("NEW",80,20),_row("NEW2",90,10),
              _row("S1",15,85),_row("S2",20,80)]
    previous = [{"symbol":"OLD","direction":"bullish","selected_since":"2026-10-30T10:15:00+05:30"}]
    selected = _apply_stability(ranked, previous, min_score=60, replacement_margin=8, as_of=now)
    old = next(x for x in selected if x["symbol"] == "OLD")
    assert old["selected_since"] == previous[0]["selected_since"]
    assert not any(x["symbol"] == "NEW" for x in selected)


def test_selection_replaces_old_stock_when_challenger_exceeds_margin():
    now = datetime(2026,10,30,10,45,tzinfo=IST)
    ranked = [_row("OLD",76,24),_row("NEW",85,15),_row("NEW2",90,10),
              _row("S1",15,85),_row("S2",20,80)]
    previous = [{"symbol":"OLD","direction":"bullish","selected_since":"2026-10-30T10:15:00+05:30"}]
    selected = _apply_stability(ranked, previous, min_score=60, replacement_margin=8, as_of=now)
    assert any(x["symbol"] == "NEW" for x in selected)
    assert not any(x["symbol"] == "OLD" for x in selected)


def test_selected_stock_is_removed_immediately_when_scanner_data_gate_fails():
    from types import SimpleNamespace
    selection = {
        "status": "OK",
        "selected": [
            {"symbol":"AAA","direction":"bullish","score":85,"selected_since":"2026-10-30T10:00:00+05:30"},
            {"symbol":"BBB","direction":"bearish","score":80,"selected_since":"2026-10-30T10:00:00+05:30"},
        ],
        "ranking": [
            {"symbol":"AAA","eligible":True,"selected":True},
            {"symbol":"BBB","eligible":True,"selected":True},
        ],
    }
    statuses = [
        SimpleNamespace(symbol="AAA", status="READY", reason=""),
        SimpleNamespace(symbol="BBB", status="DATA_NOT_READY", reason="missing completed 1m candle"),
    ]
    updated = apply_scan_readiness(selection, statuses)
    assert [x["symbol"] for x in updated["selected"]] == ["AAA"]
    assert updated["status"] == "DEGRADED_DATA_QUALITY"
    blocked = next(x for x in updated["ranking"] if x["symbol"] == "BBB")
    assert blocked["eligible"] is False
    assert "missing completed 1m candle" in blocked["reason"]
    recovered = apply_scan_readiness(updated, [
        SimpleNamespace(symbol="AAA", status="READY", reason=""),
    ])
    assert recovered["status"] == "OK"
    assert [x["symbol"] for x in recovered["selected"]] == ["AAA"]


def test_ranking_cycle_runs_only_on_new_15_minute_boundaries():
    last = datetime(2026,10,30,10,30,tzinfo=IST)
    assert ranking_cycle_due(datetime(2026,10,30,10,45,tzinfo=IST), last)
    assert not ranking_cycle_due(datetime(2026,10,30,10,46,tzinfo=IST), last)
    assert not ranking_cycle_due(datetime(2026,10,30,10,45,tzinfo=IST), datetime(2026,10,30,10,45,tzinfo=IST))


def test_ranker_requires_verified_rvol_history_and_does_not_make_up_data():
    members = tuple(Constituent(f"SYM{i:02d}", f"Company {i}", f"Industry {i%5}") for i in range(50))
    universe = UniverseSnapshot("u1", datetime.now(IST).isoformat(), "2026-10-30",
                                "nse", "a"*64, members)
    day = date(2026,10,30)
    session = TradingSession("NSE", day, datetime(2026,10,30,9,15,tzinfo=IST),
                             datetime(2026,10,30,15,30,tzinfo=IST), "fixture")
    calendar = ExchangeCalendar("NSE","Asia/Kolkata",day,day,[session],[],"fixture")
    class EmptyStore:
        def load_verified_candles(self,*args,**kwargs): return []
    result = rank_and_select_stocks(universe=universe,store=EmptyStore(),calendar=calendar,
        scan_date=day,as_of=datetime(2026,10,30,10,30,tzinfo=IST))
    assert result["status"] == "WAITING_FOR_UNIVERSE_COVERAGE"
    assert result["selected"] == []
    assert result["universe_coverage"] == 0
    assert all(not row["eligible"] for row in result["ranking"])


def test_ranking_cycle_rejects_naive_timestamps():
    import pytest
    with pytest.raises(ValueError, match="timezone-aware"):
        ranking_cycle_due(datetime(2026,10,30,10,30), None)
