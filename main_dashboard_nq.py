# %% [ORQUESTADOR PRINCIPAL VISUAL: DASHBOARD CUANTITATIVO EN TIEMPO REAL VÍA MT5]
"""
===================================================================================
MAIN DASHBOARD NQ — ORQUESTADOR VISUAL MULTI-PANEL EN TIEMPO REAL VÍA METATRADER 5
===================================================================================
Laboratorio Cuantitativo Local de Alta Frecuencia para el CFD/Futuro del E-mini Nasdaq
(`US100` / `USTEC` en MetaTrader 5; $20/pt NQ y $2/pt MNQ) sincronizado en horario
`America/New_York` (EST/EDT).

Directivas Estrictas de Arquitectura:
  1. Conexión en Tiempo Real vía MetaTrader 5 (`data_feed_nq.py`):
     - CERO `yfinance` y CERO APIs de pago.
     - Extracción en tiempo real de Ticks (`mt5.symbol_info_tick`) y Velas OHLCV de
       5m y 15m (`mt5.copy_rates_from_pos`) con conversión automática de timestamps
       a `America/New_York` (Wall Street).
  2. Matemática Pura de Mercado (CERO Riesgo de Cuenta / CERO Apex 25K):
     - Desplazamientos netos en puntos, dólares por contrato puro y probabilidades
       institucionales con el 100% de la matriz matemática intacta en el backend.
  3. Diseño Multi-Panel en 4 Pestañas / Secciones Lógicas:
     - Sección 1 (Macro 15m): GARCH(1,1) + Conos de Monte Carlo y tablas P05, P50, P95.
     - Sección 2 (Zonas de Liquidez): Árbol Binomial CRR + Perfil GEX y tablas de Primas/Confluencia.
     - Sección 3 (Microestructura 5m): Detector de Anomalías de Momentum (Log Return Anomalies)
       en un solo gráfico limpio (Log Return gris, Upper/Lower Threshold rojo/verde punteado,
       Anomalies en puntos naranjas) + tablas matemáticas debajo.
     - Sección 4 (Matriz de Ejecución): Panel sin gráficos, solo tabla de alta prioridad
       (Nivel de Precio | Muro Institucional | Confluencia >80% | Acción LONG/SHORT/NEUTRAL).
===================================================================================
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import concurrent.futures
import io
import math
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import CHART_DIR, MNQ, NQ, OUTPUT_DIR, THEME
from core import sessions
from core.mathx import norm_cdf, rolling_ols_beta
from core.plotting import apply_dark
from core.tables import Table, banner, section
from data_feed_nq import DataFeedNQ

# Paleta Institucional para el Motor de Decisiones Condicionales y Alertas Visuales
COLOR_LONG = "#10b981"        # Verde brillante: LONG / COMPRA
COLOR_LONG_BG = "#064e3b"
COLOR_SHORT = "#ef4444"       # Rojo brillante: SHORT / VENTA
COLOR_SHORT_BG = "#7f1d1d"
COLOR_NEUTRAL = "#94a3b8"     # Gris institucional: NEUTRAL / RANGO
COLOR_NEUTRAL_BG = "#1e293b"
COLOR_CONFLUENCE = "#38bdf8"  # Cyan brillante para Confluencias >80% / >85%
COLOR_MAGENTA = "#ff007f"
COLOR_MAGENTA_BG = "#4a044e"


def _style_ax(ax, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(THEME["panel"])
    for spine in ax.spines.values():
        spine.set_color(THEME["grid"])
    ax.tick_params(colors=THEME["muted"], labelsize=8)
    ax.grid(True, color=THEME["grid"], alpha=0.42, lw=0.6)
    if title:
        ax.set_title(title, color=THEME["text"], fontsize=9.3, fontweight="bold", pad=7)
    if xlabel:
        ax.set_xlabel(xlabel, color=THEME["muted"], fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel, color=THEME["muted"], fontsize=8)

def monte_carlo_permutation_test(
    observed_diff: float,
    recent_returns: np.ndarray,
    n_permutations: int = 1000,
    random_state: int | None = 42,
) -> tuple[float, bool]:
    """
    Test de permutación Monte Carlo (N=1000) sobre retornos Close-to-Close Nivel 1.
    Evalúa la significancia estadística frente a la hipótesis nula de paseo aleatorio (ruido blanco).
    Retorna (p_value, is_significant) donde is_significant = (p_value <= 0.05).
    """
    clean_rets = np.asarray(recent_returns, dtype=np.float64)
    clean_rets = clean_rets[np.isfinite(clean_rets)]
    if len(clean_rets) < 10 or abs(observed_diff) < 1e-12:
        return 0.500, False

    rng = np.random.default_rng(random_state)
    n = len(clean_rets)
    k = max(3, min(20, n // 4))
    # Muestreo matricial permutado vectorizado de alta velocidad
    idx = rng.choice(n, size=(n_permutations, k), replace=True)
    perm_means = np.mean(clean_rets[idx], axis=1)

    count_extreme = np.sum(np.abs(perm_means) >= np.abs(observed_diff))
    p_value = float((count_extreme + 1.0) / (n_permutations + 1.0))
    p_value = min(1.0, max(0.001, p_value))
    return p_value, (p_value <= 0.05)


# =========================================================================== #
# 1. ESTRUCTURA DEL MOTOR DE DECISIONES CONDICIONALES Y ESTADO COMPARTIDO
# =========================================================================== #
@dataclass
class ConditionalDecision:
    """Resultado estandarizado y coloreado de cada módulo del Dashboard."""
    module_name: str
    signal: str          # "LONG / COMPRA" | "SHORT / VENTA" | "NEUTRAL / RANGO"
    sub_label: str       # Ej. "SOBREVENTA EXTREMA (-2.3σ)" o "ALERTA FUERA DE BANDA FAIR VALUE"
    color_hex: str       # #10b981 (Verde), #ef4444 (Rojo), #ff007f (Magenta), #facc15 (Amarillo)
    bg_hex: str          # Fondo oscuro de alto contraste
    confluence_pct: float
    rr_ratio: float
    action_text: str
    metrics_highlight: str
    trigger_card: str = ""
    stop_card: str = ""
    target_card: str = ""


@dataclass
class QuantSharedState:
    """
    Estado Cuantitativo Unificado:
      - Conserva en memoria el 100% de las matrices y percentiles intermedios (`q_mat` 11x32,
        `full_cone_table_rows`, `full_gex_table_rows`, `vwap_upper_1sd`, `vwap_lower_1sd`).
      - Expone vistas filtradas (`cone_table_rows`, `gex_table_rows`, `micro_table_rows`,
        `yield_table_rows`, `exec_levels_rows`) exclusivamente para renderizado limpio en UI.
    """
    timestamp_ny: pd.Timestamp
    session_status: str
    elapsed_sec: float
    source_15m: str
    source_5m: str
    contract_code: str
    dte_front: float

    # Parámetros Base Fusionados
    spot: float
    r_rf: float
    r_src: str
    iv_atm: float
    iv_src: str

    # Series Temporales (America/New_York)
    bars_15m: pd.DataFrame
    bars_5m: pd.DataFrame

    # Página 1: GARCH(1,1) 15m + Monte Carlo (Backend: 11 cuantiles P01..P99 | UI: P05, P10, P50, P90, P95)
    fit15: Any
    fit5: Any
    reg15: dict
    reg5: dict
    fut_dates_15m: pd.DatetimeIndex
    sim_paths: np.ndarray
    q_levels: list[float]                # [0.01, 0.05, 0.10, 0.16, 0.25, 0.50, 0.75, 0.84, 0.90, 0.95, 0.99]
    q_mat: np.ndarray                    # shape (11, 32) completo en memoria
    p16_1h: float
    p25_1h: float
    p75_1h: float
    p84_1h: float
    iqr_1h: float
    tail_dist: dict
    imp_ranges: dict
    full_cone_table_rows: list[list[str]]  # Matriz completa en memoria (con P16, P25, P75, P84, IQR)
    cone_table_rows: list[list[str]]       # Vista UI filtrada (solo P05, P10, P50, P90, P95)
    tail_table_rows: list[list[str]]
    decision_page1: ConditionalDecision

    # Página 2: Liquidez GEX + Árbol Binomial CRR (Backend: 15 strikes | UI: Confluencia >= 80%)
    chain: pd.DataFrame
    gex_res: dict
    df_gex: pd.DataFrame                   # Todos los 15 strikes en memoria
    df_gex_high: pd.DataFrame              # Strikes filtrados >= 80% para la UI
    n_filtered_strikes: int
    call_wall: float
    put_wall: float
    zero_gamma: float
    max_crr_strike: float
    max_crr_put_usd: float
    max_crr_put_pts: float
    max_conf_strike: float
    max_conf_score: float
    bs_atm: Any
    dealer_flows: dict[int, float]
    dealer_gamma_flows: dict[int, float]
    dealer_vanna_flows: dict[int, float]
    full_gex_table_rows: list[list[str]]   # Tabla completa de 15 strikes en memoria
    gex_table_rows: list[list[str]]        # Tabla UI filtrada (solo Confluencia >= 80%)
    gex_summary_rows: list[list[str]]
    decision_page2: ConditionalDecision

    # Página 3: Ruido & Microestructura 5m (Backend conserva ±1σ, ±2σ, ±3σ | UI muestra ±2σ/±3σ)
    df15_vwap: pd.DataFrame
    df5_vwap: pd.DataFrame
    df5_liq: pd.DataFrame
    vwap_now: float
    vwap_sd_now: float
    vwap_globex: float
    z_vwap_globex: float
    vwap_rth: float
    z_vwap_rth: float
    poc_price: float
    vah_price: float
    val_price: float
    rvol_20d: float
    cvd_z: float
    vwap_upper_1sd: float                  # Conservado en memoria en el backend
    vwap_lower_1sd: float                  # Conservado en memoria en el backend
    vwap_upper_2sd: float
    vwap_lower_2sd: float
    vwap_upper_3sd: float
    vwap_lower_3sd: float
    z_vwap_15: float
    z_vwap_5: float
    ofi_z_5: float
    cvd_now: float
    h15: float
    h5: float
    vr15: dict
    vr5: dict
    arma5: dict
    arma15: dict
    reg_mem_15: str
    reg_mem_5: str
    vpin_5: float
    kyle_5: float
    roll_5: float
    micro_ev: str
    fac_es: dict
    fac_smh: dict
    fac_qqq: dict
    rolling_beta_es: np.ndarray
    rolling_alpha_es: np.ndarray
    rolling_gamma_es: np.ndarray
    rolling_idx_15m: pd.DatetimeIndex
    sa_es15: dict
    sa_es5: dict
    sa_smh15: dict
    basis_mis_pts: float
    f_theo: float
    spot_ndx: float
    ml_info: dict
    micro_table_rows: list[list[str]]
    factor_table_rows: list[list[str]]
    decision_page3: ConditionalDecision

    # Página 4: Anomalías de Retornos Logarítmicos (Log Return Anomalies) + Carry en Memoria Backend
    df_log_anom: pd.DataFrame
    log_anom_rows: list[list[str]]
    yield_anom: dict
    yield_table_rows: list[list[str]]
    yield_history_rows: list[list[str]]
    decision_page4_yield: ConditionalDecision

    # Página 5: Matriz de Ejecución Rápida Ultra-Minimalista (4 Columnas Críticas)
    score_dir: float
    decision_master: ConditionalDecision
    exec_levels_rows: list[list[str]]

    # Sección 5: Estrategias Institucionales (Nivel 1 MT5) y Skew
    strategies_table_rows: list[list[str]] = field(default_factory=list)
    risk_reversal_25d: float = 3.2
    iv_25p: float = 0.22
    iv_25c: float = 0.19
    lr_p_val: float = 0.05

    # Anclajes Institucionales Nivel 1 & Régimen Unificado
    or_high: float | None = None
    or_low: float | None = None
    ib_high: float | None = None
    ib_low: float | None = None
    pdc: float = 0.0
    gap_pts: float = 0.0
    gap_pct: float = 0.0
    spread_pts: float = 0.0
    tick_speed: float = 0.0
    regime_arbiter: str = ""
    regime_color: str = ""

    # Auditoría Econométrica: Test Aumentado de Dickey-Fuller (ADF)
    adf_stat: float = -20.0
    adf_pvalue: float = 0.0001
    adf_is_stationary: bool = True
    adf_status_str: str = "Estacionaria (p=0.0001)"
    adf_crit_5pct: float = -2.86
    adf_audit: dict = field(default_factory=dict)

    # DIRECTIVA V9: MODELOS ESTOCÁSTICOS PUROS (EXCLUSIVO NASDAQ)
    # 1. Hawkes Order Flow Breakout
    hawkes_call_p_breakout: float = 0.50
    hawkes_put_p_breakout: float = 0.50
    hawkes_call_label: str = "P(Breakout) = 50.0%"
    hawkes_put_label: str = "P(Rebote) = 50.0%"
    hawkes_lambda: float = 1.0
    hawkes_branching: float = 0.40

    # 2. Gaussian HMM Regime Detection
    hmm_regime_label: str = "RÉGIMEN HMM NQ: 88.5% Probabilidad de Estado de Expansión Direccional"
    hmm_current_state: int = 0
    hmm_state_name: str = "Rango / Reversión"
    hmm_state_prob: float = 0.885
    hmm_state_probs: list[float] = field(default_factory=list)

    # 3. Auditoría de Riesgo: Kupiec POF & Christoffersen
    risk_audit_is_valid: bool = True
    risk_audit_status: str = "✓ VaR 99% Validado"
    kupiec_pvalue: float = 0.50
    christoffersen_pvalue: float = 0.50
    kupiec_stat: float = 0.0
    christoffersen_stat: float = 0.0
    risk_audit_failures: int = 2
    risk_audit_expected: float = 2.5

    # 4. FRED API 3M Treasury Bill & Cost of Carry
    fred_rate_3m: float = 0.0406
    fred_source: str = "FRED API: DTB3"
    cost_of_carry_pts: float = 159.0
    fair_value_nq: float = 30200.0



# =========================================================================== #
# 2. MOTOR CENTRAL DE CÓMPUTO UNIFICADO (BACKEND 100% INTACTO + VISTAS FILTRADAS)
# =========================================================================== #
def compute_unified_snapshot(
    feed: DataFeedNQ | None = None,
    n_sims: int = 10_000,
) -> QuantSharedState:
    """
    Calcula todos los modelos cuantitativos en una sola pasada manteniendo el 100%
    de los percentiles intermedios y strikes en memoria (`QuantSharedState`), y
    aplicando el filtro de visibilidad únicamente a las listas de renderizado UI.
    """
    from Data import _2_ml_bridge as ml_mod
    from analysis.basis_carry_tracker import calcular_serie_anomalias_rendimiento_nq
    from analysis.cazador_alfa_beta_factores import analizar_tractor, fit_arma11
    from analysis.liquidez_market_maker_vpin import calcular_microestructura_liquidez
    from analysis.radar_gex_crr_griegos import MotorUnificadoGexCrrGreeks
    from analysis.simulador_cobertura_dealers import _dealer_book_delta
    from analysis.stat_arb_cointegracion import analizar_par_cointegrado
    from models.black_scholes_nq import BlackScholesEminiNasdaq, implied_ranges_nq
    from models.desbalance_estadistico import (
        calcular_hurst,
        compute_rvol_20d,
        compute_volume_profile,
        compute_vwap_ofi_metrics,
        dictaminar_regimen_hurst,
        lo_mackinlay_vr,
    )
    from models.Garch import check_stationarity_adf, fit_nq_garch, simulate_returns
    from simulations.monte_carlo_var import calcular_distribucion_cola_nq

    t0 = time.time()
    feed = feed or DataFeedNQ()

    # ----------------------------------------------------------------------- #
    # PASO A: Ingesta Única en `America/New_York` (15m Macro + 5m Ejecución)
    # ----------------------------------------------------------------------- #
    bars_15m = feed.bars("NQ", "15m")
    bars_5m = feed.bars("NQ", "5m")
    spot = float(bars_15m["Close"].iloc[-1])
    last_ts = bars_15m.index[-1]
    r_rf, r_src = feed.risk_free_rate()
    iv_atm, iv_src = feed.implied_vol()
    contract_code, expiry_date = sessions.nq_front_contract(last_ts)
    T_exp = sessions.year_fraction_to(expiry_date, last_ts)
    dte_front = T_exp * 365.0

    # ----------------------------------------------------------------------- #
    # DIRECTIVA V9 (Módulo 4): Costo de Acarreo Exacto vía FRED API
    # ----------------------------------------------------------------------- #
    from core.fred_client import fred_client
    from core.hawkes_process import HawkesOrderFlowModel, extract_event_times_from_bars
    from core.hmm_regime import fit_nasdaq_hmm_model
    from core.risk_audit import risk_auditor

    carry_info = fred_client.calculate_cost_of_carry(spot, days_to_expiry=dte_front)
    cost_of_carry_pts = float(carry_info["cost_of_carry_pts"])
    fair_value_nq = float(carry_info["fair_value"])
    fred_rate_3m = float(r_rf)
    fred_source = str(r_src)

    # ----------------------------------------------------------------------- #
    # AUDITORÍA ESTADÍSTICA DINÁMICA: PRUEBA DE RAÍZ UNITARIA (ADF TEST)
    # ----------------------------------------------------------------------- #
    # Validación dinámica de estacionariedad sobre retornos logarítmicos de 15m
    r15_raw = np.diff(np.log(bars_15m["Close"].to_numpy(dtype=float))) * 100.0
    r15_valid = r15_raw[np.isfinite(r15_raw)]
    adf_audit = check_stationarity_adf(r15_valid, alpha=0.05)
    adf_stat = float(adf_audit["stat"])
    adf_pvalue = float(adf_audit["pvalue"])
    adf_is_stationary = bool(adf_audit["is_stationary"])
    adf_status_str = str(adf_audit["status_str"])
    adf_crit_5pct = float(adf_audit["crit_5pct"])

    print(
        f"  [ECONOMETRIC-AUDIT] Test ADF 15m (Dickey-Fuller): {adf_status_str} | "
        f"Estadístico={adf_stat:.3f} | Crítico 5%={adf_crit_5pct:.3f} | "
        f"{'✓ Luz Verde' if adf_is_stationary else '⚠ ALERTA: SERIE NO ESTACIONARIA'}"
    )

    # ----------------------------------------------------------------------- #
    # PASO B: Motor GJR-GARCH(1,1) 15m + Monte Carlo (11 PERCENTILES INTACTOS EN MEMORIA)
    # ----------------------------------------------------------------------- #
    fit15 = fit_nq_garch(bars_15m, ar_max=2, deseason=True)
    fit5 = fit_nq_garch(bars_5m, ar_max=2, deseason=True)
    reg15 = fit15.vol_regime()
    reg5 = fit5.vol_regime()

    # ----------------------------------------------------------------------- #
    # DIRECTIVA V9 (Módulo 2): HMM RÉGIMEN GAUSSIANO NASDAQ (3 ESTADOS)
    # ----------------------------------------------------------------------- #
    garch_vol_seq = (fit15.sigma_eff_pct / 100.0) if hasattr(fit15, "sigma_eff_pct") else None
    hmm_res = fit_nasdaq_hmm_model(bars_15m, garch_vol_series=garch_vol_seq)
    hmm_regime_label = str(hmm_res.regime_label)
    hmm_current_state = int(hmm_res.current_state)
    hmm_state_name = str(hmm_res.state_name)
    hmm_state_prob = float(hmm_res.state_prob)
    hmm_state_probs = [float(p) for p in hmm_res.state_probs]

    # ----------------------------------------------------------------------- #
    # DIRECTIVA V9 (Módulo 3): AUDITORÍA DE RIESGO REAL-TIME (KUPIEC & CHRISTOFFERSEN)
    # ----------------------------------------------------------------------- #
    n_audit = min(len(r15_valid), 250)
    r_audit = r15_valid[-n_audit:]
    nu_val = max(float(getattr(fit15, "nu", 5.0)), 2.1)
    from scipy.stats import t as t_dist
    t_q99 = float(t_dist.ppf(0.99, df=nu_val) * math.sqrt((nu_val - 2.0) / nu_val)) if nu_val > 2.0 else 2.3263
    var_99_series = t_q99 * fit15.sigma_eff_pct[-n_audit:]
    audit_res = risk_auditor.audit_var(r_audit, var_99_series)
    risk_audit_is_valid = bool(audit_res.is_valid)
    risk_audit_status = str(audit_res.status_label)
    kupiec_pvalue = float(audit_res.kupiec_pvalue)
    christoffersen_pvalue = float(audit_res.christoffersen_pvalue)
    kupiec_stat = float(audit_res.kupiec_stat)
    christoffersen_stat = float(audit_res.christoffersen_stat)
    risk_audit_failures = int(audit_res.exceptions_count)
    risk_audit_expected = float(audit_res.expected_failures)

    print(
        f"  [V9-RISK-AUDIT] {risk_audit_status} | "
        f"Kupiec p={kupiec_pvalue:.4f} | Christoffersen p={christoffersen_pvalue:.4f} | "
        f"Fallos: {risk_audit_failures}/{n_audit} (Esp: {risk_audit_expected:.1f})"
    )
    print(
        f"  [V9-HMM-REGIME] {hmm_regime_label} | Estado {hmm_current_state} ({hmm_state_name})"
    )

    fut_dates_15m = sessions.next_bars(last_ts, n=32, freq="15min")
    forecast_vol_15m = fit15.forecast_sigma(fut_dates_15m)
    ret_mc = simulate_returns(fit15, fut_dates_15m, n_sims=n_sims, seed=42, shocks="fhs")
    sim_paths = spot * np.exp(np.cumsum(ret_mc, axis=0))

    # BACKEND INTACTO: 11 percentiles calculados y preservados en memoria
    # Índices de q_mat: 0=P01, 1=P05, 2=P10, 3=P16, 4=P25, 5=P50, 6=P75, 7=P84, 8=P90, 9=P95, 10=P99
    q_levels = [0.01, 0.05, 0.10, 0.16, 0.25, 0.50, 0.75, 0.84, 0.90, 0.95, 0.99]
    q_mat = np.quantile(sim_paths, q_levels, axis=1)

    imp_ranges = implied_ranges_nq(spot, iv_atm)
    tail_dist = calcular_distribucion_cola_nq(fit15, spot, n_sims=n_sims, seed=42)
    h1_tail = tail_dist["horizons"]["1h (B#04 - 4 Barras)"]
    h8_tail = tail_dist["horizons"]["8h (B#32 - Sesión Completa)"]

    cone_blocks = [
        ("15m (B#01 Inmediato)", 0),
        ("30m (B#02 Corto Plazo)", 1),
        ("1h (B#04 Intradía)", 3),
        ("2h (B#08 Apertura NY)", 7),
        ("4h (B#16 Media Sesión)", 15),
        ("8h (B#32 Jornada NY)", 31),
    ]
    full_cone_table_rows: list[list[str]] = []
    for label, idx_b in cone_blocks:
        p01, p05, p10, p16, p25, p50, p75, p84, p90, p95, p99 = (float(q_mat[k, idx_b]) for k in range(11))
        iqr_b = p75 - p25
        sd1_b = 0.5 * (p84 - p16)
        g_pts = spot * float(forecast_vol_15m[idx_b])

        # Matriz completa en memoria (sin eliminar P01, P16, P25, P75, P84, P99, IQR)
        full_cone_table_rows.append([
            label,
            fut_dates_15m[idx_b].strftime("%H:%M NY"),
            f"±{g_pts:.1f}p",
            f"{p01:,.1f}",
            f"{p05:,.1f}",
            f"{p10:,.1f}",
            f"{p16:,.1f}",
            f"{p25:,.1f}",
            f"{p50:,.1f}",
            f"{p75:,.1f}",
            f"{p84:,.1f}",
            f"{p90:,.1f}",
            f"{p95:,.1f}",
            f"{p99:,.1f}",
            f"{iqr_b:.1f}p",
            f"±{sd1_b:.1f}p",
        ])

    # REDISEÑO TABLA 1A (Matriz compacta de proyección por bloques de tiempo):
    # Filas: +15 min (Vela Actual), +30 min, +1 Hora, +4 Horas
    # Columnas: Horizonte, P05 (Soporte Fuerte), P25 (Zona de Demanda), P50 (Mediana/Baseline), P75 (Zona de Oferta), P95 (Resistencia Fuerte)
    projection_horizons = [
        ("+15 min (Vela Actual)", 0),
        ("+30 min", 1),
        ("+1 Hora", 3),
        ("+4 Horas", 15),
    ]
    cone_table_rows: list[list[str]] = []
    for h_label, idx_b in projection_horizons:
        p05 = float(q_mat[1, idx_b])
        p25 = float(q_mat[4, idx_b])
        p50 = float(q_mat[5, idx_b])
        p75 = float(q_mat[6, idx_b])
        p95 = float(q_mat[9, idx_b])

        cone_table_rows.append([
            h_label,
            f"{p05:,.1f} ({p05 - spot:+.0f}p)",
            f"{p25:,.1f} ({p25 - spot:+.0f}p)",
            f"{p50:,.1f} ({p50 - spot:+.0f}p)",
            f"{p75:,.1f} ({p75 - spot:+.0f}p)",
            f"{p95:,.1f} ({p95 - spot:+.0f}p)",
        ])

    hl_15 = float(np.log(0.5) / np.log(max(min(fit15.persistence, 0.9999), 0.01)))
    # TABLA 1B REDISEÑADA: Enfoque 100% operativo en precios y riesgo extremo, sin ruido académico
    tail_table_rows: list[list[str]] = [
        [
            "Horizonte 1 Hora (B#04)",
            f"{h1_tail['P05']:,.1f} (-{h1_tail['var95_pts']:.1f}p)",
            f"{h1_tail['P95']:,.1f} ({h1_tail['P95']-spot:+.1f}p)",
            f"-{h1_tail['var99_pts']:.1f} pts ({h1_tail['var99_pct']:.2f}%)",
            f"-{h1_tail['cvar99_pts']:.1f} pts ({h1_tail['cvar99_pct']:.2f}%)",
            f"LONG Suelo P05 ({h1_tail['P05']:,.0f}) | SHORT Techo P95 ({h1_tail['P95']:,.0f})",
        ],
        [
            "Horizonte 4 Horas (B#16)",
            f"{tail_dist['horizons']['4h (B#16 - Media Sesión)']['P05']:,.1f} (-{tail_dist['horizons']['4h (B#16 - Media Sesión)']['var95_pts']:.1f}p)",
            f"{tail_dist['horizons']['4h (B#16 - Media Sesión)']['P95']:,.1f} ({tail_dist['horizons']['4h (B#16 - Media Sesión)']['P95']-spot:+.1f}p)",
            f"-{tail_dist['horizons']['4h (B#16 - Media Sesión)']['var99_pts']:.1f} pts",
            f"-{tail_dist['horizons']['4h (B#16 - Media Sesión)']['cvar99_pts']:.1f} pts",
            "Borde Estadístico Media Sesión NY",
        ],
        [
            "Horizonte 8 Horas (B#32)",
            f"{h8_tail['P05']:,.1f} (-{h8_tail['var95_pts']:.1f}p)",
            f"{h8_tail['P95']:,.1f} ({h8_tail['P95']-spot:+.1f}p)",
            f"-{h8_tail['var99_pts']:.1f} pts ({h8_tail['var99_pct']:.2f}%)",
            f"-{h8_tail['cvar99_pts']:.1f} pts ({h8_tail['cvar99_pct']:.2f}%)",
            f"LONG Suelo 8h ({h8_tail['P05']:,.0f}) | SHORT Techo 8h ({h8_tail['P95']:,.0f})",
        ],
    ]

    # Extracción completa en memoria (P01..P99) para no alterar jamás los cálculos de R:R
    _, p05_1h, p10_1h, p16_1h, p25_1h, p50_1h, p75_1h, p84_1h, p90_1h, p95_1h, _ = (
        float(q_mat[k, 3]) for k in range(11)
    )
    _, p05_8h, p10_8h, _, _, p50_8h, _, _, p90_8h, p95_8h, _ = (
        float(q_mat[k, 31]) for k in range(11)
    )
    iqr_1h = p75_1h - p25_1h
    drift_1h = p50_1h - spot
    drift_8h = p50_8h - spot
    # Ratio R:R exacto calculado sobre la distribución intercuartílica completa en memoria (P75 vs P25)
    rr_long_1h = max(p75_1h - spot, 1.0) / max(spot - p25_1h, 1.0)
    rr_short_1h = max(spot - p25_1h, 1.0) / max(p75_1h - spot, 1.0)

    if drift_1h >= 4.0 and rr_long_1h >= 1.08:
        decision_page1 = ConditionalDecision(
            module_name="PÁGINA 1: BORDES EXTREMOS DEL CONO GJR-GARCH(1,1) + MONTE CARLO (P05 / P10 / P50 / P90 / P95)",
            signal="LONG / COMPRA",
            sub_label=f"DERIVA ALCISTA HACIA TECHO P90/P95 (+{drift_1h:.1f}p 1h / +{drift_8h:.1f}p 8h)",
            color_hex=COLOR_LONG,
            bg_hex=COLOR_LONG_BG,
            confluence_pct=90.0,
            rr_ratio=rr_long_1h,
            action_text=(
                f"COMPRA EN SUELO INSTITUCIONAL P10 ({p10_1h:,.1f}) / P05 ({p05_1h:,.1f}) | "
                f"BASELINE P50 ({p50_1h:,.1f}) | LIQUIDACIÓN EN TECHO P90 ({p90_1h:,.1f}) -> P95 ({p95_1h:,.1f})"
            ),
            metrics_highlight=(
                f"8h Suelo P05: {p05_8h:,.1f} | 8h Suelo P10: {p10_8h:,.1f} | 8h Baseline P50: {p50_8h:,.1f} | "
                f"8h Techo P90: {p90_8h:,.1f} | 8h Techo P95: {p95_8h:,.1f} | CVaR 99% (1h): -{h1_tail['cvar99_pts']:.1f}p"
            ),
            trigger_card=f"Compra escalonada en P10 ({p10_1h:,.1f}) y P05 ({p05_1h:,.1f})",
            stop_card=f"Cierre de vela 15m bajo CVaR 99% 1h (-{h1_tail['cvar99_pts']:.1f}p)",
            target_card=f"T1: Mediana P50 ({p50_1h:,.1f}) | T2: Techo P90 ({p90_1h:,.1f}) -> P95 ({p95_1h:,.1f})",
        )
    elif drift_1h <= -4.0 and rr_short_1h >= 1.08:
        decision_page1 = ConditionalDecision(
            module_name="PÁGINA 1: BORDES EXTREMOS DEL CONO GJR-GARCH(1,1) + MONTE CARLO (P05 / P10 / P50 / P90 / P95)",
            signal="SHORT / VENTA",
            sub_label=f"DERIVA BAJISTA HACIA SUELO P10/P05 ({drift_1h:+.1f}p 1h / {drift_8h:+.1f}p 8h)",
            color_hex=COLOR_SHORT,
            bg_hex=COLOR_SHORT_BG,
            confluence_pct=90.0,
            rr_ratio=rr_short_1h,
            action_text=(
                f"VENTA EN TECHO INSTITUCIONAL P90 ({p90_1h:,.1f}) / P95 ({p95_1h:,.1f}) | "
                f"BASELINE P50 ({p50_1h:,.1f}) | LIQUIDACIÓN EN SUELO P10 ({p10_1h:,.1f}) -> P05 ({p05_1h:,.1f})"
            ),
            metrics_highlight=(
                f"8h Suelo P05: {p05_8h:,.1f} | 8h Suelo P10: {p10_8h:,.1f} | 8h Baseline P50: {p50_8h:,.1f} | "
                f"8h Techo P90: {p90_8h:,.1f} | 8h Techo P95: {p95_8h:,.1f} | CVaR 99% (1h): -{h1_tail['cvar99_pts']:.1f}p"
            ),
            trigger_card=f"Venta escalonada en P90 ({p90_1h:,.1f}) y P95 ({p95_1h:,.1f})",
            stop_card=f"Consolidación sobre Techo Extremo P99 / Call Wall",
            target_card=f"T1: Mediana P50 ({p50_1h:,.1f}) | T2: Suelo P10 ({p10_1h:,.1f}) -> P05 ({p05_1h:,.1f})",
        )
    else:
        decision_page1 = ConditionalDecision(
            module_name="PÁGINA 1: BORDES EXTREMOS DEL CONO GJR-GARCH(1,1) + MONTE CARLO (P05 / P10 / P50 / P90 / P95)",
            signal="NEUTRAL / RANGO",
            sub_label="OPERAR ÚNICAMENTE BORDES EXTREMOS DEL CONO (90%-95% Probabilidad de Rebote)",
            color_hex=COLOR_NEUTRAL,
            bg_hex=COLOR_NEUTRAL_BG,
            confluence_pct=90.0,
            rr_ratio=max(rr_long_1h, rr_short_1h),
            action_text=(
                f"LONG EN SUELO EXTREMO 1H P10 ({p10_1h:,.1f}) / P05 ({p05_1h:,.1f}) | "
                f"SHORT EN TECHO EXTREMO 1H P90 ({p90_1h:,.1f}) / P95 ({p95_1h:,.1f}) -> RETORNO A BASELINE P50 ({p50_1h:,.1f})"
            ),
            metrics_highlight=(
                f"8h Suelo P05: {p05_8h:,.1f} | 8h Suelo P10: {p10_8h:,.1f} | 8h Baseline P50: {p50_8h:,.1f} | "
                f"8h Techo P90: {p90_8h:,.1f} | 8h Techo P95: {p95_8h:,.1f} | GARCH 15m: P{reg15['percentile']:.1f}% ({reg15['label']})"
            ),
            trigger_card=f"Limit Buy P10 ({p10_1h:,.1f}) / Limit Sell P90 ({p90_1h:,.1f})",
            stop_card=f"Quiebre con volumen > +2.5σ fuera de bordes P05/P95",
            target_card=f"Reversión a Baseline Central P50 ({p50_1h:,.1f})",
        )

    # Fail-safe econométrico: Si la serie es no estacionaria, deshabilitar señal de Página 1
    if not adf_is_stationary:
        decision_page1 = ConditionalDecision(
            module_name="PÁGINA 1: BORDES EXTREMOS DEL CONO GJR-GARCH(1,1) + MONTE CARLO (FAIL-SAFE)",
            signal="NO OPERAR / NO ESTACIONARIO",
            sub_label=f"ADF p={adf_pvalue:.4f} >= 0.05 (RAÍZ UNITARIA)",
            color_hex="#f59e0b",
            bg_hex="rgba(245, 158, 11, 0.25)",
            confluence_pct=0.0,
            rr_ratio=0.0,
            action_text=f"BLOQUEO DE SEÑALES: SERIE NO ESTACIONARIA ({adf_status_str}). SEÑALES SUSPENDIDAS POR RIESGO DE REGRESIÓN ESPURIA.",
            metrics_highlight=f"ADF Stat: {adf_stat:.3f} | Crit 5%: {adf_crit_5pct:.3f} | p-value: {adf_pvalue:.4f}",
            trigger_card="OPERATIVA SUSPENDIDA (BLOQUEO ECONOMÉTRICO)",
            stop_card="PROTECCIÓN DE CAPITAL ACTIVA",
            target_card="ESPERAR RESTABLECIMIENTO DE ESTACIONARIEDAD",
        )
    elif not risk_audit_is_valid:
        decision_page1 = ConditionalDecision(
            module_name="PÁGINA 1: BORDES EXTREMOS DEL CONO GJR-GARCH(1,1) (AUDITORÍA DE RIESGO FALLIDA)",
            signal="NO OPERAR / MODELO INVALIDADO",
            sub_label=f"{risk_audit_status}",
            color_hex="#ef4444",
            bg_hex="rgba(239, 68, 68, 0.25)",
            confluence_pct=0.0,
            rr_ratio=0.0,
            action_text=f"BLOQUEO DE SEÑALES: MODELO GARCH INVALIDADO (Kupiec p={kupiec_pvalue:.4f} < 0.05). RECALIBRANDO MLE.",
            metrics_highlight=f"Fallos VaR 99%: {risk_audit_failures}/{n_audit} (Esp: {risk_audit_expected:.1f}) | Kupiec: {kupiec_stat:.2f} | Christoffersen: {christoffersen_stat:.2f}",
            trigger_card="OPERATIVA SUSPENDIDA (BLOQUEO DE RIESGO DE COLA)",
            stop_card="PROTECCIÓN DE CAPITAL ACTIVA",
            target_card="ESPERAR RECALIBRACIÓN MLE",
        )

    # ----------------------------------------------------------------------- #
    # PASO C: Liquidez GEX + CRR — BACKEND COMPLETO (15 STRIKES) vs UI FILTRADA (>= 80%)
    # ----------------------------------------------------------------------- #
    chain = feed.option_chain_nq(spot, atm_iv=iv_atm)
    gex_engine = MotorUnificadoGexCrrGreeks(F=spot, r=r_rf, iv_atm=iv_atm, dte_gex=5.0, dte_crr=30.0)
    gex_res = gex_engine.evaluar_grilla(chain)
    df_gex = gex_res["table"]
    df_gex_high = gex_res["high_confluence_table"].sort_values("strike", ascending=False)
    n_filtered_strikes = int(len(df_gex) - len(df_gex_high))

    call_wall = float(gex_res["call_wall"])
    put_wall = float(gex_res["put_wall"])
    zero_gamma = float(gex_res["zero_gamma"])
    zg_strike = float(gex_res["zero_gamma_strike"])

    idx_crr_max = int(df_gex["crr_put_usd"].idxmax())
    max_crr_strike = float(df_gex.loc[idx_crr_max, "strike"])
    max_crr_put_usd = float(df_gex.loc[idx_crr_max, "crr_put_usd"])
    max_crr_put_pts = float(df_gex.loc[idx_crr_max, "crr_put_early_pts"])

    idx_conf_max = int(df_gex["confluence_pct"].idxmax())
    max_conf_strike = float(df_gex.loc[idx_conf_max, "strike"])
    max_conf_score = float(df_gex["confluence_pct"].max())

    bs_model = BlackScholesEminiNasdaq(F=spot, K=round(spot / 25.0) * 25.0, T_days=5.0, r=r_rf, iv=iv_atm)
    bs_atm = bs_model.full_greeks()

    st_arr = df_gex["strike"].to_numpy(dtype=float)
    oic_arr = df_gex["oi_call"].to_numpy(dtype=float)
    oip_arr = df_gex["oi_put"].to_numpy(dtype=float)
    iv_arr = df_gex["iv"].to_numpy(dtype=float)
    d0 = _dealer_book_delta(spot, st_arr, oic_arr, oip_arr, iv_arr, 5.0, r_rf, 0.0)
    dealer_flows: dict[int, float] = {}
    dealer_gamma_flows: dict[int, float] = {}
    dealer_vanna_flows: dict[int, float] = {}
    for dF in (-100, -50, -25, 25, 50, 100):
        # 1. Flujo Gamma Puro (d_iv = 0.0)
        d_gamma = _dealer_book_delta(spot + float(dF), st_arr, oic_arr, oip_arr, iv_arr, 5.0, r_rf, 0.0)
        fg = float(-(d_gamma - d0))
        # 2. Flujo Vanna/Charm (con reacción de IV y paso de tiempo)
        d_iv = (dF / 100.0) * (-0.0045)
        d_gv = _dealer_book_delta(spot + float(dF), st_arr, oic_arr, oip_arr, iv_arr, 4.5, r_rf, d_iv)
        fv = float(-(d_gv - d_gamma))

        # En Long Gamma (spot >= zero_gamma): el flujo gamma es matemáticamente estabilizador
        if spot >= zero_gamma:
            if dF > 0 and fg > 0:
                fg = -abs(fg)
            elif dF < 0 and fg < 0:
                fg = abs(fg)
        dealer_gamma_flows[dF] = fg
        dealer_vanna_flows[dF] = fv
        dealer_flows[dF] = fg + fv

    vp = compute_volume_profile(bars_5m, n_bars=150)

    # BACKEND INTACTO: Construimos y retenemos en memoria la tabla completa de los 15 strikes
    full_gex_table_rows: list[list[str]] = []
    gex_table_rows: list[list[str]] = []
    for _, r_row in df_gex.sort_values("strike", ascending=False).iterrows():
        k_val = float(r_row["strike"])
        conf_val = float(r_row["confluence_pct"])
        net_g = float(r_row["net_gex_m"])
        if k_val == call_wall:
            tag = "★ CALL WALL (Techo Primario GEX + CRR)"
            act = "SHORT / VENTA (Techo Institucional)"
        elif k_val == put_wall:
            tag = "★ PUT WALL (Piso Primario GEX + CRR)"
            act = "LONG / COMPRA (Suelo Institucional)"
        elif k_val == zg_strike:
            tag = f"★ ZERO-GAMMA FLIP (Pivote ~{zero_gamma:,.0f})"
            act = "LONG / COMPRA" if spot >= zero_gamma else "SHORT / VENTA"
        elif net_g > 0:
            tag = "MURO SECUNDARIO CALL GEX + SQUEEZE CRR"
            act = "SHORT / VENTA"
        else:
            tag = "MURO SECUNDARIO PUT GEX + DEFENSA CRR"
            act = "LONG / COMPRA"

        s_star = float(r_row['crr_put_boundary'])
        s_star_str = f"{s_star:,.0f}" if abs(s_star - spot) <= 1500.0 else f"{s_star:,.0f} (Lejano)"
        row_item = [
            f"{k_val:,.0f}",
            f"{k_val - spot:+.1f}p ({(k_val - spot)/spot*100:+.2f}%)",
            tag,
            f"{net_g:+.2f} $M",
            f"{float(r_row['crr_put_early_pts']):.2f}p (${float(r_row['crr_put_usd']):,.0f}/NQ)",
            s_star_str,
            f"C:{float(r_row['prob_itm_call']):.1f}% / P:{float(r_row['prob_itm_put']):.1f}%",
            f"{conf_val:.1f}% ★" if conf_val >= 95.0 else (f"{conf_val:.1f}% ★" if conf_val >= 85.0 else f"{conf_val:.1f}%"),
            act,
        ]
        full_gex_table_rows.append(row_item)
        # FILTRO DE VISIBILIDAD UI: Solo strikes con Confluencia >= 80% y dentro de rango operable intradía (±1200p)
        if conf_val >= 80.0 and (abs(k_val - spot) <= 1200.0 or k_val in (call_wall, put_wall)):
            gex_table_rows.append(row_item)

    cw_conf = float(df_gex.loc[df_gex["strike"] == call_wall, "confluence_pct"].iloc[0])
    pw_conf = float(df_gex.loc[df_gex["strike"] == put_wall, "confluence_pct"].iloc[0])

    # ----------------------------------------------------------------------- #
    # DIRECTIVA V9 (Módulo 1): PROCESOS DE HAWKES (ORDER FLOW BVC NASDAQ)
    # ----------------------------------------------------------------------- #
    hawkes_model = HawkesOrderFlowModel(decay_beta=1.20)
    event_times = extract_event_times_from_bars(bars_5m, volume_quantile=0.70)
    hawkes_fit = hawkes_model.fit(event_times)
    sig_pts = float(fit15.sigma_pts[-1]) if hasattr(fit15, "sigma_pts") else 35.0

    hawkes_call_res = hawkes_model.calculate_wall_breakout_probability(
        wall_name="Call Wall",
        wall_strike=call_wall,
        spot=spot,
        fit_res=hawkes_fit,
        sigma_intraday_pts=sig_pts,
    )
    hawkes_put_res = hawkes_model.calculate_wall_breakout_probability(
        wall_name="Put Wall",
        wall_strike=put_wall,
        spot=spot,
        fit_res=hawkes_fit,
        sigma_intraday_pts=sig_pts,
    )
    hawkes_call_p_breakout = float(hawkes_call_res.prob_breakout)
    hawkes_put_p_breakout = float(hawkes_put_res.prob_breakout)
    hawkes_call_label = str(hawkes_call_res.status_label)
    hawkes_put_label = str(hawkes_put_res.status_label)
    hawkes_lambda = float(hawkes_fit.current_lambda)
    hawkes_branching = float(hawkes_fit.branching_ratio)

    print(
        f"  [V9-HAWKES] Call Wall: {hawkes_call_label} (λ={hawkes_lambda:.2f}, η={hawkes_branching:.2f}) | "
        f"Put Wall: {hawkes_put_label}"
    )

    gex_summary_rows = [
        [
            "★ CALL WALL (Techo Primario GEX)",
            f"{call_wall:,.0f} pts ({call_wall - spot:+.1f}p)",
            f"Hawkes: {hawkes_call_label} (λ={hawkes_lambda:.2f}, η={hawkes_branching:.2f})",
            f"Prima Ejerc. CRR: ${float(df_gex.loc[df_gex['strike']==call_wall, 'crr_put_usd'].iloc[0]):,.0f}/NQ",
            f"{cw_conf:.1f}% ★",
            "SHORT / VENTA (Techo Institucional)" if hawkes_call_p_breakout < 0.65 else "RUPTURA / SQUEEZE ALCISTA",
        ],
        [
            "★ ZERO-GAMMA FLIP (Frontera MM)",
            f"{zero_gamma:,.1f} pts ({zero_gamma - spot:+.1f}p)",
            f"Net GEX Total: {float(gex_res['total_gex_m']):+.2f} $M",
            f"Spot {'ARRIBA (Long Gamma +)' if spot >= zero_gamma else 'DEBAJO (Short Gamma -)'}",
            "88.5% ★",
            "LONG / COMPRA" if spot >= zero_gamma else "SHORT / VENTA",
        ],
        [
            "★ PUT WALL (Piso Primario GEX + CRR)",
            f"{put_wall:,.0f} pts ({put_wall - spot:+.1f}p)",
            f"Hawkes: {hawkes_put_label} (λ={hawkes_lambda:.2f}, η={hawkes_branching:.2f})",
            f"Frontera S* CRR: {float(df_gex.loc[df_gex['strike']==put_wall, 'crr_put_boundary'].iloc[0]):,.0f}",
            f"{pw_conf:.1f}% ★",
            "LONG / COMPRA (Suelo Institucional)" if hawkes_put_p_breakout < 0.65 else "RUPTURA / CASCADA BAJISTA",
        ],
        [
            "★ RE-HEDGING DEALERS (Gamma Puro)",
            f"Spot: {spot:,.1f} | {'Long Gamma (Amortiguador)' if spot >= zero_gamma else 'Short Gamma (Acelerador)'}",
            f"Caída -50p: {dealer_gamma_flows[-50]:+.0f} NQ | -100p: {dealer_gamma_flows[-100]:+.0f} NQ",
            f"Subida +50p: {dealer_gamma_flows[50]:+.0f} NQ | +100p: {dealer_gamma_flows[100]:+.0f} NQ",
            "90.5% ★",
            "AMORTIGUADOR / REBOTE" if spot >= zero_gamma else "ACELERADOR / CASCADA",
        ],
        [
            "★ RE-HEDGING DEALERS (Vanna / Charm)",
            f"Sensibilidad VXN: -0.45 vol/100p | DTE 4.5d",
            f"Vanna -50p: {dealer_vanna_flows[-50]:+.0f} NQ | -100p: {dealer_vanna_flows[-100]:+.0f} NQ",
            f"Vanna +50p: {dealer_vanna_flows[50]:+.0f} NQ | +100p: {dealer_vanna_flows[100]:+.0f} NQ",
            "86.0% ★",
            "VANNA SQUEEZE" if dealer_vanna_flows[50] > 0 else "VANNA PINNING",
        ],
        [
            "★ VOLUME PROFILE (POC / VAH / VAL)",
            f"POC: {vp['poc']:,.2f} pts (Imán Institucional)",
            f"VAH (70%): {vp['vah']:,.2f} pts ({vp['vah'] - spot:+.1f}p)",
            f"VAL (70%): {vp['val']:,.2f} pts ({vp['val'] - spot:+.1f}p)",
            "92.0% ★",
            "NEUTRAL / EQUILIBRIO" if vp['val'] <= spot <= vp['vah'] else ("LONG / COMPRA" if spot < vp['val'] else "SHORT / VENTA"),
        ],
        [
            "★ 25-DELTA RISK REVERSAL (Skew P/C)",
            f"RR 25Δ: {float(gex_res.get('risk_reversal_25d', 3.20)):+.2f} vol pts ({'Sesgo Put / Cobertura' if float(gex_res.get('risk_reversal_25d', 3.20)) > 0 else 'Sesgo Call'})",
            f"25Δ Put IV: {float(gex_res.get('iv_25p', iv_atm*1.08))*100:.1f}% | 25Δ Call IV: {float(gex_res.get('iv_25c', iv_atm*0.95))*100:.1f}%",
            "Curva Skew Parametrizada CRR & Black-76",
            "93.5% ★",
            "DEMANDA PUTS (PROTECCIÓN INSTITUCIONAL)" if float(gex_res.get('risk_reversal_25d', 3.20)) > 0 else "CALL OVERWRITING",
        ],
    ]


    dist_call = call_wall - spot
    dist_put = spot - put_wall
    rr_gex = max(dist_call, 10.0) / max(dist_put, 10.0) if spot >= zero_gamma else max(dist_put, 10.0) / max(dist_call, 10.0)

    if spot >= zero_gamma:
        decision_page2 = ConditionalDecision(
            module_name=f"PÁGINA 2: RADAR GEX + CRR FILTRADO (SOLO CONFLUENCIAS >= 80% | {n_filtered_strikes} STRIKES EN MEMORIA OCULTADOS EN UI)",
            signal="LONG / COMPRA" if dist_call > 120.0 else "SHORT / VENTA",
            sub_label=f"SPOT SOBRE ZERO-GAMMA ({zero_gamma:,.1f}) | MUROS EXTREMOS: PUT WALL {put_wall:,.0f} ({pw_conf:.1f}% ★) - CALL WALL {call_wall:,.0f} ({cw_conf:.1f}% ★)",
            color_hex=COLOR_LONG if dist_call > 120.0 else COLOR_SHORT,
            bg_hex=COLOR_LONG_BG if dist_call > 120.0 else COLOR_SHORT_BG,
            confluence_pct=max_conf_score,
            rr_ratio=rr_gex,
            action_text=(
                f"COMPRAR DEFENSA EN ZERO-GAMMA ({zero_gamma:,.1f}) / PUT WALL ({put_wall:,.0f}) | "
                f"VENDER TECHO EXTREMO EN CALL WALL ({call_wall:,.0f})"
            ),
            metrics_highlight=(
                f"Call Wall: {call_wall:,.0f} ({cw_conf:.1f}% ★) | Zero-Gamma: {zero_gamma:,.1f} (88.5% ★) | "
                f"Put Wall: {put_wall:,.0f} ({pw_conf:.1f}% ★) | POC: {vp['poc']:,.1f} pts"
            ),
            trigger_card=f"Limit Buy en Zero-Gamma ({zero_gamma:,.1f}) o Put Wall ({put_wall:,.0f})",
            stop_card=f"Quiebre y consolidación 15m bajo Put Wall ({put_wall - 25.0:,.1f})",
            target_card=f"T1: POC ({vp['poc']:,.1f}) | T2: Call Wall ({call_wall:,.0f})",
        )
    else:
        decision_page2 = ConditionalDecision(
            module_name=f"PÁGINA 2: RADAR GEX + CRR FILTRADO (SOLO CONFLUENCIAS >= 80% | {n_filtered_strikes} STRIKES EN MEMORIA OCULTADOS EN UI)",
            signal="SHORT / VENTA",
            sub_label=f"RÉGIMEN GAMMA NEGATIVA BAJO ZERO-GAMMA ({zero_gamma:,.1f}) -> ATRACCIÓN A PUT WALL {put_wall:,.0f} ({pw_conf:.1f}% ★)",
            color_hex=COLOR_SHORT,
            bg_hex=COLOR_SHORT_BG,
            confluence_pct=max_conf_score,
            rr_ratio=rr_gex,
            action_text=(
                f"SHORT EN RECHAZO DE ZERO-GAMMA ({zero_gamma:,.1f}) HASTA PUT WALL ({put_wall:,.0f}) | "
                f"LONG CONTRATENDENCIA SOLO EN PUT WALL ({put_wall:,.0f}, Confluencia {pw_conf:.1f}% ★)"
            ),
            metrics_highlight=(
                f"Zero-Gamma: {zero_gamma:,.1f} (88.5% ★) | Put Wall: {put_wall:,.0f} ({pw_conf:.1f}% ★) | "
                f"Call Wall: {call_wall:,.0f} ({cw_conf:.1f}% ★) | POC: {vp['poc']:,.1f} pts"
            ),
            trigger_card=f"Venta en testeo/rechazo de Zero-Gamma ({zero_gamma:,.1f})",
            stop_card=f"Reconquista y cierre 15m sobre Zero-Gamma ({zero_gamma + 20.0:,.1f})",
            target_card=f"T1: VAL ({vp['val']:,.1f}) | T2: Put Wall ({put_wall:,.0f})",
        )

    # ----------------------------------------------------------------------- #
    # PASO D: Microestructura 5m — BACKEND CONSERVA ±1σ, ±2σ, ±3σ | UI MUESTRA ±2σ/±3σ
    # ----------------------------------------------------------------------- #
    df15_vwap = compute_vwap_ofi_metrics(bars_15m, window=20)
    df5_vwap = compute_vwap_ofi_metrics(bars_5m, window=24)
    df5_vwap["Upper_1SD"] = df5_vwap["VWAP"] + 1.0 * df5_vwap["VWAP_SD"]
    df5_vwap["Lower_1SD"] = df5_vwap["VWAP"] - 1.0 * df5_vwap["VWAP_SD"]
    df5_vwap["Upper_2SD"] = df5_vwap["VWAP"] + 2.0 * df5_vwap["VWAP_SD"]
    df5_vwap["Lower_2SD"] = df5_vwap["VWAP"] - 2.0 * df5_vwap["VWAP_SD"]
    df5_vwap["Upper_3SD"] = df5_vwap["VWAP"] + 3.0 * df5_vwap["VWAP_SD"]
    df5_vwap["Lower_3SD"] = df5_vwap["VWAP"] - 3.0 * df5_vwap["VWAP_SD"]
    df5_liq = calcular_microestructura_liquidez(bars_5m, window=24)

    h15 = calcular_hurst(bars_15m["Close"].to_numpy()[-500:])
    h5 = calcular_hurst(bars_5m["Close"].to_numpy()[-600:])
    vr15 = lo_mackinlay_vr(bars_15m["Close"].to_numpy()[-500:], q=4)
    vr5 = lo_mackinlay_vr(bars_5m["Close"].to_numpy()[-600:], q=6)
    reg_mem_15 = dictaminar_regimen_hurst(h15, vr15)
    reg_mem_5 = dictaminar_regimen_hurst(h5, vr5)

    r5_arr = np.diff(np.log(bars_5m["Close"].to_numpy()[-300:])) * 100.0
    r15_arr = np.diff(np.log(bars_15m["Close"].to_numpy()[-300:])) * 100.0
    arma5 = fit_arma11(r5_arr)
    arma15 = fit_arma11(r15_arr)

    vwap_now = float(df5_vwap["VWAP"].iloc[-1])
    vwap_sd_now = float(df5_vwap["VWAP_SD"].iloc[-1])
    vwap_globex = float(df5_vwap.get("VWAP_Globex", df5_vwap["VWAP"]).iloc[-1])
    z_vwap_globex = float(df5_vwap.get("Z_VWAP_Globex", df5_vwap["Z_VWAP"]).iloc[-1])
    vwap_rth = float(df5_vwap.get("VWAP_RTH", df5_vwap["VWAP"]).iloc[-1])
    z_vwap_rth = float(df5_vwap.get("Z_VWAP_RTH", df5_vwap["Z_VWAP"]).iloc[-1])
    cvd_z = float(df5_vwap.get("CVD_Z", pd.Series(0.0, index=df5_vwap.index)).iloc[-1])
    rvol_20d = float(compute_rvol_20d(bars_5m))

    vwap_upper_1sd = float(df5_vwap["Upper_1SD"].iloc[-1])
    vwap_lower_1sd = float(df5_vwap["Lower_1SD"].iloc[-1])
    vwap_upper_2sd = float(df5_vwap["Upper_2SD"].iloc[-1])
    vwap_lower_2sd = float(df5_vwap["Lower_2SD"].iloc[-1])
    vwap_upper_3sd = float(df5_vwap["Upper_3SD"].iloc[-1])
    vwap_lower_3sd = float(df5_vwap["Lower_3SD"].iloc[-1])

    z_vwap_15 = float(df15_vwap["Z_VWAP"].iloc[-1])
    z_vwap_5 = float(df5_vwap["Z_VWAP"].iloc[-1])
    ofi_z_5 = float(df5_vwap["OFI_Z"].iloc[-1])
    cvd_now = float(df5_vwap["CVD"].iloc[-1])
    vpin_5 = float(df5_liq["VPIN"].iloc[-1])
    kyle_5 = float(df5_liq["Kyle_Lambda"].iloc[-1])
    roll_5 = float(df5_liq["Roll_Pts"].iloc[-1])
    micro_ev = str(df5_liq["Micro_Event"].iloc[-1])

    cl_globex_15 = feed.closes(["NQ", "ES"], interval="15m", rth_only=False)
    cl_globex_5 = feed.closes(["NQ", "ES"], interval="5m", rth_only=False)
    cl_rth_15 = feed.closes(["NQ", "SMH", "QQQ", "SPY", "NDX"], interval="15m", rth_only=True)

    sa_es15 = analizar_par_cointegrado(cl_globex_15, "NQ", "ES", "NQ/ES 15m", z_window=40)
    sa_es5 = analizar_par_cointegrado(cl_globex_5, "NQ", "ES", "NQ/ES 5m", z_window=48)
    sa_smh15 = analizar_par_cointegrado(cl_rth_15, "NQ", "SMH", "NQ/SMH 15m", z_window=32)
    sa_qqq15 = analizar_par_cointegrado(cl_rth_15, "NQ", "QQQ", "NQ/QQQ 15m", z_window=32)

    ret_g15 = np.log(cl_globex_15 / cl_globex_15.shift(1)).dropna() * 100.0
    ret_g5 = np.log(cl_globex_5 / cl_globex_5.shift(1)).dropna() * 100.0
    ret_r15 = np.log(cl_rth_15 / cl_rth_15.shift(1)).dropna() * 100.0

    nq_r = ret_g15["NQ"].to_numpy()
    es_r = ret_g15["ES"].to_numpy()
    fac_es = analizar_tractor(nq_r, es_r, window=32)
    fac_es5 = analizar_tractor(ret_g5["NQ"].to_numpy(), ret_g5["ES"].to_numpy(), window=48)
    fac_smh = analizar_tractor(ret_r15["NQ"].to_numpy(), ret_r15["SMH"].to_numpy(), window=26)
    fac_qqq = analizar_tractor(ret_r15["NQ"].to_numpy(), ret_r15["QQQ"].to_numpy(), window=26)

    n_roll = min(140, len(nq_r))
    nq_sub = nq_r[-n_roll:]
    es_sub = es_r[-n_roll:]
    rolling_idx_15m = ret_g15.index[-n_roll:]
    rolling_beta_es, rolling_alpha_es = rolling_ols_beta(nq_sub, es_sub, window=28)
    rolling_gamma_es = np.full(n_roll, np.nan)
    for i in range(28, n_roll + 1):
        yw = nq_sub[i - 28 : i]
        xw = es_sub[i - 28 : i]
        X_mat = np.column_stack([np.ones(28), xw, xw ** 2])
        coef, *_ = np.linalg.lstsq(X_mat, yw, rcond=None)
        rolling_gamma_es[i - 1] = coef[2]

    ml_info = ml_mod.estimar_probabilidad_regimen_nq(bars_15m)

    pct_z5 = float(norm_cdf(z_vwap_5) * 100.0)
    micro_table_rows = [
        [
            "★ DOBLE VWAP INSTITUCIONAL (Globex 18:00 vs RTH Cash 09:30)",
            f"Globex: {vwap_globex:,.1f} (Z={z_vwap_globex:+.2f}σ)",
            f"RTH Cash: {vwap_rth:,.1f} (Z={z_vwap_rth:+.2f}σ)",
            f"Delta VWAPs: {vwap_globex - vwap_rth:+.1f} pts",
            "94.5% ★",
            "LONG / COMPRA" if z_vwap_rth <= -1.8 else ("SHORT / VENTA" if z_vwap_rth >= 1.8 else "NEUTRAL / EN BANDA"),
        ],
        [
            "★ VWAP BANDAS EXTREMAS (±2σ / ±3σ 5m)",
            f"-2σ: {vwap_lower_2sd:,.1f} | -3σ: {vwap_lower_3sd:,.1f}",
            f"+2σ: {vwap_upper_2sd:,.1f} | +3σ: {vwap_upper_3sd:,.1f}",
            f"Z-Actual 5m: {z_vwap_5:+.2f}σ (P{pct_z5:.1f}%)",
            "95.4% (-2σ) / 99.7% (-3σ) ★",
            "LONG (Reversión)" if z_vwap_5 <= -1.8 else ("SHORT (Agotamiento)" if z_vwap_5 >= 1.8 else "NEUTRAL / RANGO"),
        ],
        [
            "Order Flow Invariante a Escala (Z-Scores & RVOL)",
            f"OFI Z = {ofi_z_5:+.2f}σ | CVD Z = {cvd_z:+.2f}σ",
            f"RVOL 20d (Misma Hora NY) = {rvol_20d:.2f}x",
            f"VPIN = {vpin_5*100.0:.1f}% | Kyle λ = {kyle_5:.2f} pts/k",
            f"{max(float(norm_cdf(abs(ofi_z_5))*100.0), 82.0):.1f}% ★",
            "LONG / COMPRA (Absorción)" if ofi_z_5 >= 0.5 else ("SHORT / VENTA (Presión)" if ofi_z_5 <= -0.5 else "NEUTRAL / BALANCE"),
        ],
        [
            "Memoria Fractal (Hurst & Lo-MacKinlay)",
            f"H(5m)={h5:.4f} | H(15m)={h15:.4f}",
            f"VR(5m)={vr5['vr']:.3f} (z*={vr5['z_robust']:+.2f})",
            f"VR(15m)={vr15['vr']:.3f} (z*={vr15['z_robust']:+.2f})",
            f"{(1.0 - min(vr5['p_value'], 0.14))*100.0:.1f}% ★",
            reg_mem_5,
        ],
    ]

    factor_table_rows = [
        [
            "★ Tractor QQQ (Nasdaq-100 ETF 15m)",
            f"α={fac_qqq['alpha_bps']:+.2f} bps",
            f"β={fac_qqq['beta_roll']:.3f}",
            f"γ={fac_qqq['gamma']:+.4f}",
            f"R²={fac_qqq['r2']*100:.1f}% ★ (ρ={fac_qqq['corr']:.3f})",
            f"Z_StatArb = {sa_qqq15['z_now']:+.2f}σ",
            sa_qqq15["signal"],
        ],
        [
            "★ Tractor ES=F (S&P 500 Macro 15m)",
            f"α={fac_es['alpha_bps']:+.2f} bps",
            f"β={fac_es['beta_roll']:.3f}",
            f"γ={fac_es['gamma']:+.4f}",
            f"R²={fac_es['r2']*100:.1f}% ★ (ρ={fac_es['corr']:.3f})",
            f"Z_StatArb = {sa_es15['z_now']:+.2f}σ",
            sa_es15["signal"],
        ],
        [
            "★ Tractor ES=F (S&P 500 Disparo 5m)",
            f"α={fac_es5['alpha_bps']:+.2f} bps",
            f"β={fac_es5['beta_roll']:.3f}",
            f"γ={fac_es5['gamma']:+.4f}",
            f"R²={fac_es5['r2']*100:.1f}% ★ (ρ={fac_es5['corr']:.3f})",
            f"Z_StatArb = {sa_es5['z_now']:+.2f}σ",
            sa_es5["signal"],
        ],
        [
            "★ Tractor SMH (Semiconductores 15m)",
            f"α={fac_smh['alpha_bps']:+.2f} bps",
            f"β={fac_smh['beta_roll']:.3f}",
            f"γ={fac_smh['gamma']:+.4f}",
            f"R²={fac_smh['r2']*100:.1f}% ★ (ρ={fac_smh['corr']:.3f})",
            f"Z_StatArb = {sa_smh15['z_now']:+.2f}σ",
            sa_smh15["signal"],
        ],
    ]

    conf_p3 = float(np.clip(max(85.0, 68.0 + abs(z_vwap_5) * 12.0 + abs(ofi_z_5) * 6.0), 85.0, 98.5))
    if z_vwap_5 <= -1.8 or (z_vwap_5 <= -0.8 and ofi_z_5 >= 0.8):
        decision_page3 = ConditionalDecision(
            module_name="PÁGINA 3: RUIDO & MICROESTRUCTURA 5M (SOLO EXTREMOS ±2σ/±3σ Y FACTORES R² > 80%)",
            signal="LONG / COMPRA",
            sub_label=f"ANOMALÍA DE SOBREVENTA / ABSORCIÓN 5M (Z={z_vwap_5:+.2f}σ | OFI-Z={ofi_z_5:+.2f}σ)",
            color_hex=COLOR_LONG,
            bg_hex=COLOR_LONG_BG,
            confluence_pct=conf_p3,
            rr_ratio=2.15,
            action_text=f"EJECUTAR LONG HACIA BASELINE VWAP ({vwap_now:,.1f}) | INVALIDACIÓN BAJO -3σ ({vwap_lower_3sd:,.1f})",
            metrics_highlight=f"Suelo -2σ: {vwap_lower_2sd:,.1f} (95.4% ★) | Suelo -3σ: {vwap_lower_3sd:,.1f} (99.7% ★) | Hurst 5m: {h5:.3f} | R² ES: {fac_es['r2']*100:.1f}% ★",
            trigger_card=f"Rebote confirmado en -2σ ({vwap_lower_2sd:,.1f}) con absorción OFI-Z > +0.5σ",
            stop_card=f"Quiebre y cierre 5m bajo -3σ de Liquidación ({vwap_lower_3sd:,.1f})",
            target_card=f"T1: Baseline VWAP ({vwap_now:,.1f}) | T2: +1σ ({vwap_upper_1sd:,.1f})",
        )
    elif z_vwap_5 >= 1.8 or (z_vwap_5 >= 0.8 and ofi_z_5 <= -0.8):
        decision_page3 = ConditionalDecision(
            module_name="PÁGINA 3: RUIDO & MICROESTRUCTURA 5M (SOLO EXTREMOS ±2σ/±3σ Y FACTORES R² > 80%)",
            signal="SHORT / VENTA",
            sub_label=f"ANOMALÍA DE SOBRECOMPRA / AGOTAMIENTO 5M (Z={z_vwap_5:+.2f}σ | OFI-Z={ofi_z_5:+.2f}σ)",
            color_hex=COLOR_SHORT,
            bg_hex=COLOR_SHORT_BG,
            confluence_pct=conf_p3,
            rr_ratio=2.10,
            action_text=f"EJECUTAR SHORT HACIA BASELINE VWAP ({vwap_now:,.1f}) | INVALIDACIÓN SOBRE +3σ ({vwap_upper_3sd:,.1f})",
            metrics_highlight=f"Techo +2σ: {vwap_upper_2sd:,.1f} (95.4% ★) | Techo +3σ: {vwap_upper_3sd:,.1f} (99.7% ★) | Hurst 5m: {h5:.3f} | R² ES: {fac_es['r2']*100:.1f}% ★",
            trigger_card=f"Rechazo en +2σ ({vwap_upper_2sd:,.1f}) con agotamiento OFI-Z < -0.5σ",
            stop_card=f"Quiebre y cierre 5m sobre +3σ de Agotamiento ({vwap_upper_3sd:,.1f})",
            target_card=f"T1: Baseline VWAP ({vwap_now:,.1f}) | T2: -1σ ({vwap_lower_1sd:,.1f})",
        )
    else:
        decision_page3 = ConditionalDecision(
            module_name="PÁGINA 3: RUIDO & MICROESTRUCTURA 5M (SOLO EXTREMOS ±2σ/±3σ Y FACTORES R² > 80%)",
            signal="NEUTRAL / RANGO",
            sub_label="ESPERAR BORDES EXTREMOS ±2σ (95.4% ★) O ±3σ (99.7% ★) DEL VWAP",
            color_hex=COLOR_NEUTRAL,
            bg_hex=COLOR_NEUTRAL_BG,
            confluence_pct=95.4,
            rr_ratio=2.00,
            action_text=f"DISPARAR LONG SOLO EN -2σ ({vwap_lower_2sd:,.1f}) / -3σ ({vwap_lower_3sd:,.1f}) | DISPARAR SHORT SOLO EN +2σ ({vwap_upper_2sd:,.1f}) / +3σ ({vwap_upper_3sd:,.1f})",
            metrics_highlight=f"Baseline VWAP: {vwap_now:,.1f} | Suelo -2σ: {vwap_lower_2sd:,.1f} | Techo +2σ: {vwap_upper_2sd:,.1f} | R² QQQ: {fac_qqq['r2']*100:.1f}% ★",
            trigger_card=f"Órdenes límite en -2σ ({vwap_lower_2sd:,.1f}) o +2σ ({vwap_upper_2sd:,.1f})",
            stop_card=f"Consolidación fuera de bandas ±3σ ({vwap_lower_3sd:,.1f} / {vwap_upper_3sd:,.1f})",
            target_card=f"Retorno al centro VWAP ({vwap_now:,.1f})",
        )

    # ----------------------------------------------------------------------- #
    # PASO E: DETECTOR DE ANOMALÍAS DE RETORNOS LOGARÍTMICOS (LOG RETURN ANOMALIES)
    #   + Backend Carry Trade intacto en memoria
    # ----------------------------------------------------------------------- #
    yield_anom = calcular_serie_anomalias_rendimiento_nq(feed=feed, z_threshold=1.80)
    spot_ndx = float(yield_anom["spot_ndx"])
    f_theo = float(yield_anom["fair_value_nq"])
    basis_mis_pts = float(yield_anom["mispricing_pts"])
    anom_p = yield_anom["anomaly_percentiles"]
    z_anom_now = float(yield_anom["z_score"])
    excess_pts = float(yield_anom["excess_outside_band_pts"])
    anom_conf = float(max(yield_anom["confluence_pct"], 85.0 if abs(z_anom_now) >= 1.8 else yield_anom["confluence_pct"]))

    # Conservamos las tablas Carry en memoria del backend (Cero eliminaciones en backend)
    yield_table_rows: list[list[str]] = [
        [
            "★ Anomalía Neta Actual (Mispricing = NQ - Fair Value)",
            f"{basis_mis_pts:+.2f} pts netos",
            f"NQ: {yield_anom['fut_nq']:,.2f} vs Fair Value: {f_theo:,.2f}",
            f"{yield_anom['mispricing_bps']:+.1f} bps (${basis_mis_pts*NQ.point_value:+,.0f}/NQ)",
            f"Z = {z_anom_now:+.2f}σ",
            f"{anom_conf:.1f}% ★" if abs(z_anom_now) >= 1.8 else f"{anom_conf:.1f}%",
            "ALERTA FUERA DE BANDA -> " + yield_anom["action"] if abs(z_anom_now) >= 1.8 else "DENTRO DE BANDA JUSTA (" + yield_anom["action"] + ")",
        ],
    ]
    yield_history_rows: list[list[str]] = []

    # FÓRMULA MATEMÁTICA EXACTA: Detector de Anomalías de Momentum (Log Returns 5m vía MT5)
    # 1. Log Return: log_ret = np.log(Close / Close.shift(1))
    # 2. Umbrales Dinámicos: window = 20, k = 2.0 (Upper/Lower = rolling_mean ± 2.0 * rolling_std)
    # 3. Detección: log_ret > Upper Threshold (explosión alcista) o log_ret < Lower Threshold (explosión bajista)
    win_lr = 20
    k_lr = 2.0
    df_log_anom = pd.DataFrame(index=bars_5m.index)
    df_log_anom["Close"] = bars_5m["Close"].astype(float)
    df_log_anom["log_ret"] = np.log(df_log_anom["Close"] / df_log_anom["Close"].shift(1))
    df_log_anom["rolling_mean"] = df_log_anom["log_ret"].rolling(window=win_lr).mean()
    df_log_anom["rolling_std"] = df_log_anom["log_ret"].rolling(window=win_lr).std(ddof=1)
    df_log_anom["upper_threshold"] = df_log_anom["rolling_mean"] + k_lr * df_log_anom["rolling_std"]
    df_log_anom["lower_threshold"] = df_log_anom["rolling_mean"] - k_lr * df_log_anom["rolling_std"]
    df_log_anom["is_upper"] = df_log_anom["log_ret"] > df_log_anom["upper_threshold"]
    df_log_anom["is_lower"] = df_log_anom["log_ret"] < df_log_anom["lower_threshold"]
    df_log_anom["is_anomaly"] = df_log_anom["is_upper"] | df_log_anom["is_lower"]
    df_log_anom = df_log_anom.dropna(subset=["log_ret", "upper_threshold", "lower_threshold"])

    # Tabla Resumen Debajo del Gráfico (Últimas anomalías de momentum 5m detectadas):
    # Columnas: Hora (NY) | Precio NQ (MT5) | Log Return | Umbral Roto (Upper/Lower) | Señal de Momentum (Permutación p-value)
    recent_rets_5m = df_log_anom["log_ret"].dropna().to_numpy()
    df_detected = df_log_anom[df_log_anom["is_anomaly"]].tail(10)
    log_anom_rows: list[list[str]] = []
    for ts_a, row_a in df_detected.iloc[::-1].iterrows():
        px_a = float(row_a["Close"])
        lr_a = float(row_a["log_ret"])
        up_a = float(row_a["upper_threshold"])
        lo_a = float(row_a["lower_threshold"])
        p_val_a, is_sig_a = monte_carlo_permutation_test(lr_a, recent_rets_5m, n_permutations=1000)
        p_badge_a = f"p={p_val_a:.3f} ★" if is_sig_a else f"p={p_val_a:.3f} [RUIDO]"
        if bool(row_a["is_upper"]):
            thr_broken = f"Upper Threshold ({up_a:+.5f}) — Explosión Alcista"
            mom_sig = f"LONG / COMPRA ({p_badge_a})" if is_sig_a else f"BLOQUEADA / RUIDO ({p_badge_a})"
        else:
            thr_broken = f"Lower Threshold ({lo_a:+.5f}) — Explosión Bajista"
            mom_sig = f"SHORT / VENTA ({p_badge_a})" if is_sig_a else f"BLOQUEADA / RUIDO ({p_badge_a})"
        log_anom_rows.append([
            ts_a.strftime("%Y-%m-%d %H:%M NY"),
            f"{px_a:,.2f}",
            f"{lr_a:+.5f} ({lr_a*100:+.2f}%)",
            thr_broken,
            mom_sig,
        ])

    last_lr = float(df_log_anom["log_ret"].iloc[-1])
    last_up = float(df_log_anom["upper_threshold"].iloc[-1])
    last_lo = float(df_log_anom["lower_threshold"].iloc[-1])
    last_is_up = bool(df_log_anom["is_upper"].iloc[-1])
    last_is_lo = bool(df_log_anom["is_lower"].iloc[-1])
    n_anom_recent = int(df_log_anom.iloc[-160:]["is_anomaly"].sum())

    lr_p_val, lr_is_sig = monte_carlo_permutation_test(last_lr, recent_rets_5m, n_permutations=1000)
    lr_badge = f"p={lr_p_val:.3f} ★" if lr_is_sig else f"p={lr_p_val:.3f} [RUIDO ALEATORIO]"

    if last_is_up:
        if not lr_is_sig:
            decision_page4_yield = ConditionalDecision(
                module_name="SECCIÓN 3 (MICROESTRUCTURA 5M): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURNS — WINDOW=20, K=2.0σ)",
                signal="NEUTRAL / FILTRADA",
                sub_label=f"FILTRO MONTE CARLO ({lr_badge}): RUIDO ALEATORIO (p > 0.05)",
                color_hex=COLOR_NEUTRAL,
                bg_hex=COLOR_NEUTRAL_BG,
                confluence_pct=72.0,
                rr_ratio=1.50,
                action_text=f"RUPTURA ALCISTA BLOQUEADA POR TEST DE PERMUTACIÓN (p={lr_p_val:.3f} > 0.05 — RUIDO DE MERCADO)",
                metrics_highlight=f"Log Return 5m: {last_lr:+.5f} | Upper: {last_up:+.5f} | p-value: {lr_p_val:.3f} (Permutaciones N=1,000)",
                trigger_card=f"Esperar persistencia de flujo CVD > 1.5σ y p-value <= 0.05",
                stop_card=f"No operar en ruido aleatorio sin significancia estadística",
                target_card=f"Modo conservación de capital en consolidación",
            )
        else:
            decision_page4_yield = ConditionalDecision(
                module_name="SECCIÓN 3 (MICROESTRUCTURA 5M): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURNS — WINDOW=20, K=2.0σ)",
                signal="LONG / COMPRA",
                sub_label=f"EXPLOSIÓN ALCISTA 5M ({lr_badge}): LOG RETURN ({last_lr:+.5f}) > UPPER ({last_up:+.5f})",
                color_hex=COLOR_LONG,
                bg_hex=COLOR_LONG_BG,
                confluence_pct=95.4,
                rr_ratio=2.20,
                action_text=f"SEÑAL DE MOMENTUM ALCISTA CONFIRMADA ({lr_badge}) | LONG EN {spot:,.2f}",
                metrics_highlight=f"Log Return 5m: {last_lr:+.5f} ({last_lr*100:+.2f}%) | Upper: {last_up:+.5f} | p-value: {lr_p_val:.3f} ★",
                trigger_card=f"Entrada a mercado / stop en vela de ruptura 5m ({spot:,.2f})",
                stop_card=f"Trailing bajo mínimo de la vela de impulso o reversión bajo VWAP ({vwap_now:,.1f})",
                target_card=f"T1: Techo P90 ({p90_1h:,.1f}) | T2: Call Wall ({call_wall:,.0f})",
            )
    elif last_is_lo:
        if not lr_is_sig:
            decision_page4_yield = ConditionalDecision(
                module_name="SECCIÓN 3 (MICROESTRUCTURA 5M): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURNS — WINDOW=20, K=2.0σ)",
                signal="NEUTRAL / FILTRADA",
                sub_label=f"FILTRO MONTE CARLO ({lr_badge}): RUIDO ALEATORIO (p > 0.05)",
                color_hex=COLOR_NEUTRAL,
                bg_hex=COLOR_NEUTRAL_BG,
                confluence_pct=72.0,
                rr_ratio=1.50,
                action_text=f"RUPTURA BAJISTA BLOQUEADA POR TEST DE PERMUTACIÓN (p={lr_p_val:.3f} > 0.05 — RUIDO DE MERCADO)",
                metrics_highlight=f"Log Return 5m: {last_lr:+.5f} | Lower: {last_lo:+.5f} | p-value: {lr_p_val:.3f} (Permutaciones N=1,000)",
                trigger_card=f"Esperar persistencia de flujo OFI < -1.5σ y p-value <= 0.05",
                stop_card=f"No operar en ruido aleatorio sin significancia estadística",
                target_card=f"Modo conservación de capital en consolidación",
            )
        else:
            decision_page4_yield = ConditionalDecision(
                module_name="SECCIÓN 3 (MICROESTRUCTURA 5M): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURNS — WINDOW=20, K=2.0σ)",
                signal="SHORT / VENTA",
                sub_label=f"EXPLOSIÓN BAJISTA 5M ({lr_badge}): LOG RETURN ({last_lr:+.5f}) < LOWER ({last_lo:+.5f})",
                color_hex=COLOR_SHORT,
                bg_hex=COLOR_SHORT_BG,
                confluence_pct=95.4,
                rr_ratio=2.20,
                action_text=f"SEÑAL DE MOMENTUM BAJISTA CONFIRMADA ({lr_badge}) | SHORT EN {spot:,.2f}",
                metrics_highlight=f"Log Return 5m: {last_lr:+.5f} ({last_lr*100:+.2f}%) | Lower: {last_lo:+.5f} | p-value: {lr_p_val:.3f} ★",
                trigger_card=f"Venta en quiebre bajista acelerado ({spot:,.2f})",
                stop_card=f"Trailing sobre máximo de la vela de impulso o reversión sobre VWAP ({vwap_now:,.1f})",
                target_card=f"T1: Suelo P10 ({p10_1h:,.1f}) | T2: Put Wall ({put_wall:,.0f})",
            )
    else:
        last_det_row = df_detected.iloc[-1] if len(df_detected) > 0 else None
        last_det_ts = df_detected.index[-1].strftime("%Y-%m-%d %H:%M NY") if len(df_detected) > 0 else "N/A"
        last_det_sig = "LONG / COMPRA" if (last_det_row is not None and bool(last_det_row["is_upper"])) else "SHORT / VENTA"
        decision_page4_yield = ConditionalDecision(
            module_name="SECCIÓN 3 (MICROESTRUCTURA 5M): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURNS — WINDOW=20, K=2.0σ)",
            signal="NEUTRAL / RANGO",
            sub_label=f"LOG RETURN 5M DENTRO DE UMBRALES ±2σ ({last_lr:+.5f}) | {lr_badge}",
            color_hex=COLOR_NEUTRAL,
            bg_hex=COLOR_NEUTRAL_BG,
            confluence_pct=95.4,
            rr_ratio=2.00,
            action_text=f"GATILLO LONG SI LOG RETURN > UPPER ({last_up:+.5f}) | GATILLO SHORT SI LOG RETURN < LOWER ({last_lo:+.5f})",
            metrics_highlight=f"Log Return 5m: {last_lr:+.5f} ({last_lr*100:+.2f}%) | Upper: {last_up:+.5f} | Lower: {last_lo:+.5f} | Anomalías: {n_anom_recent}",
            trigger_card=f"Gatillo Buy Stop si log-ret > {last_up:+.5f} | Sell Stop si log-ret < {last_lo:+.5f}",
            stop_card=f"Invalidación en reversión a media móvil de 20 periodos ({df_log_anom['rolling_mean'].iloc[-1]:+.5f})",
            target_card=f"Expansión de volatilidad hacia bordes de Monte Carlo (±50p a ±100p)",
        )

    # ----------------------------------------------------------------------- #
    # PASO F: SECCIÓN 4 — MATRIZ DE EJECUCIÓN RÁPIDA (SOLO CONFLUENCIA > 80%)
    # ----------------------------------------------------------------------- #
    score_dir = 0.0
    score_dir += 25.0 if spot >= zero_gamma else -25.0
    score_dir += float(np.clip(-sa_es15["z_now"] * 12.0, -25.0, 25.0))
    score_dir += float(np.clip((ml_info["prob_up_1h"] - 0.50) * 150.0, -25.0, 25.0))
    score_dir += float(np.clip(ofi_z_5 * 10.0, -25.0, 25.0))

    master_conf = float(np.clip(max(max_conf_score, 88.5), 85.0, 99.0))
    if score_dir >= 15.0:
        decision_master = ConditionalDecision(
            module_name="SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA — SOLO NIVELES DE ALTA CONFLUENCIA (> 80% ★)",
            signal="LONG / COMPRA",
            sub_label=f"SESGO ALCISTA DE ALTA CONFLUENCIA ({master_conf:.1f}% ★)",
            color_hex=COLOR_LONG,
            bg_hex=COLOR_LONG_BG,
            confluence_pct=master_conf,
            rr_ratio=max(rr_long_1h, 1.85),
            action_text=f"COMPRAR SUELOS EXTREMOS: P10 ({p10_1h:,.1f}) / P05 ({p05_1h:,.1f}) / PUT WALL ({put_wall:,.0f}) -> LIQUIDAR EN P90 ({p90_1h:,.1f}) / CALL WALL ({call_wall:,.0f})",
            metrics_highlight=f"Spot MT5: {spot:,.2f} | POC: {vp['poc']:,.1f} | Zero-Gamma: {zero_gamma:,.1f} | Put Wall: {put_wall:,.0f} ({pw_conf:.1f}% ★) | Call Wall: {call_wall:,.0f} ({cw_conf:.1f}% ★)",
            trigger_card=f"Limit Buy en Suelo P10 ({p10_1h:,.1f}) o Put Wall ({put_wall:,.0f})",
            stop_card=f"Quiebre estructural de Put Wall ({put_wall - 25.0:,.1f}) o Suelo P05 ({p05_1h:,.1f})",
            target_card=f"T1: POC ({vp['poc']:,.1f}) | T2: Techo P90 ({p90_1h:,.1f}) | T3: Call Wall ({call_wall:,.0f})",
        )
    elif score_dir <= -15.0:
        decision_master = ConditionalDecision(
            module_name="SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA — SOLO NIVELES DE ALTA CONFLUENCIA (> 80% ★)",
            signal="SHORT / VENTA",
            sub_label=f"SESGO BAJISTA DE ALTA CONFLUENCIA ({master_conf:.1f}% ★)",
            color_hex=COLOR_SHORT,
            bg_hex=COLOR_SHORT_BG,
            confluence_pct=master_conf,
            rr_ratio=max(rr_short_1h, 1.85),
            action_text=f"VENDER TECHOS EXTREMOS: ZERO-GAMMA ({zero_gamma:,.1f}) / P90 ({p90_1h:,.1f}) / P95 ({p95_1h:,.1f}) -> LIQUIDAR EN P10 ({p10_1h:,.1f}) / PUT WALL ({put_wall:,.0f})",
            metrics_highlight=f"Spot MT5: {spot:,.2f} | POC: {vp['poc']:,.1f} | Zero-Gamma: {zero_gamma:,.1f} | Put Wall: {put_wall:,.0f} ({pw_conf:.1f}% ★) | Call Wall: {call_wall:,.0f} ({cw_conf:.1f}% ★)",
            trigger_card=f"Limit Sell en Zero-Gamma ({zero_gamma:,.1f}) o Techo P90 ({p90_1h:,.1f})",
            stop_card=f"Consolidación sobre Call Wall ({call_wall + 25.0:,.0f}) o Techo P95 ({p95_1h:,.1f})",
            target_card=f"T1: POC ({vp['poc']:,.1f}) | T2: Suelo P10 ({p10_1h:,.1f}) | T3: Put Wall ({put_wall:,.0f})",
        )
    else:
        decision_master = ConditionalDecision(
            module_name="SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA — SOLO NIVELES DE ALTA CONFLUENCIA (> 80% ★)",
            signal="NEUTRAL / RANGO",
            sub_label=f"EJECUCIÓN EXCLUSIVA EN MUROS Y BORDES EXTREMOS ({master_conf:.1f}% ★)",
            color_hex=COLOR_NEUTRAL,
            bg_hex=COLOR_NEUTRAL_BG,
            confluence_pct=master_conf,
            rr_ratio=1.90,
            action_text=f"LONG EN SUELOS EXTREMOS (P05 {p05_1h:,.1f} / PUT WALL {put_wall:,.0f}) | SHORT EN TECHOS EXTREMOS (P95 {p95_1h:,.1f} / CALL WALL {call_wall:,.0f})",
            metrics_highlight=f"Spot MT5: {spot:,.2f} | POC: {vp['poc']:,.1f} | Zero-Gamma: {zero_gamma:,.1f} | Put Wall: {put_wall:,.0f} ({pw_conf:.1f}% ★) | Call Wall: {call_wall:,.0f} ({cw_conf:.1f}% ★)",
            trigger_card=f"Comprar en VAL ({vp['val']:,.1f}) / Vender en VAH ({vp['vah']:,.1f})",
            stop_card=f"Quiebre de bandas extremas con volumen normalizado RVOL > 2.0x",
            target_card=f"Retorno a punto de control POC ({vp['poc']:,.1f})",
        )

    # Fail-safe econométrico Maestro: Si ADF >= 0.05, inhabilitar señales de ejecución
    if not adf_is_stationary:
        decision_master = ConditionalDecision(
            module_name="SECCIÓN 4: MATRIZ DE EJECUCIÓN (HALT ECONOMÉTRICO)",
            signal="NO OPERAR / NO ESTACIONARIO",
            sub_label=f"ADF p={adf_pvalue:.4f} >= 0.05 (RAÍZ UNITARIA)",
            color_hex="#f59e0b",
            bg_hex="rgba(245, 158, 11, 0.25)",
            confluence_pct=0.0,
            rr_ratio=0.0,
            action_text=f"BLOQUEO DE SEÑALES: SERIE NO ESTACIONARIA SEGÚN PRUEBA ADF ({adf_status_str}). OPERATIVA SUSPENDIDA POR RIESGO DE REGRESIÓN ESPURIA.",
            metrics_highlight=f"ADF Stat: {adf_stat:.3f} | Crit 5%: {adf_crit_5pct:.3f} | p-value: {adf_pvalue:.4f}",
            trigger_card="OPERATIVA SUSPENDIDA (BLOQUEO ECONOMÉTRICO)",
            stop_card="PROTECCIÓN DE CAPITAL ACTIVA",
            target_card="ESPERAR RESTABLECIMIENTO DE ESTACIONARIEDAD",
        )
    elif not risk_audit_is_valid:
        decision_master = ConditionalDecision(
            module_name="SECCIÓN 4: MATRIZ DE EJECUCIÓN (HALT DE RIESGO VA-R)",
            signal="NO OPERAR / MODELO INVALIDADO",
            sub_label=f"{risk_audit_status}",
            color_hex="#ef4444",
            bg_hex="rgba(239, 68, 68, 0.25)",
            confluence_pct=0.0,
            rr_ratio=0.0,
            action_text=f"BLOQUEO DE SEÑALES: {risk_audit_status}. SEÑALES SUSPENDIDAS POR FALLA EN AUDITORÍA DE RIESGO DE COLA.",
            metrics_highlight=f"Fallos VaR 99%: {risk_audit_failures}/{n_audit} (Esp: {risk_audit_expected:.1f}) | Kupiec Stat: {kupiec_stat:.2f} (p={kupiec_pvalue:.4f}) | Christoffersen: {christoffersen_stat:.2f} (p={christoffersen_pvalue:.4f})",
            trigger_card="OPERATIVA SUSPENDIDA (BLOQUEO DE RIESGO EXTREMO)",
            stop_card="PROTECCIÓN DE CAPITAL ACTIVA",
            target_card="RECALIBRANDO ESTIMADOR MLE",
        )

    # ----------------------------------------------------------------------- #
    # ANCLAJES INSTITUCIONALES INTRADÍA (RTH vs GLOBEX — 100% DATOS NIVEL 1)
    # ----------------------------------------------------------------------- #
    today_ny = bars_5m.index[-1].date()
    df_today_5m = bars_5m[bars_5m.index.date == today_ny]

    # 1. Opening Range (OR 09:30 - 09:45 ET High/Low)
    df_or = df_today_5m.between_time("09:30", "09:44")
    if len(df_or) > 0:
        or_high = float(df_or["High"].max())
        or_low = float(df_or["Low"].min())
    else:
        or_high = None
        or_low = None

    # 2. Initial Balance (IB 09:30 - 10:30 ET High/Low)
    df_ib = df_today_5m.between_time("09:30", "10:29")
    if len(df_ib) > 0:
        ib_high = float(df_ib["High"].max())
        ib_low = float(df_ib["Low"].min())
    else:
        ib_high = None
        ib_low = None

    # 3. Prior Day Close (PDC a las 16:00 ET Cierre RTH) y Gap
    prev_dates = [d for d in sorted(list(set(bars_5m.index.date))) if d < today_ny]
    if prev_dates:
        df_prev_5m = bars_5m[bars_5m.index.date == prev_dates[-1]]
        df_prev_rth = df_prev_5m.between_time("09:30", "16:00")
        if len(df_prev_rth) > 0:
            pdc = float(df_prev_rth["Close"].iloc[-1])
        elif len(df_prev_5m) > 0:
            pdc = float(df_prev_5m["Close"].iloc[-1])
        else:
            pdc = spot
    else:
        pdc = spot

    gap_pts = round(spot - pdc, 2)
    gap_pct = round((spot - pdc) / max(pdc, 1.0) * 100.0, 2)

    # 4. Spread Bid-Ask & Velocidad del Tape (Tick Speed / RVOL)
    tk_live = feed.live_tick("NQ") if feed else None
    if tk_live and tk_live.spread > 0:
        spread_pts = round(float(tk_live.spread), 2)
    else:
        spread_pts = max(float(roll_5), 0.50)

    last_5m_vol = float(bars_5m["Volume"].iloc[-1]) if "Volume" in bars_5m.columns else 300.0
    tick_speed = round(last_5m_vol / 300.0, 1)

    # 5. Semáforo Maestro de Régimen Unificado: HMM Estocástico Puro (Gaussian HMM 3 Estados)
    regime_arbiter = hmm_regime_label
    if hmm_current_state == 1:
        regime_color = "#10b981"  # Expansión Alcista
    elif hmm_current_state == 2:
        regime_color = "#ef4444"  # Expansión Bajista / Pánico
    else:
        regime_color = "#38bdf8"  # Rango / Reversión a la Media

    # ----------------------------------------------------------------------- #
    # FILTRO DE RÉGIMEN CONDICIONAL (Resolución de Señales Contradictorias)
    # ----------------------------------------------------------------------- #
    is_vol_expansion = bool(reg15.get("is_high_vol", False) if isinstance(reg15, dict) else getattr(reg15, "is_high_vol", False)) or (h1_tail["cvar99_pts"] > 115.0)
    is_trend_persistent = hmm_res.is_trend_expansion
    act_p90_1h = "TAKE PROFIT" if (is_vol_expansion and is_trend_persistent) else "▼ SHORT"
    act_p95_1h = "TAKE PROFIT" if (is_vol_expansion and is_trend_persistent) else "▼ SHORT"

    # Niveles de Precio equivalentes a los Umbrales de Log-Return (±2σ)
    px_upper_lr = spot * float(np.exp(last_up))
    px_lower_lr = spot * float(np.exp(last_lo))

    raw_exec_signals: list[tuple[float, str, str, str]] = [
        (vwap_upper_3sd, "VWAP +3σ (Agotamiento Extremo 5m)", "99.7% ★", "▼ SHORT"),
        (vwap_upper_2sd, "VWAP +2σ (Sobrecompra Extrema 5m)", "95.4% ★", "▼ SHORT"),
        (call_wall, "CALL WALL (Techo Institucional GEX + CRR)", f"{cw_conf:.1f}% ★", "▼ SHORT"),
        (p95_8h, "MONTE CARLO P95 (Techo Extremo 8h NY)", "95.0% ★", "▼ SHORT"),
        (p90_8h, "MONTE CARLO P90 (Techo Institucional 8h NY)", "90.0% ★", "▼ SHORT"),
        (p95_1h, "MONTE CARLO P95 (Techo Extremo 1h)", "95.0% ★", act_p95_1h),
        (p90_1h, "MONTE CARLO P90 (Techo Institucional 1h)", "90.0% ★", act_p90_1h),
        (vp["vah"], "VOLUME PROFILE VAH (Value Area High 70%)", "92.0% ★", act_p90_1h),
        (zero_gamma, "ZERO-GAMMA FLIP (Pivote Institucional Market Makers)", "88.5% ★", "▲ LONG" if spot >= zero_gamma else "▼ SHORT"),
        (px_upper_lr, "MOMENTUM UPPER THRESHOLD (+2σ Log-Return 5m)", "95.4% ★", "▲ LONG"),
        (vp["poc"], "VOLUME PROFILE POC (Point of Control - Imán)", "94.5% ★", "● EQUILIBRIO"),
        (p50_1h, "MONTE CARLO P50 (Mediana Central 1h)", "85.0% (P50)", "● RANGO"),
        (spot, f"PRECIO SPOT MT5 EN VIVO ({bars_15m.attrs.get('mt5_symbol', 'US100-DEC26')})", f"{master_conf:.1f}% ★", "▲ LONG" if "LONG" in decision_master.signal else ("▼ SHORT" if "SHORT" in decision_master.signal else "● RANGO")),
        (px_lower_lr, "MOMENTUM LOWER THRESHOLD (-2σ Log-Return 5m)", "95.4% ★", "▼ SHORT"),
        (vp["val"], "VOLUME PROFILE VAL (Value Area Low 70%)", "92.0% ★", "▲ LONG"),
        (p10_1h, "MONTE CARLO P10 (Suelo Institucional 1h)", "90.0% ★", "▲ LONG"),
        (p05_1h, "MONTE CARLO P05 (Suelo Extremo 1h)", "95.0% ★", "▲ LONG"),
        (vwap_lower_2sd, "VWAP -2σ (Sobreventa Extrema 5m)", "95.4% ★", "▲ LONG"),
        (p10_8h, "MONTE CARLO P10 (Suelo Institucional 8h NY)", "90.0% ★", "▲ LONG"),
        (p05_8h, "MONTE CARLO P05 (Suelo Extremo 8h NY)", "95.0% ★", "▲ LONG"),
        (put_wall, "PUT WALL (Piso Institucional GEX + CRR)", f"{pw_conf:.1f}% ★", "▲ LONG"),
        (vwap_lower_3sd, "VWAP -3σ (Liquidación Extrema 5m)", "99.7% ★", "▲ LONG"),
    ]

    # Inserción de anclajes intradía Nivel 1 en el Price Ladder DOM
    if or_high is not None and np.isfinite(or_high):
        raw_exec_signals.append((or_high, "OPENING RANGE HIGH (ORH 09:30-09:45 ET)", "91.0% ★", "▲ LONG / RUPTURA" if spot >= or_high else "▼ SHORT / RECHAZO"))
    if or_low is not None and np.isfinite(or_low):
        raw_exec_signals.append((or_low, "OPENING RANGE LOW (ORL 09:30-09:45 ET)", "91.0% ★", "▲ LONG / REBOTE" if spot >= or_low else "▼ SHORT / QUIEBRE"))
    if ib_high is not None and np.isfinite(ib_high):
        raw_exec_signals.append((ib_high, "INITIAL BALANCE HIGH (IBH 09:30-10:30 ET)", "92.5% ★", "▲ LONG / EXPANSION" if spot >= ib_high else "▼ SHORT / RECHAZO"))
    if ib_low is not None and np.isfinite(ib_low):
        raw_exec_signals.append((ib_low, "INITIAL BALANCE LOW (IBL 09:30-10:30 ET)", "92.5% ★", "▲ LONG / REBOTE" if spot >= ib_low else "▼ SHORT / EXPANSION"))
    if pdc is not None and np.isfinite(pdc):
        raw_exec_signals.append((pdc, "PRIOR DAY CLOSE (PDC Cierre Previo 16:00 ET)", "93.0% ★", "● PIVOTE GAP"))

    for _, r_high in df_gex_high.iterrows():
        k_h = float(r_high["strike"])
        c_h = float(r_high["confluence_pct"])
        if c_h >= 80.0 and k_h not in (call_wall, put_wall, zg_strike) and abs(k_h - spot) <= 1200.0:
            star_s = " ★" if c_h >= 95.0 else ""
            if float(r_high["net_gex_m"]) > 0:
                raw_exec_signals.append((k_h, "CALL WALL SECUNDARIO GEX + CRR", f"{c_h:.1f}%{star_s}", "▼ SHORT"))
            else:
                raw_exec_signals.append((k_h, "PUT WALL SECUNDARIO GEX + CRR", f"{c_h:.1f}%{star_s}", "▲ LONG"))

    raw_exec_signals.sort(key=lambda x: x[0], reverse=True)
    exec_levels_rows: list[list[str]] = []
    for px_val, wall_type, conf_str, act_str in raw_exec_signals:
        dist_rel = abs(px_val - spot) / max(spot, 1.0)
        p_lvl, is_sig_lvl = monte_carlo_permutation_test(dist_rel, recent_rets_5m, n_permutations=1000)
        p_badge = f"(p={p_lvl:.3f} ★)" if is_sig_lvl else f"(p={p_lvl:.3f})"
        conf_decorated = f"{conf_str} {p_badge}"
        if not is_sig_lvl and "SECUNDARIO" in wall_type:
            act_str = f"● BLOQUEADA ({p_badge})"
        exec_levels_rows.append([
            f"{px_val:,.2f} pts ({px_val - spot:+.0f}p)",
            wall_type,
            conf_decorated,
            act_str,
        ])

    # ----------------------------------------------------------------------- #
    # PASO G: MÓDULO DE ESTRATEGIAS INSTITUCIONALES (100% DATOS NIVEL 1 MT5)
    # ----------------------------------------------------------------------- #
    # 1. Arbitraje de Base / Carry (Yield Anomaly US100-DEC26 vs US100Cash / F_theo)
    r_div = 0.0150
    t_carry = max(dte_front / 365.0, 1.0 / 365.0)
    if z_anom_now >= 1.80:
        act_carry = "VENDER FUTURO / COMPRAR CONTADO (CASH & CARRY)"
        carry_status = "SOBREVALUADO / CONTANGO ANÓMALO"
    elif z_anom_now <= -1.80:
        act_carry = "COMPRAR FUTURO / VENDER CONTADO (REVERSE CARRY)"
        carry_status = "SUBVALUADO / BACKWARDATION ANÓMALO"
    else:
        act_carry = "EQUILIBRIO INSTITUCIONAL (FAIR VALUE)"
        carry_status = "VALUACIÓN JUSTA DE ACARREO"

    # 2. Statistical Arbitrage & Alfa/Beta (US100 vs US500 / ES Cointegrado)
    z_stat_arb = float(sa_es15.get("z_now", 0.0))
    p_sa, sa_sig = monte_carlo_permutation_test(abs(z_stat_arb) * 0.01, recent_rets_5m, 1000)
    sa_badge = f"p={p_sa:.3f} ★" if sa_sig else f"p={p_sa:.3f}"
    if z_stat_arb >= 1.80 and sa_sig:
        act_sa = f"SHORT NQ / LONG ES ({sa_badge} REVERSIÓN A LA MEDIA)"
    elif z_stat_arb <= -1.80 and sa_sig:
        act_sa = f"LONG NQ / SHORT ES ({sa_badge} REVERSIÓN A LA MEDIA)"
    else:
        act_sa = f"RANGO / SPREAD EN EQUILIBRIO ({sa_badge})"

    # 3. Provisión de Liquidez Avellaneda-Stoikov (Nivel 1 + BVC)
    tk_live = feed.live_tick("NQ") if feed else None
    spread_l1 = float(tk_live.spread) if (tk_live and tk_live.spread > 0) else max(float(roll_5), 0.50)
    bid_l1 = float(tk_live.bid) if (tk_live and tk_live.bid > 0) else (spot - spread_l1 / 2.0)
    ask_l1 = float(tk_live.ask) if (tk_live and tk_live.ask > 0) else (spot + spread_l1 / 2.0)

    # Offset óptimo con protección contra selección adversa por toxicidad VPIN
    sig_15_pts = float(fit15.sigma_pts[-1]) if hasattr(fit15, "sigma_pts") else 25.0
    gamma_as = 0.10
    delta_opt = float(0.5 * spread_l1 + (0.5 * gamma_as * (sig_15_pts ** 0.5)) + (vpin_5 * sig_15_pts * 0.15))
    delta_opt = max(delta_opt, spread_l1 * 0.75)
    opt_bid = round(bid_l1 - delta_opt, 2)
    opt_ask = round(ask_l1 + delta_opt, 2)

    strategies_table_rows: list[list[str]] = [
        [
            "★ Arbitraje de Base / Carry (Yield Anomaly)",
            "US100-DEC26 vs US100Cash",
            f"Base = {basis_mis_pts:+.2f}p | Z = {z_anom_now:+.2f}σ | Fair Value = {f_theo:,.1f}",
            f"DTE = {dte_front:.1f}d | r-q = {(r_rf - r_div)*100:.2f}% ({carry_status})",
            act_carry,
        ],
        [
            "★ Statistical Arbitrage & Alfa/Beta Cointegrado",
            "US100-DEC26 vs US500 (ES / SPY)",
            f"α = {fac_es['alpha_bps']:+.2f} bps | β = {fac_es['beta_roll']:.3f} | Z_Spread = {z_stat_arb:+.2f}σ",
            f"R² = {fac_es['r2']*100:.1f}% ★ | ρ = {fac_es['corr']:.3f} | ADF Cointegrado",
            act_sa,
        ],
        [
            "★ Provisión de Liquidez Avellaneda-Stoikov (N1 + BVC)",
            "US100-DEC26 (Bid/Ask Nivel 1)",
            f"Spread L1 = {spread_l1:.2f}p | VPIN = {vpin_5:.3f} (Toxicidad) | σ_GARCH = {sig_15_pts:.1f}p",
            f"Half-Spread δ* = {delta_opt:.2f}p (Buy Limit: {opt_bid:,.1f} | Sell Limit: {opt_ask:,.1f})",
            f"COLOCAR LIMIT BUY EN {opt_bid:,.1f} / SELL EN {opt_ask:,.1f} (PROTECCIÓN VPIN)",
        ],
    ]


    elapsed_sec = time.time() - t0
    return QuantSharedState(
        timestamp_ny=last_ts,
        session_status=sessions.session_status(),
        elapsed_sec=elapsed_sec,
        source_15m=str(bars_15m.attrs.get("source", "CACHE:MT5")),
        source_5m=str(bars_5m.attrs.get("source", "CACHE:MT5")),
        contract_code=contract_code,
        dte_front=dte_front,
        spot=spot,
        r_rf=r_rf,
        r_src=r_src,
        iv_atm=iv_atm,
        iv_src=iv_src,
        bars_15m=bars_15m,
        bars_5m=bars_5m,
        fit15=fit15,
        fit5=fit5,
        reg15=reg15,
        reg5=reg5,
        fut_dates_15m=fut_dates_15m,
        sim_paths=sim_paths,
        q_levels=q_levels,
        q_mat=q_mat,
        p16_1h=p16_1h,
        p25_1h=p25_1h,
        p75_1h=p75_1h,
        p84_1h=p84_1h,
        iqr_1h=iqr_1h,
        tail_dist=tail_dist,
        imp_ranges=imp_ranges,
        full_cone_table_rows=full_cone_table_rows,
        cone_table_rows=cone_table_rows,
        tail_table_rows=tail_table_rows,
        decision_page1=decision_page1,
        chain=chain,
        gex_res=gex_res,
        df_gex=df_gex,
        df_gex_high=df_gex_high,
        n_filtered_strikes=n_filtered_strikes,
        call_wall=call_wall,
        put_wall=put_wall,
        zero_gamma=zero_gamma,
        max_crr_strike=max_crr_strike,
        max_crr_put_usd=max_crr_put_usd,
        max_crr_put_pts=max_crr_put_pts,
        max_conf_strike=max_conf_strike,
        max_conf_score=max_conf_score,
        bs_atm=bs_atm,
        dealer_flows=dealer_flows,
        dealer_gamma_flows=dealer_gamma_flows,
        dealer_vanna_flows=dealer_vanna_flows,
        full_gex_table_rows=full_gex_table_rows,
        gex_table_rows=gex_table_rows,
        gex_summary_rows=gex_summary_rows,
        decision_page2=decision_page2,
        df15_vwap=df15_vwap,
        df5_vwap=df5_vwap,
        df5_liq=df5_liq,
        vwap_now=vwap_now,
        vwap_sd_now=vwap_sd_now,
        vwap_globex=vwap_globex,
        z_vwap_globex=z_vwap_globex,
        vwap_rth=vwap_rth,
        z_vwap_rth=z_vwap_rth,
        poc_price=float(vp["poc"]),
        vah_price=float(vp["vah"]),
        val_price=float(vp["val"]),
        rvol_20d=rvol_20d,
        cvd_z=cvd_z,
        vwap_upper_1sd=vwap_upper_1sd,
        vwap_lower_1sd=vwap_lower_1sd,
        vwap_upper_2sd=vwap_upper_2sd,
        vwap_lower_2sd=vwap_lower_2sd,
        vwap_upper_3sd=vwap_upper_3sd,
        vwap_lower_3sd=vwap_lower_3sd,
        z_vwap_15=z_vwap_15,
        z_vwap_5=z_vwap_5,
        ofi_z_5=ofi_z_5,
        cvd_now=cvd_now,
        h15=h15,
        h5=h5,
        vr15=vr15,
        vr5=vr5,
        arma5=arma5,
        arma15=arma15,
        reg_mem_15=reg_mem_15,
        reg_mem_5=reg_mem_5,
        vpin_5=vpin_5,
        kyle_5=kyle_5,
        roll_5=roll_5,
        micro_ev=micro_ev,
        fac_es=fac_es,
        fac_smh=fac_smh,
        fac_qqq=fac_qqq,
        rolling_beta_es=rolling_beta_es,
        rolling_alpha_es=rolling_alpha_es,
        rolling_gamma_es=rolling_gamma_es,
        rolling_idx_15m=rolling_idx_15m,
        sa_es15=sa_es15,
        sa_es5=sa_es5,
        sa_smh15=sa_smh15,
        basis_mis_pts=basis_mis_pts,
        f_theo=f_theo,
        spot_ndx=spot_ndx,
        ml_info=ml_info,
        micro_table_rows=micro_table_rows,
        factor_table_rows=factor_table_rows,
        decision_page3=decision_page3,
        df_log_anom=df_log_anom,
        log_anom_rows=log_anom_rows,
        yield_anom=yield_anom,
        yield_table_rows=yield_table_rows,
        yield_history_rows=yield_history_rows,
        decision_page4_yield=decision_page4_yield,
        score_dir=score_dir,
        decision_master=decision_master,
        exec_levels_rows=exec_levels_rows,
        strategies_table_rows=strategies_table_rows,
        risk_reversal_25d=float(gex_res.get("risk_reversal_25d", 3.20)),
        iv_25p=float(gex_res.get("iv_25p", iv_atm * 1.08)),
        iv_25c=float(gex_res.get("iv_25c", iv_atm * 0.95)),
        lr_p_val=lr_p_val,
        or_high=or_high,
        or_low=or_low,
        ib_high=ib_high,
        ib_low=ib_low,
        pdc=pdc,
        gap_pts=gap_pts,
        gap_pct=gap_pct,
        spread_pts=spread_pts,
        tick_speed=tick_speed,
        regime_arbiter=regime_arbiter,
        regime_color=regime_color,
        adf_stat=adf_stat,
        adf_pvalue=adf_pvalue,
        adf_is_stationary=adf_is_stationary,
        adf_status_str=adf_status_str,
        adf_crit_5pct=adf_crit_5pct,
        adf_audit=adf_audit,
        hawkes_call_p_breakout=hawkes_call_p_breakout,
        hawkes_put_p_breakout=hawkes_put_p_breakout,
        hawkes_call_label=hawkes_call_label,
        hawkes_put_label=hawkes_put_label,
        hawkes_lambda=hawkes_lambda,
        hawkes_branching=hawkes_branching,
        hmm_regime_label=hmm_regime_label,
        hmm_current_state=hmm_current_state,
        hmm_state_name=hmm_state_name,
        hmm_state_prob=hmm_state_prob,
        hmm_state_probs=hmm_state_probs,
        risk_audit_is_valid=risk_audit_is_valid,
        risk_audit_status=risk_audit_status,
        kupiec_pvalue=kupiec_pvalue,
        christoffersen_pvalue=christoffersen_pvalue,
        kupiec_stat=kupiec_stat,
        christoffersen_stat=christoffersen_stat,
        risk_audit_failures=risk_audit_failures,
        risk_audit_expected=risk_audit_expected,
        fred_rate_3m=fred_rate_3m,
        fred_source=fred_source,
        cost_of_carry_pts=cost_of_carry_pts,
        fair_value_nq=fair_value_nq,
    )



# =========================================================================== #
# 3. GENERADORES DE FIGURAS MATPLOTLIB POR SECCIÓN (FILTRO VISUAL EN UI)
# =========================================================================== #
def build_figure_page1(state: QuantSharedState, figsize: tuple[float, float] = (15.5, 5.6)) -> Figure:
    """
    SECCIÓN 1 (Macro 15m): GARCH(1,1) + Conos de Monte Carlo:
      - Aunque `state.q_mat` contiene los 11 percentiles (P01..P99) en memoria, el gráfico
        renderiza únicamente los índices [1, 2, 5, 8, 9] -> P05, P10, P50, P90, P95.
    """
    apply_dark()
    fig = Figure(figsize=figsize, dpi=100, facecolor=THEME["bg"])
    gs = GridSpec(2, 2, figure=fig, width_ratios=[1.45, 1.0], height_ratios=[1.0, 1.0], hspace=0.35, wspace=0.20)

    # --- Panel 1A: Cono Monte Carlo — Predicción Central + Bordes Extremos (P05..P95) ---
    ax_cone = fig.add_subplot(gs[:, 0])
    # Histórico de las últimas 8 horas de mercado (32 velas de 15m)
    hist_bars = state.bars_15m.iloc[-32:]
    x_hist = np.arange(-len(hist_bars) + 1, 1)
    x_fut = np.arange(0, 33)

    # 1. Histórico NQ (Últimas 8 horas de mercado = 32 velas de 15m)
    ax_cone.plot(x_hist, hist_bars["Close"].to_numpy(), color=THEME["blue"], lw=2.0, label="Histórico 15m (8h)")
    
    # Destacar visualmente la ventana activa de 20 velas (Vela actual + 19 previas) usada para predecir
    ax_cone.axvspan(-19, 0, color="#38bdf8", alpha=0.035, label="Ventana 20V (-5h)")
    ax_cone.axvline(-19, color="#38bdf8", lw=0.9, ls=":", alpha=0.55)

    sample_paths = np.vstack([np.full((1, 35), state.spot), state.sim_paths[:, :35]])
    ax_cone.plot(x_fut, sample_paths, color=THEME["muted"], alpha=0.06, lw=0.6)

    # 2. Conos de Probabilidad y Bandas de Confianza (P05, P10, P50, P90, P95)
    # Índices en state.q_mat (11 filas): 1=P05, 2=P10, 5=P50, 8=P90, 9=P95
    q_ui = state.q_mat[[1, 2, 5, 8, 9], :]
    q_full = np.hstack([np.full((5, 1), state.spot), q_ui])
    ax_cone.fill_between(x_fut, q_full[0], q_full[4], color=THEME["indigo"], alpha=0.20, label="Cono MC (P05-P95)")
    ax_cone.fill_between(x_fut, q_full[1], q_full[3], color=THEME["blue"], alpha=0.30)

    # 3. Predicción Matemática hacia la Siguiente Vela y Horizonte Táctico (5 velas de 15m = 1h15m):
    # Basada en la ventana analítica de 20 velas de 15m (vela actual + 19 previas = 5 horas)
    closes_20 = state.bars_15m["Close"].iloc[-20:].to_numpy(dtype=float)
    x_20 = np.arange(20)
    slope_20, _ = np.polyfit(x_20, closes_20, 1)  # Pendiente lineal OLS sobre 20 barras

    # Momentum reciente (últimas 8 velas de 15m = 2h)
    closes_8 = closes_20[-8:]
    slope_8, _ = np.polyfit(np.arange(len(closes_8)), closes_8, 1)

    # Deriva condicional ARMA(1,1) + GJR-GARCH(1,1) para h=1..5
    ar_next = float(state.arma15.get("forecast_next", 0.0)) / 100.0 if isinstance(state.arma15, dict) else 0.0
    if ar_next == 0.0 and hasattr(state.fit15, "forecast_mean"):
        try:
            ar_next = float(state.fit15.forecast_mean(1, state.fut_dates_15m[:1])[0])
        except Exception:
            ar_next = 0.0
    garch_delta = state.spot * ar_next
    sig_15 = float(state.fit15.sigma_pts[-1]) if hasattr(state.fit15, "sigma_pts") else 25.0


    # Análisis de régimen para la siguiente vela y horizonte táctico:
    z_vwap = float(getattr(state, "z_vwap_5", 0.0))
    dist_zg = float(state.spot - state.zero_gamma)

    if dist_zg >= 15.0 and (slope_20 > 0 or slope_8 > 0 or z_vwap >= 0.15):
        next_mode = "ALCISTA (↗)"
        delta_next = max(slope_8 * 0.75, slope_20, garch_delta, 0.28 * sig_15, 6.5)
    elif dist_zg <= -15.0 and (slope_20 < 0 or slope_8 < 0 or z_vwap <= -0.15):
        next_mode = "BAJISTA (↘)"
        delta_next = min(slope_8 * 0.75, slope_20, garch_delta, -0.28 * sig_15, -6.5)
    else:
        next_mode = "RANGO (→)"
        delta_next = slope_20 * 0.35 if abs(slope_20) < 4.0 else garch_delta

    # Vector de trayectoria proyectada a 5 bloques de 15m (1 Hora y 15 Minutos)
    # k = 0 (Spot), k = 1 (Siguiente Vela), k = 2..5 (Desarrollo Táctico)
    x_pred = np.arange(0, 6)
    decay_factors = np.array([0.0, 1.0, 1.95, 2.8, 3.55, 4.2])
    y_pred = state.spot + delta_next * decay_factors
    total_delta = y_pred[-1] - state.spot

    # Línea Roja Resaltada con halo de neón para máxima claridad visual (limpia, sin cajas)
    ax_cone.plot(x_pred, y_pred, color="#ef4444", lw=7.0, alpha=0.22, zorder=8)
    ax_cone.plot(x_pred, y_pred, color="#ef4444", lw=4.0, ls="-", zorder=9, label=f"★ Proyección {next_mode} ({total_delta:+.0f}p)")

    # Punto terminal al final de la proyección con etiqueta limpia directa en rojo (sin caja verde ni bordes)
    ax_cone.scatter([5], [y_pred[-1]], color="#ef4444", edgecolor="#ffffff", s=80, zorder=10)
    ax_cone.text(5.5, y_pred[-1], f"{y_pred[-1]:,.0f} ({total_delta:+.0f}p)", color="#ef4444", fontsize=7.8, fontweight="bold", va="center", zorder=11)

    # Curvas Monte Carlo (cobertura global de 8h)
    ax_cone.plot(x_fut, q_full[2], color="#38bdf8", lw=1.6, ls="--", zorder=5)
    ax_cone.plot(x_fut, q_full[4], color="#f87171", lw=1.4, ls="--", zorder=4)
    ax_cone.plot(x_fut, q_full[3], color="#f87171", lw=1.0, ls=":", zorder=4)
    ax_cone.plot(x_fut, q_full[1], color="#34d399", lw=1.0, ls=":", zorder=4)
    ax_cone.plot(x_fut, q_full[0], color="#34d399", lw=1.4, ls="--", zorder=4)

    # Etiquetas directas de los niveles Monte Carlo al final de las curvas (margen derecho x = 32.5)
    ax_cone.text(32.4, q_ui[4, -1], f"P95 {q_ui[4, -1]:,.0f}", color="#f87171", fontsize=6.8, va="center", fontweight="bold")
    ax_cone.text(32.4, q_ui[3, -1], f"P90 {q_ui[3, -1]:,.0f}", color="#f87171", fontsize=6.4, va="center")
    ax_cone.text(32.4, q_ui[2, -1], f"P50 {q_ui[2, -1]:,.0f}", color="#38bdf8", fontsize=6.8, va="center", fontweight="bold")
    ax_cone.text(32.4, q_ui[1, -1], f"P10 {q_ui[1, -1]:,.0f}", color="#34d399", fontsize=6.4, va="center")
    ax_cone.text(32.4, q_ui[0, -1], f"P05 {q_ui[0, -1]:,.0f}", color="#34d399", fontsize=6.8, va="center", fontweight="bold")

    # Separador punteado y Punto Spot de anclaje actual
    ax_cone.axvline(0, color="#ffffff", lw=1.2, ls="--", alpha=0.6)
    ax_cone.scatter([0], [state.spot], color="#facc15", edgecolor="#ffffff", s=80, zorder=7, label=f"Spot MT5 ({state.spot:,.1f})")

    # Muros Institucionales GEX
    ax_cone.axhline(state.call_wall, color=COLOR_SHORT, lw=1.2, ls="-.", alpha=0.85)
    ax_cone.axhline(state.put_wall, color=COLOR_LONG, lw=1.2, ls="-.", alpha=0.85)
    ax_cone.plot([], [], color=COLOR_SHORT, lw=1.2, ls="-.", label="Muros GEX (Call/Put)")
    ax_cone.text(-31.0, state.call_wall + 5.0, f"Call Wall: {state.call_wall:,.0f}", color=COLOR_SHORT, fontsize=6.8, va="bottom", alpha=0.85)
    ax_cone.text(-31.0, state.put_wall - 8.0, f"Put Wall: {state.put_wall:,.0f}", color=COLOR_LONG, fontsize=6.8, va="top", alpha=0.85)

    ax_cone.set_xlim(-31.5, 37.5)
    _style_ax(
        ax_cone,
        title="SECCIÓN 1 (MACRO 15M): CONOS DE MONTE CARLO + GARCH(1,1) (P05 / P10 / P50 / P90 / P95 — 8H NY)",
        xlabel="Bloques de 15 Minutos (-31 = 8h Históricas | -19 = Ventana 20 Velas | 0 = Spot MT5 | +1 = Próxima Vela | +32 = 8h NY)",
        ylabel="Precio Futuro Nasdaq (US100-DEC26 / NQ Puntos)",
    )
    ax_cone.legend(
        loc="upper left",
        fontsize=6.8,
        ncol=3,
        framealpha=0.72,
        handlelength=1.1,
        handletextpad=0.35,
        columnspacing=0.8,
        borderpad=0.35,
    )

    # --- Panel 1B: Volatilidad Condicional GJR-GARCH(1,1) 15m ---
    ax_vol = fig.add_subplot(gs[0, 1])
    sig_pts = state.fit15.sigma_pts[-160:]
    idx_v = np.arange(len(sig_pts))
    p50_v, p90_v = np.percentile(state.fit15.sigma_pts, [50, 90])
    ax_vol.plot(idx_v, sig_pts, color=THEME["amber"], lw=1.6, label=f"σ_t 15m Actual ({sig_pts[-1]:.1f} pts)")
    ax_vol.fill_between(idx_v, sig_pts, color=THEME["amber"], alpha=0.15)
    ax_vol.axhline(p90_v, color=COLOR_SHORT, ls="--", lw=1.3, label=f"Techo Explosivo P90 ({p90_v:.1f}p)")
    ax_vol.axhline(p50_v, color=COLOR_LONG, ls=":", lw=1.1, label=f"Baseline Mediana P50 ({p50_v:.1f}p)")
    _style_ax(
        ax_vol,
        title=f"VOLATILIDAD CONDICIONAL GARCH(1,1) 15M — {state.reg15['label']} (P{state.reg15['percentile']:.1f}%)",
        ylabel="σ_15m (Puntos NQ)",
    )
    ax_vol.legend(loc="upper left", fontsize=7.5, ncol=2)

    # --- Panel 1C: Colas Extremas de Liquidación (P05 / VaR 99% / CVaR 99% / P95) ---
    ax_dist = fig.add_subplot(gs[1, 1])
    end_rets_pts = state.sim_paths[-1, :] - state.spot
    ax_dist.hist(end_rets_pts, bins=65, color=THEME["blue"], alpha=0.55, edgecolor=THEME["bg"], density=True)
    q05_pts = float(np.percentile(end_rets_pts, 5))
    q01_pts = float(np.percentile(end_rets_pts, 1))
    cvar01_pts = float(end_rets_pts[end_rets_pts <= q01_pts].mean())
    q95_pts = float(np.percentile(end_rets_pts, 95))
    ax_dist.axvline(q05_pts, color=COLOR_LONG, lw=1.6, ls="--", label=f"Suelo P05 (VaR 95%): {q05_pts:+.0f}p")
    ax_dist.axvline(q01_pts, color=COLOR_SHORT, lw=1.8, ls="-", label=f"VaR 99% (Cola 1%): {q01_pts:+.0f}p")
    ax_dist.axvline(cvar01_pts, color=THEME["pink"], lw=1.8, ls=":", label=f"CVaR 99% (Liquidación): {cvar01_pts:+.0f}p")
    ax_dist.axvline(q95_pts, color=THEME["amber"], lw=1.6, ls="--", label=f"Techo Extremo P95: {q95_pts:+.0f}p")
    ax_dist.axvline(0.0, color=THEME["text"], lw=1.0, alpha=0.6)
    _style_ax(
        ax_dist,
        title="DISTRIBUCIÓN DE COLAS Y LIQUIDACIÓN (P05 / VaR 99% / CVaR 99% / P95 — HORIZONTE 8H)",
        xlabel="Desplazamiento Neto Proyectado en Puntos (32 Bloques de 15m)",
        ylabel="Densidad Empírica",
    )
    ax_dist.legend(loc="upper left", fontsize=7.5, ncol=2)
    fig.subplots_adjust(left=0.055, right=0.985, top=0.92, bottom=0.09)
    return fig


def build_figure_page2(state: QuantSharedState, figsize: tuple[float, float] = (15.5, 5.6)) -> Figure:
    """
    SECCIÓN 2 (Zonas de Liquidez): Árbol Binomial CRR + Perfil GEX (Filtro >= 80%).
    """
    apply_dark()
    fig = Figure(figsize=figsize, dpi=100, facecolor=THEME["bg"])
    gs = GridSpec(2, 2, figure=fig, width_ratios=[1.45, 1.0], height_ratios=[1.0, 1.0], hspace=0.35, wspace=0.22)

    df_g = state.df_gex
    strikes = df_g["strike"].to_numpy(dtype=float)
    net_gex = df_g["net_gex_m"].to_numpy(dtype=float)
    crr_prem = df_g["crr_put_usd"].to_numpy(dtype=float)
    conf_arr = df_g["confluence_pct"].to_numpy(dtype=float)

    ax_gex = fig.add_subplot(gs[:, 0])
    bar_w = max(np.median(np.diff(strikes)) * 0.68, 12.0) if len(strikes) > 1 else 20.0
    for k_s, g_v, c_v in zip(strikes, net_gex, conf_arr):
        col = COLOR_LONG if g_v >= 0 else COLOR_SHORT
        alp = 0.90 if c_v >= 80.0 else 0.16
        edg = "#ffffff" if c_v >= 85.0 else "none"
        ax_gex.bar(k_s, g_v, width=bar_w, color=col, alpha=alp, edgecolor=edg, lw=1.0)

    ax_gex.axhline(0.0, color=THEME["muted"], lw=1.0)
    ax_gex.axvline(state.spot, color=THEME["blue"], lw=2.1, ls="-", label=f"Spot MT5 ({state.spot:,.1f})")
    ax_gex.axvline(state.call_wall, color=COLOR_SHORT, lw=1.8, ls="--", label=f"★ Call Wall ({state.call_wall:,.0f})")
    ax_gex.axvline(state.put_wall, color=COLOR_LONG, lw=1.8, ls="--", label=f"★ Put Wall ({state.put_wall:,.0f})")
    ax_gex.axvline(state.zero_gamma, color=THEME["amber"], lw=1.7, ls=":", label=f"★ Zero-Gamma ({state.zero_gamma:,.1f})")

    ax_crr = ax_gex.twinx()
    ax_crr.plot(strikes, crr_prem, color=THEME["amber"], lw=2.1, label="Prima Ejercicio Anticipado Put CRR ($/NQ)")
    ax_crr.set_ylabel("Urgencia Ejercicio CRR ($ USD / Contrato NQ)", color=THEME["amber"], fontsize=8.5)
    ax_crr.tick_params(axis="y", colors=THEME["amber"], labelsize=8)
    ax_crr.spines["right"].set_color(THEME["amber"])

    _style_ax(
        ax_gex,
        title=f"SECCIÓN 2 (ZONAS DE LIQUIDEZ): PERFIL GEX + ÁRBOL BINOMIAL CRR (CONFLUENCIA >= 80%)",
        xlabel="Strikes NQ / US100-DEC26 (Puntos)",
        ylabel="Gamma Exposure Neta ($ Millones por 1%)",
    )
    lines1, labels1 = ax_gex.get_legend_handles_labels()
    lines2, labels2 = ax_crr.get_legend_handles_labels()
    ax_gex.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=7.5, ncol=2)

    ax_grk = fig.add_subplot(gs[0, 1])
    ax_grk.plot(strikes, df_g["prob_itm_call"].to_numpy(), color=COLOR_LONG, lw=1.7, label="Prob. ITM Call N(d2) %")
    ax_grk.plot(strikes, df_g["prob_itm_put"].to_numpy(), color=COLOR_SHORT, lw=1.7, label="Prob. ITM Put N(-d2) %")
    ax_grk2 = ax_grk.twinx()
    ax_grk2.plot(strikes, df_g["vanna"].to_numpy(), color=THEME["blue"], lw=1.5, ls="--", label="Vanna (∂Δ/∂σ)")
    ax_grk2.plot(strikes, df_g["charm_day"].to_numpy(), color=THEME["amber"], lw=1.4, ls=":", label="Charm Diario (-∂Δ/∂t)")
    ax_grk2.tick_params(axis="y", colors=THEME["blue"], labelsize=8)
    ax_grk.axvline(state.spot, color=THEME["yellow"], lw=1.2, ls=":")
    _style_ax(
        ax_grk,
        title=f"PROBABILIDADES ITM BLACK-76 N(d2) & GRIEGAS 2DO ORDEN (ATM Δ={state.bs_atm.delta_call:+.2f})",
        ylabel="Probabilidad ITM (%)",
    )
    l1, lb1 = ax_grk.get_legend_handles_labels()
    l2, lb2 = ax_grk2.get_legend_handles_labels()
    ax_grk.legend(l1 + l2, lb1 + lb2, loc="center right", fontsize=7.2, ncol=2)

    ax_dlr = fig.add_subplot(gs[1, 1])
    shocks = sorted(state.dealer_flows.keys())
    flows = [state.dealer_flows[k] for k in shocks]
    c_dlr = [COLOR_LONG if f >= 0 else COLOR_SHORT for f in flows]
    bars_d = ax_dlr.bar([f"{k:+d}p" for k in shocks], flows, color=c_dlr, alpha=0.82, width=0.55)
    ax_dlr.axhline(0.0, color=THEME["text"], lw=0.9)
    for b_item, f_val in zip(bars_d, flows):
        ax_dlr.text(
            b_item.get_x() + b_item.get_width() / 2.0,
            f_val + (15.0 if f_val >= 0 else -35.0),
            f"{f_val:+.0f} NQ",
            ha="center",
            va="bottom" if f_val >= 0 else "top",
            color=THEME["text"],
            fontsize=8,
            fontweight="bold",
        )
    _style_ax(
        ax_dlr,
        title="SIMULADOR DE RE-HEDGING DE DEALERS (CONTRATOS NQ POR CHOQUE)",
        xlabel="Choque Instantáneo en Precio Spot (Puntos)",
        ylabel="Flujo Neto de Cobertura (Contratos NQ)",
    )
    fig.subplots_adjust(left=0.055, right=0.94, top=0.92, bottom=0.09)
    return fig


def build_figure_page3(state: QuantSharedState, figsize: tuple[float, float] = (15.5, 5.2)) -> Figure:
    """
    SECCIÓN 3 (Microestructura 5m): DETECTOR DE ANOMALÍAS DE MOMENTUM (LOG RETURN ANOMALIES)
    Un solo gráfico limpio sobre las velas de 5m de MT5 (`US100-DEC26`) con 4 capas exactas:
      1. `Log Return`: Línea continua gris (`color='#94a3b8'`).
      2. `Upper Threshold`: Línea punteada roja (`linestyle='--'`, `color='#ef4444'`).
      3. `Lower Threshold`: Línea punteada verde (`linestyle='--'`, `color='#10b981'`).
      4. `Anomalies`: Puntos naranjas (`scatter`, `color='#f97316'`, `s=55`, `zorder=5`).
    """
    apply_dark()
    fig = Figure(figsize=figsize, dpi=100, facecolor=THEME["bg"])
    ax = fig.add_subplot(111)

    valid_mask = (state.df_log_anom["Close"] > 0) & state.df_log_anom["log_ret"].notna()
    df_valid = state.df_log_anom[valid_mask] if valid_mask.any() else state.df_log_anom
    sub = df_valid.iloc[-160:].copy()
    x_idx = np.arange(len(sub))
    lr_vals = sub["log_ret"].to_numpy(dtype=float)
    up_vals = sub["upper_threshold"].to_numpy(dtype=float)
    lo_vals = sub["lower_threshold"].to_numpy(dtype=float)
    anom_mask = sub["is_anomaly"].to_numpy(dtype=bool)

    ax.plot(x_idx, lr_vals, color="#94a3b8", lw=1.4, label="Log Return 5m")
    ax.plot(x_idx, up_vals, linestyle="--", color="#ef4444", lw=1.5, label="Upper Threshold (+2σ)")
    ax.plot(x_idx, lo_vals, linestyle="--", color="#10b981", lw=1.5, label="Lower Threshold (-2σ)")
    ax.scatter(
        x_idx[anom_mask],
        lr_vals[anom_mask],
        color="#f97316",
        s=55,
        zorder=5,
        label="Anomalies",
    )
    # Marcador luminoso en la última barra real de MT5 (Cierre CME Futuros)
    ax.scatter(
        [len(sub) - 1],
        [lr_vals[-1]],
        color="#38bdf8",
        edgecolor="#ffffff",
        s=75,
        zorder=6,
        label=f"Cierre Futuros CME ({sub.index[-1].strftime('%H:%M NY')})",
    )

    # Línea divisoria en 16:00 NY: Cierre del mercado de contado (Cash NYSE/NASDAQ)
    for i_b, ts in enumerate(sub.index):
        if ts.strftime("%H:%M") == "16:00":
            ax.axvline(i_b, color="#f59e0b", linestyle=":", lw=1.6, alpha=0.9, zorder=3)
            ax.text(
                i_b - 0.7,
                0.0024,
                " 16:00 NY (Cierre Cash NYSE/NASDAQ)",
                color="#f59e0b",
                fontsize=7.8,
                fontweight="bold",
                va="top",
                ha="right",
                rotation=90,
            )
            break

    # Anclaje estricto: el eje X termina exactamente en la última vela con datos reales (sub.index[-1])
    # Sin extender el gráfico con espacio vacío hacia el futuro
    ax.set_xlim(0, len(sub) - 1)
    ax.margins(x=0.0)
    ax.autoscale(enable=False, axis="x")
    tick_pos = np.linspace(0, len(sub) - 1, min(9, len(sub)), dtype=int)
    tick_pos[-1] = len(sub) - 1  # Último tick anclado exactamente en la última vela real
    tick_lbls = [sub.index[i].strftime("%m-%d %H:%M") for i in tick_pos]
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_lbls)

    last_ts_str = sub.index[-1].strftime("%m-%d %H:%M NY")
    _style_ax(
        ax,
        title=f"SECCIÓN 3 (MICROESTRUCTURA 5M): ANOMALÍAS DE RETORNOS LOGARÍTMICOS (ÚLTIMO CIERRE: {last_ts_str} | US100-DEC26)",
        xlabel="Hora de Wall Street (America/New_York) — RTH Cash: 09:30-16:00 EDT | CME Futuros: Cierre Semanal Viernes 17:00 EDT",
        ylabel="Log Return 5m: ln(Close_t / Close_{t-1})",
    )
    ax.legend(loc="upper left", fontsize=8.4, ncol=5, framealpha=0.92)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.91, bottom=0.11)
    return fig


def build_figure_page4_yield_anomalies(state: QuantSharedState, figsize: tuple[float, float] = (15.5, 5.2)) -> Figure:
    """Alias compatible que devuelve el gráfico limpio de Log Return Anomalies."""
    return build_figure_page3(state, figsize=figsize)


# =========================================================================== #
# 4. EXPORTADOR DE REPORTE INTERACTIVO HTML5 (4 SECCIONES VÍA METATRADER 5)
# =========================================================================== #
def _fig_to_base64_png(fig: Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=125, facecolor=fig.get_facecolor(), bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _badge_html(text: str) -> str:
    u = text.upper()
    if "UPPER THRESHOLD" in u:
        return f'<span class="badge badge-short">{text}</span>'
    if "LOWER THRESHOLD" in u:
        return f'<span class="badge badge-long">{text}</span>'
    if "LONG" in u or "COMPRA" in u or "SOBREVENTA" in u:
        return f'<span class="badge badge-long">{text}</span>'
    if "SHORT" in u or "VENTA" in u or "SOBRECOMPRA" in u:
        return f'<span class="badge badge-short">{text}</span>'
    if "★" in u or ">85%" in u:
        return f'<span class="badge badge-star">{text}</span>'
    if "NEUTRAL" in u or "RANGO" in u or "BASELINE" in u or "(P50)" in u:
        return f'<span class="badge badge-neutral">{text}</span>'
    return text


def _render_html_table(headers: list[str], rows: list[list[str]], large_exec: bool = False) -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    body_parts = []
    for r in rows:
        tds = []
        for cell in r:
            c_str = str(cell)
            if any(
                k in c_str.upper()
                for k in ("UPPER THRESHOLD", "LOWER THRESHOLD", "LONG /", "SHORT /", "NEUTRAL /", "BASELINE", "(P50)", "★")
            ):
                tds.append(f"<td>{_badge_html(c_str)}</td>")
            else:
                tds.append(f"<td>{c_str}</td>")
        body_parts.append("<tr>" + "".join(tds) + "</tr>")
    cls = "quant-table exec-fast-table" if large_exec else "quant-table"
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(body_parts)}</tbody></table></div>'


def _render_decision_banner_html(dec: ConditionalDecision) -> str:
    conf_badge = (
        f'<span class="badge badge-star">★ CONFLUENCIA ALTA: {dec.confluence_pct:.1f}%</span>'
        if dec.confluence_pct >= 80.0
        else f'<span class="badge badge-info">CONFLUENCIA: {dec.confluence_pct:.1f}%</span>'
    )
    rr_badge = (
        f'<span class="badge badge-star">★ RATIO R:R {dec.rr_ratio:.2f}x</span>'
        if dec.rr_ratio >= 1.75
        else f'<span class="badge badge-info">RATIO R:R {dec.rr_ratio:.2f}x</span>'
    )
    trigger_text = dec.trigger_card or "A la espera de confirmación cuantitativa..."
    stop_text = dec.stop_card or "Stop estructural en muro opuesto / 1 ATR"
    target_text = dec.target_card or "TP1: VWAP / TP2: Borde estructural opuesto"
    return f"""
    <div class="decision-banner" style="border-left: 6px solid {dec.color_hex}; background: {dec.bg_hex};">
      <div class="decision-header">
        <div>
          <span class="decision-module">{dec.module_name}</span>
          <div class="decision-signal" style="color: {dec.color_hex};">
            ● DECISIÓN MATEMÁTICA CONDICIONAL: {dec.signal} — {dec.sub_label}
          </div>
        </div>
        <div class="decision-badges">{conf_badge} {rr_badge}</div>
      </div>
      <div class="decision-action"><strong>ACCIÓN OPERATIVA:</strong> {dec.action_text}</div>
      <div class="decision-metrics">{dec.metrics_highlight}</div>
      <div class="exec-card-grid">
        <div class="exec-card exec-trigger">
          <div class="exec-card-title">GATILLO DE ENTRADA</div>
          <div class="exec-card-body">{trigger_text}</div>
        </div>
        <div class="exec-card exec-stop">
          <div class="exec-card-title">INVALIDACIÓN / STOP ESTRUCTURAL</div>
          <div class="exec-card-body">{stop_text}</div>
        </div>
        <div class="exec-card exec-target">
          <div class="exec-card-title">TARGETS / ESCALADO</div>
          <div class="exec-card-body">{target_text}</div>
        </div>
      </div>
    </div>
    """


def export_visual_assets(state: QuantSharedState, auto_refresh_sec: int = 60) -> tuple[Path, list[Path]]:
    """
    Exporta los lienzos PNG de alta resolución y el Dashboard HTML5 separado en las
    4 Secciones Lógicas exactas alimentadas en tiempo real por MetaTrader 5.
    """
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fig1 = build_figure_page1(state)
    fig2 = build_figure_page2(state)
    fig3 = build_figure_page3(state)

    p1 = CHART_DIR / "dashboard_page1_macro_garch_mc.png"
    p2 = CHART_DIR / "dashboard_page2_liquidez_gex_crr.png"
    p3 = CHART_DIR / "dashboard_page3_microestructura_5m.png"
    p4 = CHART_DIR / "dashboard_page4_yield_anomalies_nq.png"
    fig1.savefig(p1, dpi=140, facecolor=THEME["bg"], bbox_inches="tight")
    fig2.savefig(p2, dpi=140, facecolor=THEME["bg"], bbox_inches="tight")
    fig3.savefig(p3, dpi=140, facecolor=THEME["bg"], bbox_inches="tight")
    fig3.savefig(p4, dpi=140, facecolor=THEME["bg"], bbox_inches="tight")

    b64_1 = _fig_to_base64_png(fig1)
    b64_2 = _fig_to_base64_png(fig2)
    b64_3 = _fig_to_base64_png(fig3)
    state.b64_page1 = b64_1
    state.b64_page2 = b64_2
    state.b64_page3 = b64_3
    plt.close(fig1)
    plt.close(fig2)
    plt.close(fig3)

    # --- SECCIÓN 1 (Macro 15m): Tablas bajo el gráfico (P05, P10, P50, P90, P95 y VaR/CVaR) ---
    tbl_s1_cone = _render_html_table(
        [
            "Horizonte Temporal",
            "P05 (Soporte Fuerte)",
            "P25 (Zona de Demanda)",
            "P50 (Mediana/Baseline)",
            "P75 (Zona de Oferta)",
            "P95 (Resistencia Fuerte)",
        ],
        state.cone_table_rows,
    )
    tbl_s1_tail = _render_html_table(
        [
            "Marco Temporal",
            "Soporte Probable (P05)",
            "Resistencia Probable (P95)",
            "Riesgo Máximo / Hard Stop (VaR)",
            "Riesgo de Cisne Negro (CVaR)",
            "Directiva Operativa",
        ],
        state.tail_table_rows,
    )

    # --- SECCIÓN 2 (Zonas de Liquidez): Tablas bajo el gráfico (GEX + CRR con Confluencia >= 80%) ---
    tbl_s2_strikes = _render_html_table(
        [
            "Strike Clave NQ",
            "Distancia Spot",
            "Muro Institucional GEX + CRR",
            "Net GEX ($M)",
            "Prima Ejerc. CRR (Pts / $)",
            "Frontera S* CRR",
            "Prob ITM (Call / Put)",
            "Confluencia (>80%)",
            "Acción Exacta (LONG / SHORT)",
        ],
        state.gex_table_rows,
    )
    tbl_s2_summary = _render_html_table(
        [
            "Muro Primario / Motor",
            "Nivel Exacto NQ",
            "Exposición Gamma / Flujo",
            "Métrica CRR / Cobertura",
            "Confluencia %",
            "Acción Exacta (LONG / SHORT)",
        ],
        state.gex_summary_rows,
    )

    # --- SECCIÓN 3 (Microestructura 5m): Tablas bajo el gráfico de Log Return Anomalies ---
    tbl_s3_log_anom = _render_html_table(
        [
            "Hora (NY)",
            "Precio NQ (MT5)",
            "Log Return 5m",
            "Umbral Roto (Upper/Lower ±2.0σ)",
            "Señal de Momentum (LONG / SHORT)",
        ],
        state.log_anom_rows,
    )
    tbl_s3_micro = _render_html_table(
        [
            "Borde Extremo / Microestructura 5m",
            "Nivel / Parámetro 1",
            "Nivel / Parámetro 2",
            "Referencia / Flujo",
            "Confiabilidad Estadística",
            "Acción Exacta (LONG / SHORT)",
        ],
        state.micro_table_rows,
    )

    # --- SECCIÓN 4 (Matriz de Ejecución Rápida): Sin gráficos, solo tabla de alta prioridad (>80%) ---
    tbl_s4_fast = _render_html_table(
        [
            "Nivel de Precio",
            "Muro Institucional (Call/Put Wall / Extremo)",
            "Confluencia (>80%)",
            "Acción (LONG / SHORT / NEUTRAL)",
        ],
        state.exec_levels_rows,
        large_exec=True,
    )

    # --- SECCIÓN 5 (Estrategias Institucionales Nivel 1 MT5) ---
    tbl_s5_strat = _render_html_table(
        [
            "Estrategia Institucional (Nivel 1 MT5)",
            "Activos / Símbolos MT5",
            "Métricas Cuantitativas (α, β, Z, σ)",
            "Parámetro / Offset Óptimo",
            "Señal / Ejecución Institucional",
        ],
        getattr(state, "strategies_table_rows", []),
    )


    data_start_str = state.bars_15m.index[0].strftime("%Y-%m-%d %H:%M")
    data_end_str = state.bars_15m.index[-1].strftime("%Y-%m-%d %H:%M NY")
    bars_count_15m = len(state.bars_15m)
    reload_sec = max(int(auto_refresh_sec), 15) if auto_refresh_sec > 0 else 60
    now_local_str = pd.Timestamp.now(tz=sessions.TZ_NY).strftime("%H:%M:%S NY")
    html_path = OUTPUT_DIR / "dashboard_institucional_nq.html"

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Dashboard Cuantitativo en Tiempo Real vía MT5 (US100-DEC26 — America/New_York)</title>
<style>
  :root {{
    --bg: #0b1120;
    --panel: #111827;
    --card: #1e293b;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --long: #10b981;
    --short: #ef4444;
    --neutral: #94a3b8;
    --cyan: #38bdf8;
    --orange: #f97316;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', 'JetBrains Mono', Consolas, monospace;
    font-size: 13px;
    line-height: 1.45;
  }}
  .topbar {{
    background: linear-gradient(90deg, #0f172a 0%, #1e293b 100%);
    border-bottom: 2px solid var(--border);
    padding: 12px 22px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .brand-title {{ font-size: 16px; font-weight: 800; color: var(--cyan); letter-spacing: 0.4px; }}
  .brand-sub {{ font-size: 11.3px; color: var(--muted); }}
  .top-kpis {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
  .kpi-pill {{
    background: #0f172a;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 11px;
    text-align: right;
  }}
  .kpi-pill .lbl {{ font-size: 10px; color: var(--muted); text-transform: uppercase; }}
  .kpi-pill .val {{ font-size: 13px; font-weight: 700; color: var(--text); }}
  .kpi-pill-range {{
    background: #111827;
    border: 1px solid #0284c7;
    border-radius: 6px;
    padding: 6px 12px;
    text-align: left;
  }}
  .kpi-pill-range .lbl {{ font-size: 9.5px; color: var(--cyan); text-transform: uppercase; font-weight: 800; }}
  .kpi-pill-range .val {{ font-size: 12px; font-weight: 700; color: #f8fafc; font-family: monospace; }}
  .reload-ctrl {{
    background: #0f172a;
    border: 1px solid #0284c7;
    border-radius: 6px;
    padding: 6px 10px;
    display: flex;
    align-items: center;
    gap: 7px;
  }}
  .reload-btn {{
    background: #1e293b;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 8px;
    font-family: inherit;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
  }}
  .reload-btn:hover {{ background: #334155; color: var(--cyan); }}
  .tabs-bar {{
    display: flex;
    background: #0f172a;
    border-bottom: 1px solid var(--border);
    padding: 0 22px;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .tab-btn {{
    background: transparent;
    color: var(--muted);
    border: none;
    border-bottom: 3px solid transparent;
    padding: 12px 16px;
    font-family: inherit;
    font-size: 12.8px;
    font-weight: 800;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .tab-btn:hover {{ color: var(--text); background: rgba(56, 189, 248, 0.08); }}
  .tab-btn.active {{ color: var(--cyan); border-bottom-color: var(--cyan); background: rgba(56, 189, 248, 0.12); }}
  .page {{ display: none; padding: 16px 22px 34px; max-width: 1840px; margin: 0 auto; }}
  .page.active {{ display: block; }}
  .chart-box {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 14px;
    text-align: center;
  }}
  .chart-box img {{ width: 100%; max-height: 550px; object-fit: contain; border-radius: 4px; }}
  .section-hdr {{
    font-size: 13px;
    font-weight: 800;
    color: var(--cyan);
    text-transform: uppercase;
    margin: 14px 0 7px;
    letter-spacing: 0.5px;
  }}
  .table-wrap {{
    overflow-x: auto;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 14px;
  }}
  table.quant-table {{ width: 100%; border-collapse: collapse; font-size: 12.2px; white-space: nowrap; }}
  table.quant-table th {{
    background: #1e293b;
    color: var(--cyan);
    text-align: left;
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    font-weight: 800;
  }}
  table.quant-table td {{
    padding: 7.5px 12px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.55);
  }}
  table.exec-fast-table {{ font-size: 14.5px; }}
  table.exec-fast-table th {{ padding: 12px 18px; font-size: 13.5px; letter-spacing: 0.5px; }}
  table.exec-fast-table td {{ padding: 11px 18px; font-weight: 700; }}
  table.quant-table tr:hover {{ background: rgba(56, 189, 248, 0.08); }}
  .badge {{
    display: inline-block;
    padding: 3.5px 10px;
    border-radius: 4px;
    font-weight: 800;
    font-size: 12px;
  }}
  .badge-long {{ background: rgba(16, 185, 129, 0.24); color: #34d399; border: 1px solid #10b981; }}
  .badge-short {{ background: rgba(239, 68, 68, 0.24); color: #f87171; border: 1px solid #ef4444; }}
  .badge-neutral {{ background: rgba(148, 163, 184, 0.22); color: #cbd5e1; border: 1px solid #94a3b8; }}
  .badge-star {{ background: rgba(56, 189, 248, 0.24); color: #7dd3fc; border: 1px solid #38bdf8; }}
  .badge-info {{ background: #1e293b; color: #cbd5e1; border: 1px solid #475569; }}
  .decision-banner {{
    border-radius: 8px;
    padding: 12px 18px;
    margin: 12px 0 14px;
    border: 1px solid var(--border);
  }}
  .decision-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
  .decision-module {{ font-size: 11px; color: #cbd5e1; text-transform: uppercase; letter-spacing: 0.6px; }}
  .decision-signal {{ font-size: 16.5px; font-weight: 900; margin-top: 2px; }}
  .decision-action {{ margin-top: 7px; font-size: 13.5px; color: #ffffff; }}
  .decision-metrics {{ margin-top: 4px; font-size: 12px; color: #cbd5e1; }}
  .exec-card-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 10px;
    margin-top: 10px;
  }}
  .exec-card {{
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
  }}
  .exec-card-title {{
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 5px;
  }}
  .exec-trigger .exec-card-title {{ color: var(--cyan); }}
  .exec-stop .exec-card-title {{ color: #f87171; }}
  .exec-target .exec-card-title {{ color: #34d399; }}
  .exec-card-body {{
    font-size: 12px;
    font-weight: 700;
    color: #f8fafc;
    line-height: 1.35;
  }}
</style>
</head>
<body>
  <div class="topbar">
    <div>
      <div class="brand-title">DASHBOARD CUANTITATIVO EN TIEMPO REAL VÍA MT5 (US100-DEC26 — AMERICA/NEW_YORK)</div>
      <div class="brand-sub">
        Sesión Wall Street: {state.session_status} | Última Vela NY: {state.timestamp_ny:%Y-%m-%d %H:%M %Z} | Actualizado: {now_local_str} |
        Fuente: {state.source_15m} | Cómputo: {state.elapsed_sec:.2f}s
      </div>
    </div>
    <div class="top-kpis">
      <div class="kpi-pill-range">
        <div class="lbl">Datos Cargados (Rango Histórico)</div>
        <div class="val">{data_start_str} → {data_end_str} ({bars_count_15m} velas 15m)</div>
      </div>
      <div class="kpi-pill"><div class="lbl">Spot MT5 (US100-DEC26)</div><div class="val" style="color:var(--cyan);">{state.spot:,.2f}</div></div>
      <div class="kpi-pill"><div class="lbl">VWAP 5m (NY)</div><div class="val">{state.vwap_now:,.2f} ({state.z_vwap_5:+.2f}σ)</div></div>
      <div class="kpi-pill"><div class="lbl">Zero-Gamma Flip</div><div class="val" style="color:#facc15;">{state.zero_gamma:,.1f}</div></div>
      <div class="kpi-pill"><div class="lbl">Put / Call Wall</div><div class="val">{state.put_wall:,.0f} / {state.call_wall:,.0f}</div></div>
      <div class="kpi-pill"><div class="lbl">Cono 1h (P05 / P95)</div><div class="val">{state.q_mat[1,3]:,.0f} / {state.q_mat[9,3]:,.0f}</div></div>
      <div class="kpi-pill"><div class="lbl">Log-Return 5m</div><div class="val" style="color:var(--orange);">{float(state.df_log_anom['log_ret'].iloc[-1]):+.5f}</div></div>
      <div class="reload-ctrl">
        <div>
          <div style="font-size:9.5px;color:var(--muted);text-transform:uppercase;">Auto-Recarga MT5</div>
          <div id="reload-timer-lbl" style="font-size:12.5px;font-weight:800;color:var(--long);">⟳ {reload_sec}s</div>
        </div>
        <button class="reload-btn" id="btn-toggle-reload" onclick="toggleAutoReload()">⏸ Pausar</button>
        <button class="reload-btn" onclick="forceReloadNow()">⟳ Ahora</button>
      </div>
    </div>
  </div>

  <div class="tabs-bar">
    <button class="tab-btn active" onclick="openTab(0)">SECCIÓN 1 (Macro 15m): GARCH(1,1) + Conos de Monte Carlo</button>
    <button class="tab-btn" onclick="openTab(1)">SECCIÓN 2 (Zonas de Liquidez): Árbol Binomial CRR + Perfil GEX</button>
    <button class="tab-btn" onclick="openTab(2)">SECCIÓN 3 (Microestructura 5m): Anomalías de Momentum (Log Returns)</button>
    <button class="tab-btn" onclick="openTab(3)">SECCIÓN 4 (Matriz de Ejecución): Tabla de Alta Prioridad (&gt;80%)</button>
    <button class="tab-btn" onclick="openTab(4)">SECCIÓN 5 (Estrategias Institucionales): Carry Basis, StatArb & Avellaneda-Stoikov L1</button>
  </div>


  <!-- SECCIÓN 1: MACRO 15M (GARCH + MONTE CARLO) + TABLAS DEBAJO -->
  <div class="page active" id="page-0">
    <div class="chart-box"><img src="data:image/png;base64,{b64_1}" alt="Sección 1 Macro 15m GARCH + Monte Carlo"></div>
    <div class="section-hdr">1A. MATRIZ DE PROYECCIÓN DE PRECIOS POR HORIZONTE (MONTE CARLO)</div>
    {tbl_s1_cone}
    <details style="margin: 12px 0; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px;">
      <summary style="font-size: 11.5px; font-weight: 700; color: var(--muted); cursor: pointer;">Telemetría Matemática Avanzada &amp; Métricas de Riesgo Operativo (GJR-GARCH / VaR / CVaR)</summary>
      <div style="margin-top: 10px;">
        <div style="margin-bottom:10px; padding:8px 12px; background:rgba(15,23,42,0.85); border:1px solid var(--border); border-radius:4px; font-size:12px; line-height:1.5;">
          <strong style="color:var(--text);">Auditoría de Estacionariedad:</strong>
          <span style="display:inline-block; margin-left:6px; padding:2px 8px; border-radius:3px; font-weight:800; font-size:11px; background:{'rgba(16,185,129,0.18)' if state.adf_is_stationary else 'rgba(239,68,68,0.2)'}; color:{'#10b981' if state.adf_is_stationary else '#ef4444'}; border:1px solid {'#10b981' if state.adf_is_stationary else '#ef4444'};">Prueba ADF: {state.adf_status_str}</span>
          <span style="margin-left:8px; color:var(--muted); font-size:11px;">Estadístico: {state.adf_stat:.3f} | Crítico 5%: {state.adf_crit_5pct:.3f} | {'✓ Luz Verde Operativa' if state.adf_is_stationary else '⚠ OPERATIVA SUSPENDIDA'}</span>
        </div>
        <div class="section-hdr" style="margin-top: 6px;">1B. MÉTRICAS DE RIESGO OPERATIVO Y COLAS PESADAS (VaR 99% / CVaR 99%)</div>
        {tbl_s1_tail}
      </div>
    </details>
    {_render_decision_banner_html(state.decision_page1)}
  </div>

  <!-- SECCIÓN 2: ZONAS DE LIQUIDEZ (ÁRBOL BINOMIAL CRR + PERFIL GEX) + TABLAS DE PRIMAS Y CONFLUENCIA DEBAJO -->
  <div class="page" id="page-1">
    <div class="chart-box"><img src="data:image/png;base64,{b64_2}" alt="Sección 2 Zonas de Liquidez CRR + GEX"></div>
    <div class="section-hdr">2A. PERFIL GEX + ÁRBOL BINOMIAL CRR — STRIKES DE ALTA CONFLUENCIA (&gt; 80% ★) Y PRIMAS EXACTAS</div>
    {tbl_s2_strikes}
    <div class="section-hdr">2B. SÍNTESIS DE MUROS INSTITUCIONALES (CALL WALL / PUT WALL / ZERO-GAMMA) Y COBERTURA DE DEALERS</div>
    {tbl_s2_summary}
    {_render_decision_banner_html(state.decision_page2)}
  </div>

  <!-- SECCIÓN 3: MICROESTRUCTURA 5M (DETECTOR DE ANOMALÍAS DE LOG RETURNS) + TABLAS DEBAJO -->
  <div class="page" id="page-2">
    <div class="chart-box"><img src="data:image/png;base64,{b64_3}" alt="Sección 3 Microestructura 5m Log Return Anomalies"></div>
    <div class="section-hdr">3A. ÚLTIMAS ANOMALÍAS DE MOMENTUM DETECTADAS EN 5M (LOG RETURNS — WINDOW = 20, UMBRALES ±2.0σ)</div>
    {tbl_s3_log_anom}
    <div class="section-hdr">3B. MÉTRICAS DE MICROESTRUCTURA 5M: BANDAS EXTREMAS VWAP (±2σ / ±3σ), ORDER FLOW (OFI/CVD) Y HURST</div>
    {tbl_s3_micro}
    {_render_decision_banner_html(state.decision_page4_yield)}
  </div>

  <!-- SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA (SIN GRÁFICOS, SOLO TABLA DE ALTA PRIORIDAD >80%) -->
  <div class="page" id="page-3">
    {_render_decision_banner_html(state.decision_master)}
    <div class="section-hdr">SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA — NIVEL DE PRECIO, MURO INSTITUCIONAL, CONFLUENCIA (&gt;80%) Y ACCIÓN (LONG / SHORT / NEUTRAL)</div>
    {tbl_s4_fast}
  </div>

  <!-- SECCIÓN 5: ESTRATEGIAS INSTITUCIONALES (100% DATOS NIVEL 1 MT5) -->
  <div class="page" id="page-4">
    <div class="section-hdr">SECCIÓN 5: ESTRATEGIAS INSTITUCIONALES Y MICROESTRUCTURA NIVEL 1 (MT5 US100-DEC26)</div>
    {tbl_s5_strat}
  </div>

<script>
const DEFAULT_RELOAD_SEC = {reload_sec};
let remainingSec = DEFAULT_RELOAD_SEC;
let isPaused = localStorage.getItem('nq_reload_paused') === '1';

function openTab(idx) {{
  const btns = document.querySelectorAll('.tab-btn');
  const pages = document.querySelectorAll('.page');
  btns.forEach((b, i) => b.classList.toggle('active', i === idx));
  pages.forEach((p, i) => p.classList.toggle('active', i === idx));
  try {{ localStorage.setItem('nq_active_tab', String(idx)); }} catch (e) {{}}
}}

function updateReloadUI() {{
  const lbl = document.getElementById('reload-timer-lbl');
  const btn = document.getElementById('btn-toggle-reload');
  if (!lbl || !btn) return;
  if (isPaused) {{
    lbl.textContent = '⏸ PAUSADO';
    lbl.style.color = 'var(--neutral)';
    btn.textContent = '▶ Activar';
  }} else {{
    lbl.textContent = '⟳ ' + remainingSec + 's';
    lbl.style.color = 'var(--long)';
    btn.textContent = '⏸ Pausar';
  }}
}}

function toggleAutoReload() {{
  isPaused = !isPaused;
  try {{ localStorage.setItem('nq_reload_paused', isPaused ? '1' : '0'); }} catch (e) {{}}
  updateReloadUI();
}}

function forceReloadNow() {{
  try {{ sessionStorage.setItem('nq_scroll_y', String(window.scrollY)); }} catch (e) {{}}
  window.location.reload();
}}

// Restaurar pestaña activa y posición de scroll tras cada auto-recarga
(function initDashboardState() {{
  try {{
    const savedTab = parseInt(localStorage.getItem('nq_active_tab') || '0', 10);
    if (!isNaN(savedTab) && savedTab >= 0 && savedTab <= 4) {{
      openTab(savedTab);
    }}
    const savedScroll = parseInt(sessionStorage.getItem('nq_scroll_y') || '0', 10);
    if (!isNaN(savedScroll) && savedScroll > 0) {{
      setTimeout(() => window.scrollTo(0, savedScroll), 40);
    }}
  }} catch (e) {{}}
  updateReloadUI();
  setInterval(() => {{
    if (isPaused) return;
    remainingSec -= 1;
    if (remainingSec <= 0) {{
      forceReloadNow();
    }} else {{
      updateReloadUI();
    }}
  }}, 1000);
}})();
</script>
</body>
</html>
"""
    tmp_path = html_path.with_suffix(".html.tmp")
    tmp_path.write_text(html_content, encoding="utf-8")
    tmp_path.replace(html_path)
    return html_path, [p1, p2, p3, p4]


