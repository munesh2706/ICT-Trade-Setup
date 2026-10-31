from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from ict_engine.context import LiquidityLevel
from ict_engine.models import Candle
from ict_engine.paper_store import StockPaperStore
from ict_engine.paper_trading import PaperTradingConfig, StockPaperTradingEngine
from ict_engine.stock_feed import StockInstrument
from ict_engine.stock_scanner import StockScanReport, StockSignal
from ict_engine.stock_storage import StockCandleStore

IST = ZoneInfo("Asia/Kolkata")

def signal():
    return StockSignal(
        "signal-abc", "ABC", "ABC Ltd", "ICT_2022_Mentorship_Episode_6",
        "bullish", "ENTRY_ARMED",
        datetime(2026,10,30,10,0,tzinfo=IST),
        D("100"), D("101"), D("100.50"), (D("99"),D("99.50")),
        "Confirmed local swing low", D("99.50"), D("98.80"),
        datetime(2026,10,30,9,55,tzinfo=IST), D("99.50"), D("0.8"),
        datetime(2026,10,30,9,45,tzinfo=IST),
        datetime(2026,10,30,9,50,tzinfo=IST),
        datetime(2026,10,30,9,55,tzinfo=IST),
        None,
        (LiquidityLevel("Previous Day High",D("110"),"buy_side","completed_prior_day"),),
        {}, ("test assumption",), "ICT2022_EP6",
    )

def report(sig, as_of):
    return StockScanReport(date(2026,10,30),as_of,"universe-1",50,50,(sig,),())

def candle(minute, o, h, l, c):
    return Candle(datetime(2026,10,30,10,minute,tzinfo=IST),
                  D(str(o)),D(str(h)),D(str(l)),D(str(c)),D("1000"))

def add_verified_candles(store, snapshot_id, bars):
    store.create_snapshot(snapshot_id,"universe-1","paper engine test bars")
    store.store_candles(snapshot_id,"ABC","1m","12345",bars)
    store.finalize(snapshot_id,"ACQUIRED")
    store.mark_universe_snapshots_verified("universe-1")

def make_engine(tmp_path):
    candle_store=StockCandleStore(tmp_path/"candles.sqlite")
    journal=StockPaperStore(tmp_path/"paper.sqlite")
    instrument=StockInstrument("ABC","ABC Ltd","ABC-EQ","12345","NSE","nse_cm",
                               tick_size=D("0.05"))
    config=PaperTradingConfig(
        starting_equity=D("100000"),
        round_trip_fees_per_share=D("0"),
        round_trip_slippage_points=D("0"),
    )
    return candle_store,journal,StockPaperTradingEngine(config,{"ABC":instrument})

def test_paper_engine_persists_entry_exit_and_daily_risk_across_restarts(tmp_path):
    candles,journal,engine=make_engine(tmp_path)
    sig=signal()

    first=engine.process_scan_report(
        report(sig,datetime(2026,10,30,10,0,tzinfo=IST)),
        candles=candles,journal=journal,
    )
    assert first.pending_signals==1
    assert first.open_positions==0

    add_verified_candles(candles,"bars-entry",[
        candle(0,100.5,100.7,100.3,100.4),
        candle(1,100.4,101.0,100.2,100.8),
    ])
    second=engine.process_scan_report(
        report(sig,datetime(2026,10,30,10,2,tzinfo=IST)),
        candles=candles,journal=journal,
    )
    assert second.positions_opened==1
    assert second.open_positions==1

    restarted=StockPaperStore(tmp_path/"paper.sqlite")
    assert len(restarted.load_open_positions())==1

    add_verified_candles(candles,"bars-exit",[
        candle(2,105,111,104,110.5),
    ])
    third=engine.process_scan_report(
        report(sig,datetime(2026,10,30,10,3,tzinfo=IST)),
        candles=candles,journal=restarted,
    )
    assert third.positions_closed==1
    assert third.open_positions==0
    assert restarted.signal_status(sig.signal_id).value=="closed"
    risk=restarted.load_daily_risk(date(2026,10,30),D("100000"))
    assert risk.open_positions==0
    assert risk.trades_today==1
    assert risk.realized_pnl>D("0")
    assert len(restarted.closed_trade_rows())==1

def test_paper_engine_rejects_same_bar_entry_and_stop_ambiguity(tmp_path):
    candles,journal,engine=make_engine(tmp_path)
    sig=signal()
    engine.process_scan_report(
        report(sig,datetime(2026,10,30,10,0,tzinfo=IST)),
        candles=candles,journal=journal,
    )
    add_verified_candles(candles,"bars-ambiguous",[
        candle(0,100.5,101,98.5,100),
    ])
    result=engine.process_scan_report(
        report(sig,datetime(2026,10,30,10,1,tzinfo=IST)),
        candles=candles,journal=journal,
    )
    assert result.positions_opened==0
    assert result.signals_no_trade==1
    assert result.open_positions==0
