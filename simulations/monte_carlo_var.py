# %% [MONTE CARLO DISTRIBUCION DE COLA, PERCENTILES PUROS Y VaR/CVaR EN PUNTOS NQ]
"""
Motor Estocástico de Distribución de Probabilidad, Conos de Percentiles y Métricas
de Cola (VaR / CVaR en Puntos Puros) para el E-mini Nasdaq (`NQ=F` / `MNQ=F`).

100% Matemática Pura de Mercado (Cero sesgos por tamaño de cuenta o lotaje):
  1. Distribución Monte Carlo acoplada a la volatilidad GJR-GARCH(1,1) actual
     para horizontes intradía (`15m`, `30m`, `1h`, `2h`, `4h`, `8h = 32 barras`)
     y multi-sesión (`Día +1` a `Día +5`).
  2. Percentiles exactos de precio y variación en puntos:
     `P01`, `P05`, `P10`, `P16 (-1σ)`, `P25`, `P50 (Mediana)`, `P75`, `P84 (+1σ)`, `P90`, `P95`, `P99`.
  3. Métricas de cola en puntos puros de NQ y retorno porcentual:
     - Desviación Estándar 1-SD (68.2%) y 2-SD (95.4%)
     - Value at Risk: VaR 95% y VaR 99% (en puntos NQ y %)
     - Expected Shortfall / Tail Conditional Expectation: CVaR 95% y CVaR 99% (en puntos NQ y %)
     - Probabilidad Direccional Empírica P(S_T > S_0) (%), Asimetría (Skewness) y Curtosis.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MNQ, NQ, THEME
from core import sessions
from models.Garch import fit_nq_garch, simulate_returns


def calcular_distribucion_cola_nq(
    fit,
    spot: float,
    n_sims: int = 15_000,
    seed: int = 42,
) -> dict:
    """
    Calcula la matriz completa de percentiles (`P01` a `P99`), `1-SD`, `2-SD`,
    `VaR 95%`, `VaR 99%`, `CVaR 95%`, `CVaR 99%` y probabilidades direccionales
    en puntos puros de NQ para todos los horizontes intradía (15m a 8h).
    """
    last_ts = pd.Timestamp(fit.index[-1]) if hasattr(fit, "index") else sessions.now_ny()
    fut_idx = sessions.next_bars(last_ts, n=32, freq="15min")
    ret_mat = simulate_returns(fit, fut_idx, n_sims=n_sims, seed=seed, shocks="fhs")
    cum_ret = np.cumsum(ret_mat, axis=0)
    price_paths = spot * np.exp(cum_ret)

    horizons = {
        "15m (B#01 - 1 Barra)": 0,
        "30m (B#02 - 2 Barras)": 1,
        "1h (B#04 - 4 Barras)": 3,
        "2h (B#08 - Apertura NY)": 7,
        "4h (B#16 - Media Sesión)": 15,
        "6h (B#24 - Tarde NY)": 23,
        "8h (B#32 - Sesión Completa)": 31,
    }

    p_levels = [1, 5, 10, 16, 25, 50, 75, 84, 90, 95, 99]
    metrics_by_h = {}

    for h_name, idx_h in horizons.items():
        px_h = price_paths[idx_h, :]
        d_pts = px_h - spot
        losses_pts = -d_pts
        sd1_pts = float(np.std(d_pts, ddof=1))
        sd2_pts = 2.0 * sd1_pts

        try:
            from core.jit_math import calc_tail_metrics_fast
            _, var95_pts, cvar95_pts, var99_pts, cvar99_pts = calc_tail_metrics_fast(losses_pts)
        except Exception:
            var95_pts = float(np.percentile(losses_pts, 95))
            var99_pts = float(np.percentile(losses_pts, 99))
            cvar95_pts = float(np.mean(losses_pts[losses_pts >= var95_pts]))
            cvar99_pts = float(np.mean(losses_pts[losses_pts >= var99_pts]))

        pct_vals = np.percentile(px_h, p_levels)
        pct_dict = {f"P{p:02d}": float(v) for p, v in zip(p_levels, pct_vals)}
        prob_up = float(np.mean(d_pts > 0.0) * 100.0)

        # Momentos de orden superior (asimetría y curtosis de la distribución proyectada)
        z_centered = (d_pts - float(np.mean(d_pts))) / max(sd1_pts, 1e-9)
        skew = float(np.mean(z_centered ** 3))
        kurt = float(np.mean(z_centered ** 4))

        metrics_by_h[h_name] = {
            "block_idx": idx_h,
            "ny_time": fut_idx[idx_h].strftime("%H:%M NY"),
            "sd1_pts": sd1_pts,
            "sd2_pts": sd2_pts,
            "var95_pts": var95_pts,
            "var99_pts": var99_pts,
            "cvar95_pts": cvar95_pts,
            "cvar99_pts": cvar99_pts,
            "var95_pct": (var95_pts / spot) * 100.0,
            "var99_pct": (var99_pts / spot) * 100.0,
            "cvar99_pct": (cvar99_pts / spot) * 100.0,
            "prob_up_pct": prob_up,
            "skew": skew,
            "kurtosis": kurt,
            "iqr_pts": float(pct_dict["P75"] - pct_dict["P25"]),
            "range90_pts": float(pct_dict["P95"] - pct_dict["P05"]),
            **pct_dict,
        }

    return {
        "spot": spot,
        "future_dates": fut_idx,
        "price_paths": price_paths,
        "horizons": metrics_by_h,
    }


def ejecutar_monte_carlo_visual_nq(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    bars_15m = feed.bars("NQ", "15m")
    fit = fit_nq_garch(bars_15m, ar_max=2, deseason=True)
    reg = fit.vol_regime()
    S0 = float(bars_15m["Close"].iloc[-1])

    tail_res = calcular_distribucion_cola_nq(fit, S0, n_sims=15_000, seed=42)

    # Simulación multi-día (5 sesiones x 32 bloques de 15m) calibrada con la vol GARCH actual
    rng = np.random.default_rng(42)
    dias_proyeccion = 5
    pasos_por_dia = 32
    total_pasos = dias_proyeccion * pasos_por_dia
    num_sims = 15_000

    vol_anual = fit.ann_vol_now()
    mu_anual = 0.08
    dt = (1.0 / 252.0) / pasos_por_dia

    nu = max(fit.nu, 3.5)
    z = rng.standard_t(nu, size=(num_sims, total_pasos)) / math.sqrt(nu / (nu - 2.0))
    log_returns = (mu_anual - 0.5 * (vol_anual ** 2)) * dt + vol_anual * math.sqrt(dt) * z
    trayectorias = np.hstack([np.full((num_sims, 1), S0), S0 * np.exp(np.cumsum(log_returns, axis=1))])

    # BACKEND INTACTO: Calculamos los 11 percentiles completos en memoria para todas las sesiones
    percentiles_all = [1, 5, 10, 16, 25, 50, 75, 84, 90, 95, 99]
    multi_day_all = {}
    for d in range(1, dias_proyeccion + 1):
        idx_paso = d * pasos_por_dia
        vals_all = np.percentile(trayectorias[:, idx_paso], percentiles_all)
        multi_day_all[f"Día +{d}"] = {f"P{p:02d}": float(v) for p, v in zip(percentiles_all, vals_all)}
    tail_res["multi_day_percentiles_all"] = multi_day_all

    print("\n" + banner(
        f"DISTRIBUCION ESTOCASTICA MONTE CARLO + GJR-GARCH(1,1) (EXTREMOS PUROS P05/P10/P50/P90/P95) | SPOT: {S0:,.2f}",
        f"Volatilidad GARCH Anualizada: {vol_anual*100:.2f}% ({reg['label']}, P{reg['percentile']:.1f}) | Colas t-Student (ν={fit.nu:.1f})"
    ))
    h1 = tail_res["horizons"]["1h (B#04 - 4 Barras)"]
    h8 = tail_res["horizons"]["8h (B#32 - Sesión Completa)"]
    print(kv_block([
        ("Parámetros GJR-GARCH", f"Persistencia: {fit.persistence:.4f} | ν (t-Student): {fit.nu:.2f} | σ_15m actual: {reg['sigma_now_pts']:.2f} pts (Percentil {reg['percentile']:.1f}%)"),
        ("Extremos Cono 1 Hora", f"Suelo P05={h1['P05']:,.1f} | Suelo P10={h1['P10']:,.1f} | Baseline P50={h1['P50']:,.1f} | Techo P90={h1['P90']:,.1f} | Techo P95={h1['P95']:,.1f}"),
        ("Extremos Cono 8 Horas", f"Suelo P05={h8['P05']:,.1f} | Suelo P10={h8['P10']:,.1f} | Baseline P50={h8['P50']:,.1f} | Techo P90={h8['P90']:,.1f} | Techo P95={h8['P95']:,.1f}"),
        ("Riesgo de Cola Extremo", f"1h VaR95=-{h1['var95_pts']:.1f}p, VaR99=-{h1['var99_pts']:.1f}p, CVaR99=-{h1['cvar99_pts']:.1f}p | 8h VaR95=-{h8['var95_pts']:.1f}p, CVaR99=-{h8['cvar99_pts']:.1f}p"),
    ]))

    # UI FILTRADA: Solo Bordes Extremos del Cono (P05, P10, P50, P90, P95) y Liquidación VaR/CVaR 99%
    t_var = Table(
        ["Horizonte Intradía", "Hora NY", "Suelo P05 (95%)", "Suelo P10 (90%)", "Baseline P50", "Techo P90 (90%)", "Techo P95 (95%)", "VaR 99% (Cola)", "CVaR 99% (ES)"],
        aligns="llrrrrrrr",
        title="BORDES EXTREMOS DEL CONO MONTE CARLO (P05/P10/P50/P90/P95) Y COLAS DE LIQUIDACION (15,000 SIMS)"
    )
    for h_name, info in tail_res["horizons"].items():
        t_var.add_row([
            h_name,
            info["ny_time"],
            f"{fmt_num(info['P05'], 1)} ({info['P05']-S0:+.0f}p)",
            f"{fmt_num(info['P10'], 1)} ({info['P10']-S0:+.0f}p)",
            f"{fmt_num(info['P50'], 1)}",
            f"{fmt_num(info['P90'], 1)} ({info['P90']-S0:+.0f}p)",
            f"{fmt_num(info['P95'], 1)} ({info['P95']-S0:+.0f}p)",
            f"-{fmt_num(info['var99_pts'], 1)}p",
            f"-{fmt_num(info['cvar99_pts'], 1)}p",
        ])
    print("\n" + t_var.render())

    # Tabla 2: Cono Multi-Sesión (5 Días) mostrando en UI exclusivamente P05, P10, P50, P90, P95
    t_mc = Table(
        ["Sesión", "Suelo Extremo P05 (95%)", "Suelo Institucional P10 (90%)", "Mediana / Baseline P50", "Techo Institucional P90 (90%)", "Techo Extremo P95 (95%)"],
        aligns="lrrrrr",
        title=f"CONO DE PROBABILIDAD MULTI-SESION — SOLO BORDES EXTREMOS ({num_sims:,} TRAYECTORIAS M15)"
    )
    for d_label, p_map in multi_day_all.items():
        t_mc.add_row([
            d_label,
            fmt_num(p_map["P05"], 1),
            fmt_num(p_map["P10"], 1),
            fmt_num(p_map["P50"], 1),
            fmt_num(p_map["P90"], 1),
            fmt_num(p_map["P95"], 1),
        ])
    print("\n" + t_mc.render() + "\n")

    import matplotlib.pyplot as plt
    eje_x = np.arange(total_pasos + 1)
    p05_t = np.percentile(trayectorias, 5, axis=0)
    p10_t = np.percentile(trayectorias, 10, axis=0)
    p50_t = np.percentile(trayectorias, 50, axis=0)
    p90_t = np.percentile(trayectorias, 90, axis=0)
    p95_t = np.percentile(trayectorias, 95, axis=0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.2))
    ax1.plot(eje_x, trayectorias[:35, :].T, color=THEME["text"], alpha=0.06, lw=0.7)
    ax1.fill_between(eje_x, p05_t, p95_t, color=THEME["red"], alpha=0.18, label="Banda Extrema P05 - P95 (90% Confianza)")
    ax1.fill_between(eje_x, p10_t, p90_t, color=THEME["blue"], alpha=0.25, label="Banda Institucional P10 - P90 (80% Confianza)")
    ax1.plot(eje_x, p50_t, color=THEME["green"], lw=2.2, label="Mediana / Baseline P50")
    ax1.set_title("1. Cono Estocástico Monte Carlo — Solo Bordes Extremos (P05/P10/P50/P90/P95)")
    ax1.set_xlabel("Bloques de 15 Minutos")
    ax1.set_ylabel("Precio Proyectado NQ")
    ax1.legend(loc="upper left")

    d_pts_8h = tail_res["price_paths"][-1, :] - S0
    v95_p = -h8["var95_pts"]
    v99_p = -h8["var99_pts"]
    cvar99_p = -h8["cvar99_pts"]

    ax2.hist(d_pts_8h, bins=80, color=THEME["indigo"], alpha=0.78, edgecolor="none", density=True)
    ax2.axvline(v95_p, color=THEME["amber"], ls="--", lw=1.8, label=f"VaR 95% ({v95_p:+.1f} pts)")
    ax2.axvline(v99_p, color=THEME["red"], ls="--", lw=1.8, label=f"VaR 99% ({v99_p:+.1f} pts)")
    ax2.axvline(cvar99_p, color=THEME["pink"], ls=":", lw=2.0, label=f"CVaR 99% ({cvar99_p:+.1f} pts)")
    ax2.axvline(0.0, color=THEME["yellow"], ls="-", lw=1.4, label="Spot Actual (0 pts)")
    ax2.set_title("2. Distribución de Variación en Puntos NQ (Horizonte 8h = 32 Barras 15m)")
    ax2.set_xlabel("Variación Proyectada en Puntos NQ")
    ax2.set_ylabel("Densidad de Probabilidad")
    ax2.legend(loc="upper left")
    finalize(fig, "monte_carlo_var_puro_nq", show=show_plot)

    return tail_res


if __name__ == "__main__":
    ejecutar_monte_carlo_visual_nq()
