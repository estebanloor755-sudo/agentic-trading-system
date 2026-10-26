"""
Núcleo matemático sin dependencias duras (sólo NumPy).

Si SciPy está instalado se usa para la CDF normal exacta; si no, se usa una
aproximación de alta precisión. Incluye:
  * norm_cdf / norm_pdf / norm_ppf vectorizadas
  * linear_recursion: s_t = c_t + b * s_{t-1} vectorizada por bloques (GARCH rápido)
  * nelder_mead: optimizador sin derivadas, robusto y determinista
  * ols: regresión lineal con errores estándar
  * rolling_ols_beta: beta/alpha rodantes vectorizados
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np

try:  # SciPy opcional
    from scipy.special import ndtr as _ndtr, ndtri as _ndtri  # type: ignore
    HAS_SCIPY = True
except Exception:  # pragma: no cover
    HAS_SCIPY = False

SQRT2PI = math.sqrt(2.0 * math.pi)


def norm_pdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / SQRT2PI


def norm_cdf(x):
    """CDF normal estándar. SciPy si existe; si no, math.erfc vectorizada (precisión de máquina)."""
    x = np.asarray(x, dtype=float)
    if HAS_SCIPY:
        return _ndtr(x)
    # math.erfc vectorizada: exacta a precisión de máquina
    return 0.5 * _erfc_vec(-x / math.sqrt(2.0))


_erfc_vec = np.vectorize(math.erfc, otypes=[float])


def norm_ppf(p):
    """Inversa de la CDF normal (Acklam + 1 paso de Newton si no hay SciPy)."""
    p = np.asarray(p, dtype=float)
    if HAS_SCIPY:
        return _ndtri(p)
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    cc = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
          -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p = np.clip(p, 1e-15, 1 - 1e-15)
    q = np.where(p < 0.5, p, 1 - p)
    out = np.empty_like(p)
    lo = q < 0.02425
    r = np.sqrt(-2 * np.log(q[lo]))
    out[lo] = (((((cc[0]*r+cc[1])*r+cc[2])*r+cc[3])*r+cc[4])*r+cc[5]) / ((((d[0]*r+d[1])*r+d[2])*r+d[3])*r+1)
    mid = ~lo
    qq = q[mid] - 0.5
    r = qq * qq
    out[mid] = -(((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*qq / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    out = np.where(p < 0.5, out, -out)
    # refinamiento de Newton
    e = norm_cdf(out) - p
    out = out - e * SQRT2PI * np.exp(0.5 * out * out)
    return out


# --------------------------------------------------------------------------- #
# Recursión lineal vectorizada (clave para MLE GARCH rápido sin numba)
# --------------------------------------------------------------------------- #
def linear_recursion(c: np.ndarray, beta: float, s0: float, block: int = 48) -> np.ndarray:
    """
    Calcula s_t = c_t + beta * s_{t-1}, t = 0..n-1, con s_{-1} = s0.

    Se procesa en bloques: dentro de cada bloque la suma es una cumsum
    vectorizada; sólo los estados frontera se propagan con un bucle corto
    (n/block iteraciones). ~30x más rápido que un bucle Python puro.
    """
    c = np.asarray(c, dtype=float)
    n = c.size
    if n == 0:
        return c.copy()
    beta = float(beta)
    if beta < 0.05:  # estabilidad numérica de beta^-m: bucle directo (barato con beta chico)
        out = np.empty(n)
        s = s0
        for t in range(n):
            s = c[t] + beta * s
            out[t] = s
        return out
    nb = -(-n // block)
    pad = nb * block - n
    cp = np.concatenate([c, np.zeros(pad)]).reshape(nb, block) if pad else c.reshape(nb, block)
    m = np.arange(block, dtype=float)
    bpow = beta ** m
    partial = np.cumsum(cp / bpow, axis=1) * bpow          # estado inicial cero
    bp1 = bpow * beta                                       # beta^(m+1)
    last = partial[:, -1]
    bB = beta ** block
    starts = np.empty(nb)
    s = s0
    for k in range(nb):
        starts[k] = s
        s = bB * s + last[k]
    return (partial + starts[:, None] * bp1).ravel()[:n]


# --------------------------------------------------------------------------- #
# Nelder-Mead
# --------------------------------------------------------------------------- #
def nelder_mead(f: Callable[[np.ndarray], float], x0: Sequence[float], step: float | Sequence[float] = 0.5,
                max_iter: int = 3000, xtol: float = 1e-7, ftol: float = 1e-9) -> tuple[np.ndarray, float, int]:
    """Nelder-Mead adaptativo (Gao & Han 2012). Devuelve (x*, f*, iteraciones)."""
    x0 = np.asarray(x0, dtype=float)
    n = x0.size
    alpha, gamma = 1.0, 1.0 + 2.0 / n
    rho, sigma = 0.75 - 1.0 / (2 * n), 1.0 - 1.0 / n
    steps = np.full(n, step, dtype=float) if np.isscalar(step) else np.asarray(step, dtype=float)
    simplex = np.vstack([x0] + [x0 + np.eye(n)[i] * steps[i] for i in range(n)])
    fvals = np.array([_safe(f, x) for x in simplex])
    it = 0
    for it in range(1, max_iter + 1):
        order = np.argsort(fvals)
        simplex, fvals = simplex[order], fvals[order]
        if (np.max(np.abs(simplex[1:] - simplex[0])) < xtol and
                np.max(np.abs(fvals[1:] - fvals[0])) < ftol):
            break
        centroid = simplex[:-1].mean(axis=0)
        xr = centroid + alpha * (centroid - simplex[-1])
        fr = _safe(f, xr)
        if fr < fvals[0]:
            xe = centroid + gamma * (xr - centroid)
            fe = _safe(f, xe)
            simplex[-1], fvals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fvals[-2]:
            simplex[-1], fvals[-1] = xr, fr
        else:
            if fr < fvals[-1]:
                xc = centroid + rho * (xr - centroid)
            else:
                xc = centroid + rho * (simplex[-1] - centroid)
            fc = _safe(f, xc)
            if fc < min(fr, fvals[-1]):
                simplex[-1], fvals[-1] = xc, fc
            else:
                simplex[1:] = simplex[0] + sigma * (simplex[1:] - simplex[0])
                fvals[1:] = [_safe(f, x) for x in simplex[1:]]
    best = int(np.argmin(fvals))
    return simplex[best], float(fvals[best]), it


def _safe(f, x) -> float:
    try:
        v = float(f(x))
        return v if np.isfinite(v) else 1e18
    except (FloatingPointError, ValueError, OverflowError, ZeroDivisionError):
        return 1e18


# --------------------------------------------------------------------------- #
# Regresión
# --------------------------------------------------------------------------- #
def ols(y: np.ndarray, X: np.ndarray, add_const: bool = True) -> dict:
    """OLS con errores estándar clásicos. Devuelve coef, se, t, resid, r2, sigma."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    if add_const:
        X = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = X.shape
    dof = max(n - k, 1)
    s2 = float(resid @ resid) / dof
    try:
        cov = s2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        t = coef / se
    return {"coef": coef, "se": se, "t": t, "resid": resid, "r2": r2, "sigma": math.sqrt(s2), "n": n}


