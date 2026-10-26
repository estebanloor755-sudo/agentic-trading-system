# %% [ESCANER MULTI-TIMEFRAME (15M MACRO + 5M EJECUCION): VWAP Z-SCORE, OFI/CVD, HURST & LO-MACKINLAY]
"""
Detector de Microestructura, Desbalance Estadístico y Régimen de Memoria para NQ=F:
  * Alineación Multi-Timeframe: 15m (Macro) + 5m (Disparo en ventanas NY 09:30-11:45 y 15:00-16:00)
  * VWAP Anclado de Sesión + Bandas de Desviación Estándar Ponderadas por Volumen -> Z-Score
  * Order Flow Imbalance (OFI / Cumulative Volume Delta proxy vía Close Location Value)
  * Exponente de Hurst (H) sobre retornos/precios log + Test de Ratio de Varianza
    de Lo-MacKinlay robusto a heterocedasticidad (z*(q)):
      - H < 0.48 -> REVERSION A LA MEDIA (Operar extremos Z > +2 / Z < -2 hacia VWAP)
      - H > 0.52 -> MOMENTUM PERSISTENTE (Operar rupturas y pullbacks al VWAP)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MODEL, THEME
from core.mathx import norm_cdf
from core import sessions


def calcular_hurst(serie: np.ndarray, max_lag: int = 32) -> float:
    """
    Exponente de Hurst H mediante variograma de incrementos logarítmicos
    Var(p_{t+tau} - p_t) ~ tau^{2H}, combinado con R/S reescalado para robustez.
    """
    s = np.asarray(serie, dtype=float)
    s = s[np.isfinite(s) & (s > 0)]
    if len(s) < 40:
        return 0.50
    log_p = np.log(s)
    hi_lag = min(max_lag, len(log_p) // 4)
    lags = np.arange(2, max(hi_lag + 1, 6))
    tau = np.array([max(float(np.std(log_p[lag:] - log_p[:-lag], ddof=1)), 1e-12) for lag in lags])
    slope, _ = np.polyfit(np.log(lags.astype(float)), np.log(tau), 1)
    h_var = float(np.clip(slope, 0.15, 0.85))

    # Estimador R/S complementario sobre sub-bloques
    r = np.diff(log_p)
    rs_vals, ns = [], []
    for n_sub in (16, 32, 64, 128):
        if len(r) < n_sub * 2:
            continue
        k_blocks = len(r) // n_sub
        rs_b = []
        for b in range(k_blocks):
            seg = r[b * n_sub:(b + 1) * n_sub]
            dev = np.cumsum(seg - seg.mean())
            R = float(dev.max() - dev.min())
            S = float(seg.std(ddof=1))
            if S > 1e-12:
                rs_b.append(R / S)
        if rs_b:
            rs_vals.append(np.mean(rs_b))
            ns.append(n_sub)
    if len(ns) >= 2:
        h_rs = float(np.clip(np.polyfit(np.log(ns), np.log(rs_vals), 1)[0], 0.15, 0.85))
        return 0.65 * h_var + 0.35 * h_rs
    return h_var


def lo_mackinlay_vr(prices: np.ndarray, q: int = 4) -> dict:
    """
    Test de Ratio de Varianza de Lo-MacKinlay (1988) robusto a heterocedasticidad (z*(q)).
      VR(q) < 1 -> autocorrelación negativa (Reversión a la Media)
      VR(q) > 1 -> autocorrelación positiva (Momentum Persistente)
    """
    p = np.log(np.asarray(prices, dtype=float))
    r = np.diff(p)
    n = len(r)
    if n <= 2 * q + 5:
        return {"q": q, "vr": 1.0, "z_robust": 0.0, "p_value": 1.0}
    mu = float(r.mean())
    r_c = r - mu
    sig2_1 = float(np.sum(r_c ** 2)) / (n - 1.0)
    # Retornos acumulados de q periodos solapados
    rq = p[q:] - p[:-q] - q * mu
    m = q * (n - q + 1.0) * (1.0 - q / n)
    sig2_q = float(np.sum(rq ** 2)) / max(m, 1.0)
    vr = sig2_q / max(sig2_1, 1e-12)

    # Varianza asintótica robusta a heterocedasticidad (theta(q))
    r_c2 = r_c ** 2
    denom = float(np.sum(r_c2)) ** 2
    theta = 0.0
    for j in range(1, q):
        delta_j = float(n * np.sum(r_c2[j:] * r_c2[:-j])) / max(denom, 1e-18)
        w_j = 2.0 * (q - j) / q
        theta += (w_j ** 2) * delta_j
    z_star = (vr - 1.0) / math.sqrt(max(theta / n, 1e-12)) if theta > 0 else 0.0
    # Si delta_j ya incluye factor n, corregimos la escala estándar de Lo-MacKinlay:
    # delta_j_std = sum(r_t^2 r_{t-j}^2) / (sum(r_t^2))^2 -> theta_std = sum((2(q-j)/q)^2 * delta_j_std)
    theta_std = theta / n
    z_star = (vr - 1.0) / math.sqrt(max(theta_std, 1e-12))
    pval = 2.0 * (1.0 - float(norm_cdf(abs(z_star))))
    return {"q": q, "vr": float(vr), "z_robust": float(z_star), "p_value": float(pval)}


def compute_vwap_ofi_metrics(df: pd.DataFrame, window: int = 32) -> pd.DataFrame:
    """
    Calcula VWAP anclado por sesión + VWAP rodante, Z-Score respecto al VWAP,
    Close Location Value (CLV), Order Flow Imbalance (OFI) y CVD proxy.
    """
    out = df.copy()
    tp = (out["High"] + out["Low"] + out["Close"]) / 3.0
    vol = np.maximum(out["Volume"].to_numpy(dtype=float), 1.0)
    tp_arr = tp.to_numpy(dtype=float)
    cl_arr = out["Close"].to_numpy(dtype=float)
    hi_arr = out["High"].to_numpy(dtype=float)
    lo_arr = out["Low"].to_numpy(dtype=float)

    # Sesión Globex: agrupa por fecha de sesión (desplaza +6h para que 18:00 ET inicie nueva sesión)
    sess_date = (out.index + pd.Timedelta(hours=6)).date
    vwap = np.empty_like(cl_arr)
    vwap_sd = np.empty_like(cl_arr)
    for d in pd.unique(sess_date):
        mask = sess_date == d
        v_s = vol[mask]
        tp_s = tp_arr[mask]
        cum_v = np.cumsum(v_s)
        cum_vp = np.cumsum(v_s * tp_s)
        vw = cum_vp / cum_v
        # Varianza ponderada por volumen dentro de la sesión
        cum_vp2 = np.cumsum(v_s * (tp_s ** 2))
        var_w = np.maximum(cum_vp2 / cum_v - vw ** 2, (cl_arr[mask] * 0.0008) ** 2)
        vwap[mask] = vw
        vwap_sd[mask] = np.sqrt(var_w)

    out["VWAP"] = vwap
    out["VWAP_SD"] = vwap_sd
    out["Z_VWAP"] = (cl_arr - vwap) / np.maximum(vwap_sd, 1e-6)
    out["VWAP_Globex"] = vwap
    out["VWAP_Globex_SD"] = vwap_sd
    out["Z_VWAP_Globex"] = out["Z_VWAP"]

    # ----------------------------------------------------------------------- #
    # RTH NY Cash VWAP: anclado estrictamente a las 09:30 ET de Wall Street
    # ----------------------------------------------------------------------- #
    import datetime as dt_mod
    rth_mask = np.array([
        (t.weekday() < 5 and dt_mod.time(9, 30) <= t.time() < dt_mod.time(16, 0))
        for t in out.index
    ])
    vwap_rth = np.full_like(cl_arr, np.nan)
    vwap_rth_sd = np.full_like(cl_arr, np.nan)
    rth_date = out.index.date

    for d in pd.unique(rth_date):
        d_mask = (rth_date == d) & rth_mask
        if np.any(d_mask):
            v_rth = vol[d_mask]
            tp_rth = tp_arr[d_mask]
            cum_v_r = np.cumsum(v_rth)
            cum_vp_r = np.cumsum(v_rth * tp_rth)
            vw_r = cum_vp_r / np.maximum(cum_v_r, 1e-6)
            cum_vp2_r = np.cumsum(v_rth * (tp_rth ** 2))
            var_w_r = np.maximum(cum_vp2_r / np.maximum(cum_v_r, 1e-6) - vw_r ** 2, (cl_arr[d_mask] * 0.0008) ** 2)
            vwap_rth[d_mask] = vw_r
            vwap_rth_sd[d_mask] = np.sqrt(var_w_r)

    s_vw_rth = pd.Series(vwap_rth, index=out.index).ffill().bfill()
    s_sd_rth = pd.Series(vwap_rth_sd, index=out.index).ffill().bfill()
    out["VWAP_RTH"] = s_vw_rth.to_numpy()
    out["VWAP_RTH_SD"] = s_sd_rth.to_numpy()
    out["Z_VWAP_RTH"] = (cl_arr - out["VWAP_RTH"]) / np.maximum(out["VWAP_RTH_SD"], 1e-6)

    # ----------------------------------------------------------------------- #
    # Bulk Volume Classification (BVC - López de Prado) con datos Nivel 1 OHLCV
    # Descompone el volumen en compras/ventas usando la distribución acumulada
    # sobre los retornos estandarizados: V_buy = V * Phi(dP/sigma), V_sell = V * (1 - Phi)
    # ----------------------------------------------------------------------- #
    delta_p = np.diff(cl_arr, prepend=cl_arr[0])
    s_dp = pd.Series(delta_p, index=out.index)
    sigma_dp = s_dp.rolling(window, min_periods=5).std(ddof=1).replace(0, np.nan).bfill().fillna(1.0).to_numpy()
    z_dp = np.clip(delta_p / np.maximum(sigma_dp, 1e-4), -4.0, 4.0)
    try:
        from scipy.special import ndtr
        phi_z = ndtr(z_dp)
    except Exception:
        phi_z = 0.5 * (1.0 + np.vectorize(math.erf)(z_dp / math.sqrt(2.0)))

    bvc_buy_vol = vol * phi_z
    bvc_sell_vol = vol * (1.0 - phi_z)
    bvc_ofi = bvc_buy_vol - bvc_sell_vol

    # Combinación institucional con CLV (Close Location Value) intrabarra
    rng = np.maximum(hi_arr - lo_arr, 0.25)
    clv = ((cl_arr - lo_arr) - (hi_arr - cl_arr)) / rng
    ofi_bar = 0.65 * bvc_ofi + 0.35 * (clv * vol)
    out["CLV"] = clv
    out["BVC_Buy"] = bvc_buy_vol
    out["BVC_Sell"] = bvc_sell_vol
    out["OFI"] = ofi_bar

    # CVD por sesión y normalización invariante a escala (CVD Z-Score)
    cvd = np.empty_like(cl_arr)
    for d in pd.unique(sess_date):
        mask = sess_date == d
        cvd[mask] = np.cumsum(ofi_bar[mask])
    out["CVD"] = cvd
    s_cvd = pd.Series(cvd, index=out.index)
    cvd_roll_mean = s_cvd.rolling(window * 2, min_periods=5).mean()
    cvd_roll_sd = s_cvd.rolling(window * 2, min_periods=5).std(ddof=1)
    out["CVD_Z"] = ((s_cvd - cvd_roll_mean) / cvd_roll_sd.replace(0, np.nan)).fillna(0.0).to_numpy()

    s_ofi = pd.Series(ofi_bar, index=out.index)
    ofi_roll_mean = s_ofi.rolling(window, min_periods=5).sum()
    ofi_roll_sd = s_ofi.rolling(window, min_periods=5).std(ddof=1) * math.sqrt(window)
    out["OFI_Z"] = (ofi_roll_mean / ofi_roll_sd.replace(0, np.nan)).fillna(0.0)
    return out


def compute_volume_profile(df: pd.DataFrame, n_bars: int = 150, value_area_pct: float = 0.70) -> dict:
    """
    Calcula el Volume Profile Institucional del E-mini Nasdaq (NQ/MNQ):
      - Point of Control (POC): Precio con mayor volumen acumulado.
      - Value Area High (VAH) y Value Area Low (VAL): Rango que contiene el 70% del volumen.
    """
    sub = df.tail(n_bars).copy()
    if len(sub) == 0:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "total_vol": 0.0}

    step = 5.0  # Bins institucionales de 5 pts para NQ
    p_min = math.floor(float(sub["Low"].min()) / step) * step
    p_max = math.ceil(float(sub["High"].max()) / step) * step
    bins = np.arange(p_min, p_max + step, step)
    vol_hist = np.zeros(len(bins), dtype=float)

    for _, row in sub.iterrows():
        b_lo = float(row["Low"])
        b_hi = float(row["High"])
        b_vol = max(float(row["Volume"]), 1.0)
        idx_lo = max(0, int((b_lo - p_min) // step))
        idx_hi = min(len(bins) - 1, int((b_hi - p_min) // step))
        n_covered = max(idx_hi - idx_lo + 1, 1)
        vol_hist[idx_lo : idx_hi + 1] += b_vol / n_covered

    poc_idx = int(np.argmax(vol_hist))
    poc_price = float(bins[poc_idx])

    total_vol = float(np.sum(vol_hist))
    target_va = total_vol * value_area_pct
    current_va = vol_hist[poc_idx]
    up_idx = poc_idx
    dn_idx = poc_idx

    while current_va < target_va and (up_idx < len(bins) - 1 or dn_idx > 0):
        next_up = vol_hist[up_idx + 1] if up_idx < len(bins) - 1 else -1.0
        next_dn = vol_hist[dn_idx - 1] if dn_idx > 0 else -1.0
        if next_up >= next_dn and up_idx < len(bins) - 1:
            up_idx += 1
            current_va += vol_hist[up_idx]
        elif dn_idx > 0:
            dn_idx -= 1
            current_va += vol_hist[dn_idx]
        else:
            break

    vah_price = float(bins[up_idx])
    val_price = float(bins[dn_idx])
    return {
        "poc": poc_price,
        "vah": vah_price,
        "val": val_price,
        "total_vol": total_vol,
    }


def compute_rvol_20d(df: pd.DataFrame) -> float:
    """
    Volumen Relativo (RVOL) normalizado a las últimas 20 sesiones a la misma hora NY.
    """
    if len(df) < 50:
        return 1.0
    last_t = df.index[-1].time()
    last_vol = float(df["Volume"].iloc[-1])
    # Barras históricas con el mismo minuto/hora
    same_time_bars = df[df.index.time == last_t]["Volume"].tail(20)
    mean_hist = float(same_time_bars.mean()) if len(same_time_bars) > 0 else 1.0
    return float(np.clip(last_vol / max(mean_hist, 1.0), 0.1, 10.0))


def dictaminar_regimen_hurst(h: float, vr_dict: dict) -> str:
    if h < MODEL.hurst_reversion:
        return f"REVERSION A LA MEDIA (H={h:.3f} < 0.48 | VR={vr_dict['vr']:.2f})"
    if h > MODEL.hurst_momentum:
        return f"MOMENTUM PERSISTENTE (H={h:.3f} > 0.52 | VR={vr_dict['vr']:.2f})"
    if vr_dict["vr"] < 0.94:
        return f"TRANSICION -> SESGO REVERSION (H={h:.3f} | VR={vr_dict['vr']:.2f})"
    if vr_dict["vr"] > 1.06:
        return f"TRANSICION -> SESGO MOMENTUM (H={h:.3f} | VR={vr_dict['vr']:.2f})"
    return f"CAMINATA ALEATORIA / EQUILIBRIO (H={h:.3f} | VR={vr_dict['vr']:.2f})"


def tag_ny_window(ts: pd.Timestamp) -> str:
    if sessions.in_window(ts, "APERTURA_NY"):
        return "APERTURA NY (09:30-11:45)"
    if sessions.in_window(ts, "CIERRE_NY"):
        return "CIERRE NY (15:00-16:00)"
    if sessions.is_rth(ts):
        return "MEDIO DIA RTH"
    return "GLOBEX OVERNIGHT"


def escanear_desbalance_estadistico_nq(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, kv_block

    feed = feed or DataFeedNQ()
    df15 = compute_vwap_ofi_metrics(feed.bars("NQ", "15m"), window=20)
    df5 = compute_vwap_ofi_metrics(feed.bars("NQ", "5m"), window=24)

    h15 = calcular_hurst(df15["Close"].to_numpy()[-500:])
    h5 = calcular_hurst(df5["Close"].to_numpy()[-600:])
    vr15 = lo_mackinlay_vr(df15["Close"].to_numpy()[-500:], q=4)
    vr5 = lo_mackinlay_vr(df5["Close"].to_numpy()[-600:], q=6)

    reg15_str = dictaminar_regimen_hurst(h15, vr15)
    reg5_str = dictaminar_regimen_hurst(h5, vr5)

    spot = float(df5["Close"].iloc[-1])
    vwap15 = float(df15["VWAP"].iloc[-1])
    z15 = float(df15["Z_VWAP"].iloc[-1])
    z5 = float(df5["Z_VWAP"].iloc[-1])
    ofi_z5 = float(df5["OFI_Z"].iloc[-1])

    print("\n" + banner(
        f"ESCANER DE DESBALANCE ESTADISTICO, VWAP, OFI/CVD & HURST | SPOT NQ: {spot:,.2f}",
        f"Alineación Multi-Timeframe: 15m (Macro) + 5m (Ejecución en Ventanas NY 09:30-11:45 & 15:00-16:00 EST)"
    ))
    print(kv_block([
        ("VWAP Sesión Actual", f"{vwap15:,.2f} pts | Distancia Spot-VWAP: {spot - vwap15:+.2f} pts"),
        ("Z-Score vs VWAP", f"Macro 15m: {z15:+.2f} SD  |  Ejecución 5m: {z5:+.2f} SD  |  OFI Z-Score (5m): {ofi_z5:+.2f} SD"),
        ("Hurst & Lo-MacKinlay 15m", f"H = {h15:.3f} | VR(4) = {vr15['vr']:.3f} (z*={vr15['z_robust']:+.2f}, p={vr15['p_value']:.3f}) -> {reg15_str}"),
        ("Hurst & Lo-MacKinlay 5m", f"H = {h5:.3f} | VR(6) = {vr5['vr']:.3f} (z*={vr5['z_robust']:+.2f}, p={vr5['p_value']:.3f}) -> {reg5_str}"),
    ]))

    # Tabla 1: Últimas 10 barras de 15m (Macro)
    t15 = Table(
        ["Hora NY (15m)", "Ventana Sesión", "Cierre NQ", "VWAP", "Z-VWAP", "OFI Z", "Diagnóstico Macro 15m"],
        aligns="llrrrrl",
        title="VISTA MACRO (15 MINUTOS) - DESBALANCE RESPECTO AL VWAP Y FLUJO INSTITUCIONAL"
    )
    for ts, row in df15.tail(10).iterrows():
        z = float(row["Z_VWAP"])
        oz = float(row["OFI_Z"])
        if z > 2.0:
            diag = "Sobreextensión Alcista (>+2 SD) -> Riesgo Reversión" if h15 < 0.50 else "Ruptura Alcista con Flujo"
        elif z < -2.0:
            diag = "Sobreextensión Bajista (<-2 SD) -> Absorción / Rebote" if h15 < 0.50 else "Presión Bajista Persistente"
        elif abs(oz) > 1.5:
            diag = "Acumulación Compradora (CVD+)" if oz > 0 else "Distribución Vendedora (CVD-)"
        else:
            diag = "Subasta en Equilibrio alrededor del VWAP"
        t15.add_row([
            ts.strftime("%a %H:%M"),
            tag_ny_window(ts),
            fmt_num(row["Close"], 2),
            fmt_num(row["VWAP"], 2),
            f"{z:+.2f} SD",
            f"{oz:+.2f}",
            diag,
        ])
    print("\n" + t15.render())

    # Tabla 2: Barras de 5m (priorizando ventanas operativas NY 09:30-11:45 y 15:00-16:00)
    mask_win = [sessions.in_window(ts, "APERTURA_NY") or sessions.in_window(ts, "CIERRE_NY") for ts in df5.index]
    df5_win = df5[mask_win].tail(12)
    if len(df5_win) < 8:
        df5_win = df5.tail(12)

    t5 = Table(
        ["Hora NY (5m)", "Ventana Operativa", "Cierre NQ", "VWAP", "Z-VWAP (5m)", "CLV", "OFI Z (5m)", "Gatillo de Ejecución 5m"],
        aligns="llrrrrrl",
        title="VISTA DE DISPARO (5 MINUTOS) - VENTANAS CLAVE DE NUEVA YORK (09:30-11:45 & 15:00-16:00 EST)"
    )
    for ts, row in df5_win.iterrows():
        z = float(row["Z_VWAP"])
        oz = float(row["OFI_Z"])
        clv = float(row["CLV"])
        if z <= -1.8 and clv > 0.25:
            trig = ">>> GATILLO LONG (Absorción en Banda Inferior VWAP)"
        elif z >= 1.8 and clv < -0.25:
            trig = ">>> GATILLO SHORT (Agotamiento en Banda Superior VWAP)"
        elif z > 0.5 and oz > 1.2 and h5 > 0.52:
            trig = ">>> LONG MOMENTUM (Flujo CVD+ sobre VWAP)"
        elif z < -0.5 and oz < -1.2 and h5 > 0.52:
            trig = ">>> SHORT MOMENTUM (Flujo CVD- bajo VWAP)"
        else:
            trig = "Neutral / Esperar extremo Z ±2.0 o barrido"
        t5.add_row([
            ts.strftime("%a %H:%M"),
            tag_ny_window(ts),
            fmt_num(row["Close"], 2),
            fmt_num(row["VWAP"], 2),
            f"{z:+.2f} SD",
            f"{clv:+.2f}",
            f"{oz:+.2f}",
            trig,
        ])
    print("\n" + t5.render() + "\n")

    # Gráfico institucional (Precio + VWAP Bandas y Z-Score / OFI en 5m)
    import matplotlib.pyplot as plt
    sub5 = df5.tail(96)
    x5 = np.arange(len(sub5))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 6.8), sharex=True)

    vw = sub5["VWAP"].to_numpy()
    sd = sub5["VWAP_SD"].to_numpy()
    ax1.plot(x5, sub5["Close"].to_numpy(), color=THEME["blue"], lw=1.9, label="Cierre NQ (5m)")
    ax1.plot(x5, vw, color=THEME["yellow"], lw=1.8, ls="--", label="VWAP Sesión")
    ax1.fill_between(x5, vw - 2 * sd, vw + 2 * sd, color=THEME["indigo"], alpha=0.22, label="Bandas VWAP ±2 SD")
    ax1.set_title(f"Microestructura 5m NQ | Precio vs VWAP + Bandas | Hurst 5m = {h5:.3f} ({reg5_str.split('(')[0].strip()})")
    ax1.set_ylabel("Precio NQ")
    ax1.legend(loc="upper left")

    ax2.plot(x5, sub5["Z_VWAP"].to_numpy(), color=THEME["green"], lw=1.8, label="Z-Score vs VWAP")
    ax2.plot(x5, sub5["OFI_Z"].to_numpy(), color=THEME["amber"], lw=1.4, alpha=0.85, label="OFI / CVD Z-Score")
    ax2.axhline(2.0, color=THEME["red"], ls="--", lw=1.2, label="Umbral +2 SD")
    ax2.axhline(-2.0, color=THEME["green"], ls="--", lw=1.2, label="Umbral -2 SD")
    ax2.axhline(0.0, color=THEME["muted"], lw=0.8)
    ax1.set_xlim(0, len(sub5) - 1)
    ax2.set_xlim(0, len(sub5) - 1)
    ax1.margins(x=0.0)
    ax2.margins(x=0.0)
    tick_pos_5 = list(range(0, len(sub5), 8))
    if tick_pos_5[-1] != len(sub5) - 1:
        tick_pos_5.append(len(sub5) - 1)
    ax2.set_xticks(tick_pos_5)
    ax2.set_xticklabels([ts.strftime("%H:%M") for ts in sub5.index[tick_pos_5]], rotation=45)
    ax2.set_ylabel("Z-Score (SD)")
    ax2.set_xlabel("Barras de 5 Minutos (Hora NY)")
    ax2.legend(loc="upper left")
    finalize(fig, "desbalance_estadistico_nq", show=show_plot)

    return {
        "spot": spot,
        "vwap": vwap15,
        "z_15m": z15,
        "z_5m": z5,
        "ofi_z_5m": ofi_z5,
        "hurst_15m": h15,
        "hurst_5m": h5,
        "vr_15m": vr15,
        "vr_5m": vr5,
        "regime_15m": reg15_str,
        "regime_5m": reg5_str,
    }


if __name__ == "__main__":
    escanear_desbalance_estadistico_nq()
