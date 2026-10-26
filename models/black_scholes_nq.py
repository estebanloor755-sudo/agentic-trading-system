# %% [BLACK-76 & MOTOR DE GRIEGAS 1er Y 2do ORDEN | TERMINAL NQ]
"""
Valuación Black-76 para opciones sobre futuros del E-mini Nasdaq (NQ=F / MNQ=F).

Calcula:
  * Prima teórica Call y Put (en puntos y USD)
  * Griegas de 1er orden: Delta (Δ), Gamma (Γ), Vega (ν), Theta (Θ diario)
  * Griegas de 2do orden: Vanna (∂Δ/∂σ), Charm (∂Δ/∂t diario), Vomma (∂ν/∂σ)
  * Rango implícito intradía (15m / 1h), diario (1D) y semanal (5D)
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MNQ, NQ, THEME
from core.mathx import norm_cdf, norm_pdf


@dataclass
class Black76Greeks:
    call_pts: float
    put_pts: float
    delta_call: float
    delta_put: float
    gamma: float
    vega_pts: float          # pts por +1% (+0.01) en IV
    theta_call_day: float    # pts por día calendario
    theta_put_day: float
    vanna: float             # cambio en Delta por +1% (+0.01) en IV
    charm_call_day: float    # cambio en Delta Call por 1 día que pasa
    charm_put_day: float
    vomma: float             # cambio en Vega por +1% en IV
    prob_itm_call: float     # % N(d2)
    prob_itm_put: float      # % N(-d2)
    d1: float
    d2: float


class BlackScholesEminiNasdaq:
    """Modelo Black-76 vectorizado o escalar sobre futuros NQ=F."""

    def __init__(self, F: float, K: float | np.ndarray, T_days: float, r: float, iv: float | np.ndarray):
        self.F = float(F)
        self.K = K
        self.T_days = max(float(T_days), 0.05)
        self.T = max(self.T_days / 365.0, 1e-6)
        self.r = float(r)
        self.iv = np.maximum(iv, 1e-4)

    def _d1_d2(self):
        sqrtT = np.sqrt(self.T)
        sig_sqrtT = self.iv * sqrtT
        d1 = (np.log(self.F / self.K) + 0.5 * (self.iv ** 2) * self.T) / sig_sqrtT
        d2 = d1 - sig_sqrtT
        return d1, d2, sqrtT, sig_sqrtT

    def full_greeks(self) -> Black76Greeks:
        """Retorna todas las Griegas de 1er y 2do orden para NQ=F (Black-76)."""
        d1, d2, sqrtT, sig_sqrtT = self._d1_d2()
        df = math.exp(-self.r * self.T)
        nd1 = norm_pdf(d1)
        Nd1 = norm_cdf(d1)
        Nd2 = norm_cdf(d2)
        Nmd1 = norm_cdf(-d1)
        Nmd2 = norm_cdf(-d2)

        call_pts = df * (self.F * Nd1 - self.K * Nd2)
        put_pts = df * (self.K * Nmd2 - self.F * Nmd1)

        delta_call = df * Nd1
        delta_put = -df * Nmd1
        gamma = df * nd1 / (self.F * sig_sqrtT)

        # Vega expresada por +1 punto porcentual (+0.01) de cambio en IV
        vega_pts = (df * self.F * nd1 * sqrtT) * 0.01

        # Theta Black-76 anual -> dividido entre 365 para lectura diaria
        theta_common = -(df * self.F * nd1 * self.iv) / (2.0 * sqrtT)
        theta_call_yr = theta_common + self.r * call_pts
        theta_put_yr = theta_common + self.r * put_pts
        theta_call_day = theta_call_yr / 365.0
        theta_put_day = theta_put_yr / 365.0

        # Griegas de 2do orden:
        # Vanna = ∂Delta/∂sigma = -df * phi(d1) * (d2 / sigma) -> escalado por 0.01 (1 vol pt)
        vanna = (-df * nd1 * (d2 / self.iv)) * 0.01

        # Charm = -∂Delta/∂T (decaimiento de Delta por día hacia el vencimiento)
        # En Black-76: ∂(df*N(d1))/∂T = -r*df*N(d1) + df*phi(d1)*(-d2/(2T))
        # Por tanto, el cambio en Delta cuando pasa dt = +1/365 días es -∂Delta/∂T / 365:
        charm_call_day = (self.r * delta_call + df * nd1 * (d2 / (2.0 * self.T))) / 365.0
        charm_put_day = (self.r * delta_put + df * nd1 * (d2 / (2.0 * self.T))) / 365.0

        # Vomma (Volga) = ∂Vega/∂sigma por +1% IV
        vomma = vega_pts * (d1 * d2 / self.iv) * 0.01

        return Black76Greeks(
            call_pts=float(call_pts),
            put_pts=float(put_pts),
            delta_call=float(delta_call),
            delta_put=float(delta_put),
            gamma=float(gamma),
            vega_pts=float(vega_pts),
            theta_call_day=float(theta_call_day),
            theta_put_day=float(theta_put_day),
            vanna=float(vanna),
            charm_call_day=float(charm_call_day),
            charm_put_day=float(charm_put_day),
            vomma=float(vomma),
            prob_itm_call=float(Nd2 * 100.0),
            prob_itm_put=float(Nmd2 * 100.0),
            d1=float(d1),
            d2=float(d2),
        )

    def metrics(self):
        """Compatibilidad directa con tuplas (call, put, delta_call, gamma, prob_itm)."""
        g = self.full_greeks()
        return g.call_pts, g.put_pts, g.delta_call, g.gamma, g.prob_itm_call


def implied_ranges_nq(spot: float, iv: float) -> dict:
    """Rangos implícitos 1-SD (68.2%) y 2-SD (95.4%) para distintas ventanas."""
    horizons = {
        "15m (Macro Bar)": 1.0 / (252.0 * 26.0),
        "1h (Intradía)": 1.0 / (252.0 * 6.5),
        "1D (Sesión Diaria)": 1.0 / 252.0,
        "5D (Semanal)": 5.0 / 252.0,
        "30D (Mensual)": 30.0 / 365.0,
    }
    out = {}
    for label, T_yr in horizons.items():
        sd1 = spot * iv * math.sqrt(T_yr)
        out[label] = {
            "sd1_pts": sd1,
            "sd2_pts": 2.0 * sd1,
            "low_1sd": spot - sd1,
            "high_1sd": spot + sd1,
            "mnq_1sd_usd": sd1 * MNQ.point_value,
            "nq_1sd_usd": sd1 * NQ.point_value,
        }
    return out


def ejecutar_black_scholes_interactivo(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd

    feed = feed or DataFeedNQ()
    spot_raw = feed.last_price("NQ", "15m")
    futuro_nq = round(spot_raw / 25.0) * 25.0
    tasa_fed, r_src = feed.risk_free_rate()
    vol_implicita, iv_src = feed.implied_vol()
    dias_vencimiento = 5.0

    print("\n" + banner(
        f"VALUACION BLACK-76 & GRIEGAS 1er/2do ORDEN | SPOT NQ: {spot_raw:,.2f} (ATM: {futuro_nq:,.0f})",
        f"VXN/IV: {vol_implicita*100:.2f}% [{iv_src}] | Tasa r: {tasa_fed*100:.2f}% [{r_src}] | DTE: {dias_vencimiento:.0f}d"
    ))

    # 1. Tabla de Rangos Implícitos
    ranges = implied_ranges_nq(spot_raw, vol_implicita)
    t_rng = Table(
        ["Horizonte", "±1 SD (68.2%)", "Rango 1-SD [Piso - Techo]", "±2 SD (95.4%)", "Valor 1-SD (1 MNQ)", "Valor 1-SD (1 NQ)"],
        aligns="lrcrrr",
        title="RANGOS IMPLICITOS DEL E-MINI NASDAQ SEGUN VOLATILIDAD IMPLICITA (VXN)"
    )
    for h_label, info in ranges.items():
        t_rng.add_row([
            h_label,
            f"±{fmt_num(info['sd1_pts'], 1)} pts",
            f"[{fmt_num(info['low_1sd'], 0)}  -  {fmt_num(info['high_1sd'], 0)}]",
            f"±{fmt_num(info['sd2_pts'], 1)} pts",
            fmt_usd(info["mnq_1sd_usd"], 0),
            fmt_usd(info["nq_1sd_usd"], 0),
        ])
    print(t_rng.render())

    # 2. Cadena de Opciones + Griegas 1er y 2do Orden
    strikes = np.arange(futuro_nq - 500, futuro_nq + 550, 50)
    t_opt = Table(
        ["Strike", "Moneyness", "Call (Pts)", "Put (Pts)", "Delta C", "Gamma", "Vega/1%", "Theta/d", "Vanna", "Charm/d", "Prob ITM"],
        aligns="rrrrrrrrrrr",
        title="CADENA BLACK-76 NQ: GRIEGAS DE 1er ORDEN (Δ, Γ, ν, Θ) Y 2do ORDEN (VANNA, CHARM)"
    )

    c_list, p_list, vanna_list, charm_list = [], [], [], []
    for k in strikes:
        # Incorpora un skew realista alrededor de la IV ATM
        m_log = math.log(float(k) / spot_raw)
        iv_k = max(vol_implicita * (1.0 - 0.85 * m_log + 2.2 * (m_log ** 2)), 0.08)
        bs = BlackScholesEminiNasdaq(spot_raw, float(k), dias_vencimiento, tasa_fed, iv_k)
        g = bs.full_greeks()
        c_list.append(g.call_pts)
        p_list.append(g.put_pts)
        vanna_list.append(g.vanna)
        charm_list.append(g.charm_call_day)

        moneyness_pct = ((k - spot_raw) / spot_raw) * 100.0
        marca = " <-- ATM" if k == futuro_nq else ""
        t_opt.add_row([
            f"{k:,.0f}",
            f"{moneyness_pct:+.2f}%",
            fmt_num(g.call_pts, 2),
            fmt_num(g.put_pts, 2),
            fmt_num(g.delta_call, 3, sign=True),
            f"{g.gamma:.6f}",
            fmt_num(g.vega_pts, 2),
            fmt_num(g.theta_call_day, 2, sign=True),
            fmt_num(g.vanna, 4, sign=True),
            fmt_num(g.charm_call_day, 4, sign=True),
            f"{g.prob_itm_call:5.1f}%{marca}",
        ])
    print("\n" + t_opt.render() + "\n")

    # Gráfico institucional doble panel
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.2))
    ax1.plot(strikes, c_list, color=THEME["green"], lw=2.2, label="Call Price (Pts)")
    ax1.plot(strikes, p_list, color=THEME["red"], lw=2.2, label="Put Price (Pts)")
    ax1.axvline(spot_raw, color=THEME["yellow"], ls="--", lw=1.6, label=f"Spot NQ ({spot_raw:,.0f})")
    ax1.set_title("Black-76 | Primas Call & Put sobre NQ=F")
    ax1.set_xlabel("Strike NQ")
    ax1.set_ylabel("Prima (Puntos NQ)")
    ax1.legend()

    ax2.plot(strikes, vanna_list, color=THEME["blue"], lw=2.2, marker="o", markersize=4, label="Vanna (∂Δ/∂σ por 1% IV)")
    ax2.plot(strikes, charm_list, color=THEME["amber"], lw=2.2, marker="s", markersize=4, label="Charm (∂Δ/∂t por día)")
    ax2.axhline(0, color=THEME["muted"], lw=1.0)
    ax2.axvline(spot_raw, color=THEME["yellow"], ls="--", lw=1.6, label="Spot NQ")
    ax2.set_title("Griegas de 2do Orden | Vanna & Charm (Flujo Dealer)")
    ax2.set_xlabel("Strike NQ")
    ax2.set_ylabel("Sensibilidad de Delta")
    ax2.legend()
    finalize(fig, "black_scholes_nq", show=show_plot)

    return {"spot": spot_raw, "iv": vol_implicita, "r": tasa_fed, "ranges": ranges}


if __name__ == "__main__":
    ejecutar_black_scholes_interactivo()
