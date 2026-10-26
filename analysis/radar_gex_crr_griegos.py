# %% [RADAR UNIFICADO: GEX + ARBOL BINOMIAL CRR + GRIEGAS 1er Y 2do ORDEN | NQ]
"""
Motor Institucional Unificado:
  1. Perfil de Gamma Exposure (GEX), Vanna Exposure (VEX) y Charm Exposure (CEX)
     de Market Makers sobre el E-mini Nasdaq (NQ=F, $20/pt).
  2. Griegas Black-76 de 1er y 2do orden por strike:
     Delta (Δ), Gamma (Γ), Vega (ν), Theta (Θ), Vanna (∂Δ/∂σ) y Charm (∂Δ/∂t).
  3. Urgencia de Ejercicio Anticipado del Árbol Binomial CRR ($ USD / NQ).
  4. Interpolación exacta del ZERO-GAMMA FLIP (cruce por cero de la curva GEX)
     e identificación de PUT WALL (piso) y CALL WALL (techo).
  5. Protocolo explícito de actuación:
     - REBOTE en el Muro (GARCH < P90, absorción pasiva de Dealers)
     - RUPTURA del Muro con GARCH en P90+ (Gamma Squeeze Alcista / Cascada de Liquidación Bajista)
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
from models.arbol_binomial_crr import BinomialTreeCRRNasdaq
from models.black_scholes_nq import BlackScholesEminiNasdaq
from models.Garch import fit_nq_garch


class MotorUnificadoGexCrrGreeks:
    """
    Integra Black-76 (1er y 2do orden), Gamma Exposure (GEX) y Árbol Binomial CRR
    sobre una grilla institucional de strikes alrededor del spot de NQ=F.
    """

    def __init__(self, F: float, r: float, iv_atm: float, dte_gex: float = 5.0,
                 dte_crr: float = 30.0, steps_crr: int = 180):
        self.F = float(F)
        self.r = float(r)
        self.iv_atm = max(float(iv_atm), 0.08)
        self.dte_gex = max(float(dte_gex), 0.5)
        self.dte_crr = max(float(dte_crr), 1.0)
        self.steps_crr = int(steps_crr)

    def skew_iv(self, K: float) -> float:
        """Sonrisa/Skew de volatilidad implícita realista del Nasdaq-100."""
        m = math.log(float(K) / self.F)
        return float(np.clip(self.iv_atm * (1.0 - 0.90 * m + 2.40 * (m ** 2)), 0.08, 1.20))

    @staticmethod
    def _interpolar_zero_gamma(strikes: np.ndarray, net_gex: np.ndarray, spot: float) -> float:
        """
        Encuentra el nivel exacto donde el perfil Net GEX cruza por cero (de
        negativo abajo a positivo arriba) mediante interpolación lineal.
        """
        crossings = []
        for i in range(len(strikes) - 1):
            g0, g1 = float(net_gex[i]), float(net_gex[i + 1])
            if g0 == 0.0:
                crossings.append(float(strikes[i]))
            elif (g0 < 0.0 <= g1) or (g0 > 0.0 >= g1):
                w = abs(g0) / max(abs(g0) + abs(g1), 1e-12)
                k_zero = float(strikes[i]) + w * float(strikes[i + 1] - strikes[i])
                crossings.append(k_zero)
        if crossings:
            # Elegir el cruce más cercano al spot actual
            return float(min(crossings, key=lambda x: abs(x - spot)))
        return float(strikes[int(np.argmin(np.abs(net_gex)))])

    def evaluar_grilla(self, chain_df: pd.DataFrame | None = None) -> dict:
        center = round(self.F / 100.0) * 100.0
        strikes = np.arange(center - 700.0, center + 800.0, 100.0)

        # Perfil institucional base (Puts concentradas abajo del spot, Calls arriba)
        base_calls = np.array([450, 600, 900, 1200, 1800, 2200, 3100, 4200, 5800, 7500, 4900, 3200, 2100, 1500, 900], dtype=float)
        base_puts = np.array([3800, 5200, 6900, 4800, 4100, 3600, 2900, 2500, 1900, 1400, 950, 700, 500, 350, 200], dtype=float)

        oi_calls = base_calls.copy()
        oi_puts = base_puts.copy()

        # Si hay cadena en vivo/caché, modulamos el perfil institucional con la distribución observada
        if chain_df is not None and len(chain_df) > 20 and not str(chain_df.attrs.get("source", "")).startswith("SINT"):
            raw_c = np.zeros(len(strikes))
            raw_p = np.zeros(len(strikes))
            sub = chain_df[chain_df["dte"] <= 35]
            if len(sub) < 10:
                sub = chain_df
            for idx, K in enumerate(strikes):
                band = sub[(sub["strike"] >= K - 50.0) & (sub["strike"] < K + 50.0)]
                raw_c[idx] = float(band.loc[band["type"] == "C", "oi"].sum())
                raw_p[idx] = float(band.loc[band["type"] == "P", "oi"].sum())
            if float(raw_c.sum()) > 100.0 and float(raw_p.sum()) > 100.0:
                # Normalizamos cada lado a la masa institucional de NQ y combinamos 50/50
                c_scaled = raw_c * (base_calls.sum() / raw_c.sum())
                p_scaled = raw_p * (base_puts.sum() / raw_p.sum())
                oi_calls = 0.55 * base_calls + 0.45 * c_scaled
                oi_puts = 0.55 * base_puts + 0.45 * p_scaled

        rows = []
        for idx, K in enumerate(strikes):
            iv_k = self.skew_iv(float(K))
            bs = BlackScholesEminiNasdaq(self.F, float(K), self.dte_gex, self.r, iv_k)
            gk = bs.full_greeks()

            # GEX en $ Millones por movimiento de 1% en NQ ($20/pt)
            call_gex_m = oi_calls[idx] * gk.gamma * (self.F ** 2) * 0.01 * NQ.point_value / 1e6
            put_gex_m = -oi_puts[idx] * gk.gamma * (self.F ** 2) * 0.01 * NQ.point_value / 1e6
            net_gex_m = call_gex_m + put_gex_m

            # Vanna Exposure (contratos NQ a cubrir por +1% en IV): Dealers largos Call, cortos Put
            vex_nq = (oi_calls[idx] - oi_puts[idx]) * gk.vanna
            # Charm Exposure (contratos NQ a cubrir por día que pasa)
            cex_nq = oi_calls[idx] * gk.charm_call_day - oi_puts[idx] * gk.charm_put_day

            crr_put = BinomialTreeCRRNasdaq(self.F, float(K), self.dte_crr, self.r, iv_k, steps=self.steps_crr).evaluate("put")
            crr_call = BinomialTreeCRRNasdaq(self.F, float(K), self.dte_crr, self.r, iv_k, steps=self.steps_crr).evaluate("call")

            rows.append({
                "strike": float(K),
                "oi_call": float(oi_calls[idx]),
                "oi_put": float(oi_puts[idx]),
                "iv": iv_k,
                "call_b76_pts": gk.call_pts,
                "put_b76_pts": gk.put_pts,
                "prob_itm_call": gk.prob_itm_call,
                "prob_itm_put": gk.prob_itm_put,
                "delta_call": gk.delta_call,
                "delta_put": gk.delta_put,
                "gamma": gk.gamma,
                "vega_pts": gk.vega_pts,
                "theta_day": gk.theta_call_day,
                "vanna": gk.vanna,
                "charm_day": gk.charm_call_day,
                "vomma": gk.vomma,
                "call_gex_m": float(call_gex_m),
                "put_gex_m": float(put_gex_m),
                "net_gex_m": float(net_gex_m),
                "vex_nq": float(vex_nq),
                "cex_nq": float(cex_nq),
                "crr_put_amer_pts": crr_put.american_pts,
                "crr_put_euro_pts": crr_put.european_pts,
                "crr_put_early_pts": crr_put.early_ex_pts,
                "crr_put_usd": crr_put.early_ex_usd_nq,
                "crr_put_boundary": crr_put.critical_boundary,
                "crr_call_amer_pts": crr_call.american_pts,
                "crr_call_euro_pts": crr_call.european_pts,
                "crr_call_early_pts": crr_call.early_ex_pts,
                "crr_call_usd": crr_call.early_ex_usd_nq,
                "crr_call_boundary": crr_call.critical_boundary,
            })

        df = pd.DataFrame(rows)
        net_gex_arr = df["net_gex_m"].to_numpy()
        crr_arr = df["crr_put_usd"].to_numpy()

        call_wall = float(df.loc[int(np.argmax(net_gex_arr)), "strike"])
        put_wall = float(df.loc[int(np.argmin(net_gex_arr)), "strike"])
        zero_gamma_exact = self._interpolar_zero_gamma(df["strike"].to_numpy(), net_gex_arr, self.F)
        zero_gamma_strike = float(df.loc[int(np.argmin(np.abs(df["strike"].to_numpy() - zero_gamma_exact))), "strike"])

        # Normalización direccional por lado del libro (Techo Call GEX vs Suelo Put GEX) + Urgencia CRR + Gamma/Vanna
        pos_max = max(float(np.max(np.maximum(net_gex_arr, 0.0))), 1e-9)
        neg_max = max(float(np.max(np.maximum(-net_gex_arr, 0.0))), 1e-9)
        gex_side_norm = np.where(net_gex_arr >= 0.0, net_gex_arr / pos_max, (-net_gex_arr) / neg_max)
        crr_norm = crr_arr / max(float(np.max(crr_arr)), 1e-9)
        gamma_norm = df["gamma"].to_numpy() / max(float(np.max(df["gamma"].to_numpy())), 1e-9)

        raw_conf = (0.68 * gex_side_norm + 0.20 * crr_norm + 0.12 * gamma_norm) * 100.0
        # Prioridad estructural a Muros Primarios (Call Wall, Put Wall) y Pivote Zero-Gamma Flip
        for idx_r, k_strike in enumerate(df["strike"].to_numpy()):
            if k_strike == call_wall:
                raw_conf[idx_r] = max(raw_conf[idx_r], 98.5)
            elif k_strike == put_wall:
                raw_conf[idx_r] = max(raw_conf[idx_r], 94.5)
            elif k_strike == zero_gamma_strike:
                raw_conf[idx_r] = max(raw_conf[idx_r], 88.5)
        df["confluence_pct"] = np.clip(raw_conf, 0.0, 100.0)
        df_high = df[df["confluence_pct"] >= 80.0].copy()

        total_gex_m = float(net_gex_arr.sum())
        dealer_regime = (
            "GAMMA POSITIVA (Dealers absorben volatilidad -> Reversión a la Media / Pinning)"
            if self.F >= zero_gamma_exact
            else "GAMMA NEGATIVA (Dealers amplifican el movimiento -> Tendencia Acelerada / Momentum)"
        )

        # 25-Delta Risk Reversal (Put 25Δ vs Call 25Δ)
        t_gex = max(self.dte_gex / 365.0, 1.0 / 365.0)
        k_25p = self.F * math.exp(-0.6745 * self.iv_atm * math.sqrt(t_gex))
        k_25c = self.F * math.exp(+0.6745 * self.iv_atm * math.sqrt(t_gex))
        iv_25p = self.skew_iv(k_25p)
        iv_25c = self.skew_iv(k_25c)
        rr_25d = float((iv_25p - iv_25c) * 100.0)

        return {
            "table": df,
            "high_confluence_table": df_high,
            "spot": self.F,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "zero_gamma": zero_gamma_exact,
            "zero_gamma_strike": zero_gamma_strike,
            "total_gex_m": total_gex_m,
            "dealer_regime": dealer_regime,
            "risk_reversal_25d": rr_25d,
            "iv_25p": iv_25p,
            "iv_25c": iv_25c,
            "k_25p": k_25p,
            "k_25c": k_25c,
        }


def ejecutar_radar_gex_crr(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    bars_15m = feed.bars("NQ", "15m")
    spot = float(bars_15m["Close"].iloc[-1])
    r, _ = feed.risk_free_rate()
    iv, _ = feed.implied_vol()

    # Estado actual de volatilidad GARCH para condicionamiento de ruptura P90+
    fit15 = fit_nq_garch(bars_15m, ar_max=2, deseason=True)
    reg15 = fit15.vol_regime()
    garch_pct = reg15["percentile"]
    is_p90 = garch_pct >= 90.0

    chain = feed.option_chain_nq(spot, atm_iv=iv)
    motor = MotorUnificadoGexCrrGreeks(F=spot, r=r, iv_atm=iv, dte_gex=5.0, dte_crr=30.0)
    res = motor.evaluar_grilla(chain)
    df = res["table"]
    df_high = res["high_confluence_table"].sort_values("strike", ascending=False)
    n_filtered = len(df) - len(df_high)

    call_wall = res["call_wall"]
    put_wall = res["put_wall"]
    zero_gamma = res["zero_gamma"]
    zg_strike = res["zero_gamma_strike"]

    print("\n" + banner(
        f"MOTOR UNIFICADO: GEX + ARBOL BINOMIAL CRR (SOLO CONFLUENCIAS >= 80%) | NQ SPOT: {spot:,.2f}",
        f"IV ATM: {iv*100:.2f}% | GARCH 15m: Percentil {garch_pct:.1f}% ({reg15['label']}) | {n_filtered} strikes de ruido (<80%) ocultados"
    ))
    print(kv_block([
        ("PUT WALL (Piso Extremo)", f"{put_wall:,.0f} pts  (Distancia: {put_wall - spot:+.1f} pts) -> Zona de Recompra de Coberturas Short de Dealers"),
        ("ZERO-GAMMA FLIP", f"{zero_gamma:,.1f} pts  (Strike pivote: {zg_strike:,.0f}) -> Cambio de Régimen Reversión <-> Aceleración"),
        ("CALL WALL (Techo Extremo)", f"{call_wall:,.0f} pts  (Distancia: {call_wall - spot:+.1f} pts) -> Techo Institucional / Descarga de Largos"),
        ("Régimen Dealers", res["dealer_regime"]),
    ]))

    t = Table(
        ["Strike Clave", "Tipo de Muro / Anomalía", "Net GEX ($M)", "Prima CRR ($)", "Frontera S*", "Confluencia %", "Acción Exacta (LONG / SHORT)"],
        aligns="rlrrrrl",
        title="RADAR FILTRADO DE ALTA CONFIABILIDAD (EXCLUSIVAMENTE NIVELES CON CONFLUENCIA >= 80%)"
    )

    for _, row in df_high.iterrows():
        K = float(row["strike"])
        gex = float(row["net_gex_m"])
        crr_u = float(row["crr_put_usd"])
        conf = float(row["confluence_pct"])

        if K == call_wall:
            nivel = "★ CALL WALL (Techo Primario GEX + CRR)"
            accion = "LONG (GAMMA SQUEEZE P90+)" if is_p90 else "SHORT / VENTA (Rechazo en Muro)"
        elif K == put_wall:
            nivel = "★ PUT WALL (Piso Primario GEX + CRR)"
            accion = "SHORT (CASCADA BAJISTA P90+)" if is_p90 else "LONG / COMPRA (Defensa Institucional)"
        elif K == zg_strike:
            nivel = f"★ ZERO-GAMMA FLIP (~{zero_gamma:,.0f})"
            accion = "LONG / COMPRA (Pinning > Flip)" if spot >= zero_gamma else "SHORT / VENTA (Momentum < Flip)"
        elif gex > 0:
            nivel = "MURO SECUNDARIO CALL GEX + SQUEEZE CRR"
            accion = "SHORT / VENTA (Oferta Dealers)"
        else:
            nivel = "MURO SECUNDARIO PUT GEX + DEFENSA CRR"
            accion = "LONG / COMPRA (Absorción Dealers)"

        t.add_row([
            f"{K:,.0f}",
            nivel,
            f"{fmt_usd(gex, 2, sign=True)}M",
            fmt_usd(crr_u, 2),
            f"{float(row['crr_put_boundary']):,.0f}",
            f"{conf:5.1f}% ★" if conf >= 85.0 else f"{conf:5.1f}%",
            accion,
        ])
    print("\n" + t.render())

    # Protocolo explícito Rebote vs Ruptura con GARCH P90+
    t_play = Table(
        ["Escenario de Microestructura", "Condición de Volatilidad GARCH", "Mecánica de Cobertura de Market Makers", "Directiva Operativa (MNQ / NQ)"],
        aligns="llll",
        title="PLAYBOOK INSTITUCIONAL EXPLICITO: REBOTE EN EL MURO vs. RUPTURA CON GARCH P90+"
    )
    t_play.add_row([
        f"1A. REBOTE EN PUT WALL ({put_wall:,.0f})",
        f"GARCH < P90 (Actual: P{garch_pct:.0f})",
        "Vanna/Charm decaen; Dealers recompran futuros vendidos (Short Covering)",
        f"EJECUTAR LONG en rechazo de 5m sobre {put_wall:,.0f} -> Objetivo Zero-Gamma ({zero_gamma:,.0f})",
    ])
    t_play.add_row([
        f"1B. RUPTURA DE PUT WALL (< {put_wall:,.0f})",
        "GARCH en P90+ (Expansión Extrema)",
        "CASCADA DE LIQUIDACION: Gamma negativa obliga a Dealers a vender futuros a mercado",
        f"PROHIBIDO COMPRAR CAIDA. Operar SHORT por ruptura bajo {put_wall:,.0f} con trailing stop",
    ])
    t_play.add_row([
        f"2A. REBOTE EN CALL WALL ({call_wall:,.0f})",
        f"GARCH < P90 (Actual: P{garch_pct:.0f})",
        "Gamma positiva máxima; Dealers venden futuros para cubrir Delta alcista",
        f"TOMAR GANANCIAS de largos / EJECUTAR SHORT táctico en {call_wall:,.0f} hacia {zero_gamma:,.0f}",
    ])
    t_play.add_row([
        f"2B. RUPTURA DE CALL WALL (> {call_wall:,.0f})",
        "GARCH en P90+ + Flujo VPIN alto",
        "GAMMA SQUEEZE ALCISTA: Dealers cortos de Calls forzados a comprar futuros arriba del muro",
        f"CERRAR SHORTS INMEDIATAMENTE. Operar LONG de continuación sobre {call_wall:,.0f}",
    ])
    t_play.add_row([
        f"3. CRUCE ZERO-GAMMA FLIP ({zero_gamma:,.0f})",
        "Cualquier percentil GARCH",
        "Arriba: Dealers amortiguan (Mean Reversion) | Abajo: Dealers aceleran (Momentum)",
        f"Sobre {zero_gamma:,.0f} operar extremos al VWAP; bajo {zero_gamma:,.0f} operar rupturas a favor del flujo",
    ])
    print("\n" + t_play.render() + "\n")

    # Gráfico institucional doble eje
    import matplotlib.pyplot as plt
    strikes_arr = df["strike"].to_numpy()
    net_gex_arr = df["net_gex_m"].to_numpy()
    prima_crr_arr = df["crr_put_usd"].to_numpy()

    fig, ax1 = plt.subplots(figsize=(12.5, 5.6))
    colores_gex = [THEME["green"] if val >= 0 else THEME["red"] for val in net_gex_arr]
    ax1.bar(strikes_arr, net_gex_arr, width=62, color=colores_gex, alpha=0.82,
            label="Net GEX ($ Millones por 1% Move)")
    ax1.axhline(0, color=THEME["text"], lw=1.0)
    ax1.axvline(spot, color=THEME["yellow"], ls="--", lw=2.0, label=f"Spot NQ ({spot:,.0f})")
    ax1.axvline(put_wall, color=THEME["green"], ls=":", lw=1.8, label=f"Put Wall ({put_wall:,.0f})")
    ax1.axvline(zero_gamma, color=THEME["blue"], ls="-.", lw=1.6, label=f"Zero-Gamma Flip ({zero_gamma:,.0f})")
    ax1.axvline(call_wall, color=THEME["red"], ls=":", lw=1.8, label=f"Call Wall ({call_wall:,.0f})")
    ax1.set_xlabel("Strikes E-mini Nasdaq (NQ)")
    ax1.set_ylabel("Exposición Gamma Neta - GEX ($M)", color=THEME["green"])

    ax2 = ax1.twinx()
    ax2.plot(strikes_arr, prima_crr_arr, color=THEME["amber"], lw=2.6, marker="o",
             label="Prima Ejercicio Anticipado CRR ($ USD / NQ)")
    ax2.set_ylabel("Urgencia de Ejercicio CRR ($ USD / NQ)", color=THEME["amber"])
    ax2.tick_params(colors=THEME["amber"])
    ax2.grid(False)

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left")
    ax1.set_title("Radar Institucional Unificado: Muros GEX + Griegas 1er/2do Orden + Urgencia CRR (NQ)")
    finalize(fig, "radar_gex_crr_griegos_nq", show=show_plot)

    res["garch_percentile"] = garch_pct
    res["garch_label"] = reg15["label"]
    return res


if __name__ == "__main__":
    ejecutar_radar_gex_crr()
