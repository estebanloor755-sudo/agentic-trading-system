# %% [LIQUIDITY PROVISION, MARKET MAKER ALPHA, ROLL SPREAD, KYLE'S LAMBDA & VPIN | NQ]
"""
Microestructura Institucional, Provisión de Liquidez y Toxicidad de Flujo (VPIN)
para el E-mini Nasdaq (`NQ=F` / `MNQ=F`) en 5m (Disparo) y 15m (Macro):

  1. Order Book Imbalance Proxy (OBI): presión compradora/vendedora en el libro
     ponderada por volumen relativo (RVOL).
  2. Roll Effective Spread (1984) + Corwin-Schultz High-Low Spread: mide el
     spread efectivo implícito en puntos y ticks de NQ (0.25 pts = 1 tick).
  3. Kyle's Lambda (λ): pendiente de impacto de precio (ΔP_t = λ * OFI_t + e_t)
     en puntos de NQ por cada 1,000 contratos netos.
       - λ ALTO + VPIN ALTO  -> Libro vacío / Barrido de Liquidez (Liquidity Sweep)
       - λ BAJO + RVOL ALTO  -> Absorción Institucional (Órdenes Iceberg pasivas)
  4. Bulk-Volume VPIN (Easley, López de Prado & O'Hara): Probabilidad de Trading
     Informado (0% a 100%) que alerta cuándo los Market Makers retiran liquidez.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import NQ, THEME
from core.mathx import norm_cdf
from core import sessions
from models.desbalance_estadistico import tag_ny_window


def calcular_microestructura_liquidez(df: pd.DataFrame, window: int = 24) -> pd.DataFrame:
    """
    Calcula OBI, RVOL, Roll Spread, Kyle's Lambda (pts / 1,000 contratos) y
    Bulk-Volume VPIN sobre barras OHLCV de 5m o 15m.
    """
    out = df.copy()
    cl = out["Close"].to_numpy(dtype=float)
    hi = out["High"].to_numpy(dtype=float)
    lo = out["Low"].to_numpy(dtype=float)
    op = out["Open"].to_numpy(dtype=float)
    vol = np.maximum(out["Volume"].to_numpy(dtype=float), 1.0)
    n = len(out)

    dp = np.diff(cl, prepend=cl[0])
    rng = np.maximum(hi - lo, NQ.tick_size)

    # 1. Order Book Imbalance Proxy (OBI in [-1, +1]) y RVOL
    clv = ((cl - lo) - (hi - cl)) / rng
    vol_ma = pd.Series(vol, index=out.index).rolling(window, min_periods=5).mean().to_numpy()
    rvol = vol / np.maximum(vol_ma, 1.0)
    obi = np.clip(clv * np.sqrt(np.clip(rvol, 0.25, 4.0)), -2.0, 2.0)

    # 2. Bulk-Volume Classification (López de Prado) -> VPIN
    sd_dp = pd.Series(dp, index=out.index).rolling(window, min_periods=5).std(ddof=1).to_numpy()
    sd_dp = np.where((sd_dp <= 1e-6) | ~np.isfinite(sd_dp), np.std(dp) + 1e-6, sd_dp)
    z_dp = np.clip(dp / sd_dp, -4.0, 4.0)
    v_buy = vol * norm_cdf(z_dp)
    v_sell = vol - v_buy
    v_imb = np.abs(v_buy - v_sell)
    signed_flow = v_buy - v_sell  # flujo neto firmado en contratos

    vpin_num = pd.Series(v_imb, index=out.index).rolling(window, min_periods=5).sum().to_numpy()
    vpin_den = pd.Series(vol, index=out.index).rolling(window, min_periods=5).sum().to_numpy()
    vpin = np.clip(vpin_num / np.maximum(vpin_den, 1.0), 0.0, 1.0)

    # 3. Roll Effective Spread (pts): 2 * sqrt(max(0, -Cov(dP_t, dP_{t-1})))
    #    Combinado con estimador de rango intrabarra cuando hay momentum positivo
    roll_pts = np.empty(n, dtype=float)
    kyle_lambda = np.empty(n, dtype=float)
    flow_k = signed_flow / 1000.0  # en miles de contratos NQ

    for i in range(n):
        i0 = max(0, i - window + 1)
        dp_w = dp[i0:i + 1]
        fl_w = flow_k[i0:i + 1]
        n_trades_est = max(math.sqrt(float(np.median(vol[i0:i + 1])) / 2.5), 10.0)
        if len(dp_w) >= 6:
            cov1 = float(np.cov(dp_w[1:], dp_w[:-1])[0, 1])
            # Roll (1984) reescalado de barra agregada a spread efectivo por transacción
            r_est = (2.0 * math.sqrt(max(0.0, -cov1))) / (n_trades_est * 0.45)
            hl_proxy = (float(np.median(rng[i0:i + 1])) / n_trades_est) * 0.55
            roll_pts[i] = round(max(r_est, hl_proxy, NQ.tick_size) * 4.0) / 4.0
            # Kyle's Lambda: pendiente cov(|dP|, |flow_k|) / var(flow_k)
            var_f = float(np.var(fl_w))
            if var_f > 1e-9:
                lam = float(np.cov(np.abs(dp_w), np.abs(fl_w))[0, 1]) / var_f
                if lam <= 0:
                    lam = float(np.mean(np.abs(dp_w) / np.maximum(np.abs(fl_w), 0.05))) * 0.25
                kyle_lambda[i] = max(lam, 0.10)
            else:
                kyle_lambda[i] = 1.0
        else:
            roll_pts[i] = max(round((float(rng[i]) / n_trades_est) * 2.0) / 4.0, NQ.tick_size)
            kyle_lambda[i] = 1.0

    # Percentiles históricos para detectar Absorción vs Barrido (Sweep)
    lam_med = float(np.nanmedian(kyle_lambda))
    out["RVOL"] = rvol
    out["OBI"] = obi
    out["SignedFlow"] = signed_flow
    out["Roll_Pts"] = roll_pts
    out["Roll_Ticks"] = roll_pts / NQ.tick_size
    out["Kyle_Lambda"] = kyle_lambda
    out["VPIN"] = vpin * 100.0
    out["Body_Ratio"] = np.abs(cl - op) / rng

    # Clasificación barra a barra de absorción institucional vs barrido
    eventos = []
    for i in range(n):
        rv = rvol[i]
        vp = out["VPIN"].iloc[i]
        lam = kyle_lambda[i]
        br = out["Body_Ratio"].iloc[i]
        c_loc = clv[i]
        if rv >= 1.35 and (lam <= 1.05 * lam_med or br <= 0.38):
            if c_loc >= 0.15:
                eventos.append("ABSORCION COMPRADORA (Iceberg Bid -> Rebote Alcista)")
            elif c_loc <= -0.15:
                eventos.append("ABSORCION VENDEDORA (Iceberg Ask -> Techo Intradía)")
            else:
                eventos.append("ABSORCION INSTITUCIONAL EN EQUILIBRIO (Pinning)")
        elif vp >= 62.0 and lam > 1.15 * lam_med:
            if dp[i] > 0:
                eventos.append("BARRIDO DE LIQUIDEZ ALCISTA (Sweep / Flujo Informado)")
            else:
                eventos.append("BARRIDO DE LIQUIDEZ BAJISTA (Sweep / Retiro de Bids)")
        elif vp >= 55.0:
            eventos.append("Flujo Informado Moderado (VPIN Elevado)")
        else:
            eventos.append("Provisión Normal de Liquidez (Market Making Estable)")
    out["Micro_Event"] = eventos
    return out


def ejecutar_liquidez_vpin(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    df5 = calcular_microestructura_liquidez(feed.bars("NQ", "5m"), window=24)
    df15 = calcular_microestructura_liquidez(feed.bars("NQ", "15m"), window=20)

    spot = float(df5["Close"].iloc[-1])
    last5 = df5.iloc[-1]
    last15 = df15.iloc[-1]

    vpin5 = float(last5["VPIN"])
    vpin15 = float(last15["VPIN"])
    roll5_pts = float(last5["Roll_Pts"])
    roll5_ticks = float(last5["Roll_Ticks"])
    lam5 = float(last5["Kyle_Lambda"])
    lam15 = float(last15["Kyle_Lambda"])
    obi5 = float(last5["OBI"])

    if vpin5 >= 65.0:
        tox_label = "ALTA TOXICIDAD (VPIN >= 65% -> Dealers amplían spreads; operar rupturas, no reversión)"
    elif vpin5 >= 50.0:
        tox_label = "TOXICIDAD MODERADA (VPIN 50-65% -> Flujo institucional direccional activo)"
    else:
        tox_label = "BAJA TOXICIDAD (VPIN < 50% -> Market Makers proveen liquidez y capturan el spread)"

    print("\n" + banner(
        f"LIQUIDITY PROVISION, MARKET MAKER ALPHA, ROLL SPREAD, KYLE'S LAMBDA & VPIN | NQ: {spot:,.2f}",
        f"Sincronizado en 5m (Ejecución NY) y 15m (Macro) | Estado VPIN: {tox_label}"
    ))
    print(kv_block([
        ("Roll Effective Spread", f"5m: {roll5_pts:.2f} pts ({roll5_ticks:.1f} ticks = {fmt_usd(roll5_pts * NQ.point_value, 2)}/NQ) | 15m: {float(last15['Roll_Pts']):.2f} pts"),
        ("Kyle's Lambda (λ)", f"5m: {lam5:.2f} pts / 1,000 NQ  |  15m: {lam15:.2f} pts / 1,000 NQ (Impacto de precio por flujo neto)"),
        ("Toxicidad VPIN", f"5m: {vpin5:.1f}%  |  15m: {vpin15:.1f}%  |  Order Book Imbalance (OBI 5m): {obi5:+.2f}"),
        ("Diagnóstico Actual", f"{last5['Micro_Event']}"),
    ]))

    # Tabla en ventanas operativas de 5m (09:30-11:45 y 15:00-16:00 NY)
    mask_ny = [sessions.in_window(ts, "APERTURA_NY") or sessions.in_window(ts, "CIERRE_NY") for ts in df5.index]
    sub5 = df5[mask_ny].tail(14)
    if len(sub5) < 8:
        sub5 = df5.tail(14)

    t = Table(
        ["Hora NY (5m)", "Ventana NY", "Cierre NQ", "RVOL", "OBI Proxy", "Roll Spread", "Kyle λ (pts/1k)", "VPIN (%)", "Diagnóstico de Liquidez / Absorción"],
        aligns="llrrrrrrl",
        title="RADAR DE MICROESTRUCTURA EN 5 MINUTOS: ABSORCION INSTITUCIONAL Y BARRIDOS DE LIQUIDEZ"
    )
    for ts, row in sub5.iterrows():
        t.add_row([
            ts.strftime("%a %H:%M"),
            tag_ny_window(ts),
            fmt_num(row["Close"], 2),
            f"{row['RVOL']:.2f}x",
            f"{row['OBI']:+.2f}",
            f"{row['Roll_Pts']:.2f}p ({row['Roll_Ticks']:.1f}t)",
            fmt_num(row["Kyle_Lambda"], 2),
            f"{row['VPIN']:5.1f}%",
            row["Micro_Event"],
        ])
    print("\n" + t.render() + "\n")

    # Gráfico institucional (3 paneles: Precio + Eventos, VPIN, Kyle's Lambda & Roll Spread)
    import matplotlib.pyplot as plt
    tail_plot = df5.tail(96)
    x = np.arange(len(tail_plot))
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12.5, 8.0), sharex=True)

    cl_p = tail_plot["Close"].to_numpy()
    ax1.plot(x, cl_p, color=THEME["blue"], lw=1.9, label="Cierre NQ (5m)")
    abs_mask = [str(ev).startswith("ABSORCION") for ev in tail_plot["Micro_Event"]]
    swp_mask = [str(ev).startswith("BARRIDO") for ev in tail_plot["Micro_Event"]]
    if any(abs_mask):
        ax1.scatter(x[abs_mask], cl_p[abs_mask], color=THEME["green"], s=45, zorder=5, label="Zona de Absorción (Iceberg)")
    if any(swp_mask):
        ax1.scatter(x[swp_mask], cl_p[swp_mask], color=THEME["red"], marker="^", s=50, zorder=5, label="Barrido de Liquidez (Sweep)")
    ax1.set_title("1. Precio NQ (5m) + Detección de Zonas de Absorción y Barridos de Liquidez")
    ax1.set_ylabel("Precio NQ")
    ax1.legend(loc="upper left")

    ax2.plot(x, tail_plot["VPIN"].to_numpy(), color=THEME["amber"], lw=2.0, label="VPIN - Toxicidad de Flujo Informado (%)")
    ax2.axhline(65.0, color=THEME["red"], ls="--", lw=1.3, label="Alerta Toxicidad Alta (65%)")
    ax2.axhline(50.0, color=THEME["green"], ls=":", lw=1.2, label="Umbral Neutral (50%)")
    ax2.set_title("2. VPIN (Volume-Synchronized Probability of Informed Trading)")
    ax2.set_ylabel("VPIN (%)")
    ax2.legend(loc="upper left")

    ax3.plot(x, tail_plot["Kyle_Lambda"].to_numpy(), color=THEME["violet"], lw=1.9, label="Kyle's Lambda λ (pts / 1,000 NQ)")
    ax3.plot(x, tail_plot["Roll_Pts"].to_numpy(), color=THEME["green"], lw=1.6, ls="--", label="Roll Effective Spread (pts)")
    ax3.set_xticks(x[::8])
    ax3.set_xticklabels([ts.strftime("%H:%M") for ts in tail_plot.index[::8]], rotation=45)
    ax3.set_title("3. Impacto de Precio de Kyle (λ) y Spread Efectivo de Roll (5m)")
    ax3.set_ylabel("Puntos NQ")
    ax3.set_xlabel("Barras de 5 Minutos (America/New_York)")
    ax3.legend(loc="upper left")
    finalize(fig, "liquidez_market_maker_vpin_nq", show=show_plot)

    return {
        "spot": spot,
        "vpin_5m": vpin5,
        "vpin_15m": vpin15,
        "roll_pts_5m": roll5_pts,
        "roll_ticks_5m": roll5_ticks,
        "kyle_lambda_5m": lam5,
        "kyle_lambda_15m": lam15,
        "obi_5m": obi5,
        "last_event": str(last5["Micro_Event"]),
        "toxicity_regime": tox_label,
    }


if __name__ == "__main__":
    ejecutar_liquidez_vpin()
