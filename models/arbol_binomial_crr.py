# %% [ARBOL BINOMIAL COX-ROSS-RUBINSTEIN (CRR) | OPCIONES AMERICANAS NQ]
"""
Árbol Binomial Cox-Ross-Rubinstein (CRR) sobre futuros del E-mini Nasdaq (NQ=F).

En un futuro (neutral al riesgo con drift 0 bajo medida Q porque el futuro no
paga costo de acarreo adicional), el descuento por paso `exp(-r*dt)` genera un
incentivo positivo de ejercicio anticipado tanto en Puts profundas ITM como en
Calls profundas ITM (a diferencia de acciones sin dividendos).

Calcula:
  * Precio Americano vs Europeo (Put y Call)
  * Prima de Ejercicio Anticipado (pts y USD por contrato NQ = $20/pt)
  * Frontera Crítica de Ejercicio Anticipado S*(t)
  * Griegas Binomiales (Delta, Gamma, Theta por diferencias finitas en el árbol)
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import NQ, THEME


@dataclass
class CRRResult:
    american_pts: float
    european_pts: float
    early_ex_pts: float
    early_ex_usd_nq: float
    delta: float
    gamma: float
    critical_boundary: float    # nivel S* donde el valor intrínseco iguala continuación


class BinomialTreeCRRNasdaq:
    """Árbol Binomial CRR vectorizado con cálculo de frontera de ejercicio anticipado."""

    def __init__(self, F: float, K: float, T_days: float, r: float, sigma: float, steps: int = 200):
        self.F = float(F)
        self.K = float(K)
        self.T = max(float(T_days) / 365.0, 1e-6)
        self.r = float(r)
        self.sigma = max(float(sigma), 1e-4)
        self.N = int(max(steps, 10))

    def evaluate(self, option_type: str = "put") -> CRRResult:
        try:
            from core.jit_math import crr_american_tree_fast
            amer, euro, ee_pts, delta, gamma, theta_approx, boundary_mid = crr_american_tree_fast(
                F=self.F,
                K=self.K,
                T_days=self.T * 365.0,
                r=self.r,
                sigma=self.sigma,
                steps=self.N,
                option_type=option_type,
            )
            return CRRResult(
                american_pts=amer,
                european_pts=euro,
                early_ex_pts=ee_pts,
                early_ex_usd_nq=ee_pts * NQ.point_value,
                delta=float(delta),
                gamma=float(gamma),
                critical_boundary=boundary_mid,
            )
        except Exception:
            pass

        dt = self.T / self.N
        u = math.exp(self.sigma * math.sqrt(dt))
        d = 1.0 / u
        # Para futuros bajo medida Q, E[F_{t+dt} | F_t] = F_t -> p = (1 - d) / (u - d)
        p = (1.0 - d) / (u - d)
        disc = math.exp(-self.r * dt)

        j = np.arange(self.N + 1)
        terminal_prices = self.F * (u ** (self.N - j)) * (d ** j)

        is_call = option_type.lower().startswith("c")
        if is_call:
            val_amer = np.maximum(0.0, terminal_prices - self.K)
        else:
            val_amer = np.maximum(0.0, self.K - terminal_prices)
        val_euro = val_amer.copy()

        boundary_mid = self.K
        v1_up, v1_dn = 0.0, 0.0
        v2_uu, v2_ud, v2_dd = 0.0, 0.0, 0.0

        for step in range(self.N - 1, -1, -1):
            i = np.arange(step + 1)
            node_prices = self.F * (u ** (step - i)) * (d ** i)

            cont_amer = disc * (p * val_amer[:step + 1] + (1.0 - p) * val_amer[1:step + 2])
            cont_euro = disc * (p * val_euro[:step + 1] + (1.0 - p) * val_euro[1:step + 2])

            intrinsic = np.maximum(0.0, node_prices - self.K) if is_call else np.maximum(0.0, self.K - node_prices)
            ex_mask = (intrinsic > cont_amer + 1e-9) & (intrinsic > 0.0)
            val_amer = np.maximum(cont_amer, intrinsic)
            val_euro = cont_euro

            if step == self.N // 2 and np.any(ex_mask):
                boundary_mid = float(np.min(node_prices[ex_mask])) if is_call else float(np.max(node_prices[ex_mask]))
            if step == 2:
                v2_uu, v2_ud, v2_dd = float(val_amer[0]), float(val_amer[1]), float(val_amer[2])
            elif step == 1:
                v1_up, v1_dn = float(val_amer[0]), float(val_amer[1])

        s_up, s_dn = self.F * u, self.F * d
        s_uu, s_ud, s_dd = self.F * u * u, self.F, self.F * d * d
        delta = (v1_up - v1_dn) / (s_up - s_dn)
        delta_u = (v2_uu - v2_ud) / (s_uu - s_ud)
        delta_d = (v2_ud - v2_dd) / (s_ud - s_dd)
        gamma = (delta_u - delta_d) / (0.5 * (s_uu - s_dd))

        amer = float(val_amer[0])
        euro = float(val_euro[0])
        ee_pts = max(amer - euro, 0.0)
        return CRRResult(
            american_pts=amer,
            european_pts=euro,
            early_ex_pts=ee_pts,
            early_ex_usd_nq=ee_pts * NQ.point_value,
            delta=float(delta),
            gamma=float(gamma),
            critical_boundary=boundary_mid,
        )

    def price_option(self, option_type: str = "put", american: bool = True) -> float:
        res = self.evaluate(option_type=option_type)
        return res.american_pts if american else res.european_pts


def ejecutar_crr_interactivo(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd

    feed = feed or DataFeedNQ()
    spot_raw = feed.last_price("NQ", "15m")
    F_nq = round(spot_raw / 50.0) * 50.0
    T_dias = 30.0
    r_fed, _ = feed.risk_free_rate()
    vol, _ = feed.implied_vol()

    strikes = np.arange(F_nq - 750, F_nq + 800, 150)

    print("\n" + banner(
        f"VALUACION ARBOL BINOMIAL CRR (N=200 Nodos) | SPOT NQ: {spot_raw:,.2f} (Ref: {F_nq:,.0f})",
        f"DTE: {T_dias:.0f}d | IV (VXN): {vol*100:.2f}% | Tasa r: {r_fed*100:.2f}% | Multiplicador NQ: $20/pt"
    ))

    t = Table(
        ["Strike", "Put Amer (Pts)", "Put Euro (Pts)", "Prima Ejerc. ($ NQ)", "Frontera S*", "Delta Put", "Lectura Operativa NQ"],
        aligns="rrrrrrl",
        title="CURVA DE URGENCIA DE EJERCICIO ANTICIPADO EN PUTS INSTITUCIONALES (NQ)"
    )

    s_list, prima_put_usd, prima_call_usd = [], [], []
    for k in strikes:
        m_log = math.log(float(k) / spot_raw)
        iv_k = max(vol * (1.0 - 0.85 * m_log + 2.0 * (m_log ** 2)), 0.08)
        crr = BinomialTreeCRRNasdaq(spot_raw, float(k), T_dias, r_fed, iv_k, steps=200)
        res_p = crr.evaluate("put")
        res_c = crr.evaluate("call")

        if res_p.early_ex_usd_nq >= 11.0:
            lectura = "Cobro Institucional Put ITM -> Toma Ganancias / Rebote"
        elif res_p.early_ex_usd_nq >= 6.0:
            lectura = "Zona Equilibrio / Transición ATM"
        else:
            lectura = "Puts Abiertas sin urgencia -> Continúa cobertura activa"

        s_list.append(float(k))
        prima_put_usd.append(res_p.early_ex_usd_nq)
        prima_call_usd.append(res_c.early_ex_usd_nq)

        t.add_row([
            f"{k:,.0f}",
            f"{fmt_num(res_p.american_pts, 2)} pts",
            f"{fmt_num(res_p.european_pts, 2)} pts",
            fmt_usd(res_p.early_ex_usd_nq, 2),
            fmt_num(res_p.critical_boundary, 0),
            fmt_num(res_p.delta, 3, sign=True),
            lectura,
        ])
    print(t.render() + "\n")

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    w = 55
    x_arr = np.asarray(s_list)
    ax.bar(x_arr - w / 2, prima_put_usd, width=w, color=THEME["pink"], alpha=0.88,
           label="Prima Ejercicio Anticipado Put ($ USD / NQ)")
    ax.bar(x_arr + w / 2, prima_call_usd, width=w, color=THEME["green"], alpha=0.78,
           label="Prima Ejercicio Anticipado Call ($ USD / NQ)")
    ax.axvline(spot_raw, color=THEME["yellow"], ls="--", lw=1.8, label=f"Spot NQ ({spot_raw:,.0f})")
    ax.set_title("Árbol Binomial CRR | Urgencia de Ejercicio Anticipado en Opciones sobre NQ")
    ax.set_xlabel("Strike NQ")
    ax.set_ylabel("USD por Contrato NQ ($20/pt)")
    ax.legend()
    finalize(fig, "arbol_binomial_crr_nq", show=show_plot)

    return {"spot": spot_raw, "strikes": s_list, "put_ee_usd": prima_put_usd, "call_ee_usd": prima_call_usd}


if __name__ == "__main__":
    ejecutar_crr_interactivo()
