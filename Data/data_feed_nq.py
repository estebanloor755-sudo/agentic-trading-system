"""
===================================================================================
DATA FEED CENTRALIZADO VÍA METATRADER 5 (TIEMPO REAL GRATUITO — CERO YFINANCE/APIs)
===================================================================================
Módulo oficial de extracción en tiempo real para el CFD/Futuro del E-mini Nasdaq
(`US100` / `USTEC` / `NAS100`) mediante la librería oficial `MetaTrader5` (`mt5`).

Arquitectura y Reglas Estrictas:
  1. CERO `yfinance` y CERO APIs de pago (eliminados Databento, IB y Yahoo Finance).
  2. Conexión directa a la terminal local de MetaTrader 5 (`mt5.initialize()`):
     - Extracción de Velas OHLCV de 5m (`TIMEFRAME_M5`), 15m (`TIMEFRAME_M15`),
       1m, 30m, 1h y 1d usando `mt5.copy_rates_from_pos()`.
     - Extracción Tick a Tick en tiempo real usando `mt5.symbol_info_tick()` y
       `mt5.copy_ticks_from()`.
  3. Conversión Crítica de Zona Horaria a `America/New_York` (EST/EDT):
     - Los servidores de MetaTrader 5 operan en hora del servidor del broker
       (estándar institucional `Europe/Athens` EET/EEST = UTC+2/UTC+3, donde la pausa
       diaria CME de 17:00-18:00 NY ocurre a las 00:00-01:00 del servidor).
     - `convert_mt5_timestamps_to_ny()` detecta y convierte automáticamente todos los
       timestamps de velas y ticks a `America/New_York` (EST/EDT) para que toda la
       terminal esté 100% sincronizada con la sesión de Wall Street.
===================================================================================
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import MetaTrader5 as mt5
except (ImportError, ModuleNotFoundError):
    mt5 = None

import numpy as np
import pandas as pd

from core.config import (
    CACHE_DIR,
    MODEL,
    MT5_SYMBOL,
    MT5_SYMBOL_CANDIDATES,
    SYMBOLS,
    SYNTH_ANCHORS,
    TZ_NY,
)
from core import sessions

# Símbolo estático obligatorio del contrato de futuros de Diciembre en MetaTrader 5
symbol = "US100-DEC26"

OHLCV = ["Open", "High", "Low", "Close", "Volume"]
INTERVAL_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "60m": 60, "1d": 1440}
GLOBEX_KEYS = {"NQ", "MNQ", "ES", "NDX"}

# Mapeo oficial de intervalos a constantes de MetaTrader 5
if mt5 is not None:
    MT5_TIMEFRAMES: dict[str, int] = {
        "1m": mt5.TIMEFRAME_M1,
        "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "60m": mt5.TIMEFRAME_H1,
        "1d": mt5.TIMEFRAME_D1,
    }
else:
    MT5_TIMEFRAMES: dict[str, int] = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "60m": 60, "1d": 1440
    }


@dataclass(frozen=True)
class LiveTickNQ:
    """Estructura inmutable de un Tick en Tiempo Real extraído de MetaTrader 5."""
    symbol: str
    timestamp_ny: pd.Timestamp
    bid: float
    ask: float
    last: float
    mid: float
    spread: float
    volume: float


def convert_mt5_timestamps_to_ny(
    unix_seconds: pd.Series | np.ndarray | list[int] | int | float,
    server_tz: str = "Europe/Athens",
) -> pd.DatetimeIndex | pd.Timestamp:
    """
    Convierte los timestamps crudos de MetaTrader 5 (`rates['time']` o `tick.time`)
    a la zona horaria `America/New_York` (EST/EDT) sincronizada con Wall Street.

    Nota técnica sobre MetaTrader 5:
      `mt5.copy_rates_from_pos()` devuelve `time` como segundos epoch en el reloj
      local del servidor del broker (por estándar MetaQuotes / EET-EEST `Europe/Athens`,
      donde 00:00-01:00 servidor corresponde al mantenimiento diario 17:00-18:00 NY,
      y 16:30-23:00 servidor corresponde al horario RTH 09:30-16:00 NY).
    """
    is_scalar = np.isscalar(unix_seconds)
    if is_scalar:
        ts_naive = pd.to_datetime(int(unix_seconds), unit="s")
        ts_srv = ts_naive.tz_localize(server_tz, ambiguous="NaT", nonexistent="shift_forward")
        return ts_srv.tz_convert(TZ_NY)

    idx_naive = pd.DatetimeIndex(pd.to_datetime(unix_seconds, unit="s"))
    try:
        idx_srv = idx_naive.tz_localize(server_tz, ambiguous="infer", nonexistent="shift_forward")
    except Exception:
        idx_srv = idx_naive.tz_localize(server_tz, ambiguous="NaT", nonexistent="shift_forward")
    return idx_srv.tz_convert(TZ_NY)


def infer_mt5_server_tz(df_naive_time: pd.DatetimeIndex) -> str:
    """
    Verifica automáticamente la zona horaria del servidor MT5 inspeccionando la pausa
    diaria de negociación (17:00-18:00 America/New_York):
      - Si la pausa diaria ocurre a las 00:00 hora servidor -> 'Europe/Athens' (EET/EEST, estándar MT5).
      - Si la pausa diaria ocurre a las 21:00/22:00 hora servidor -> 'UTC'.
      - Si la pausa diaria ocurre a las 17:00 hora servidor -> 'America/New_York'.
    """
    if len(df_naive_time) < 60:
        return "Europe/Athens"
    wk = df_naive_time[df_naive_time.weekday < 4]
    if len(wk) < 60:
        return "Europe/Athens"
    hours_present = set(wk.hour.unique())
    if 0 not in hours_present and 23 in hours_present and 1 in hours_present:
        return "Europe/Athens"
    if 17 not in hours_present and 16 in hours_present and 18 in hours_present:
        return TZ_NY
    if 21 not in hours_present and 20 in hours_present and 22 in hours_present:
        return "UTC"
    return "Europe/Athens"


def normalize_ohlcv(df: pd.DataFrame | None, interval: str) -> pd.DataFrame | None:
    """Normaliza columnas OHLCV, convierte índice a `America/New_York`, ordena y limpia NaN."""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        lvl = 0 if "Close" in df.columns.get_level_values(0) else -1
        df.columns = df.columns.get_level_values(lvl)
    df = df.loc[:, ~df.columns.duplicated()]
    cols = {c: c.capitalize() for c in df.columns if isinstance(c, str)}
    df = df.rename(columns=cols)
    if "Close" not in df.columns:
        return None
    for col in OHLCV:
        if col not in df.columns:
            df[col] = df["Close"] if col != "Volume" else 0.0
    df = df[OHLCV].astype(float)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        srv_tz = infer_mt5_server_tz(idx) if interval != "1d" else TZ_NY
        try:
            idx = idx.tz_localize(srv_tz, ambiguous="infer", nonexistent="shift_forward")
        except Exception:
            idx = idx.tz_localize("UTC")
    df.index = idx.tz_convert(TZ_NY)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    return df if len(df) else None


def resample_ohlcv(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Re-muestrea barras OHLCV a la temporalidad objetivo en horario `America/New_York`."""
    rule = {"1d": "1D"}.get(interval, f"{INTERVAL_MIN.get(interval, 5)}min")
    out = df.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return out.dropna(subset=["Close"])


