"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Cpu,
  Flame,
  Gauge,
  Grid,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Zap
} from "lucide-react";

type AgentRuntimeState = "IDLE" | "INFERENCIA" | "RATE_LIMIT";

interface FleetAgentTelemetryCard {
  id: "KRONOS" | "ORION" | "HERMES" | "ATHENA" | "CORTEX";
  nameRole: string;
  modelEngine: string;
  accentColor: string;
  baseState: AgentRuntimeState;
  tasks: string[];
  latencyMs: number;
  contextLoadPct: number;
  gpuLoadPct: number;
  tokensPerMin: string;
  apiCostPerHour: string;
}

const FLEET_AGENTS_CONFIG: FleetAgentTelemetryCard[] = [
  {
    id: "KRONOS",
    nameRole: "KRONOS (Técnico)",
    modelEngine: "ViT-Orderflow-L2 v4",
    accentColor: "#4ade80",
    baseState: "INFERENCIA",
    tasks: [
      "Escaneando NQ 5m (L2 ZeroMQ :5556)...",
      "Detectando FVG + Liquidity Sweep NY...",
      "Validando ruptura CHoCH vela #18..."
    ],
    latencyMs: 11,
    contextLoadPct: 68,
    gpuLoadPct: 82,
    tokensPerMin: "42.8k tok/m",
    apiCostPerHour: "$0.18/h"
  },
  {
    id: "ORION",
    nameRole: "ORION (Cuantitativo)",
    modelEngine: "Numba-Vector-MC1000",
    accentColor: "#22d3ee",
    baseState: "INFERENCIA",
    tasks: [
      "Ejecutando enjambre SL/TP (100 variantes)...",
      "Calculando retención Sharpe IS/OOS...",
      "Filtrando Max Drawdown < 4.50%..."
    ],
    latencyMs: 19,
    contextLoadPct: 84,
    gpuLoadPct: 91,
    tokensPerMin: "64.1k tok/m",
    apiCostPerHour: "$0.29/h"
  },
  {
    id: "HERMES",
    nameRole: "HERMES (NLP)",
    modelEngine: "FinBERT-ArXiv-NER",
    accentColor: "#eab308",
    baseState: "INFERENCIA",
    tasks: [
      "Extrayendo NER en arXiv:2610.09412...",
      "Tokenizando 'VWAP' y 'order block'...",
      "Indexando 12 preprints SSRN..."
    ],
    latencyMs: 38,
    contextLoadPct: 54,
    gpuLoadPct: 49,
    tokensPerMin: "28.4k tok/m",
    apiCostPerHour: "$0.14/h"
  },
  {
    id: "ATHENA",
    nameRole: "ATHENA (Cualitativo)",
    modelEngine: "Macro-LLM-FOMC-Pro",
    accentColor: "#d946ef",
    baseState: "RATE_LIMIT",
    tasks: [
      "Analizando actas FOMC (Tono Hawkish)...",
      "Monitoreando feed Bloomberg / CPI...",
      "Evaluando shock geopolítico XAU/USD..."
    ],
    latencyMs: 142,
    contextLoadPct: 93,
    gpuLoadPct: 76,
    tokensPerMin: "89.5k tok/m",
    apiCostPerHour: "$0.64/h"
  },
  {
    id: "CORTEX",
    nameRole: "CORTEX (Codificador)",
    modelEngine: "AST-CodeGen-Quant",
    accentColor: "#38bdf8",
    baseState: "IDLE",
    tasks: [
      "Esperando nuevo bloque NER de HERMES...",
      "AST verificado: 0 Lookahead Bias...",
      "Plantilla kronos_choch.py en caché..."
    ],
    latencyMs: 14,
    contextLoadPct: 31,
    gpuLoadPct: 22,
    tokensPerMin: "12.0k tok/m",
    apiCostPerHour: "$0.07/h"
  }
];

