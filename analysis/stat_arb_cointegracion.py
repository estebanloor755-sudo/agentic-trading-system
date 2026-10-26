# %% [STATISTICAL ARBITRAGE (STATARB) & COINTEGRACION INTRADIA | NQ vs ES, SMH & QQQ]
"""
Motor de Arbitraje Estadístico (StatArb) y Cointegración Intradía para NQ=F:
  * Evalúa la cointegración de Engle-Granger (regresión en log-precios + test
    Augmented Dickey-Fuller sobre el spread residual) para los pares:
      1. `NQ=F` vs `ES=F` (Spread Inter-Índice Nasdaq / S&P 500 en 15m y 5m)
      2. `NQ=F` vs `SMH`  (Spread Nasdaq / Semiconductores en 15m RTH)
      3. `NQ=F` vs `QQQ`  (Spread Futuro NQ / ETF Cash QQQ en 15m RTH)
  * Calcula la Vida Media de Reversión Ornstein-Uhlenbeck (Half-Life en barras),
    el Ratio de Cobertura Dinámico (Hedge Ratio β), el Z-Score causal del spread
    y el desajuste equivalente en puntos de NQ antes de que se cierre la anomalía.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ES_POINT_VALUE, NQ, THEME
from core.mathx import adf_test, ols, rolling_zscore


def analizar_par_cointegrado(
    closes: pd.DataFrame,
    col_y: str,
    col_x: str,
    label: str,
    z_window: int = 40,
) -> dict:
    df = closes[[col_y, col_x]].dropna().tail(600)
    y_raw = df[col_y].to_numpy(dtype=float)
    x_raw = df[col_x].to_numpy(dtype=float)
    ly = np.log(y_raw)
    lx = np.log(x_raw)

    reg = ols(ly, lx, add_const=True)
    alpha_c = float(reg["coef"][0])
    beta_c = float(reg["coef"][1])
    spread = reg["resid"]

    adf = adf_test(spread)
    t_stat = float(adf["stat"])
    cv_5 = float(adf["cv_eg"]["5%"])
    cv_10 = float(adf["cv_eg"]["10%"])
    cointegrated = t_stat <= cv_10

    # Ornstein-Uhlenbeck Half-Life: d(spread)_t = a + phi * spread_{t-1} + e_t
    ds = np.diff(spread)
    ou_reg = ols(ds, spread[:-1], add_const=True)
    phi_ou = float(ou_reg["coef"][1])
    if -0.95 < phi_ou < -1e-4:
        half_life = -math.log(2.0) / math.log(1.0 + phi_ou)
    else:
        half_life = 45.0

    w = min(z_window, max(len(spread) // 3, 12))
    z_arr = rolling_zscore(spread, window=w)
    z_now = float(z_arr[-1]) if np.isfinite(z_arr[-1]) else 0.0

    # Media rodante del spread para medir cuántos puntos de NQ equivalen a volver a Z=0
    s_ser = pd.Series(spread, index=df.index)
    s_mean = float(s_ser.rolling(w, min_periods=5).mean().iloc[-1])
    dev_log = float(spread[-1] - s_mean)
    spot_y = float(y_raw[-1])
    spot_x = float(x_raw[-1])
    target_rev_pts = -dev_log * spot_y  # puntos que NQ debe moverse para cerrar el spread

    if z_now >= 2.0:
        signal = f">>> SHORT NQ / LONG {col_x} (Z={z_now:+.2f} SD -> Obj: {target_rev_pts:+.1f} pts NQ)"
    elif z_now <= -2.0:
        signal = f">>> LONG NQ / SHORT {col_x} (Z={z_now:+.2f} SD -> Obj: {target_rev_pts:+.1f} pts NQ)"
    elif z_now >= 1.25:
        signal = f"NQ Caro vs {col_x} (Vigilar techo para Short StatArb -> {target_rev_pts:+.1f} pts)"
    elif z_now <= -1.25:
        signal = f"NQ Barato vs {col_x} (Vigilar piso para Long StatArb -> {target_rev_pts:+.1f} pts)"
    else:
        signal = f"Spread en Equilibrio Estadístico (Desajuste: {target_rev_pts:+.1f} pts NQ)"

    return {
        "label": label,
        "col_x": col_x,
        "spot_y": spot_y,
        "spot_x": spot_x,
        "alpha": alpha_c,
        "beta": beta_c,
        "r2": float(reg["r2"]),
        "adf_stat": t_stat,
        "cv_5": cv_5,
        "cv_10": cv_10,
        "cointegrated": cointegrated,
        "half_life_bars": float(np.clip(half_life, 1.0, 250.0)),
        "z_now": z_now,
        "target_rev_pts": target_rev_pts,
        "signal": signal,
        "index": df.index,
        "z_series": z_arr,
        "spread_pts_series": (spread - s_ser.rolling(w, min_periods=5).mean().to_numpy()) * spot_y,
    }


def ejecutar_stat_arb_cointegracion(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    cl_globex_15 = feed.closes(["NQ", "ES"], interval="15m", rth_only=False)
    cl_globex_5 = feed.closes(["NQ", "ES"], interval="5m", rth_only=False)
    cl_rth_15 = feed.closes(["NQ", "SMH", "QQQ"], interval="15m", rth_only=True)

    p_nq_es_15 = analizar_par_cointegrado(cl_globex_15, "NQ", "ES", "NQ vs ES (15m Macro)", z_window=40)
    p_nq_es_5 = analizar_par_cointegrado(cl_globex_5, "NQ", "ES", "NQ vs ES (5m Ejecución)", z_window=48)
    p_nq_smh_15 = analizar_par_cointegrado(cl_rth_15, "NQ", "SMH", "NQ vs SMH Semis (15m RTH)", z_window=32)
    p_nq_qqq_15 = analizar_par_cointegrado(cl_rth_15, "NQ", "QQQ", "NQ vs QQQ Cash (15m RTH)", z_window=32)

    pairs = [p_nq_es_15, p_nq_es_5, p_nq_smh_15, p_nq_qqq_15]
    spot_nq = p_nq_es_15["spot_y"]
    spot_es = p_nq_es_15["spot_x"]

    # Ratio nocional de contratos para spread neutro en dólares entre NQ ($20/pt) y ES ($50/pt)
    notional_nq = spot_nq * NQ.point_value
    notional_es = spot_es * ES_POINT_VALUE
    es_per_nq = (p_nq_es_15["beta"] * notional_nq) / max(notional_es, 1.0)

    print("\n" + banner(
        f"STATISTICAL ARBITRAGE (STATARB) & COINTEGRACION INTRADIA | NQ: {spot_nq:,.2f} | ES: {spot_es:,.2f}",
        f"Hedge Ratio Nocional NQ/ES: 1 NQ (${notional_nq:,.0f}) vs {es_per_nq:.2f} ES (${notional_es:,.0f}/ct) ó 10 MNQ vs 2 MES"
    ))
    print(kv_block([
        ("Spread NQ/ES (15m)", f"Z = {p_nq_es_15['z_now']:+.2f} SD | ADF t = {p_nq_es_15['adf_stat']:.2f} | Half-Life = {p_nq_es_15['half_life_bars']:.1f} barras | Ajuste NQ: {p_nq_es_15['target_rev_pts']:+.1f} pts"),
        ("Spread NQ/ES (5m)", f"Z = {p_nq_es_5['z_now']:+.2f} SD | ADF t = {p_nq_es_5['adf_stat']:.2f} | Half-Life = {p_nq_es_5['half_life_bars']:.1f} barras | Ajuste NQ: {p_nq_es_5['target_rev_pts']:+.1f} pts"),
        ("Spread NQ/SMH (15m)", f"Z = {p_nq_smh_15['z_now']:+.2f} SD | ADF t = {p_nq_smh_15['adf_stat']:.2f} | Half-Life = {p_nq_smh_15['half_life_bars']:.1f} barras | Ajuste NQ: {p_nq_smh_15['target_rev_pts']:+.1f} pts"),
    ]))

    t = Table(
        ["Par Cointegrado", "Hedge β", "R²", "ADF t-Stat", "Estado Coint.", "Half-Life (OU)", "Z-Score Spread", "Ajuste Fair (NQ)", "Señal Táctica StatArb"],
        aligns="lrrrlrrrl",
        title="MATRIZ DE COINTEGRACION DE ENGLE-GRANGER Y DIVERGENCIAS ESTADISTICAS (STATARB)"
    )
    for p in pairs:
        coint_str = "COINTEGRADO" if p["cointegrated"] else ("ESTACIONARIO DEB." if p["adf_stat"] < -2.4 else "DERIVA ACTIVA")
        t.add_row([
            p["label"],
            fmt_num(p["beta"], 3),
            f"{p['r2']*100:5.1f}%",
            fmt_num(p["adf_stat"], 2, sign=True),
            coint_str,
            f"{p['half_life_bars']:.1f} barras",
            f"{p['z_now']:+.2f} SD",
            f"{p['target_rev_pts']:+.1f} pts",
            p["signal"],
        ])
    print("\n" + t.render())

    # Historial reciente del spread NQ vs ES en 5m (marco de disparo)
    t5 = Table(
        ["Hora NY (5m)", "Futuro NQ", "Futuro ES", "Z-Score NQ/ES (5m)", "Desajuste (Pts NQ)", "Acción Relativa en 5m"],
        aligns="lrrrrl",
        title="RADAR DE DISPARO STATARB EN 5 MINUTOS (DIVERGENCIA NQ=F vs ES=F)"
    )
    idx5 = p_nq_es_5["index"]
    z5 = p_nq_es_5["z_series"]
    sp5 = p_nq_es_5["spread_pts_series"]
    nq5 = cl_globex_5.loc[idx5, "NQ"].to_numpy()
    es5 = cl_globex_5.loc[idx5, "ES"].to_numpy()
    for i in range(max(len(idx5) - 10, 0), len(idx5)):
        zv = float(z5[i]) if np.isfinite(z5[i]) else 0.0
        dv = float(sp5[i]) if np.isfinite(sp5[i]) else 0.0
        act = ">>> VENDER NQ (Sobreextendido vs ES)" if zv >= 2.0 else (
              ">>> COMPRAR NQ (Rezagado vs ES)" if zv <= -2.0 else "Dentro de banda StatArb (±2 SD)")
        t5.add_row([
            idx5[i].strftime("%a %H:%M"),
            fmt_num(nq5[i], 2),
            fmt_num(es5[i], 2),
            f"{zv:+.2f} SD",
            f"{dv:+.1f} pts",
            act,
        ])
    print("\n" + t5.render() + "\n")

    # Gráfico institucional
    import matplotlib.pyplot as plt
    n_plot = 120
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 6.4), sharex=False)

    z15_tail = p_nq_es_15["z_series"][-n_plot:]
    z_smh_tail = p_nq_smh_15["z_series"][-min(n_plot, len(p_nq_smh_15["z_series"])):]
    ax1.plot(np.arange(len(z15_tail)), z15_tail, color=THEME["blue"], lw=2.0, label="Z-Score Spread NQ vs ES (15m)")
    ax1.plot(np.arange(len(z_smh_tail)), z_smh_tail, color=THEME["amber"], lw=1.8, label="Z-Score Spread NQ vs SMH (15m)")
    ax1.axhline(2.0, color=THEME["red"], ls="--", lw=1.3, label="Umbral Arbitraje ±2.0 SD")
    ax1.axhline(-2.0, color=THEME["green"], ls="--", lw=1.3)
    ax1.axhline(0.0, color=THEME["muted"], lw=0.8)
    ax1.set_title("1. Arbitraje Estadístico Macro (15m) | Z-Score Cointegrado NQ/ES y NQ/SMH")
    ax1.set_ylabel("Z-Score (SD)")
    ax1.legend(loc="upper left")

    z5_tail = z5[-n_plot:]
    ax2.plot(np.arange(len(z5_tail)), z5_tail, color=THEME["green"], lw=1.8, label="Z-Score Spread NQ vs ES (5m Disparo)")
    ax2.fill_between(np.arange(len(z5_tail)), -2.0, 2.0, color=THEME["indigo"], alpha=0.18, label="Zona Neutral (±2 SD)")
    ax2.axhline(2.0, color=THEME["red"], ls="--", lw=1.3)
    ax2.axhline(-2.0, color=THEME["green"], ls="--", lw=1.3)
    ax2.axhline(0.0, color=THEME["muted"], lw=0.8)
    ax2.set_title("2. Gatillo Intradía de 5 Minutos | Spread Cointegrado NQ=F vs ES=F")
    ax2.set_ylabel("Z-Score (5m)")
    ax2.set_xlabel("Barras Recientes")
    ax2.legend(loc="upper left")
    finalize(fig, "stat_arb_cointegracion_nq", show=show_plot)

    return {
        "nq_es_15m": p_nq_es_15,
        "nq_es_5m": p_nq_es_5,
        "nq_smh_15m": p_nq_smh_15,
        "nq_qqq_15m": p_nq_qqq_15,
    }


if __name__ == "__main__":
    ejecutar_stat_arb_cointegracion()
