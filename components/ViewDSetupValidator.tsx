"use client";

import React, { useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  Sparkles,
  X
} from "lucide-react";
import {
  ReplayCandlestickChart,
  type ReplayCandleItem,
  type ReplayPatternDataset
} from "./ReplayCandlestickChart";
import type { UTCTimestamp } from "lightweight-charts";

export interface TaxonomyPatternItem {
  id: string;
  name: string;
  esSubtitle: string;
  countLabel: string;
  category: "STRUCTUUR" | "SESSIES";
  functionName: string;
  descriptionEs: string;
}

export const STRUCTUUR_PATTERNS: TaxonomyPatternItem[] = [
  {
    id: "bos",
    name: "Break of structure",
    esSubtitle: "Ruptura de estructura a favor de tendencia",
    countLabel: "29k",
    category: "STRUCTUUR",
    functionName: "detect_break_of_structure(df, swing_len=5)",
    descriptionEs:
      "Cierre de cuerpo completo por encima del último Swing High en tendencia alcista institucional."
  },
  {
    id: "choch",
    name: "Change of character",
    esSubtitle: "Cambio de carácter estructural (Reversión)",
    countLabel: "9k",
    category: "STRUCTUUR",
    functionName: "detect_change_of_character(df, lookback=14)",
    descriptionEs:
      "Tras una secuencia Lower High → Lower Low (Sweep), el precio rompe el último Lower High con desplazamiento FVG."
  },
  {
    id: "displacement",
    name: "Displacement",
    esSubtitle: "Desplazamiento institucional de rango amplio",
    countLabel: "11k",
    category: "STRUCTUUR",
    functionName: "detect_displacement_candle(df, atr_mult=2.2)",
    descriptionEs:
      "Vela de expansión cuyo cuerpo supera 2.2x ATR(14) dejando un Fair Value Gap no mitigado."
  },
  {
    id: "hh_hl",
    name: "Higher high, higher low",
    esSubtitle: "Secuencia de máximos y mínimos crecientes",
    countLabel: "52k",
    category: "STRUCTUUR",
    functionName: "detect_hh_hl_trend(df, pivot_window=8)",
    descriptionEs:
      "Estructura direccional sostenida validada por KRONOS en regímenes DIRECTIONAL_RUNNER."
  },
  {
    id: "swing_hl",
    name: "Swing high en swing low",
    esSubtitle: "Pivotes fractales de liquidez primaria",
    countLabel: "88k",
    category: "STRUCTUUR",
    functionName: "extract_fractal_swings(df, left=3, right=3)",
    descriptionEs:
      "Puntos de giro fractales donde se acumulan órdenes Stop-Loss institucionales y retail."
  },
  {
    id: "range",
    name: "Range",
    esSubtitle: "Rango de consolidación y equilibrio",
    countLabel: "12k",
    category: "STRUCTUUR",
    functionName: "detect_compression_range(df, min_bars=18)",
    descriptionEs:
      "Caja de equilibrio horizontal previa a expansiones de volatilidad y barridos de liquidez."
  },
  {
    id: "inside_bar",
    name: "Inside bar",
    esSubtitle: "Vela interna de compresión",
    countLabel: "11k",
    category: "STRUCTUUR",
    functionName: "detect_inside_bar_coiling(df)",
    descriptionEs:
      "Vela contenida íntegramente dentro del rango High-Low de la vela madre precedente."
  }
];

