# %% [PERFIL GAMMA EXPOSURE (GEX) + VANNA & CHARM | TERMINAL NQ]
"""
Perfil de Gamma Exposure (GEX), Vanna Exposure (VEX) y Charm Exposure (CEX)
de Market Makers sobre el E-mini Nasdaq (NQ=F).

Conectado al motor unificado (`analysis/radar_gex_crr_griegos.py`) y al feed
en vivo (`Data/data_feed_nq.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.radar_gex_crr_griegos import MotorUnificadoGexCrrGreeks
from core.config import THEME


def calcular_perfil_gex_nasdaq(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    spot = feed.last_price("NQ", "15m")
    r, _ = feed.risk_free_rate()
    iv, _ = feed.implied_vol()
    chain = feed.option_chain_nq(spot, atm_iv=iv)

    motor = MotorUnificadoGexCrrGreeks(F=spot, r=r, iv_atm=iv, dte_gex=5.0, dte_crr=30.0)
    res = motor.evaluar_grilla(chain)
    df = res["table"]

    call_wall = res["call_wall"]
    put_wall = res["put_wall"]
    zero_gamma = res["zero_gamma"]
    zg_strike = res["zero_gamma_strike"]

    print("\n" + banner(
        f"PERFIL GAMMA EXPOSURE (GEX) + VANNA/CHARM | SPOT NQ: {spot:,.2f}",
        f"Put Wall: {put_wall:,.0f} | Zero-Gamma Flip: {zero_gamma:,.1f} | Call Wall: {call_wall:,.0f} | Net GEX: {res['total_gex_m']:+.2f} $M"
    ))
    print(kv_block([
        ("Régimen Dealers", res["dealer_regime"]),
        ("Piso Institucional", f"PUT WALL en {put_wall:,.0f} pts -> Dealers recompran shorts en rebotes"),
        ("Techo Institucional", f"CALL WALL en {call_wall:,.0f} pts -> Dealers venden largos / frenan subida"),
        ("Pivote Volatilidad", f"ZERO-GAMMA en {zero_gamma:,.1f} pts -> Debajo de este nivel el mercado acelera"),
    ]))

    t = Table(
        ["Strike", "OI Call", "OI Put", "Δ Call", "Gamma", "Vanna", "Charm/d", "Call GEX", "Put GEX", "Net GEX ($M)", "Nivel Institucional"],
        aligns="rrrrrrrrrrl",
        title="EXPOSICION DE MARKET MAKERS POR STRIKE (GAMMA, VANNA Y CHARM)"
    )

    for _, row in df.iterrows():
        K = float(row["strike"])
        tag = "-"
        if K == call_wall:
            tag = "<-- CALL WALL (Techo / Zona Short)"
        elif K == put_wall:
            tag = "<-- PUT WALL (Soporte / Zona Long)"
        elif K == zg_strike:
            tag = f"<-- ZERO-GAMMA FLIP (~{zero_gamma:,.0f})"

        t.add_row([
            f"{K:,.0f}",
            f"{row['oi_call']:,.0f}",
            f"{row['oi_put']:,.0f}",
            fmt_num(row["delta_call"], 3, sign=True),
            f"{row['gamma']:.6f}",
            fmt_num(row["vanna"], 4, sign=True),
            fmt_num(row["charm_day"], 4, sign=True),
            f"{fmt_usd(row['call_gex_m'], 2, sign=True)}M",
            f"{fmt_usd(row['put_gex_m'], 2, sign=True)}M",
            f"{fmt_usd(row['net_gex_m'], 2, sign=True)}M",
            tag,
        ])
    print("\n" + t.render() + "\n")

    import matplotlib.pyplot as plt
    strikes = df["strike"].to_numpy()
    net_gex = df["net_gex_m"].to_numpy()
    fig, ax = plt.subplots(figsize=(11.0, 5.0))
    colors = [THEME["green"] if g >= 0 else THEME["red"] for g in net_gex]
    ax.bar(strikes, net_gex, width=65, color=colors, alpha=0.85, label="Net GEX ($M por 1% move)")
    ax.axhline(0, color=THEME["text"], lw=1.0)
    ax.axvline(spot, color=THEME["yellow"], ls="--", lw=1.8, label=f"Spot NQ ({spot:,.0f})")
    ax.axvline(put_wall, color=THEME["green"], ls=":", lw=1.8, label=f"Put Wall ({put_wall:,.0f})")
    ax.axvline(zero_gamma, color=THEME["blue"], ls="-.", lw=1.6, label=f"Zero-Gamma ({zero_gamma:,.0f})")
    ax.axvline(call_wall, color=THEME["red"], ls=":", lw=1.8, label=f"Call Wall ({call_wall:,.0f})")
    ax.set_title("Perfil Gamma Exposure (GEX) de Market Makers | E-mini Nasdaq (NQ)")
    ax.set_xlabel("Strike NQ")
    ax.set_ylabel("Net GEX ($ Millones)")
    ax.legend()
    finalize(fig, "gex_profile_nq", show=show_plot)

    return res


if __name__ == "__main__":
    calcular_perfil_gex_nasdaq()
