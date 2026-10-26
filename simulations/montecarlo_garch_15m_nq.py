# %% [MOTOR FUSIONADO: GJR-GARCH(1,1)-t + AR(p) + MONTE CARLO (32 BLOQUES 15M = 8H NY)]
"""
Proyección Estocástica Macro de 32 bloques de 15 minutos (8 horas operativas en
horario America/New_York EST/EDT) para el E-mini Nasdaq (NQ=F / MNQ=F).

Mejoras institucionales respecto al script previo (movido de analysis/simulations/):
  * Calendario CME Globex real (`core.sessions.next_bars`): salta la pausa diaria
    17:00-18:00 ET y el cierre de fin de semana (viernes 17:00 -> domingo 18:00 ET).
  * Motor GJR-GARCH(1,1)-t + AR(p) con desestacionalización intradía y Filtered
    Historical Simulation (10,000+ trayectorias con propagación de varianza ruta a ruta).
  * Entrega niveles exactos de percentiles (`P05`, `P25`, `P50`, `P75`, `P95`) como
    bandas dinámicas de Stop Loss (SL) y Take Profit (TP1 / TP2) para NQ y MNQ.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MNQ, MODEL, NQ, THEME
from core import sessions
from models.Garch import fit_nq_garch, simulate_returns

N_PERIODS = MODEL.n_periods_15m
N_SIMULATIONS = MODEL.n_sims


def ejecutar_suite_ny(feed=None, n_periods: int = N_PERIODS, n_sims: int = N_SIMULATIONS,
                      show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    bars_15m = feed.bars("NQ", "15m")
    fit = fit_nq_garch(bars_15m, ar_max=2, deseason=True)
    reg = fit.vol_regime()

    last_price = float(bars_15m["Close"].iloc[-1])
    last_time = pd.Timestamp(bars_15m.index[-1])

    # 32 bloques futuros de 15m en horario real de Globex / Nueva York
    future_dates = sessions.next_bars(last_time, n=n_periods, freq="15min")
    forecast_vol = fit.forecast_sigma(future_dates)
    forecast_mean = fit.forecast_mean(n_periods, future_dates)

    # Simulación de 10,000+ trayectorias con propagación GJR-GARCH + FHS
    ret_sim = simulate_returns(fit, future_dates, n_sims=n_sims, seed=42, shocks="fhs")
    simulations = last_price * np.exp(np.cumsum(ret_sim, axis=0))

    # BACKEND INTACTO: Calculamos la matriz completa de 11 percentiles en memoria sin eliminar nada
    niveles_q = [0.01, 0.05, 0.10, 0.16, 0.25, 0.50, 0.75, 0.84, 0.90, 0.95, 0.99]
    matriz_q = np.quantile(simulations, niveles_q, axis=1)
    sim_summary = pd.DataFrame(matriz_q, index=niveles_q, columns=future_dates)

    p01 = sim_summary.loc[0.01].to_numpy()
    p05 = sim_summary.loc[0.05].to_numpy()
    p10 = sim_summary.loc[0.10].to_numpy()
    p16 = sim_summary.loc[0.16].to_numpy()
    p25 = sim_summary.loc[0.25].to_numpy()
    p50 = sim_summary.loc[0.50].to_numpy()
    p75 = sim_summary.loc[0.75].to_numpy()
    p84 = sim_summary.loc[0.84].to_numpy()
    p90 = sim_summary.loc[0.90].to_numpy()
    p95 = sim_summary.loc[0.95].to_numpy()
    p99 = sim_summary.loc[0.99].to_numpy()
    iqr_pts = p75 - p25
    sd1_band_pts = p84 - p16
    garch_projected_prices = last_price * np.exp(np.cumsum(forecast_mean))

    print("\n" + banner(
        f"MOTOR AR({fit.p}) + GJR-GARCH(1,1)-t + MONTE CARLO ({n_sims:,} RUTAS, 32 BLOQUES 15M = 8H NY) | NQ: {last_price:,.2f}",
        f"Última barra: {last_time:%a %d-%b %H:%M %Z} | Régimen GARCH: {reg['label']} (P{reg['percentile']:.1f}) | Persistencia: {fit.persistence:.4f}"
    ))

    # UI FILTRADA: Solo se muestran en pantalla los bordes extremos (P05, P10, P50, P90, P95)
    t = Table(
        ["Bloque", "Hora NY", "GARCH σ (Pts)", "Suelo Extremo P05 (95%)", "Suelo P10 (90%)", "Baseline P50 (Mediana)", "Techo P90 (90%)", "Techo Extremo P95 (95%)"],
        aligns="llrrrrrr",
        title="BORDES EXTREMOS DEL CONO ESTOCASTICO DE 32 BLOQUES DE 15 MINUTOS (8 HORAS AMERICA/NEW_YORK)"
    )
    for i in range(0, n_periods, 4):
        hora_ny = future_dates[i].strftime("%a %H:%M")
        garch_pts = last_price * forecast_vol[i]
        t.add_row([
            f"B#{i+1:02d}",
            hora_ny,
            f"{fmt_num(garch_pts, 2)} pts",
            fmt_num(p05[i], 2),
            fmt_num(p10[i], 2),
            fmt_num(p50[i], 2),
            fmt_num(p90[i], 2),
            fmt_num(p95[i], 2),
        ])
    print(t.render())

    t_tp = Table(
        ["Horizonte Operativo", "Bloque", "Suelo Extremo (P05 / P10)", "Baseline (P50)", "Techo Institucional (P90)", "Techo Extremo (P95)", "Acción en Bordes Extremos"],
        aligns="llrrrrl",
        title="ZONAS DE REBOTE Y LIQUIDACION EN EXTREMOS DEL CONO (P05 / P10 / P50 / P90 / P95)"
    )
    for label, idx_b in [("1 Hora (Corto Plazo)", 3), ("2 Horas (Sesión Apertura)", 7), ("4 Horas (Media Sesión)", 15), ("8 Horas (Jornada Completa)", 31)]:
        idx_b = min(idx_b, n_periods - 1)
        t_tp.add_row([
            label,
            f"B#{idx_b+1:02d} ({future_dates[idx_b]:%H:%M})",
            f"{p05[idx_b]:,.2f} / {p10[idx_b]:,.2f}",
            f"{p50[idx_b]:,.2f}",
            f"{p90[idx_b]:,.2f} ({p90[idx_b]-last_price:+.1f}p)",
            f"{p95[idx_b]:,.2f} ({p95[idx_b]-last_price:+.1f}p)",
            "LONG en P10/P05 | SHORT en P90/P95",
        ])
    print("\n" + t_tp.render() + "\n")

    import matplotlib.pyplot as plt
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(17.0, 5.4))

    n_hist_plot = 96
    hist_tail = bars_15m["Close"].tail(n_hist_plot)
    x_hist = np.arange(len(hist_tail))
    x_fut = np.arange(len(hist_tail) - 1, len(hist_tail) - 1 + n_periods + 1)
    y_garch_line = np.insert(garch_projected_prices, 0, last_price)
    y_p10 = np.insert(p10, 0, last_price)
    y_p90 = np.insert(p90, 0, last_price)

    ax1.plot(x_hist, hist_tail.to_numpy(), color=THEME["blue"], lw=1.8, label="Histórico NQ (15m)")
    ax1.plot(x_fut, y_garch_line, color=THEME["red"], lw=2.6, label="Deriva AR+GARCH (8h)")
    ax1.fill_between(x_fut, y_p10, y_p90, color=THEME["indigo"], alpha=0.30, label="Banda Extrema P10-P90 (80%)")
    ax1.set_title("1. Histórico + Proyección AR(p)+GJR-GARCH (32x15m)")
    ax1.set_xlabel("Barras de 15m")
    ax1.set_ylabel("Precio NQ")
    ax1.legend(loc="upper left")

    x_mc = np.arange(1, n_periods + 1)
    ax2.plot(x_mc, simulations[:, :100], color=THEME["muted"], alpha=0.12, lw=0.7)
    ax2.plot(x_mc, p50, color=THEME["red"], lw=2.5, label="Baseline P50")
    ax2.axhline(last_price, color=THEME["yellow"], ls="--", lw=1.2, label=f"Spot ({last_price:,.0f})")
    ax2.set_title(f"2. Simulación Monte Carlo FHS ({n_sims:,} Trayectorias)")
    ax2.set_xlabel("Bloques Futuros de 15m (1..32)")
    ax2.legend(loc="upper left")

    ax3.plot(x_mc, p50, color=THEME["red"], lw=2.4, label="Baseline P50 (Mediana)")
    ax3.fill_between(x_mc, p05, p95, color=THEME["violet"], alpha=0.22, label="Cono Extremo 90% (P05 - P95)")
    ax3.fill_between(x_mc, p10, p90, color=THEME["indigo"], alpha=0.40, label="Cono Institucional 80% (P10 - P90)")
    ax3.axhline(last_price, color=THEME["yellow"], ls="--", lw=1.2)
    ax3.set_title("3. Bordes del Cono de Probabilidad (P05 / P10 / P50 / P90 / P95)")
    ax3.set_xlabel("Bloques Futuros de 15m (8 Horas NY)")
    ax3.legend(loc="upper left")

    finalize(fig, "montecarlo_garch_15m_nq", show=show_plot)

    return {
        "spot": last_price,
        "last_time": last_time,
        "future_dates": future_dates,
        "forecast_vol": forecast_vol,
        "forecast_mean": forecast_mean,
        "sim_summary": sim_summary,
        "p01": p01,
        "p05": p05,
        "p10": p10,
        "p16": p16,
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "p84": p84,
        "p90": p90,
        "p95": p95,
        "p99": p99,
        "iqr_pts": iqr_pts,
        "sd1_band_pts": sd1_band_pts,
        "simulations": simulations,
        "fit": fit,
        "regime": reg,
    }


if __name__ == "__main__":
    ejecutar_suite_ny()