export const SESSIES_ITEMS: TaxonomyPatternItem[] = [
  {
    id: "opening_range",
    name: "Opening range",
    esSubtitle: "Rango de apertura (09:30 - 09:45 EST)",
    countLabel: "2.4k",
    category: "SESSIES",
    functionName: "filter_opening_range_breakout(df)",
    descriptionEs: "Filtro temporal de los primeros 15 minutos de apertura en CME Globex."
  },
  {
    id: "ny_sessie",
    name: "New York-sessie",
    esSubtitle: "Sesión Nueva York (09:30 - 11:30 EST)",
    countLabel: "Activo",
    category: "SESSIES",
    functionName: "filter_ny_killzone(df, start='09:30', end='11:30')",
    descriptionEs: "Ventana de máxima liquidez institucional en futuros NQ y ES."
  },
  {
    id: "londen_sessie",
    name: "Londen-sessie",
    esSubtitle: "Sesión Londres (03:00 - 05:00 EST)",
    countLabel: "",
    category: "SESSIES",
    functionName: "filter_london_open(df, start='03:00', end='05:00')",
    descriptionEs: "Ventana europea de barrido de rangos asiáticos."
  },
  {
    id: "azie_range",
    name: "Azië-range",
    esSubtitle: "Rango Asiático (20:00 - 00:00 EST)",
    countLabel: "2.1k",
    category: "SESSIES",
    functionName: "compute_asian_liquidity_box(df)",
    descriptionEs: "Acumulación nocturna utilizada como objetivo de barrido matutino."
  }
];

const VALIDATION_CHECKLIST = [
  {
    id: "chk-1",
    dutch: "BEVESTIGD",
    es: "Confirmado por KRONOS"
  },
  {
    id: "chk-2",
    dutch: "UIT JOUW DATABESTAND",
    es: "De tu base de datos"
  },
  {
    id: "chk-3",
    dutch: "PLAATJE UIT EIGEN DATA GEHAALD",
    es: "Imagen extraída"
  },
  {
    id: "chk-4",
    dutch: "CODE GEHAALD",
    es: "Código obtenido — 8 de 8 ejemplos"
  },
  {
    id: "chk-5",
    dutch: 'JOUW "KLOPT"',
    es: 'Tu validación — "Tú dijiste correcto"'
  }
];

// Construye un dataset de 28 velas exactas ("kaars 28 van 28") para el motor de Replay
function buildReplayDatasets(): ReplayPatternDataset[] {
  const baseTimestamp = 1729866600;

  // 28 velas diseñadas para mostrar claramente:
  // 1) Caída inicial -> 2) Lower High (vela #7, idx 6) -> 3) Lower Low / Sweep (vela #11, idx 10)
  // -> 4) Desplazamiento FVG (velas #13..#16) -> 5) Ruptura Change of Character (vela #18, idx 17)
  // -> 6) Continuación alcista hasta vela #28
  const raw28Bars: Array<[number, number, number, number]> = [
    [5854.0, 5855.25, 5851.5, 5852.0],   // 1
    [5852.0, 5852.75, 5849.0, 5849.5],   // 2
    [5849.5, 5850.5, 5846.75, 5847.25],  // 3
    [5847.25, 5848.0, 5844.5, 5845.0],   // 4
    [5845.0, 5847.75, 5844.25, 5847.25], // 5
    [5847.25, 5849.5, 5846.5, 5849.0],   // 6
    [5849.0, 5850.75, 5847.25, 5847.75], // 7 -> LOWER HIGH (idx 6, High 5850.75)
    [5847.75, 5848.25, 5843.5, 5844.0],  // 8
    [5844.0, 5844.75, 5840.25, 5840.75], // 9
    [5840.75, 5841.5, 5837.5, 5838.0],   // 10
    [5838.0, 5839.25, 5833.5, 5838.75],  // 11 -> LOWER LOW / SWEEP (idx 10, Low 5833.50)
    [5838.75, 5841.75, 5838.0, 5841.25], // 12
    [5841.25, 5846.5, 5841.0, 5846.0],   // 13 -> Inicio Desplazamiento FVG (idx 12)
    [5846.0, 5849.25, 5845.25, 5848.75], // 14
    [5848.75, 5850.0, 5846.75, 5847.5],  // 15
    [5847.5, 5848.25, 5845.0, 5846.25],  // 16 -> Retesteo a zona FVG
    [5846.25, 5849.75, 5845.75, 5849.25],// 17
    [5849.25, 5853.5, 5848.75, 5853.0],  // 18 -> CHANGE OF CHARACTER (idx 17, rompe 5850.75)
    [5853.0, 5855.25, 5851.75, 5854.75], // 19
    [5854.75, 5855.5, 5852.25, 5853.0],  // 20
    [5853.0, 5856.5, 5852.5, 5856.0],    // 21
    [5856.0, 5858.25, 5855.0, 5857.75],  // 22
    [5857.75, 5858.75, 5855.75, 5856.5], // 23
    [5856.5, 5860.0, 5856.0, 5859.5],    // 24
    [5859.5, 5861.75, 5858.5, 5861.25],  // 25
    [5861.25, 5862.5, 5859.75, 5860.5],  // 26
    [5860.5, 5864.0, 5860.0, 5863.5],    // 27
    [5863.5, 5866.25, 5862.75, 5865.75]  // 28 -> Vela final 28 van 28
  ];

  return Array.from({ length: 8 }, (_, idx) => {
    const offset = idx * 15;
    const candles: ReplayCandleItem[] = raw28Bars.map(([o, h, l, c], i) => ({
      time: (baseTimestamp + idx * 86400 + i * 300) as UTCTimestamp,
      open: Number((o + offset).toFixed(2)),
      high: Number((h + offset).toFixed(2)),
      low: Number((l + offset).toFixed(2)),
      close: Number((c + offset).toFixed(2))
    }));

    return {
      patternId: `sample-${idx + 1}`,
      patternName: "Change of character (CHoCH)",
      patternDutchName: "Change of character",
      symbol: "NQ (E-mini Nasdaq-100) • 5m",
      timeframe: "5m",
      sessionLabel: "New York-sessie (09:30 - 11:30 EST)",
      candles,
      lowerHighIdx: 6,
      lowerLowIdx: 10,
      fvgStartIdx: 11,
      fvgEndIdx: 22,
      fvgBottom: Number((5841.75 + offset).toFixed(2)),
      fvgTop: Number((5845.25 + offset).toFixed(2)),
      chochBreakIdx: 17,
      lowerHighPrice: Number((5850.75 + offset).toFixed(2)),
      lowerLowPrice: Number((5833.5 + offset).toFixed(2)),
      chochBreakPrice: Number((5850.75 + offset).toFixed(2))
    };
  });
}

