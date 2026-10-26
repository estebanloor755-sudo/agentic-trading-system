"""
Configuración central de la Terminal Cuantitativa NQ / MNQ (Vía MetaTrader 5 en Tiempo Real).

Todos los parámetros de especificaciones de contrato, sesiones de Wall Street
(`America/New_York`) y simbología de MetaTrader 5 (`USTEC` / `US100`) viven aquí
para mantener consistencia matemática pura en todos los modelos.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "Data" / "cache"
OUTPUT_DIR = ROOT_DIR / "outputs"
CHART_DIR = OUTPUT_DIR / "charts"

TZ_NY = "America/New_York"


# --------------------------------------------------------------------------- #
# Especificaciones de contrato (Valor puro por punto y tick, cero sesgo de cuenta)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    mt5_symbol: str
    point_value: float      # USD por punto puro (NQ=$20/pt, MNQ=$2/pt)
    tick_size: float = 0.25
    commission_per_side: float = 2.09

    @property
    def tick_value(self) -> float:
        return self.tick_size * self.point_value

    @property
    def round_trip_commission(self) -> float:
        return self.commission_per_side * 2.0


MT5_SYMBOL = "US100-DEC26"

NQ = ContractSpec("NQ", MT5_SYMBOL, point_value=20.0, tick_size=0.25, commission_per_side=2.09)
MNQ = ContractSpec("MNQ", MT5_SYMBOL, point_value=2.0, tick_size=0.25, commission_per_side=0.82)
CONTRACTS = {"NQ": NQ, "MNQ": MNQ}

# --------------------------------------------------------------------------- #
# DIRECTIVA V11: MICROESTRUCTURA CME Y COMISIONES DE FONDEO (RITHMIC/TRADOVATE)
# --------------------------------------------------------------------------- #
CME_FEE_SCHEDULE = {
    "NQ": {
        "NAME": "E-mini Nasdaq 100",
        "TICK_SIZE": 0.25,
        "TICK_VALUE": 5.00,
        "POINT_VALUE": 20.00,
        "COMMISSION_PER_SIDE": 2.09,
        "ROUND_TRIP_COMMISSION": 4.18,
        "SLIPPAGE_TICKS_MARKET": 1.0,
        "SLIPPAGE_TICKS_STOP": 1.0,
        "SLIPPAGE_TICKS_LIMIT": 0.0,
    },
    "MNQ": {
        "NAME": "Micro E-mini Nasdaq 100",
        "TICK_SIZE": 0.25,
        "TICK_VALUE": 0.50,
        "POINT_VALUE": 2.00,
        "COMMISSION_PER_SIDE": 0.82,
        "ROUND_TRIP_COMMISSION": 1.64,
        "SLIPPAGE_TICKS_MARKET": 1.0,
        "SLIPPAGE_TICKS_STOP": 1.0,
        "SLIPPAGE_TICKS_LIMIT": 0.0,
    },
}

# --------------------------------------------------------------------------- #
# DIRECTIVA DE FONDEO 25K (SUELO CRÍTICO EN $24,000 USD / BUFFER: $1,000 USD)
# --------------------------------------------------------------------------- #
ACCOUNT_25K_SPEC = {
    "NAME": "Cuenta de Fondeo 25k (Apex/Tradovate)",
    "INITIAL_CAPITAL": 25_000.0,
    "CRITICAL_FLOOR": 24_000.0,
    "MAX_TRAILING_DRAWDOWN": 1_000.0,
    "SYMBOL": "MNQ",
    "CONTRACTS": 2,
    "STOP_LOSS_PTS": 20.0,        # 20 pts = $40 USD por contrato ($80 total)
    "TARGET_1_PTS": 20.0,         # Scalp: Cobra a +20p ($40 USD) y pasa C2 a Break-Even
    "TARGET_2_PTS": 40.0,         # Runner: Busca expansión de +40p ($80 USD)
    "TIME_STOP_BARS": 6,          # 6 velas de 15m = 90 minutos max holding
    "HMM_PROB_THRESHOLD": 0.55,
}

# Multiplicador de S&P 500 E-mini usado en relaciones inter-mercado StatArb
ES_POINT_VALUE = 50.0


# --------------------------------------------------------------------------- #
# Simbología del universo en MetaTrader 5 (símbolo estático obligatorio US100-DEC26)
# --------------------------------------------------------------------------- #
SYMBOLS = {
    "NQ": "US100-DEC26",
    "MNQ": "US100-DEC26",
    "ES": "US100-DEC26",
    "SPY": "US100-DEC26",
    "QQQ": "US100-DEC26",
    "SMH": "US100-DEC26",
    "NDX": "US100-DEC26",
    "VXN": "US100-DEC26",
    "VIX": "US100-DEC26",
    "VIX9D": "US100-DEC26",
    "VIX3M": "US100-DEC26",
    "TNX": "US100-DEC26",
    "IRX": "US100-DEC26",
}

# Configuración estática estricta del símbolo de datos en MT5
MT5_SYMBOL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "NQ": ("US100-DEC26",),
    "MNQ": ("US100-DEC26",),
    "NDX": ("US100-DEC26",),
}

# Valores de referencia para el generador sintético de respaldo (si MT5 está cerrado y sin caché)
SYNTH_ANCHORS = {
    "NQ": 29_183.4, "MNQ": 29_183.4, "ES": 7_658.4, "SPY": 764.0, "QQQ": 710.0,
    "SMH": 398.0, "NDX": 29_183.4, "VXN": 22.0, "VIX": 17.5, "VIX9D": 16.5,
    "VIX3M": 19.2, "TNX": 4.10, "IRX": 3.90,
}


# --------------------------------------------------------------------------- #
# Parámetros de mercado / modelos matemáticos
# --------------------------------------------------------------------------- #
@dataclass
class ModelConfig:
    n_periods_15m: int = 32            # 32 bloques x 15m = 8 horas operativas
    n_sims: int = 10_000               # Trayectorias Monte Carlo
    lookback_days_15m: int = 59        # Ventana histórica para 15m
    lookback_days_5m: int = 20         # Ventana histórica para 5m
    risk_free_fallback: float = 0.040  # Tasa libre de riesgo anualizada
    ndx_div_yield: float = 0.0070      # Rendimiento por dividendo implícito del NDX
    iv_fallback: float = 0.22          # Volatilidad implícita base
    hurst_reversion: float = 0.48
    hurst_momentum: float = 0.52
    seed: int = 20_251_017


MODEL = ModelConfig()


# --------------------------------------------------------------------------- #
# Ventanas operativas (hora de Nueva York)
# --------------------------------------------------------------------------- #
SESSION_WINDOWS = {
    "APERTURA_NY": ("09:30", "11:45"),
    "CIERRE_NY": ("15:00", "16:00"),
}
RTH = ("09:30", "16:00")
GLOBEX_BREAK = ("17:00", "18:00")   # mantenimiento diario CME


# --------------------------------------------------------------------------- #
# Tema visual institucional
# --------------------------------------------------------------------------- #
THEME = {
    "bg": "#0f172a",
    "panel": "#1e293b",
    "grid": "#334155",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "blue": "#38bdf8",
    "green": "#10b981",
    "red": "#ef4444",
    "amber": "#f59e0b",
    "violet": "#818cf8",
    "indigo": "#6366f1",
    "yellow": "#facc15",
    "pink": "#f43f5e",
}
