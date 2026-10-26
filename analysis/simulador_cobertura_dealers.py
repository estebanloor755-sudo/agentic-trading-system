# %% [DYNAMIC HEDGING SIMULATOR: FLUJO DE COBERTURA DELTA-GAMMA-VANNA-CHARM DE DEALERS | NQ]
"""
Simulador Dinámico del Flujo de Cobertura de Market Makers (Dealers) en NQ=F:
  * Modela cuántos contratos de futuros `NQ` ($20/pt) y `MNQ` ($2/pt) tienen que
    comprar o vender dinámicamente los Market Makers ante movimientos de:
        -100, -50, -25, +25, +50 y +100 puntos del E-mini Nasdaq
  * Descompone el flujo exacto (revaluando la cartera completa Black-76 en cada
    nuevo nivel de precio, volatilidad y tiempo) en tres motores institucionales:
      1. FLUJO GAMMA (∂Δ/∂F * dF): Rebalanceo por movimiento direccional del precio.
      2. FLUJO VANNA (∂Δ/∂σ * dσ): Rebalanceo por cambio en Volatilidad Implícita
         inducido por el apalancamiento asimétrico del Nasdaq (caídas suben VXN,
         subidas comprimen VXN -> el "Vanna Rally" institucional).
      3. FLUJO CHARM (∂Δ/∂t * dt): Rebalanceo por paso del tiempo durante la sesión
         de Nueva York (6.5h RTH / 1 día).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.radar_gex_crr_griegos import MotorUnificadoGexCrrGreeks
from core.config import MNQ, NQ, THEME
from models.black_scholes_nq import BlackScholesEminiNasdaq


def _dealer_book_delta(
    spot: float,
    strikes: np.ndarray,
    oi_calls: np.ndarray,
    oi_puts: np.ndarray,
    base_ivs: np.ndarray,
    dte_days: float,
    r: float,
    iv_shift: float = 0.0,
) -> float:
    """
    Exposición Delta Neta de la cartera de los Dealers (en contratos NQ equivalentes).
    Convención institucional:
      * Dealers están LARGOS de Calls (+oi_call * Δ_call) -> Gamma positiva
      * Dealers están CORTOS de Puts  (-oi_put * Δ_put > 0 porque Δ_put < 0) -> Gamma negativa
    Para mantener neutralidad Delta (Δ_port + N_fut = 0), la posición de cobertura
    en futuros es N_fut = -Δ_port. Cuando Δ_port cambia en dΔ_port, los Dealers
    deben ejecutar dN_fut = -dΔ_port contratos de NQ.
    """
    total_delta = 0.0
    for idx, K in enumerate(strikes):
        iv_k = max(float(base_ivs[idx]) + iv_shift, 0.06)
        g = BlackScholesEminiNasdaq(spot, float(K), max(dte_days, 0.05), r, iv_k).full_greeks()
        # Posición de opciones del Dealer: +OI_Call * Call - OI_Put * Put
        dealer_opt_delta = float(oi_calls[idx]) * g.delta_call - float(oi_puts[idx]) * g.delta_put
        total_delta += dealer_opt_delta
    return total_delta


def simular_flujo_cobertura_dealers(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    spot = feed.last_price("NQ", "15m")
    r, _ = feed.risk_free_rate()
    iv_atm, _ = feed.implied_vol()
    chain = feed.option_chain_nq(spot, atm_iv=iv_atm)

    dte_gex = 5.0
    motor = MotorUnificadoGexCrrGreeks(F=spot, r=r, iv_atm=iv_atm, dte_gex=dte_gex, dte_crr=30.0)
    res_gex = motor.evaluar_grilla(chain)
    df_grid = res_gex["table"]

    strikes = df_grid["strike"].to_numpy(dtype=float)
    oi_calls = df_grid["oi_call"].to_numpy(dtype=float)
    oi_puts = df_grid["oi_put"].to_numpy(dtype=float)
    base_ivs = df_grid["iv"].to_numpy(dtype=float)

    # Delta inicial del libro de opciones de Dealers en F_0, IV_0, T_0
    delta_0 = _dealer_book_delta(spot, strikes, oi_calls, oi_puts, base_ivs, dte_gex, r, iv_shift=0.0)

    # Choques de puntos solicitados: -100, -50, -25, +25, +50, +100
    shocks_pts = [-100.0, -50.0, -25.0, 25.0, 50.0, 100.0]
    # Sensibilidad empírica VXN vs NQ: caída de 100 pts (~-0.34%) eleva IV en ~+0.45 vol pts
    beta_iv_per_100pts = -0.0045
    dt_session_days = 0.50  # media jornada / sesión RTH hacia el cierre

    rows_sim = []
    for dF in shocks_pts:
        F_new = spot + dF
        d_iv = (dF / 100.0) * beta_iv_per_100pts

        # 1. Solo movimiento de precio (Flujo Gamma puro)
        delta_gamma = _dealer_book_delta(F_new, strikes, oi_calls, oi_puts, base_ivs, dte_gex, r, iv_shift=0.0)
        flow_gamma_nq = -(delta_gamma - delta_0)

        # 2. Movimiento de precio + reacción de IV (Gamma + Vanna)
        delta_gv = _dealer_book_delta(F_new, strikes, oi_calls, oi_puts, base_ivs, dte_gex, r, iv_shift=d_iv)
        flow_vanna_nq = -(delta_gv - delta_gamma)

        # 3. Efecto adicional por decaimiento temporal intradía (Charm)
        delta_gvc = _dealer_book_delta(F_new, strikes, oi_calls, oi_puts, base_ivs, dte_gex - dt_session_days, r, iv_shift=d_iv)
        flow_charm_nq = -(delta_gvc - delta_gv)

        flow_total_nq = flow_gamma_nq + flow_vanna_nq + flow_charm_nq
        flow_total_mnq = flow_total_nq * 10.0
        notional_m = (flow_total_nq * F_new * NQ.point_value) / 1e6

        if flow_total_nq > 0 and dF < 0:
            efecto = "AMORTIGUADOR (Dealers COMPRAN la caída -> Soporte / Rebote)"
        elif flow_total_nq < 0 and dF > 0:
            efecto = "AMORTIGUADOR (Dealers VENDEN la subida -> Freno / Pinning)"
        elif flow_total_nq < 0 and dF < 0:
            efecto = "ACELERADOR BAJISTA (Dealers VENDEN en caída -> Cascada)"
        else:
            efecto = "ACELERADOR ALCISTA (Dealers COMPRAN en subida -> Squeeze)"

        rows_sim.append({
            "shock_pts": dF,
            "target_price": F_new,
            "iv_shift_pct": d_iv * 100.0,
            "flow_gamma_nq": flow_gamma_nq,
            "flow_vanna_nq": flow_vanna_nq,
            "flow_charm_nq": flow_charm_nq,
            "flow_total_nq": flow_total_nq,
            "flow_total_mnq": flow_total_mnq,
            "notional_m": notional_m,
            "effect": efecto,
        })

    # Choques puros de Volatilidad (Vanna Shock ±1% y ±2% IV) y Tiempo (Charm 1 Día)
    delta_iv_up1 = _dealer_book_delta(spot, strikes, oi_calls, oi_puts, base_ivs, dte_gex, r, iv_shift=+0.01)
    delta_iv_dn1 = _dealer_book_delta(spot, strikes, oi_calls, oi_puts, base_ivs, dte_gex, r, iv_shift=-0.01)
    delta_charm_1d = _dealer_book_delta(spot, strikes, oi_calls, oi_puts, base_ivs, dte_gex - 1.0, r, iv_shift=0.0)

    vanna_shock_up1_nq = -(delta_iv_up1 - delta_0)
    vanna_shock_dn1_nq = -(delta_iv_dn1 - delta_0)
    charm_1d_nq = -(delta_charm_1d - delta_0)

    print("\n" + banner(
        f"DYNAMIC HEDGING SIMULATOR: FLUJO DE COBERTURA DE DEALERS (Δ-Γ-VANNA-CHARM) | NQ: {spot:,.2f}",
        f"Zero-Gamma Flip: {res_gex['zero_gamma']:,.1f} | Put Wall: {res_gex['put_wall']:,.0f} | Call Wall: {res_gex['call_wall']:,.0f}"
    ))
    print(kv_block([
        ("Régimen Actual", res_gex["dealer_regime"]),
        ("Choque Vanna (-1% VXN)", f"Si VXN cae -1.0 pt -> Dealers deben ejecutar {vanna_shock_dn1_nq:+.0f} NQ ({vanna_shock_dn1_nq*10:+.0f} MNQ) [Vanna Rally]"),
        ("Choque Vanna (+1% VXN)", f"Si VXN sube +1.0 pt -> Dealers deben ejecutar {vanna_shock_up1_nq:+.0f} NQ ({vanna_shock_up1_nq*10:+.0f} MNQ)"),
        ("Flujo Charm (1 Día)", f"Por decaimiento de 1 día (sin mover precio) -> Dealers ejecutan {charm_1d_nq:+.0f} NQ ({charm_1d_nq*10:+.0f} MNQ)"),
    ]))

    t = Table(
        ["Movimiento NQ", "Nivel NQ", "ΔVXN Est.", "Flujo Gamma (NQ)", "Flujo Vanna (NQ)", "Flujo Charm (NQ)", "TOTAL Orden (NQ)", "Equiv. (MNQ)", "Nocional ($M)", "Impacto en Microestructura"],
        aligns="rrrrrrrrrl",
        title="SIMULACION DE ORDENES DE COBERTURA DE MARKET MAKERS POR MOVIMIENTO DE ±25, ±50 Y ±100 PUNTOS"
    )
    for r_row in rows_sim:
        side = "BUY " if r_row["flow_total_nq"] >= 0 else "SELL"
        t.add_row([
            f"{r_row['shock_pts']:+.0f} pts",
            fmt_num(r_row["target_price"], 2),
            f"{r_row['iv_shift_pct']:+.2f}%",
            f"{r_row['flow_gamma_nq']:+.0f} NQ",
            f"{r_row['flow_vanna_nq']:+.0f} NQ",
            f"{r_row['flow_charm_nq']:+.0f} NQ",
            f"{side} {abs(r_row['flow_total_nq']):,.0f} NQ",
            f"{r_row['flow_total_mnq']:+,.0f} MNQ",
            f"{fmt_usd(r_row['notional_m'], 1, sign=True)}M",
            r_row["effect"],
        ])
    print("\n" + t.render() + "\n")

    # Gráfico institucional: barras apiladas Gamma + Vanna + Charm por choque de puntos
    import matplotlib.pyplot as plt
    labels = [f"{r['shock_pts']:+.0f}p\n({r['target_price']:,.0f})" for r in rows_sim]
    g_vals = np.array([r["flow_gamma_nq"] for r in rows_sim])
    v_vals = np.array([r["flow_vanna_nq"] for r in rows_sim])
    c_vals = np.array([r["flow_charm_nq"] for r in rows_sim])
    tot_vals = np.array([r["flow_total_nq"] for r in rows_sim])

    x = np.arange(len(rows_sim))
    w = 0.25
    fig, ax = plt.subplots(figsize=(12.0, 5.2))
    ax.bar(x - w, g_vals, width=w, color=THEME["blue"], label="Flujo Gamma (∂Δ/∂F)")
    ax.bar(x, v_vals, width=w, color=THEME["amber"], label="Flujo Vanna (∂Δ/∂σ)")
    ax.bar(x + w, c_vals, width=w, color=THEME["violet"], label="Flujo Charm (∂Δ/∂t)")
    ax.plot(x, tot_vals, color=THEME["green"], lw=2.4, marker="o", label="Flujo Neto Total (Contratos NQ)")
    ax.axhline(0, color=THEME["text"], lw=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title("Simulador de Cobertura Dinámica de Dealers | Órdenes en Futuros NQ por Choque (±25, ±50, ±100 pts)")
    ax.set_xlabel("Choque de Precio en E-mini Nasdaq (Puntos)")
    ax.set_ylabel("Contratos NQ a Comprar (+) / Vender (-)")
    ax.legend(loc="best")
    finalize(fig, "simulador_cobertura_dealers_nq", show=show_plot)

    return {
        "spot": spot,
        "rows": rows_sim,
        "vanna_dn1_nq": vanna_shock_dn1_nq,
        "vanna_up1_nq": vanna_shock_up1_nq,
        "charm_1d_nq": charm_1d_nq,
    }


if __name__ == "__main__":
    simular_flujo_cobertura_dealers()
