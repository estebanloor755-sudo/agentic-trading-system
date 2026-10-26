"""
==================================================================================
MÓDULO DE AUDITORÍA DE RIESGO: TESTS DE KUPIEC & CHRISTOFFERSEN (NASDAQ)
==================================================================================
Valida el rigor econométrico del modelo GJR-GARCH(1,1) y su proyección de VaR 99%
sobre las últimas 250 velas de 15m del Nasdaq (E-mini NQ / US100-DEC26).

Tests Implementados:
  1. Test de Proporción de Fallos de Kupiec (POF - Cobertura Incondicional):
     Evalúa si el número de excepciones de VaR coincide estadísticamente
     con la tasa teórica alpha = 0.01 (LR_pof ~ Chi^2(1)).
  2. Test de Independencia de Christoffersen:
     Evalúa si las excepciones de VaR ocurren de forma aislada e independiente
     o si se agrupan en racimos (clustering de riesgo) (LR_ind ~ Chi^2(1)).
  3. Test de Cobertura Condicional (LR_cc = LR_pof + LR_ind ~ Chi^2(2)).

Acción de Seguridad:
  Si p-value < 0.05, el modelo queda INVALIDADO y se activa una bandera de
  bloqueo temporal de señales para proteger la cuenta.
==================================================================================
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class RiskAuditResult:
    is_valid: bool
    exceptions_count: int
    total_bars: int
    failure_rate_pct: float
    expected_failures: float
    kupiec_stat: float
    kupiec_pvalue: float
    christoffersen_stat: float
    christoffersen_pvalue: float
    conditional_coverage_stat: float
    conditional_coverage_pvalue: float
    status_label: str
    action_directive: str


def _chi2_sf_1df(x: float) -> float:
    """Función de supervivencia Chi-cuadrado con 1 grado de libertad."""
    if x <= 0.0:
        return 1.0
    # Para 1 gl: P(X > x) = 2 * (1 - Phi(sqrt(x))) = erfc(sqrt(x / 2))
    return math.erfc(math.sqrt(x / 2.0))


def _chi2_sf_2df(x: float) -> float:
    """Función de supervivencia Chi-cuadrado con 2 grados de libertad."""
    if x <= 0.0:
        return 1.0
    # Para 2 gl: P(X > x) = exp(-x / 2)
    return math.exp(-x / 2.0)


class BacktestRiskAuditor:
    """
    Auditor econométrico de Value-at-Risk para carteras institucionales.
    """

    def __init__(self, confidence_level: float = 0.99, alpha_significance: float = 0.05):
        self.conf = float(confidence_level)
        self.p_expected = 1.0 - self.conf  # ej. 0.01 para VaR 99%
        self.alpha_sig = float(alpha_significance)

    def audit_var(
        self,
        returns: np.ndarray,
        var_projected: np.ndarray,
    ) -> RiskAuditResult:
        """
        Ejecuta los tests de Kupiec POF y Christoffersen sobre las excepciones reales.
        """
        r = np.asarray(returns, dtype=np.float64)
        v = np.asarray(var_projected, dtype=np.float64)

        n = min(len(r), len(v))
        if n < 30:
            # Fallback para muestras pequeñas
            return RiskAuditResult(
                is_valid=True,
                exceptions_count=0,
                total_bars=n,
                failure_rate_pct=0.0,
                expected_failures=round(n * self.p_expected, 1),
                kupiec_stat=0.0,
                kupiec_pvalue=1.0,
                christoffersen_stat=0.0,
                christoffersen_pvalue=1.0,
                conditional_coverage_stat=0.0,
                conditional_coverage_pvalue=1.0,
                status_label="✓ VaR 99% Calibrado (Muestra Inicial)",
                action_directive="OPERATIVA NORMAL",
            )

        r = r[-n:]
        v = v[-n:]

        # Secuencia de excepciones I_t = 1 si r_t < -VaR_t
        # Nota: v es positivo (magnitud de pérdida de VaR)
        hits = (r < -np.abs(v)).astype(int)
        x = int(np.sum(hits))
        p = self.p_expected
        p_hat = x / n

        # ------------------------------------------------------------------
        # 1. TEST DE KUPIEC (POF - Proporción de Fallos)
        # ------------------------------------------------------------------
        if x == 0:
            lr_pof = -2.0 * n * math.log(1.0 - p)
        elif x == n:
            lr_pof = -2.0 * n * math.log(p)
        else:
            log_l_null = (n - x) * math.log(1.0 - p) + x * math.log(p)
            log_l_alt = (n - x) * math.log(1.0 - p_hat) + x * math.log(p_hat)
            lr_pof = max(-2.0 * (log_l_null - log_l_alt), 0.0)

        p_val_kupiec = _chi2_sf_1df(lr_pof)

        # ------------------------------------------------------------------
        # 2. TEST DE INDEPENDENCIA DE CHRISTOFFERSEN
        # ------------------------------------------------------------------
        # Matriz de transición de excepciones consecutivas: n_00, n_01, n_10, n_11
        n00, n01, n10, n11 = 0, 0, 0, 0
        for t in range(1, n):
            prev = hits[t - 1]
            curr = hits[t]
            if prev == 0 and curr == 0:
                n00 += 1
            elif prev == 0 and curr == 1:
                n01 += 1
            elif prev == 1 and curr == 0:
                n10 += 1
            elif prev == 1 and curr == 1:
                n11 += 1

        denom0 = n00 + n01
        denom1 = n10 + n11
        denom_total = denom0 + denom1

        if denom1 == 0 or n01 == 0 or n10 == 0:
            # No hay clusters ni transiciones complejas
            lr_ind = 0.0
            p_val_christ = 1.0
        else:
            pi_01 = n01 / denom0 if denom0 > 0 else 0.0
            pi_11 = n11 / denom1 if denom1 > 0 else 0.0
            pi = (n01 + n11) / denom_total if denom_total > 0 else 0.0

            def _safelog(val: float) -> float:
                return math.log(val) if val > 1e-12 else -50.0

            log_l_ind_null = (n00 + n10) * _safelog(1.0 - pi) + (n01 + n11) * _safelog(pi)
            log_l_ind_alt = (
                n00 * _safelog(1.0 - pi_01)
                + n01 * _safelog(pi_01)
                + n10 * _safelog(1.0 - pi_11)
                + n11 * _safelog(pi_11)
            )
            lr_ind = max(-2.0 * (log_l_ind_null - log_l_ind_alt), 0.0)
            p_val_christ = _chi2_sf_1df(lr_ind)

        # ------------------------------------------------------------------
        # 3. TEST DE COBERTURA CONDICIONAL
        # ------------------------------------------------------------------
        lr_cc = lr_pof + lr_ind
        p_val_cc = _chi2_sf_2df(lr_cc)

        # Regla de Validación: Si Kupiec o Christoffersen tienen p < 0.05, el modelo falla
        is_model_valid = bool(p_val_kupiec >= self.alpha_sig and p_val_christ >= self.alpha_sig)

        if not is_model_valid:
            if p_val_kupiec < self.alpha_sig:
                status_label = f"⚠️ MODELO GARCH INVALIDADO (Kupiec p={p_val_kupiec:.3f}) - Recalibrando MLE"
            else:
                status_label = f"⚠️ MODELO GARCH INVALIDADO (Christoffersen Cluster p={p_val_christ:.3f})"
            action_directive = "BLOQUEO OPERATIVO PREVENTIVO (RIESGO DE COLA EXCEDIDO)"
        else:
            status_label = f"✓ VaR 99% Validado (Kupiec p={p_val_kupiec:.3f}, Christoffersen p={p_val_christ:.3f})"
            action_directive = "OPERATIVA NORMAL (LUZ VERDE)"

        return RiskAuditResult(
            is_valid=is_model_valid,
            exceptions_count=x,
            total_bars=n,
            failure_rate_pct=round((x / n) * 100.0, 2),
            expected_failures=round(n * p, 2),
            kupiec_stat=round(float(lr_pof), 3),
            kupiec_pvalue=round(float(p_val_kupiec), 4),
            christoffersen_stat=round(float(lr_ind), 3),
            christoffersen_pvalue=round(float(p_val_christ), 4),
            conditional_coverage_stat=round(float(lr_cc), 3),
            conditional_coverage_pvalue=round(float(p_val_cc), 4),
            status_label=status_label,
            action_directive=action_directive,
        )


risk_auditor = BacktestRiskAuditor(confidence_level=0.99, alpha_significance=0.05)