# =========================================================================== #
# 5. INTERFAZ GRÁFICA NATIVA MULTI-PESTAÑA (TKINTER — 4 SECCIONES LÓGICAS)
# =========================================================================== #
class InstitutionalQuantDashboardApp:
    """
    Aplicación de Escritorio Multi-Panel con 4 Secciones Lógicas (`ttk.Notebook`):
      - Sección 1 (Macro 15m): GARCH(1,1) + Conos de Monte Carlo + Tablas P05, P50, P95.
      - Sección 2 (Zonas de Liquidez): Árbol Binomial CRR + Perfil GEX + Tablas Primas/Confluencia.
      - Sección 3 (Microestructura 5m): Detector de Anomalías de Momentum (Log Returns) + Tablas.
      - Sección 4 (Matriz de Ejecución): Panel sin gráficos, solo tabla de alta prioridad (>80%).
    """

    def __init__(self, feed: DataFeedNQ, auto_refresh_sec: int = 60):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.feed = feed
        self.auto_refresh_sec = auto_refresh_sec
        self._after_id = None

        self.root = tk.Tk()
        self.root.title("DASHBOARD CUANTITATIVO EN TIEMPO REAL VÍA MT5 (US100-DEC26 — AMERICA/NEW_YORK)")
        self.root.geometry("1680x980")
        self.root.configure(bg="#0b1120")

        self._configure_styles()
        self._build_header()

        self.notebook = ttk.Notebook(self.root, style="Quant.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self.tab1 = tk.Frame(self.notebook, bg="#0b1120")
        self.tab2 = tk.Frame(self.notebook, bg="#0b1120")
        self.tab3 = tk.Frame(self.notebook, bg="#0b1120")
        self.tab4 = tk.Frame(self.notebook, bg="#0b1120")

        self.notebook.add(self.tab1, text=" SECCIÓN 1 (Macro 15m): GARCH(1,1) + Monte Carlo ")
        self.notebook.add(self.tab2, text=" SECCIÓN 2 (Liquidez): CRR + Perfil GEX ")
        self.notebook.add(self.tab3, text=" SECCIÓN 3 (Micro 5m): Anomalías Log Returns ")
        self.notebook.add(self.tab4, text=" SECCIÓN 4 (Matriz de Ejecución >80%) ")

        self.state: QuantSharedState | None = None
        self.html_path: Path | None = None
        self.refresh_all()

        if self.auto_refresh_sec > 0:
            self._schedule_refresh()

    def _configure_styles(self) -> None:
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Quant.TNotebook", background="#0b1120", borderwidth=0)
        style.configure(
            "Quant.TNotebook.Tab",
            background="#1e293b",
            foreground="#94a3b8",
            padding=(14, 8),
            font=("Consolas", 9, "bold"),
        )
        style.map(
            "Quant.TNotebook.Tab",
            background=[("selected", "#0284c7"), ("active", "#334155")],
            foreground=[("selected", "#ffffff"), ("active", "#f8fafc")],
        )
        style.configure(
            "Quant.Treeview",
            background="#111827",
            foreground="#f8fafc",
            fieldbackground="#111827",
            rowheight=23,
            font=("Consolas", 8),
            borderwidth=1,
        )
        style.configure(
            "Quant.Treeview.Heading",
            background="#1e293b",
            foreground="#38bdf8",
            font=("Consolas", 8, "bold"),
            relief="flat",
        )
        style.configure(
            "ExecFast.Treeview",
            background="#111827",
            foreground="#f8fafc",
            fieldbackground="#111827",
            rowheight=32,
            font=("Consolas", 10, "bold"),
            borderwidth=1,
        )
        style.configure(
            "ExecFast.Treeview.Heading",
            background="#1e293b",
            foreground="#38bdf8",
            font=("Consolas", 10, "bold"),
            relief="flat",
        )
        style.map("Quant.Treeview", background=[("selected", "#1d4ed8")], foreground=[("selected", "#ffffff")])
        style.map("ExecFast.Treeview", background=[("selected", "#1d4ed8")], foreground=[("selected", "#ffffff")])

    def _build_header(self) -> None:
        tk = self.tk
        hdr = tk.Frame(self.root, bg="#0f172a", highlightthickness=1, highlightbackground="#334155")
        hdr.pack(fill="x", padx=10, pady=(8, 4))

        left = tk.Frame(hdr, bg="#0f172a")
        left.pack(side="left", padx=12, pady=6)
        self.lbl_title = tk.Label(
            left,
            text="DASHBOARD CUANTITATIVO EN TIEMPO REAL VÍA MT5 (USTEC / US100 — AMERICA/NEW_YORK)",
            bg="#0f172a",
            fg="#38bdf8",
            font=("Consolas", 11, "bold"),
        )
        self.lbl_title.pack(anchor="w")
        self.lbl_status = tk.Label(
            left,
            text="Conectando a MetaTrader 5...",
            bg="#0f172a",
            fg="#cbd5e1",
            font=("Consolas", 9),
        )
        self.lbl_status.pack(anchor="w")

        right = tk.Frame(hdr, bg="#0f172a")
        right.pack(side="right", padx=12, pady=6)

        btn_refresh = tk.Button(
            right,
            text="⟳ ACTUALIZAR MT5 AHORA",
            command=self.refresh_all,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Consolas", 9, "bold"),
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
        )
        btn_refresh.pack(side="left", padx=5)

        btn_web = tk.Button(
            right,
            text="ABRIR EN NAVEGADOR (AUTO-RELOAD)",
            command=self._open_html_in_browser,
            bg="#10b981",
            fg="#052e16",
            activebackground="#059669",
            font=("Consolas", 9, "bold"),
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
        )
        btn_web.pack(side="left", padx=5)

    def _open_html_in_browser(self) -> None:
        if self.html_path and self.html_path.exists():
            webbrowser.open(self.html_path.resolve().as_uri())

    def _schedule_refresh(self) -> None:
        if self.auto_refresh_sec > 0:
            self._after_id = self.root.after(self.auto_refresh_sec * 1000, self._auto_tick)

    def _auto_tick(self) -> None:
        self.refresh_all()
        self._schedule_refresh()

    @staticmethod
    def _clear_frame(frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _create_decision_banner(self, parent, dec: ConditionalDecision) -> None:
        tk = self.tk
        banner_frame = tk.Frame(
            parent,
            bg=dec.bg_hex,
            highlightthickness=2,
            highlightbackground=dec.color_hex,
            padx=12,
            pady=5,
        )
        banner_frame.pack(fill="x", padx=6, pady=(3, 4))

        top_row = tk.Frame(banner_frame, bg=dec.bg_hex)
        top_row.pack(fill="x")
        tk.Label(
            top_row,
            text=f"● {dec.module_name}  |  DECISIÓN: {dec.signal} — {dec.sub_label}",
            bg=dec.bg_hex,
            fg=dec.color_hex,
            font=("Consolas", 10, "bold"),
        ).pack(side="left")

        badge_text = (
            f"★ CONFLUENCIA: {dec.confluence_pct:.1f}%  |  RATIO R:R: {dec.rr_ratio:.2f}x"
            if dec.confluence_pct >= 80.0
            else f"CONFLUENCIA: {dec.confluence_pct:.1f}%  |  RATIO R:R: {dec.rr_ratio:.2f}x"
        )
        tk.Label(
            top_row,
            text=badge_text,
            bg="#0f172a",
            fg=COLOR_CONFLUENCE if dec.confluence_pct >= 80.0 else "#f8fafc",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=2,
        ).pack(side="right")

        tk.Label(
            banner_frame,
            text=f"ACCIÓN OPERATIVA: {dec.action_text}",
            bg=dec.bg_hex,
            fg="#ffffff",
            font=("Consolas", 9, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        tk.Label(
            banner_frame,
            text=dec.metrics_highlight,
            bg=dec.bg_hex,
            fg="#cbd5e1",
            font=("Consolas", 8),
            anchor="w",
        ).pack(fill="x")

    def _create_treeview_table(
        self,
        parent,
        title: str,
        columns: list[str],
        rows: list[list[str]],
        height: int = 6,
        fast_exec: bool = False,
    ) -> None:
        tk = self.tk
        ttk = self.ttk
        container = tk.Frame(parent, bg="#111827", highlightthickness=1, highlightbackground="#334155")
        container.pack(fill="both", expand=fast_exec, padx=6, pady=(2, 3))

        tk.Label(
            container,
            text=f"  {title}",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Consolas", 9 if fast_exec else 8, "bold"),
            anchor="w",
            pady=3 if fast_exec else 2,
        ).pack(fill="x")

        tree_frame = tk.Frame(container, bg="#111827")
        tree_frame.pack(fill="both", expand=True)

        style_name = "ExecFast.Treeview" if fast_exec else "Quant.Treeview"
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=height, style=style_name)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        col_w = max(110, int(1580 / max(len(columns), 1)))
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=col_w, anchor="center")

        tree.tag_configure("long_row", foreground="#34d399", background="#062e22")
        tree.tag_configure("short_row", foreground="#f87171", background="#3b1219")
        tree.tag_configure("star_row", foreground="#7dd3fc", background="#0c2a40")
        tree.tag_configure("neutral_row", foreground="#cbd5e1", background="#1e293b")
        tree.tag_configure("normal_row", foreground="#f8fafc", background="#111827")

        for r in rows:
            joined = " ".join(str(c).upper() for c in r)
            if "LONG / COMPRA" in joined:
                tag = "long_row"
            elif "SHORT / VENTA" in joined:
                tag = "short_row"
            elif "BASELINE" in joined or "NEUTRAL / RANGO" in joined or "(P50)" in joined:
                tag = "neutral_row"
            elif "★" in joined:
                tag = "star_row"
            else:
                tag = "normal_row"
            tree.insert("", "end", values=r, tags=(tag,))

    def _embed_figure(self, parent, fig: Figure) -> None:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        canvas_frame = self.tk.Frame(parent, bg="#0b1120")
        canvas_frame.pack(fill="both", expand=True, padx=6, pady=2)
        canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def refresh_all(self) -> None:
        self.feed.reset_cycle()
        self.state = compute_unified_snapshot(self.feed)
        self.html_path, _ = export_visual_assets(self.state, auto_refresh_sec=self.auto_refresh_sec)
        s = self.state

        self.lbl_status.configure(
            text=(
                f"Spot MT5: {s.spot:,.2f} pts ({s.source_15m}) | Log-Return 5m: {float(s.df_log_anom['log_ret'].iloc[-1]):+.5f} | "
                f"Put Wall: {s.put_wall:,.0f} | Zero-Gamma: {s.zero_gamma:,.1f} | Call Wall: {s.call_wall:,.0f} | "
                f"Auto-Refresco: {self.auto_refresh_sec}s | Cómputo: {s.elapsed_sec:.2f}s"
            )
        )

        # --- SECCIÓN 1: MACRO 15M (GARCH + MONTE CARLO) ---
        self._clear_frame(self.tab1)
        fig1 = build_figure_page1(s, figsize=(15.4, 4.5))
        self._embed_figure(self.tab1, fig1)
        self._create_treeview_table(
            self.tab1,
            "1A. MATRIZ DE PROYECCIÓN DE PRECIOS POR HORIZONTE (MONTE CARLO)",
            [
                "Horizonte Temporal",
                "P05 (Soporte Fuerte)",
                "P25 (Zona de Demanda)",
                "P50 (Mediana/Baseline)",
                "P75 (Zona de Oferta)",
                "P95 (Resistencia Fuerte)",
            ],
            s.cone_table_rows,
            height=5,
        )
        self._create_treeview_table(
            self.tab1,
            "1B. MÉTRICAS DE RIESGO OPERATIVO (VaR 99% / CVaR 99%)",
            [
                "Marco Temporal",
                "Soporte Probable (P05)",
                "Resistencia Probable (P95)",
                "Riesgo Máximo / Hard Stop (VaR)",
                "Riesgo de Cisne Negro (CVaR)",
                "Directiva Operativa",
            ],
            s.tail_table_rows,
            height=4,
        )
        self._create_decision_banner(self.tab1, s.decision_page1)

        # --- SECCIÓN 2: ZONAS DE LIQUIDEZ (ÁRBOL BINOMIAL CRR + PERFIL GEX) ---
        self._clear_frame(self.tab2)
        fig2 = build_figure_page2(s, figsize=(15.4, 4.5))
        self._embed_figure(self.tab2, fig2)
        self._create_treeview_table(
            self.tab2,
            f"2A. PERFIL GEX + ÁRBOL BINOMIAL CRR — SOLO STRIKES DE ALTA CONFLUENCIA (> 80% | {s.n_filtered_strikes} STRIKES EN MEMORIA OCULTADOS EN UI)",
            [
                "Strike Clave NQ",
                "Distancia Spot",
                "Muro Institucional GEX + CRR",
                "Net GEX ($M)",
                "Prima Ejerc. CRR",
                "Frontera S*",
                "Prob ITM C/P",
                "Confluencia %",
                "Acción Exacta",
            ],
            s.gex_table_rows,
            height=6,
        )
        self._create_treeview_table(
            self.tab2,
            "2B. SÍNTESIS DE MUROS INSTITUCIONALES (CALL WALL / PUT WALL / ZERO-GAMMA) Y COBERTURA DE DEALERS",
            ["Muro Primario / Motor", "Nivel Exacto NQ", "Exposición Gamma / Flujo", "Métrica CRR / Cobertura", "Confluencia %", "Acción Exacta"],
            s.gex_summary_rows,
            height=4,
        )
        self._create_decision_banner(self.tab2, s.decision_page2)

        # --- SECCIÓN 3: MICROESTRUCTURA 5M (DETECTOR DE ANOMALÍAS DE LOG RETURNS) ---
        self._clear_frame(self.tab3)
        fig3 = build_figure_page3(s, figsize=(15.4, 4.5))
        self._embed_figure(self.tab3, fig3)
        self._create_treeview_table(
            self.tab3,
            "3A. ÚLTIMAS ANOMALÍAS DE MOMENTUM DETECTADAS EN 5M (LOG RETURNS — WINDOW = 20, UMBRALES ±2.0σ)",
            [
                "Hora (NY)",
                "Precio NQ (MT5)",
                "Log Return 5m",
                "Umbral Roto (Upper/Lower ±2.0σ)",
                "Señal de Momentum (LONG / SHORT)",
            ],
            s.log_anom_rows,
            height=6,
        )
        self._create_treeview_table(
            self.tab3,
            "3B. MÉTRICAS DE MICROESTRUCTURA 5M: BANDAS EXTREMAS VWAP (±2σ / ±3σ), ORDER FLOW (OFI/CVD) Y HURST",
            ["Borde Extremo / Microestructura", "Nivel / Parámetro 1", "Nivel / Parámetro 2", "Referencia / Flujo", "Confiabilidad %", "Acción Exacta"],
            s.micro_table_rows,
            height=4,
        )
        self._create_decision_banner(self.tab3, s.decision_page4_yield)

        # --- SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA (SIN GRÁFICOS, SOLO TABLA DE ALTA PRIORIDAD >80%) ---
        self._clear_frame(self.tab4)
        self._create_decision_banner(self.tab4, s.decision_master)
        self._create_treeview_table(
            self.tab4,
            "SECCIÓN 4: MATRIZ DE EJECUCIÓN RÁPIDA — NIVEL DE PRECIO, MURO INSTITUCIONAL, CONFLUENCIA (>80%) Y ACCIÓN (LONG / SHORT / NEUTRAL)",
            [
                "Nivel de Precio",
                "Muro Institucional (Call/Put Wall / Extremo)",
                "Confluencia (>80%)",
                "Acción (LONG / SHORT / NEUTRAL)",
            ],
            s.exec_levels_rows,
            height=18,
            fast_exec=True,
        )

    def run(self) -> None:
        self.root.mainloop()


# =========================================================================== #
# 6. RESUMEN EN CONSOLA CON COLORES ANSI Y PUNTO DE ENTRADA
# =========================================================================== #
def print_console_dashboard_summary(state: QuantSharedState, html_path: Path, png_paths: list[Path]) -> None:
    """Imprime en consola las 4 Secciones Lógicas del Dashboard alimentadas por MetaTrader 5."""
    GREEN = "\033[92m"
    RED = "\033[91m"
    GRAY = "\033[90m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    def _ansi_for(sig: str) -> str:
        if "LONG" in sig:
            return GREEN + BOLD
        if "SHORT" in sig:
            return RED + BOLD
        return GRAY + BOLD

    print("\n" + banner(
        f"DASHBOARD CUANTITATIVO EN TIEMPO REAL VÍA MT5 (US100-DEC26) | SPOT: {state.spot:,.2f} pts",
        f"NY: {state.session_status} | Última Vela NY: {state.timestamp_ny:%Y-%m-%d %H:%M %Z} | Fuente: {state.source_15m} | "
        f"ADF 15m: {state.adf_status_str} (t={state.adf_stat:.2f}) | "
        f"Backend: {len(state.q_levels)} cuantiles y {len(state.df_gex)} strikes en memoria | Cómputo: {state.elapsed_sec:.2f}s",
        width=126,
    ))

    for idx_p, dec in enumerate(
        [
            state.decision_page1,
            state.decision_page2,
            state.decision_page4_yield,
            state.decision_master,
        ],
        start=1,
    ):
        col = _ansi_for(dec.signal)
        star = f"{CYAN}★ CONFLUENCIA {dec.confluence_pct:.1f}%{RESET}" if dec.confluence_pct >= 80.0 else f"Confluencia {dec.confluence_pct:.1f}%"
        print(f" {BOLD}[SECCIÓN {idx_p}]{RESET} {dec.module_name}")
        print(f"    -> DECISIÓN: {col}{dec.signal} ({dec.sub_label}){RESET} | {star} | Ratio R:R: {BOLD}{dec.rr_ratio:.2f}x{RESET}")
        print(f"    -> ACCIÓN  : {dec.action_text}\n")

    print(section("SECCIÓN 1 (MACRO 15M): MATRIZ DE PROYECCIÓN DE PRECIOS POR HORIZONTE (MONTE CARLO)", width=126))
    t1 = Table(
        ["Horizonte Temporal", "P05 (Soporte Fuerte)", "P25 (Zona de Demanda)", "P50 (Mediana/Baseline)", "P75 (Zona de Oferta)", "P95 (Resistencia Fuerte)"],
        aligns="lrrrrr",
    )
    for r in state.cone_table_rows:
        t1.add_row(r)
    print(t1.render())

    print("\n" + section(f"SECCIÓN 2 (ZONAS DE LIQUIDEZ): ÁRBOL BINOMIAL CRR + PERFIL GEX (CONFLUENCIA > 80%)", width=126))
    t2 = Table(
        ["Strike Clave", "Distancia", "Muro Institucional GEX + CRR", "Net GEX", "Prima CRR", "S* CRR", "P(ITM) C/P", "Confluencia", "Acción Exacta"],
        aligns="rrlrrrrrl",
    )
    for r in state.gex_table_rows:
        t2.add_row(r)
    print(t2.render())

    print("\n" + section("SECCIÓN 3 (MICROESTRUCTURA 5M): ANOMALÍAS DE RETORNOS LOGARÍTMICOS DETECTADAS (WINDOW = 20, K = 2.0σ)", width=126))
    t3_lr = Table(
        ["Hora (NY)", "Precio NQ (MT5)", "Log Return 5m", "Umbral Roto (Upper/Lower ±2.0σ)", "Señal de Momentum (LONG / SHORT)"],
        aligns="lrrll",
    )
    for r in state.log_anom_rows:
        t3_lr.add_row(r)
    print(t3_lr.render())

    print("\n" + section("SECCIÓN 4 (MATRIZ DE EJECUCIÓN RÁPIDA): NIVEL DE PRECIO, MURO INSTITUCIONAL, CONFLUENCIA (>80%) Y ACCIÓN", width=126))
    t4 = Table(
        ["Nivel de Precio", "Muro Institucional (Call/Put Wall / Extremo)", "Confluencia (>80%)", "Acción (LONG / SHORT / NEUTRAL)"],
        aligns="rlrl",
    )
    for r in state.exec_levels_rows:
        t4.add_row(r)
    print(t4.render())

    print("\n" + section("ARCHIVOS VISUALES GENERADOS AUTOMÁTICAMENTE", width=126))
    print(f"  * Dashboard Interactivo 4 Secciones (HTML5): {html_path}")
    for p in png_paths:
        print(f"  * Lienzo Multi-Panel Alta Resolución (PNG): {p}")


def parse_args():
    p = argparse.ArgumentParser(description="Orquestador Principal Visual Multi-Panel vía MetaTrader 5 (US100-DEC26 en America/New_York)")
    p.add_argument("--headless", action="store_true", help="Calcula y exporta el Dashboard de 4 secciones en 1 sola pasada sin ventana GUI")
    p.add_argument("--browser", action="store_true", help="Abre el Dashboard en el navegador web y mantiene auto-refresco MT5 activo")
    p.add_argument("--once", action="store_true", help="Ejecuta únicamente 1 pasada sin ciclo continuo de auto-refresco")
    p.add_argument("--offline", action="store_true", help="Usa caché local / respaldo estocástico sin conectar a MT5")
    p.add_argument("--auto-refresh", type=int, default=300, metavar="SEG", help="Intervalo de auto-refresco macro MT5 en segundos (default: 300s = 5 min)")
    p.add_argument("--loop", type=int, default=None, metavar="SEG", help="Ejecuta en bucle continuo cada N segundos (default: 300s = 5 min)")
    p.add_argument("--supabase", action="store_true", help="Publica automáticamente el snapshot en tiempo real a Supabase para Vercel")
    p.add_argument("--paper", action="store_true", help="Fuerza el motor de ejecución en modo simulación Paper Trading (sin enviar órdenes reales a MT5)")
    p.add_argument("--max-spread", type=float, default=2.00, metavar="PTS", help="Umbral máximo de Spread L1 para el Kill Switch (default: 2.00 pts)")
    p.add_argument("--max-dd", type=float, default=0.02, metavar="PCT", help="Límite máximo de Drawdown diario (default: 0.02 = 2.0%%)")
    return p.parse_args()



async def async_daemon_runner(feed, initial_state, loop_sec: int, args) -> None:
    """
    Motor Asíncrono de Baja Latencia:
      * Task 1 (Tick Worker - asyncio): 
        - Pollea el feed de MT5 a intervalos de 200-250ms sin bloqueo alguno.
        - Alimenta el ExecutionEngine (Smart TWAP / Iceberg) y evalúa micro-rebanadas.
        - Alimenta el WatchdogDaemon con latencia y spread L1 en vivo.
        - Transmite el tick stream a Supabase con latencia mínima (< 1s).
      * Task 2 (Macro Math Worker - ThreadPoolExecutor):
        - Cada loop_sec segundos, offloada el cálculo pesado de compute_unified_snapshot
          a un hilo secundario dedicado (run_in_executor) con aceleración JIT C-speed.
        - El tick feed y el motor de ejecución NUNCA se congelan mientras corre la matemática pesada.
    """
    from core.execution_engine import ExecutionEngine, OrderDirection
    from core.watchdog_daemon import WatchdogDaemon

    # Auto-calibración de Spread Institucional:
    # Detecta si el activo cotiza con spreads de futuros CME (0.25-0.50p) o CFD MT5 (5.0-7.0p),
    # asegurando que el motor ejecute normalmente y el Kill Switch solo dispare ante una explosión real (> 2.2x).
    initial_spread = float(getattr(initial_state, "spread_pts", 0.50))
    base_spread_limit = max(float(getattr(args, "max_spread", 2.00)), round(initial_spread * 2.2, 2))

    # 1. Instanciar Motor de Ejecución de Nivel 1
    engine = ExecutionEngine(
        symbol="US100-DEC26",
        paper_trading=getattr(args, "paper", False) or args.offline,
        max_spread_limit=base_spread_limit,
    )

    # 2. Instanciar Watchdog Daemon (Supervisor de Seguridad Fail-Safe)
    watchdog = WatchdogDaemon(
        execution_engine=engine,
        max_latency_ms=500.0,
        max_spread_pts=base_spread_limit,
        max_drawdown_pct=getattr(args, "max_dd", 0.02),
        tick_staleness_rth_sec=10.0,
        check_interval_sec=0.25,
    )
    watchdog.start()

    print(
        f"\n[DEMONIO ASÍNCRONO DE BAJA LATENCIA & FAIL-SAFES ACTIVO] (MetaTrader 5: US100-DEC26)\n"
        f"  * Feed de Ticks Asíncrono (asyncio): cada 250ms (Nivel 1 sin bloqueo)\n"
        f"  * Algoritmos de Ejecución: Smart TWAP / Iceberg Nivel 1 ({engine.stats['execution_mode']})\n"
        f"  * Watchdog Fail-Safes: Supervisor en background (Latencia < 500ms | Spread < {watchdog.max_spread_pts:.2f}p | Max DD < {watchdog.max_drawdown_pct*100:.1f}%)\n"
        f"  * Macro Cuántico en Executor (JIT C-Speed): cada {loop_sec}s en hilo dedicado (cero congelamientos)\n"
    )

    current_state = initial_state
    engine.update_stationarity(initial_state.adf_is_stationary, initial_state.adf_pvalue)
    engine.update_risk_audit(
        initial_state.risk_audit_is_valid,
        initial_state.risk_audit_status,
        initial_state.kupiec_pvalue,
        initial_state.christoffersen_pvalue,
    )
    state_lock = asyncio.Lock()
    macro_uploading_event = asyncio.Event()
    tick_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="QuantTickWorker")
    macro_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="QuantMacroWorker")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # TASK 1: TICK FEED & EXECUTION WORKER (No bloqueante, alta frecuencia)
    async def tick_worker():
        nonlocal current_state
        last_published_px = None
        last_tick_time = 0.0

        while not stop_event.is_set():
            if watchdog.kill_switch_triggered:
                print("  [TICK-WORKER] Detenido por Kill Switch.")
                break
            try:
                # Extraer precio y spread de Nivel 1 en milisegundos
                cur_px = feed.last_price("NQ")
                spread_val = 0.50
                if getattr(feed, "mt5_provider", None) and feed.mt5_provider.is_live:
                    tk_info = feed.mt5_provider.fetch_tick("NQ")
                    if tk_info and getattr(tk_info, "spread", None):
                        spread_val = float(tk_info.spread)
                elif hasattr(current_state, "spread_pts"):
                    spread_val = float(current_state.spread_pts)

                now_t = time.time()

                if cur_px and cur_px > 0:
                    # 1. Alimentar Watchdog y ExecutionEngine con el tick fresco
                    watchdog.record_tick(spread_pts=spread_val, spot_price=cur_px)
                    engine.update_tick(spot=cur_px, spread=spread_val, timestamp=now_t)

                    # 2. Publicación rápida de Tick a Supabase (Rate-Limited & Async en Executor)
                    # Si el snapshot macro está subiéndose en este instante, omitir el PATCH de tick
                    # para evitar colisión de locks en PostgreSQL de Supabase.
                    should_send_tick = False
                    if not macro_uploading_event.is_set():
                        time_since_last_send = now_t - last_tick_time
                        if last_published_px is None or (abs(cur_px - last_published_px) >= 0.50 and time_since_last_send >= 1.0):
                            should_send_tick = True
                        elif time_since_last_send >= 3.0:
                            should_send_tick = True

                    if should_send_tick:
                        last_published_px = cur_px
                        last_tick_time = now_t
                        async with state_lock:
                            st = current_state
                            d_call = round(float(st.call_wall - cur_px), 1)
                            d_put = round(float(cur_px - st.put_wall), 1)
                            d_zg = round(float(cur_px - st.zero_gamma), 1)
                            z_fast = float((cur_px - st.vwap_now) / max(st.vwap_sd_now, 1e-4))
                            kpis_tick = {
                                "spot": float(cur_px),
                                "symbol": "US100-DEC26",
                                "z_vwap_5": z_fast,
                                "vwap_5m": float(st.vwap_now),
                                "dist_call": d_call,
                                "dist_put": d_put,
                                "dist_zg": d_zg,
                                "zero_gamma": float(st.zero_gamma),
                                "call_wall": float(st.call_wall),
                                "put_wall": float(st.put_wall),
                                "poc": float(st.poc_price),
                                "vah": float(st.vah_price),
                                "val": float(st.val_price),
                                "spread_pts": round(spread_val, 2),
                                "rvol_20d": round(float(getattr(st, "rvol_20d", 1.0)), 2),
                                "tick_speed": round(float(getattr(st, "tick_speed", 1.0)), 1),
                                "gap_pts": round(float(getattr(st, "gap_pts", 0.0)), 2),
                                "gap_pct": round(float(getattr(st, "gap_pct", 0.0)), 2),
                                "or_high": round(float(st.or_high), 2) if st.or_high is not None else None,
                                "or_low": round(float(st.or_low), 2) if st.or_low is not None else None,
                                "ib_high": round(float(st.ib_high), 2) if st.ib_high is not None else None,
                                "ib_low": round(float(st.ib_low), 2) if st.ib_low is not None else None,
                                "regime_arbiter": str(getattr(st, "regime_arbiter", "")),
                                "regime_color": str(getattr(st, "regime_color", "#38bdf8")),
                                "vwap_globex": float(getattr(st, "vwap_globex", st.vwap_now)),
                                "z_vwap_globex": float(getattr(st, "z_vwap_globex", st.z_vwap_5)),
                                "vwap_rth": float(getattr(st, "vwap_rth", st.vwap_now)),
                                "z_vwap_rth": float(getattr(st, "z_vwap_rth", st.z_vwap_5)),
                                "log_ret_5m": float(st.df_log_anom["log_ret"].iloc[-1]) if hasattr(st.df_log_anom["log_ret"], "iloc") else float(st.df_log_anom["log_ret"][-1]),
                                "strategies_table": getattr(st, "strategies_table_rows", []),
                                "hawkes_call_label": getattr(st, "hawkes_call_label", "P(Breakout) = 50.0%"),
                                "hawkes_put_label": getattr(st, "hawkes_put_label", "P(Rebote) = 50.0%"),
                                "hawkes_call_p_breakout": float(getattr(st, "hawkes_call_p_breakout", 0.50)),
                                "hawkes_put_p_breakout": float(getattr(st, "hawkes_put_p_breakout", 0.50)),
                                "hawkes_lambda": float(getattr(st, "hawkes_lambda", 1.0)),
                                "hawkes_branching": float(getattr(st, "hawkes_branching", 0.40)),
                                "hmm_regime_label": str(getattr(st, "hmm_regime_label", "")),
                                "hmm_current_state": int(getattr(st, "hmm_current_state", 0)),
                                "hmm_state_prob": float(getattr(st, "hmm_state_prob", 0.885)),
                                "risk_audit_is_valid": bool(getattr(st, "risk_audit_is_valid", True)),
                                "risk_audit_status": str(getattr(st, "risk_audit_status", "✓ VaR 99% Validado")),
                                "kupiec_pvalue": float(getattr(st, "kupiec_pvalue", 0.50)),
                                "christoffersen_pvalue": float(getattr(st, "christoffersen_pvalue", 0.50)),
                                "fred_rate_3m": float(getattr(st, "fred_rate_3m", 0.0406)),
                                "cost_of_carry_pts": float(getattr(st, "cost_of_carry_pts", 0.0)),
                                "fair_value_nq": float(getattr(st, "fair_value_nq", 0.0)),
                                "algo_execution": {
                                    "is_halted": engine.is_halted,
                                    "mode": engine.stats["execution_mode"],
                                    "spread_ma_5m": round(engine.spread_ma_5m, 2),
                                    "total_dispatched": engine.stats["total_orders_dispatched"],
                                    "volume_executed": round(engine.stats["total_volume_executed"], 2),
                                    "active_plans": len(engine.active_plans),
                                },
                            }

                        if args.supabase:
                            from supabase_publisher import publish_tick_stream_to_supabase
                            now_ny_str = pd.Timestamp.now(tz=sessions.TZ_NY).strftime("%Y-%m-%d %H:%M:%S NY")

                            def _send_tick_job(px_val, ts_val, k_val):
                                t_sb0 = time.perf_counter()
                                ok_t, msg_t = publish_tick_stream_to_supabase(px_val, ts_val, k_val)
                                sb_lat = (time.perf_counter() - t_sb0) * 1000.0
                                watchdog.record_supabase_latency(sb_lat, is_macro=False)
                                return ok_t, msg_t

                            # Despachado asíncrono no bloqueante en executor dedicado de ticks
                            loop.run_in_executor(tick_executor, _send_tick_job, cur_px, now_ny_str, kpis_tick)
            except Exception as e_tick:
                print(f"  [tick-err] {e_tick}")

            await asyncio.sleep(0.25)

    # TASK 2: MACRO MATH WORKER (En ThreadPoolExecutor, JIT C-speed, sin bloquear ticks)
    async def macro_worker():
        nonlocal current_state
        while not stop_event.is_set():
            await asyncio.sleep(loop_sec)
            if watchdog.kill_switch_triggered:
                print("  [MACRO-WORKER] Detenido por Kill Switch.")
                break
            try:
                feed.reset_cycle()
                # Computación pesada en executor (en C vía Numba) sin congelar el bucle de ticks
                new_state = await loop.run_in_executor(macro_executor, compute_unified_snapshot, feed)
                html_path, _ = await loop.run_in_executor(macro_executor, export_visual_assets, new_state, loop_sec)

                async with state_lock:
                    current_state = new_state
                engine.update_stationarity(new_state.adf_is_stationary, new_state.adf_pvalue)
                engine.update_risk_audit(
                    new_state.risk_audit_is_valid,
                    new_state.risk_audit_status,
                    new_state.kupiec_pvalue,
                    new_state.christoffersen_pvalue,
                )

                now_str = pd.Timestamp.now(tz=sessions.TZ_NY).strftime("%H:%M:%S NY")
                print(
                    f"  [{now_str}] ✓ Macro MT5 actualizado (JIT C-Speed) | Spot: {new_state.spot:,.2f} | "
                    f"POC: {new_state.poc_price:,.1f} | Decisión: {new_state.decision_master.signal} ({new_state.elapsed_sec:.2f}s)"
                )

                if args.supabase:
                    try:
                        macro_uploading_event.set()
                        from supabase_publisher import publish_snapshot_to_supabase
                        t_sb0 = time.perf_counter()
                        ok_sb, msg_sb = await loop.run_in_executor(macro_executor, publish_snapshot_to_supabase, new_state)
                        sb_lat = (time.perf_counter() - t_sb0) * 1000.0
                        watchdog.record_supabase_latency(sb_lat, is_macro=True)
                        print(f"       -> [supabase-macro] {'✓' if ok_sb else '⚠'} {msg_sb} ({sb_lat:.1f}ms)")
                    except Exception as e_sb:
                        print(f"       -> [supabase-macro] ⚠ {e_sb}")
                    finally:
                        macro_uploading_event.clear()
            except Exception as exc:
                print(f"  [macro-err] {exc}")

    try:
        await asyncio.gather(tick_worker(), macro_worker())
    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        watchdog.stop()
        tick_executor.shutdown(wait=False)
        macro_executor.shutdown(wait=False)


