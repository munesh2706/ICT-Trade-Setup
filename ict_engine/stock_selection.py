"""Transparent 15-minute NIFTY 50 stock ranking and stable watchlist selection.

This is a screening layer, not an ICT detector or trade signal. Benchmark and
industry comparisons are internal proxies derived from the dated NIFTY 50
constituent basket and NSE constituent industry labels; no external index or
sector-index prices are implied.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from .market_calendar import ExchangeCalendar
from .stock_storage import StockCandleStore
from .stock_universe import UniverseSnapshot

BAR_MINUTES = 5
BASELINE_SESSIONS = 20
MIN_RVOL_SAMPLES = 10
HISTORY_LIMIT = (BASELINE_SESSIONS + 1) * 75
IST_OPEN_MINUTES = 9 * 60 + 15

WEIGHTS = {
    "relative_strength_vs_basket": 15.0,
    "relative_strength_vs_industry": 10.0,
    "industry_strength": 10.0,
    "industry_breadth": 5.0,
    "industry_persistence": 5.0,
    "relative_volume": 20.0,
    "momentum": 15.0,
    "market_structure_proxy": 20.0,
}


def _pct_change(current: float, reference: float) -> float:
    if reference == 0:
        return 0.0
    return (current / reference - 1.0) * 100.0


def _percentile_scores(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted((value, key) for key, value in values.items())
    if len(ordered) == 1:
        return {ordered[0][1]: 50.0}
    result: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        rank = (i + j) / 2
        score = 100.0 * rank / (len(ordered) - 1)
        for _, key in ordered[i:j + 1]:
            result[key] = score
        i = j + 1
    return result


def _slot(timestamp: datetime) -> int:
    local = timestamp
    minute = local.hour * 60 + local.minute
    return (minute - IST_OPEN_MINUTES) // BAR_MINUTES


def _structure_proxy(bars) -> float:
    if len(bars) < 12:
        raise ValueError("at least 12 completed 5m bars are required for structure proxy")
    prior, recent = bars[-12:-6], bars[-6:]
    prior_high = max(float(x.high) for x in prior)
    prior_low = min(float(x.low) for x in prior)
    recent_high = max(float(x.high) for x in recent)
    recent_low = min(float(x.low) for x in recent)
    high_direction = 1.0 if recent_high > prior_high else (-1.0 if recent_high < prior_high else 0.0)
    low_direction = 1.0 if recent_low > prior_low else (-1.0 if recent_low < prior_low else 0.0)
    return (high_direction + low_direction) / 2.0


def _candidate_features(member, bars, scan_date: date, as_of: datetime,
                        calendar: ExchangeCalendar, cas_eligible: bool) -> dict[str, Any]:
    completed = [
        bar for bar in bars
        if bar.timestamp + timedelta(minutes=BAR_MINUTES) <= as_of
        and (not cas_eligible or calendar.is_continuous_trading_at(bar.timestamp, cas_eligible=True))
    ]
    current = [bar for bar in completed if bar.timestamp.astimezone(calendar.timezone).date() == scan_date]
    if len(current) < 13:
        return {"eligible": False, "reason": "waiting for 60-minute completed 5m history",
                "symbol": member.symbol, "industry": member.industry or "UNCLASSIFIED"}
    current.sort(key=lambda x: x.timestamp)
    last = current[-1]
    local_last = last.timestamp.astimezone(calendar.timezone)
    slot = _slot(local_last)
    prior_by_date: dict[date, dict[int, Any]] = {}
    for bar in completed:
        local = bar.timestamp.astimezone(calendar.timezone)
        if local.date() >= scan_date:
            continue
        prior_by_date.setdefault(local.date(), {})[_slot(local)] = bar
    prior_dates = sorted(prior_by_date)[-BASELINE_SESSIONS:]
    same_slot_volumes = [
        float(prior_by_date[day][slot].volume)
        for day in prior_dates if slot in prior_by_date[day]
    ]
    if len(same_slot_volumes) < MIN_RVOL_SAMPLES:
        return {"eligible": False,
                "reason": f"insufficient same-time RVOL baseline ({len(same_slot_volumes)}/{MIN_RVOL_SAMPLES} minimum)",
                "symbol": member.symbol, "industry": member.industry or "UNCLASSIFIED",
                "rvol_samples": len(same_slot_volumes)}
    baseline_volume = median(same_slot_volumes)
    rvol = float(last.volume) / baseline_volume if baseline_volume > 0 else None
    if rvol is None:
        return {"eligible": False, "reason": "same-time historical median volume is zero",
                "symbol": member.symbol, "industry": member.industry or "UNCLASSIFIED"}
    close = float(last.close)
    ret_30m = _pct_change(close, float(current[-7].close))
    ret_60m = _pct_change(close, float(current[-13].close))
    session_return = _pct_change(close, float(current[0].open))
    momentum = 0.50 * ret_30m + 0.30 * ret_60m + 0.20 * session_return
    structure = _structure_proxy(current)
    return {
        "eligible": True, "reason": "completed candles and same-time RVOL baseline available",
        "symbol": member.symbol, "company_name": member.company_name,
        "industry": member.industry or "UNCLASSIFIED",
        "industry_peers": 0, "latest_5m": last.timestamp.isoformat(),
        "last_price": close, "return_30m_pct": ret_30m, "return_60m_pct": ret_60m,
        "session_return_pct": session_return, "momentum_raw": momentum,
        "structure_raw": structure, "rvol_ratio": rvol,
        "rvol_samples": len(same_slot_volumes), "rvol_baseline_median_volume": baseline_volume,
    }


def _score_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    basket_60m = sum(x["return_60m_pct"] for x in rows) / len(rows)
    basket_session = sum(x["session_return_pct"] for x in rows) / len(rows)
    industries: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        industries.setdefault(row["industry"], []).append(row)
    industry_metrics: dict[str, dict[str, float]] = {}
    for industry, members in industries.items():
        r60 = sum(x["return_60m_pct"] for x in members) / len(members)
        rday = sum(x["session_return_pct"] for x in members) / len(members)
        composite = 0.60 * r60 + 0.40 * rday
        breadth = sum(1 for x in members if 0.60 * x["return_60m_pct"] + 0.40 * x["session_return_pct"] > 0) / len(members)
        same_sign = (r60 > 0 and rday > 0) or (r60 < 0 and rday < 0)
        persistence = 1.0 if same_sign and r60 > 0 else (-1.0 if same_sign and r60 < 0 else 0.0)
        industry_metrics[industry] = {
            "composite": composite, "breadth": breadth * 100.0,
            "persistence": (persistence + 1.0) * 50.0,
        }
    raw: dict[str, dict[str, float]] = {}
    for row in rows:
        peers = [x for x in industries[row["industry"]] if x["symbol"] != row["symbol"]]
        peer_composite = (
            sum(0.60 * x["return_60m_pct"] + 0.40 * x["session_return_pct"] for x in peers) / len(peers)
            if peers else 0.60 * row["return_60m_pct"] + 0.40 * row["session_return_pct"]
        )
        row["industry_peers"] = len(peers)
        rs_basket = 0.60 * (row["return_60m_pct"] - basket_60m) + 0.40 * (row["session_return_pct"] - basket_session)
        own_composite = 0.60 * row["return_60m_pct"] + 0.40 * row["session_return_pct"]
        raw[row["symbol"]] = {
            "rs_basket": rs_basket,
            "rs_industry": own_composite - peer_composite if peers else 0.0,
            "industry_strength": industry_metrics[row["industry"]]["composite"],
            "industry_breadth": industry_metrics[row["industry"]]["breadth"],
            "industry_persistence": industry_metrics[row["industry"]]["persistence"],
            "rvol": row["rvol_ratio"],
            "momentum": row["momentum_raw"],
            "structure": row["structure_raw"],
        }
    pct = {
        key: _percentile_scores({symbol: values[key] for symbol, values in raw.items()})
        for key in ("rs_basket", "rs_industry", "industry_strength", "rvol", "momentum", "structure")
    }
    for row in rows:
        symbol = row["symbol"]
        values = raw[symbol]
        components = {
            "relative_strength_vs_basket": pct["rs_basket"][symbol],
            "relative_strength_vs_industry": pct["rs_industry"][symbol] if row["industry_peers"] else 50.0,
            "industry_strength": pct["industry_strength"][symbol],
            "industry_breadth": values["industry_breadth"],
            "industry_persistence": values["industry_persistence"],
            "relative_volume": pct["rvol"][symbol],
            "momentum": pct["momentum"][symbol],
            "market_structure_proxy": pct["structure"][symbol],
        }
        bullish = (
            components["relative_strength_vs_basket"] * 0.15
            + components["relative_strength_vs_industry"] * 0.10
            + components["industry_strength"] * 0.10
            + components["industry_breadth"] * 0.05
            + components["industry_persistence"] * 0.05
            + components["relative_volume"] * 0.20
            + components["momentum"] * 0.15
            + components["market_structure_proxy"] * 0.20
        )
        bearish = (
            (100.0 - components["relative_strength_vs_basket"]) * 0.15
            + (100.0 - components["relative_strength_vs_industry"]) * 0.10
            + (100.0 - components["industry_strength"]) * 0.10
            + (100.0 - components["industry_breadth"]) * 0.05
            + (100.0 - components["industry_persistence"]) * 0.05
            + components["relative_volume"] * 0.20
            + (100.0 - components["momentum"]) * 0.15
            + (100.0 - components["market_structure_proxy"]) * 0.20
        )
        row["components"] = {k: round(v, 2) for k, v in components.items()}
        row["bullish_score"] = round(bullish, 2)
        row["bearish_score"] = round(bearish, 2)
        row["best_direction"] = "bullish" if bullish >= bearish else "bearish"
        row["best_score"] = max(bullish, bearish)
        if not row["industry_peers"]:
            row["industry_note"] = "Single-member NSE industry group; peer-relative component is neutral."


def _apply_stability(ranked: list[dict[str, Any]], previous: list[dict[str, Any]],
                     *, min_score: float, replacement_margin: float,
                     as_of: datetime, max_selected: int = 4) -> list[dict[str, Any]]:
    by_symbol = {row["symbol"]: row for row in ranked if row.get("eligible")}
    selected: list[dict[str, Any]] = []
    for direction, score_key in (("bullish", "bullish_score"), ("bearish", "bearish_score")):
        pool = sorted(
            (row for row in by_symbol.values() if row[score_key] >= min_score),
            key=lambda row: (-row[score_key], row["symbol"]),
        )
        picks = pool[:2]
        previous_side = [
            item for item in previous
            if item.get("direction") == direction and item.get("symbol") in by_symbol
            and by_symbol[item["symbol"]][score_key] >= min_score
        ]
        for old in previous_side:
            old_row = by_symbol[old["symbol"]]
            if any(x["symbol"] == old_row["symbol"] for x in picks):
                continue
            if not picks:
                picks.append(old_row)
                continue
            weakest = min(picks, key=lambda row: (row[score_key], row["symbol"]))
            if weakest[score_key] < old_row[score_key] + replacement_margin:
                picks.remove(weakest)
                picks.append(old_row)
        selected.extend({
            "symbol": row["symbol"], "direction": direction,
            "score": row[score_key],
            "selected_since": next((x.get("selected_since") for x in previous
                                    if x.get("symbol") == row["symbol"] and x.get("direction") == direction),
                                   as_of.isoformat()),
        } for row in picks)
    # If one side has fewer than two qualified names, allow the other side to
    # fill remaining capacity, but never force a candidate below min_score.
    counts = {side: sum(x["direction"] == side for x in selected) for side in ("bullish", "bearish")}
    remaining = []
    for row in by_symbol.values():
        if row["best_score"] < min_score or any(x["symbol"] == row["symbol"] for x in selected):
            continue
        direction = row["best_direction"]
        if counts[direction] < 3:
            remaining.append((row, direction))
    remaining.sort(key=lambda item: (-item[0]["best_score"], item[0]["symbol"]))
    for row, direction in remaining:
        if len(selected) >= max_selected:
            break
        if counts[direction] >= 3:
            continue
        selected.append({
            "symbol": row["symbol"], "direction": direction,
            "score": row["best_score"], "selected_since": as_of.isoformat(),
        })
        counts[direction] += 1
    selected.sort(key=lambda x: (-x["score"], x["symbol"]))
    return selected[:max_selected]


def rank_and_select_stocks(
    *,
    universe: UniverseSnapshot,
    store: StockCandleStore,
    calendar: ExchangeCalendar,
    scan_date: date,
    as_of: datetime,
    cas_eligible_symbols: set[str] | None = None,
    previous_selection: list[dict[str, Any]] | None = None,
    minimum_score: float = 60.0,
    replacement_margin: float = 8.0,
) -> dict[str, Any]:
    """Rank all constituents and choose a stable balanced watchlist.

    Defaults (60/100 qualification and 8-point replacement margin) are
    configurable engineering starting values, not statistically validated
    thresholds or ICT rules.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if minimum_score < 0 or minimum_score > 100 or replacement_margin < 0:
        raise ValueError("invalid stock-selection thresholds")
    if len(universe.constituents) != 50:
        raise ValueError("stock selection requires exactly 50 constituents")
    cas = set(cas_eligible_symbols or ())
    ranked: list[dict[str, Any]] = []
    for member in universe.constituents:
        bars = store.load_verified_candles(
            member.symbol, "5m", end=as_of, limit=HISTORY_LIMIT,
        )
        ranked.append(_candidate_features(
            member, bars, scan_date, as_of, calendar, member.symbol in cas,
        ))
    valid = [row for row in ranked if row.get("eligible")]
    if len(valid) >= 40:
        _score_rows(valid)
        selected = _apply_stability(
            valid, previous_selection or [], min_score=minimum_score,
            replacement_margin=replacement_margin, as_of=as_of,
        )
        status = "OK" if selected else "NO_QUALIFIED_CANDIDATES"
    else:
        selected = []
        status = "WAITING_FOR_UNIVERSE_COVERAGE"
    selected_map = {x["symbol"]: x for x in selected}
    for row in ranked:
        picked = selected_map.get(row["symbol"])
        row["selected"] = bool(picked)
        row["selected_direction"] = picked["direction"] if picked else None
        row["selected_since"] = picked["selected_since"] if picked else None
        row.setdefault("bullish_score", None)
        row.setdefault("bearish_score", None)
        row.setdefault("best_score", None)
        row.setdefault("components", {})
    ranked.sort(key=lambda row: (
        not row.get("eligible", False),
        -(row.get("best_score") or 0.0),
        row["symbol"],
    ))
    return {
        "status": status, "ranked_at": as_of.isoformat(),
        "refresh_minutes": 15, "target_bullish": 2, "target_bearish": 2,
        "max_selected": 4, "minimum_score": minimum_score,
        "replacement_margin": replacement_margin,
        "universe_coverage": len(valid), "universe_size": 50,
        "selected": selected, "ranking": ranked,
        "methodology": {
            "relative_strength": "NIFTY 50 equal-weight constituent-basket proxy and NSE industry-peer proxy; not official index/sector-index prices",
            "sector_strength": "NSE constituent Industry-group average return, breadth and 60m/session directional persistence",
            "relative_volume": "Latest completed 5m volume divided by median volume for the same 5m session slot across up to 20 prior sessions; at least 10 samples required",
            "momentum": "50% 30m return + 30% 60m return + 20% session return",
            "market_structure_proxy": "Comparison of recent six 5m bars against preceding six for higher/lower highs and lows; screening proxy, not an ICT rule",
            "weights": WEIGHTS,
            "thresholds_are_provisional": True,
        },
    }


def ranking_cycle_due(as_of: datetime, last_ranked_at: datetime | None) -> bool:
    """Run on 15-minute wall-clock boundaries; retry each boundary until ranked."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if as_of.minute % 15 != 0:
        return False
    if last_ranked_at is None:
        return True
    bucket = as_of.replace(minute=(as_of.minute // 15) * 15, second=0, microsecond=0)
    last_bucket = last_ranked_at.replace(
        minute=(last_ranked_at.minute // 15) * 15, second=0, microsecond=0,
    )
    return bucket != last_bucket