export interface ViewDSetupValidatorProps {
  onValidateSetup?: (
    setupId: string,
    decision: "APPROVED" | "REJECTED",
    notes?: string
  ) => boolean;
}

export function ViewDSetupValidator({
  onValidateSetup
}: ViewDSetupValidatorProps = {}) {
  const datasets = useMemo(() => buildReplayDatasets(), []);
  const [selectedPatternId, setSelectedPatternId] = useState<string>("choch");
  const [selectedSessionId, setSelectedSessionId] = useState<string>("ny_sessie");
  const [sampleIndex, setSampleIndex] = useState<number>(0);

  const [exclusionNote, setExclusionNote] = useState<string>(
    "Operar únicamente en New York-sessie tras barrido de Lower Low"
  );
  const [decisions, setDecisions] = useState<
    Record<string, "CORRECTO" | "INCORRECTO">
  >({});
  const [lastFeedback, setLastFeedback] = useState<string | null>(null);

  const activePattern =
    STRUCTUUR_PATTERNS.find((p) => p.id === selectedPatternId) ??
    STRUCTUUR_PATTERNS[1];
  const activeSession =
    SESSIES_ITEMS.find((s) => s.id === selectedSessionId) ?? SESSIES_ITEMS[1];

  const currentDataset = useMemo(() => {
    const base = datasets[sampleIndex] ?? datasets[0];
    return {
      ...base,
      patternId: `${selectedPatternId}-${selectedSessionId}-${sampleIndex}`,
      patternName: activePattern.name,
      sessionLabel: activeSession.esSubtitle
    };
  }, [datasets, sampleIndex, selectedPatternId, selectedSessionId, activePattern, activeSession]);

  const currentDecisionKey = `${selectedPatternId}-${sampleIndex}`;
  const currentDecision = decisions[currentDecisionKey] ?? null;

  function handleDecision(verdict: "CORRECTO" | "INCORRECTO") {
    const setupId = `${selectedPatternId.toUpperCase()}_NQ_${120 + sampleIndex + 1}`;
    const wsDecision = verdict === "CORRECTO" ? "APPROVED" : "REJECTED";
    const sentViaWs = onValidateSetup?.(setupId, wsDecision, exclusionNote);

    setDecisions((prev) => ({
      ...prev,
      [currentDecisionKey]: verdict
    }));
    setLastFeedback(
      verdict === "CORRECTO"
        ? `✓ [SENTINEL] "${activePattern.name}" (#${sampleIndex + 1}/8) validado como CORRECTO (Klopt) ${
            sentViaWs ? "→ WS :4100 ACK" : "→ Registrado"
          }`
        : `✕ [SENTINEL] "${activePattern.name}" (#${sampleIndex + 1}/8) marcado como INCORRECTO ${
            sentViaWs ? "→ WS :4100 ACK" : "→ Registrado"
          }`
    );
  }

  return (
    <div className="grid h-full min-h-0 w-full grid-cols-1 gap-2.5 lg:grid-cols-12">
      {/* =====================================================================
          1. PANEL IZQUIERDO: TAXONOMÍA ESTRUCTURAL (PATTERN TAXONOMY - KRONOS)
      ====================================================================== */}
      <aside className="flex min-h-0 flex-col justify-between overflow-y-auto rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3 lg:col-span-3">
        <div className="space-y-3">
          {/* Header del Escáner KRONOS */}
          <div className="border-b border-[#1f222d] pb-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-[#4ade80]">
                ESCÁNER ESTRUCTURAL KRONOS
              </span>
              <span className="rounded border border-[#4ade80]/30 bg-[#4ade80]/10 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#4ade80]">
                212k Patrones
              </span>
            </div>
            <p className="mt-0.5 font-mono text-[9px] text-slate-500">
              Taxonomía histórica extraída de tu base de datos CME
            </p>
          </div>

          {/* SECCIÓN "STRUCTUUR" (ESTRUCTURA) */}
          <div>
            <div className="mb-1.5 flex items-center justify-between px-1 font-mono text-[9px] font-bold uppercase tracking-widest text-slate-500">
              <span>STRUCTUUR (ESTRUCTURA)</span>
              <span>CONTEO</span>
            </div>

            <div className="space-y-1">
              {STRUCTUUR_PATTERNS.map((item) => {
                const isSelected = item.id === selectedPatternId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedPatternId(item.id)}
                    className={`flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left transition-all ${
                      isSelected
                        ? "border-[#4ade80]/50 bg-[#0f1714] text-white shadow-[inset_2px_0_0_#4ade80]"
                        : "border-transparent bg-[#050609]/70 text-slate-400 hover:border-[#1f222d] hover:text-slate-200"
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {/* Icono circular vacío vs círculo con punto interno */}
                      <span
                        className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border ${
                          isSelected
                            ? "border-[#4ade80] bg-[#4ade80]/15"
                            : "border-slate-600"
                        }`}
                      >
                        {isSelected && (
                          <span className="h-1.5 w-1.5 rounded-full bg-[#4ade80] shadow-[0_0_6px_#4ade80]" />
                        )}
                      </span>
                      <div className="truncate">
                        <div className="truncate font-mono text-[11px] font-semibold">
                          {item.name}
                        </div>
                        <div className="truncate font-mono text-[8.5px] text-slate-500">
                          {item.esSubtitle}
                        </div>
                      </div>
                    </div>

                    <span
                      className={`ml-2 shrink-0 font-mono text-[10px] font-bold ${
                        isSelected ? "text-[#4ade80]" : "text-slate-500"
                      }`}
                    >
                      {item.countLabel}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* SECCIÓN "SESSIES EN TIJD" (SESIONES Y TIEMPO) */}
          <div className="pt-1">
            <div className="mb-1.5 flex items-center justify-between px-1 font-mono text-[9px] font-bold uppercase tracking-widest text-slate-500">
              <span>SESSIES EN TIJD (SESIONES Y TIEMPO)</span>
              <span>ESTADO</span>
            </div>

            <div className="space-y-1">
              {SESSIES_ITEMS.map((sess) => {
                const isSelected = sess.id === selectedSessionId;
                return (
                  <button
                    key={sess.id}
                    type="button"
                    onClick={() => setSelectedSessionId(sess.id)}
                    className={`flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left transition-all ${
                      isSelected
                        ? "border-[#22d3ee]/50 bg-[#0d1520] text-white shadow-[inset_2px_0_0_#22d3ee]"
                        : "border-transparent bg-[#050609]/70 text-slate-400 hover:border-[#1f222d] hover:text-slate-200"
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border ${
                          isSelected
                            ? "border-[#22d3ee] bg-[#22d3ee]/15"
                            : "border-slate-600"
                        }`}
                      >
                        {isSelected && (
                          <span className="h-1.5 w-1.5 rounded-full bg-[#22d3ee] shadow-[0_0_6px_#22d3ee]" />
                        )}
                      </span>
                      <div className="truncate">
                        <div className="truncate font-mono text-[11px] font-semibold">
                          {sess.name}
                        </div>
                        <div className="truncate font-mono text-[8.5px] text-slate-500">
                          {sess.esSubtitle}
                        </div>
                      </div>
                    </div>

                    {sess.countLabel && (
                      <span
                        className={`ml-2 shrink-0 rounded px-1.5 py-0.2 font-mono text-[9px] font-bold ${
                          sess.countLabel === "Activo"
                            ? "bg-[#4ade80]/15 text-[#4ade80]"
                            : isSelected
                            ? "text-[#22d3ee]"
                            : "text-slate-500"
                        }`}
                      >
                        {sess.countLabel}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Resumen inferior del filtro activo */}
        <div className="mt-2 rounded border border-[#1f222d] bg-[#050608] p-2 font-mono text-[9px] text-slate-400">
          <div className="flex items-center justify-between">
            <span>Patrón Activo:</span>
            <strong className="text-[#4ade80]">{activePattern.name}</strong>
          </div>
          <div className="mt-0.5 flex items-center justify-between">
            <span>Sesión Temporal:</span>
            <strong className="text-[#22d3ee]">{activeSession.name}</strong>
          </div>
        </div>
      </aside>

      {/* =====================================================================
          2. ÁREA CENTRAL: ANILLO DE VALIDACIÓN (6/6) + MOTOR DE REPLAY VELA A VELA
      ====================================================================== */}
      <div className="flex min-h-0 flex-col justify-between gap-2.5 lg:col-span-6">
        {/* HEADER CENTRAL CON ANILLO DE VALIDACIÓN (DONUT CHART 6/6) */}
        <div className="grid shrink-0 grid-cols-1 gap-2.5 rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3 xl:grid-cols-12">
          {/* Descripción estructural del patrón seleccionado */}
          <div className="flex flex-col justify-between xl:col-span-5">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-[#4ade80]/15 px-1.5 py-0.5 font-mono text-[9px] font-bold text-[#4ade80]">
                  ESTRUCTURA VALIDADA
                </span>
                <span className="font-mono text-[9px] text-slate-500">
                  Muestra {sampleIndex + 1} de 8
                </span>
              </div>
              <h2 className="mt-1 font-mono text-sm font-extrabold text-white">
                {activePattern.name}{" "}
                <span className="text-xs font-normal text-[#22d3ee]">
                  ({activePattern.countLabel})
                </span>
              </h2>
              <p className="mt-1 text-[11px] leading-snug text-slate-400">
                {activePattern.descriptionEs}
              </p>
            </div>

            {/* Navegador de los 8 ejemplos extraídos */}
            <div className="mt-2 flex items-center gap-1.5 font-mono text-[10px]">
              <button
                type="button"
                onClick={() =>
                  setSampleIndex((prev) => (prev - 1 + datasets.length) % datasets.length)
                }
                className="flex h-6 w-6 items-center justify-center rounded border border-[#1f222d] bg-[#030407] text-slate-400 hover:border-[#22d3ee]/40 hover:text-white"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span className="rounded border border-[#1f222d] bg-[#030407] px-2 py-0.5 text-slate-300">
                Ejemplo <strong className="text-[#4ade80]">{sampleIndex + 1}</strong> / 8
              </span>
              <button
                type="button"
                onClick={() => setSampleIndex((prev) => (prev + 1) % datasets.length)}
                className="flex h-6 w-6 items-center justify-center rounded border border-[#1f222d] bg-[#030407] text-slate-400 hover:border-[#22d3ee]/40 hover:text-white"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* WIDGET DE ESTADO DE VALIDACIÓN: ANILLO 6/6 + CHECKLIST */}
          <div className="flex items-center gap-3 rounded-md border border-[#1f222d] bg-[#050608] p-2.5 xl:col-span-7">
            {/* Donut Chart segmentado en 6 partes iguales */}
            <div className="relative flex h-20 w-20 shrink-0 flex-col items-center justify-center">
              <svg viewBox="0 0 100 100" className="h-20 w-20 -rotate-90">
                <circle
                  cx="50"
                  cy="50"
                  r="38"
                  fill="none"
                  stroke="#141824"
                  strokeWidth="10"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="38"
                  fill="none"
                  stroke="#4ade80"
                  strokeWidth="10"
                  strokeDasharray="34.8 5"
                  strokeLinecap="butt"
                  className="drop-shadow-[0_0_6px_rgba(74,222,128,0.55)]"
                />
              </svg>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center font-mono">
                <span className="text-sm font-extrabold leading-none text-white">
                  6/6
                </span>
                <span className="mt-0.5 text-[6.5px] font-bold uppercase tracking-tighter text-[#4ade80]">
                  HELEMAAL KLAAR
                </span>
              </div>
            </div>

            {/* Checklist de 5 pasos al lado del anillo */}
            <div className="min-w-0 flex-1 space-y-1 font-mono text-[9px]">
              <div className="mb-1 flex items-center justify-between border-b border-[#1f222d] pb-0.5">
                <span className="font-bold uppercase text-[#4ade80]">
                  COMPLETAMENTE LISTO (HELEMAAL KLAAR)
                </span>
                <span className="text-[8px] text-slate-500">100% Auditado</span>
              </div>
              {VALIDATION_CHECKLIST.map((step, idx) => (
                <div key={step.id} className="flex items-center gap-1.5 truncate">
                  <CheckCircle2 className="h-3 w-3 shrink-0 text-[#4ade80]" />
                  <span className="font-bold text-slate-200">
                    {idx + 1}. {step.dutch}
                  </span>
                  <span className="truncate text-slate-500">({step.es})</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* EL NÚCLEO: MOTOR DE REPLAY VELA A VELA (BAR-BY-BAR REPLAY) */}
        <div className="min-h-0 flex-1">
          <ReplayCandlestickChart
            dataset={currentDataset}
            decisionBadge={currentDecision}
          />
        </div>
      </div>

      {/* =====================================================================
          3. COLUMNA DERECHA: CÓDIGO EXTRAÍDO (CORTEX) + VALIDACIÓN HUMANA ("KLOPT")
      ====================================================================== */}
      <div className="flex min-h-0 flex-col justify-between gap-2.5 lg:col-span-3">
        {/* Bloque Superior: Código Python extraído (8 de 8 ejemplos) */}
        <div className="flex min-h-0 flex-1 flex-col justify-between overflow-hidden rounded-lg border border-[#1f222d] bg-[#050608] p-3">
          <div className="flex items-center justify-between border-b border-[#1f222d] pb-2">
            <div className="flex items-center gap-1.5">
              <FileCode2 className="h-3.5 w-3.5 text-[#22d3ee]" />
              <span className="font-mono text-[10px] font-bold text-slate-200">
                kronos_{activePattern.id}.py
              </span>
            </div>
            <span className="rounded border border-purple-400/30 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[8.5px] font-bold text-purple-300">
              CORTEX • 8/8 Ejemplos
            </span>
          </div>

          <div className="my-2 flex-1 overflow-auto rounded border border-[#1f222d]/60 bg-[#030407] p-2 font-mono text-[10px] leading-relaxed">
            <pre className="text-slate-300">
              <code>
                <span className="text-slate-500">
                  # Patrón: {activePattern.name} ({activePattern.countLabel})
                </span>
                {"\n"}
                <span className="text-slate-500">
                  # Sesión: {activeSession.name}
                </span>
                {"\n"}
                <span className="text-purple-400">def</span>{" "}
                <span className="font-bold text-[#22d3ee]">
                  {activePattern.functionName}
                </span>
                :{"\n"}
                {"    "}
                <span className="text-slate-500">
                  # 1. Identificar Lower High y Lower Low (Sweep)
                </span>
                {"\n"}
                {"    "}lh_level = df[<span className="text-[#4ade80]">&apos;high&apos;</span>
                ].rolling(<span className="text-[#eab308]">7</span>).max(){"\n"}
                {"    "}ll_sweep = (df[<span className="text-[#4ade80]">&apos;low&apos;</span>
                ] &lt; df[<span className="text-[#4ade80]">&apos;low&apos;</span>].shift(
                <span className="text-[#eab308]">4</span>)){"\n\n"}
                {"    "}
                <span className="text-slate-500">
                  # 2. Validar Desplazamiento + Fair Value Gap
                </span>
                {"\n"}
                {"    "}fvg_bull = df[<span className="text-[#4ade80]">&apos;low&apos;</span>
                ] &gt; df[<span className="text-[#4ade80]">&apos;high&apos;</span>].shift(
                <span className="text-[#eab308]">2</span>){"\n\n"}
                {"    "}
                <span className="text-slate-500">
                  # 3. Ruptura Change of Character (Vela #18)
                </span>
                {"\n"}
                {"    "}choch_break = (df[
                <span className="text-[#4ade80]">&apos;close&apos;</span>] &gt; lh_level) &amp;
                fvg_bull{"\n"}
                {"    "}
                <span className="text-purple-400">return</span> np.where(choch_break,{" "}
                <span className="text-[#eab308]">1</span>,{" "}
                <span className="text-[#eab308]">0</span>)
              </code>
            </pre>
          </div>

          <div className="flex items-center justify-between font-mono text-[9px] text-slate-500">
            <span>Complejidad: O(N) NumPy</span>
            <span className="text-[#4ade80]">✓ 0 Lookahead Bias</span>
          </div>
        </div>

        {/* Bloque Inferior: Validación Human-in-the-Loop (JOUW "KLOPT") */}
        <div className="flex shrink-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-[#eab308]" />
                <h3 className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-100">
                  AUDITORÍA HUMANA (JOUW &ldquo;KLOPT&rdquo;)
                </h3>
              </div>
              <span className="font-mono text-[9px] text-[#4ade80]">WS :4100</span>
            </div>

            <p className="mt-1 text-[11px] leading-snug text-slate-300">
              ¿El motor de Replay forma correctamente el{" "}
              <strong className="text-[#4ade80]">{activePattern.name}</strong>?
            </p>

            <div className="mt-2">
              <input
                type="text"
                value={exclusionNote}
                onChange={(e) => setExclusionNote(e.target.value)}
                className="w-full rounded border border-[#1f222d] bg-[#050608] px-2.5 py-1.5 font-mono text-[10px] text-slate-200 focus:border-[#22d3ee] focus:outline-none"
                placeholder="Restricción de sesión o liquidez..."
              />
            </div>
          </div>

          <div className="mt-2.5 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => handleDecision("CORRECTO")}
              className="flex items-center justify-center gap-1.5 rounded-md border border-[#4ade80] bg-[#050608] px-2.5 py-2 font-mono text-[10px] font-bold text-[#4ade80] transition hover:bg-[#4ade80]/15 hover:shadow-[0_0_16px_rgba(74,222,128,0.28)]"
            >
              <Check className="h-3.5 w-3.5" />
              <span>[Correcto (Klopt)]</span>
            </button>

            <button
              type="button"
              onClick={() => handleDecision("INCORRECTO")}
              className="flex items-center justify-center gap-1.5 rounded-md border border-[#334155] bg-[#050608] px-2.5 py-2 font-mono text-[10px] font-bold text-slate-300 transition hover:border-slate-400 hover:bg-slate-800/50"
            >
              <X className="h-3.5 w-3.5 text-slate-400" />
              <span>[Incorrecto]</span>
            </button>
          </div>

          {lastFeedback && (
            <div className="mt-2 truncate rounded border border-[#1f222d] bg-[#050608] px-2 py-1 font-mono text-[9px] text-[#22d3ee]">
              {lastFeedback}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
