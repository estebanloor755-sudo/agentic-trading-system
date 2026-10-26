export interface FunnelKpi {
  id: string;
  labelTag: string;
  labelEs: string;
  count: number;
  formatted: string;
  conversionPct: number;
  barColor: "cyan" | "green" | "mustard";
  subtext: string;
}

export interface QuantStrategyItem {
  id: string;
  name: string;
  family: string;
  instrument: string;
  timeframe: string;
  status: "EN VIVO" | "APROBADA" | "FILTRO" | "DESCARTADA";
  sharpeIS: number;
  sharpeOOS: number;
  profitFactor: number;
  winRate: number;
  maxDrawdown: number;
  totalTrades: number;
  netPnl: number;
  oosRetention: number;
  sparkline: number[];
  curveColor: string;
  authorAgent: string;
  sourceOrigin: "ArXiv" | "GitHub" | "YouTube" | "Propietario";
}

export interface SpaghettiCurve {
  id: string;
  name: string;
  status: "PRIMARY" | "LIVE" | "APPROVED" | "SURVIVOR" | "DECAYED";
  points: number[]; // 260 trades: 0..179 In-Sample, 180..259 Out-Of-Sample
  finalPnl: number;
  sharpeIS: number;
  sharpeOOS: number;
}

export type SubAgentId =
  | "KRONOS"
  | "ORION"
  | "HERMES"
  | "ATHENA"
  | "CORTEX"
  | "SENTINEL"
  | "FINBERT";

export interface SubAgentSpec {
  id: SubAgentId;
  roleTitle: string;
  shortTag: string;
  specialty: string;
  accentColor: string;
  badgeClass: string;
}

export const SUB_AGENT_SPECS: Record<SubAgentId, SubAgentSpec> = {
  KRONOS: {
    id: "KRONOS",
    roleTitle: "Agente Técnico",
    shortTag: "PA / Orderflow / FVG",
    specialty:
      "Analiza Price Action, Orderflow, Liquidity Sweeps, FVGs y patrones geométricos.",
    accentColor: "#4ade80",
    badgeClass: "border-[#4ade80]/40 bg-[#4ade80]/10 text-[#4ade80]"
  },
  ORION: {
    id: "ORION",
    roleTitle: "Agente Cuantitativo",
    shortTag: "Riesgo / Sharpe / OOS",
    specialty:
      "Analiza métricas de riesgo (Sharpe, Sortino, Monte Carlo, Degradación Out-of-Sample, Expectancy).",
    accentColor: "#22d3ee",
    badgeClass: "border-[#22d3ee]/40 bg-[#22d3ee]/10 text-[#22d3ee]"
  },
  HERMES: {
    id: "HERMES",
    roleTitle: "Agente Investigador NLP",
    shortTag: "ArXiv / NER / FinBERT",
    specialty:
      "Extrae contexto macroeconómico, lee papers de ArXiv y procesa sentimiento institucional (FinBERT).",
    accentColor: "#eab308",
    badgeClass: "border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]"
  },
  ATHENA: {
    id: "ATHENA",
    roleTitle: "Agente Macro y de Sentimiento",
    shortTag: "FOMC / CPI / Bloomberg",
    specialty:
      "Lee transcripciones del FOMC, calendario económico (CPI, NFP), Fed Speakers (Nick Timiraos) y titulares de Bloomberg.",
    accentColor: "#d946ef",
    badgeClass:
      "border-[#a855f7]/60 bg-[#a855f7]/15 text-[#d946ef] shadow-[0_0_10px_rgba(168,85,247,0.2)]"
  },
  CORTEX: {
    id: "CORTEX",
    roleTitle: "Agente Codificador",
    shortTag: "AST / Python Vectorizado",
    specialty:
      "Transforma la lógica en código Python vectorizado para el backtest.",
    accentColor: "#38bdf8",
    badgeClass: "border-sky-400/40 bg-sky-500/10 text-sky-300"
  },
  SENTINEL: {
    id: "SENTINEL",
    roleTitle: "Auditor Human-in-the-Loop",
    shortTag: "Validación Humana",
    specialty:
      "Supervisa aprobaciones manuales y bloquea sobreajuste en tiempo real.",
    accentColor: "#4ade80",
    badgeClass: "border-[#4ade80]/40 bg-[#4ade80]/15 text-[#4ade80]"
  },
  FINBERT: {
    id: "FINBERT",
    roleTitle: "Agente Investigador NLP (HERMES)",
    shortTag: "FinBERT / Macro",
    specialty:
      "Sub-módulo de HERMES para inferencia de sentimiento institucional.",
    accentColor: "#eab308",
    badgeClass: "border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]"
  }
};

