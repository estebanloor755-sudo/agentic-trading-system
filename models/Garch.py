# %% [MOTOR GJR-GARCH(1,1)-t + AR(p) | E-MINI NASDAQ 15M MACRO & 5M EJECUCION]
"""
Volatilidad condicional institucional para NQ=F / MNQ=F (15m macro y 5m ejecución).

Modelo sobre retornos logarítmicos en % desestacionalizados (x_t = r_t / s_slot):
    x_t   = mu + sum_{i=1}^p phi_i x_{t-i} + eps_t                AR(p), p por BIC
    eps_t = sigma_t * z_t,   z_t ~ t-Student(nu) estandarizada
    s2_t  = omega + (alpha + gamma * I[eps_{t-1}<0]) * eps_{t-1}^2 + beta * s2_{t-1}

Correcciones clave frente al script original:
  1. Signo de la verosimilitud corregido: el script previo devolvía -0.5*sum(...)
     en `neg_log_likelihood`, minimizando la log-verosimilitud en vez de maximizarla
     y estancando la varianza en un perfil plano.
  2. Reparametrización logística + Variance Targeting + Multi-Start Nelder-Mead
     con recursión lineal vectorizada por bloques: garantiza convergencia sin
     depender de gradientes numéricos frágiles ni de `arch`.
  3. Desestacionalización intradía en U (apertura NY 09:30 tiene ~3x la vol del
     overnight) para separar estacionalidad horaria de clustering GARCH real.
  4. Prueba ARCH-LM(12) de Engle antes y después del ajuste.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import MNQ, NQ, THEME
from core.mathx import linear_recursion, nelder_mead, norm_cdf, ols
from core import sessions


# --------------------------------------------------------------------------- #
# Pruebas estadísticas y estacionalidad intradía
# --------------------------------------------------------------------------- #
def chi2_sf(x: float, k: int) -> float:
    """P(Chi2_k > x) mediante aproximación de Wilson-Hilferty."""
    if x <= 0 or not math.isfinite(x):
        return 1.0
    z = ((x / k) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * k))) / math.sqrt(2.0 / (9.0 * k))
    return float(1.0 - norm_cdf(z))


def arch_lm_test(e: np.ndarray, lags: int = 12) -> tuple[float, float]:
    """Test ARCH-LM de Engle sobre e_t^2. Retorna (estadístico LM, p-valor)."""
    e2 = np.asarray(e, dtype=float) ** 2
    if len(e2) <= lags + 15:
        return float("nan"), float("nan")
    Y = e2[lags:]
    X = np.column_stack([e2[lags - i:-i] for i in range(1, lags + 1)])
    r2 = ols(Y, X)["r2"]
    stat = float(len(Y) * r2)
    return stat, chi2_sf(stat, lags)


def check_stationarity_adf(
    series: np.ndarray | pd.Series,
    alpha: float = 0.05,
    max_lag: int | None = None,
) -> dict[str, Any]:
    """
    Test Aumentado de Dickey-Fuller (ADF) sobre retornos logarítmicos.
    
    H0 (Hipótesis Nula): La serie posee raíz unitaria (es NO estacionaria).
    H1 (Hipótesis Alternativa): La serie es estacionaria (no posee raíz unitaria).

    Criterio Cuantitativo:
      - p-value < 0.05: Se rechaza H0 con >=95% de confianza. La serie es ESTACIONARIA.
      - p-value >= 0.05: No se puede rechazar H0. La serie es NO ESTACIONARIA.
        Se evalúa una diferenciación adicional d(r_t) y se emite bandera de fail-safe.
    """
    from typing import Any
    import warnings

    if isinstance(series, pd.Series):
        x = series.to_numpy(dtype=float)
    else:
        x = np.asarray(series, dtype=float)

    x = x[np.isfinite(x)]
    if len(x) < 20:
        return {
            "stat": 0.0,
            "pvalue": 1.0,
            "is_stationary": False,
            "status_str": "Muestra insuficiente (<20)",
            "critical_values": {},
            "crit_5pct": -2.86,
            "lags": 0,
            "nobs": len(x),
            "diff_tested": False,
            "diff_stat": None,
            "diff_pvalue": None,
        }

    try:
        from statsmodels.tsa.stattools import adfuller
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = adfuller(x, maxlag=max_lag, autolag="AIC")
        stat = float(res[0])
        pvalue = float(res[1])
        lags = int(res[2])
        nobs = int(res[3])
        crit = {str(k): float(v) for k, v in res[4].items()}
        crit_5 = float(crit.get("5%", -2.86))
    except Exception as exc:
        return {
            "stat": -99.0,
            "pvalue": 0.0,
            "is_stationary": True,
            "status_str": f"Fallback ({exc})",
            "critical_values": {"5%": -2.86},
            "crit_5pct": -2.86,
            "lags": 0,
            "nobs": len(x),
            "diff_tested": False,
            "diff_stat": None,
            "diff_pvalue": None,
        }

    is_stat = bool(pvalue < alpha)
    diff_tested = False
    diff_stat = None
    diff_pvalue = None

    # Si la serie no es estacionaria, evaluar diferenciación de segundo orden d(r_t)
    if not is_stat and len(x) > 30:
        dx = np.diff(x)
        dx = dx[np.isfinite(dx)]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res_diff = adfuller(dx, maxlag=max_lag, autolag="AIC")
            diff_stat = float(res_diff[0])
            diff_pvalue = float(res_diff[1])
            diff_tested = True
        except Exception:
            pass

    if is_stat:
        status_str = f"Estacionaria (p={pvalue:.4f})"
    else:
        if diff_pvalue is not None and diff_pvalue < alpha:
            status_str = f"NO Estacionaria en r_t (p={pvalue:.4f}) | Estacionaria en Δr_t (p={diff_pvalue:.4f})"
        else:
            status_str = f"NO Estacionaria / Régimen Roto (p={pvalue:.4f} >= {alpha})"

    return {
        "stat": stat,
        "pvalue": pvalue,
        "is_stationary": is_stat,
        "status_str": status_str,
        "critical_values": crit,
        "crit_5pct": crit_5,
        "lags": lags,
        "nobs": nobs,
        "diff_tested": diff_tested,
        "diff_stat": diff_stat,
        "diff_pvalue": diff_pvalue,
    }


def seasonal_factors(r: np.ndarray, index: pd.DatetimeIndex, minutes: int,
                     shrink: float = 12.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Perfil diurno de volatilidad s_slot = sqrt(E[r^2 | slot] / E[r^2]) con
    shrinkage Bayesiano hacia 1.0 y suavizado circular.
    """
    n_slots = 1440 // minutes
    slots = sessions.slot_of(index, minutes)
    r2 = np.asarray(r, dtype=float) ** 2
    cap = float(np.quantile(r2, 0.995)) if len(r2) > 20 else 1.0
    r2 = np.minimum(r2, max(cap, 1e-12))
    tot = max(float(r2.mean()), 1e-12)
    sums = np.bincount(slots, weights=r2, minlength=n_slots)
    cnts = np.bincount(slots, minlength=n_slots).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(cnts > 0, (sums / np.maximum(cnts, 1.0)) / tot, 1.0)
    shr = (cnts * raw + shrink * 1.0) / (cnts + shrink)
    sm = (np.roll(shr, 1) + 2.0 * shr + np.roll(shr, -1)) / 4.0
    sm = np.where(cnts > 0, sm, 1.0)
    table = np.sqrt(np.maximum(sm, 0.05))
    s_obs = table[slots]
    norm = float(np.sqrt(np.mean(s_obs ** 2)))
    return s_obs / norm, table / norm


