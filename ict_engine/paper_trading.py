"""Broker-free, restart-safe paper execution for stock ICT signals.

Only completed Angel One historical candles are used for fills/exits. No broker
order endpoint is imported or called. Silver Bullet remains alert-only until
its entry chronology is implemented without retroactive fills.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path

from .market_calendar import ExchangeCalendar
from .paper_execution import calculate_position_size
from .risk_controls import DailyRiskState, RiskLimits
from .signal_lifecycle import SignalStatus
from .stock_feed import StockInstrument
from .stock_scanner import StockScanReport, StockSignal
from .stock_storage import StockCandleStore
from .paper_store import StockPaperStore
from .trade_simulator import PaperPosition, process_position_bar

ZERO = Decimal("0")
ONE = Decimal("1")

@dataclass(frozen=True, slots=True)
class PaperTradingConfig:
    starting_equity: Decimal
    round_trip_fees_per_share: Decimal
    round_trip_slippage_points: Decimal
    risk_per_trade_fraction: Decimal = Decimal("0.005")
    max_daily_loss_fraction: Decimal = Decimal("0.02")
    max_open_positions: int = 1
    max_trades_per_day: int = 5
    max_consecutive_losses: int = 3
    entry_variant: str = "detector_reference"
    stop_reference_index: int = 0
    target_selection: str = "nearest"
    max_entry_wait_minutes: int = 90
    quantity_step: Decimal = ONE

    def __post_init__(self):
        if self.starting_equity <= ZERO:
            raise ValueError("starting_equity must be positive")
        if self.round_trip_fees_per_share < ZERO or self.round_trip_slippage_points < ZERO:
            raise ValueError("fees and slippage must be explicit non-negative values")
        if not ZERO < self.risk_per_trade_fraction <= ONE:
            raise ValueError("risk_per_trade_fraction must be in (0,1]")
        if not ZERO < self.max_daily_loss_fraction <= ONE:
            raise ValueError("max_daily_loss_fraction must be in (0,1]")
        if self.max_daily_loss_fraction < self.risk_per_trade_fraction:
            raise ValueError("max_daily_loss_fraction cannot be smaller than risk_per_trade_fraction")
        if min(self.max_open_positions, self.max_trades_per_day,
               self.max_consecutive_losses, self.max_entry_wait_minutes) < 1:
            raise ValueError("risk limits and entry wait must be positive")
        if self.entry_variant not in {"detector_reference", "fvg_ce", "proximal_edge", "distal_edge"}:
            raise ValueError("unsupported entry_variant")
        if self.stop_reference_index not in {0, 1}:
            raise ValueError("stop_reference_index must be 0 or 1")
        if self.target_selection not in {"nearest", "farthest"}:
            raise ValueError("target_selection must be nearest or farthest")
        if self.quantity_step <= ZERO:
            raise ValueError("quantity_step must be positive")

@dataclass(frozen=True, slots=True)
class PaperEngineReport:
    scan_date: str
    signals_registered: int
    positions_opened: int
    positions_closed: int
    signals_rejected: int
    signals_no_trade: int
    pending_signals: int
    open_positions: int
    realized_pnl_today: Decimal
    actions: tuple[dict, ...]


def load_paper_trading_config(path: str | Path) -> PaperTradingConfig:
    """Load explicit paper settings; required equity/cost inputs cannot be guessed."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        required = ("starting_equity", "round_trip_fees_per_share", "round_trip_slippage_points")
        missing = [key for key in required if payload.get(key) is None]
        if missing:
            raise ValueError("paper config must explicitly set: " + ", ".join(missing))
        return PaperTradingConfig(
            starting_equity=Decimal(str(payload["starting_equity"])),
            round_trip_fees_per_share=Decimal(str(payload["round_trip_fees_per_share"])),
            round_trip_slippage_points=Decimal(str(payload["round_trip_slippage_points"])),
            risk_per_trade_fraction=Decimal(str(payload.get("risk_per_trade_fraction", "0.005"))),
            max_daily_loss_fraction=Decimal(str(payload.get("max_daily_loss_fraction", "0.02"))),
            max_open_positions=int(payload.get("max_open_positions", 1)),
            max_trades_per_day=int(payload.get("max_trades_per_day", 5)),
            max_consecutive_losses=int(payload.get("max_consecutive_losses", 3)),
            entry_variant=str(payload.get("entry_variant", "detector_reference")),
            stop_reference_index=int(payload.get("stop_reference_index", 0)),
            target_selection=str(payload.get("target_selection", "nearest")),
            max_entry_wait_minutes=int(payload.get("max_entry_wait_minutes", 90)),
            quantity_step=Decimal(str(payload.get("quantity_step", "1"))),
        )
    except Exception as exc:
        raise ValueError(f"invalid paper trading configuration: {type(exc).__name__}: {exc}") from None