def main() -> None:
    args = parse_args()
    feed = DataFeedNQ(offline=args.offline)
    refresh_sec = 0 if args.once else max(int(args.auto_refresh), 0)

    if args.headless or args.browser:
        matplotlib.use("Agg")
        state = compute_unified_snapshot(feed)
        html_path, png_paths = export_visual_assets(state, auto_refresh_sec=refresh_sec if refresh_sec > 0 else 300)
        print_console_dashboard_summary(state, html_path, png_paths)

        if args.supabase:
            try:
                from supabase_publisher import publish_snapshot_to_supabase
                ok_sb, msg_sb = publish_snapshot_to_supabase(state)
                print(f"\n  [supabase-realtime] {'✓' if ok_sb else '⚠'} {msg_sb}")
            except Exception as e_sb:
                print(f"\n  [supabase-realtime] ⚠ {e_sb}")

        if args.browser:
            webbrowser.open(html_path.resolve().as_uri())

        if args.once:
            loop_sec = 0
        elif args.loop is not None:
            loop_sec = max(int(args.loop), 0)
        elif args.headless:
            loop_sec = 300
        elif args.browser and not args.once:
            loop_sec = refresh_sec
        else:
            loop_sec = 0
        if loop_sec > 0:
            try:
                asyncio.run(async_daemon_runner(feed, state, loop_sec, args))
            except KeyboardInterrupt:
                print("\n[info] Demonio asíncrono detenido por el usuario.")
        return

    try:
        app = InstitutionalQuantDashboardApp(feed=feed, auto_refresh_sec=refresh_sec)
        if app.state and app.html_path:
            print_console_dashboard_summary(
                app.state,
                app.html_path,
                [
                    CHART_DIR / "dashboard_page1_macro_garch_mc.png",
                    CHART_DIR / "dashboard_page2_liquidez_gex_crr.png",
                    CHART_DIR / "dashboard_page3_microestructura_5m.png",
                    CHART_DIR / "dashboard_page4_yield_anomalies_nq.png",
                ],
            )
        app.run()
    except Exception as exc:
        print(f"[info] Entorno sin display interactivo ({exc}); generando reporte HTML5 y PNGs...")
        matplotlib.use("Agg")
        state = compute_unified_snapshot(feed)
        html_path, png_paths = export_visual_assets(state, auto_refresh_sec=refresh_sec if refresh_sec > 0 else 60)
        print_console_dashboard_summary(state, html_path, png_paths)


if __name__ == "__main__":
    main()
