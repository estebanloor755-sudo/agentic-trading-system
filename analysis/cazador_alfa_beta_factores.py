# %% [CAZADOR DE ANOMALIAS Y FACTORES: ALPHA, BETA, GAMMA, AR/ARMA, HURST & LO-MACKINLAY | NQ]
"""
Cazador Institucional de Factores y Anomalías para el E-mini Nasdaq (NQ=F):
  1. Descomposición rodante e intradía de Alpha (α anualizado/sesión), Beta (β)
     y Gamma de convexidad cuadrática (γ de Treynor-Mazuy: r_NQ = α + β r_F + γ r_F^2)
     frente a los tractores del Nasdaq:
       - `ES=F` (S&P 500 E-mini)
       - `SPY`  (ETF S&P 500 RTH)
       - `QQQ`  (Invesco Nasdaq-100 ETF)
       - `SMH`  (VanEck Semiconductor ETF - tractor líder de tecnología)
       - `^VXN` / `^VIX` (Índices de volatilidad implícita)
  2. Combinación de Autorregresión AR(p) / ARMA(1,1), Exponente de Hurst (H) y
     Ratio de Varianza de Lo-MacKinlay en 15m (Macro) y 5m (Ejecución) para
     dictaminar el régimen operativo:
       - Reversión a la Media (H < 0.48)
       - Momentum Persistente (H > 0.52)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import THEME
from core.mathx import nelder_mead, ols, rolling_ols_beta, rolling_zscore
from models.desbalance_estadistico import calcular_hurst, dictaminar_regimen_hurst, lo_mackinlay_vr


def fit_arma11(r: np.ndarray) -> dict:
    """
    Estima ARMA(1,1): r_t = mu + phi * r_{t-1} + theta * e_{t-1} + e_t
    por Mínimos Cuadrados Condicionales (CLS) + AR(p) por OLS.
    """
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 40:
        return {"mu": 0.0, "phi": 0.0, "theta": 0.0, "ar1": 0.0, "ar2": 0.0, "forecast_next": 0.0}
    mu0 = float(r.mean())
    y = r - mu0

    # AR(2) rápido por OLS
    ar_ols = ols(y[2:], np.column_stack([y[1:-1], y[:-2]]), add_const=False)
    ar1, ar2 = float(ar_ols["coef"][0]), float(ar_ols["coef"][1])

    def sse_arma(params):
        phi, theta = float(params[0]), float(params[1])
        if abs(phi) >= 0.96 or abs(theta) >= 0.96:
            return 1e12
        e_prev = 0.0
        s = 0.0
        for t in range(1, len(y)):
            e_t = y[t] - phi * y[t - 1] - theta * e_prev
            s += e_t * e_t
            e_prev = e_t
        return s

    best_x, _, _ = nelder_mead(sse_arma, [np.clip(ar1, -0.5, 0.5), 0.0], step=0.15, max_iter=350)
    phi, theta = float(np.clip(best_x[0], -0.92, 0.92)), float(np.clip(best_x[1], -0.92, 0.92))
    e_prev = 0.0
    for t in range(1, len(y)):
        e_prev = y[t] - phi * y[t - 1] - theta * e_prev
    fc_next = mu0 + phi * y[-1] + theta * e_prev
    return {"mu": mu0, "phi": phi, "theta": theta, "ar1": ar1, "ar2": ar2, "forecast_next": float(fc_next)}


def analizar_tractor(r_nq: np.ndarray, r_fac: np.ndarray, window: int = 32) -> dict:
    """
    Calcula Alpha (α), Beta (β), Gamma cuadrática (γ), R², correlación y Z-Score
    del residuo idioincrático de NQ frente a un tractor.
    """
    mask = np.isfinite(r_nq) & np.isfinite(r_fac)
    y = r_nq[mask]
    x = r_fac[mask]
    if len(y) < max(window, 25):
        return {
            "alpha_bps": 0.0, "beta": 1.0, "beta_roll": 1.0, "gamma": 0.0,
            "r2": 0.0, "corr": 0.0, "resid_z": 0.0, "signal": "Datos insuficientes",
        }
    # Regresión lineal y cuadrática (Treynor-Mazuy: captura convexidad / Gamma de factor)
    reg_lin = ols(y, x, add_const=True)
    reg_quad = ols(y, np.column_stack([x, x * x]), add_const=True)

    alpha_bar_pct = float(reg_lin["coef"][0])
    beta_full = float(reg_lin["coef"][1])
    gamma_quad = float(reg_quad["coef"][2])
    r2 = float(reg_lin["r2"])
    corr = float(np.corrcoef(y, x)[0, 1]) if np.std(x) > 0 and np.std(y) > 0 else 0.0

    b_roll, a_roll = rolling_ols_beta(y, x, window=min(window, len(y) // 2))
    beta_now = float(b_roll[-1]) if np.isfinite(b_roll[-1]) else beta_full
    alpha_now_bps = (float(a_roll[-1]) if np.isfinite(a_roll[-1]) else alpha_bar_pct) * 100.0

    # Spread acumulado de exceso de retorno (Alpha acumulado) y Z-Score rodante
    cum_excess = np.cumsum(y - beta_full * x)
    z_arr = rolling_zscore(cum_excess, window=min(window, len(y) // 2))
    resid_z = float(z_arr[-1]) if np.isfinite(z_arr[-1]) else 0.0

    if resid_z <= -1.8:
        sig = "NQ Rezagado vs Tractor (Z<-1.8) -> Oportunidad LONG Catch-Up"
    elif resid_z >= 1.8:
        sig = "NQ Sobreextendido vs Tractor (Z>+1.8) -> Riesgo Compresión"
    elif alpha_now_bps > 0.35:
        sig = "Liderazgo Alcista de NQ (Alpha+)"
    elif alpha_now_bps < -0.35:
        sig = "Debilidad Relativa de NQ (Alpha-)"
    else:
        sig = "Alineado en Equilibrio con Tractor"

    return {
        "alpha_bps": alpha_now_bps,
        "beta": beta_full,
        "beta_roll": beta_now,
        "gamma": gamma_quad,
        "r2": r2,
        "corr": corr,
        "resid_z": resid_z,
        "signal": sig,
        "b_series": b_roll,
        "z_series": z_arr,
    }


def ejecutar_cazador_factores(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    df_nq15 = feed.bars("NQ", "15m")
    df_nq5 = feed.bars("NQ", "5m")
    spot_nq = float(df_nq15["Close"].iloc[-1])

    # Series cruzadas en 15m (RTH para ETFs/índices, Globex completo para ES)
    closes_globex = feed.closes(["NQ", "ES"], interval="15m", rth_only=False)
    closes_rth = feed.closes(["NQ", "SPY", "QQQ", "SMH"], interval="15m", rth_only=True)
    closes_daily = feed.closes(["NQ", "VXN", "VIX"], interval="1d", rth_only=False)

    ret_globex = np.log(closes_globex / closes_globex.shift(1)).dropna() * 100.0
    ret_rth = np.log(closes_rth / closes_rth.shift(1)).dropna() * 100.0
    ret_daily = np.log(closes_daily / closes_daily.shift(1)).dropna() * 100.0

    tractors = {
        "ES=F (S&P 500 Futuro)": analizar_tractor(ret_globex["NQ"].to_numpy(), ret_globex["ES"].to_numpy(), window=32),
        "QQQ (Nasdaq-100 ETF)": analizar_tractor(ret_rth["NQ"].to_numpy(), ret_rth["QQQ"].to_numpy(), window=26),
        "SPY (S&P 500 ETF)": analizar_tractor(ret_rth["NQ"].to_numpy(), ret_rth["SPY"].to_numpy(), window=26),
        "SMH (Semiconductores)": analizar_tractor(ret_rth["NQ"].to_numpy(), ret_rth["SMH"].to_numpy(), window=26),
        "^VXN (Volatilidad NDX)": analizar_tractor(ret_daily["NQ"].to_numpy(), ret_daily["VXN"].to_numpy(), window=15),
        "^VIX (Volatilidad S&P)": analizar_tractor(ret_daily["NQ"].to_numpy(), ret_daily["VIX"].to_numpy(), window=15),
    }

    # Autorregresión + Hurst + Lo-MacKinlay en 15m y 5m
    r15 = np.diff(np.log(df_nq15["Close"].to_numpy())) * 100.0
    r5 = np.diff(np.log(df_nq5["Close"].to_numpy())) * 100.0
    arma15 = fit_arma11(r15[-600:])
    arma5 = fit_arma11(r5[-800:])
    h15 = calcular_hurst(df_nq15["Close"].to_numpy()[-500:])
    h5 = calcular_hurst(df_nq5["Close"].to_numpy()[-600:])
    vr15 = lo_mackinlay_vr(df_nq15["Close"].to_numpy()[-500:], q=4)
    vr5 = lo_mackinlay_vr(df_nq5["Close"].to_numpy()[-600:], q=6)

    reg15_str = dictaminar_regimen_hurst(h15, vr15)
    reg5_str = dictaminar_regimen_hurst(h5, vr5)

    print("\n" + banner(
        f"CAZADOR DE ANOMALIAS Y FACTORES: ALPHA, BETA, GAMMA, ARMA & HURST | NQ: {spot_nq:,.2f}",
        "Descomposición frente a Tractores (ES, SPY, QQQ, SMH, VXN, VIX) + Dictamen de Memoria Intradía"
    ))
    print(kv_block([
        ("ARMA(1,1) Macro 15m", f"φ(AR1)={arma15['phi']:+.3f} | θ(MA1)={arma15['theta']:+.3f} | E[r_t+1]={arma15['forecast_next']*100:+.2f} bps"),
        ("ARMA(1,1) Micro 5m", f"φ(AR1)={arma5['phi']:+.3f} | θ(MA1)={arma5['theta']:+.3f} | E[r_t+1]={arma5['forecast_next']*100:+.2f} bps"),
        ("Dictamen Régimen 15m", f"Hurst H={h15:.3f} | Lo-MacKinlay VR(4)={vr15['vr']:.3f} (z*={vr15['z_robust']:+.2f}) -> {reg15_str}"),
        ("Dictamen Régimen 5m", f"Hurst H={h5:.3f} | Lo-MacKinlay VR(6)={vr5['vr']:.3f} (z*={vr5['z_robust']:+.2f}) -> {reg5_str}"),
    ]))

    t = Table(
        ["Tractor de Mercado", "Alpha Rodante (bps)", "Beta Estructural", "Beta Rodante", "Gamma (Convexidad)", "Corr (ρ)", "R²", "Z-Score Residual", "Lectura / Anomalía Institucional"],
        aligns="lrrrrrrrl",
        title="MATRIZ MULTI-FACTOR DEL E-MINI NASDAQ: ALPHA (α), BETA (β), GAMMA (γ) Y DIVERGENCIA Z-SCORE"
    )
    for name, info in tractors.items():
        t.add_row([
            name,
            f"{info['alpha_bps']:+.2f} bps",
            fmt_num(info["beta"], 3, sign=True),
            fmt_num(info["beta_roll"], 3, sign=True),
            fmt_num(info["gamma"], 3, sign=True),
            fmt_num(info["corr"], 3, sign=True),
            f"{info['r2']*100:5.1f}%",
            f"{info['resid_z']:+.2f} SD",
            info["signal"],
        ])
    print("\n" + t.render() + "\n")

    # Gráfico institucional: Beta rodante y Z-Score residual vs ES y SMH
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 6.4), sharex=False)

    es_b = tractors["ES=F (S&P 500 Futuro)"]["b_series"][-120:]
    smh_b = tractors["SMH (Semiconductores)"]["b_series"][-120:]
    ax1.plot(np.arange(len(es_b)), es_b, color=THEME["blue"], lw=2.0, label="Beta Rodante NQ vs ES=F")
    ax1.plot(np.arange(len(smh_b)), smh_b, color=THEME["amber"], lw=2.0, label="Beta Rodante NQ vs SMH (Semis)")
    ax1.axhline(1.0, color=THEME["muted"], ls="--", lw=1.0)
    ax1.set_title("1. Sensibilidad Beta (β) Rodante Intradía del Nasdaq frente a ES=F y Semiconductores (SMH)")
    ax1.set_ylabel("Beta (β)")
    ax1.legend(loc="upper left")

    es_z = tractors["ES=F (S&P 500 Futuro)"]["z_series"][-120:]
    smh_z = tractors["SMH (Semiconductores)"]["z_series"][-120:]
    ax2.plot(np.arange(len(es_z)), es_z, color=THEME["green"], lw=1.9, label="Z-Score Alpha Residual NQ vs ES")
    ax2.plot(np.arange(len(smh_z)), smh_z, color=THEME["pink"], lw=1.8, label="Z-Score Alpha Residual NQ vs SMH")
    ax2.axhline(2.0, color=THEME["red"], ls="--", lw=1.2, label="Banda Arbitraje ±2 SD")
    ax2.axhline(-2.0, color=THEME["green"], ls="--", lw=1.2)
    ax2.axhline(0.0, color=THEME["muted"], lw=0.8)
    ax2.set_title("2. Cazador de Divergencias de Factor (Z-Score Idiosincrático de NQ)")
    ax2.set_ylabel("Z-Score (SD)")
    ax2.set_xlabel("Barras Recientes de 15 Minutos")
    ax2.legend(loc="upper left")
    finalize(fig, "cazador_alfa_beta_factores_nq", show=show_plot)

    return {
        "spot": spot_nq,
        "tractors": tractors,
        "arma15": arma15,
        "arma5": arma5,
        "hurst_15m": h15,
        "hurst_5m": h5,
        "vr_15m": vr15,
        "vr_5m": vr5,
        "regime_15m": reg15_str,
        "regime_5m": reg5_str,
    }


if __name__ == "__main__":
    ejecutar_cazador_factores()