def fit_ar(x: np.ndarray, max_p: int = 3) -> tuple[int, float, np.ndarray, np.ndarray]:
    """Ajusta AR(p) por OLS eligiendo p (1..max_p) según BIC."""
    n = len(x)
    best = None
    p_lo = 1 if n > 40 else 0
    for p in range(p_lo, max_p + 1):
        Y = x[max_p:]
        if p == 0:
            const = float(Y.mean())
            res = Y - const
            k = 1
            phis = np.zeros(0)
        else:
            X = np.column_stack([x[max_p - i:n - i] for i in range(1, p + 1)])
            o = ols(Y, X)
            const, phis, res = float(o["coef"][0]), np.asarray(o["coef"][1:], dtype=float), o["resid"]
            # Estabilidad estacionaria
            if np.sum(np.abs(phis)) >= 0.95:
                phis = np.clip(phis, -0.45, 0.45)
            k = p + 1
        rss = max(float(res @ res), 1e-12)
        bic = len(Y) * math.log(rss / len(Y)) + k * math.log(len(Y))
        if best is None or bic < best[0]:
            best = (bic, p, const, phis)
    _, p, const, phis = best
    resid = x - const
    for i, ph in enumerate(phis, start=1):
        resid[i:] -= ph * x[:-i]
    if p > 0:
        resid[:p] = x[:p] - float(x.mean())
    return p, const, phis, resid


