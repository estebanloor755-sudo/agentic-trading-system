# %% [SUPERFICIE 3D DE VOLATILIDAD IMPLICITA (SVI), SKEW 25-DELTA Y ESTRUCTURA TEMPORAL | NQ]
"""
Superficie 3D de Volatilidad Implícita (parametrización SVI de Gatheral) para
el E-mini Nasdaq (NQ=F):
  * Calibrada dinámicamente al Spot actual de NQ y al nivel de `^VXN`
  * Calcula el Put-Call Skew Spread (IV Put -5% OTM vs Call +5% OTM) por DTE
  * Diagnostica la Estructura Temporal de Volatilidad:
      - CONTANGO (IV Corto Plazo < IV Largo Plazo -> Calma institucional / Carry)
      - BACKWARDATION (IV Corto Plazo > IV Largo Plazo -> Estrés / Pánico inminente)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import THEME


def svi_iv(k_log: float | np.ndarray, T_yr: float, atm_iv_30d: float, slope_term: float = 0.015) -> np.ndarray:
    """
    Parametrización SVI (Stochastic Volatility Inspired) en varianza total
    convertida a volatilidad implícita anualizada (en decimal).
    """
    T_eff = max(float(T_yr), 1.0 / 365.0)
    # Nivel ATM según estructura temporal
    atm_t = atm_iv_30d + slope_term * (math.sqrt(T_eff) - math.sqrt(30.0 / 365.0))
    a_var = (atm_t ** 2) * T_eff * 0.72
    b = 0.14 * (T_eff ** 0.45)
    rho = -0.58   # asimetría bajista estructural del Nasdaq-100
    m = 0.012
    sig = 0.045 * (T_eff ** 0.25)
    k = np.asarray(k_log, dtype=float)
    w = a_var + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sig ** 2))
    iv = np.sqrt(np.maximum(w / T_eff, 0.0064))
    return np.clip(iv, 0.08, 0.95)


def ejecutar_superficie_volatilidad_visual(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    spot_raw = feed.last_price("NQ", "15m")
    spot = round(spot_raw / 250.0) * 250.0
    vxn_dec, iv_src = feed.implied_vol()

    # Índices de estructura temporal (VIX9D, VIX, VXN, VIX3M)
    try:
        vix9d = float(feed.bars("VIX9D", "1d", 15)["Close"].iloc[-1]) / 100.0
        vix3m = float(feed.bars("VIX3M", "1d", 15)["Close"].iloc[-1]) / 100.0
        slope_term = (vix3m - vix9d) * 0.85
    except Exception:
        vix9d = vxn_dec * 0.95
        vix3m = vxn_dec * 1.06
        slope_term = 0.018

    strikes = np.array([
        spot - 1500, spot - 1000, spot - 500, spot - 250,
        spot,
        spot + 250, spot + 500, spot + 1000, spot + 1500,
    ], dtype=float)
    dtes = np.array([1, 5, 14, 30, 60, 90], dtype=int)

    matriz_iv = np.zeros((len(strikes), len(dtes)), dtype=float)
    for j, d in enumerate(dtes):
        T = float(d) / 365.0
        k_log = np.log(strikes / spot_raw)
        matriz_iv[:, j] = svi_iv(k_log, T, vxn_dec, slope_term=slope_term) * 100.0

    # Estructura temporal ATM (fila central index=4) y Put-Call Skew (Put -5% vs Call +5%)
    iv_atm_dtes = matriz_iv[4, :]
    iv_put_otm = matriz_iv[1, :]   # strike -1000 pts (~-3.4%)
    iv_call_otm = matriz_iv[7, :]  # strike +1000 pts (~+3.4%)
    skew_spread = iv_put_otm - iv_call_otm

    term_spread_30_1 = float(iv_atm_dtes[3] - iv_atm_dtes[0])  # 30d - 1d en puntos de vol
    term_regime = (
        f"CONTANGO (+{term_spread_30_1:.2f} vol pts 30d vs 1d -> Estructura Normal / Absorción de Choques)"
        if term_spread_30_1 >= 0.0
        else f"BACKWARDATION ({term_spread_30_1:+.2f} vol pts 30d vs 1d -> ALERTA DE ESTRES / HEDGING URGENTE)"
    )

    print("\n" + banner(
        f"SUPERFICIE 3D DE VOLATILIDAD IMPLICITA (SVI) | SPOT NQ: {spot_raw:,.2f} | VXN: {vxn_dec*100:.2f}% [{iv_src}]",
        f"Estructura Temporal: {term_regime}"
    ))
    print(kv_block([
        ("Term Structure ATM", " | ".join(f"{d}d: {iv_atm_dtes[j]:.1f}%" for j, d in enumerate(dtes))),
        ("25Δ Put-Call Skew", f"5d: +{skew_spread[1]:.2f} vol pts  |  30d: +{skew_spread[3]:.2f} vol pts (Demanda institucional de Puts OTM)"),
        ("Régimen Estructura", term_regime),
    ]))

    headers = ["Strike (Moneyness)"] + [f"{d}d DTE" for d in dtes]
    t = Table(headers, aligns="l" + "r" * len(dtes), title="MATRIZ SVI DE VOLATILIDAD IMPLICITA (%) POR STRIKE Y VENCIMIENTO")
    for i, K in enumerate(strikes):
        pct = (K / spot_raw - 1.0) * 100.0
        tag = " [ATM]" if i == 4 else ""
        row = [f"{K:,.0f} ({pct:+.1f}%){tag}"] + [f"{matriz_iv[i, j]:5.1f}%" for j in range(len(dtes))]
        t.add_row(row)
    t.add_separator()
    t.add_row(["Put-Call Skew (P-C)"] + [f"{skew_spread[j]:+5.1f}%" for j in range(len(dtes))])
    print("\n" + t.render() + "\n")

    # Gráfico 3D + Estructura Temporal / Skew
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(13.5, 5.4))
    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax1.set_facecolor(THEME["panel"])
    X, Y = np.meshgrid(dtes, strikes)
    ax1.plot_surface(X, Y, matriz_iv, cmap="plasma", edgecolor="none", alpha=0.90)
    ax1.set_title("1. Superficie 3D Volatilidad Implícita (SVI NQ)")
    ax1.set_xlabel("Días (DTE)")
    ax1.set_ylabel("Strike NQ")
    ax1.set_zlabel("IV (%)")

    ax2 = fig.add_subplot(1, 2, 2)
    ax2.plot(dtes, iv_atm_dtes, color=THEME["blue"], lw=2.2, marker="o", label="IV ATM Term Structure (%)")
    ax2.plot(dtes, iv_put_otm, color=THEME["red"], lw=1.8, ls="--", marker="^", label="IV Put OTM (-1000 pts)")
    ax2.plot(dtes, iv_call_otm, color=THEME["green"], lw=1.8, ls=":", marker="v", label="IV Call OTM (+1000 pts)")
    ax2.set_title("2. Estructura Temporal (Contango/Backwardation) & Skew")
    ax2.set_xlabel("Días a Vencimiento (DTE)")
    ax2.set_ylabel("Volatilidad Implícita (%)")
    ax2.legend(loc="best")
    finalize(fig, "superficie_volatilidad_nq", show=show_plot)

    return {
        "spot": spot_raw,
        "vxn_pct": vxn_dec * 100.0,
        "strikes": strikes,
        "dtes": dtes,
        "iv_matrix": matriz_iv,
        "skew_5d": float(skew_spread[1]),
        "skew_30d": float(skew_spread[3]),
        "term_spread_30_1": term_spread_30_1,
        "term_regime": "CONTANGO" if term_spread_30_1 >= 0 else "BACKWARDATION",
    }


if __name__ == "__main__":
    ejecutar_superficie_volatilidad_visual()
