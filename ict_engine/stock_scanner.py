"""Explainable ICT candidate scanner for individual NIFTY 50 stocks.

Only verified Angel One historical candles are accepted. Detectors are kept
source-versioned; engineering thresholds are surfaced on every signal.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Sequence

from .context import (
    LiquidityLevel, build_market_context, directional_target_candidates,
    equal_high_low_pools, previous_period_levels,
)
from .ict_2022_episode6 import detect_ict_2022_episode6
from .ict_silver_bullet_2023 import detect_silver_bullet_candidate
from .market_calendar import ExchangeCalendar
from .models import Candle, ICT2022SetupCandidate
from .sessions import silver_bullet_windows_ist
from .stock_storage import StockCandleStore
from .stock_universe import UniverseSnapshot

ZERO = Decimal("0")

@dataclass(frozen=True, slots=True)
class StockICTScanConfig:
    enable_episode6: bool = True
    enable_silver_bullet: bool = True
    pivot_left: int = 2
    pivot_right: int = 2
    displacement_min_body_to_range: Decimal = Decimal("0.65")
    max_bars_after_sweep: int = 6
    max_bars_after_mss: int = 3
    max_5m_lookback_bars: int = 240
    max_1m_lookback_bars: int = 420
    equal_high_low_tolerance_by_symbol: dict[str, Decimal] | None = None
    candle_timestamp_role: str = "start"

    def __post_init__(self):
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot widths must be positive")
        if not ZERO < self.displacement_min_body_to_range <= Decimal("1"):
            raise ValueError("displacement threshold must be in (0,1]")
        if min(self.max_bars_after_sweep, self.max_bars_after_mss,
               self.max_5m_lookback_bars, self.max_1m_lookback_bars) < 1:
            raise ValueError("bar limits must be positive")
        if self.candle_timestamp_role != "start":
            raise ValueError("current stock scanner requires verified Angel One start-time candle timestamps")
        if self.equal_high_low_tolerance_by_symbol is not None:
            if any(value < ZERO for value in self.equal_high_low_tolerance_by_symbol.values()):
                raise ValueError("equal-high/low tolerances cannot be negative")

@dataclass(frozen=True, slots=True)
class StockSignal:
    signal_id: str
    symbol: str
    company_name: str
    model_id: str
    direction: str
    status: str
    available_at: datetime
    entry_zone_lower: Decimal
    entry_zone_upper: Decimal
    entry_reference: Decimal | None
    invalidation_references: tuple[Decimal, ...]
    sweep_name: str | None
    sweep_price: Decimal | None
    sweep_extreme: Decimal | None
    mss_time: datetime | None
    mss_level: Decimal | None
    displacement_body_to_range: Decimal | None
    fvg_first_time: datetime
    fvg_middle_time: datetime
    fvg_third_time: datetime
    retest_time: datetime | None
    draw_targets: tuple[LiquidityLevel, ...]
    context: dict
    assumptions: tuple[str, ...]
    source_id: str

@dataclass(frozen=True, slots=True)
class StockScanStatus:
    symbol: str
    company_name: str
    status: str
    reason: str
    candles_1m: int
    candles_5m: int
    candles_15m: int
    latest_1m: datetime | None

@dataclass(frozen=True, slots=True)
class StockScanReport:
    scan_date: date
    as_of: datetime
    universe_snapshot_id: str
    total_stocks: int
    ready_stocks: int
    signals: tuple[StockSignal, ...]
    stock_status: tuple[StockScanStatus, ...]

def _validate_candles(candles: Sequence[Candle], symbol: str, timeframe: str):
    if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
        raise ValueError(f"{symbol}/{timeframe} candles are not strictly chronological")
    if any(c.timestamp.tzinfo is None for c in candles):
        raise ValueError(f"{symbol}/{timeframe} contains naive timestamps")

def _completed(candles: Sequence[Candle], as_of: datetime, duration: timedelta) -> list[Candle]:
    return [c for c in candles if c.timestamp + duration <= as_of]

def _prior_sessions(calendar: ExchangeCalendar, scan_date: date):
    if scan_date <= calendar.coverage_start:
        return (), ()
    previous_day = calendar.sessions_between(
        max(calendar.coverage_start, scan_date - timedelta(days=14)),
        scan_date - timedelta(days=1),
    )
    prior_day_sessions = previous_day[-1:] if previous_day else ()
    current_week_start = scan_date - timedelta(days=scan_date.weekday())
    prior_week_start = current_week_start - timedelta(days=7)
    prior_week_end = current_week_start - timedelta(days=1)
    if prior_week_start < calendar.coverage_start:
        prior_week_sessions = ()
    else:
        prior_week_sessions = calendar.sessions_between(prior_week_start, prior_week_end)
    return prior_day_sessions, prior_week_sessions

def _liquidity_context(
    symbol: str,
    candles_15m: Sequence[Candle],
    calendar: ExchangeCalendar,
    scan_date: date,
    current_price: Decimal,
    config: StockICTScanConfig,
):
    prior_day_sessions, prior_week_sessions = _prior_sessions(calendar, scan_date)
    day_dates = {x.trading_date for x in prior_day_sessions}
    week_dates = {x.trading_date for x in prior_week_sessions}
    prior_day = [c for c in candles_15m if c.timestamp.date() in day_dates]
    prior_week = [c for c in candles_15m if c.timestamp.date() in week_dates]
    levels: list[LiquidityLevel] = []
    if prior_day:
        levels.extend(previous_period_levels(prior_day, period_name="Day"))
    if prior_week:
        levels.extend(previous_period_levels(prior_week, period_name="Week"))

    tolerance = None
    if config.equal_high_low_tolerance_by_symbol is not None:
        tolerance = config.equal_high_low_tolerance_by_symbol.get(symbol)
    if tolerance is not None:
        # Use only completed prior sessions; the configured tolerance is a
        # per-symbol engineering parameter, never silently inferred from price.
        history = [c for c in candles_15m if c.timestamp.date() in (day_dates | week_dates)]
        for pool in equal_high_low_pools(history, tolerance=tolerance):
            levels.append(LiquidityLevel(
                "Relative Equal Highs" if pool.side == "buy_side" else "Relative Equal Lows",
                pool.level, pool.side, pool.source,
            ))

    context = None
    if prior_day and prior_week:
        week_high = max(c.high for c in prior_week)
        week_low = min(c.low for c in prior_week)
        context_obj = None
        if week_high > week_low:
            context_obj = build_market_context(
                current_price=current_price,
                dealing_range_high=week_high,
                dealing_range_low=week_low,
                previous_day_candles=prior_day,
                previous_week_candles=prior_week,
            )
        context = {
            "price_location_in_previous_week_range": context_obj.price_location if context_obj else "unavailable_dealing_range",
            "previous_week_high": week_high,
            "previous_week_low": week_low,
            "previous_week_equilibrium": context_obj.dealing_range.equilibrium if context_obj else None,
            "previous_day_high": max(c.high for c in prior_day),
            "previous_day_low": min(c.low for c in prior_day),
            "draws_above": tuple(context_obj.draws_above) if context_obj else (),
            "draws_below": tuple(context_obj.draws_below) if context_obj else (),
        }
    return tuple(levels), context

def _signal_id(symbol: str, model: str, direction: str, available_at: datetime,
               lower: Decimal, upper: Decimal, evidence_key: str = "") -> str:
    raw = "|".join((symbol, model, direction, available_at.isoformat(), str(lower), str(upper), evidence_key))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]

def _episode6_signal(
    symbol: str,
    company_name: str,
    candles_5m: Sequence[Candle],
    candles_1m: Sequence[Candle],
    levels: Sequence[LiquidityLevel],
    context: dict,
    config: StockICTScanConfig,
    scan_date: date,
    as_of: datetime,
) -> list[StockSignal]:
    recent = list(candles_5m[-config.max_5m_lookback_bars:])
    if len(recent) < config.pivot_left + config.pivot_right + 3:
        return []
    candidates = detect_ict_2022_episode6(
        recent,
        pivot_left=config.pivot_left,
        pivot_right=config.pivot_right,
        displacement_min_body_to_range=config.displacement_min_body_to_range,
        max_bars_after_sweep=config.max_bars_after_sweep,
        max_bars_after_mss=config.max_bars_after_mss,
        external_liquidity_levels=levels,
    )
    result_by_id: dict[str, StockSignal] = {}
    for candidate in candidates:
        available_at = recent[candidate.available_at_index].timestamp + timedelta(minutes=5)
        if available_at.date() != scan_date or available_at > as_of:
            continue
        gap = candidate.fvg
        lower, upper = gap.lower, gap.upper
        retest = next((
            c for c in candles_1m
            if c.timestamp >= available_at
            and c.timestamp + timedelta(minutes=1) <= as_of
            and c.low <= upper and c.high >= lower
        ), None)
        sweep = candidate.sweep
        if hasattr(sweep, "reference_swing"):
            sweep_name = f"Confirmed local swing {sweep.reference_swing.kind}"
            sweep_price = sweep.reference_swing.price
            sweep_extreme = sweep.extreme
        else:
            sweep_name = sweep.reference_name
            sweep_price = sweep.reference_price
            sweep_extreme = sweep.extreme
        targets = directional_target_candidates(candidate.direction, candidate.entry_reference, levels)
        signal_id = _signal_id(symbol, candidate.model, candidate.direction, available_at, lower, upper)
        signal_context = dict(context or {})
        signal_context["primary_liquidity_sweep"] = {
            "name": sweep_name, "price": sweep_price, "extreme": sweep_extreme,
        }
        signal = StockSignal(
            signal_id,
            symbol, company_name, candidate.model, candidate.direction,
            "ENTRY_ARMED" if retest else "QUALIFIED_WAITING_FOR_FVG_RETRACE",
            available_at, lower, upper, candidate.entry_reference,
            candidate.invalidation_references, sweep_name, sweep_price, sweep_extreme,
            recent[candidate.mss.candle_index].timestamp + timedelta(minutes=5),
            candidate.mss.broken_swing.price, candidate.mss.body_to_range,
            recent[gap.first_candle_index].timestamp,
            recent[gap.middle_candle_index].timestamp,
            recent[gap.third_candle_index].timestamp,
            retest.timestamp + timedelta(minutes=1) if retest else None,
            targets, signal_context,
            candidate.assumptions + (
                "setup detection uses completed 5m candles only",
                "1m FVG-zone intersection is a retest alert, not a guaranteed fill",
                "entry price and stop variant are not selected by the scanner",
                "multiple liquidity raids producing the same FVG are consolidated into one signal",
            ),
            candidate.source_id,
        )
        previous = result_by_id.get(signal_id)
        if previous is None:
            signal_context["additional_liquidity_sweeps"] = []
            result_by_id[signal_id] = replace(signal, context=signal_context)
        else:
            updated_context = dict(previous.context)
            additional = list(updated_context.get("additional_liquidity_sweeps", []))
            additional.append({"name": sweep_name, "price": sweep_price, "extreme": sweep_extreme})
            updated_context["additional_liquidity_sweeps"] = additional
            result_by_id[signal_id] = replace(previous, context=updated_context)
    return list(result_by_id.values())

def _silver_bullet_signals(
    symbol: str,
    company_name: str,
    candles_1m: Sequence[Candle],
    levels: Sequence[LiquidityLevel],
    context: dict,
    scan_date: date,
    as_of: datetime,
    session,
    current_price: Decimal,
) -> list[StockSignal]:
    if not candles_1m or not levels:
        return []
    windows = silver_bullet_windows_ist(scan_date)
    result = []
    for window in windows:
        # Only windows overlapping this NSE cash session are applicable.
        # Do not shift New York windows to force a match.
        if window.end <= session.open_at or window.start >= session.close_at:
            continue
        for direction, side in (("bullish", "buy_side"), ("bearish", "sell_side")):
            targets = [
                x for x in levels
                if x.side == side and (
                    x.price > current_price if direction == "bullish" else x.price < current_price
                )
            ]
            if direction == "bullish":
                targets.sort(key=lambda x: x.price)
            else:
                targets.sort(key=lambda x: x.price, reverse=True)
            candidate = None
            for target in targets:
                try:
                    candidate = detect_silver_bullet_candidate(
                        candles_1m, window=window, direction=direction,
                        draw_on_liquidity=target,
                        bar_duration=timedelta(minutes=1),
                        timestamp_role="start",
                    )
                except ValueError as exc:
                    if "draw-on-liquidity must be" in str(exc):
                        continue
                    raise
                if candidate is not None:
                    break
            if candidate is None:
                continue
            if candidate.fvg_completed_at > as_of or candidate.fvg_completed_at.date() != scan_date:
                continue
            retest_time = candles_1m[candidate.retest_candle_index].timestamp + timedelta(minutes=1)
            if retest_time > as_of:
                continue
            gap = candidate.fvg
            available_at = retest_time
            result.append(StockSignal(
                _signal_id(symbol, candidate.model, direction, available_at, gap.lower, gap.upper,
                           f"{candidate.draw_on_liquidity.name}:{candidate.draw_on_liquidity.price}"),
                symbol, company_name, candidate.model, direction, "ENTRY_ARMED",
                available_at, gap.lower, gap.upper, None, (),
                None, None, None, None, None, None,
                candles_1m[gap.first_candle_index].timestamp,
                candles_1m[gap.middle_candle_index].timestamp,
                candles_1m[gap.third_candle_index].timestamp,
                retest_time,
                (candidate.draw_on_liquidity,),
                {
                    **(context or {}),
                    "silver_bullet_window": candidate.window_name,
                    "window_start": candidate.window_start,
                    "window_end": candidate.window_end,
                },
                candidate.assumptions + (
                    "New York local window converted with IANA DST rules",
                    "candidate is only considered if the original window overlaps NSE cash hours",
                    "entry-zone retest is not a guaranteed broker fill",
                ),
                candidate.source_id,
            ))
    return result

class StockICTScanner:
    def __init__(self, config: StockICTScanConfig | None = None):
        self.config = config or StockICTScanConfig()

    def scan_universe(
        self,
        *,
        universe: UniverseSnapshot,
        store: StockCandleStore,
        calendar: ExchangeCalendar,
        scan_date: date,
        as_of: datetime,
    ) -> StockScanReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if len(universe.constituents) != 50 or len({x.symbol for x in universe.constituents}) != 50:
            raise ValueError("scanner requires exactly 50 unique NIFTY 50 constituents")
        if calendar.exchange != "NSE":
            raise ValueError("scanner requires the NSE calendar")
        session = calendar.session_for(scan_date)
        if session is None:
            raise ValueError("scan_date must be an explicitly configured NSE trading session")
        if as_of.date() != scan_date:
            raise ValueError("as_of date must equal scan_date")
        signals: list[StockSignal] = []
        statuses: list[StockScanStatus] = []
        ready = 0
        for member in universe.constituents:
            raw_1m = store.load_verified_candles(member.symbol, "1m")
            raw_5m = store.load_verified_candles(member.symbol, "5m")
            raw_15m = store.load_verified_candles(member.symbol, "15m")
            for timeframe, values in (("1m", raw_1m), ("5m", raw_5m), ("15m", raw_15m)):
                _validate_candles(values, member.symbol, timeframe)
            one = _completed(raw_1m, as_of, timedelta(minutes=1))[-self.config.max_1m_lookback_bars:]
            five = _completed(raw_5m, as_of, timedelta(minutes=5))[-self.config.max_5m_lookback_bars:]
            fifteen = _completed(raw_15m, as_of, timedelta(minutes=15))
            latest = one[-1].timestamp if one else None
            expected_by_tf = {
                "1m": [x for x in calendar.expected_candle_starts(scan_date, 1)
                       if x + timedelta(minutes=1) <= as_of.astimezone(calendar.timezone)],
                "5m": [x for x in calendar.expected_candle_starts(scan_date, 5)
                       if x + timedelta(minutes=5) <= as_of.astimezone(calendar.timezone)],
                "15m": [x for x in calendar.expected_candle_starts(scan_date, 15)
                        if x + timedelta(minutes=15) <= as_of.astimezone(calendar.timezone)],
            }
            observed_by_tf = {
                "1m": {c.timestamp.astimezone(calendar.timezone) for c in raw_1m},
                "5m": {c.timestamp.astimezone(calendar.timezone) for c in raw_5m},
                "15m": {c.timestamp.astimezone(calendar.timezone) for c in raw_15m},
            }
            missing_counts = {
                tf: sum(1 for stamp in expected if stamp not in observed_by_tf[tf])
                for tf, expected in expected_by_tf.items()
            }
            if not any(expected_by_tf.values()) or not one or not five or not fifteen or any(missing_counts.values()):
                if not any(expected_by_tf.values()):
                    reason = "waiting for first completed current-session candles"
                else:
                    reason = "current-session verified candle gaps: " + ", ".join(
                        f"{tf}={count}" for tf, count in missing_counts.items() if count
                    )
                statuses.append(StockScanStatus(member.symbol, member.company_name, "DATA_NOT_READY",
                    reason, len(one), len(five), len(fifteen), latest))
                continue
            ready += 1
            current_price = one[-1].close
            levels, context = _liquidity_context(
                member.symbol, fifteen, calendar, scan_date, current_price, self.config,
            )
            if self.config.enable_episode6:
                signals.extend(_episode6_signal(
                    member.symbol, member.company_name, five, one, levels, context,
                    self.config, scan_date, as_of,
                ))
            if self.config.enable_silver_bullet:
                signals.extend(_silver_bullet_signals(
                    member.symbol, member.company_name, one, levels, context,
                    scan_date, as_of, session, current_price,
                ))
            statuses.append(StockScanStatus(member.symbol, member.company_name, "READY",
                "verified historical data available", len(one), len(five), len(fifteen), latest))
        signals.sort(key=lambda x: (x.available_at, x.symbol, x.model_id, x.direction))
        return StockScanReport(scan_date, as_of, universe.snapshot_id, 50, ready,
                               tuple(signals), tuple(statuses))