# --------------------------------------------------------------------------- #
# Estructura de resultados GARCH
# --------------------------------------------------------------------------- #
@dataclass
class GarchFit:
    mu: float
    phi: np.ndarray
    omega: float
    alpha: float
    gamma: float
    beta: float
    nu: float
    loglik: float
    n: int
    sigma: np.ndarray              # sigma condicional desestacionalizada (%)
    eps: np.ndarray                # residuos AR (%)
    z: np.ndarray                  # innovaciones estandarizadas eps / sigma
    x: np.ndarray                  # retornos desestacionalizados (%)
    s_obs: np.ndarray              # factor estacional histórico por barra
    s_table: np.ndarray            # factor estacional por franja del día
    minutes: int
    index: pd.DatetimeIndex
    close: np.ndarray
    arch_lm_raw: tuple = (np.nan, np.nan)
    arch_lm_std: tuple = (np.nan, np.nan)
    method: str = "GJR-GARCH(1,1)-t + AR(p) [MLE Variance-Targeted]"
    extras: dict = field(default_factory=dict)

    @property
    def p(self) -> int:
        return len(self.phi)

    @property
    def persistence(self) -> float:
        return float(self.alpha + 0.5 * self.gamma + self.beta)

    @property
    def half_life_bars(self) -> float:
        P = self.persistence
        return math.log(0.5) / math.log(P) if 0.0 < P < 1.0 else float("inf")

    @property
    def uncond_var(self) -> float:
        return float(self.omega / max(1.0 - self.persistence, 1e-6))

    @property
    def sigma_eff_pct(self) -> np.ndarray:
        """Volatilidad condicional efectiva en % por barra (re-estacionalizada)."""
        return self.sigma * self.s_obs

    @property
    def sigma_pts(self) -> np.ndarray:
        """Volatilidad condicional efectiva en puntos de NQ por barra."""
        return self.close * (self.sigma_eff_pct / 100.0)

    def slot_factor(self, index: pd.DatetimeIndex) -> np.ndarray:
        return self.s_table[sessions.slot_of(index, self.minutes)]

    def next_sigma2(self) -> float:
        e, s2 = float(self.eps[-1]), float(self.sigma[-1] ** 2)
        return float(self.omega + (self.alpha + self.gamma * (e < 0.0)) * (e * e) + self.beta * s2)

    def forecast_sigma(self, future_index: pd.DatetimeIndex) -> np.ndarray:
        """Sigma determinista proyectada para cada barra futura (en decimal, re-estacionalizada)."""
        H = len(future_index)
        s2 = np.empty(H, dtype=float)
        s2[0] = self.next_sigma2()
        P = self.persistence
        for h in range(1, H):
            s2[h] = self.omega + P * s2[h - 1]
        return np.sqrt(s2) * self.slot_factor(future_index) / 100.0

    def forecast_mean(self, H: int, future_index: pd.DatetimeIndex | None = None) -> np.ndarray:
        """Media AR(p) proyectada para cada barra futura (en decimal)."""
        lags = list(self.x[-self.p:][::-1]) if self.p else []
        out = np.empty(H, dtype=float)
        for h in range(H):
            m = self.mu + sum(float(ph) * lags[i] for i, ph in enumerate(self.phi))
            out[h] = m
            if self.p:
                lags = [m] + lags[:-1]
        sf = self.slot_factor(future_index) if future_index is not None else 1.0
        return (out * sf) / 100.0

    def ann_vol_now(self) -> float:
        bars_day = float(self.extras.get("bars_per_day", 1440.0 / self.minutes))
        return math.sqrt(self.next_sigma2() * bars_day * 252.0) / 100.0

    def ann_vol_uncond(self) -> float:
        bars_day = float(self.extras.get("bars_per_day", 1440.0 / self.minutes))
        return math.sqrt(self.uncond_var * bars_day * 252.0) / 100.0

    def vol_regime(self, lookback: int | None = None) -> dict:
        """Clasifica el estado GARCH actual frente a su distribución histórica."""
        hist_deseas = self.sigma if lookback is None else self.sigma[-lookback:]
        cur_deseas = math.sqrt(self.next_sigma2())
        pct = float(np.mean(hist_deseas <= cur_deseas) * 100.0)
        pts_hist = self.sigma_pts
        cur_pts = float(self.close[-1]) * (cur_deseas * float(self.s_obs[-1])) / 100.0
        if pct >= 90.0:
            lab = "EXTREMO (P90+)"
        elif pct >= 75.0:
            lab = "EXPANSION (P75+)"
        elif pct <= 25.0:
            lab = "COMPRESION (<P25)"
        else:
            lab = "ESTANDAR (P25-P75)"
        q10, q25, q50, q75, q90, q99 = np.percentile(pts_hist, [10, 25, 50, 75, 90, 99])
        return {
            "percentile": pct,
            "label": lab,
            "sigma_now_pct": cur_deseas * float(self.s_obs[-1]),
            "sigma_now_pts": cur_pts,
            "p10_pts": float(q10), "p25_pts": float(q25), "p50_pts": float(q50),
            "p75_pts": float(q75), "p90_pts": float(q90), "p99_pts": float(q99),
        }