def rolling_ols_beta(y: np.ndarray, x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Beta y alpha rodantes (univariado) vía sumas acumuladas. O(n)."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    beta = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    if n < window:
        return beta, alpha

    def rsum(a):
        cs = np.concatenate([[0.0], np.cumsum(a)])
        return cs[window:] - cs[:-window]

    sx, sy = rsum(x), rsum(y)
    sxx, sxy = rsum(x * x), rsum(x * y)
    w = float(window)
    var = sxx - sx * sx / w
    cov = sxy - sx * sy / w
    with np.errstate(divide="ignore", invalid="ignore"):
        b = np.where(var > 1e-18, cov / var, np.nan)
    a = (sy - b * sx) / w
    beta[window - 1:] = b
    alpha[window - 1:] = a
    return beta, alpha


def rolling_zscore(x: np.ndarray, window: int, min_periods: int | None = None) -> np.ndarray:
    """Z-score rodante sin look-ahead (usa sólo datos hasta t)."""
    import pandas as pd
    s = pd.Series(np.asarray(x, dtype=float))
    mp = min_periods or max(window // 2, 5)
    mu = s.rolling(window, min_periods=mp).mean()
    sd = s.rolling(window, min_periods=mp).std(ddof=1)
    return ((s - mu) / sd.replace(0, np.nan)).to_numpy()


def adf_test(y: np.ndarray, max_lag: int | None = None, regression: str = "c") -> dict:
    """
    Dickey-Fuller aumentado (lag por AIC). Valores críticos MacKinnon (1 variable, con constante).
    Para residuos de cointegración (Engle-Granger, 2 variables) usar cv_eg.
    """
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    if max_lag is None:
        max_lag = int(min(12 * (n / 100.0) ** 0.25, n // 4))
    dy = np.diff(y)
    best = None
    for p in range(0, max_lag + 1):
        Y = dy[p:]
        cols = [y[p:-1]]
        for i in range(1, p + 1):
            cols.append(dy[p - i:-i])
        X = np.column_stack(cols)
        res = ols(Y, X, add_const=(regression == "c"))
        k = X.shape[1] + (1 if regression == "c" else 0)
        rss = float(res["resid"] @ res["resid"])
        aic = len(Y) * math.log(max(rss / max(len(Y), 1), 1e-18)) + 2 * k
        if best is None or aic < best[0]:
            idx = 1 if regression == "c" else 0
            best = (aic, p, res["t"][idx], res["coef"][idx])
    _, lag, tstat, gamma = best
    return {
        "stat": float(tstat), "lag": lag, "gamma": float(gamma),
        "cv": {"1%": -3.43, "5%": -2.86, "10%": -2.57},
        "cv_eg": {"1%": -3.90, "5%": -3.34, "10%": -3.04},
    }
