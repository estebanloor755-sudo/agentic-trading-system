# %% [ORQUESTADOR MAESTRO: TERMINAL DE ANALISIS CUANTITATIVO LOCAL NQ=F / MNQ=F]
"""
Orquestador Maestro de la Terminal Cuantitativa Institucional para E-mini Nasdaq
(`NQ=F`, $20/pt) y Micro E-mini Nasdaq (`MNQ=F`, $2/pt) — 100% Matemática Pura de
Mercado (Puntos Netos, Conos de Percentiles, Muros GEX, Árbol Binomial CRR, Griegas
Black-76 y Confluencias Institucionales).

Modos de ejecución por consola:
  * Dashboard Ejecutivo Consolidado (por defecto):
        python main_terminal_nq.py
  * Suite Completa (Dashboard + todos los módulos especializados):
        python main_terminal_nq.py --all
  * Ejecutar un módulo específico (1..11):
        python main_terminal_nq.py --module 3
  * Menú interactivo en consola:
        python main_terminal_nq.py --menu
  * Modo Auto-Refresh continuo durante la sesión de Nueva York (ej. cada 60s):
        python main_terminal_nq.py --auto-refresh 60
  * Opciones adicionales:
        --no-plots   (guarda todos los gráficos en outputs/charts/ sin abrir ventanas)
        --offline    (usa caché local / generador sintético sin llamadas de red)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import MNQ, NQ, THEME
from core import sessions
from core.tables import Table, banner, fmt_num, kv_block, section


def ejecutar_dashboard_ejecutivo(
    feed=None,
    show_plot: bool = True,
) -> dict:
    """
    Calcula y despliega en consola el Dashboard Ejecutivo Consolidado unificando
    todos los motores matemáticos puros de la terminal en una sola vista institucional.
    """
    from Data.data_feed_nq import DataFeedNQ
    from Data import _2_ml_bridge as ml_mod
    from analysis.cazador_alfa_beta_factores import analizar_tractor
    from analysis.liquidez_market_maker_vpin import calcular_microestructura_liquidez
    from analysis.radar_gex_crr_griegos import MotorUnificadoGexCrrGreeks
    from analysis.simulador_cobertura_dealers import _dealer_book_delta
    from analysis.stat_arb_cointegracion import analizar_par_cointegrado
    from core.plotting import finalize
    from models.black_scholes_nq import implied_ranges_nq
    from models.desbalance_estadistico import (
        calcular_hurst,
        compute_vwap_ofi_metrics,
        dictaminar_regimen_hurst,
        lo_mackinlay_vr,
    )
    from models.Garch import fit_nq_garch, simulate_returns
    from simulations.monte_carlo_var import calcular_distribucion_cola_nq

    t0 = time.time()
    feed = feed or DataFeedNQ()

    # 1. Ingesta multi-timeframe y cross-asset
    bars_15m = feed.bars("NQ", "15m")
    bars_5m = feed.bars("NQ", "5m")
    spot = float(bars_15m["Close"].iloc[-1])
    last_ts = bars_15m.index[-1]
    r_rf, r_src = feed.risk_free_rate()
    iv_atm, iv_src = feed.implied_vol()

    # 2. Motor GJR-GARCH(1,1)-t + AR(p) en 15m (Macro) y 5m (Disparo)
    fit15 = fit_nq_garch(bars_15m, ar_max=2, deseason=True)
    fit5 = fit_nq_garch(bars_5m, ar_max=2, deseason=True)
    reg15 = fit15.vol_regime()
    reg5 = fit5.vol_regime()

    # 3. Proyección Monte Carlo + GJR-GARCH (BACKEND INTACTO: 9 percentiles completos en memoria)
    fut_dates = sessions.next_bars(last_ts, n=32, freq="15min")
    ret_mc = simulate_returns(fit15, fut_dates, n_sims=10_000, seed=42, shocks="fhs")
    sim_paths = spot * np.exp(np.cumsum(ret_mc, axis=0))
    # Índices en q_mat: 0=P05, 1=P10, 2=P16, 3=P25, 4=P50, 5=P75, 6=P84, 7=P90, 8=P95
    q_levels = [0.05, 0.10, 0.16, 0.25, 0.50, 0.75, 0.84, 0.90, 0.95]
    q_mat = np.quantile(sim_paths, q_levels, axis=1)

    # 4. Distribución de Cola y Rangos Implícitos en Puntos Puros NQ
    tail_dist = calcular_distribucion_cola_nq(fit15, spot, n_sims=15_000, seed=42)
    imp_ranges = implied_ranges_nq(spot, iv_atm)

    # 5. Motor Unificado GEX + Árbol Binomial CRR + Griegas 1er y 2do Orden
    chain = feed.option_chain_nq(spot, atm_iv=iv_atm)
    gex_engine = MotorUnificadoGexCrrGreeks(F=spot, r=r_rf, iv_atm=iv_atm, dte_gex=5.0, dte_crr=30.0)
    gex_res = gex_engine.evaluar_grilla(chain)
    df_gex = gex_res["table"]
    call_wall = gex_res["call_wall"]
    put_wall = gex_res["put_wall"]
    zero_gamma = gex_res["zero_gamma"]

    # Flujo de cobertura de Dealers para ±25, ±50, ±100 pts
    st_arr = df_gex["strike"].to_numpy(dtype=float)
    oic_arr = df_gex["oi_call"].to_numpy(dtype=float)
    oip_arr = df_gex["oi_put"].to_numpy(dtype=float)
    iv_arr = df_gex["iv"].to_numpy(dtype=float)
    d0 = _dealer_book_delta(spot, st_arr, oic_arr, oip_arr, iv_arr, 5.0, r_rf, 0.0)
    dealer_flows = {}
    for dF in (-100.0, -50.0, -25.0, 25.0, 50.0, 100.0):
        d_iv = (dF / 100.0) * (-0.0045)
        d_new = _dealer_book_delta(spot + dF, st_arr, oic_arr, oip_arr, iv_arr, 4.5, r_rf, d_iv)
        dealer_flows[int(dF)] = -(d_new - d0)

    # 6. VWAP Z-Score, OFI/CVD, Hurst & Lo-MacKinlay (15m y 5m) + Liquidez VPIN
    df15_vwap = compute_vwap_ofi_metrics(bars_15m, window=20)
    df5_vwap = compute_vwap_ofi_metrics(bars_5m, window=24)
    df5_liq = calcular_microestructura_liquidez(bars_5m, window=24)

    h15 = calcular_hurst(bars_15m["Close"].to_numpy()[-500:])
    h5 = calcular_hurst(bars_5m["Close"].to_numpy()[-600:])
    vr15 = lo_mackinlay_vr(bars_15m["Close"].to_numpy()[-500:], q=4)
    vr5 = lo_mackinlay_vr(bars_5m["Close"].to_numpy()[-600:], q=6)
    reg_mem_15 = dictaminar_regimen_hurst(h15, vr15)
    reg_mem_5 = dictaminar_regimen_hurst(h5, vr5)

    vwap_now = float(df15_vwap["VWAP"].iloc[-1])
    z_vwap_15 = float(df15_vwap["Z_VWAP"].iloc[-1])
    z_vwap_5 = float(df5_vwap["Z_VWAP"].iloc[-1])
    ofi_z_5 = float(df5_vwap["OFI_Z"].iloc[-1])
    vpin_5 = float(df5_liq["VPIN"].iloc[-1])
    kyle_5 = float(df5_liq["Kyle_Lambda"].iloc[-1])
    roll_5 = float(df5_liq["Roll_Pts"].iloc[-1])
    micro_ev = str(df5_liq["Micro_Event"].iloc[-1])

    # 7. StatArb Cointegración (NQ/ES 15m & 5m, NQ/SMH) + Basis Carry + ML
    cl_globex_15 = feed.closes(["NQ", "ES"], interval="15m", rth_only=False)
    cl_globex_5 = feed.closes(["NQ", "ES"], interval="5m", rth_only=False)
    cl_rth_15 = feed.closes(["NQ", "SMH", "QQQ", "SPY", "NDX"], interval="15m", rth_only=True)

    sa_es15 = analizar_par_cointegrado(cl_globex_15, "NQ", "ES", "NQ/ES 15m", z_window=40)
    sa_es5 = analizar_par_cointegrado(cl_globex_5, "NQ", "ES", "NQ/ES 5m", z_window=48)
    sa_smh15 = analizar_par_cointegrado(cl_rth_15, "NQ", "SMH", "NQ/SMH 15m", z_window=32)

    ret_g15 = np.log(cl_globex_15 / cl_globex_15.shift(1)).dropna() * 100.0
    ret_r15 = np.log(cl_rth_15 / cl_rth_15.shift(1)).dropna() * 100.0
    fac_es = analizar_tractor(ret_g15["NQ"].to_numpy(), ret_g15["ES"].to_numpy(), window=32)
    fac_smh = analizar_tractor(ret_r15["NQ"].to_numpy(), ret_r15["SMH"].to_numpy(), window=26)

    # Basis Fair Value
    contract_code, expiry_date = sessions.nq_front_contract(last_ts)
    T_exp = sessions.year_fraction_to(expiry_date, last_ts)
    spot_ndx = float(cl_rth_15["NDX"].iloc[-1])
    f_nq_rth = float(cl_rth_15["NQ"].iloc[-1])
    f_theo = spot_ndx * np.exp((r_rf - 0.0070) * T_exp)
    basis_mis_pts = f_nq_rth - f_theo

    ml_info = ml_mod.estimar_probabilidad_regimen_nq(bars_15m)

    # 8. Score Compuesto Direccional (-100 a +100)
    score_dir = 0.0
    score_dir += 25.0 if spot >= zero_gamma else -25.0
    score_dir += float(np.clip(-sa_es15["z_now"] * 12.0, -25.0, 25.0))
    score_dir += float(np.clip((ml_info["prob_up_1h"] - 0.50) * 150.0, -25.0, 25.0))
    score_dir += float(np.clip(ofi_z_5 * 10.0, -25.0, 25.0))

    if score_dir >= 18.0:
        sesgo_global = f"ALCISTA INSTITUCIONAL (Score: {score_dir:+.1f}/100) -> Priorizar COMPRAS (LONG) en retrocesos"
    elif score_dir <= -18.0:
        sesgo_global = f"BAJISTA INSTITUCIONAL (Score: {score_dir:+.1f}/100) -> Priorizar VENTAS (SHORT) en rebotes"
    else:
        sesgo_global = f"NEUTRAL / ROTACIONAL EN RANGO (Score: {score_dir:+.1f}/100) -> Operar extremos hacia VWAP"

    elapsed = time.time() - t0

    print("\n" + banner(
        f"TERMINAL CUANTITATIVA INSTITUCIONAL NQ=F ($20/pt) & MNQ=F ($2/pt) | SPOT: {spot:,.2f} pts",
        f"Estado NY: {sessions.session_status()} | Última Barra: {last_ts:%a %d-%b %H:%M %Z} | "
        f"Fuente: {bars_15m.attrs.get('source')} | Cómputo: {elapsed:.2f}s",
        width=116,
    ))

    # Bloque 1: Síntesis Ejecutiva y Sesgo del Día
    print(section("1. SINTESIS EJECUTIVA, SESGO DEL DIA Y REGIMEN MULTI-TIMEFRAME (15M MACRO / 5M DISPARO)", width=116))
    print(kv_block([
        ("SESGO DEL DIA", sesgo_global),
        ("Régimen GARCH 15m", f"{reg15['label']} (Percentil {reg15['percentile']:.1f}%) | σ_15m = {reg15['sigma_now_pts']:.2f} pts | Vol Anual = {fit15.ann_vol_now()*100:.2f}% | VXN = {iv_atm*100:.2f}%"),
        ("Régimen GARCH 5m", f"{reg5['label']} (Percentil {reg5['percentile']:.1f}%) | σ_5m  = {reg5['sigma_now_pts']:.2f} pts | Persistencia GJR = {fit15.persistence:.4f}"),
        ("Memoria & Hurst 15m", reg_mem_15),
        ("Memoria & Hurst 5m", reg_mem_5),
        ("VWAP & Flujo 5m", f"VWAP Sesión = {vwap_now:,.2f} (Spot-VWAP: {spot-vwap_now:+.1f}p) | Z-15m={z_vwap_15:+.2f} | Z-5m={z_vwap_5:+.2f} | OFI-Z={ofi_z_5:+.2f}"),
        ("Microestructura 5m", f"VPIN={vpin_5:.1f}% | Kyle λ={kyle_5:.2f} pts/1k NQ | Roll Spread={roll_5:.2f} pts -> {micro_ev}"),
    ]))

    # Bloque 2: Muros GEX + CRR + Flujo de Cobertura de Dealers
    print("\n" + section("2. MUROS DE LIQUIDEZ GEX + ARBOL BINOMIAL CRR + COBERTURA DINAMICA DE DEALERS", width=116))
    t_levels = Table(
        ["Nivel Institucional", "Precio NQ", "Distancia", "Mecánica de Market Makers (Δ-Γ-Vanna-Charm)", "Acción Táctica: REBOTE (GARCH<P90) vs RUPTURA (GARCH P90+)"],
        aligns="lrrll",
    )
    t_levels.add_row([
        "CALL WALL (Techo)",
        f"{call_wall:,.0f}",
        f"{call_wall - spot:+.1f} pts",
        "Máxima Gamma Positiva; Dealers venden futuros",
        "RUPTURA P90+: Gamma Squeeze (LONG) | REBOTE: Vender / TP Largos",
    ])
    t_levels.add_row([
        "ZERO-GAMMA FLIP",
        f"{zero_gamma:,.1f}",
        f"{zero_gamma - spot:+.1f} pts",
        "Frontera de Régimen: Arriba=Pinning, Abajo=Momentum",
        f"Spot {'ARRIBA' if spot >= zero_gamma else 'DEBAJO'} del Flip -> {'Operar Reversión al VWAP' if spot >= zero_gamma else 'Operar Rupturas a favor del flujo'}",
    ])
    t_levels.add_row([
        "PUT WALL (Piso)",
        f"{put_wall:,.0f}",
        f"{put_wall - spot:+.1f} pts",
        "Máxima Gamma Negativa / Recompra de Shorts MM",
        "RUPTURA P90+: Cascada Bajista (SHORT) | REBOTE: Comprar (LONG)",
    ])
    t_levels.add_row([
        "Flujo Dealers ±Pts",
        f"Spot {spot:,.0f}",
        "±25/50/100p",
        f"-100p:{dealer_flows[-100]:+.0f}NQ | -50p:{dealer_flows[-50]:+.0f}NQ | -25p:{dealer_flows[-25]:+.0f}NQ",
        f"+25p:{dealer_flows[25]:+.0f}NQ | +50p:{dealer_flows[50]:+.0f}NQ | +100p:{dealer_flows[100]:+.0f}NQ",
    ])
    print(t_levels.render())

    # Bloque 3: Cono Monte Carlo + GJR-GARCH (Solo Bordes Extremos P05, P10, P50, P90, P95)
    print("\n" + section("3. CONO ESTOCASTICO AR(p) + GJR-GARCH + MONTE CARLO — SOLO BORDES EXTREMOS (P05/P10/P50/P90/P95)", width=116))
    t_cone = Table(
        ["Horizonte (Bloque)", "Hora NY", "Suelo Extremo P05 (95%)", "Suelo P10 (90%)", "Baseline P50 (Mediana)", "Techo P90 (90%)", "Techo Extremo P95 (95%)"],
        aligns="llrrrrr",
    )
    for label, idx_b in [
        ("30 Min (B#02)", 1),
        ("1 Hora (B#04 - Intradía)", 3),
        ("2 Horas (B#08 - Apertura)", 7),
        ("4 Horas (B#16 - Media Ses.)", 15),
        ("8 Horas (B#32 - Jornada)", 31),
    ]:
        t_cone.add_row([
            label,
            fut_dates[idx_b].strftime("%a %H:%M"),
            f"{q_mat[0, idx_b]:,.1f} ({q_mat[0, idx_b]-spot:+.0f}p)",
            f"{q_mat[1, idx_b]:,.1f} ({q_mat[1, idx_b]-spot:+.0f}p)",
            f"{q_mat[4, idx_b]:,.1f}",
            f"{q_mat[7, idx_b]:,.1f} ({q_mat[7, idx_b]-spot:+.0f}p)",
            f"{q_mat[8, idx_b]:,.1f} ({q_mat[8, idx_b]-spot:+.0f}p)",
        ])
    print(t_cone.render())

    # Bloque 4: Radar de Anomalías Cross-Asset (StatArb, Basis/Carry y Factores)
    print("\n" + section("4. RADAR DE ANOMALIAS: STATARB COINTEGRACION, BASIS/CARRY Y FACTORES ALPHA/BETA", width=116))
    t_anom = Table(
        ["Motor / Par Institucional", "Métrica Clave", "Z-Score", "Ajuste Fair Value NQ", "Señal / Diagnóstico de Arbitraje"],
        aligns="llrrl",
    )
    t_anom.add_row([
        "StatArb NQ vs ES (15m Macro)",
        f"β={sa_es15['beta']:.3f} | HL={sa_es15['half_life_bars']:.1f}b",
        f"{sa_es15['z_now']:+.2f} SD",
        f"{sa_es15['target_rev_pts']:+.1f} pts",
        sa_es15["signal"],
    ])
    t_anom.add_row([
        "StatArb NQ vs ES (5m Disparo)",
        f"β={sa_es5['beta']:.3f} | HL={sa_es5['half_life_bars']:.1f}b",
        f"{sa_es5['z_now']:+.2f} SD",
        f"{sa_es5['target_rev_pts']:+.1f} pts",
        sa_es5["signal"],
    ])
    t_anom.add_row([
        "StatArb NQ vs SMH Semis (15m)",
        f"β={sa_smh15['beta']:.3f} | HL={sa_smh15['half_life_bars']:.1f}b",
        f"{sa_smh15['z_now']:+.2f} SD",
        f"{sa_smh15['target_rev_pts']:+.1f} pts",
        sa_smh15["signal"],
    ])
    t_anom.add_row([
        f"Basis Carry ({contract_code} vs ^NDX)",
        f"r={r_rf*100:.2f}% | F_theo={f_theo:,.1f}",
        f"{basis_mis_pts / max(spot*0.001, 1.0):+.2f} SD",
        f"{-basis_mis_pts:+.1f} pts",
        "Prima sobre Fair Value" if basis_mis_pts > 0 else "Descuento bajo Fair Value",
    ])
    t_anom.add_row([
        "Factor Alpha/Beta vs SMH & ES",
        f"β_ES={fac_es['beta_roll']:.2f} | β_SMH={fac_smh['beta_roll']:.2f}",
        f"{fac_smh['resid_z']:+.2f} SD",
        f"α_ES={fac_es['alpha_bps']:+.1f} bps",
        fac_smh["signal"],
    ])
    print(t_anom.render())

    # Bloque 5: Distribución de Cola Extrema VaR / CVaR en Puntos Puros NQ
    print("\n" + section("5. COLAS DE LIQUIDACION VaR 95% / VaR 99% / CVaR 99% EN PUNTOS PUROS NQ", width=116))
    t_tail = Table(
        ["Horizonte", "Hora NY", "Suelo Extremo P05", "Techo Extremo P95", "VaR 95% (Pts)", "VaR 99% (Pts)", "CVaR 99% (Liquidación)"],
        aligns="llrrrrr",
    )
    for h_name, info in tail_dist["horizons"].items():
        t_tail.add_row([
            h_name,
            info["ny_time"],
            f"{info['P05']:,.1f} pts",
            f"{info['P95']:,.1f} pts",
            f"-{info['var95_pts']:.1f} pts",
            f"-{info['var99_pts']:.1f} pts",
            f"-{info['cvar99_pts']:.1f} pts",
        ])
    print(t_tail.render() + "\n")

    import matplotlib.pyplot as plt
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15.5, 9.2))

    # Panel 1: Cono Monte Carlo + GJR-GARCH (32 bloques 15m — Solo Extremos P05/P10/P50/P90/P95) + Muros GEX
    x_mc = np.arange(1, 33)
    ax1.fill_between(x_mc, q_mat[0], q_mat[8], color=THEME["violet"], alpha=0.20, label="Cono Extremo 90% (P05 - P95)")
    ax1.fill_between(x_mc, q_mat[1], q_mat[7], color=THEME["indigo"], alpha=0.35, label="Cono Institucional 80% (P10 - P90)")
    ax1.plot(x_mc, q_mat[4], color=THEME["red"], lw=2.3, label="Baseline P50 (Mediana)")
    ax1.axhline(spot, color=THEME["yellow"], ls="--", lw=1.4, label=f"Spot ({spot:,.0f})")
    ax1.axhline(call_wall, color=THEME["red"], ls=":", lw=1.4, label=f"Call Wall ({call_wall:,.0f})")
    ax1.axhline(put_wall, color=THEME["green"], ls=":", lw=1.4, label=f"Put Wall ({put_wall:,.0f})")
    ax1.set_title("1. Proyección 32x15m (8h NY): Bordes Extremos P05/P10/P50/P90/P95 & Muros GEX")
    ax1.set_xlabel("Bloques Futuros de 15m")
    ax1.set_ylabel("Precio NQ")
    ax1.legend(loc="upper left")

    # Panel 2: Perfil Net GEX + Curva de Urgencia CRR
    st_g = df_gex["strike"].to_numpy()
    ng_g = df_gex["net_gex_m"].to_numpy()
    cols_g = [THEME["green"] if v >= 0 else THEME["red"] for v in ng_g]
    ax2.bar(st_g, ng_g, width=62, color=cols_g, alpha=0.82, label="Net GEX ($M)")
    ax2.axvline(spot, color=THEME["yellow"], ls="--", lw=1.8, label="Spot NQ")
    ax2.axvline(zero_gamma, color=THEME["blue"], ls="-.", lw=1.5, label=f"Zero-Gamma ({zero_gamma:,.0f})")
    ax2.set_title("2. Perfil Gamma Exposure (GEX) de Market Makers")
    ax2.set_xlabel("Strike NQ")
    ax2.set_ylabel("Net GEX ($M)")
    ax2.legend(loc="upper left")

    # Panel 3: Microestructura 5m (Z-VWAP, StatArb Z-Score y VPIN)
    n_p = 90
    z_vw_t = df5_vwap["Z_VWAP"].to_numpy()[-n_p:]
    z_sa_t = sa_es5["z_series"][-n_p:]
    ax3.plot(np.arange(len(z_vw_t)), z_vw_t, color=THEME["blue"], lw=1.8, label="Z-Score vs VWAP (5m)")
    ax3.plot(np.arange(len(z_sa_t)), z_sa_t, color=THEME["green"], lw=1.8, label="Z-Score StatArb NQ/ES (5m)")
    ax3.axhline(2.0, color=THEME["red"], ls="--", lw=1.2)
    ax3.axhline(-2.0, color=THEME["green"], ls="--", lw=1.2)
    ax3.axhline(0.0, color=THEME["muted"], lw=0.8)
    ax3.set_title(f"3. Microestructura 5m: Z-VWAP & StatArb | VPIN={vpin_5:.1f}% | H_5m={h5:.2f}")
    ax3.set_xlabel("Barras de 5m Recientes")
    ax3.set_ylabel("Z-Score (SD)")
    ax3.legend(loc="upper left")

    # Panel 4: Distribución de Cola en Puntos Puros NQ (Horizonte 8h)
    d_pts_8h = sim_paths[-1, :] - spot
    h8_info = tail_dist["horizons"]["8h (B#32 - Sesión Completa)"]
    ax4.hist(d_pts_8h, bins=65, color=THEME["blue"], alpha=0.65, edgecolor=THEME["bg"], density=True)
    ax4.axvline(-h8_info["var95_pts"], color=THEME["amber"], ls="--", lw=1.6, label=f"VaR 95%: -{h8_info['var95_pts']:.0f}p")
    ax4.axvline(-h8_info["var99_pts"], color=THEME["red"], ls="-", lw=1.8, label=f"VaR 99%: -{h8_info['var99_pts']:.0f}p")
    ax4.axvline(-h8_info["cvar99_pts"], color=THEME["pink"], ls=":", lw=1.8, label=f"CVaR 99%: -{h8_info['cvar99_pts']:.0f}p")
    ax4.set_title("4. Distribución de Cola Monte Carlo + GJR-GARCH (Puntos Puros NQ a 8h)")
    ax4.set_xlabel("Variación Proyectada en Puntos NQ")
    ax4.set_ylabel("Densidad")
    ax4.legend(loc="upper left")

    finalize(fig, "dashboard_ejecutivo_nq", show=show_plot)

    return {
        "spot": spot,
        "score_dir": score_dir,
        "sesgo": sesgo_global,
        "garch_15m": reg15,
        "garch_5m": reg5,
        "gex": gex_res,
        "tail_dist": tail_dist,
        "stat_arb_es15": sa_es15,
        "stat_arb_es5": sa_es5,
    }


def _get_modules():
    from Data._2_ml_bridge import ejecutar_suite_robustez
    from analysis.basis_carry_tracker import ejecutar_basis_carry_tracker
    from analysis.cazador_alfa_beta_factores import ejecutar_cazador_factores
    from analysis.liquidez_market_maker_vpin import ejecutar_liquidez_vpin
    from analysis.radar_gex_crr_griegos import ejecutar_radar_gex_crr
    from analysis.simulador_cobertura_dealers import simular_flujo_cobertura_dealers
    from analysis.stat_arb_cointegracion import ejecutar_stat_arb_cointegracion
    from models.arbol_binomial_crr import ejecutar_crr_interactivo
    from models.black_scholes_nq import ejecutar_black_scholes_interactivo
    from models.desbalance_estadistico import escanear_desbalance_estadistico_nq
    from models.Garch import ejecutar_garch_15m
    from simulations.monte_carlo_var import ejecutar_monte_carlo_visual_nq
    from simulations.montecarlo_garch_15m_nq import ejecutar_suite_ny
    from simulations.superficie_volatilidad import ejecutar_superficie_volatilidad_visual

    return [
        (1, "Dashboard Ejecutivo Consolidado (Vista Maestra)", ejecutar_dashboard_ejecutivo),
        (2, "Motor GJR-GARCH(1,1)-t + AR(p) (15m Macro & 5m Disparo)", ejecutar_garch_15m),
        (3, "Proyección Fusionada AR+GARCH+Monte Carlo (32 Bloques 15m NY)", ejecutar_suite_ny),
        (4, "Radar Unificado GEX + Árbol Binomial CRR + Griegas 1er/2do Orden", ejecutar_radar_gex_crr),
        (5, "Distribución Monte Carlo de Cola (Percentiles P01-P99 & VaR/CVaR en Puntos NQ)", ejecutar_monte_carlo_visual_nq),
        (6, "Cazador de Anomalías y Factores (Alpha, Beta, Gamma, ARMA, Hurst & VR)", ejecutar_cazador_factores),
        (7, "Yield Anomaly & Carry / Basis Trade Tracker (NQ=F vs ^NDX & ^IRX/^TNX)", ejecutar_basis_carry_tracker),
        (8, "Dynamic Hedging Simulator (Flujo Dealers Δ-Γ-Vanna-Charm ±25/50/100p)", simular_flujo_cobertura_dealers),
        (9, "Statistical Arbitrage (StatArb) & Cointegración Intradía (NQ/ES/SMH)", ejecutar_stat_arb_cointegracion),
        (10, "Liquidity Provision, Roll Spread, Kyle's Lambda (λ) & Toxicidad VPIN", ejecutar_liquidez_vpin),
        (11, "Escáner Multi-TF VWAP Z-Score, OFI/CVD, Hurst + Valuación BS/CRR/SVI/ML", lambda feed=None, show_plot=True: (
            escanear_desbalance_estadistico_nq(feed=feed, show_plot=show_plot),
            ejecutar_black_scholes_interactivo(feed=feed, show_plot=show_plot),
            ejecutar_crr_interactivo(feed=feed, show_plot=show_plot),
            ejecutar_superficie_volatilidad_visual(feed=feed, show_plot=show_plot),
            ejecutar_suite_robustez(feed=feed, show_plot=show_plot),
        )),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Terminal Cuantitativa Institucional NQ=F / MNQ=F (Matemática Pura)")
    parser.add_argument("--all", action="store_true", help="Ejecuta el Dashboard Ejecutivo y todos los módulos")
    parser.add_argument("--dashboard", action="store_true", help="Ejecuta únicamente el Dashboard Ejecutivo Consolidado")
    parser.add_argument("--module", type=int, default=None, help="Ejecuta el módulo indicado (1..11)")
    parser.add_argument("--menu", action="store_true", help="Abre el menú interactivo en consola")
    parser.add_argument("--auto-refresh", type=int, default=0, metavar="SEG", help="Refresca el Dashboard cada SEG segundos")
    parser.add_argument("--offline", action="store_true", help="Usa caché local / generador sintético sin red")
    parser.add_argument("--no-plots", action="store_true", help="No abre ventanas emergentes (guarda PNGs en outputs/charts/)")
    args = parser.parse_args(argv)

    from Data.data_feed_nq import DataFeedNQ
    show_plot = not args.no_plots
    modules = _get_modules()

    if args.auto_refresh > 0:
        interval_s = max(args.auto_refresh, 10)
        try:
            while True:
                feed = DataFeedNQ(offline=args.offline)
                ejecutar_dashboard_ejecutivo(feed=feed, show_plot=False)
                print(f" [Auto-Refresh Activo] Próxima actualización en {interval_s}s (Ctrl+C para detener)...")
                time.sleep(interval_s)
        except KeyboardInterrupt:
            print("\n [Auto-Refresh finalizado por el usuario.]")
            return

    feed = DataFeedNQ(offline=args.offline)

    if args.all:
        for _, _, mfn in modules:
            mfn(feed=feed, show_plot=show_plot)
        return

    if args.module is not None:
        for mid, _, mfn in modules:
            if mid == args.module:
                mfn(feed=feed, show_plot=show_plot)
                return
        print(f" [!] Módulo {args.module} no válido. Elija entre 1 y {len(modules)}.")
        return

    if args.menu:
        t_m = Table(["ID", "Módulo Cuantitativo Institucional"], aligns="rl", title="MENU INTERACTIVO - TERMINAL NQ / MNQ")
        for mid, mname, _ in modules:
            t_m.add_row([mid, mname])
        t_m.add_row([0, "Ejecutar SUITE COMPLETA (Todos los módulos)"])
        print("\n" + t_m.render())
        try:
            choice = int(input("\n Seleccione opción (0..11, Enter=1): ").strip() or "1")
        except (EOFError, ValueError):
            choice = 1
        if choice == 0:
            for _, _, mfn in modules:
                mfn(feed=feed, show_plot=show_plot)
        else:
            for mid, _, mfn in modules:
                if mid == choice:
                    mfn(feed=feed, show_plot=show_plot)
                    break
        return

    ejecutar_dashboard_ejecutivo(feed=feed, show_plot=show_plot)


if __name__ == "__main__":
    main()