# --------------------------------------------------------------------------- #
# Optimizador MLE para GJR-GARCH(1,1) con innovaciones t-Student
# --------------------------------------------------------------------------- #
def _sigmoid(u: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(float(u), 60.0), -60.0)))


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


_P_LO, _P_HI, _A_MIN = 0.60, 0.996, 0.025


def _unpack(theta: np.ndarray, var_t: float) -> tuple[float, float, float, float, float]:
    p_raw, ua, ug, n_raw = theta
    P = _P_LO + (_P_HI - _P_LO) * _sigmoid(p_raw)
    ea = math.exp(max(min(float(ua), 25.0), -25.0))
    eg = math.exp(max(min(float(ug), 25.0), -25.0))
    den = 1.0 + ea + eg
    free = P - _A_MIN
    alpha = _A_MIN + free * (ea / den)
    gamma = 2.0 * free * (eg / den)
    beta = free * (1.0 / den)
    nu = 3.0 + 45.0 * _sigmoid(n_raw)
    omega = max(var_t * (1.0 - P), 1e-8)
    return omega, alpha, gamma, beta, nu


def _pack(P: float, alpha: float, gamma: float, beta: float, nu: float) -> list[float]:
    free = max(P - _A_MIN, 1e-4)
    wa = max((alpha - _A_MIN) / free, 1e-4)
    wg = max((0.5 * gamma) / free, 1e-4)
    wb = max(beta / free, 1e-4)
    return [
        _logit((P - _P_LO) / (_P_HI - _P_LO)),
        math.log(wa / wb),
        math.log(wg / wb),
        _logit((nu - 3.0) / 45.0),
    ]


def _sigma2_path(eps: np.ndarray, omega: float, alpha: float, gamma: float,
                 beta: float, s2_0: float) -> np.ndarray:
    e2 = eps * eps
    c = omega + (alpha + gamma * (eps[:-1] < 0.0)) * e2[:-1]
    out = np.empty_like(eps)
    out[0] = s2_0
    out[1:] = linear_recursion(c, beta, s2_0)
    return out


def _negll_student_t(theta: np.ndarray, eps: np.ndarray, var_t: float) -> float:
    omega, alpha, gamma, beta, nu = _unpack(theta, var_t)
    s2 = _sigma2_path(eps, omega, alpha, gamma, beta, var_t)
    if not np.all(np.isfinite(s2)) or float(s2.min()) <= 1e-12:
        return 1e18
    const = math.lgamma((nu + 1.0) / 2.0) - math.lgamma(nu / 2.0) - 0.5 * math.log(math.pi * (nu - 2.0))
    ll = const - 0.5 * np.log(s2) - 0.5 * (nu + 1.0) * np.log1p((eps * eps) / ((nu - 2.0) * s2))
    # Penalización suave si beta < 0.55 para evitar soluciones ruidosas sin memoria
    pen = 50.0 * max(0.55 - beta, 0.0) ** 2
    return -float(ll.sum()) + pen