def _quantize(price: Decimal, tick: Decimal, rounding) -> Decimal:
    if tick <= ZERO:
        raise ValueError("tick size must be positive")
    return (price / tick).to_integral_value(rounding=rounding) * tick

def _entry_price(signal: StockSignal, config: PaperTradingConfig) -> Decimal | None:
    if config.entry_variant == "detector_reference":
        return signal.entry_reference
    if config.entry_variant == "fvg_ce":
        return (signal.entry_zone_lower + signal.entry_zone_upper) / Decimal("2")
    if config.entry_variant == "proximal_edge":
        return signal.entry_zone_upper if signal.direction == "bullish" else signal.entry_zone_lower
    return signal.entry_zone_lower if signal.direction == "bullish" else signal.entry_zone_upper

def _signal_evidence(signal: StockSignal) -> dict:
    return asdict(signal)

class StockPaperTradingEngine:
    def __init__(self, config: PaperTradingConfig, instruments: dict[str, StockInstrument]):
        self.config = config
        self.instruments = dict(instruments)

    def _limits(self) -> RiskLimits:
        return RiskLimits(
            max_daily_loss=self.config.starting_equity * self.config.max_daily_loss_fraction,
            max_risk_per_trade=self.config.starting_equity * self.config.risk_per_trade_fraction,
            max_open_positions=self.config.max_open_positions,
            max_trades_per_day=self.config.max_trades_per_day,
            max_consecutive_losses=self.config.max_consecutive_losses,
        )

    def _event(self, store: StockPaperStore, signal: StockSignal, status: SignalStatus,
               report: StockScanReport, reason: str, suffix: str):
        return store.append_event(
            f"{signal.signal_id}:{suffix}", signal.signal_id, report.as_of,
            status, reason, evidence_ref=signal.source_id,
        )

    def _build_prices(self, signal: StockSignal, instrument: StockInstrument):
        tick = instrument.tick_size
        if tick is None or tick <= ZERO:
            raise ValueError("Angel One instrument master tick size is unavailable")
        raw_entry = _entry_price(signal, self.config)
        if raw_entry is None:
            raise ValueError("this ICT model has no configured entry-price reference")
        if signal.direction == "bullish":
            entry = _quantize(raw_entry, tick, ROUND_FLOOR)
            if len(signal.invalidation_references) <= self.config.stop_reference_index:
                raise ValueError("no source-backed bullish invalidation reference")
            stop = _quantize(signal.invalidation_references[self.config.stop_reference_index], tick, ROUND_FLOOR)
            targets = [x.price for x in signal.draw_targets if x.price > entry]
            target_rounding = ROUND_CEILING
        else:
            entry = _quantize(raw_entry, tick, ROUND_CEILING)
            if len(signal.invalidation_references) <= self.config.stop_reference_index:
                raise ValueError("no source-backed bearish invalidation reference")
            stop = _quantize(signal.invalidation_references[self.config.stop_reference_index], tick, ROUND_CEILING)
            targets = [x.price for x in signal.draw_targets if x.price < entry]
            target_rounding = ROUND_FLOOR
        if not signal.entry_zone_lower <= entry <= signal.entry_zone_upper:
            raise ValueError("tick-rounded entry lies outside the FVG zone")
        if not targets:
            raise ValueError("no directional liquidity target beyond the entry")
        if signal.direction == "bullish":
            target_raw = min(targets) if self.config.target_selection == "nearest" else max(targets)
        else:
            target_raw = max(targets) if self.config.target_selection == "nearest" else min(targets)
        target = _quantize(target_raw, tick, target_rounding)
        if signal.direction == "bullish" and not stop < entry < target:
            raise ValueError("tick-rounded bullish stop/entry/target ordering is invalid")
        if signal.direction == "bearish" and not target < entry < stop:
            raise ValueError("tick-rounded bearish target/entry/stop ordering is invalid")
        return entry, stop, target

    def _process_open_positions(self, report: StockScanReport, candles: StockCandleStore,
                                journal: StockPaperStore, risk: DailyRiskState, *,
                                calendar: ExchangeCalendar | None = None,
                                cas_eligible_symbols: set[str] | None = None) -> int:
        closed = 0
        for position in journal.load_open_positions():
            last = journal.last_processed_bar(position.position_id)
            bars = candles.load_verified_candles(
                position.instrument_id, "1m", start=last, end=report.as_of,
            )
            for bar in bars:
                if calendar is not None and position.instrument_id in (cas_eligible_symbols or set()):
                    if not calendar.is_continuous_trading_at(bar.timestamp, cas_eligible=True):
                        continue
                if bar.timestamp <= last or bar.timestamp + timedelta(minutes=1) > report.as_of:
                    continue
                exit_ = process_position_bar(position, bar, bar_duration=timedelta(minutes=1))
                if exit_ is not None:
                    signal_id = journal.position_signal_id(position.position_id)
                    if journal.close_position(exit_, signal_id):
                        risk.record_close(exit_.net_pnl)
                        closed += 1
                    break
                journal.update_position_progress(position.position_id, bar.timestamp)
        return closed

    def _try_entry(self, signal: StockSignal, report: StockScanReport,
                   candles: StockCandleStore, journal: StockPaperStore,
                   risk: DailyRiskState, limits: RiskLimits, *,
                   calendar: ExchangeCalendar | None = None,
                   cas_eligible_symbols: set[str] | None = None,
                   not_before: datetime | None = None) -> str:
        if "SILVER_BULLET" in signal.model_id.upper():
            self._event(journal, signal, SignalStatus.NO_TRADE, report,
                        "Silver Bullet entry chronology is alert-only; no retroactive fill is permitted",
                        "no-trade-silver-bullet")
            return "no_trade"
        instrument = self.instruments.get(signal.symbol)
        if instrument is None:
            self._event(journal, signal, SignalStatus.CANCELLED_DATA, report,
                        "Angel One instrument mapping is unavailable", "cancelled-no-instrument")
            return "rejected"
        try:
            entry, stop, target = self._build_prices(signal, instrument)
        except ValueError as exc:
            self._event(journal, signal, SignalStatus.NO_TRADE, report, str(exc), "no-trade-price-policy")
            return "no_trade"

        first_seen = journal.signal_created_at(signal.signal_id)
        signal_start = max(first_seen, signal.available_at)
        if report.as_of - signal_start > timedelta(minutes=self.config.max_entry_wait_minutes):
            self._event(journal, signal, SignalStatus.MISSED, report,
                        "FVG limit entry expired without a verified fill", "missed-entry-expired")
            return "rejected"
        # Watchlist activation and prior-trade exit boundaries prevent retroactive fills.
        scan_start = max(signal_start, not_before) if not_before is not None else signal_start

        bars = candles.load_verified_candles(signal.symbol, "1m", start=scan_start, end=report.as_of)
        for bar in bars:
            if calendar is not None and signal.symbol in (cas_eligible_symbols or set()):
                if not calendar.is_continuous_trading_at(bar.timestamp, cas_eligible=True):
                    continue
            if bar.timestamp < scan_start or bar.timestamp + timedelta(minutes=1) > report.as_of:
                continue
            long_side = signal.direction == "bullish"
            entry_hit = bar.low <= entry <= bar.high
            stop_hit = bar.low <= stop if long_side else bar.high >= stop
            target_hit = bar.high >= target if long_side else bar.low <= target

            if entry_hit and (stop_hit or target_hit):
                self._event(journal, signal, SignalStatus.NO_TRADE, report,
                            "Entry, stop or target touched in the same OHLC bar; intrabar chronology is unknowable",
                            "no-trade-ambiguous-entry-bar")
                return "no_trade"
            if not entry_hit and stop_hit:
                self._event(journal, signal, SignalStatus.INVALIDATED, report,
                            "Invalidation level traded before the FVG entry price", "invalidated-before-entry")
                return "rejected"
            if not entry_hit and target_hit:
                self._event(journal, signal, SignalStatus.MISSED, report,
                            "Directional liquidity target traded before entry", "missed-target-before-entry")
                return "rejected"
            if not entry_hit:
                continue

            fill_price = entry
            if long_side and bar.open < entry:
                fill_price = bar.open
            elif not long_side and bar.open > entry:
                fill_price = bar.open
            try:
                sizing = calculate_position_size(
                    risk_budget=self.config.starting_equity * self.config.risk_per_trade_fraction,
                    entry=fill_price, stop=stop, point_value=ONE,
                    quantity_step=self.config.quantity_step,
                    round_trip_fees_per_unit=self.config.round_trip_fees_per_share,
                    round_trip_slippage_points=self.config.round_trip_slippage_points,
                )
            except ValueError as exc:
                self._event(journal, signal, SignalStatus.REJECTED_RISK, report,
                            f"Position sizing rejected: {exc}", "rejected-position-size")
                return "rejected"
            decision = risk.evaluate_entry(limits, sizing.planned_risk)
            if not decision.allowed:
                self._event(journal, signal, SignalStatus.REJECTED_RISK, report,
                            "Risk guard blocked entry: " + ",".join(decision.reasons),
                            "rejected-risk-limits")
                return "rejected"

            position = PaperPosition(
                position_id="paper_" + signal.signal_id,
                instrument_id=signal.symbol, model_id=signal.model_id,
                direction="long" if long_side else "short",
                entry_time=bar.timestamp, entry_price=fill_price,
                stop=stop, target=target, quantity=sizing.quantity,
                point_value=ONE,
                round_trip_fees_per_unit=self.config.round_trip_fees_per_share,
                round_trip_slippage_points=self.config.round_trip_slippage_points,
            )
            if journal.open_position(position, signal.signal_id):
                risk.record_entry(limits, sizing.planned_risk)
                return "opened"
            return "pending"
        return "pending"


    def expire_pending_signals(self, journal: StockPaperStore, session_close) -> int:
        """Expire unfilled intraday candidates at the strategy's continuous-session close."""
        expired = 0
        for pending in journal.pending_signals():
            if pending["created_at"] > session_close:
                continue
            event_id = f'{pending["signal_id"]}:expired-session:{session_close.date().isoformat()}'
            if journal.append_event(
                event_id, pending["signal_id"], session_close, SignalStatus.EXPIRED,
                "Unfilled ICT setup expired at the end of its continuous-trading session",
                evidence_ref="session_close",
            ):
                expired += 1
        return expired

    def process_scan_report(self, report: StockScanReport, *,
                            candles: StockCandleStore,
                            journal: StockPaperStore,
                            calendar: ExchangeCalendar | None = None,
                            cas_eligible_symbols: set[str] | None = None,
                            eligible_symbols: set[str] | None = None,
                            eligible_directions: dict[str, str] | None = None,
                            signal_priorities: dict[str, float] | None = None,
                            eligible_since: dict[str, datetime] | None = None) -> PaperEngineReport:
        cas_eligible_symbols = set(cas_eligible_symbols or ())
        risk = journal.load_daily_risk(report.scan_date, self.config.starting_equity)
        limits = self._limits()
        closed = self._process_open_positions(
            report, candles, journal, risk, calendar=calendar,
            cas_eligible_symbols=cas_eligible_symbols,
        )
        registered = opened = rejected = no_trade = 0
        actions = []
        # The exit bar of the previous position cannot also open the next one.
        latest_exit = None
        for row in journal.closed_trade_rows():
            try:
                stamp = datetime.fromisoformat(str(row.get("exit_time", "")))
                latest_exit = stamp if latest_exit is None or stamp > latest_exit else latest_exit
            except (TypeError, ValueError):
                continue
        trade_slot_not_before = latest_exit + timedelta(minutes=1) if latest_exit is not None else None
        priorities = signal_priorities or {}
        ordered_signals = sorted(
            report.signals,
            key=lambda item: (-float(priorities.get(item.symbol, 0.0)),
                              item.available_at, item.symbol, item.model_id),
        )
        for signal in ordered_signals:
            if journal.register_signal(signal, evidence=_signal_evidence(signal), observed_at=report.as_of):
                registered += 1
            current_status = journal.signal_status(signal.signal_id)
            if "SILVER_BULLET" in signal.model_id.upper() and current_status == SignalStatus.QUALIFIED:
                self._event(journal, signal, SignalStatus.NO_TRADE, report,
                            "Silver Bullet remains an alert-only model until its entry chronology is implemented",
                            "no-trade-silver-bullet")
                no_trade += 1
                actions.append({"signal_id": signal.signal_id, "symbol": signal.symbol, "action": "alert_only"})
                continue
            if current_status != SignalStatus.ENTRY_ARMED:
                continue
            if journal.has_position_for_signal(signal.signal_id):
                continue
            if eligible_symbols is not None and signal.symbol not in eligible_symbols:
                continue
            if eligible_directions is not None and eligible_directions.get(signal.symbol) != signal.direction:
                continue
            # Leave candidates pending while the global trade slot is occupied.
            # They cannot be retroactively filled after that position closes.
            if journal.load_open_positions():
                continue
            not_before = (eligible_since or {}).get(signal.symbol)
            if trade_slot_not_before is not None:
                not_before = max(not_before, trade_slot_not_before) if not_before is not None else trade_slot_not_before
            action = self._try_entry(
                signal, report, candles, journal, risk, limits,
                calendar=calendar, cas_eligible_symbols=cas_eligible_symbols,
                not_before=not_before,
            )
            actions.append({"signal_id": signal.signal_id, "symbol": signal.symbol, "action": action})
            if action == "opened":
                opened += 1
            elif action == "rejected":
                rejected += 1
            elif action == "no_trade":
                no_trade += 1
        journal.save_daily_risk(report.scan_date, self.config.starting_equity, risk)
        return PaperEngineReport(
            report.scan_date.isoformat(), registered, opened, closed, rejected,
            no_trade, sum(1 for x in report.signals if journal.signal_status(x.signal_id) == SignalStatus.ENTRY_ARMED),
            len(journal.load_open_positions()), risk.realized_pnl, tuple(actions),
        )
