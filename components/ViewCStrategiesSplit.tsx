"use client";

import React, { useMemo, useState } from "react";
import { GitBranch, Layers, Search, Sparkles } from "lucide-react";
import {
  generateSpaghettiDataset,
  STRATEGIES_LIST,
  type QuantStrategyItem
} from "./mockData";

const TOTAL_TRADES = 260;
const SPLIT_INDEX = 180; // Línea divisoria vertical: 0..180 In-Sample, 180..260 Out-Of-Sample

export function ViewCStrategiesSplit() {
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("STR-001");
  const [statusFilter, setStatusFilter] = useState<
    "ALL" | "EN VIVO" | "APROBADA" | "FILTRO"
  >("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [curveFilter, setCurveFilter] = useState<"ALL" | "SURVIVORS" | "LIVE_ONLY">(
    "ALL"
  );
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const spaghettiCurves = useMemo(
    () => generateSpaghettiDataset(TOTAL_TRADES, SPLIT_INDEX),
    []
  );

  const selectedStrategy: QuantStrategyItem = useMemo(
    () =>
      STRATEGIES_LIST.find((s) => s.id === selectedStrategyId) ??
      STRATEGIES_LIST[0],
    [selectedStrategyId]
  );

  const filteredStrategies = useMemo(() => {
    return STRATEGIES_LIST.filter((item) => {
      if (statusFilter !== "ALL" && item.status !== statusFilter) return false;
      if (
        searchQuery.trim() &&
        !item.name.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !item.instrument.toLowerCase().includes(searchQuery.toLowerCase()) &&
        !item.family.toLowerCase().includes(searchQuery.toLowerCase())
      ) {
        return false;
      }
      return true;
    });
  }, [statusFilter, searchQuery]);

  const selectedCurveIndex = useMemo(() => {
    const idx = STRATEGIES_LIST.findIndex((s) => s.id === selectedStrategyId);
    return idx >= 0 ? idx : 0;
  }, [selectedStrategyId]);

  const svgWidth = 1000;
  const svgHeight = 360;
  const padLeft = 58;
  const padRight = 68;
  const padTop = 26;
  const padBottom = 30;
  const plotW = svgWidth - padLeft - padRight;
  const plotH = svgHeight - padTop - padBottom;

  const { minVal, maxVal } = useMemo(() => {
    let min = -6000;
    let max = 48000;
    for (const c of spaghettiCurves) {
      for (const v of c.points) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    return { minVal: min - 2000, maxVal: max + 3000 };
  }, [spaghettiCurves]);

  const xForStep = (step: number) =>
    padLeft + (step / (TOTAL_TRADES - 1)) * plotW;
  const yForValue = (val: number) =>
    padTop + plotH - ((val - minVal) / (maxVal - minVal)) * plotH;

  const splitX = xForStep(SPLIT_INDEX);

  const buildPath = (points: number[]) => {
    return points
      .map(
        (val, idx) =>
          `${idx === 0 ? "M" : "L"}${xForStep(idx).toFixed(1)},${yForValue(
            val
          ).toFixed(1)}`
      )
      .join(" ");
  };

  const oosEnvelopePath = useMemo(() => {
    const upperPts: string[] = [];
    const lowerPts: string[] = [];

    for (let t = SPLIT_INDEX; t < TOTAL_TRADES; t++) {
      const vals = spaghettiCurves.map((c) => c.points[t]).sort((a, b) => a - b);
      const p10 = vals[Math.floor(vals.length * 0.12)];
      const p90 = vals[Math.floor(vals.length * 0.88)];
      const x = xForStep(t).toFixed(1);
      upperPts.push(
        `${t === SPLIT_INDEX ? "M" : "L"}${x},${yForValue(p90).toFixed(1)}`
      );
      lowerPts.unshift(`L${x},${yForValue(p10).toFixed(1)}`);
    }

    return `${upperPts.join(" ")} ${lowerPts.join(" ")} Z`;
  }, [spaghettiCurves]);

  const activeStep = hoverIndex !== null ? hoverIndex : TOTAL_TRADES - 1;
  const primaryCurve = spaghettiCurves[selectedCurveIndex] ?? spaghettiCurves[0];
  const activePrimaryValue =
    primaryCurve.points[activeStep] ?? primaryCurve.finalPnl;
  const isActiveStepOOS = activeStep > SPLIT_INDEX;

  return (
    <div className="grid h-full min-h-0 w-full grid-cols-1 gap-2.5 lg:grid-cols-12">
      {/* COLUMNA IZQUIERDA (4 COLS): BIBLIOTECA DE ESTRATEGIAS + SPARKLINES */}
      <div className="flex min-h-0 flex-col rounded-lg border border-[#1f222d] bg-[#0a0b10] lg:col-span-4">
        <div className="border-b border-[#1f222d] p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-[#22d3ee]" />
              <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                BIBLIOTECA DE ESTRATEGIAS
              </h2>
            </div>
            <span className="rounded border border-[#1f222d] bg-[#030407] px-2 py-0.5 font-mono text-[10px] text-[#4ade80]">
              343 Aprobadas • 3 En Vivo
            </span>
          </div>

          <div className="mt-2.5 flex items-center gap-1.5">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Buscar estrategia, mercado (ES, NQ, GC)..."
                className="h-7 w-full rounded border border-[#1f222d] bg-[#030407] pl-7 pr-2 font-mono text-[11px] text-slate-200 placeholder-slate-600 outline-none focus:border-[#22d3ee]/60"
              />
            </div>
            <div className="flex items-center rounded border border-[#1f222d] bg-[#030407] p-0.5 font-mono text-[9px]">
              {(
                [
                  { id: "ALL", label: "Todas" },
                  { id: "EN VIVO", label: "En Vivo" },
                  { id: "APROBADA", label: "Paper" },
                  { id: "FILTRO", label: "Filtro" }
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setStatusFilter(tab.id)}
                  className={`rounded px-1.5 py-0.5 transition ${
                    statusFilter === tab.id
                      ? "bg-[#1f222d] font-bold text-[#22d3ee]"
                      : "text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-2.5 grid grid-cols-12 px-1.5 font-mono text-[9px] uppercase tracking-wider text-slate-500">
            <span className="col-span-5">Estrategia / Activo</span>
            <span className="col-span-3 text-right">IS / OOS SR</span>
            <span className="col-span-4 text-right">Curva Sparkline</span>
          </div>
        </div>

        <div className="flex-1 divide-y divide-[#1f222d]/60 overflow-y-auto">
          {filteredStrategies.map((strat) => {
            const isSelected = strat.id === selectedStrategyId;
            const statusBadge =
              strat.status === "EN VIVO"
                ? "border-[#4ade80]/40 bg-[#4ade80]/10 text-[#4ade80]"
                : strat.status === "APROBADA"
                ? "border-[#22d3ee]/40 bg-[#22d3ee]/10 text-[#22d3ee]"
                : strat.status === "FILTRO"
                ? "border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]"
                : "border-red-500/40 bg-red-500/10 text-red-400";

            return (
              <button
                key={strat.id}
                type="button"
                onClick={() => setSelectedStrategyId(strat.id)}
                className={`group grid w-full grid-cols-12 items-center gap-1 px-3 py-2.5 text-left transition ${
                  isSelected
                    ? "bg-[#131622] shadow-[inset_2px_0_0_#4ade80]"
                    : "hover:bg-[#0e1017]"
                }`}
              >
                <div className="col-span-5 min-w-0 pr-1">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        strat.status === "EN VIVO"
                          ? "animate-pulse bg-[#4ade80]"
                          : strat.status === "APROBADA"
                          ? "bg-[#22d3ee]"
                          : strat.status === "FILTRO"
                          ? "bg-[#eab308]"
                          : "bg-red-500"
                      }`}
                    />
                    <p className="truncate font-mono text-xs font-bold text-slate-100 group-hover:text-white">
                      {strat.name}
                    </p>
                  </div>
                  <div className="mt-1 flex items-center gap-1.5">
                    <span
                      className={`rounded border px-1 py-0.2 font-mono text-[8px] font-bold ${statusBadge}`}
                    >
                      {strat.status}
                    </span>
                    <span className="truncate font-mono text-[10px] text-slate-400">
                      {strat.instrument.split(" ")[0]} • {strat.timeframe}
                    </span>
                  </div>
                </div>

                <div className="col-span-3 text-right font-mono">
                  <div className="text-[11px] font-bold text-slate-200">
                    <span>{strat.sharpeIS.toFixed(2)}</span>
                    <span className="mx-0.5 text-slate-600">→</span>
                    <span
                      className={
                        strat.sharpeOOS >= 2.0
                          ? "text-[#4ade80]"
                          : strat.sharpeOOS >= 1.4
                          ? "text-[#22d3ee]"
                          : "text-red-400"
                      }
                    >
                      {strat.sharpeOOS.toFixed(2)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[9px] text-slate-500">
                    WR {strat.winRate}% • PF {strat.profitFactor}
                  </div>
                </div>

                <div className="col-span-4 flex flex-col items-end justify-center">
                  <MiniSparkline
                    data={strat.sparkline}
                    color={
                      strat.status === "DESCARTADA"
                        ? "#ef4444"
                        : strat.status === "EN VIVO"
                        ? "#4ade80"
                        : "#22d3ee"
                    }
                  />
                  <span
                    className={`mt-0.5 font-mono text-[10px] font-semibold ${
                      strat.status === "DESCARTADA"
                        ? "text-red-400"
                        : "text-[#4ade80]"
                    }`}
                  >
                    +${strat.netPnl.toLocaleString()}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="flex items-center justify-between border-t border-[#1f222d] bg-[#06070b] px-3 py-2 font-mono text-[10px] text-slate-400">
          <span>
            Activa: <strong className="text-[#4ade80]">{selectedStrategy.name}</strong>
          </span>
          <span>
            Origen:{" "}
            <strong className="text-[#22d3ee]">
              {selectedStrategy.sourceOrigin}
            </strong>{" "}
            ({selectedStrategy.authorAgent})
          </span>
        </div>
      </div>

      {/* COLUMNA DERECHA (8 COLS): AUDITORÍA IS/OOS + GRÁFICO SPAGHETTI EN ABANICO */}
      <div className="flex min-h-0 flex-col gap-2.5 lg:col-span-8">
        <div className="grid shrink-0 grid-cols-2 gap-2 rounded-lg border border-[#1f222d] bg-[#0a0b10] p-2.5 sm:grid-cols-6">
          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              ESTRATEGIA ACTIVA
            </span>
            <span className="mt-0.5 block truncate font-mono text-xs font-bold text-[#4ade80]">
              {selectedStrategy.name}
            </span>
            <span className="font-mono text-[9px] text-slate-400">
              {selectedStrategy.instrument} ({selectedStrategy.timeframe})
            </span>
          </div>

          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              SHARPE (IS → OOS)
            </span>
            <div className="mt-0.5 flex items-baseline gap-1 font-mono text-sm font-bold">
              <span className="text-slate-200">{selectedStrategy.sharpeIS}</span>
              <span className="text-xs text-slate-600">/</span>
              <span className="text-[#22d3ee]">{selectedStrategy.sharpeOOS}</span>
            </div>
            <span className="font-mono text-[9px] text-[#4ade80]">
              Retención: {selectedStrategy.oosRetention}%
            </span>
          </div>

          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              PROFIT FACTOR
            </span>
            <span className="mt-0.5 block font-mono text-sm font-bold text-slate-100">
              {selectedStrategy.profitFactor.toFixed(2)}
            </span>
            <span className="font-mono text-[9px] text-slate-400">
              Tasa Acierto: {selectedStrategy.winRate}%
            </span>
          </div>

          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              MAX DRAWDOWN
            </span>
            <span className="mt-0.5 block font-mono text-sm font-bold text-[#eab308]">
              {selectedStrategy.maxDrawdown.toFixed(2)}%
            </span>
            <span className="font-mono text-[9px] text-slate-400">
              Límite: -4.50%
            </span>
          </div>

          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              TOTAL OPERACIONES
            </span>
            <span className="mt-0.5 block font-mono text-sm font-bold text-slate-100">
              {selectedStrategy.totalTrades}
            </span>
            <span className="font-mono text-[9px] text-[#22d3ee]">
              180 IS • {selectedStrategy.totalTrades - 180} OOS
            </span>
          </div>

          <div className="rounded border border-[#1f222d]/80 bg-[#030407] px-2.5 py-1.5">
            <span className="block font-mono text-[9px] uppercase text-slate-500">
              PNL NETO (ACUM.)
            </span>
            <span className="mt-0.5 block font-mono text-sm font-bold text-[#4ade80]">
              +${selectedStrategy.netPnl.toLocaleString()}
            </span>
            <span className="font-mono text-[9px] text-slate-400">
              Walk-Forward Validado
            </span>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
            <div>
              <div className="flex items-center gap-2">
                <GitBranch className="h-3.5 w-3.5 text-[#4ade80]" />
                <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                  CLÚSTER MULTI-EQUIDAD SPAGHETTI — IN-SAMPLE (IS) VS. ABANICO OUT-OF-SAMPLE (OOS)
                </h3>
              </div>
              <p className="mt-0.5 font-mono text-[10px] text-slate-400">
                28 Variantes Paramétricas y Generadas por Agentes • Corte Vertical en Trade #{SPLIT_INDEX} (Validación Walk-Forward)
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="hidden items-center gap-3 font-mono text-[10px] xl:flex">
                <span className="flex items-center gap-1.5 text-[#4ade80]">
                  <span className="h-0.5 w-3.5 bg-[#4ade80] shadow-[0_0_6px_#4ade80]" />
                  Activa / En Vivo (3)
                </span>
                <span className="flex items-center gap-1.5 text-[#22d3ee]">
                  <span className="h-0.5 w-3.5 bg-[#22d3ee]" />
                  Aprobadas (12)
                </span>
                <span className="flex items-center gap-1.5 text-slate-400">
                  <span className="h-0.5 w-3.5 bg-slate-600" />
                  Clúster Filtro (343)
                </span>
                <span className="flex items-center gap-1.5 text-red-400/80">
                  <span className="h-0.5 w-3.5 bg-red-500/60" />
                  Degradación OOS (Sobreajuste)
                </span>
              </div>

              <div className="flex items-center rounded border border-[#1f222d] bg-[#030407] p-0.5 font-mono text-[9px]">
                {(
                  [
                    { id: "ALL", label: "Todas (28)" },
                    { id: "SURVIVORS", label: "Superan OOS (12)" },
                    { id: "LIVE_ONLY", label: "En Vivo (3)" }
                  ] as const
                ).map((mode) => (
                  <button
                    key={mode.id}
                    onClick={() => setCurveFilter(mode.id)}
                    className={`rounded px-2 py-0.5 transition ${
                      curveFilter === mode.id
                        ? "bg-[#1f222d] font-bold text-[#4ade80]"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="relative my-1.5 flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-[#1f222d]/80 bg-[#030407]">
            <div className="pointer-events-none absolute inset-x-0 top-2 z-10 flex justify-between px-16 font-mono text-[10px]">
              <div className="flex items-center gap-2 rounded border border-[#1f222d] bg-[#0a0b10]/90 px-2.5 py-1 text-slate-300">
                <span className="h-1.5 w-1.5 rounded-full bg-[#22d3ee]" />
                <span>ENTRENAMIENTO IN-SAMPLE (IS) • TRADES 1 – {SPLIT_INDEX}</span>
              </div>

              <div className="flex items-center gap-2 rounded border border-[#4ade80]/30 bg-[#0a0b10]/90 px-2.5 py-1 text-[#4ade80]">
                <Sparkles className="h-3 w-3 text-[#4ade80]" />
                <span>ABANICO OUT-OF-SAMPLE (OOS) • TRADES {SPLIT_INDEX} – {TOTAL_TRADES}</span>
              </div>
            </div>

            <div className="pointer-events-none absolute bottom-9 left-16 z-10 flex items-center gap-3 rounded border border-[#1f222d] bg-[#0a0b10]/90 px-2.5 py-1 font-mono text-[10px]">
              <span className="text-slate-400">
                Operación <strong className="text-slate-100">#{activeStep}</strong>
              </span>
              <span
                className={`rounded px-1.5 py-0.2 text-[9px] font-bold ${
                  isActiveStepOOS
                    ? "bg-[#4ade80]/15 text-[#4ade80]"
                    : "bg-[#22d3ee]/15 text-[#22d3ee]"
                }`}
              >
                {isActiveStepOOS ? "OUT-OF-SAMPLE (OOS)" : "IN-SAMPLE (IS)"}
              </span>
              <span className="text-slate-400">
                {selectedStrategy.name}:{" "}
                <strong className="text-[#4ade80]">
                  {activePrimaryValue >= 0
                    ? `+$${activePrimaryValue.toLocaleString()}`
                    : `-$${Math.abs(activePrimaryValue).toLocaleString()}`}
                </strong>
              </span>
            </div>

            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              preserveAspectRatio="none"
              className="h-full w-full flex-1 cursor-crosshair"
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const relX = ((e.clientX - rect.left) / rect.width) * svgWidth;
                const clampedX = Math.max(padLeft, Math.min(svgWidth - padRight, relX));
                const step = Math.round(((clampedX - padLeft) / plotW) * (TOTAL_TRADES - 1));
                setHoverIndex(step);
              }}
              onMouseLeave={() => setHoverIndex(null)}
            >
              <defs>
                <linearGradient id="oosBgZone" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.06" />
                  <stop offset="100%" stopColor="#4ade80" stopOpacity="0.02" />
                </linearGradient>
                <linearGradient id="oosConeGrad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.03" />
                  <stop offset="100%" stopColor="#4ade80" stopOpacity="0.11" />
                </linearGradient>
                <filter id="neonGlow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="2.5" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              <rect
                x={splitX}
                y={padTop}
                width={svgWidth - padRight - splitX}
                height={plotH}
                fill="url(#oosBgZone)"
              />

              {[-5000, 0, 10000, 20000, 30000, 40000].map((lvl) => {
                const y = yForValue(lvl);
                const isZero = lvl === 0;
                return (
                  <g key={lvl}>
                    <line
                      x1={padLeft}
                      y1={y}
                      x2={svgWidth - padRight}
                      y2={y}
                      stroke={isZero ? "#334155" : "#141722"}
                      strokeDasharray={isZero ? "3 3" : undefined}
                      strokeWidth={isZero ? 1.2 : 1}
                    />
                    <text
                      x={padLeft - 8}
                      y={y + 3}
                      textAnchor="end"
                      className="fill-slate-500 font-mono text-[9px]"
                    >
                      {lvl >= 0 ? `+$${lvl / 1000}k` : `-$${Math.abs(lvl) / 1000}k`}
                    </text>
                  </g>
                );
              })}

              {[0, 40, 80, 120, 160, 200, 240].map((tStep) => {
                const x = xForStep(tStep);
                return (
                  <g key={tStep}>
                    <line
                      x1={x}
                      y1={padTop}
                      x2={x}
                      y2={svgHeight - padBottom}
                      stroke="#11131c"
                      strokeWidth="1"
                    />
                    <text
                      x={x}
                      y={svgHeight - 10}
                      textAnchor="middle"
                      className="fill-slate-600 font-mono text-[9px]"
                    >
                      T{tStep}
                    </text>
                  </g>
                );
              })}

              <path d={oosEnvelopePath} fill="url(#oosConeGrad)" />

              {spaghettiCurves.map((curve, idx) => {
                const isHighlighted = idx === selectedCurveIndex;

                if (
                  curveFilter === "LIVE_ONLY" &&
                  curve.status !== "PRIMARY" &&
                  curve.status !== "LIVE" &&
                  !isHighlighted
                ) {
                  return null;
                }
                if (
                  curveFilter === "SURVIVORS" &&
                  curve.status === "DECAYED" &&
                  !isHighlighted
                ) {
                  return null;
                }

                let stroke = "#334155";
                let strokeWidth = 1.0;
                let opacity = 0.38;

                if (isHighlighted) {
                  stroke = "#4ade80";
                  strokeWidth = 2.6;
                  opacity = 1;
                } else if (curve.status === "PRIMARY" || curve.status === "LIVE") {
                  stroke = "#4ade80";
                  strokeWidth = 1.75;
                  opacity = 0.85;
                } else if (curve.status === "APPROVED") {
                  stroke = "#22d3ee";
                  strokeWidth = 1.3;
                  opacity = 0.65;
                } else if (curve.status === "DECAYED") {
                  stroke = "#ef4444";
                  strokeWidth = 1.0;
                  opacity = 0.35;
                }

                return (
                  <path
                    key={curve.id}
                    d={buildPath(curve.points)}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    strokeOpacity={opacity}
                    filter={isHighlighted ? "url(#neonGlow)" : undefined}
                  />
                );
              })}

              {/* LÍNEA VERTICAL DIVISORIA: IN-SAMPLE (IS) | OUT-OF-SAMPLE (OOS) */}
              <g>
                <line
                  x1={splitX}
                  y1={padTop}
                  x2={splitX}
                  y2={svgHeight - padBottom}
                  stroke="#eab308"
                  strokeOpacity="0.22"
                  strokeWidth="6"
                />
                <line
                  x1={splitX}
                  y1={padTop}
                  x2={splitX}
                  y2={svgHeight - padBottom}
                  stroke="#eab308"
                  strokeWidth="1.6"
                  strokeDasharray="5 4"
                />
                <rect
                  x={splitX - 62}
                  y={svgHeight - padBottom - 20}
                  width="124"
                  height="16"
                  rx="3"
                  fill="#0a0b10"
                  stroke="#eab308"
                  strokeWidth="1"
                />
                <text
                  x={splitX}
                  y={svgHeight - padBottom - 9}
                  textAnchor="middle"
                  className="fill-[#eab308] font-mono text-[9px] font-bold"
                >
                  ◄ CORTE IS | OOS ►
                </text>
              </g>

              {hoverIndex !== null && (
                <g>
                  <line
                    x1={xForStep(hoverIndex)}
                    y1={padTop}
                    x2={xForStep(hoverIndex)}
                    y2={svgHeight - padBottom}
                    stroke="#22d3ee"
                    strokeWidth="1"
                    strokeDasharray="2 2"
                  />
                  <circle
                    cx={xForStep(hoverIndex)}
                    cy={yForValue(activePrimaryValue)}
                    r="4.5"
                    fill="#4ade80"
                    stroke="#030407"
                    strokeWidth="1.5"
                  />
                </g>
              )}

              <g>
                <circle
                  cx={xForStep(TOTAL_TRADES - 1)}
                  cy={yForValue(primaryCurve.finalPnl)}
                  r="3.5"
                  fill="#4ade80"
                />
                <text
                  x={svgWidth - padRight + 6}
                  y={yForValue(primaryCurve.finalPnl) + 3}
                  className="fill-[#4ade80] font-mono text-[9px] font-bold"
                >
                  +${(primaryCurve.finalPnl / 1000).toFixed(1)}k
                </text>
              </g>
            </svg>
          </div>

          <div className="grid shrink-0 grid-cols-1 gap-2 border-t border-[#1f222d] pt-2 sm:grid-cols-4">
            <div className="flex items-center justify-between rounded border border-[#1f222d]/70 bg-[#030407] px-2.5 py-1.5 font-mono text-[10px]">
              <span className="text-slate-500">MEDIA IN-SAMPLE</span>
              <span className="font-bold text-[#22d3ee]">+$24,180 (SR 2.64)</span>
            </div>
            <div className="flex items-center justify-between rounded border border-[#1f222d]/70 bg-[#030407] px-2.5 py-1.5 font-mono text-[10px]">
              <span className="text-slate-500">MEDIANA OOS (P50)</span>
              <span className="font-bold text-[#4ade80]">+$34,920 (SR 2.31)</span>
            </div>
            <div className="flex items-center justify-between rounded border border-[#1f222d]/70 bg-[#030407] px-2.5 py-1.5 font-mono text-[10px]">
              <span className="text-slate-500">ABANICO OOS (P90/P10)</span>
              <span className="font-bold text-slate-200">+$44.9k / +$6.4k</span>
            </div>
            <div className="flex items-center justify-between rounded border border-[#1f222d]/70 bg-[#030407] px-2.5 py-1.5 font-mono text-[10px]">
              <span className="text-slate-500">RATIO SOBREAJUSTE</span>
              <span className="font-bold text-[#eab308]">14.2% (Riesgo Bajo)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniSparkline({ data, color }: { data: number[]; color: string }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(1, max - min);
  const width = 76;
  const height = 20;

  const points = data
    .map((val, idx) => {
      const x = (idx / (data.length - 1)) * width;
      const y = height - 2 - ((val - min) / range) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
