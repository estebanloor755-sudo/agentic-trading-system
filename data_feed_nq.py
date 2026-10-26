"""
Módulo Centralizado de Datos en Tiempo Real vía MetaTrader 5 (`import MetaTrader5 as mt5`)
configurado estáticamente sobre el contrato de futuros de Diciembre:
`symbol = "US100-DEC26"` ($20/pt NQ y $2/pt MNQ).

Extrae Ticks en tiempo real (`mt5.symbol_info_tick`, `mt5.copy_ticks_from`) y Velas OHLCV
de 5m y 15m (`mt5.copy_rates_from_pos(symbol, ...)`), convirtiendo todos los timestamps a
la zona horaria `America/New_York` (EST/EDT) para sincronización exacta con Wall Street.
"""
from __future__ import annotations

try:
    import MetaTrader5 as mt5
except (ImportError, ModuleNotFoundError):
    mt5 = None

from Data.data_feed_nq import (
    GLOBEX_KEYS,
    INTERVAL_MIN,
    MT5_TIMEFRAMES,
    OHLCV,
    BaseProvider,
    CacheStore,
    DataFeedNQ,
    L1TickAggregator,
    LiveTickNQ,
    MT5Provider,
    SyntheticProvider,
    aggregate_l1_ticks_to_bars,
    convert_mt5_timestamps_to_ny,
    infer_mt5_server_tz,
    normalize_ohlcv,
    resample_ohlcv,
    synthetic_option_chain,
)

# Símbolo estático obligatorio del contrato de futuros de Diciembre en MetaTrader 5
symbol = "US100-DEC26"

__all__ = [
    "mt5",
    "symbol",
    "GLOBEX_KEYS",
    "INTERVAL_MIN",
    "MT5_TIMEFRAMES",
    "OHLCV",
    "BaseProvider",
    "CacheStore",
    "DataFeedNQ",
    "L1TickAggregator",
    "LiveTickNQ",
    "MT5Provider",
    "SyntheticProvider",
    "aggregate_l1_ticks_to_bars",
    "convert_mt5_timestamps_to_ny",
    "infer_mt5_server_tz",
    "normalize_ohlcv",
    "resample_ohlcv",
    "synthetic_option_chain",
]

if __name__ == "__main__":
    from core import sessions
    from core.tables import Table

    feed = DataFeedNQ(verbose=True)
    for k, itv in (("NQ", "15m"), ("NQ", "5m")):
        feed.bars(k, itv)
    t = Table(
        ["Activo", "TF", "Fuente MT5", "Última Vela (America/New_York)", "Barras"],
        aligns="llllr",
        title=f"DATA FEED CENTRAL NQ VÍA METATRADER 5 ({symbol}) | {sessions.session_status()}",
    )
    for row in feed.status_rows():
        t.add_row(row)
    print(t.render())
    print(
        f" Último NQ ({symbol}): {feed.last_price('NQ'):,.2f} | "
        f"r = {feed.risk_free_rate()} | IV = {feed.implied_vol()}"
    )
