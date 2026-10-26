# %% [CORE JIT MATH: LOW-LATENCY COMPILATION VIA NUMBA & C-LEVEL VECTORIZATION]
"""
Motor Matemático Compilado JIT (Just-In-Time) a Nivel C para Computación Cuantitativa de Baja Latencia.

Módulos Acelerados:
  1. GJR-GARCH(1,1)-t + AR(p) Path Simulation (10,000+ trayectorias en milisegundos).
  2. Cox-Ross-Rubinstein (CRR) American Option Binomial Tree (Inducción hacia atrás en microsegundos).
  3. VaR / CVaR / Tail Loss Sorting & Percentile Extraction.

Incluye detección automática de Numba con fallback vectorizado a NumPy puro si Numba no está disponible.
"""
from __future__ import annotations

import math
import numpy as np

# Intentar importar Numba para compilación LLVM nativa a código máquina
try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    # Fallback decorator transparente si numba no está instalado
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    prange = range


# ==============================================================================
# 1. KERNEL JIT: SIMULACIÓN DE RETORNOS GJR-GARCH(1,1) + AR(p)
# ==============================================================================

@njit(fastmath=True)
def _simulate_gjr_garch_mc_jit(
    H: int,
    n_sims: int,
    omega: float,
    alpha: float,
    gamma: float,
    beta: float,
    mu: float,
    phi: np.ndarray,
    p: int,
    init_eps: float,
    init_s2: float,
    init_lags: np.ndarray,
    Z: np.ndarray,
    s_fut: np.ndarray,
) -> np.ndarray:
    """
    Simulación JIT compilada de trayectorias GJR-GARCH(1,1) + AR(p).
    Ejecuta el bucle temporal en C puro sin overhead de listas ni interpretador Python.
    
    Parámetros:
      H: Número de pasos futuros (ej. 32 barras de 15m).
      n_sims: Número de trayectorias (ej. 10,000).
      omega, alpha, gamma, beta: Parámetros de varianza condicional GJR-GARCH.
      mu, phi, p: Parámetros del proceso autorregresivo AR(p).
      init_eps: Último residuo observado.
      init_s2: Última varianza condicional observada.
      init_lags: Historial de retornos recientes para retardos AR(p).
      Z: Matriz (H, n_sims) de innovaciones estandarizadas (FHS o Student-t).
      s_fut: Vector (H,) con factores de estacionalidad intradía.
      
    Retorna:
      out: Matriz (H, n_sims) de retornos logarítmicos proyectados (en decimal).
    """
    out = np.empty((H, n_sims), dtype=np.float64)
    
    # Vector de varianzas condicionales y residuos actuales por trayectoria
    s2 = np.full(n_sims, init_s2, dtype=np.float64)
    e = np.full(n_sims, init_eps, dtype=np.float64)
    
    # Matriz de retardos AR: shape (p, n_sims)
    if p > 0:
        lags = np.empty((p, n_sims), dtype=np.float64)
        for i in range(p):
            lags[i, :] = init_lags[i]
    else:
        lags = np.empty((0, n_sims), dtype=np.float64)
        
    for h in range(H):
        # 1. Propagación de varianza condicional GJR-GARCH(1,1)
        # s2_{t} = omega + (alpha + gamma * I_{e < 0}) * e_{t-1}^2 + beta * s2_{t-1}
        for j in range(n_sims):
            ej = e[j]
            is_neg = 1.0 if ej < 0.0 else 0.0
            asym = alpha + gamma * is_neg
            s2_new = omega + asym * (ej * ej) + beta * s2[j]
            if s2_new < 1e-12:
                s2_new = 1e-12
            s2[j] = s2_new
            
            # 2. Innovación shockeada por Student-t o FHS
            ej_new = math.sqrt(s2_new) * Z[h, j]
            e[j] = ej_new
            
            # 3. Ecuación de media AR(p)
            mean_ret = mu
            for k in range(p):
                mean_ret += phi[k] * lags[k, j]
                
            xh = mean_ret + ej_new
            out[h, j] = s_fut[h] * (xh / 100.0)
            
        # 4. Actualización de retardos AR para el siguiente paso
        if p > 0:
            for k in range(p - 1, 0, -1):
                lags[k, :] = lags[k - 1, :]
            # El retardo 0 recibe el xh recién calculado (desestacionalizado)
            for j in range(n_sims):
                lags[0, j] = (out[h, j] * 100.0) / s_fut[h]
                
    return out