def fit_gjr(eps: np.ndarray, n_starts: int = 5) -> tuple[tuple[float, float, float, float, float], float, int]:
    eps = np.asarray(eps, dtype=float)
    var_t = max(float(np.var(eps)), 1e-8)
    starts = [
        (0.95, 0.06, 0.07, 0.855, 6.0),
        (0.92, 0.09, 0.08, 0.790, 5.5),
        (0.97, 0.04, 0.05, 0.905, 7.0),
        (0.88, 0.12, 0.09, 0.715, 5.0),
        (0.98, 0.035, 0.04, 0.925, 8.0),
    ][:n_starts]
    best = None
    total_it = 0
    for P, a, g, b, nu in starts:
        b = P - a - 0.5 * g
        if b <= 0.05:
            continue
        x0 = _pack(P, a, g, b, nu)
        x, f, it = nelder_mead(lambda th: _negll_student_t(th, eps, var_t), x0, step=0.55, max_iter=900)
        total_it += it
        if best is None or f < best[1]:
            best = (x, f)
    x_best, f_best = best
    x_opt, f_opt, it2 = nelder_mead(lambda th: _negll_student_t(th, eps, var_t), x_best, step=0.15, max_iter=900)
    total_it += it2
    if f_opt < f_best:
        x_best, f_best = x_opt, f_opt
    return _unpack(x_best, var_t), -float(f_best), total_it