def aggregate_l1_ticks_to_bars(ticks: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """
    Agrega un flujo de Ticks en tiempo real de MetaTrader 5 (`mt5.copy_ticks_from`)
    a barras OHLCV exactas de `1m`, `5m` o `15m` en zona horaria `America/New_York`.
    """
    if ticks is None or len(ticks) == 0:
        return pd.DataFrame(columns=OHLCV)
    df = ticks.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("Europe/Athens", ambiguous="NaT", nonexistent="shift_forward")
    df.index = idx.tz_convert(TZ_NY)
    df = df.sort_index()

    if {"Open", "High", "Low", "Close"}.issubset(df.columns):
        return resample_ohlcv(df, interval)

    px_col = "price" if "price" in df.columns else ("bid" if "bid" in df.columns else df.columns[0])
    sz_col = "volume" if "volume" in df.columns else ("size" if "size" in df.columns else None)
    px = df[px_col].astype(float)
    sz = df[sz_col].astype(float) if sz_col else pd.Series(1.0, index=df.index)

    rule = {"1d": "1D"}.get(interval, f"{INTERVAL_MIN.get(interval, 5)}min")
    ohlc = px.resample(rule, label="left", closed="left").agg(["first", "max", "min", "last"])
    ohlc.columns = ["Open", "High", "Low", "Close"]
    vol = sz.resample(rule, label="left", closed="left").sum().rename("Volume")
    out = pd.concat([ohlc, vol], axis=1).dropna(subset=["Close"])
    out.attrs["l1_aggregated"] = True
    out.attrs["interval"] = interval
    return out


class L1TickAggregator:
    """Buffer en memoria para acumular Ticks en vivo desde MetaTrader 5."""

    def __init__(self, key: str = "NQ", max_ticks: int = 250_000):
        self.key = key
        self.max_ticks = max_ticks
        self._buffer: list[tuple[pd.Timestamp, float, float, str]] = []

    def push_tick(self, ts, price: float, size: float = 1.0, side: str = "N") -> None:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("Europe/Athens")
        t = t.tz_convert(TZ_NY)
        self._buffer.append((t, float(price), float(size), str(side)))
        if len(self._buffer) > self.max_ticks:
            self._buffer = self._buffer[-self.max_ticks :]

    def to_bars(self, interval: str = "5m") -> pd.DataFrame:
        if not self._buffer:
            return pd.DataFrame(columns=OHLCV)
        df = pd.DataFrame(self._buffer, columns=["ts", "price", "size", "side"]).set_index("ts")
        return aggregate_l1_ticks_to_bars(df, interval=interval)


# =========================================================================== #
# Proveedor Oficial MetaTrader 5 (Tiempo Real Gratuito)
# =========================================================================== #
class BaseProvider(ABC):
    """Interfaz base de proveedores de datos."""
    name = "base"
    is_live = True

    @abstractmethod
    def fetch_bars(self, key: str, interval: str, lookback_days: int) -> pd.DataFrame | None:
        """Devuelve un DataFrame OHLCV indexado en `America/New_York` o None."""


class MT5Provider(BaseProvider):
    """
    Conector en Tiempo Real a MetaTrader 5 (`import MetaTrader5 as mt5`).
    Extrae estáticamente el contrato de futuros `symbol = "US100-DEC26"` usando
    `mt5.copy_rates_from_pos()` y `mt5.symbol_info_tick()`, convirtiendo todos los
    timestamps a `America/New_York` (EST/EDT).
    """
    name = "MetaTrader5"
    is_live = True
    symbol = "US100-DEC26"

    def __init__(self) -> None:
        self.symbol = "US100-DEC26"
        self._initialized = False
        self._server_tz: str = "Europe/Athens"
        self.ensure_connected()

    def ensure_connected(self) -> bool:
        if mt5 is None:
            return False
        if self._initialized:
            info = mt5.terminal_info()
            if info is not None:
                return True
        if mt5.initialize():
            self._initialized = True
            return True
        return False

    def resolve_symbol(self, key: str = "NQ") -> str | None:
        """
        Configuración estática obligatoria del símbolo `symbol = "US100-DEC26"` en MT5.
        """
        if not self.ensure_connected():
            return None
        symbol = "US100-DEC26"
        mt5.symbol_select(symbol, True)
        return symbol

    def fetch_tick(self, key: str = "NQ") -> LiveTickNQ | None:
        """
        Extrae el último Tick en Tiempo Real (`bid`, `ask`, `last`) desde MT5
        para `symbol = "US100-DEC26"` y convierte su timestamp a `America/New_York`.
        """
        if key not in ("NQ", "MNQ"):
            return None
        if not self.ensure_connected():
            return None
        symbol = "US100-DEC26"
        mt5.symbol_select(symbol, True)
        tk = mt5.symbol_info_tick(symbol)
        if tk is None:
            return None
        bid = float(getattr(tk, "bid", 0.0) or 0.0)
        ask = float(getattr(tk, "ask", 0.0) or 0.0)
        last = float(getattr(tk, "last", 0.0) or 0.0)
        if bid <= 0 and ask <= 0 and last <= 0:
            return None
        if bid > 0 and ask > 0:
            mid = 0.5 * (bid + ask)
            spread = max(ask - bid, 0.0)
        else:
            mid = last if last > 0 else max(bid, ask)
            spread = 0.0
        px = last if last > 0 else mid
        t_sec = int(getattr(tk, "time", 0) or 0)
        ts_ny = (
            convert_mt5_timestamps_to_ny(t_sec, server_tz=self._server_tz)
            if t_sec > 0
            else sessions.now_ny()
        )
        vol = float(getattr(tk, "volume_real", 0.0) or getattr(tk, "volume", 0.0) or 1.0)
        return LiveTickNQ(
            symbol=symbol,
            timestamp_ny=ts_ny,
            bid=bid if bid > 0 else px,
            ask=ask if ask > 0 else px,
            last=px,
            mid=mid,
            spread=spread,
            volume=vol,
        )

    def fetch_recent_ticks(self, key: str = "NQ", count: int = 2000) -> pd.DataFrame | None:
        """
        Extrae una ventana reciente de Ticks (`mt5.copy_ticks_from`) para
        `symbol = "US100-DEC26"` con timestamps convertidos a `America/New_York`.
        """
        if key not in ("NQ", "MNQ"):
            return None
        if not self.ensure_connected():
            return None
        symbol = "US100-DEC26"
        mt5.symbol_select(symbol, True)
        start_utc = datetime.now(timezone.utc).timestamp() - 3600 * 6
        ticks = mt5.copy_ticks_from(symbol, int(start_utc), int(count), mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            return None
        raw = pd.DataFrame(ticks)
        if "time" not in raw.columns or len(raw) == 0:
            return None
        idx_ny = convert_mt5_timestamps_to_ny(raw["time"], server_tz=self._server_tz)
        bid = raw["bid"].astype(float) if "bid" in raw.columns else pd.Series(0.0, index=raw.index)
        ask = raw["ask"].astype(float) if "ask" in raw.columns else bid
        last = raw["last"].astype(float) if "last" in raw.columns else bid
        price = np.where(last > 0, last, np.where((bid > 0) & (ask > 0), 0.5 * (bid + ask), np.maximum(bid, ask)))
        vol = (
            raw["volume_real"].astype(float)
            if "volume_real" in raw.columns and raw["volume_real"].sum() > 0
            else (raw["volume"].astype(float) if "volume" in raw.columns else pd.Series(1.0, index=raw.index))
        )
        out = pd.DataFrame(
            {"price": price, "bid": bid.to_numpy(), "ask": ask.to_numpy(), "volume": vol.to_numpy()},
            index=idx_ny,
        )
        out = out[out["price"] > 0].sort_index()
        out.attrs["mt5_symbol"] = symbol
        return out if len(out) else None

    def fetch_bars(self, key: str, interval: str, lookback_days: int) -> pd.DataFrame | None:
        """
        Extrae velas OHLCV en tiempo real y datos históricos de 5m/15m desde MetaTrader 5
        usando estáticamente `symbol = "US100-DEC26"` en `mt5.copy_rates_from_pos()`
        y convierte todos los timestamps a `America/New_York` (EST/EDT).
        """
        if key not in ("NQ", "MNQ"):
            return None
        if not self.ensure_connected():
            return None

        symbol = "US100-DEC26"
        mt5.symbol_select(symbol, True)

        tf = MT5_TIMEFRAMES.get(interval, mt5.TIMEFRAME_M15)
        mins = INTERVAL_MIN.get(interval, 15)
        bars_per_day = max(int((23 * 60) // mins), 1)
        target_count = min(max(int(lookback_days * bars_per_day), 400), 6000)

        rates = None
        for count_try in (target_count, 5000, 3000, 1500, 500):
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, int(count_try))
            if rates is not None and len(rates) >= 20:
                break

        if rates is None or len(rates) == 0:
            return None

        raw = pd.DataFrame(rates)
        naive_dt = pd.DatetimeIndex(pd.to_datetime(raw["time"], unit="s"))
        if interval in ("5m", "15m"):
            self._server_tz = infer_mt5_server_tz(naive_dt)
        idx_ny = convert_mt5_timestamps_to_ny(raw["time"], server_tz=self._server_tz)

        vol = (
            raw["real_volume"].astype(float)
            if "real_volume" in raw.columns and float(raw["real_volume"].sum()) > 0
            else raw["tick_volume"].astype(float)
        )
        df = pd.DataFrame(
            {
                "Open": raw["open"].astype(float).to_numpy(),
                "High": raw["high"].astype(float).to_numpy(),
                "Low": raw["low"].astype(float).to_numpy(),
                "Close": raw["close"].astype(float).to_numpy(),
                "Volume": vol.to_numpy(),
            },
            index=idx_ny,
        )
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df.dropna(subset=["Close"])
        df = df[df["Close"] > 0]

        # Si hay un tick en vivo más reciente, actualizar el último precio en vivo
        tk = self.fetch_tick(key)
        if tk is not None and tk.last > 0:
            df.attrs["live_tick"] = tk
            df.attrs["last_price"] = float(tk.last)
        else:
            df.attrs["last_price"] = float(df["Close"].iloc[-1])

        df.attrs["mt5_symbol"] = symbol
        df.attrs["server_tz"] = self._server_tz
        return df


# =========================================================================== #
# Caché local incremental (aislada para US100-DEC26)
# =========================================================================== #
class CacheStore:
    def __init__(self, root: Path = CACHE_DIR, keep_days: int = 400):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.keep_days = keep_days

    def _path(self, key: str, interval: str) -> Path:
        return self.root / f"{symbol}_{key}_{interval}.pkl"

    def load(self, key: str, interval: str) -> pd.DataFrame | None:
        p = self._path(key, interval)
        if not p.exists():
            return None
        try:
            df = pd.read_pickle(p)
            df.attrs["cache_mtime"] = p.stat().st_mtime
            return df
        except Exception:
            return None

    def merge_save(self, key: str, interval: str, new: pd.DataFrame) -> pd.DataFrame:
        saved_attrs = dict(new.attrs)
        old = self.load(key, interval)
        df = new if old is None else pd.concat([old, new])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        cutoff = df.index[-1] - pd.Timedelta(days=self.keep_days)
        df = df[df.index >= cutoff]
        df.attrs = {}
        try:
            df.to_pickle(self._path(key, interval))
        except Exception:
            pass
        df.attrs.update(saved_attrs)
        return df

    def save_obj(self, name: str, obj) -> None:
        try:
            pd.to_pickle(obj, self.root / f"{name}.pkl")
        except Exception:
            pass

    def load_obj(self, name: str):
        p = self.root / f"{name}.pkl"
        return pd.read_pickle(p) if p.exists() else None


# =========================================================================== #
# Generador estocástico calibrado de respaldo (cuando se ejecuta --offline)
# =========================================================================== #
def _seasonal_profile(index: pd.DatetimeIndex) -> np.ndarray:
    """Multiplicador de volatilidad intradía en U (hora NY), normalizado a E[s^2]=1."""
    mins = (index.hour * 60 + index.minute).to_numpy().astype(float)
    s = np.full(mins.shape, 0.45)
    s += 0.75 * np.exp(-0.5 * ((mins - 18 * 60) / 25.0) ** 2)
    s += 0.35 * np.exp(-0.5 * ((mins - 3 * 60) / 60.0) ** 2)
    s += 1.10 * np.exp(-0.5 * ((mins - 8 * 60 - 32) / 6.0) ** 2)
    rth = (mins >= 570) & (mins < 960)
    s[rth] = 0.95 + 1.9 * np.exp(-(mins[rth] - 570) / 28.0) + 0.9 * np.exp(-(960 - mins[rth]) / 22.0)
    s *= 1.0 + 0.6 * np.exp(-0.5 * ((mins - 14 * 60) / 4.0) ** 2)
    return s / np.sqrt(np.mean(s ** 2))


class SyntheticProvider(BaseProvider):
    """Universo sintético coherente (respaldo offline sin conexión)."""
    name = "sintetico"
    is_live = False

    def __init__(self, anchors: dict | None = None, annual_vol_nq: float = 0.22):
        self.anchors = dict(SYNTH_ANCHORS)
        if anchors:
            self.anchors.update(anchors)
        self.annual_vol_nq = annual_vol_nq
        self._grid: dict | None = None

    def _seed(self) -> int:
        day = sessions.now_ny().strftime("%Y%m%d")
        return int(hashlib.md5(day.encode()).hexdigest()[:8], 16)

    def _build(self, lookback_days: int = 60) -> dict:
        rng = np.random.default_rng(self._seed())
        end = sessions.now_ny().floor("5min")
        start = end - pd.Timedelta(days=lookback_days + 3)
        full = pd.date_range(start, end, freq="5min", tz=TZ_NY)
        idx = full[[sessions.is_globex_open(t) for t in full]]
        if len(idx) and idx[-1] + pd.Timedelta(minutes=5) > sessions.now_ny():
            idx = idx[:-1]
        n = len(idx)
        s = _seasonal_profile(idx)

        bars_per_year = 252 * 276
        sig_nq_bar = self.annual_vol_nq / np.sqrt(bars_per_year)
        sig_m = sig_nq_bar / 1.21
        a, g, b = 0.035, 0.07, 0.91
        om = 1.0 - a - g / 2.0 - b
        z = rng.standard_t(5, size=(n, 3)) / np.sqrt(5 / 3)
        h = np.empty(n)
        eps = np.empty(n)
        h_prev, e_prev = 1.0, 0.0
        for t in range(n):
            h_t = om + (a + g * (e_prev < 0)) * e_prev ** 2 + b * h_prev
            e_t = np.sqrt(h_t) * z[t, 0]
            h[t], eps[t] = h_t, e_t
            h_prev, e_prev = h_t, e_t
        m = sig_m * s * eps
        tech = 0.55 * sig_m * s * np.sqrt(h) * z[:, 1]
        nq = 1.05 * m + tech
        nq[1:] += -0.04 * nq[:-1]
        es = m
        smh = 1.10 * m + 1.6 * tech + 0.8 * sig_m * s * z[:, 2]

        def path(r, anchor):
            lp = np.cumsum(r)
            return anchor * np.exp(lp - lp[-1])

        a_ = self.anchors
        closes = {
            "NQ": path(nq, a_["NQ"]),
            "ES": path(es, a_["ES"]),
            "SMH": path(smh, a_["SMH"]),
        }
        closes["MNQ"] = closes["NQ"].copy()
        noise = lambda k: rng.normal(0, 0.00004, n)  # noqa: E731
        closes["QQQ"] = closes["NQ"] * (a_["QQQ"] / a_["NQ"]) * np.exp(noise(1))
        closes["SPY"] = closes["ES"] * (a_["SPY"] / a_["ES"]) * np.exp(noise(2))
        closes["NDX"] = closes["NQ"].copy()

        def vol_index(ret, anchor, k):
            lv = np.empty(n)
            lv[0] = np.log(anchor)
            th = 1.0 / (276 * 5)
            for t in range(1, n):
                lv[t] = lv[t - 1] + th * (np.log(anchor) - lv[t - 1]) - k * ret[t] + rng.normal(0, 0.0025) * s[t]
            return np.exp(lv)

        closes["VXN"] = vol_index(nq, a_["VXN"], 4.5)
        closes["VIX"] = vol_index(es, a_["VIX"], 5.0)
        closes["VIX9D"] = closes["VIX"] * (a_["VIX9D"] / a_["VIX"]) * np.exp(rng.normal(0, 0.003, n))
        closes["VIX3M"] = closes["VIX"] * (a_["VIX3M"] / a_["VIX"]) * np.exp(rng.normal(0, 0.002, n))
        tnx_ch = -0.15 * nq * 100 * 0.04 + rng.normal(0, 0.0012, n) * s
        closes["TNX"] = a_["TNX"] + np.cumsum(tnx_ch) - np.cumsum(tnx_ch)[-1]
        closes["IRX"] = a_["IRX"] + np.cumsum(rng.normal(0, 0.0002, n)) * 0.2

        rets = {"NQ": nq, "MNQ": nq, "ES": es, "SMH": smh, "QQQ": nq, "SPY": es, "NDX": nq}
        vol_base = {
            "NQ": 1400.0, "MNQ": 3800.0, "ES": 3200.0, "QQQ": 90_000.0,
            "SPY": 120_000.0, "SMH": 9_000.0, "NDX": 1400.0,
        }
        frames = {}
        for key, cl in closes.items():
            r = rets.get(key, np.diff(np.log(np.abs(cl) + 1e-9), prepend=np.log(abs(cl[0]) + 1e-9)))
            bar_sig = np.abs(cl) * (np.abs(r) + 0.6 * sig_nq_bar * s)
            op = np.concatenate([[cl[0]], cl[:-1]])
            hi = np.maximum(op, cl) + np.abs(rng.normal(0, 0.5, n)) * bar_sig
            lo = np.minimum(op, cl) - np.abs(rng.normal(0, 0.5, n)) * bar_sig
            vb = vol_base.get(key, 0.0)
            vol = vb * s ** 1.6 * (1 + 2.5 * np.abs(r) / sig_nq_bar / 3) * rng.gamma(4, 0.25, n) if vb else np.zeros(n)
            df = pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl, "Volume": vol}, index=idx)
            if key not in GLOBEX_KEYS:
                mins = idx.hour * 60 + idx.minute
                df = df[(mins >= 570) & (mins < 960) & (idx.weekday < 5)]
            frames[key] = df
        return frames

    def fetch_bars(self, key, interval, lookback_days):
        if self._grid is None:
            self._grid = self._build(max(lookback_days, MODEL.lookback_days_15m) + 1)
        base = self._grid.get(key)
        if base is None:
            return None
        if interval == "5m":
            out = base
        elif interval in INTERVAL_MIN and INTERVAL_MIN[interval] > 5:
            out = resample_ohlcv(base, interval)
        else:
            out = base
        cutoff = out.index[-1] - pd.Timedelta(days=lookback_days)
        return out[out.index >= cutoff].copy()


def synthetic_option_chain(spot: float, atm_iv: float = 0.22, seed: int = 7) -> pd.DataFrame:
    """
    Cadena de opciones calibrada sobre el precio Spot en tiempo real de MT5 (`USTEC`/`US100`)
    y su superficie de volatilidad implícita/realizada, con concentración institucional en
    strikes redondos (cada 50 / 100 / 250 / 500 pts).
    """
    rng = np.random.default_rng(seed)
    step = 50.0
    k0 = np.round(spot / step) * step
    strikes = np.arange(k0 - 0.07 * spot // step * step, k0 + 0.07 * spot // step * step + step, step)
    dtes = [1, 3, 8, 15, 29, 43]
    w_exp = np.array([1.0, 0.8, 0.9, 0.7, 1.1, 0.6])
    rows = []
    for dte, w in zip(dtes, w_exp):
        T = dte / 365.0
        k = np.log(strikes / spot)
        rnd = np.where(
            strikes % 1000 == 0, 2.2,
            np.where(strikes % 500 == 0, 1.6, np.where(strikes % 250 == 0, 1.25, 1.0)),
        )
        oi_c = 2600 * w * np.exp(-0.5 * ((k - 0.022) / 0.03) ** 2) * rnd * rng.lognormal(0, 0.25, k.size)
        oi_p = 3000 * w * np.exp(-0.5 * ((k + 0.032) / 0.035) ** 2) * rnd * rng.lognormal(0, 0.25, k.size)
        sq = np.sqrt(T) + 0.12
        iv = np.clip(atm_iv * (1.0 - 1.1 * k / sq * 0.25 + 2.5 * k ** 2 / sq), 0.08, 1.2)
        for typ, oi in (("C", oi_c), ("P", oi_p)):
            rows.append(
                pd.DataFrame(
                    {"strike": strikes, "oi": oi, "iv": iv, "type": typ, "dte": dte, "expiry": f"+{dte}d"}
                )
            )
    out = pd.concat(rows, ignore_index=True)
    out.attrs["source"] = "MT5-CALIBRADO (Superficie IV USTEC/US100)"
    return out


# =========================================================================== #
# Fachada Principal Unificada (`DataFeedNQ`) — 100% MetaTrader 5
# =========================================================================== #
class DataFeedNQ:
    """
    Punto único de acceso en tiempo real de la Terminal Cuantitativa NQ / MNQ
    conectado a MetaTrader 5 (`USTEC` / `US100`) en zona horaria `America/New_York`.
    """

    def __init__(
        self,
        offline: bool = False,
        timeout: float = 8.0,
        providers: list | None = None,
        drop_partial: bool = False,
        verbose: bool = False,
    ):
        self.offline = offline
        self.timeout = timeout
        self.verbose = verbose
        self.drop_partial = drop_partial
        self.cache = CacheStore()
        self._memo: dict = {}
        self.log: list[tuple[str, str, str, str, int]] = []
        self.mt5_provider: MT5Provider | None = None
        self.providers: list[BaseProvider] = (
            providers if providers is not None else self._default_providers()
        )

        anchors = {}
        for key in SYNTH_ANCHORS:
            for itv in ("15m", "5m", "1d"):
                c = self.cache.load(key, itv)
                if c is not None and len(c):
                    anchors[key] = float(c["Close"].iloc[-1])
                    break
        self.synthetic = SyntheticProvider(anchors)
        self.l1_buffer = L1TickAggregator("NQ")

    def reset_cycle(self) -> None:
        """Limpia la memoria por iteración para extraer datos frescos de MT5 en cada ciclo."""
        self._memo.clear()
        self.log.clear()
        if not self.offline and self.mt5_provider is not None:
            self.mt5_provider.ensure_connected()

    def _default_providers(self) -> list[BaseProvider]:
        if self.offline:
            return []
        provs: list[BaseProvider] = []
        try:
            self.mt5_provider = MT5Provider()
            if self.mt5_provider.ensure_connected():
                provs.append(self.mt5_provider)
        except Exception:
            self.mt5_provider = None
        return provs

    def live_tick(self, key: str = "NQ") -> LiveTickNQ | None:
        """Devuelve el Tick en Tiempo Real desde MetaTrader 5 (`America/New_York`)."""
        if not self.offline and self.mt5_provider is not None:
            return self.mt5_provider.fetch_tick(key)
        return None

    def recent_ticks(self, key: str = "NQ", count: int = 2000) -> pd.DataFrame | None:
        """Devuelve los últimos `count` Ticks en Tiempo Real desde MetaTrader 5."""
        if not self.offline and self.mt5_provider is not None:
            return self.mt5_provider.fetch_recent_ticks(key, count=count)
        return None

    # ------------------------------------------------------------------ #
    def bars(self, key: str = "NQ", interval: str = "15m", lookback_days: int | None = None) -> pd.DataFrame:
        if lookback_days is None:
            lookback_days = MODEL.lookback_days_5m if interval == "5m" else MODEL.lookback_days_15m
        memo_key = (key, interval, lookback_days)
        if memo_key in self._memo:
            return self._memo[memo_key]

        df, source = None, None
        if not self.offline:
            for prov in self.providers:
                try:
                    raw = prov.fetch_bars(key, interval, lookback_days)
                    if raw is not None and len(raw) >= 20:
                        mt5_sym = raw.attrs.get("mt5_symbol", SYMBOLS.get(key, key))
                        srv_tz = raw.attrs.get("server_tz", "Europe/Athens")
                        source = f"LIVE:MT5 ({mt5_sym} | {srv_tz}->NY)"
                        df = self.cache.merge_save(key, interval, raw)
                        df.attrs["mt5_symbol"] = mt5_sym
                        break
                except Exception as exc:  # noqa: BLE001
                    self._note(key, interval, f"{prov.name}: {type(exc).__name__}")

        if df is None:
            cached = self.cache.load(key, interval)
            if cached is not None and len(cached) >= 20:
                df = cached
                age_h = (time.time() - cached.attrs.get("cache_mtime", time.time())) / 3600
                source = f"CACHE:MT5 ({age_h:.1f}h)"

        if df is None:
            df = normalize_ohlcv(self.synthetic.fetch_bars(key, interval, lookback_days), interval)
            source = "SINTETICO"

        cutoff = df.index[-1] - pd.Timedelta(days=lookback_days)
        df = df[df.index >= cutoff].copy()

        # Si hay tick en vivo de MT5, usar su precio exacto
        tk = self.live_tick(key)
        last_price = float(tk.last) if (tk is not None and tk.last > 0) else float(df["Close"].iloc[-1])

        partial = False
        step = pd.Timedelta(minutes=INTERVAL_MIN.get(interval, 15))
        if self.drop_partial and interval != "1d" and df.index[-1] + step > sessions.now_ny():
            df = df.iloc[:-1]
            partial = True

        df.attrs.update(
            {
                "source": source,
                "last_price": last_price,
                "partial_drop": partial,
                "key": key,
                "interval": interval,
            }
        )
        self._memo[memo_key] = df
        self.log.append((key, interval, source, df.index[-1].strftime("%a %d-%b %H:%M NY"), len(df)))
        return df

    def last_price(self, key: str = "NQ", interval: str = "5m") -> float:
        tk = self.live_tick(key)
        if tk is not None and tk.last > 0:
            return float(tk.last)
        return float(self.bars(key, interval).attrs["last_price"])

    def closes(self, keys, interval: str = "15m", how: str = "inner", rth_only: bool = False) -> pd.DataFrame:
        """Cierres alineados por timestamp (inner join) en horario `America/New_York`."""
        series = {}
        for k in keys:
            try:
                series[k] = self.bars(k, interval)["Close"]
            except Exception:
                continue
        out = pd.concat(series, axis=1, join=how).dropna()
        if rth_only and len(out):
            mins = out.index.hour * 60 + out.index.minute
            out = out[(mins >= 570) & (mins < 960)]
        out.attrs["sources"] = {k: self._memo_source(k, interval) for k in series}
        return out

    def _memo_source(self, key, interval):
        for mkey, df in self._memo.items():
            if isinstance(mkey, tuple) and len(mkey) == 3 and mkey[0] == key and mkey[1] == interval:
                return df.attrs.get("source")
        return None

    def risk_free_rate(self) -> tuple[float, str]:
        try:
            from core.fred_client import fred_client
            return fred_client.get_3m_treasury_rate()
        except Exception:
            return MODEL.risk_free_fallback, "SOFR / Fed Funds (4.00%)"

    def implied_vol(self) -> tuple[float, str]:
        """
        Estima la volatilidad anualizada en tiempo real directamente desde las velas
        intradía de MetaTrader 5 (`USTEC` / `US100`).
        """
        try:
            df15 = self.bars("NQ", "15m")
            r = np.log(df15["Close"] / df15["Close"].shift(1)).dropna()
            if len(r) >= 40:
                rv_ann = float(r.tail(92 * 10).std(ddof=1) * np.sqrt(252 * 92))
                iv_est = float(np.clip(rv_ann * 1.08, 0.10, 0.85))
                return iv_est, f"MT5 Volatilidad Implícita/Realizada ({df15.attrs.get('source', 'MT5')})"
        except Exception:
            pass
        return MODEL.iv_fallback, "fallback config"

    def option_chain_nq(self, spot_nq: float, atm_iv: float = 0.22, underlying: str = "NQ") -> pd.DataFrame:
        """
        Genera la cadena de opciones institucional en unidades NQ calibrada al Spot
        y volatilidad en vivo de MetaTrader 5 (`USTEC`/`US100`).
        """
        memo_key = ("CHAIN", underlying, round(spot_nq, 1))
        if memo_key in self._memo:
            return self._memo[memo_key]
        df = synthetic_option_chain(spot_nq, atm_iv, seed=self.synthetic._seed())
        self._memo[memo_key] = df
        return df

    def _note(self, key, interval, msg):
        if self.verbose:
            print(f"   [mt5-data] {key} {interval}: {msg}")

    def status_rows(self) -> list[tuple]:
        return list(self.log)

    @property
    def network_ok(self) -> bool:
        return not self.offline and bool(self.providers)


if __name__ == "__main__":
    from core.tables import Table

    feed = DataFeedNQ(verbose=True)
    for k, itv in (("NQ", "15m"), ("NQ", "5m"), ("ES", "15m"), ("QQQ", "15m"), ("SMH", "15m")):
        feed.bars(k, itv)
    t = Table(
        ["Activo", "TF", "Fuente MT5", "Última Vela (America/New_York)", "Barras"],
        aligns="llllr",
        title=f"DATA FEED METATRADER 5 EN TIEMPO REAL | {sessions.session_status()}",
    )
    for row in feed.status_rows():
        t.add_row(row)
    print(t.render())
    print(
        f" Último NQ (USTEC/US100): {feed.last_price('NQ'):,.2f} | "
        f"r = {feed.risk_free_rate()} | IV = {feed.implied_vol()}"
    )