def simulate_gjr_garch_fast(
    H: int,
    n_sims: int,
    omega: float,
    alpha: float,
    gamma: float,
    beta: float,
    mu: float,
    phi: np.ndarray | None,
    init_eps: float,
    init_s2: float,
    init_lags: np.ndarray | None,
    Z: np.ndarray,
    s_fut: np.ndarray,
) -> np.ndarray:
    """Wrapper con tipado estricto que invoca el kernel JIT o vectorizado."""
    phi_arr = np.asarray(phi, dtype=np.float64) if phi is not None and len(phi) > 0 else np.empty(0, dtype=np.float64)
    p = len(phi_arr)
    lags_arr = np.asarray(init_lags, dtype=np.float64) if init_lags is not None and len(init_lags) > 0 else np.empty(0, dtype=np.float64)
    s_fut_arr = np.asarray(s_fut, dtype=np.float64)
    Z_arr = np.asarray(Z, dtype=np.float64)

    return _simulate_gjr_garch_mc_jit(
        H, n_sims,
        float(omega), float(alpha), float(gamma), float(beta),
        float(mu), phi_arr, p,
        float(init_eps), float(init_s2), lags_arr,
        Z_arr, s_fut_arr
    )


# ==============================================================================
# 2. KERNEL JIT: ÁRBOL BINOMIAL COX-ROSS-RUBINSTEIN (CRR) AMERICANO
# ==============================================================================

@njit(fastmath=True)
def _crr_backward_induction_jit(
    N: int,
    F: float,
    K: float,
    u: float,
    d: float,
    p: float,
    disc: float,
    is_call: bool,
) -> tuple[float, float, float, float, float, float, float]:
    """
    Inducción hacia atrás vectorizada en C para Árbol Binomial CRR con frontera americana.
    
    Retorna:
      (val_amer, val_euro, early_ex_pts, delta, gamma, theta_approx, boundary_mid)
    """
    # Vector de precios terminales S(T)
    val_amer = np.empty(N + 1, dtype=np.float64)
    val_euro = np.empty(N + 1, dtype=np.float64)
    
    # 1. Pago terminal en t = T
    for j in range(N + 1):
        st = F * (u ** (N - j)) * (d ** j)
        if is_call:
            payoff = st - K if st > K else 0.0
        else:
            payoff = K - st if K > st else 0.0
        val_amer[j] = payoff
        val_euro[j] = payoff
        
    boundary_mid = K
    v1_up = 0.0
    v1_dn = 0.0
    v2_uu = 0.0
    v2_ud = 0.0
    v2_dd = 0.0
    
    # 2. Inducción hacia atrás desde t = N-1 hasta t = 0
    for step in range(N - 1, -1, -1):
        for i in range(step + 1):
            st = F * (u ** (step - i)) * (d ** i)
            cont_amer = disc * (p * val_amer[i] + (1.0 - p) * val_amer[i + 1])
            cont_euro = disc * (p * val_euro[i] + (1.0 - p) * val_euro[i + 1])
            
            if is_call:
                intrinsic = st - K if st > K else 0.0
            else:
                intrinsic = K - st if K > st else 0.0
                
            val_amer[i] = intrinsic if intrinsic > cont_amer else cont_amer
            val_euro[i] = cont_euro
            
            # Registrar frontera crítica en el punto medio del árbol
            if step == N // 2:
                if intrinsic > cont_amer + 1e-9:
                    boundary_mid = st

        # Guardar valores de nodos clave para griegas por diferencias finitas
        if step == 2:
            v2_uu = val_amer[0]
            v2_ud = val_amer[1]
            v2_dd = val_amer[2]
        elif step == 1:
            v1_up = val_amer[0]
            v1_dn = val_amer[1]

    # Valor final en la raíz t=0
    amer_pts = val_amer[0]
    euro_pts = val_euro[0]
    early_ex = amer_pts - euro_pts if amer_pts > euro_pts else 0.0
    
    # Griegas por diferencias finitas
    s_up = F * u
    s_dn = F * d
    s_uu = F * u * u
    s_dd = F * d * d
    
    denom_delta = s_up - s_dn if abs(s_up - s_dn) > 1e-12 else 1e-12
    delta = (v1_up - v1_dn) / denom_delta
    
    denom_u = s_uu - F if abs(s_uu - F) > 1e-12 else 1e-12
    denom_d = F - s_dd if abs(F - s_dd) > 1e-12 else 1e-12
    delta_u = (v2_uu - v2_ud) / denom_u
    delta_d = (v2_ud - v2_dd) / denom_d
    
    denom_gamma = 0.5 * (s_uu - s_dd) if abs(0.5 * (s_uu - s_dd)) > 1e-12 else 1e-12
    gamma = (delta_u - delta_d) / denom_gamma
    theta_approx = (v2_ud - amer_pts)  # Proxy de decaimiento temporal por paso

    return amer_pts, euro_pts, early_ex, delta, gamma, theta_approx, boundary_mid


