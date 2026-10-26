# %% [YIELD ANOMALY & CARRY / BASIS TRADE TRACKER | NQ=F vs ^NDX & ^IRX/^TNX]
"""
Rastreador Institucional de Anomalías de Rendimiento (Yield Anomalies), Fair Value
Spread, Tasa Repo Implícita y Arbitraje de Índices entre el Futuro E-mini Nasdaq
(`NQ=F`) y el Índice Spot (`^NDX`).

Ecuación Exacta de Cost-of-Carry Institucional:
    F_theo(t) = S_NDX(t) * exp((r - q) * T)
    Base Teórica (Fair Value Spread) = F_theo(t) - S_NDX(t)
    Base Real de Mercado             = F_NQ(t) - S_NDX(t)
    Anomalía / Mispricing (Pts Netos)= F_NQ(t) - F_theo(t)
    Tasa Repo Implícita              = (1 / T) * ln(F_NQ / S_NDX) + q

Banda Teórica Justa (No-Arbitrage Band):
    F_theo_Spread(t) ± k_arb * sigma_basis(t)   (con umbral institucional k_arb = 1.80 SD)
    Cuando la Base Real se sale de esta banda teórica justa, se activa una alerta
    visual (Rojo / Magenta) indicando una inyección de liquidez institucional anómala
    o disparo de programas algorítmicos Cash-and-Carry / Reverse Cash-and-Carry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MNQ, MODEL, NQ, THEME
from core.mathx import rolling_zscore
from core import sessions


def calcular_serie_anomalias_rendimiento_nq(feed=None, z_threshold: float = 1.80) -> dict:
    """
    Calcula en el backend la serie temporal completa y sin recortes de:
      - Futuro `NQ=F`, Spot `^NDX` y `Fair Value Teórico` ajustado por `r` (^IRX/SOFR) y `q` (Dividend Yield).
      - `Base de Mercado (NQ - NDX)` vs `Base Teórica Justa (F_theo - NDX)`.
      - `Banda Teórica Justa Superior e Inferior` (`Fair Value ± 1.80 σ_rolling` y `± 2.50 σ_rolling`).
      - `Anomalía Neta en Puntos (Mispricing = F_NQ - F_theo)` y en `bps`.
      - `Tasa Repo Implícita (%)`, `Carry Spread (bps)` y `Spread Curva 10Y-3M (^TNX - ^IRX)`.
      - Máscara booleana exacta `is_anomaly` para resaltar en color de alerta (rojo/magenta)
        todos los instantes en que el spread rompe su banda teórica justa.
    """
    from Data.data_feed_nq import DataFeedNQ

    feed = feed or DataFeedNQ()
    closes = feed.closes(["NQ", "NDX"], interval="15m", rth_only=True)
    if len(closes) < 25:
        closes = feed.closes(["NQ", "NDX"], interval="1d", rth_only=False)

    r_rf, r_src = feed.risk_free_rate()
    try:
        tnx_df = feed.bars("TNX", "1d", 30)
        tnx_yield = float(tnx_df["Close"].iloc[-1]) / 100.0
    except Exception:
        tnx_yield = 0.041

    q_div = MODEL.ndx_div_yield
    contract_code, expiry_date = sessions.nq_front_contract(closes.index[-1])

    exp_ts = pd.Timestamp(expiry_date).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
    T_arr = np.maximum((exp_ts - closes.index).total_seconds().to_numpy() / (365.0 * 86400.0), 1.0 / 365.0)
    dte_now = float(T_arr[-1] * 365.0)

    f_nq = closes["NQ"].to_numpy(dtype=float)
    s_ndx = closes["NDX"].to_numpy(dtype=float)

    # Cost-of-Carry Crudo T-Bill (^IRX) conservado 100% en memoria del backend
    f_theo_tbill = s_ndx * np.exp((r_rf - q_div) * T_arr)
    basis_theo_tbill = f_theo_tbill - s_ndx
    mispricing_tbill_pts = f_nq - f_theo_tbill

    # Tasa Repo Implícita instantánea y Costo de Acarreo Institucional SOFR + Equity Financing
    implied_repo = np.log(f_nq / s_ndx) / T_arr + q_div
    win = min(36, max(len(f_nq) // 3, 12))
    sofr_carry_series = (
        pd.Series(implied_repo)
        .rolling(win, min_periods=6)
        .median()
        .bfill()
        .ffill()
        .to_numpy(dtype=float)
    )

    # Fair Value Teórico Ajustado por Costo de Acarreo Institucional (SOFR / Bonos / Dividend Yield q)
    f_theo = s_ndx * np.exp((sofr_carry_series - q_div) * T_arr)
    basis_mkt = f_nq - s_ndx
    basis_theo = f_theo - s_ndx
    mispricing_pts = f_nq - f_theo
    mispricing_bps = (mispricing_pts / s_ndx) * 10_000.0
    carry_spread_bps = (implied_repo - r_rf) * 10_000.0
    repo_anomaly_bps = (implied_repo - sofr_carry_series) * 10_000.0

    z_rolling_series = np.nan_to_num(rolling_zscore(mispricing_pts, window=win), nan=0.0)

    # Desviación estándar móvil del spread frente al Fair Value para la Banda Teórica Justa (±1.8σ)
    s_series = pd.Series(mispricing_pts)
    roll_sd = s_series.rolling(win, min_periods=6).std(ddof=1).bfill().ffill().to_numpy(dtype=float)
    roll_sd = np.maximum(roll_sd, 2.5)

    # Z-Score exacto frente al Fair Value Teórico (Mispricing / sigma_basis)
    z_mis = mispricing_pts / roll_sd

    fair_band_upper_18 = basis_theo + z_threshold * roll_sd
    fair_band_lower_18 = basis_theo - z_threshold * roll_sd
    fair_band_upper_25 = basis_theo + 2.50 * roll_sd
    fair_band_lower_25 = basis_theo - 2.50 * roll_sd

    # Detección exacta de los momentos en que el spread rompe su Banda Teórica Justa (±1.8σ)
    is_upper_anomaly = (basis_mkt > fair_band_upper_18) | (z_mis >= z_threshold)
    is_lower_anomaly = (basis_mkt < fair_band_lower_18) | (z_mis <= -z_threshold)
    is_anomaly = is_upper_anomaly | is_lower_anomaly

    # Percentiles completos de la distribución histórica de la anomalía (100% intactos en memoria)
    p_levels = [1, 5, 10, 16, 25, 50, 75, 84, 90, 95, 99]
    p_vals = np.percentile(mispricing_pts, p_levels)
    anomaly_percentiles = {f"P{p:02d}": float(v) for p, v in zip(p_levels, p_vals)}

    z_now = float(z_mis[-1])
    f_now = float(f_nq[-1])
    s_now = float(s_ndx[-1])
    ft_now = float(f_theo[-1])
    bm_now = float(basis_mkt[-1])
    bt_now = float(basis_theo[-1])
    mp_pts_now = float(mispricing_pts[-1])
    mp_bps_now = float(mispricing_bps[-1])
    irepo_now = float(implied_repo[-1])
    sofr_now = float(sofr_carry_series[-1])
    carry_bps_now = float(carry_spread_bps[-1])
    band_width_now = float(z_threshold * roll_sd[-1])
    upper_band_now = float(fair_band_upper_18[-1])
    lower_band_now = float(fair_band_lower_18[-1])

    # Magnitud de exceso fuera de la banda teórica justa (0 si está dentro de la banda)
    if bm_now > upper_band_now:
        excess_outside_band_pts = bm_now - upper_band_now
    elif bm_now < lower_band_now:
        excess_outside_band_pts = bm_now - lower_band_now
    else:
        excess_outside_band_pts = 0.0

    if z_now >= z_threshold:
        arb_signal = "ALERTA PRIMA ANÓMALA (FUERA DE BANDA > +1.8σ) -> SHORT NQ / BUY NDX (Cash-and-Carry)"
        action_short = "SHORT / VENTA"
    elif z_now <= -z_threshold:
        arb_signal = "ALERTA DESCUENTO ANÓMALO (FUERA DE BANDA < -1.8σ) -> LONG NQ / SELL NDX (Reverse Carry)"
        action_short = "LONG / COMPRA"
    elif mp_pts_now >= roll_sd[-1]:
        arb_signal = "Prima Institucional Moderada sobre Fair Value -> Presión Compradora de Acarreo"
        action_short = "SHORT / VENTA" if z_now > 1.2 else "NEUTRAL / RANGO"
    elif mp_pts_now <= -roll_sd[-1]:
        arb_signal = "Descuento Institucional Moderado bajo Fair Value -> Cobertura / Presión Vendedora"
        action_short = "LONG / COMPRA" if z_now < -1.2 else "NEUTRAL / RANGO"
    else:
        arb_signal = "DENTRO DE BANDA TEÓRICA JUSTA (FAIR VALUE) -> Sin anomalía de arbitraje activa"
        action_short = "NEUTRAL / RANGO"

    conf_anom = float(np.clip(72.0 + abs(z_now) * 12.5, 68.0, 99.2))

    return {
        "index": closes.index,
        "contract": contract_code,
        "expiry": str(expiry_date),
        "dte": dte_now,
        "r_rf": r_rf,
        "r_src": r_src,
        "q_div": q_div,
        "tnx_yield": tnx_yield,
        "yield_curve_10y_3m_bps": (tnx_yield - r_rf) * 10_000.0,
        # Series completas en memoria (Backend 100% intacto)
        "f_nq_series": f_nq,
        "s_ndx_series": s_ndx,
        "f_theo_series": f_theo,
        "f_theo_tbill_series": f_theo_tbill,
        "basis_mkt_series": basis_mkt,
        "basis_theo_series": basis_theo,
        "basis_theo_tbill_series": basis_theo_tbill,
        "mispricing_pts_series": mispricing_pts,
        "mispricing_tbill_pts_series": mispricing_tbill_pts,
        "mispricing_bps_series": mispricing_bps,
        "implied_repo_series": implied_repo,
        "sofr_carry_series": sofr_carry_series,
        "repo_anomaly_bps_series": repo_anomaly_bps,
        "carry_spread_bps_series": carry_spread_bps,
        "z_series": z_mis,
        "z_rolling_series": z_rolling_series,
        "roll_sd_series": roll_sd,
        "fair_band_upper_18": fair_band_upper_18,
        "fair_band_lower_18": fair_band_lower_18,
        "fair_band_upper_25": fair_band_upper_25,
        "fair_band_lower_25": fair_band_lower_25,
        "is_upper_anomaly": is_upper_anomaly,
        "is_lower_anomaly": is_lower_anomaly,
        "is_anomaly": is_anomaly,
        "anomaly_count": int(np.sum(is_anomaly)),
        "anomaly_percentiles": anomaly_percentiles,
        "sofr_carry_pct": sofr_now * 100.0,
        # Valores actuales puntuales
        "fut_nq": f_now,
        "spot_ndx": s_now,
        "fair_value_nq": ft_now,
        "basis_mkt_pts": bm_now,
        "basis_theo_pts": bt_now,
        "mispricing_pts": mp_pts_now,
        "mispricing_bps": mp_bps_now,
        "band_width_pts": band_width_now,
        "upper_band_pts": upper_band_now,
        "lower_band_pts": lower_band_now,
        "excess_outside_band_pts": excess_outside_band_pts,
        "implied_repo_pct": irepo_now * 100.0,
        "risk_free_pct": r_rf * 100.0,
        "tnx_pct": tnx_yield * 100.0,
        "carry_spread_bps": carry_bps_now,
        "z_score": z_now,
        "confluence_pct": conf_anom,
        "signal": arb_signal,
        "action": action_short,
    }


def ejecutar_basis_carry_tracker(feed=None, show_plot: bool = True) -> dict:
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    res = calcular_serie_anomalias_rendimiento_nq(feed=feed, z_threshold=1.80)
    idx = res["index"]
    f_nq = res["f_nq_series"]
    s_ndx = res["s_ndx_series"]
    basis_mkt = res["basis_mkt_series"]
    basis_theo = res["basis_theo_series"]
    mispricing_pts = res["mispricing_pts_series"]
    implied_repo = res["implied_repo_series"]
    z_mis = res["z_series"]
    fair_u18 = res["fair_band_upper_18"]
    fair_l18 = res["fair_band_lower_18"]
    is_anom = res["is_anomaly"]

    print("\n" + banner(
        f"YIELD ANOMALY & CARRY / BASIS TRADE TRACKER | CONTRATO: {res['contract']} (Vence: {res['expiry']}, DTE: {res['dte']:.1f}d)",
        f"Futuro NQ: {res['fut_nq']:,.2f} | Spot ^NDX: {res['spot_ndx']:,.2f} | Tasa Corta (^IRX/SOFR): {res['risk_free_pct']:.2f}% | Bono 10Y (^TNX): {res['tnx_pct']:.2f}%"
    ))
    print(kv_block([
        ("Fair Value Teórico", f"F_theo = {res['fair_value_nq']:,.2f} pts  |  Spread Fair Value (F_theo - NDX) = {res['basis_theo_pts']:+.2f} pts"),
        ("Banda Teórica Justa", f"[{res['lower_band_pts']:+.2f} pts  a  {res['upper_band_pts']:+.2f} pts] (Ancho No-Arbitraje ±1.8σ: ±{res['band_width_pts']:.2f} pts)"),
        ("Anomalía Actual Neta", f"Base Mkt = {res['basis_mkt_pts']:+.2f} pts  |  Mispricing (F_NQ - F_theo) = {res['mispricing_pts']:+.2f} pts ({res['mispricing_bps']:+.1f} bps)"),
        ("Tasa Repo Implícita", f"r_imp = {res['implied_repo_pct']:.2f}% vs Tasa Libre de Riesgo r = {res['risk_free_pct']:.2f}% (Carry Spread: {res['carry_spread_bps']:+.1f} bps)"),
        ("Z-Score Arbitraje", f"Z = {res['z_score']:+.2f} SD | Anomalías Detectadas en Ventana: {res['anomaly_count']} -> {res['signal']}"),
    ]))

    t = Table(
        ["Hora NY (RTH)", "Futuro NQ=F", "Spot ^NDX", "Base Mkt (Pts)", "Fair Value (Pts)", "Anomalía Neta (Pts)", "Repo Implícita", "Z-Score", "Estado Banda Fair Value"],
        aligns="lrrrrrrrl",
        title="MAGNITUD DE LA ANOMALIA DE RENDIMIENTO (NQ=F vs ^NDX) EN PUNTOS NETOS"
    )
    tail_n = min(12, len(idx))
    for i in range(len(idx) - tail_n, len(idx)):
        ts = idx[i]
        zv = float(z_mis[i])
        mp = float(mispricing_pts[i])
        if zv >= 1.8:
            act = "ALERTA ROJA/MAGENTA: PRIMA FUERA DE BANDA (SELL NQ)"
        elif zv <= -1.8:
            act = "ALERTA ROJA/MAGENTA: DESCUENTO FUERA DE BANDA (BUY NQ)"
        else:
            act = "DENTRO DE BANDA TEÓRICA JUSTA (FAIR VALUE)"
        t.add_row([
            ts.strftime("%a %H:%M"),
            fmt_num(f_nq[i], 2),
            fmt_num(s_ndx[i], 2),
            fmt_num(basis_mkt[i], 2, sign=True),
            fmt_num(basis_theo[i], 2, sign=True),
            f"{mp:+.2f} pts",
            f"{implied_repo[i]*100:5.2f}%",
            f"{zv:+.2f} SD",
            act,
        ])
    print("\n" + t.render() + "\n")

    import matplotlib.pyplot as plt
    n_plot = min(120, len(idx))
    x = np.arange(n_plot)
    bm_sub = basis_mkt[-n_plot:]
    bt_sub = basis_theo[-n_plot:]
    u18_sub = fair_u18[-n_plot:]
    l18_sub = fair_l18[-n_plot:]
    mp_sub = mispricing_pts[-n_plot:]
    z_sub = z_mis[-n_plot:]
    anom_sub = is_anom[-n_plot:]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.5, 6.6), sharex=True)

    ax1.fill_between(x, l18_sub, u18_sub, color=THEME["blue"], alpha=0.16, label="Banda Teórica Justa Fair Value (±1.8σ No-Arbitraje)")
    ax1.plot(x, bt_sub, color=THEME["yellow"], lw=1.9, ls="--", label="Fair Value Teórico Cost-of-Carry")
    ax1.plot(x, bm_sub, color=THEME["blue"], lw=1.9, label="Spread Real de Mercado (NQ=F - ^NDX)")
    # Resaltar en Magenta/Rojo de alerta las excursiones fuera de la banda justa
    ax1.fill_between(x, u18_sub, bm_sub, where=(bm_sub > u18_sub), color="#ff007f", alpha=0.55, interpolate=True, label="Alerta Prima Anómala (> Banda Fair Value)")
    ax1.fill_between(x, l18_sub, bm_sub, where=(bm_sub < l18_sub), color="#ef4444", alpha=0.55, interpolate=True, label="Alerta Descuento Anómalo (< Banda Fair Value)")
    if np.any(anom_sub):
        ax1.scatter(x[anom_sub], bm_sub[anom_sub], color="#ff007f", edgecolor="#ffffff", s=36, zorder=6, label="Disparo Institucional de Arbitraje")
    ax1.set_title(f"1. Anomalías de Rendimiento (Yield Anomalies): Spread NQ=F vs ^NDX & Banda Fair Value ({res['contract']})")
    ax1.set_ylabel("Spread en Puntos NQ")
    ax1.legend(loc="upper left", ncol=2)

    bar_cols = ["#ff007f" if abs(zv) >= 1.8 else (THEME["green"] if mp >= 0 else THEME["blue"]) for mp, zv in zip(mp_sub, z_sub)]
    ax2.bar(x, mp_sub, color=bar_cols, alpha=0.82, width=0.72, label="Magnitud de la Anomalía en Puntos Netos (F_NQ - F_theo)")
    ax2.plot(x, (u18_sub - bt_sub), color="#ff007f", ls="--", lw=1.3, label="Límite Banda Teórica Justa (+1.8σ)")
    ax2.plot(x, (l18_sub - bt_sub), color="#ef4444", ls="--", lw=1.3, label="Límite Banda Teórica Justa (-1.8σ)")
    ax2.axhline(0.0, color=THEME["yellow"], lw=1.0)
    ax2.set_xticks(x[::max(n_plot // 10, 1)])
    ax2.set_xticklabels([ts.strftime("%d-%b %H:%M") for ts in idx[-n_plot:][::max(n_plot // 10, 1)]], rotation=35)
    ax2.set_ylabel("Anomalía Neta (Pts NQ)")
    ax2.set_xlabel("Barras Intradía (America/New_York)")
    ax2.legend(loc="upper left", ncol=3)
    finalize(fig, "basis_carry_tracker_nq", show=show_plot)

    return res


if __name__ == "__main__":
    ejecutar_basis_carry_tracker()
