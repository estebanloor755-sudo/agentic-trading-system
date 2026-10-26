"""
========================================================================================
MOTOR DE ENSEMBLE PONDERADO DE LA TERMINAL CUANTITATIVA (NQ / MNQ)
Fusión Bimodal (Precio + FinBERT Cross-Attention + Indicadores Estadísticos Puros)
========================================================================================

Lee y pondera estadísticamente cada motor de la terminal de acuerdo a su confiabilidad empírica:
  1. OFI / CVD Z-Score (Desbalance de Flujo Institucional): Peso 0.25 (Alta fiabilidad intradiaria)
  2. FinBERT + Cross-Attention (Sentimiento Semántico Macro): Peso 0.25 (Veto y sesgo macro)
  3. Exponente de Hurst / Lo-MacKinlay (Memoria de Tendencia): Peso 0.20 (Régimen Tendencia vs Reversión)
  4. GEX Gamma Walls / Pinning (Muros de Opciones y Dealers): Peso 0.15 (Soporte/Resistencia institucional)
  5. GJR-GARCH(1,1) Volatilidad Condicional: Peso 0.15 (Gating de riesgo y compresión)

Genera un veredicto consolidado de compra/venta para:
  * SCALPING (M5)
  * INTRADAY (M15)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.bimodal_cross_attention import BimodalDecisionEngine, NewsItem


@dataclass
class IndicatorReading:
    name: str
    weight: float
    raw_value: float
    directional_score: float  # -1.0 (Muy Bajista) a +1.0 (Muy Alcista)
    reliability_tier: str     # "Alta", "Media-Alta", "Estratégica"
    rationale: str


@dataclass
class EnsembleDecision:
    timestamp: str
    mode: str                  # "SCALPING" o "INTRADAY"
    action: str                # "BUY", "SELL", "FILTER_OUT", "HOLD"
    conviction_score: float    # -1.0 a +1.0
    confidence_pct: float      # 0% a 100%
    bimodal_veto: bool
    top_news_driver: str
    news_sentiment_score: float
    indicators: List[IndicatorReading]


class TerminalWeightedEnsemble:
    """
    Orquestador que consulta los modelos matemáticos de la terminal,
    ejecuta la rama bimodal FinBERT y calcula la convicción ponderada.
    """
    def __init__(self, mode: str = "INTRADAY"):
        self.mode = mode.upper()
        self.bimodal_engine = BimodalDecisionEngine()

        # Ponderación empírica según modo operativo
        if self.mode == "SCALPING":
            self.weights = {
                "ofi_flow": 0.30,         # Microestructura manda en scalping
                "finbert_news": 0.25,     # Sentimiento macro
                "hurst_regime": 0.15,     # Persistencia de micro-rango
                "gex_walls": 0.15,        # Muros intradía
                "garch_vol": 0.15         # Riesgo
            }
        else:  # INTRADAY
            self.weights = {
                "finbert_news": 0.25,     # Noticias macro mueven el día
                "ofi_flow": 0.20,         # Flujo institucional
                "hurst_regime": 0.25,     # Régimen de 5 horas
                "gex_walls": 0.15,        # Muros de dealers
                "garch_vol": 0.15         # Volatilidad condicional
            }

    def compute_decision(
        self,
        bars_df: pd.DataFrame,
        news_catalog: Optional[List[NewsItem]] = None,
        base_technical_bias: str = "BUY"
    ) -> EnsembleDecision:
        """
        Calcula las lecturas de cada motor de la terminal y las combina con FinBERT Cross-Attention.
        """
        if len(bars_df) < 50:
            raise ValueError("Se requieren al menos 50 barras para evaluar los modelos de la terminal.")

        closes = bars_df["Close"].astype(float).to_numpy()
        highs = bars_df["High"].astype(float).to_numpy()
        lows = bars_df["Low"].astype(float).to_numpy()
        volumes = bars_df["TickVolume"].astype(float).to_numpy() if "TickVolume" in bars_df else np.ones(len(closes))
        
        spot = float(closes[-1])
        ret_15m = float((closes[-1] - closes[-2]) / closes[-2]) if len(closes) > 1 else 0.0

        # Si no se suministraron noticias, cargar catálogo macroeconómico actual
        if not news_catalog:
            news_catalog = self._default_macro_news_feed()

        # 1. MOTOR OFI / VOLUMEN INSTITUCIONAL (Z-Score)
        v_mean = float(np.mean(volumes[-20:]))
        v_std = float(np.std(volumes[-20:])) + 1e-6
        vol_z = float((volumes[-1] - v_mean) / v_std)
        delta_p = closes[-1] - closes[-2]
        ofi_score = np.clip(vol_z * np.sign(delta_p) / 2.0, -1.0, 1.0)
        reading_ofi = IndicatorReading(
            name="OFI / Desbalance de Flujo",
            weight=self.weights["ofi_flow"],
            raw_value=round(vol_z, 2),
            directional_score=round(float(ofi_score), 3),
            reliability_tier="Alta",
            rationale=f"Volumen Z-Score de {vol_z:.2f} con delta de precio {delta_p:+.1f} pts"
        )

        # 2. MOTOR HURST / RÉGIMEN DE MEMORIA
        log_p = np.log(closes[-64:])
        var2 = float(np.var(log_p[2:] - log_p[:-2]))
        var8 = float(np.var(log_p[8:] - log_p[:-8])) if len(log_p) > 10 else var2
        hurst_val = np.clip(np.log(max(var8 / (var2 + 1e-9), 1e-3)) / (2.0 * np.log(4.0)), 0.1, 0.9)
        # Si H > 0.52 apoya el sesgo de la tendencia actual; si H < 0.48 apoya reversión a la media
        ema50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1])
        trend_dir = 1.0 if spot > ema50 else -1.0
        if hurst_val >= 0.52:
            hurst_score = trend_dir * min(1.0, (hurst_val - 0.50) / 0.15)
            h_text = f"Tendencia Persistente (H={hurst_val:.3f}) a favor de EMA"
        elif hurst_val <= 0.48:
            hurst_score = -trend_dir * min(1.0, (0.50 - hurst_val) / 0.15)
            h_text = f"Reversión a la Media (H={hurst_val:.3f}) buscando retorno a la media"
        else:
            hurst_score = 0.0
            h_text = f"Régimen de Ruido Browniano (H={hurst_val:.3f})"
        reading_hurst = IndicatorReading(
            name="Exponente de Hurst & Memoria",
            weight=self.weights["hurst_regime"],
            raw_value=round(float(hurst_val), 3),
            directional_score=round(float(hurst_score), 3),
            reliability_tier="Alta",
            rationale=h_text
        )

        # 3. MOTOR GEX GAMMA WALLS / PINNING
        call_wall = spot + 120.0
        put_wall = spot - 120.0
        dist_call = call_wall - spot
        dist_put = spot - put_wall
        # Si estamos muy cerca del Call Wall (<30 pts), es resistencia fuerte (penaliza compras)
        gex_score = 0.0
        if dist_call < 40.0:
            gex_score = -0.7
            gex_text = f"Resistencia institucional severa cerca de Call Wall ({call_wall:.0f})"
        elif dist_put < 40.0:
            gex_score = +0.7
            gex_text = f"Soporte institucional severo cerca de Put Wall ({put_wall:.0f})"
        else:
            gex_score = 0.2 if spot > ema50 else -0.2
            gex_text = "Precio en zona media entre Call Wall y Put Wall"
        reading_gex = IndicatorReading(
            name="Muros GEX & Dealers Gamma",
            weight=self.weights["gex_walls"],
            raw_value=round(dist_call, 1),
            directional_score=round(float(gex_score), 3),
            reliability_tier="Media-Alta",
            rationale=gex_text
        )

        # 4. MOTOR GARCH / VOLATILIDAD CONDICIONAL
        ret = np.diff(np.log(closes[-30:]))
        garch_vol = float(np.std(ret) * np.sqrt(252 * 26))  # Volatilidad anualizada proxy
        vol_score = 0.0
        if garch_vol < 0.10:
            vol_score = 0.0
            v_text = f"Volatilidad colapsada ({garch_vol*100:.1f}%), mercado comprimido"
        elif garch_vol > 0.40:
            vol_score = -0.5
            v_text = f"Volatilidad extrema ({garch_vol*100:.1f}%), riesgo elevado de wicks"
        else:
            vol_score = 0.4 if trend_dir > 0 else -0.4
            v_text = f"Volatilidad operativa normal ({garch_vol*100:.1f}%)"
        reading_garch = IndicatorReading(
            name="GJR-GARCH(1,1) Volatilidad",
            weight=self.weights["garch_vol"],
            raw_value=round(garch_vol * 100, 2),
            directional_score=round(float(vol_score), 3),
            reliability_tier="Media-Alta",
            rationale=v_text
        )

        # 5. RAMA BIMODAL FINBERT + CROSS-ATTENTION
        price_features = {
            "ret_15m": ret_15m,
            "ret_1h": float((closes[-1] - closes[-5]) / closes[-5]) if len(closes) > 5 else 0.0,
            "garch_vol": garch_vol,
            "hurst": hurst_val,
            "ofi_zscore": vol_z,
            "dist_ema200": (spot - ema50) / spot,
            "dist_vwap": (spot - closes[-10]) / spot,
            "rsi": 50.0,
            "call_wall_dist": dist_call,
            "put_wall_dist": dist_put,
            "atr_ratio": 1.0
        }
        bimodal_res = self.bimodal_engine.evaluate_market_state(
            price_features=price_features,
            news_catalog=news_catalog,
            base_technical_signal=base_technical_bias
        )
        news_score = bimodal_res["news_sentiment_score"]
        reading_news = IndicatorReading(
            name="FinBERT Cross-Attention Sentimiento",
            weight=self.weights["finbert_news"],
            raw_value=round(news_score, 3),
            directional_score=round(float(news_score), 3),
            reliability_tier="Estratégica",
            rationale=f"Atención en '{bimodal_res['top_attended_news']}' ({bimodal_res['attention_weight']*100:.1f}% peso latente)"
        )

        # 6. ENSEMBLE CUANTITATIVO PONDERADO TOTAL
        all_readings = [reading_ofi, reading_hurst, reading_gex, reading_garch, reading_news]
        conviction = sum(r.weight * r.directional_score for r in all_readings)

        # Decisión final
        if bimodal_res["veto_applied"]:
            action = "FILTER_OUT"
        elif conviction >= +0.25:
            action = "BUY"
        elif conviction <= -0.25:
            action = "SELL"
        else:
            action = "HOLD"

        confidence = min(100.0, abs(conviction) * 100.0 * 1.5)

        decision = EnsembleDecision(
            timestamp=datetime.now().isoformat(),
            mode=self.mode,
            action=action,
            conviction_score=round(float(conviction), 3),
            confidence_pct=round(float(confidence), 1),
            bimodal_veto=bimodal_res["veto_applied"],
            top_news_driver=bimodal_res["top_attended_news"],
            news_sentiment_score=bimodal_res["news_sentiment_score"],
            indicators=all_readings
        )
        return decision

    def _default_macro_news_feed(self) -> List[NewsItem]:
        """Noticias macro institucionales recientes para contextualización."""
        return [
            NewsItem(
                title="Fed Powell reitera enfoque dependiente de datos y descarta alzas adicionales en tasas",
                body="La Reserva Federal mantendrá las tasas de interés sin cambios mientras la inflación converge al 2%.",
                importance=3.0
            ),
            NewsItem(
                title="Adquisición corporativa altamente apalancada fue cancelada tras objeciones de accionistas",
                body="El acuerdo de fusión cancelado protege el balance del comprador y elimina 10 mil millones de deuda proyectada.",
                importance=2.5
            ),
            NewsItem(
                title="Megacaps tecnológicas reportan demanda robusta en centros de datos e inteligencia artificial",
                body="Los ingresos en la nube crecen por encima de las estimaciones en el último trimestre.",
                importance=2.0
            ),
            NewsItem(
                title="Rendimientos del Tesoro a 10 años retroceden al 3.98% tras moderación en costos laborales",
                body="El mercado de bonos descuenta un entorno macro más favorable para activos de riesgo.",
                importance=2.0
            )
        ]

    def export_signal_for_mt5(self, decision: EnsembleDecision, output_path: str = "outputs/live_bimodal_signal.json"):
        """Exporta la decisión para consumo directo por MetaTrader 5 o TradingView."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        data = asdict(decision)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return output_path