interface RegimePreset {
  id: string;
  label: string;
  quadrantTitle: string;
  xTrend: number; // -100 (Bajista) a +100 (Alcista)
  yVolatility: number; // -100 (Baja Vol) a +100 (Alta Vol)
  vixLevel: number;
  zeusRule: string;
}

const REGIME_PRESETS: RegimePreset[] = [
  {
    id: "REGIME_4_SHOCK",
    label: "Régimen 4: Alta Vol / Shock",
    quadrantTitle: "ALTA VOLATILIDAD / PRESIÓN MACRO",
    xTrend: -48,
    yVolatility: 68,
    vixLevel: 27.4,
    zeusRule: 'Régimen 4: Bloqueando estrategias Mean-Reversion. VIX > 25'
  },
  {
    id: "DIRECTIONAL_RUNNER",
    label: "Régimen 1: Tendencia Alcista",
    quadrantTitle: "ALTA VOLATILIDAD / TENDENCIA ALCISTA",
    xTrend: 64,
    yVolatility: 56,
    vixLevel: 21.8,
    zeusRule:
      "Régimen 1: Autorizando bots Trend-Following (ES/NQ) y piramidación controlada."
  },
  {
    id: "MEAN_REVERSION_CLAMP",
    label: "Régimen 2: Compresión VWAP",
    quadrantTitle: "BAJA VOLATILIDAD / RANGO INSTITUCIONAL",
    xTrend: 28,
    yVolatility: -52,
    vixLevel: 14.2,
    zeusRule:
      "Régimen 2: Priorizando estrategias de Reversión a VWAP y absorción en Order Blocks."
  },
  {
    id: "BEAR_DRIFT",
    label: "Régimen 3: Deriva Bajista",
    quadrantTitle: "BAJA VOLATILIDAD / DISTRIBUCIÓN",
    xTrend: -55,
    yVolatility: -38,
    vixLevel: 18.6,
    zeusRule:
      "Régimen 3: Reduciendo exposición larga un 50%; habilitando barridos de liquidez en cortos."
  }
];

interface SwarmCell {
  index: number;
  row: number;
  col: number;
  slTicks: number;
  tpTicks: number;
  outcome: "SUCCESS" | "FAILED";
  sharpe: number;
  maxDrawdownPct: number;
  netProfit: number;
}

function buildSwarm100Grid(): SwarmCell[] {
  const slValues = [10, 14, 18, 22, 26, 30, 35, 40, 45, 50];
  const tpValues = [20, 28, 36, 44, 52, 60, 70, 80, 90, 100];
  const cells: SwarmCell[] = [];

  for (let r = 0; r < 10; r++) {
    for (let c = 0; c < 10; c++) {
      const idx = r * 10 + c;
      const sl = slValues[r];
      const tp = tpValues[c];

      // Isla de estabilidad cuantitativa (Cluster verde vibrante cuando SL 22..40 y TP 52..90)
      const inSweetSpot =
        r >= 3 && r <= 7 && c >= 4 && c <= 8 && (r + c) % 4 !== 0;
      const secondaryPocket = r === 2 && (c === 5 || c === 6);
      const isSuccess = inSweetSpot || secondaryPocket;

      const sharpe = isSuccess
        ? Number((1.58 + ((r * 3 + c * 5) % 14) * 0.09).toFixed(2))
        : Number((0.42 + ((r * 7 + c * 2) % 9) * 0.11).toFixed(2));

      const maxDrawdownPct = isSuccess
        ? Number((1.65 + ((r + c) % 5) * 0.48).toFixed(2))
        : Number((4.85 + ((r * 2 + c) % 7) * 0.62).toFixed(2));

      const netProfit = isSuccess
        ? 14200 + (idx * 310) % 18500
        : -4200 + (idx * 190) % 3800;

      cells.push({
        index: idx,
        row: r,
        col: c,
        slTicks: sl,
        tpTicks: tp,
        outcome: isSuccess ? "SUCCESS" : "FAILED",
        sharpe,
        maxDrawdownPct,
        netProfit
      });
    }
  }
  return cells;
}

