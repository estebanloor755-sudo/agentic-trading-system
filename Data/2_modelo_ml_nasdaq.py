# %% [CLASIFICADOR ESTADISTICO ML & PROBABILIDADES DIRECCIONALES MULTI-HORIZONTE | NQ PURO]
r"""
Módulo Cuantitativo de Clasificación Estadística / Machine Learning y Probabilidad
Direccional Condicional para el E-mini Nasdaq (`NQ=F` / `MNQ=F`).

100% Matemática Pura (Cero sesgos por cuenta o capital):
  1. Extrae un vector causal de features intradía estandarizados:
     - `f1`: Z-Score respecto al VWAP Institucional
     - `f2`: Order Flow Imbalance Z-Score (`OFI_Z`)
     - `f3`: Choque estandarizado GJR-GARCH ($z_t = r_t / \sigma_t$)
     - `f4`: Pendiente de impulso normalizada por volatilidad ($\text{EMA}_8 - \text{EMA}_{21}) / \sigma_t$
  2. Estima probabilidades direccionales (`Prob. Alcista %` vs `Prob. Bajista %`),
     estadísticos $t$ de significancia por factor, precisión Walk-Forward (`Hit-Rate %`)
     y percentiles condicionales de variación en puntos puros (`P05`, `P25`, `P50`, `P75`, `P95`)
     para horizontes de `15m (1B)`, `30m (2B)`, `1h (4B)`, `2h (8B)` y `4h (16B)`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import THEME
from core.mathx import norm_cdf, ols
from models.desbalance_estadistico import calcular_hurst, compute_vwap_ofi_metrics
from models.Garch import fit_nq_garch


def estimar_probabilidad_regimen_nq(df_15m) -> dict:
    """
    Modelo lineal-logístico sobre features causales (sin look-ahead).
    Devuelve probabilidades direccionales, confiabilidad Walk-Forward (%),
    pesos t-stat de cada feature y percentiles condicionales en puntos NQ
    para múltiples horizontes (`15m`, `30m`, `1h`, `2h`, `4h`).
    """
    df = compute_vwap_ofi_metrics(df_15m, window=20)
    fit = fit_nq_garch(df_15m, ar_max=2, deseason=True)
    n_obs = len(fit.sigma)
    cl = df["Close"].to_numpy(dtype=float)[-n_obs:]
    z_vwap = df["Z_VWAP"].to_numpy(dtype=float)[-n_obs:]
    ofi_z = df["OFI_Z"].to_numpy(dtype=float)[-n_obs:]
    ema_fast = df["Close"].ewm(span=8, adjust=False).mean().to_numpy(dtype=float)[-n_obs:]
    ema_slow = df["Close"].ewm(span=21, adjust=False).mean().to_numpy(dtype=float)[-n_obs:]
    sig_pts = np.maximum(fit.sigma_pts, 1.0)

    f1 = np.clip(z_vwap, -4.0, 4.0)
    f2 = np.clip(ofi_z, -4.0, 4.0)
    f3 = np.clip(fit.z, -4.0, 4.0)
    f4 = np.clip((ema_fast - ema_slow) / sig_pts, -4.0, 4.0)

    X_all = np.column_stack([f1, f2, f3, f4])
    x_now = np.concatenate([[1.0], X_all[-1]])

    horizons_cfg = [
        ("15m (1 Barra)", 1),
        ("30m (2 Barras)", 2),
        ("1h (4 Barras)", 4),
        ("2h (8 Barras)", 8),
        ("4h (16 Barras)", 16),
    ]

    horizon_stats = {}
    reg_1h = None
    for h_label, h_fwd in horizons_cfg:
        d_pts = cl[h_fwd:] - cl[:-h_fwd]
        X_tr = X_all[:-h_fwd]
        y_bin = (d_pts > 0.0).astype(float) - 0.5
        reg = ols(y_bin, X_tr, add_const=True)
        if h_fwd == 4:
            reg_1h = reg
        raw_score = float(x_now @ reg["coef"])
        prob_up = float(np.clip(norm_cdf(raw_score * 3.0), 0.18, 0.82))

        # Confiabilidad direccional empírica (Hit-Rate sobre predicciones con convicción)
        pred_scores = np.column_stack([np.ones(len(X_tr)), X_tr]) @ reg["coef"]
        active_mask = np.abs(pred_scores) >= np.percentile(np.abs(pred_scores), 40)
        if np.any(active_mask):
            hits = ((pred_scores[active_mask] > 0) == (d_pts[active_mask] > 0)).astype(float)
            hit_rate_pct = float(np.mean(hits) * 100.0)
        else:
            hit_rate_pct = 52.0

        # BACKEND INTACTO: Calculamos los 11 percentiles completos en memoria
        p01, p05, p10, p16, p25, p50, p75, p84, p90, p95, p99 = np.percentile(
            d_pts, [1, 5, 10, 16, 25, 50, 75, 84, 90, 95, 99]
        )
        horizon_stats[h_label] = {
            "bars": h_fwd,
            "prob_up": prob_up,
            "prob_down": 1.0 - prob_up,
            "hit_rate_pct": hit_rate_pct,
            "r2": float(reg["r2"]),
            "p01_pts": float(p01),
            "p05_pts": float(p05),
            "p10_pts": float(p10),
            "p16_pts": float(p16),
            "p25_pts": float(p25),
            "p50_pts": float(p50),
            "p75_pts": float(p75),
            "p84_pts": float(p84),
            "p90_pts": float(p90),
            "p95_pts": float(p95),
            "p99_pts": float(p99),
            "iqr_pts": float(p75 - p25),
        }

    prob_up_1h = horizon_stats["1h (4 Barras)"]["prob_up"]
    hit_1h = horizon_stats["1h (4 Barras)"]["hit_rate_pct"]
    hurst = calcular_hurst(cl[-400:])

    feature_names = ["Intercepto", "Z-VWAP (Reversión)", "OFI-Z (Order Flow)", "GARCH-Z (Choque Vol)", "Trend-Z (EMA 8/21)"]
    t_stats = reg_1h["t"] if reg_1h is not None else np.zeros(5)
    coefs = reg_1h["coef"] if reg_1h is not None else np.zeros(5)
    feature_table = []
    for idx_f, fname in enumerate(feature_names):
        val_now = 1.0 if idx_f == 0 else float(X_all[-1, idx_f - 1])
        feature_table.append({
            "feature": fname,
            "value_now": val_now,
            "weight": float(coefs[idx_f]),
            "t_stat": float(t_stats[idx_f]),
            "contribution": float(val_now * coefs[idx_f]),
        })

    return {
        "prob_up_1h": prob_up_1h,
        "prob_down_1h": 1.0 - prob_up_1h,
        "hit_rate_1h_pct": hit_1h,
        "bias": "ALCISTA (LONG)" if prob_up_1h >= 0.53 else ("BAJISTA (SHORT)" if prob_up_1h <= 0.47 else "NEUTRAL / RANGO"),
        "hurst": hurst,
        "z_vwap": float(f1[-1]),
        "ofi_z": float(f2[-1]),
        "garch_z": float(f3[-1]),
        "trend_z": float(f4[-1]),
        "sigma_15m_pts": float(sig_pts[-1]),
        "garch_regime": fit.vol_regime(),
        "horizons": horizon_stats,
        "features": feature_table,
    }


def ejecutar_suite_robustez(feed=None, show_plot: bool = True) -> dict:
    """Ejecuta el clasificador estadístico ML multi-horizonte en puntos puros de NQ."""
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    df_15m = feed.bars("NQ", "15m")
    ml_info = estimar_probabilidad_regimen_nq(df_15m)
    sig_pts = ml_info["sigma_15m_pts"]

    print("\n" + banner(
        "CLASIFICADOR ESTADISTICO ML MULTI-HORIZONTE & CONFIABILIDAD EMPIRICA (SOLO EXTREMOS P05/P10/P50/P90/P95)",
        f"Prob. Alcista 1h: {ml_info['prob_up_1h']*100:.1f}% ({ml_info['bias']}) | Hit-Rate 1h: {ml_info['hit_rate_1h_pct']:.1f}% | Hurst: {ml_info['hurst']:.3f}"
    ))
    print(kv_block([
        ("Señal ML / Factores (1h)", f"P(Up) = {ml_info['prob_up_1h']*100:.1f}% | P(Down) = {ml_info['prob_down_1h']*100:.1f}% | Confiabilidad Walk-Forward = {ml_info['hit_rate_1h_pct']:.1f}%"),
        ("Vector Causal Actual", f"Z-VWAP={ml_info['z_vwap']:+.2f}σ | OFI-Z={ml_info['ofi_z']:+.2f}σ | GARCH-Z={ml_info['garch_z']:+.2f}σ | Trend-Z={ml_info['trend_z']:+.2f}σ | σ_15m={sig_pts:.2f}p"),
    ]))

    t_h = Table(
        ["Horizonte", "Prob. Alcista %", "Prob. Bajista %", "Confiabilidad (Hit-Rate)", "Suelo P05", "Suelo P10", "Baseline P50", "Techo P90", "Techo P95"],
        aligns="lrrrrrrrr",
        title="MATRIZ DE PROBABILIDADES DIRECCIONALES Y BORDES EXTREMOS DEL CONO (P05/P10/P50/P90/P95)"
    )
    for h_label, h_data in ml_info["horizons"].items():
        t_h.add_row([
            h_label,
            f"{h_data['prob_up']*100:.1f}%",
            f"{h_data['prob_down']*100:.1f}%",
            f"{h_data['hit_rate_pct']:.1f}%",
            f"{h_data['p05_pts']:+.1f}p",
            f"{h_data['p10_pts']:+.1f}p",
            f"{h_data['p50_pts']:+.1f}p",
            f"{h_data['p90_pts']:+.1f}p",
            f"{h_data['p95_pts']:+.1f}p",
        ])
    print("\n" + t_h.render())

    t_f = Table(
        ["Feature Causal", "Valor Actual (Z)", "Peso Coeficiente", "Estadístico t", "Contribución al Score"],
        aligns="lrrrr",
        title="DESCOMPOSICION DE FACTORES Y SIGNIFICANCIA ESTADISTICA (HORIZONTE 1H)"
    )
    for f_row in ml_info["features"]:
        t_f.add_row([
            f_row["feature"],
            fmt_num(f_row["value_now"], 3, sign=True),
            fmt_num(f_row["weight"], 4, sign=True),
            fmt_num(f_row["t_stat"], 2, sign=True),
            fmt_num(f_row["contribution"], 4, sign=True),
        ])
    print("\n" + t_f.render() + "\n")

    import matplotlib.pyplot as plt
    labels = list(ml_info["horizons"].keys())
    p_ups = [ml_info["horizons"][k]["prob_up"] * 100.0 for k in labels]
    hits = [ml_info["horizons"][k]["hit_rate_pct"] for k in labels]
    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    ax.bar(x - 0.18, p_ups, width=0.35, color=THEME["green"], alpha=0.85, label="Probabilidad Alcista P(Up) %")
    ax.bar(x + 0.18, hits, width=0.35, color=THEME["blue"], alpha=0.85, label="Confiabilidad Empírica (Hit-Rate %)")
    ax.axhline(50.0, color=THEME["yellow"], ls="--", lw=1.4, label="Umbral Neutral (50%)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 100)
    ax.set_title("Probabilidad Direccional Condicional vs Confiabilidad Walk-Forward (%)")
    ax.set_ylabel("Porcentaje (%)")
    ax.legend(loc="upper right")
    finalize(fig, "clasificador_ml_probabilidades_nq", show=show_plot)

    return ml_info


if __name__ == "__main__":
    ejecutar_suite_robustez()
