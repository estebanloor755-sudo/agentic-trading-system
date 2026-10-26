"""
Calendario de sesiones CME Globex / Nueva York para el E-mini Nasdaq.

* Globex: domingo 18:00 ET -> viernes 17:00 ET, pausa diaria 17:00-18:00 ET.
* RTH (cash):  09:30 - 16:00 ET.
* Vencimientos trimestrales (H, M, U, Z): tercer viernes; roll ~8 días antes.

Nota: no modela feriados CME (Thanksgiving, Navidad, etc.). Los huecos de
datos se manejan igualmente porque las proyecciones parten del último bar real.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from core.config import SESSION_WINDOWS, TZ_NY

QUARTERLY_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def now_ny() -> pd.Timestamp:
    return pd.Timestamp.now(tz=TZ_NY)


def to_ny(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize(TZ_NY) if ts.tzinfo is None else ts.tz_convert(TZ_NY)


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def is_globex_open(ts) -> bool:
    """True si el instante (hora NY) está dentro de la sesión Globex."""
    ts = to_ny(ts)
    wd, t = ts.weekday(), ts.time()
    if wd == 5:                      # sábado
        return False
    if wd == 6:                      # domingo: abre 18:00
        return t >= dt.time(18, 0)
    if wd == 4:                      # viernes: cierra 17:00
        return t < dt.time(17, 0)
    return not (dt.time(17, 0) <= t < dt.time(18, 0))


def is_rth(ts) -> bool:
    ts = to_ny(ts)
    return ts.weekday() < 5 and dt.time(9, 30) <= ts.time() < dt.time(16, 0)


def in_window(ts, name: str) -> bool:
    ts = to_ny(ts)
    a, b = SESSION_WINDOWS[name]
    return ts.weekday() < 5 and _hm(a) <= ts.time() < _hm(b)


def next_bars(last_ts, n: int, freq: str = "15min") -> pd.DatetimeIndex:
    """Siguientes n inicios de barra válidos en Globex tras last_ts (etiqueta = inicio de barra)."""
    step = pd.Timedelta(freq)
    t = to_ny(last_ts).floor(freq) + step
    out = []
    guard = 0
    while len(out) < n and guard < n * 400:
        if is_globex_open(t):
            out.append(t)
            t += step
        else:
            t = _next_open(t)
        guard += 1
    return pd.DatetimeIndex(out)


def _at(ts: pd.Timestamp, days: int = 0, hours: int = 0, minutes: int = 0) -> pd.Timestamp:
    """Hora de reloj de pared NY (segura ante cambios DST, que ocurren en domingo)."""
    naive = ts.tz_localize(None).normalize() + pd.Timedelta(days=days, hours=hours, minutes=minutes)
    return naive.tz_localize(TZ_NY, ambiguous=True, nonexistent="shift_forward")


def _next_open(t: pd.Timestamp) -> pd.Timestamp:
    """Salta al siguiente instante de reapertura Globex."""
    wd = t.weekday()
    if wd == 4 and t.time() >= dt.time(17, 0):     # viernes tras cierre -> domingo 18:00
        return _at(t, days=2, hours=18)
    if wd == 5:                                       # sábado -> domingo 18:00
        return _at(t, days=1, hours=18)
    if wd == 6 and t.time() < dt.time(18, 0):         # domingo antes de abrir
        return _at(t, hours=18)
    if dt.time(17, 0) <= t.time() < dt.time(18, 0):   # pausa diaria
        return _at(t, hours=18)
    return t + pd.Timedelta(minutes=15)


def next_session_window(ref, start: str = "08:00", n: int = 32, freq: str = "15min") -> pd.DatetimeIndex:
    """Ventana operativa de n barras empezando a `start` (NY) del próximo día hábil >= ref."""
    ref = to_ny(ref)
    sh, sm = map(int, start.split(":"))
    for k in range(0, 8):
        cand = _at(ref, days=k, hours=sh, minutes=sm)
        if cand.weekday() < 5 and cand > ref:
            return pd.date_range(cand, periods=n, freq=freq)
    return pd.date_range(_at(ref, days=1, hours=sh, minutes=sm), periods=n, freq=freq)


def session_status(ts=None) -> str:
    ts = to_ny(ts if ts is not None else now_ny())
    if not is_globex_open(ts):
        if ts.weekday() >= 5 or (ts.weekday() == 4 and ts.time() >= dt.time(17, 0)):
            return "CERRADO (fin de semana) - reabre domingo 18:00 ET"
        return "PAUSA CME (17:00-18:00 ET)"
    if in_window(ts, "APERTURA_NY"):
        return "ABIERTO - VENTANA APERTURA NY (09:30-11:45)"
    if in_window(ts, "CIERRE_NY"):
        return "ABIERTO - VENTANA CIERRE NY (15:00-16:00)"
    if is_rth(ts):
        return "ABIERTO - RTH (mediodía)"
    return "ABIERTO - GLOBEX OVERNIGHT"


def third_friday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 15)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7)


def nq_front_contract(ref=None, roll_days: int = 8) -> tuple[str, dt.date]:
    """Contrato trimestral activo (con roll ~8 días antes del vencimiento)."""
    ref = to_ny(ref if ref is not None else now_ny()).date()
    for yr in (ref.year, ref.year + 1):
        for mo in (3, 6, 9, 12):
            exp = third_friday(yr, mo)
            if ref <= exp - dt.timedelta(days=roll_days):
                return f"NQ{QUARTERLY_CODES[mo]}{str(yr)[-2:]}", exp
    exp = third_friday(ref.year + 1, 3)
    return f"NQH{str(ref.year + 1)[-2:]}", exp


def year_fraction_to(expiry: dt.date, ref=None) -> float:
    ref = to_ny(ref if ref is not None else now_ny())
    exp_ts = pd.Timestamp(expiry).tz_localize(TZ_NY) + pd.Timedelta(hours=9, minutes=30)
    return max((exp_ts - ref).total_seconds() / (365.0 * 86400.0), 1.0 / 365.0)


def slot_of(index: pd.DatetimeIndex, minutes: int = 15) -> np.ndarray:
    """Índice de franja intradía (0..95 para 15m) en hora NY."""
    idx = index.tz_convert(TZ_NY) if index.tz is not None else index
    return ((idx.hour * 60 + idx.minute) // minutes).to_numpy()