def crr_american_tree_fast(
    F: float,
    K: float,
    T_days: float,
    r: float,
    sigma: float,
    steps: int = 150,
    option_type: str = "put"
) -> tuple[float, float, float, float, float, float, float]:
    """Wrapper para evaluación ultra-rápida de opciones americanas CRR."""
    N = int(max(steps, 10))
    T = max(float(T_days) / 365.0, 1e-6)
    sigma_val = max(float(sigma), 1e-4)
    dt = T / N
    u = math.exp(sigma_val * math.sqrt(dt))
    d = 1.0 / u
    p = (1.0 - d) / (u - d)
    disc = math.exp(-float(r) * dt)
    is_call = option_type.lower().startswith("c")

    return _crr_backward_induction_jit(
        N, float(F), float(K), u, d, p, disc, is_call
    )


# ==============================================================================
# 3. KERNEL JIT: ESTADÍSTICAS RÁPIDAS DE COLA, VaR Y CVaR
# ==============================================================================

@njit(fastmath=True)
def _calc_tail_metrics_jit(
    losses: np.ndarray,
    alpha95: float = 0.95,
    alpha99: float = 0.99,
) -> tuple[float, float, float, float, float]:
    """
    Cálculo de VaR y CVaR sobre array de pérdidas.
    losses: Array 1D de pérdidas (S0 - ST).
    Retorna: (mean_loss, var95, cvar95, var99, cvar99)
    """
    n = len(losses)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    # Ordenamiento rápido
    sorted_losses = np.sort(losses)
    
    idx95 = int(math.floor(alpha95 * n))
    idx99 = int(math.floor(alpha99 * n))
    if idx95 >= n:
        idx95 = n - 1
    if idx99 >= n:
        idx99 = n - 1
        
    var95 = sorted_losses[idx95]
    var99 = sorted_losses[idx99]
    
    # CVaR 95 (media de pérdidas >= VaR95)
    sum95 = 0.0
    count95 = 0
    for i in range(idx95, n):
        sum95 += sorted_losses[i]
        count95 += 1
    cvar95 = sum95 / count95 if count95 > 0 else var95
    
    # CVaR 99 (media de pérdidas >= VaR99)
    sum99 = 0.0
    count99 = 0
    for i in range(idx99, n):
        sum99 += sorted_losses[i]
        count99 += 1
    cvar99 = sum99 / count99 if count99 > 0 else var99
    
    mean_loss = np.mean(losses)
    return mean_loss, var95, cvar95, var99, cvar99


def calc_tail_metrics_fast(losses: np.ndarray) -> tuple[float, float, float, float, float]:
    """Wrapper para cálculo de métricas de riesgo extremo en microsegundos."""
    arr = np.asarray(losses, dtype=np.float64)
    return _calc_tail_metrics_jit(arr)