export interface AgentLogEntry {
  id: string;
  time: string;
  agent: SubAgentId;
  message: string;
  level: "green" | "cyan" | "mustard" | "purple" | "muted";
}

export const FUNNEL_KPIS: FunnelKpi[] = [
  {
    id: "leidos",
    labelTag: "INGESTA DE FUENTES",
    labelEs: "Leídos (Fuentes)",
    count: 1308,
    formatted: "1,308",
    conversionPct: 100,
    barColor: "cyan",
    subtext: "ArXiv • GitHub • YouTube • SSRN"
  },
  {
    id: "testeados",
    labelTag: "MOTOR BACKTEST",
    labelEs: "Testeados (En Backtest)",
    count: 1251,
    formatted: "1,251",
    conversionPct: 95.6,
    barColor: "cyan",
    subtext: "95.6% compilados en motor vectorizado"
  },
  {
    id: "filtro",
    labelTag: "SUPERVIVIENTES IS",
    labelEs: "Por el Filtro (Supervivientes)",
    count: 343,
    formatted: "343",
    conversionPct: 26.2,
    barColor: "cyan",
    subtext: "Sharpe > 1.6 • DD < 4.5% • N > 150"
  },
  {
    id: "aprobados",
    labelTag: "PAPER TRADING",
    labelEs: "Aprobados (Paper Trading)",
    count: 12,
    formatted: "12",
    conversionPct: 8.5,
    barColor: "mustard",
    subtext: "OOS Walk-Forward + Monte Carlo P95"
  },
  {
    id: "live",
    labelTag: "EJECUCIÓN REAL",
    labelEs: "En Vivo (En el Mercado)",
    count: 3,
    formatted: "3",
    conversionPct: 4.2,
    barColor: "green",
    subtext: "Ejecución DMA Activa • CME Globex"
  }
];