export interface ViewFSystemStatusProps {
  hmmRegime?: string;
  finbertScore?: number;
}

export function ViewFSystemStatus({
  hmmRegime = "DIRECTIONAL_RUNNER"
}: ViewFSystemStatusProps) {
  const [tickStep, setTickStep] = useState<number>(0);
  const [selectedRegimeId, setSelectedRegimeId] = useState<string>("REGIME_4_SHOCK");
  const [completedVariants, setCompletedVariants] = useState<number>(64);
  const [swarmRunning, setSwarmRunning] = useState<boolean>(true);
  const [hoveredCell, setHoveredCell] = useState<SwarmCell | null>(null);

  const swarmCells = useMemo(() => buildSwarm100Grid(), []);

  // Rotación de micro-telemetría de las 5 tarjetas de sub-agentes
  useEffect(() => {
    const id = setInterval(() => {
      setTickStep((prev) => prev + 1);
    }, 1800);
    return () => clearInterval(id);
  }, []);

  // Avance progresivo del enjambre de 100 variantes (CORTEX & ORION)
  useEffect(() => {
    if (!swarmRunning) return;
    const id = setInterval(() => {
      setCompletedVariants((prev) => {
        if (prev >= 100) {
          return 64; // Reinicia el ciclo en 64/100 para mantener vivo el barrido en tiempo real
        }
        return prev + 1;
      });
    }, 650);
    return () => clearInterval(id);
  }, [swarmRunning]);

  const activeRegime =
    REGIME_PRESETS.find((r) => r.id === selectedRegimeId) ?? REGIME_PRESETS[0];

  // Jitter suave del punto luminoso de ZEUS dentro del cuadrante
  const jitterX = ((tickStep % 3) - 1) * 2.5;
  const jitterY = (((tickStep + 1) % 3) - 1) * 2.5;
  const dotLeftPct = Math.max(8, Math.min(92, 50 + (activeRegime.xTrend + jitterX) * 0.42));
  const dotTopPct = Math.max(8, Math.min(92, 50 - (activeRegime.yVolatility + jitterY) * 0.42));

  const inspectedCell = hoveredCell ?? swarmCells[Math.min(99, completedVariants - 1)];
  const passedVariantsCount = swarmCells
    .slice(0, completedVariants)
    .filter((c) => c.outcome === "SUCCESS").length;
  const failedVariantsCount = completedVariants - passedVariantsCount;

  function renderStatusBadge(state: AgentRuntimeState) {
    if (state === "INFERENCIA") {
      return (
        <span className="flex items-center gap-1 rounded border border-[#22d3ee]/40 bg-[#22d3ee]/15 px-1.5 py-0.5 font-mono text-[8.5px] font-bold text-[#22d3ee]">
          <span>⚡ INFERENCIA</span>
        </span>
      );
    }
    if (state === "RATE_LIMIT") {
      return (
        <span className="flex items-center gap-1 rounded border border-rose-500/50 bg-rose-500/15 px-1.5 py-0.5 font-mono text-[8.5px] font-bold text-rose-400">
          <span>🔴 RATE LIMIT</span>
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1 rounded border border-[#4ade80]/40 bg-[#4ade80]/15 px-1.5 py-0.5 font-mono text-[8.5px] font-bold text-[#4ade80]">
        <span>🟢 IDLE</span>
      </span>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col justify-between gap-2.5 overflow-hidden">
      {/* =====================================================================
          1. PANEL SUPERIOR: AGENT FLEET TELEMETRY (SUPERVISIÓN DE ZEUS - 5 TARJETAS)
      ====================================================================== */}
      <section
        aria-label="Telemetría de la Flota de Sub-Agentes bajo supervisión de ZEUS"
        className="shrink-0 rounded-lg border border-[#1f222d] bg-[#0a0b10] p-2.5"
      >
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-1.5">
          <div className="flex items-center gap-2">
            <Cpu className="h-3.5 w-3.5 text-[#fbbf24]" />
            <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
              TELEMETRÍA DE LA FLOTA DE AGENTES — SUPERVISIÓN DE ZEUS (SYSTEEMSTATUS)
            </h2>
            <span className="rounded border border-[#fbbf24]/40 bg-[#fbbf24]/15 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#fbbf24]">
              ORQUESTADOR: ZEUS ACTIVO
            </span>
          </div>

          <div className="flex items-center gap-3 font-mono text-[10px] text-slate-400">
            <span>
              Throughput Total: <strong className="text-[#22d3ee]">236.8k tok/min</strong>
            </span>
            <span>•</span>
            <span>
              Costo Flota: <strong className="text-[#4ade80]">$1.32 / hora</strong>
            </span>
          </div>
        </div>

        {/* Grid de 5 tarjetas compactas (Dark Quant, bordes #1f222d) */}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {FLEET_AGENTS_CONFIG.map((ag, idx) => {
            const currentTask = ag.tasks[(tickStep + idx) % ag.tasks.length];
            const dynamicLatency =
              ag.baseState === "RATE_LIMIT"
                ? ag.latencyMs + (tickStep % 3) * 14
                : ag.latencyMs + ((tickStep + idx) % 4);
            const dynamicContext = Math.min(
              98,
              ag.contextLoadPct + (((tickStep + idx) % 3) - 1) * 2
            );

            return (
              <div
                key={ag.id}
                className="flex flex-col justify-between rounded-md border border-[#1f222d] bg-[#050609] p-2.5 transition hover:border-slate-700"
              >
                {/* Fila 1: Nombre/Rol + Estado (🟢 IDLE / ⚡ INFERENCIA / 🔴 RATE LIMIT) */}
                <div className="flex items-center justify-between gap-1">
                  <div className="truncate">
                    <div
                      className="truncate font-mono text-[11px] font-extrabold"
                      style={{ color: ag.accentColor }}
                    >
                      {ag.nameRole}
                    </div>
                    <div className="truncate font-mono text-[8.5px] text-slate-500">
                      {ag.modelEngine}
                    </div>
                  </div>
                  {renderStatusBadge(ag.baseState)}
                </div>

                {/* Fila 2: Tarea Actual truncada en vivo */}
                <div className="my-2 rounded border border-[#1f222d]/80 bg-[#0a0b10] px-2 py-1 font-mono text-[9.5px] text-slate-300">
                  <div className="truncate" title={currentTask}>
                    {currentTask}
                  </div>
                </div>

                {/* Fila 3: Anillo/Barra de carga CPU & Contexto + Latencia/Costo API */}
                <div className="space-y-1.5 font-mono text-[9px]">
                  <div className="flex items-center justify-between text-slate-400">
                    <span>
                      Latencia: <strong className="text-slate-200">{dynamicLatency}ms</strong>
                    </span>
                    <span>
                      {ag.tokensPerMin} •{" "}
                      <strong className="text-[#4ade80]">{ag.apiCostPerHour}</strong>
                    </span>
                  </div>

                  {/* Barra de carga miniatura de Contexto / GPU */}
                  <div className="flex items-center gap-2">
                    <span className="w-12 shrink-0 text-[8px] uppercase text-slate-500">
                      CTX {dynamicContext}%
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#141824]">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${dynamicContext}%`,
                          backgroundColor:
                            ag.baseState === "RATE_LIMIT" ? "#f43f5e" : ag.accentColor
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* =====================================================================
          2. FILA INFERIOR: HMM MARKET REGIME MATRIX (IZQUIERDA) + SWARM VARIANT TUNING (DERECHA)
      ====================================================================== */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2.5 lg:grid-cols-12">
        {/* WIDGET 2: HMM MARKET REGIME MATRIX (CUADRANTE DE MERCADO DE ZEUS - 5 COLS) */}
        <div className="flex min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3 lg:col-span-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
            <div className="flex items-center gap-2">
              <Gauge className="h-3.5 w-3.5 text-[#eab308]" />
              <div>
                <h3 className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-100">
                  MATRIZ DE RÉGIMEN HMM (Cuadrante de Mercado ZEUS)
                </h3>
                <p className="font-mono text-[9px] text-slate-500">
                  Eje X: Tendencia (Bajista ◄ ► Alcista) • Eje Y: Volatilidad (Baja ▼ ▲ Alta)
                </p>
              </div>
            </div>

            <span className="rounded border border-[#eab308]/40 bg-[#eab308]/10 px-2 py-0.5 font-mono text-[9px] font-bold text-[#eab308]">
              VIX: {activeRegime.vixLevel.toFixed(1)}
            </span>
          </div>

          {/* Botones de selección rápida de régimen para probar la reacción de ZEUS */}
          <div className="my-1.5 grid grid-cols-2 gap-1 font-mono text-[8.5px] sm:grid-cols-4">
            {REGIME_PRESETS.map((preset) => {
              const isSelected = preset.id === activeRegime.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setSelectedRegimeId(preset.id)}
                  className={`truncate rounded border px-1.5 py-1 font-bold transition ${
                    isSelected
                      ? "border-[#eab308] bg-[#eab308]/20 text-[#eab308]"
                      : "border-[#1f222d] bg-[#050609] text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          {/* GRÁFICO DE CUADRANTE (4 ZONAS CRUZADAS POR 2 EJES + PUNTO LUMINOSO #eab308) */}
          <div className="relative my-1 min-h-[165px] flex-1 overflow-hidden rounded-md border border-[#1f222d] bg-[#050608]">
            {/* Cuadrícula de las 4 zonas */}
            <div className="grid h-full w-full grid-cols-2 grid-rows-2">
              {/* Q2: Alta Volatilidad + Tendencia Bajista */}
              <div
                onClick={() => setSelectedRegimeId("REGIME_4_SHOCK")}
                className="flex cursor-pointer flex-col justify-between border-b border-r border-[#1f222d] p-2 transition hover:bg-rose-950/15"
              >
                <span className="font-mono text-[8.5px] font-bold uppercase text-rose-400/90">
                  Q4 • ALTA VOL / CAÍDA (SHOCK VIX &gt; 25)
                </span>
                <span className="font-mono text-[8px] text-slate-600">
                  Veto Mean-Reversion
                </span>
              </div>

              {/* Q1: Alta Volatilidad + Tendencia Alcista */}
              <div
                onClick={() => setSelectedRegimeId("DIRECTIONAL_RUNNER")}
                className="flex cursor-pointer flex-col justify-between border-b border-[#1f222d] p-2 text-right transition hover:bg-emerald-950/15"
              >
                <span className="font-mono text-[8.5px] font-bold uppercase text-[#4ade80]">
                  Q1 • ALTA VOL / TENDENCIA ALCISTA
                </span>
                <span className="font-mono text-[8px] text-slate-600">
                  Directional Runner ({hmmRegime})
                </span>
              </div>

              {/* Q3: Baja Volatilidad + Tendencia Bajista */}
              <div
                onClick={() => setSelectedRegimeId("BEAR_DRIFT")}
                className="flex cursor-pointer flex-col justify-end border-r border-[#1f222d] p-2 transition hover:bg-slate-900/40"
              >
                <span className="font-mono text-[8.5px] font-bold uppercase text-slate-400">
                  Q3 • BAJA VOL / DERIVA BAJISTA
                </span>
              </div>

              {/* Q4: Baja Volatilidad + Tendencia Alcista */}
              <div
                onClick={() => setSelectedRegimeId("MEAN_REVERSION_CLAMP")}
                className="flex cursor-pointer flex-col justify-end p-2 text-right transition hover:bg-cyan-950/15"
              >
                <span className="font-mono text-[8.5px] font-bold uppercase text-[#22d3ee]">
                  Q2 • BAJA VOL / COMPRESIÓN VWAP
                </span>
              </div>
            </div>

            {/* Ejes Centrales X e Y */}
            <div className="pointer-events-none absolute inset-x-0 top-1/2 h-[1px] bg-slate-700/70" />
            <div className="pointer-events-none absolute inset-y-0 left-1/2 w-[1px] bg-slate-700/70" />

            {/* Etiquetas de los Ejes */}
            <span className="pointer-events-none absolute left-1/2 top-1 -translate-x-1/2 rounded bg-[#050608]/90 px-1.5 font-mono text-[8px] font-bold text-slate-400">
              ▲ ALTA VOLATILIDAD (Y)
            </span>
            <span className="pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 rounded bg-[#050608]/90 px-1.5 font-mono text-[8px] font-bold text-slate-400">
              ▼ BAJA VOLATILIDAD
            </span>
            <span className="pointer-events-none absolute left-1.5 top-1/2 -translate-y-1/2 rounded bg-[#050608]/90 px-1 font-mono text-[8px] text-slate-500">
              ◄ BAJISTA
            </span>
            <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 rounded bg-[#050608]/90 px-1 font-mono text-[8px] text-slate-500">
              ALCISTA ►
            </span>

            {/* Punto Luminoso (#eab308) de ZEUS */}
            <div
              style={{
                left: `${dotLeftPct}%`,
                top: `${dotTopPct}%`
              }}
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 transition-all duration-700"
            >
              <span className="absolute -inset-3 animate-ping rounded-full bg-[#eab308]/35" />
              <span className="relative flex h-4 w-4 items-center justify-center rounded-full border-2 border-white bg-[#eab308] shadow-[0_0_18px_#eab308]" />
              <div className="mt-1 whitespace-nowrap rounded border border-[#eab308]/60 bg-[#0a0b10]/95 px-1.5 py-0.5 font-mono text-[8px] font-bold text-[#eab308] shadow-lg">
                ZEUS LOCUS ({activeRegime.xTrend > 0 ? `+${activeRegime.xTrend}` : activeRegime.xTrend},{" "}
                {activeRegime.yVolatility > 0 ? `+${activeRegime.yVolatility}` : activeRegime.yVolatility})
              </div>
            </div>
          </div>

          {/* REGLA ACTIVA DE ZEUS */}
          <div className="mt-1.5 flex items-center justify-between gap-2 rounded border border-[#eab308]/40 bg-[#120e04] px-2.5 py-1.5 font-mono text-[10px]">
            <div className="flex min-w-0 items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-[#eab308]" />
              <span className="truncate font-bold text-[#eab308]">
                {activeRegime.zeusRule}
              </span>
            </div>
            <span className="shrink-0 text-[8.5px] uppercase text-amber-200/80">
              Política Activa
            </span>
          </div>
        </div>

        {/* VISUALIZADOR 3: SWARM VARIANT TUNING (MATRIZ DE CORTEX & ORION - 7 COLS) */}
        <div className="flex min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3 lg:col-span-7">
          {/* Header del Heatmap */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
            <div className="flex items-center gap-2">
              <Grid className="h-3.5 w-3.5 text-[#10b981]" />
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-100">
                    ENJAMBRE DE VARIANTES (Swarm Variant Tuning — CORTEX &amp; ORION)
                  </h3>
                  <span className="rounded border border-[#10b981]/40 bg-[#10b981]/10 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#10b981]">
                    MATRIZ 10×10 (100 VARIANTES)
                  </span>
                </div>
                <p className="font-mono text-[9px] text-slate-500">
                  Barrido vectorial de hiperparámetros: Stop Loss (10 a 50 ticks) × Take Profit (20 a 100 ticks)
                </p>
              </div>
            </div>

            {/* OVERLAY CONTADOR RÁPIDO: Optimizando hiperparámetros... 64/100 completados */}
            <div className="flex items-center gap-1.5 font-mono text-[10px]">
              <span className="flex items-center gap-1.5 rounded border border-[#22d3ee]/40 bg-[#22d3ee]/10 px-2.5 py-1 font-bold text-[#22d3ee]">
                <Sparkles className="h-3 w-3 animate-spin" />
                <span>
                  Optimizando hiperparámetros... {completedVariants}/100 completados
                </span>
              </span>

              <button
                type="button"
                onClick={() => setSwarmRunning((prev) => !prev)}
                className="rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-slate-300 hover:text-white"
                title={swarmRunning ? "Congelar barrido en el estado actual" : "Reanudar barrido"}
              >
                {swarmRunning ? <Activity className="h-3 w-3 text-[#4ade80]" /> : <Play className="h-3 w-3" />}
              </button>

              <button
                type="button"
                onClick={() => setCompletedVariants(64)}
                className="rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-slate-300 hover:text-white"
                title="Restaurar contador a 64/100"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            </div>
          </div>

          {/* CUERPO CENTRAL: MATRIZ 10x10 + INSPECTOR DE HIPERPARÁMETROS */}
          <div className="my-2 grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-12">
            {/* Cuadrícula 10x10 */}
            <div className="flex flex-col justify-between rounded border border-[#1f222d] bg-[#050608] p-2.5 xl:col-span-8">
              <div className="mb-1 flex items-center justify-between font-mono text-[8.5px] text-slate-500">
                <span>EJE Y: STOP LOSS (10 → 50 TICKS)</span>
                <span>EJE X: TAKE PROFIT (20 → 100 TICKS)</span>
              </div>

              <div className="grid flex-1 grid-cols-10 gap-1">
                {swarmCells.map((cell) => {
                  const isProcessed = cell.index < completedVariants;
                  const isCurrentlyTesting = cell.index === completedVariants;
                  const isHovered = inspectedCell?.index === cell.index;

                  let cellClass =
                    "bg-slate-700/45 border-slate-600/40 animate-pulse text-slate-400"; // En proceso
                  if (isProcessed) {
                    if (cell.outcome === "SUCCESS") {
                      cellClass =
                        "bg-[#10b981] border-[#34d399] text-black font-extrabold shadow-[0_0_8px_rgba(16,185,129,0.35)]";
                    } else {
                      cellClass = "bg-[#7f1d1d] border-rose-800/70 text-rose-200/80";
                    }
                  } else if (isCurrentlyTesting) {
                    cellClass =
                      "bg-[#22d3ee] border-white text-black font-extrabold animate-ping";
                  }

                  return (
                    <button
                      key={cell.index}
                      type="button"
                      onMouseEnter={() => setHoveredCell(cell)}
                      onClick={() => setHoveredCell(cell)}
                      className={`flex min-h-[18px] items-center justify-center rounded-[3px] border font-mono text-[8px] transition-transform ${cellClass} ${
                        isHovered ? "scale-110 ring-2 ring-white z-10" : ""
                      }`}
                      title={`Variante #${cell.index + 1} | SL: ${cell.slTicks}t | TP: ${cell.tpTicks}t | Sharpe: ${cell.sharpe}`}
                    >
                      {isProcessed ? cell.sharpe.toFixed(1) : "··"}
                    </button>
                  );
                })}
              </div>

              {/* Leyenda de colores de la matriz */}
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 font-mono text-[8.5px] text-slate-400">
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-sm bg-[#10b981]" />
                    Exitosas (Sharpe &gt; 1.5): <strong className="text-[#10b981]">{passedVariantsCount}</strong>
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2.5 w-2.5 rounded-sm bg-[#7f1d1d]" />
                    Fallidas (DD &gt; 4.5%): <strong className="text-rose-400">{failedVariantsCount}</strong>
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2.5 w-2.5 animate-pulse rounded-sm bg-slate-600" />
                    En Proceso: <strong>{100 - completedVariants}</strong>
                  </span>
                </div>
                <span className="text-[#22d3ee]">Pasa el cursor para auditar celda</span>
              </div>
            </div>

            {/* Inspector lateral de la variante seleccionada */}
            <div className="flex flex-col justify-between rounded border border-[#1f222d] bg-[#050608] p-2.5 font-mono xl:col-span-4">
              <div>
                <div className="flex items-center justify-between border-b border-[#1f222d] pb-1.5 text-[9.5px]">
                  <span className="font-bold uppercase text-slate-200">
                    Variante #{inspectedCell.index + 1} / 100
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[8.5px] font-bold ${
                      inspectedCell.outcome === "SUCCESS"
                        ? "bg-[#10b981]/20 text-[#10b981]"
                        : "bg-[#7f1d1d]/60 text-rose-300"
                    }`}
                  >
                    {inspectedCell.outcome === "SUCCESS"
                      ? "✓ APROBADA ORION"
                      : "✕ DESCARTADA DD"}
                  </span>
                </div>

                <div className="mt-2 space-y-1.5 text-[10px]">
                  <div className="flex justify-between rounded bg-[#0a0b10] px-2 py-1">
                    <span className="text-slate-400">Stop Loss (SL):</span>
                    <strong className="text-white">{inspectedCell.slTicks} ticks</strong>
                  </div>
                  <div className="flex justify-between rounded bg-[#0a0b10] px-2 py-1">
                    <span className="text-slate-400">Take Profit (TP):</span>
                    <strong className="text-white">{inspectedCell.tpTicks} ticks</strong>
                  </div>
                  <div className="flex justify-between rounded bg-[#0a0b10] px-2 py-1">
                    <span className="text-slate-400">Ratio R:R Base:</span>
                    <strong className="text-[#22d3ee]">
                      1 : {(inspectedCell.tpTicks / inspectedCell.slTicks).toFixed(2)}
                    </strong>
                  </div>
                  <div className="flex justify-between rounded bg-[#0a0b10] px-2 py-1">
                    <span className="text-slate-400">Sharpe Ratio OOS:</span>
                    <strong
                      className={
                        inspectedCell.sharpe >= 1.5 ? "text-[#10b981]" : "text-rose-400"
                      }
                    >
                      {inspectedCell.sharpe.toFixed(2)}
                    </strong>
                  </div>
                  <div className="flex justify-between rounded bg-[#0a0b10] px-2 py-1">
                    <span className="text-slate-400">Max Drawdown:</span>
                    <strong
                      className={
                        inspectedCell.maxDrawdownPct <= 4.5
                          ? "text-[#4ade80]"
                          : "text-rose-400"
                      }
                    >
                      -{inspectedCell.maxDrawdownPct.toFixed(2)}%
                    </strong>
                  </div>
                </div>
              </div>

              <div className="mt-2 rounded border border-[#1f222d] bg-[#0a0b10] p-2 text-[9px] text-slate-400">
                <div className="flex items-center gap-1 font-bold text-[#22d3ee]">
                  <Flame className="h-3 w-3 text-[#eab308]" />
                  <span>Diagnóstico de Clúster</span>
                </div>
                <p className="mt-0.5 leading-snug">
                  Meseta robusta detectada entre{" "}
                  <strong className="text-white">SL 22–40t</strong> y{" "}
                  <strong className="text-white">TP 52–90t</strong> (bajo riesgo de sobreajuste).
                </p>
              </div>
            </div>
          </div>

          {/* Barra de progreso inferior de las 100 variantes */}
          <div className="flex items-center gap-2 border-t border-[#1f222d] pt-1.5 font-mono text-[9px] text-slate-400">
            <Zap className="h-3 w-3 text-[#10b981]" />
            <span>Progreso del Enjambre Vectorizado:</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#141824]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[#22d3ee] to-[#10b981] transition-all duration-300"
                style={{ width: `${completedVariants}%` }}
              />
            </div>
            <strong className="text-[#10b981]">{completedVariants}%</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
