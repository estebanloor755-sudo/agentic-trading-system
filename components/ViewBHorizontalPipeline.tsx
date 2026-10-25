"use client";

import React, { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Handle,
  Position,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps
} from "reactflow";
import "reactflow/dist/style.css";
import { GitBranch, RotateCcw } from "lucide-react";

interface SourceNodeData {
  label: string;
  count: string;
  tag: string;
  accent: "cyan" | "green" | "mustard" | "slate";
}

interface StageNodeData {
  stepNumber: number;
  label: string;
  count: string;
  subtitle: string;
  isActive?: boolean;
  isFinal?: boolean;
  dropLabel?: string;
  dropDetail?: string;
  selected?: boolean;
  onSelect?: (label: string) => void;
}

function SourceInputNode({ data }: NodeProps<SourceNodeData>) {
  const borderAccent =
    data.accent === "cyan"
      ? "border-[#22d3ee]/40 text-[#22d3ee]"
      : data.accent === "green"
      ? "border-[#4ade80]/40 text-[#4ade80]"
      : data.accent === "mustard"
      ? "border-[#eab308]/40 text-[#eab308]"
      : "border-[#334155] text-slate-300";

  return (
    <div className="relative flex w-[152px] items-center justify-between rounded-md border border-[#1f222d] bg-[#050609] px-3 py-2 shadow-[0_4px_20px_rgba(0,0,0,0.6)]">
      <div>
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-[#22d3ee]" />
          <span className="font-mono text-[11px] font-bold text-slate-200">
            {data.label}
          </span>
        </div>
        <span className="mt-0.5 block font-mono text-[9px] uppercase tracking-wider text-slate-500">
          {data.tag}
        </span>
      </div>

      <span
        className={`rounded border bg-[#0a0b10] px-1.5 py-0.5 font-mono text-xs font-extrabold ${borderAccent}`}
      >
        {data.count}
      </span>

      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-[#334155] !bg-[#22d3ee]"
      />
    </div>
  );
}

function PipelineStageNode({ data }: NodeProps<StageNodeData>) {
  const isHighlighted = Boolean(data.isActive);
  const isFinal = Boolean(data.isFinal);

  const ringClasses = isHighlighted
    ? "border-2 border-[#22d3ee] bg-[#071118] shadow-[0_0_32px_rgba(34,211,238,0.28),inset_0_0_14px_rgba(34,211,238,0.18)]"
    : isFinal
    ? "border-2 border-[#4ade80] bg-[#06120c] shadow-[0_0_26px_rgba(74,222,128,0.22)]"
    : "border border-[#2b3040] bg-[#050609] hover:border-[#22d3ee]/50";

  const countColor = isHighlighted
    ? "text-[#22d3ee]"
    : isFinal
    ? "text-[#4ade80]"
    : "text-slate-100";

  return (
    <div
      onClick={() => data.onSelect?.(data.label)}
      className="group relative flex flex-col items-center cursor-pointer select-none"
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-[#334155] !bg-[#1f222d]"
      />

      {isHighlighted && (
        <>
          <span className="pointer-events-none absolute -top-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded border border-[#22d3ee]/40 bg-[#050609] px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-widest text-[#22d3ee] shadow">
            ⚡ BACKTEST ACTIVO
          </span>
          <div className="pointer-events-none absolute top-3 h-[106px] w-[106px] animate-ping rounded-full border border-[#22d3ee]/25" />
          <div className="pointer-events-none absolute top-1.5 h-[118px] w-[118px] animate-pulse rounded-full border border-dashed border-[#22d3ee]/40" />
        </>
      )}

      <div
        className={`relative mt-3 flex h-[106px] w-[106px] flex-col items-center justify-center rounded-full px-2 text-center transition-all duration-300 ${ringClasses}`}
      >
        <span className="font-mono text-[9px] uppercase tracking-wider text-slate-500">
          0{data.stepNumber}
        </span>
        <span className="mt-0.5 font-mono text-[11px] font-bold tracking-tight text-slate-200">
          {data.label}
        </span>
        <span className={`mt-0.5 font-mono text-lg font-extrabold tracking-tight ${countColor}`}>
          ({data.count})
        </span>
        <span className="mt-0.5 font-mono text-[8px] text-slate-500">
          {data.subtitle}
        </span>
      </div>

      {data.dropLabel && (
        <div className="mt-3 flex flex-col items-center text-center">
          <div className="h-3 w-[1px] bg-[#334155]/70" />
          <div className="rounded border border-[#1f222d] bg-[#050609]/95 px-2 py-1 shadow">
            <p className="whitespace-nowrap font-mono text-[10px] font-semibold text-slate-400">
              {data.dropLabel}
            </p>
            {data.dropDetail && (
              <p className="whitespace-nowrap font-mono text-[8px] text-slate-500">
                {data.dropDetail}
              </p>
            )}
          </div>
        </div>
      )}

      {!isFinal && (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2 !w-2 !border-[#334155] !bg-[#22d3ee]"
        />
      )}
    </div>
  );
}

const NODE_TYPES = {
  sourceInput: SourceInputNode,
  pipelineStage: PipelineStageNode
};

function PipelineFlowCanvas({
  selectedStage,
  onSelectStage
}: {
  selectedStage: string;
  onSelectStage: (stage: string) => void;
}) {
  const { fitView } = useReactFlow();

  const nodes: Node[] = useMemo(
    () => [
      {
        id: "src-youtube",
        type: "sourceInput",
        position: { x: 0, y: 20 },
        data: { label: "YouTube", count: "185", tag: "Transcripciones", accent: "cyan" }
      },
      {
        id: "src-github",
        type: "sourceInput",
        position: { x: 0, y: 105 },
        data: { label: "GitHub", count: "90", tag: "Repos Alpha", accent: "green" }
      },
      {
        id: "src-arxiv",
        type: "sourceInput",
        position: { x: 0, y: 190 },
        data: { label: "arXiv", count: "55", tag: "Papers Quant", accent: "mustard" }
      },
      {
        id: "src-web",
        type: "sourceInput",
        position: { x: 0, y: 275 },
        data: { label: "Web", count: "77", tag: "Foros y Blogs", accent: "slate" }
      },

      {
        id: "st-leidos",
        type: "pipelineStage",
        position: { x: 220, y: 100 },
        data: {
          stepNumber: 1,
          label: "Leídos",
          count: "407",
          subtitle: "Fuentes Ingeridas",
          dropLabel: "Descartados 6",
          dropDetail: "Duplicados / Ruido",
          selected: selectedStage === "Leídos",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-resumidos",
        type: "pipelineStage",
        position: { x: 390, y: 100 },
        data: {
          stepNumber: 2,
          label: "Resumidos",
          count: "401",
          subtitle: "Síntesis NLP",
          dropLabel: "Expansión ×3.26",
          dropDetail: "+907 Hipótesis IA",
          selected: selectedStage === "Resumidos",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-ideados",
        type: "pipelineStage",
        position: { x: 560, y: 100 },
        data: {
          stepNumber: 3,
          label: "Ideados",
          count: "1,308",
          subtitle: "Scripts Generados",
          dropLabel: "Descartados 287",
          dropDetail: "Error AST / Lookahead",
          selected: selectedStage === "Ideados",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-testeados",
        type: "pipelineStage",
        position: { x: 735, y: 100 },
        data: {
          stepNumber: 4,
          label: "Testeados",
          count: "1,252",
          subtitle: "Motor Backtest",
          isActive: true,
          dropLabel: "Caídos en el filtro 908",
          dropDetail: "Sharpe < 1.6 • DD > 4.5%",
          selected: selectedStage === "Testeados",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-filtro",
        type: "pipelineStage",
        position: { x: 915, y: 100 },
        data: {
          stepNumber: 5,
          label: "Por el Filtro",
          count: "343",
          subtitle: "Supervivientes",
          dropLabel: "Descartados OOS 331",
          dropDetail: "Fallo Walk-Forward",
          selected: selectedStage === "Por el Filtro",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-aprobados",
        type: "pipelineStage",
        position: { x: 1090, y: 100 },
        data: {
          stepNumber: 6,
          label: "Aprobados",
          count: "12",
          subtitle: "Validación Humana",
          dropLabel: "En Cola 9",
          dropDetail: "Correlación Cartera",
          selected: selectedStage === "Aprobados",
          onSelect: onSelectStage
        }
      },
      {
        id: "st-paper",
        type: "pipelineStage",
        position: { x: 1260, y: 100 },
        data: {
          stepNumber: 7,
          label: "En Mercado",
          count: "3",
          subtitle: "Ejecución Activa",
          isFinal: true,
          dropLabel: "CME Globex En Vivo",
          dropDetail: "ES • NQ • GC",
          selected: selectedStage === "En Mercado",
          onSelect: onSelectStage
        }
      }
    ],
    [selectedStage, onSelectStage]
  );

  const edges: Edge[] = useMemo(
    () => [
      {
        id: "e-yt-gel",
        source: "src-youtube",
        target: "st-leidos",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 1.6 }
      },
      {
        id: "e-gh-gel",
        source: "src-github",
        target: "st-leidos",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 1.6 }
      },
      {
        id: "e-ax-gel",
        source: "src-arxiv",
        target: "st-leidos",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 1.6 }
      },
      {
        id: "e-wb-gel",
        source: "src-web",
        target: "st-leidos",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 1.6 }
      },

      {
        id: "e-1-2",
        source: "st-leidos",
        target: "st-resumidos",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 2 },
        label: "-6",
        labelStyle: { fill: "#64748b", fontFamily: "JetBrains Mono", fontSize: 9 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.9 }
      },
      {
        id: "e-2-3",
        source: "st-resumidos",
        target: "st-ideados",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 2 },
        label: "×3.2",
        labelStyle: { fill: "#22d3ee", fontFamily: "JetBrains Mono", fontSize: 9 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.9 }
      },
      {
        id: "e-3-4",
        source: "st-ideados",
        target: "st-testeados",
        type: "smoothstep",
        animated: true,
        style: { stroke: "#22d3ee", strokeWidth: 2.2 },
        label: "Descartados 287",
        labelStyle: { fill: "#94a3b8", fontFamily: "JetBrains Mono", fontSize: 9 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.95 }
      },
      {
        id: "e-4-5",
        source: "st-testeados",
        target: "st-filtro",
        type: "smoothstep",
        animated: true,
        style: { stroke: "#22d3ee", strokeWidth: 2.2 },
        label: "-908",
        labelStyle: { fill: "#eab308", fontFamily: "JetBrains Mono", fontSize: 9, fontWeight: 700 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.95 }
      },
      {
        id: "e-5-6",
        source: "st-filtro",
        target: "st-aprobados",
        type: "smoothstep",
        style: { stroke: "#334155", strokeWidth: 2 },
        label: "-331",
        labelStyle: { fill: "#64748b", fontFamily: "JetBrains Mono", fontSize: 9 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.9 }
      },
      {
        id: "e-6-7",
        source: "st-aprobados",
        target: "st-paper",
        type: "smoothstep",
        style: { stroke: "#4ade80", strokeWidth: 2.2 },
        label: "3 En Vivo",
        labelStyle: { fill: "#4ade80", fontFamily: "JetBrains Mono", fontSize: 9, fontWeight: 700 },
        labelBgStyle: { fill: "#0a0b10", fillOpacity: 0.95 }
      }
    ],
    []
  );

  useEffect(() => {
    const handleResize = () => {
      fitView({ padding: 0.08, duration: 200 });
    };
    window.addEventListener("resize", handleResize);
    const id = setTimeout(handleResize, 80);
    return () => {
      window.removeEventListener("resize", handleResize);
      clearTimeout(id);
    };
  }, [fitView]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ padding: 0.08 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={true}
      zoomOnScroll={false}
      zoomOnPinch={false}
      zoomOnDoubleClick={false}
      panOnDrag={false}
      panOnScroll={false}
      proOptions={{ hideAttribution: true }}
      className="!bg-[#0a0b10]"
    />
  );
}

interface DecisionTaskCard {
  id: string;
  category: string;
  title: string;
  subtitle: string;
  metricsTag: string;
  agentAuthor: string;
}

const INITIAL_DECISION_CARDS: DecisionTaskCard[] = [
  {
    id: "TASK-01",
    category: "PROMOCIÓN DE ESTRATEGIA",
    title: "Seguidor-Tendencia ES-4h",
    subtitle:
      "Sharpe OOS 1.84. Trabaja bien con NQ y mantiene baja correlación (0.19) en sesiones de alta volatilidad.",
    metricsTag: "PF 2.18 • MaxDD -1.92% • 194 Trades",
    agentAuthor: "ORION-v4"
  },
  {
    id: "TASK-02",
    category: "PROPUESTA DE MEJORA",
    title: "Regla: Anticipar filtro de Rollover",
    subtitle:
      "41 estrategias pasaron el test tras adelantar el filtro de rollover CME 48h antes del vencimiento trimestral.",
    metricsTag: "Delta Sharpe: +0.24 • Slippage -18%",
    agentAuthor: "SENTINEL"
  }
];

export function ViewBHorizontalPipeline() {
  const [selectedStage, setSelectedStage] = useState<string>("Testeados");
  const [resolvedTasks, setResolvedTasks] = useState<Record<string, "APROBADO" | "RECHAZADO">>({});
  const [actionBanner, setActionBanner] = useState<string | null>(null);

  const pendingCount = INITIAL_DECISION_CARDS.filter((c) => !resolvedTasks[c.id]).length;

  function handleCardAction(card: DecisionTaskCard, action: "APROBADO" | "RECHAZADO") {
    setResolvedTasks((prev) => ({
      ...prev,
      [card.id]: action
    }));
    setActionBanner(
      action === "APROBADO"
        ? `✓ "${card.title}" promovido a Paper Trading / Ejecución activa.`
        : `↩ "${card.title}" devuelto al nodo Ideados para re-optimización.`
    );
  }

  return (
    <div className="grid h-full min-h-0 w-full grid-cols-1 gap-3 lg:grid-cols-12">
      {/* CONTENEDOR IZQUIERDO (80% ANCHO): REACT FLOW PIPELINE */}
      <div className="flex min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3.5 lg:col-span-9 xl:col-span-9">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2.5">
          <div>
            <div className="flex items-center gap-2">
              <GitBranch className="h-3.5 w-3.5 text-[#22d3ee]" />
              <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                PIPELINE AUTÓNOMO DE ESTRATEGIAS — DE LA FUENTE A EJECUCIÓN REAL
              </h2>
            </div>
            <p className="mt-0.5 font-mono text-[10px] text-slate-400">
              Convergencia de 4 fuentes de ingesta (407 ítems) → Generación multi-hipótesis (1,308) → Criba cuantitativa IS/OOS
            </p>
          </div>

          <div className="flex items-center gap-2 font-mono text-[10px]">
            <span className="flex items-center gap-1.5 rounded border border-[#22d3ee]/30 bg-[#22d3ee]/10 px-2.5 py-1 text-[#22d3ee]">
              <span className="h-2 w-2 animate-ping rounded-full bg-[#22d3ee]" />
              Nodo Activo: <strong>{selectedStage}</strong>
            </span>
            <span className="hidden rounded border border-[#1f222d] bg-[#030407] px-2.5 py-1 text-slate-400 sm:inline">
              Conversión Total: <strong className="text-[#4ade80]">0.73%</strong>
            </span>
          </div>
        </div>

        <div className="relative my-2 min-h-0 flex-1 overflow-hidden rounded border border-[#1f222d]/60 bg-[#0a0b10]">
          <div className="pointer-events-none absolute inset-x-4 top-2.5 z-10 flex items-center justify-between font-mono text-[9px] uppercase tracking-widest text-slate-500">
            <span>1. INGESTA FUENTES (407)</span>
            <span>2. SÍNTESIS E IDEACIÓN (1,308)</span>
            <span className="text-[#22d3ee]">3. BACKTEST Y FILTRO (343)</span>
            <span className="text-[#4ade80]">4. VALIDACIÓN Y MERCADO (3)</span>
          </div>

          <ReactFlowProvider>
            <PipelineFlowCanvas
              selectedStage={selectedStage}
              onSelectStage={setSelectedStage}
            />
          </ReactFlowProvider>
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-2 border-t border-[#1f222d] pt-2.5 font-mono text-[10px] sm:grid-cols-4">
          <div className="flex items-center justify-between rounded border border-[#1f222d] bg-[#050609] px-2.5 py-1.5">
            <span className="text-slate-500">FUENTES TOTALES:</span>
            <span className="font-bold text-slate-200">407 Leídos</span>
          </div>
          <div className="flex items-center justify-between rounded border border-[#1f222d] bg-[#050609] px-2.5 py-1.5">
            <span className="text-slate-500">IDEADOS → TESTEADOS:</span>
            <span className="font-bold text-slate-300">Descartados 287</span>
          </div>
          <div className="flex items-center justify-between rounded border border-[#1f222d] bg-[#050609] px-2.5 py-1.5">
            <span className="text-slate-500">TESTEADOS → FILTRO:</span>
            <span className="font-bold text-[#eab308]">Descartados 908</span>
          </div>
          <div className="flex items-center justify-between rounded border border-[#1f222d] bg-[#050609] px-2.5 py-1.5">
            <span className="text-slate-500">EN MERCADO (LIVE):</span>
            <span className="font-bold text-[#4ade80]">3 Bots Activos</span>
          </div>
        </div>
      </div>

      {/* CONTENEDOR DERECHO (20% ANCHO): PANEL "TUS DECISIONES" */}
      <aside className="flex min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3.5 lg:col-span-3 xl:col-span-3">
        <div>
          <div className="flex items-center justify-between border-b border-[#1f222d] pb-2.5">
            <div>
              <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                TUS DECISIONES
              </h2>
              <p className="mt-0.5 font-mono text-[9px] text-slate-500">
                Autorización Human-in-the-Loop
              </p>
            </div>
            <span
              className={`rounded border px-2 py-0.5 font-mono text-[10px] font-extrabold ${
                pendingCount > 0
                  ? "border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]"
                  : "border-[#4ade80]/40 bg-[#4ade80]/10 text-[#4ade80]"
              }`}
            >
              {pendingCount} EN ESPERA
            </span>
          </div>

          {actionBanner && (
            <div className="mt-2.5 flex items-center justify-between gap-2 rounded border border-[#22d3ee]/30 bg-[#050609] px-2.5 py-1.5 font-mono text-[10px] text-[#22d3ee]">
              <span className="truncate">{actionBanner}</span>
              {Object.keys(resolvedTasks).length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setResolvedTasks({});
                    setActionBanner(null);
                  }}
                  className="shrink-0 text-slate-400 hover:text-white"
                  title="Restaurar tarjetas"
                >
                  <RotateCcw className="h-3 w-3" />
                </button>
              )}
            </div>
          )}
        </div>

        <div className="my-2.5 flex-1 space-y-3 overflow-y-auto pr-0.5">
          {INITIAL_DECISION_CARDS.map((card) => {
            const status = resolvedTasks[card.id];
            return (
              <div
                key={card.id}
                className={`flex flex-col justify-between rounded-lg border p-3 transition-all ${
                  status === "APROBADO"
                    ? "border-[#4ade80]/40 bg-[#050d08]"
                    : status === "RECHAZADO"
                    ? "border-[#334155]/60 bg-[#050609] opacity-65"
                    : "border-[#1f222d] bg-[#050609]"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between font-mono text-[9px]">
                    <span className="uppercase tracking-wider text-[#22d3ee]">
                      {card.category}
                    </span>
                    <span className="text-slate-500">{card.agentAuthor}</span>
                  </div>

                  <h3 className="mt-1 font-mono text-xs font-bold leading-snug text-slate-100">
                    {card.title}
                  </h3>

                  <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
                    {card.subtitle}
                  </p>

                  <div className="mt-2 rounded border border-[#1f222d] bg-[#0a0b10] px-2 py-1 font-mono text-[9px] text-slate-300">
                    {card.metricsTag}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleCardAction(card, "APROBADO")}
                    className={`flex items-center justify-center rounded border py-1.5 font-mono text-[10px] font-bold transition ${
                      status === "APROBADO"
                        ? "border-[#4ade80] bg-[#4ade80]/20 text-[#4ade80]"
                        : "border-[#4ade80] bg-[#030407] text-[#4ade80] hover:bg-[#4ade80]/15 hover:shadow-[0_0_14px_rgba(74,222,128,0.28)]"
                    }`}
                  >
                    [Aprobar]
                  </button>

                  <button
                    type="button"
                    onClick={() => handleCardAction(card, "RECHAZADO")}
                    className={`flex items-center justify-center rounded border py-1.5 font-mono text-[10px] font-bold transition ${
                      status === "RECHAZADO"
                        ? "border-slate-500 bg-slate-800/60 text-slate-300"
                        : "border-[#334155] bg-[#030407] text-slate-400 hover:border-slate-400 hover:text-slate-200"
                    }`}
                  >
                    [Rechazar]
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <div className="border-t border-[#1f222d] pt-2.5 font-mono text-[9px] text-slate-500">
          <div className="flex items-center justify-between">
            <span>Umbral Auto-Gate:</span>
            <span className="text-slate-300">Sharpe OOS &gt; 1.80</span>
          </div>
        </div>
      </aside>
    </div>
  );
}