export const STRATEGIES_LIST: QuantStrategyItem[] = [
  {
    id: "STR-001",
    name: "Seguidor-Tendencia ES",
    family: "Momentum / Ruptura",
    instrument: "ES (S&P 500)",
    timeframe: "5m",
    status: "EN VIVO",
    sharpeIS: 2.84,
    sharpeOOS: 2.52,
    profitFactor: 2.48,
    winRate: 64.2,
    maxDrawdown: -1.85,
    totalTrades: 412,
    netPnl: 38420,
    oosRetention: 88.7,
    sparkline: [10, 14, 13, 18, 22, 21, 27, 33, 31, 39, 45, 44, 52, 58, 63, 69],
    curveColor: "#4ade80",
    authorAgent: "ORION-v4",
    sourceOrigin: "ArXiv"
  },
  {
    id: "STR-002",
    name: "Reversión-Media NQ",
    family: "Arbitraje Estadístico",
    instrument: "NQ (Nasdaq 100)",
    timeframe: "1m",
    status: "EN VIVO",
    sharpeIS: 3.12,
    sharpeOOS: 2.68,
    profitFactor: 2.71,
    winRate: 71.8,
    maxDrawdown: -1.42,
    totalTrades: 628,
    netPnl: 44910,
    oosRetention: 85.9,
    sparkline: [12, 15, 19, 18, 24, 29, 28, 34, 41, 40, 47, 53, 59, 62, 68, 75],
    curveColor: "#22d3ee",
    authorAgent: "KRONOS-ML",
    sourceOrigin: "GitHub"
  },
  {
    id: "STR-003",
    name: "Barrido-Liquidez GC",
    family: "Microestructura / ICT",
    instrument: "GC (Futuros Oro)",
    timeframe: "15m",
    status: "EN VIVO",
    sharpeIS: 2.65,
    sharpeOOS: 2.31,
    profitFactor: 2.29,
    winRate: 61.5,
    maxDrawdown: -2.10,
    totalTrades: 289,
    netPnl: 29150,
    oosRetention: 87.1,
    sparkline: [8, 11, 10, 15, 19, 23, 21, 26, 30, 35, 34, 40, 44, 49, 53, 59],
    curveColor: "#4ade80",
    authorAgent: "CORTEX-NLP",
    sourceOrigin: "YouTube"
  },
  {
    id: "STR-004",
    name: "Ancla-VWAP NQ",
    family: "Reversión a la Media",
    instrument: "NQ (Nasdaq 100)",
    timeframe: "3m",
    status: "APROBADA",
    sharpeIS: 2.49,
    sharpeOOS: 2.08,
    profitFactor: 2.14,
    winRate: 66.0,
    maxDrawdown: -2.44,
    totalTrades: 354,
    netPnl: 24680,
    oosRetention: 83.5,
    sparkline: [10, 12, 15, 14, 18, 20, 25, 24, 28, 31, 35, 33, 38, 42, 45, 50],
    curveColor: "#22d3ee",
    authorAgent: "ORION-v4",
    sourceOrigin: "GitHub"
  },
  {
    id: "STR-005",
    name: "Rango-Apertura ES",
    family: "Ruptura de Volatilidad",
    instrument: "ES (S&P 500)",
    timeframe: "5m",
    status: "APROBADA",
    sharpeIS: 2.38,
    sharpeOOS: 1.94,
    profitFactor: 1.98,
    winRate: 58.4,
    maxDrawdown: -2.75,
    totalTrades: 240,
    netPnl: 19840,
    oosRetention: 81.5,
    sparkline: [9, 13, 12, 16, 15, 20, 22, 26, 25, 29, 32, 36, 35, 39, 43, 46],
    curveColor: "#22d3ee",
    authorAgent: "KRONOS-ML",
    sourceOrigin: "ArXiv"
  },
  {
    id: "STR-006",
    name: "Ruptura-Orderblock BTC",
    family: "Desbalance de Órdenes",
    instrument: "BTC (Futuros CME)",
    timeframe: "15m",
    status: "APROBADA",
    sharpeIS: 2.72,
    sharpeOOS: 2.15,
    profitFactor: 2.22,
    winRate: 59.2,
    maxDrawdown: -3.12,
    totalTrades: 198,
    netPnl: 27300,
    oosRetention: 79.0,
    sparkline: [7, 10, 14, 12, 17, 22, 20, 25, 31, 29, 34, 38, 41, 40, 46, 51],
    curveColor: "#eab308",
    authorAgent: "SENTINEL",
    sourceOrigin: "YouTube"
  },
  {
    id: "STR-007",
    name: "Retesteo-FVG NQ",
    family: "Fair Value Gap",
    instrument: "NQ (Nasdaq 100)",
    timeframe: "2m",
    status: "APROBADA",
    sharpeIS: 2.55,
    sharpeOOS: 2.02,
    profitFactor: 2.09,
    winRate: 63.1,
    maxDrawdown: -2.58,
    totalTrades: 476,
    netPnl: 22190,
    oosRetention: 79.2,
    sparkline: [11, 13, 12, 16, 19, 18, 22, 24, 27, 26, 30, 33, 37, 36, 41, 44],
    curveColor: "#22d3ee",
    authorAgent: "CORTEX-NLP",
    sourceOrigin: "YouTube"
  },
  {
    id: "STR-008",
    name: "Scalp-Gamma SPX",
    family: "Gamma Dealer / Vol",
    instrument: "ES (S&P 500)",
    timeframe: "1m",
    status: "FILTRO",
    sharpeIS: 2.41,
    sharpeOOS: 1.62,
    profitFactor: 1.76,
    winRate: 67.4,
    maxDrawdown: -3.40,
    totalTrades: 510,
    netPnl: 15420,
    oosRetention: 67.2,
    sparkline: [10, 14, 17, 16, 20, 24, 27, 29, 28, 30, 29, 31, 33, 32, 35, 36],
    curveColor: "#64748b",
    authorAgent: "KRONOS-ML",
    sourceOrigin: "ArXiv"
  },
  {
    id: "STR-009",
    name: "Compresión-Volatilidad CL",
    family: "Bollinger / Keltner",
    instrument: "CL (Petróleo Crudo)",
    timeframe: "30m",
    status: "FILTRO",
    sharpeIS: 2.19,
    sharpeOOS: 1.48,
    profitFactor: 1.69,
    winRate: 54.8,
    maxDrawdown: -3.85,
    totalTrades: 184,
    netPnl: 12890,
    oosRetention: 67.5,
    sparkline: [8, 10, 13, 15, 18, 21, 23, 25, 24, 26, 25, 27, 26, 28, 30, 31],
    curveColor: "#64748b",
    authorAgent: "ORION-v4",
    sourceOrigin: "GitHub"
  },
  {
    id: "STR-010",
    name: "Deriva-Macro ZN",
    family: "Filtro Régimen FinBERT",
    instrument: "ZN (Bono 10Y EE.UU.)",
    timeframe: "1h",
    status: "FILTRO",
    sharpeIS: 2.08,
    sharpeOOS: 1.39,
    profitFactor: 1.61,
    winRate: 57.0,
    maxDrawdown: -3.60,
    totalTrades: 162,
    netPnl: 10450,
    oosRetention: 66.8,
    sparkline: [9, 11, 13, 12, 15, 17, 19, 21, 20, 22, 23, 22, 24, 25, 26, 27],
    curveColor: "#64748b",
    authorAgent: "FINBERT",
    sourceOrigin: "ArXiv"
  },
  {
    id: "STR-011",
    name: "Delta-Neutral ETH",
    family: "Arbitraje de Base / Carry",
    instrument: "ETH (Futuros CME)",
    timeframe: "15m",
    status: "FILTRO",
    sharpeIS: 2.31,
    sharpeOOS: 1.18,
    profitFactor: 1.44,
    winRate: 52.3,
    maxDrawdown: -4.15,
    totalTrades: 275,
    netPnl: 8120,
    oosRetention: 51.0,
    sparkline: [10, 13, 16, 19, 22, 25, 27, 26, 24, 25, 23, 22, 24, 23, 22, 23],
    curveColor: "#64748b",
    authorAgent: "SENTINEL",
    sourceOrigin: "GitHub"
  },
  {
    id: "STR-012",
    name: "Ruptura-Keltner DAX",
    family: "Momentum de Sesión",
    instrument: "FDAX (Eurex)",
    timeframe: "5m",
    status: "DESCARTADA",
    sharpeIS: 2.45,
    sharpeOOS: 0.42,
    profitFactor: 1.12,
    winRate: 46.1,
    maxDrawdown: -6.20,
    totalTrades: 310,
    netPnl: 1920,
    oosRetention: 17.1,
    sparkline: [10, 14, 18, 22, 26, 29, 31, 28, 24, 21, 18, 16, 15, 13, 12, 11],
    curveColor: "#ef4444",
    authorAgent: "ORION-v4",
    sourceOrigin: "YouTube"
  }
];

