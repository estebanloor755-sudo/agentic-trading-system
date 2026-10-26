"use client";

import React, { useState } from "react";
import { AlertTriangle, BarChart3, Filter, ShieldAlert } from "lucide-react";

export interface RejectionMetricItem {
  id: string;
  label: string;
  DutchRef: string;
  count: number;
  barStyle: "muted-red" | "mustard" | "critical-red" | "slate";
  agentOwner: "ORION" | "KRONOS" | "CORTEX";
  thresholdRule: string;
  diagnosticNote: string;
}

export const INITIAL_REJECTION_METRICS: RejectionMetricItem[] = [
  {
    id: "rej-dd",
    label: "Max Drawdown > Límite Institucional (4.5%)",
    DutchRef: "Max drawdown te hoog",
    count: 219,
    barStyle: "critical-red",
    agentOwner: "ORION",
    thresholdRule: "MaxDD_IS <= 4.50%",
    diagnosticNote:
      "Principal causa de descarte: excursiones adversas severas durante aperturas de NY y eventos FOMC."
  },
  {
    id: "rej-oos",
    label: "Falla prueba Out-of-Sample (Curve-fitting)",
    DutchRef: "Faalt buiten-steekproef test",
    count: 147,
    barStyle: "mustard",
    agentOwner: "ORION",
    thresholdRule: "Sharpe_OOS >= 0.70 * Sharpe_IS",
    diagnosticNote:
      "Degradación severa tras el corte Trade #180; parámetros sobreajustados al ruido histórico In-Sample."
  },
  {
    id: "rej-sample",
    label: "Muestra insuficiente (N < 150)",
    DutchRef: "Te weinig trades",
    count: 76,
    barStyle: "slate",
    agentOwner: "ORION",
    thresholdRule: "Total_Trades >= 150",
    diagnosticNote:
      "Frecuencia operativa demasiado baja para alcanzar significancia estadística al 95% de confianza."
  },
  {
    id: "rej-winrate",
    label: "Winrate < 35%",
    DutchRef: "Winrate < 35%",
    count: 65,
    barStyle: "muted-red",
    agentOwner: "KRONOS",
    thresholdRule: "Win_Rate >= 35.0%",
    diagnosticNote:
      "Rachas perdedoras prolongadas (>11 trades consecutivos) incompatibles con psicotrading y margen intradía."
  },
  {
    id: "rej-expectancy",
    label: "Expectancy Negativa (Tras comisiones)",
    DutchRef: "Negatieve verwachting na kosten",
    count: 20,
    barStyle: "muted-red",
    agentOwner: "ORION",
    thresholdRule: "Net_Expectancy > $18.00 / trade",
    diagnosticNote:
      "El alfa bruto es absorbido por el slippage de ejecución CME Globex (1.2 ticks) y comisiones round-turn."
  },
  {
    id: "rej-rr",
    label: "R:R < 0.9",
    DutchRef: "Risk/Reward < 0.9",
    count: 18,
    barStyle: "slate",
    agentOwner: "KRONOS",
    thresholdRule: "AvgWin / AvgLoss >= 0.90",
    diagnosticNote:
      "Asimetría riesgo/beneficio desfavorable detectada en estructuras FVG con Stop Loss demasiado amplio."
  }
];

interface RejectionAnalysisPanelProps {
  compact?: boolean;
}