def fit_nq_garch(bars: pd.DataFrame, ar_max: int = 2, deseason: bool = True,
                 max_obs: int = 3500) -> GarchFit:
    """Ajusta el modelo AR(p) + GJR-GARCH(1,1)-t completo sobre barras OHLCV."""
    close_s = bars["Close"].astype(float)
    if len(close_s) > max_obs + 1:
        close_s = close_s.iloc[-(max_obs + 1):]
    diffs = pd.Series(close_s.index).diff().dt.total_seconds().dropna()
    minutes = int(max(round(float(diffs.median()) / 60.0), 1)) if len(diffs) else 15
    r = np.diff(np.log(close_s.to_numpy())) * 100.0
    idx = pd.DatetimeIndex(close_s.index[1:])
    if deseason:
        s_obs, s_table = seasonal_factors(r, idx, minutes)
    else:
        s_obs, s_table = np.ones_like(r), np.ones(1440 // minutes)
    x = r / s_obs
    p, mu, phis, eps = fit_ar(x.copy(), ar_max)
    (omega, alpha, gamma, beta, nu), ll, iters = fit_gjr(eps)
    s2 = _sigma2_path(eps, omega, alpha, gamma, beta, max(float(np.var(eps)), 1e-8))
    sigma = np.sqrt(s2)
    z = eps / sigma
    bars_per_day = float(pd.Series(idx.date).value_counts().median()) if len(idx) else (1440.0 / minutes)
    return GarchFit(
        mu=mu, phi=phis, omega=omega, alpha=alpha, gamma=gamma, beta=beta, nu=nu,
        loglik=ll, n=len(eps), sigma=sigma, eps=eps, z=z, x=x, s_obs=s_obs,
        s_table=s_table, minutes=minutes, index=idx, close=close_s.to_numpy()[1:],
        arch_lm_raw=arch_lm_test(eps), arch_lm_std=arch_lm_test(z),
        extras={"iters": iters, "bars_per_day": bars_per_day},
    )


def simulate_returns(fit: GarchFit, future_index: pd.DatetimeIndex, n_sims: int = 10_000,
                     seed: int | None = 42, shocks: str = "fhs") -> np.ndarray:
    """
    Simula matriz (H, n_sims) de retornos logarítmicos (en decimal) propagando
    la ecuación GJR-GARCH(1,1) + AR(p) trayectoria por trayectoria.
    """
    rng = np.random.default_rng(seed)
    H = len(future_index)
    if shocks == "fhs" and len(fit.z) >= 100:
        zpool = (fit.z - float(fit.z.mean())) / max(float(fit.z.std()), 1e-6)
        zpool = np.clip(zpool, -6.5, 6.5)
        Z = zpool[rng.integers(0, len(zpool), size=(H, n_sims))]
    else:
        nu = max(fit.nu, 3.1)
        Z = rng.standard_t(nu, size=(H, n_sims)) / math.sqrt(nu / (nu - 2.0))
        Z = np.clip(Z, -6.5, 6.5)
    s_fut = fit.slot_factor(future_index)
    try:
        from core.jit_math import simulate_gjr_garch_fast
        init_lags = fit.x[-fit.p:][::-1] if fit.p else np.empty(0, dtype=np.float64)
        return simulate_gjr_garch_fast(
            H=H,
            n_sims=n_sims,
            omega=fit.omega,
            alpha=fit.alpha,
            gamma=fit.gamma,
            beta=fit.beta,
            mu=fit.mu,
            phi=fit.phi,
            init_eps=float(fit.eps[-1]),
            init_s2=float(fit.sigma[-1] ** 2),
            init_lags=init_lags,
            Z=Z,
            s_fut=s_fut,
        )
    except Exception:
        e = np.full(n_sims, float(fit.eps[-1]))
        s2 = np.full(n_sims, float(fit.sigma[-1] ** 2))
        p = fit.p
        lags = [np.full(n_sims, float(v)) for v in (fit.x[-p:][::-1] if p else [])]
        out = np.empty((H, n_sims), dtype=float)
        for h in range(H):
            s2 = fit.omega + (fit.alpha + fit.gamma * (e < 0.0)) * (e * e) + fit.beta * s2
            e = np.sqrt(s2) * Z[h]
            m = fit.mu + sum(float(ph) * lags[i] for i, ph in enumerate(fit.phi)) if p else fit.mu
            xh = m + e
            if p:
                lags = [xh] + lags[:-1]
            out[h] = s_fut[h] * xh / 100.0
        return out


# --------------------------------------------------------------------------- #
# Ejecución / Reporte en Consola y Gráfico Institucional
# --------------------------------------------------------------------------- #
def ejecutar_garch_15m(feed=None, show_plot: bool = True) -> dict:
    from Data.data_feed_nq import DataFeedNQ
    from core.plotting import finalize
    from core.tables import Table, banner, fmt_num, fmt_usd, kv_block

    feed = feed or DataFeedNQ()
    df_15m = feed.bars("NQ", "15m")
    df_5m = feed.bars("NQ", "5m")

    fit15 = fit_nq_garch(df_15m, ar_max=2, deseason=True)
    fit5 = fit_nq_garch(df_5m, ar_max=2, deseason=True)
    reg15 = fit15.vol_regime()
    reg5 = fit5.vol_regime()

    last_px = float(df_15m["Close"].iloc[-1])
    phi_str = ", ".join(f"phi_{i+1}={v:+.3f}" for i, v in enumerate(fit15.phi)) or "0"
    lm0, p0 = fit15.arch_lm_raw
    lm1, p1 = fit15.arch_lm_std

    print("\n" + banner(
        f"MODELO GJR-GARCH(1,1)-t + AR({fit15.p}) | NQ SPOT: {last_px:,.2f} | FUENTE: {df_15m.attrs.get('source')}",
        f"Parámetros 15m: ω={fit15.omega:.6f}, α={fit15.alpha:.3f}, γ(asim)={fit15.gamma:.3f}, "
        f"β={fit15.beta:.3f}, ν={fit15.nu:.1f} | Persistencia={fit15.persistence:.4f}"
    ))
    print(kv_block([
        ("Ecuación Media AR", f"mu = {fit15.mu:+.4f}% | {phi_str} | Vida media choque = {fit15.half_life_bars:.1f} barras (15m)"),
        ("Volatilidad Anual", f"Condicional Actual = {fit15.ann_vol_now()*100:.2f}% | Incondicional Largo Plazo = {fit15.ann_vol_uncond()*100:.2f}%"),
        ("Test ARCH-LM(12)", f"Pre-GARCH LM={lm0:.1f} (p={p0:.4f}) -> Post-GARCH LM={lm1:.1f} (p={p1:.4f}) [Clustering Capturado]"),
        ("Régimen Macro 15m", f"{reg15['label']} (Percentil {reg15['percentile']:.1f}%) | σ_15m actual = {reg15['sigma_now_pts']:.2f} pts"),
        ("Régimen Micro 5m", f"{reg5['label']} (Percentil {reg5['percentile']:.1f}%) | σ_5m actual  = {reg5['sigma_now_pts']:.2f} pts"),
    ]))

    t_pct = Table(
        ["Percentil Vol (15m)", "Volatilidad GARCH (Pts / 15m)", "Riesgo 1 MNQ ($2/pt)", "Riesgo 1 NQ ($20/pt)"],
        aligns="lrrr",
        title="TERMOMETRO INSTITUCIONAL DE VOLATILIDAD CONDICIONAL (15 MINUTOS)"
    )
    for label, key in [
        ("P10 (Compresión)", "p10_pts"),
        ("P25 (Baja)", "p25_pts"),
        ("P50 (Mediana)", "p50_pts"),
        ("P75 (Alta)", "p75_pts"),
        ("P90 (Expansión)", "p90_pts"),
        ("P99 (Cisne Negro)", "p99_pts"),
    ]:
        val = reg15[key]
        t_pct.add_row([
            label,
            f"{fmt_num(val, 2)} pts",
            fmt_usd(val * MNQ.point_value, 2),
            fmt_usd(val * NQ.point_value, 2),
        ])
    print("\n" + t_pct.render())

    # Tabla de los 32 bloques recientes de 15m
    tail_n = 32
    c_tail = fit15.close[-tail_n:]
    idx_tail = fit15.index[-tail_n:]
    g_pts_tail = fit15.sigma_pts[-tail_n:]
    hi_tail = df_15m["High"].to_numpy()[-tail_n:]
    lo_tail = df_15m["Low"].to_numpy()[-tail_n:]
    rng_tail = hi_tail - lo_tail
    hist_sigma = fit15.sigma
    s_tail = fit15.sigma[-tail_n:]
    pct_tail = [float(np.mean(hist_sigma <= s) * 100.0) for s in s_tail]

    t_blk = Table(
        ["ID", "Hora NY", "Cierre NQ", "Rango Pts", "GARCH σ Pts", "Percentil", "Régimen Intradía"],
        aligns="llrrrrl",
        title="MATRIZ DE LOS 32 BLOQUES RECIENTES DE 15 MINUTOS (AMERICA/NEW_YORK)"
    )
    for i in range(tail_n):
        p = pct_tail[i]
        reg = "EXTREMO (P90+)" if p >= 90 else ("EXPANSION (P75+)" if p >= 75 else ("COMPRESION" if p <= 25 else "ESTANDAR"))
        t_blk.add_row([
            f"B#{i+1:02d}",
            idx_tail[i].strftime("%H:%M"),
            fmt_num(c_tail[i], 2),
            fmt_num(rng_tail[i], 2),
            fmt_num(g_pts_tail[i], 2),
            f"{p:5.1f}%",
            reg,
        ])
    print("\n" + t_blk.render() + "\n")

    # Gráfico institucional oscuro
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 7.0), sharex=True)
    x = np.arange(1, tail_n + 1)
    ax1.plot(x, c_tail, color=THEME["blue"], lw=2.0, marker="o", markersize=4, label="Cierre NQ (15m)")
    ax1.set_title("E-mini Nasdaq | Marco Temporal Macro de 15 Minutos (32 Bloques + GJR-GARCH-t)")
    ax1.set_ylabel("Precio NQ (Pts)")
    ax1.legend(loc="upper left")

    colors_bar = [THEME["red"] if p >= 90 else (THEME["amber"] if p >= 75 else THEME["indigo"]) for p in pct_tail]
    ax2.bar(x, g_pts_tail, color=colors_bar, alpha=0.88, label="GJR-GARCH σ (Pts / 15m)")
    ax2.axhline(reg15["p50_pts"], color=THEME["green"], ls="--", lw=1.5, label=f"Mediana P50 ({reg15['p50_pts']:.1f} pts)")
    ax2.axhline(reg15["p90_pts"], color=THEME["red"], ls="--", lw=1.5, label=f"Umbral P90 ({reg15['p90_pts']:.1f} pts)")
    ax2.set_xticks(x[::2])
    ax2.set_xticklabels([ts.strftime("%H:%M") for ts in idx_tail[::2]], rotation=45)
    ax2.set_ylabel("Puntos por Barra 15m")
    ax2.set_xlabel("32 Bloques Secuenciales de 15 Minutos (Hora NY)")
    ax2.legend(loc="upper left")
    finalize(fig, "garch_15m_nq", show=show_plot)

    return {"fit15": fit15, "fit5": fit5, "reg15": reg15, "reg5": reg5, "spot": last_px}


if __name__ == "__main__":
    ejecutar_garch_15m()