function seededNoise(seed: number): number {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

export function generateSpaghettiDataset(totalSteps = 260, splitIndex = 180): SpaghettiCurve[] {
  const curves: SpaghettiCurve[] = [];

  for (let c = 0; c < 28; c++) {
    const points: number[] = [0];
    let status: SpaghettiCurve["status"] = "SURVIVOR";

    if (c === 0) status = "PRIMARY";
    else if (c <= 2) status = "LIVE";
    else if (c <= 9) status = "APPROVED";
    else if (c <= 19) status = "SURVIVOR";
    else status = "DECAYED";

    const isSlope =
      status === "PRIMARY"
        ? 155
        : status === "LIVE"
        ? 140 - c * 4
        : status === "APPROVED"
        ? 118 - (c - 3) * 3.5
        : status === "SURVIVOR"
        ? 95 - (c - 10) * 2.2
        : 105 - (c - 20) * 3.0;

    const oosSlope =
      status === "PRIMARY"
        ? 195
        : status === "LIVE"
        ? 165 - c * 8
        : status === "APPROVED"
        ? 110 - (c - 3) * 9
        : status === "SURVIVOR"
        ? 28 - (c - 10) * 6.5
        : -95 - (c - 20) * 18;

    let current = 0;
    for (let t = 1; t < totalSteps; t++) {
      const n1 = seededNoise(c * 1000 + t * 17) - 0.48;
      const n2 = Math.sin(t * 0.19 + c * 0.7) * 140;

      if (t <= splitIndex) {
        const stepDelta = isSlope + n1 * 420 + n2 * 0.45;
        current += stepDelta;
      } else {
        const oosProgress = (t - splitIndex) / (totalSteps - splitIndex);
        const dispersionMultiplier = 1 + oosProgress * 1.45;
        const stepDelta = oosSlope * dispersionMultiplier + n1 * 640 * dispersionMultiplier + n2 * 0.8;
        current += stepDelta;
      }

      points.push(Math.round(current));
    }

    const finalPnl = points[points.length - 1];
    const sharpeIS = Number((2.1 + (28 - c) * 0.04).toFixed(2));
    const sharpeOOS =
      status === "DECAYED"
        ? Number((-0.4 + (28 - c) * 0.09).toFixed(2))
        : Number((sharpeIS * (status === "PRIMARY" || status === "LIVE" ? 0.88 : 0.72)).toFixed(2));

    curves.push({
      id: `CRV-${String(c + 1).padStart(2, "0")}`,
      name: STRATEGIES_LIST[c % STRATEGIES_LIST.length].name + (c >= STRATEGIES_LIST.length ? ` #v${c}` : ""),
      status,
      points,
      finalPnl,
      sharpeIS,
      sharpeOOS
    });
  }

  return curves;
}

export const INITIAL_AGENT_LOGS: AgentLogEntry[] = [
  {
    id: "log-1",
    time: "17:54:12.04",
    agent: "ATHENA",
    message:
      "ATHENA: Tono 'Hawkish' detectado en actas del FOMC. Bloqueando estrategias de Mean Reversion para NQ.",
    level: "purple"
  },
  {
    id: "log-2",
    time: "17:54:14.89",
    agent: "KRONOS",
    message:
      "[Price Action & Orderflow] Detectado Liquidity Sweep en mínimo de Londres + Fair Value Gap (FVG) alcista en NQ 5m",
    level: "green"
  },
  {
    id: "log-3",
    time: "17:54:16.45",
    agent: "ATHENA",
    message:
      "ATHENA: Rumor de shock geopolítico en Medio Oriente. Aumentando ponderación en setups de liquidez de XAU/USD.",
    level: "purple"
  },
  {
    id: "log-4",
    time: "17:54:18.31",
    agent: "HERMES",
    message:
      "[NLP & ArXiv] Paper '2610.09412v1' procesado -> Entidades NER extraídas: 'VWAP', 'order block', 'fair value gap' (FinBERT +0.84)",
    level: "mustard"
  },
  {
    id: "log-5",
    time: "17:54:20.12",
    agent: "CORTEX",
    message:
      "[Codificador AST] Hipótesis transformada en script Python vectorizado NumPy (0 bucles for) -> compilado en 14ms",
    level: "cyan"
  },
  {
    id: "log-6",
    time: "17:54:21.77",
    agent: "ORION",
    message:
      "[Riesgo & OOS] Auditoría cuantitativa completada: Sharpe IS 2.84 | Sortino 3.41 | Retención OOS 88.7% | Expectancy +$142/trade",
    level: "cyan"
  },
  {
    id: "log-7",
    time: "17:54:25.10",
    agent: "ATHENA",
    message:
      "ATHENA: Divergencia cualitativa. Precio subiendo, pero sentimiento de flujo institucional negativo (-0.65). Precaución.",
    level: "purple"
  }
];