export function RejectionAnalysisPanel({ compact = false }: RejectionAnalysisPanelProps) {
  const [selectedId, setSelectedId] = useState<string>("rej-dd");
  const [sortByMagnitude, setSortByMagnitude] = useState<boolean>(true);

  const maxCount = Math.max(...INITIAL_REJECTION_METRICS.map((m) => m.count));
  const totalRejections = INITIAL_REJECTION_METRICS.reduce((acc, m) => acc + m.count, 0);

  // Orden estándar de la directiva o por magnitud
  const orderedMetrics = sortByMagnitude
    ? [...INITIAL_REJECTION_METRICS].sort((a, b) => b.count - a.count)
    : [
        INITIAL_REJECTION_METRICS[3], // Winrate < 35% (65)
        INITIAL_REJECTION_METRICS[5], // R:R < 0.9 (18)
        INITIAL_REJECTION_METRICS[2], // Muestra insuficiente (76)
        INITIAL_REJECTION_METRICS[4], // Expectancy Negativa (20)
        INITIAL_REJECTION_METRICS[0], // Max Drawdown > 4.5% (219)
        INITIAL_REJECTION_METRICS[1]  // Falla OOS (147)
      ];

  const activeMetric =
    INITIAL_REJECTION_METRICS.find((m) => m.id === selectedId) ?? INITIAL_REJECTION_METRICS[0];

  function getBarColors(style: RejectionMetricItem["barStyle"]) {
    switch (style) {
      case "critical-red":
        return {
          bar: "bg-gradient-to-l from-rose-500/90 to-rose-900/50 shadow-[0_0_10px_rgba(244,63,94,0.35)]",
          text: "text-rose-400",
          badge: "border-rose-500/40 bg-rose-500/10 text-rose-300"
        };
      case "mustard":
        return {
          bar: "bg-gradient-to-l from-[#eab308] to-[#eab308]/40 shadow-[0_0_10px_rgba(234,179,8,0.3)]",
          text: "text-[#eab308]",
          badge: "border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]"
        };
      case "muted-red":
        return {
          bar: "bg-gradient-to-l from-rose-700/75 to-rose-950/40",
          text: "text-rose-300/90",
          badge: "border-rose-800/50 bg-rose-950/30 text-rose-300"
        };
      default:
        return {
          bar: "bg-gradient-to-l from-slate-400/75 to-slate-700/30",
          text: "text-slate-300",
          badge: "border-[#1f222d] bg-[#141824] text-slate-300"
        };
    }
  }

  return (
    <div className="flex h-full flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3">
      {/* HEADER DEL PANEL */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded border border-rose-500/30 bg-rose-500/10">
            <Filter className="h-3.5 w-3.5 text-rose-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-100">
                MOTIVOS DE RECHAZO EN BACKTEST (Filtro Cuantitativo)
              </h3>
              <span className="hidden rounded border border-[#22d3ee]/30 bg-[#22d3ee]/10 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#22d3ee] sm:inline">
                AGENTE: ORION
              </span>
            </div>
            <p className="font-mono text-[9px] text-slate-500">
              Auditoría de mortalidad de estrategias (&ldquo;¿Por qué caen en el filtro?&rdquo;) • Total analizado:{" "}
              <strong className="text-slate-300">{totalRejections} descartes</strong>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 font-mono text-[9px]">
          <button
            type="button"
            onClick={() => setSortByMagnitude((prev) => !prev)}
            className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-slate-400 transition hover:border-[#22d3ee]/40 hover:text-slate-200"
            title="Alternar orden por impacto o secuencia estándar"
          >
            <BarChart3 className="h-3 w-3 text-[#22d3ee]" />
            <span>{sortByMagnitude ? "Orden: Mayor Impacto" : "Orden: Secuencia Filtro"}</span>
          </button>
        </div>
      </div>

      {/* GRÁFICO DE BARRAS HORIZONTALES ALINEADAS A LA DERECHA */}
      <div className={`my-2 flex flex-1 flex-col justify-around ${compact ? "gap-1.5" : "gap-2"}`}>
        {orderedMetrics.map((metric) => {
          const widthPct = Math.max(6, Math.round((metric.count / maxCount) * 100));
          const pctOfTotal = ((metric.count / totalRejections) * 100).toFixed(1);
          const colors = getBarColors(metric.barStyle);
          const isSelected = metric.id === selectedId;

          return (
            <button
              key={metric.id}
              type="button"
              onClick={() => setSelectedId(metric.id)}
              className={`group flex w-full items-center justify-between gap-3 rounded border px-2.5 py-1.5 text-left transition ${
                isSelected
                  ? "border-[#22d3ee]/40 bg-[#0d111a]"
                  : "border-transparent bg-[#050609]/80 hover:border-[#1f222d] hover:bg-[#080a10]"
              }`}
            >
              {/* ETIQUETA IZQUIERDA */}
              <div className="min-w-0 flex-1 pr-2">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`truncate font-mono text-[10px] font-semibold ${
                      isSelected ? "text-white" : "text-slate-300 group-hover:text-white"
                    }`}
                  >
                    {metric.label}
                  </span>
                </div>
              </div>

              {/* BARRA HORIZONTAL DELGADA ALINEADA A LA DERECHA + VALOR NUMÉRICO */}
              <div className="flex w-44 shrink-0 items-center justify-end gap-2.5 sm:w-56 md:w-64">
                <div className="flex h-2 flex-1 items-center justify-end overflow-hidden rounded-full bg-[#131622]">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>

                <div className="flex w-16 shrink-0 items-baseline justify-end gap-1 font-mono">
                  <span className={`text-xs font-extrabold ${colors.text}`}>
                    {metric.count}
                  </span>
                  <span className="text-[9px] text-slate-500">({pctOfTotal}%)</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* FOOTER DE DIAGNÓSTICO DEL SUB-AGENTE ORION / KRONOS */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#1f222d] bg-[#050608] px-2.5 py-1.5 font-mono text-[10px]">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {activeMetric.barStyle === "mustard" ? (
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[#eab308]" />
          ) : (
            <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-rose-400" />
          )}
          <span className="shrink-0 font-bold text-[#22d3ee]">
            [{activeMetric.agentOwner}]
          </span>
          <span className="truncate text-slate-400">{activeMetric.diagnosticNote}</span>
        </div>

        <span className="shrink-0 rounded border border-[#1f222d] bg-[#0a0b10] px-2 py-0.5 text-[9px] text-slate-300">
          Regla: <strong className="text-[#4ade80]">{activeMetric.thresholdRule}</strong>
        </span>
      </div>
    </div>
  );
}
