"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  FlaskConical,
  GitMerge,
  LayoutDashboard,
  Pause,
  Play,
  Radio,
  RefreshCw,
  ShieldAlert,
  Terminal,
  Wifi,
  WifiOff,
  X,
  Zap
} from "lucide-react";
import { ViewCStrategiesSplit } from "../components/ViewCStrategiesSplit";
import { useQuantStream } from "../hooks/useQuantStream";

const ViewAParticleSphere = dynamic(
  () => import("../components/ViewAParticleSphere").then((m) => m.ViewAParticleSphere),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center rounded-lg border border-[#1f222d] bg-[#0a0b10] font-mono text-xs text-[#22d3ee]">
        Inicializando WebGL Núcleo 3D (1,900 partículas)...
      </div>
    )
  }
);

const ViewBHorizontalPipeline = dynamic(
  () => import("../components/ViewBHorizontalPipeline").then((m) => m.ViewBHorizontalPipeline),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center rounded-lg border border-[#1f222d] bg-[#0a0b10] font-mono text-xs text-[#22d3ee]">
        Cargando topología React Flow del Pipeline...
      </div>
    )
  }
);

const ViewDSetupValidator = dynamic(
  () => import("../components/ViewDSetupValidator").then((m) => m.ViewDSetupValidator),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center rounded-lg border border-[#1f222d] bg-[#0a0b10] font-mono text-xs text-[#22d3ee]">
        Montando motor TradingView Lightweight Charts...
      </div>
    )
  }
);

type SidebarSection = "resumen" | "investigacion" | "estrategias" | "conocimiento" | "envivo";
type CoreViewMode = "VIEW_A" | "VIEW_B" | "VIEW_C" | "VIEW_D" | "VIEW_E";

interface ExternalAuditResult {
  source: string;
  timestamp?: string;
  status: "OPTIMO" | "ADVERTENCIA" | "CRITICO";
  score: number;
  summary: string;
  checks: Array<{ module: string; state: string; detail: string }>;
  recommendations: string[];
}

export default function TradeBreinMasterApp() {
  const [activeSidebar, setActiveSidebar] = useState<SidebarSection>("estrategias");
  const [activeView, setActiveView] = useState<CoreViewMode>("VIEW_C");
  const [logsExpanded, setLogsExpanded] = useState<boolean>(false);
  const [logsPaused, setLogsPaused] = useState<boolean>(false);

  // Estado para el Auditor de IA Externa
  const [showAuditModal, setShowAuditModal] = useState<boolean>(false);
  const [isAuditing, setIsAuditing] = useState<boolean>(false);
  const [auditResult, setAuditResult] = useState<ExternalAuditResult | null>(null);

  const {
    lastTick,
    logs,
    connectionStatus,
    reconnectAttempt,
    sendHumanValidation
  } = useQuantStream();

  const consoleScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (logsPaused) return;
    if (consoleScrollRef.current) {
      consoleScrollRef.current.scrollTop = consoleScrollRef.current.scrollHeight;
    }
  }, [logs, logsExpanded, logsPaused]);

  const funnel = lastTick.funnel;
  const isWsConnected = connectionStatus === "CONNECTED";

  async function runExternalAiAudit() {
    setShowAuditModal(true);
    setIsAuditing(true);
    try {
      const res = await fetch("/api/ai-audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          wsConnected: isWsConnected,
          reconnectAttempt,
          hmmRegime: lastTick.hmm_regime,
          finbertScore: lastTick.finbert_score,
          funnel: lastTick.funnel,
          recentLogsCount: logs.length
        })
      });
      const data = (await res.json()) as ExternalAuditResult;
      setAuditResult(data);
    } catch {
      setAuditResult({
        source: "Auditor Local de Respaldo",
        status: "ADVERTENCIA",
        score: 80,
        summary: "No se pudo contactar la ruta /api/ai-audit, diagnóstico cliente completado.",
        checks: [],
        recommendations: ["Verificar conexión del servidor Next.js."]
      });
    } finally {
      setIsAuditing(false);
    }
  }

  const liveFunnelKpis = useMemo(() => {
    const readCount = Math.max(1, funnel.read);
    const testedPct = Math.min(100, Number(((funnel.tested / readCount) * 100).toFixed(1)));
    const passedPct = Math.min(100, Number(((funnel.passed / readCount) * 100).toFixed(1)));
    const approvedPct = Math.min(
      100,
      Math.max(4, Number(((funnel.approved / Math.max(1, funnel.passed)) * 100).toFixed(1)))
    );

    return [
      {
        id: "leidos",
        labelEs: "Leídos (Fuentes)",
        labelTag: "INGESTA",
        formatted: funnel.read.toLocaleString("en-US"),
        conversionPct: 100,
        barColor: "cyan" as const,
        subtext: "ArXiv • GitHub • YouTube • SSRN"
      },
      {
        id: "testeados",
        labelEs: "Testeados (En Backtest)",
        labelTag: "BACKTEST",
        formatted: funnel.tested.toLocaleString("en-US"),
        conversionPct: testedPct,
        barColor: "cyan" as const,
        subtext: `${testedPct}% compilados en motor vectorizado`
      },
      {
        id: "filtro",
        labelEs: "Por el Filtro (Supervivientes)",
        labelTag: "CRIBA IS",
        formatted: funnel.passed.toLocaleString("en-US"),
        conversionPct: passedPct,
        barColor: "cyan" as const,
        subtext: "Sharpe > 1.6 • DD < 4.5% • N > 150"
      },
      {
        id: "aprobados",
        labelEs: "Aprobados (Paper Trading)",
        labelTag: "VALIDADOS",
        formatted: funnel.approved.toLocaleString("en-US"),
        conversionPct: approvedPct,
        barColor: "mustard" as const,
        subtext: "OOS Walk-Forward + Human-in-the-Loop"
      },
      {
        id: "live",
        labelEs: "En Vivo (En el Mercado)",
        labelTag: "MERCADO",
        formatted: funnel.live.toLocaleString("en-US"),
        conversionPct: 6.5,
        barColor: "green" as const,
        subtext: "Ejecución DMA Activa • CME Globex"
      }
    ];
  }, [funnel]);

  const sidebarItems = useMemo(
    () => [
      {
        id: "resumen" as const,
        title: "Resumen",
        subtitle: "Núcleo 3D",
        defaultView: "VIEW_A" as const,
        icon: LayoutDashboard
      },
      {
        id: "investigacion" as const,
        title: "Investigación",
        subtitle: "Pipeline IA",
        defaultView: "VIEW_B" as const,
        icon: FlaskConical,
        badge: funnel.read.toLocaleString("en-US")
      },
      {
        id: "estrategias" as const,
        title: "Estrategias",
        subtitle: "Curvas IS/OOS",
        defaultView: "VIEW_C" as const,
        icon: GitMerge,
        badge: funnel.passed.toLocaleString("en-US")
      },
      {
        id: "conocimiento" as const,
        title: "Validador",
        subtitle: "Velas y Código",
        defaultView: "VIEW_D" as const,
        icon: BookOpen,
        badge: String(funnel.approved)
      },
      {
        id: "envivo" as const,
        title: "En Vivo (NQ MT5)",
        subtitle: "Terminal Anterior",
        defaultView: "VIEW_E" as const,
        icon: Radio,
        badge: String(funnel.live)
      }
    ],
    [funnel]
  );

  const latestLog = logs[logs.length - 1] ?? {
    id: "init",
    time: lastTick.timestamp,
    agent: "ORION",
    message: "Esperando flujo de telemetría en ws://localhost:4100...",
    level: "cyan"
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#030407] text-slate-200">
      {/* =====================================================================
          PASO 1: SIDEBAR IZQUIERDO COMPACTO (100% EN ESPAÑOL)
      ====================================================================== */}
      <aside
        aria-label="Navegación Principal"
        className="flex w-16 shrink-0 flex-col justify-between border-r border-[#1f222d] bg-[#0a0b10] py-3 xl:w-52 xl:px-2.5"
      >
        <div>
          <div className="flex items-center justify-center gap-2.5 border-b border-[#1f222d] px-1.5 pb-3 xl:justify-start">
            <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#4ade80]/40 bg-[#4ade80]/10 shadow-[0_0_15px_rgba(74,222,128,0.18)]">
              <Cpu className="h-4 w-4 text-[#4ade80]" />
              <span className="absolute -right-0.5 -top-0.5 h-2 w-2 animate-ping rounded-full bg-[#4ade80]" />
            </div>
            <div className="hidden min-w-0 xl:block">
              <div className="flex items-center gap-1.5">
                <span className="truncate font-mono text-xs font-bold tracking-wider text-white">
                  CEREBRO-QUANT
                </span>
                <span className="rounded bg-[#22d3ee]/15 px-1 py-0.2 font-mono text-[8px] font-bold text-[#22d3ee]">
                  v4.2
                </span>
              </div>
              <p className="truncate font-mono text-[9px] text-slate-500">
                Núcleo Cuantitativo Autónomo
              </p>
            </div>
          </div>

          <nav className="mt-3 flex flex-col gap-1">
            {sidebarItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeSidebar === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setActiveSidebar(item.id);
                    setActiveView(item.defaultView);
                  }}
                  className={`group flex items-center justify-center gap-2.5 rounded-md px-2.5 py-2 text-left transition-all xl:justify-start ${
                    isActive
                      ? "border border-[#1f222d] bg-[#121521] text-white shadow-[inset_2px_0_0_#4ade80]"
                      : "border border-transparent text-slate-400 hover:bg-[#0e1017] hover:text-slate-200"
                  }`}
                  title={`${item.title} (${item.subtitle})`}
                >
                  <Icon
                    className={`h-4 w-4 shrink-0 ${
                      isActive ? "text-[#4ade80]" : "text-slate-500 group-hover:text-[#22d3ee]"
                    }`}
                  />
                  <div className="hidden min-w-0 flex-1 xl:block">
                    <div className="flex items-center justify-between">
                      <span className="truncate text-xs font-semibold">{item.title}</span>
                      {item.badge && (
                        <span
                          className={`rounded px-1.5 py-0.2 font-mono text-[9px] font-bold ${
                            item.id === "envivo"
                              ? "bg-[#4ade80]/15 text-[#4ade80]"
                              : "bg-[#1f222d] text-slate-300"
                          }`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </div>
                    <p className="truncate font-mono text-[9px] text-slate-500">{item.subtitle}</p>
                  </div>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Estado del Motor y WebSocket */}
        <div className="space-y-2 border-t border-[#1f222d] pt-3">
          <div className="rounded-md border border-[#1f222d] bg-[#030407] p-2">
            <div className="flex items-center justify-center gap-2 xl:justify-start">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${
                  isWsConnected
                    ? "animate-pulse bg-[#4ade80] shadow-[0_0_8px_#4ade80]"
                    : "animate-ping bg-[#eab308]"
                }`}
              />
              <span className="hidden truncate font-mono text-[10px] font-bold text-[#4ade80] xl:inline">
                Motor en Marcha
              </span>
            </div>
            <div className="mt-1.5 hidden space-y-1 font-mono text-[9px] text-slate-400 xl:block">
              <div className="flex justify-between">
                <span>WS :4100:</span>
                <span className={isWsConnected ? "text-[#4ade80]" : "text-[#eab308]"}>
                  {isWsConnected ? "CONECTADO" : `REINTENTO #${reconnectAttempt}`}
                </span>
              </div>
              <div className="flex justify-between">
                <span>FinBERT:</span>
                <span className="text-[#22d3ee]">
                  {lastTick.finbert_score >= 0
                    ? `+${lastTick.finbert_score.toFixed(2)}`
                    : lastTick.finbert_score.toFixed(2)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      {/* =====================================================================
          CONTENEDOR DERECHO PRINCIPAL (100vh sin scroll del body)
      ====================================================================== */}
      <div className="flex h-screen min-w-0 flex-1 flex-col justify-between overflow-hidden">
        {/* TOP-BAR INSTITUCIONAL + BOTÓN AUDITORÍA IA EXTERNA + SELECTOR DE VISTAS */}
        <header className="flex h-11 shrink-0 items-center justify-between border-b border-[#1f222d] bg-[#0a0b10] px-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center gap-2">
              <Zap className="h-3.5 w-3.5 text-[#22d3ee]" />
              <span className="font-mono text-xs font-bold tracking-wider text-slate-100">
                JARVIS // MOTOR DE DESCUBRIMIENTO CUANTITATIVO
              </span>
            </div>

            <span className="hidden rounded border border-[#1f222d] bg-[#030407] px-2 py-0.5 font-mono text-[10px] text-slate-400 md:inline">
              Régimen HMM:{" "}
              <strong className="text-[#4ade80]">{lastTick.hmm_regime}</strong>
            </span>

            <span className="hidden rounded border border-[#1f222d] bg-[#030407] px-2 py-0.5 font-mono text-[10px] text-slate-400 lg:inline">
              FinBERT:{" "}
              <strong className="text-[#22d3ee]">
                {lastTick.finbert_score >= 0
                  ? `+${lastTick.finbert_score.toFixed(2)}`
                  : lastTick.finbert_score.toFixed(2)}
              </strong>
            </span>

            <span
              className={`hidden items-center gap-1 rounded border px-2 py-0.5 font-mono text-[9px] xl:flex ${
                isWsConnected
                  ? "border-[#4ade80]/30 bg-[#4ade80]/10 text-[#4ade80]"
                  : "border-[#eab308]/30 bg-[#eab308]/10 text-[#eab308]"
              }`}
            >
              {isWsConnected ? (
                <>
                  <Wifi className="h-2.5 w-2.5" />
                  <span>CONECTADO (:4100)</span>
                </>
              ) : (
                <>
                  <WifiOff className="h-2.5 w-2.5" />
                  <span>Reconectando #{reconnectAttempt}</span>
                </>
              )}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {/* Botón para disparar la Auditoría de IA Externa */}
            <button
              type="button"
              onClick={() => void runExternalAiAudit()}
              className="flex items-center gap-1.5 rounded-md border border-[#22d3ee]/40 bg-[#22d3ee]/10 px-2.5 py-1 font-mono text-[10px] font-bold text-[#22d3ee] transition hover:bg-[#22d3ee]/20"
              title="Analizar estado del sistema con IA Auditora Externa"
            >
              <Bot className="h-3.5 w-3.5" />
              <span>Auditoría IA</span>
            </button>

            {/* Conmutador de las 5 Vistas Dinámicas (incluye Trabajo Anterior NQ MT5) */}
            <div className="flex items-center gap-1 rounded-md border border-[#1f222d] bg-[#030407] p-0.5 font-mono text-[10px]">
              {(
                [
                  { id: "VIEW_A", label: "Vista A: Esfera 3D" },
                  { id: "VIEW_B", label: "Vista B: Pipeline" },
                  { id: "VIEW_C", label: "Vista C: Estrategias IS/OOS" },
                  { id: "VIEW_D", label: "Vista D: Validador" },
                  { id: "VIEW_E", label: "Vista E: Terminal NQ (Anterior)" }
                ] as const
              ).map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => setActiveView(v.id)}
                  className={`rounded px-2.5 py-1 transition ${
                    activeView === v.id
                      ? "border border-[#4ade80]/40 bg-[#4ade80]/15 font-bold text-[#4ade80]"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* ===================================================================
            PASO 2: STRIP DE KPIs SUPERIOR (100% EN ESPAÑOL)
        ==================================================================== */}
        <section
          aria-label="Embudo del Motor Agente en Vivo"
          className="grid shrink-0 grid-cols-2 gap-2 px-3 pt-2.5 md:grid-cols-5"
        >
          {liveFunnelKpis.map((kpi, idx) => {
            const accentText =
              kpi.barColor === "green"
                ? "text-[#4ade80]"
                : kpi.barColor === "mustard"
                ? "text-[#eab308]"
                : "text-slate-100";

            const barBg =
              kpi.barColor === "green"
                ? "bg-[#4ade80] shadow-[0_0_8px_#4ade80]"
                : kpi.barColor === "mustard"
                ? "bg-[#eab308]"
                : "bg-[#22d3ee]";

            return (
              <div
                key={kpi.id}
                className="relative flex flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] px-3.5 py-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[9px] font-semibold uppercase tracking-wider text-slate-400">
                    {idx + 1}. {kpi.labelEs}
                  </span>
                  <span className="font-mono text-[9px] text-slate-600">{kpi.labelTag}</span>
                </div>

                <div className="my-1 flex items-baseline justify-between">
                  <span
                    className={`font-mono text-2xl font-extrabold tracking-tight transition-all duration-150 lg:text-3xl ${accentText}`}
                  >
                    {kpi.formatted}
                  </span>
                  <span className="truncate pl-2 font-mono text-[10px] text-slate-500">
                    {kpi.subtext}
                  </span>
                </div>

                <div className="h-1 w-full overflow-hidden rounded-full bg-[#151824]">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${barBg}`}
                    style={{ width: `${kpi.conversionPct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </section>

        {/* ===================================================================
            PASO 3: EL CORE DE LA APP (Renderizado de las 5 Vistas Dinámicas)
        ==================================================================== */}
        <main className="min-h-0 flex-1 overflow-hidden px-3 py-2.5">
          {activeView === "VIEW_C" && <ViewCStrategiesSplit />}
          {activeView === "VIEW_A" && <ViewAParticleSphere />}
          {activeView === "VIEW_B" && <ViewBHorizontalPipeline />}
          {activeView === "VIEW_D" && (
            <ViewDSetupValidator onValidateSetup={sendHumanValidation} />
          )}
          {activeView === "VIEW_E" && (
            <div className="flex h-full w-full flex-col overflow-hidden rounded-lg border border-[#1f222d] bg-[#0a0b10]">
              <div className="flex items-center justify-between border-b border-[#1f222d] bg-[#030407] px-3.5 py-2 font-mono text-xs">
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#4ade80]" />
                  <span className="font-bold text-white">
                    TERMINAL NQ MT5 / SUPABASE (TRABAJO ANTERIOR INTEGRADO)
                  </span>
                  <span className="text-[10px] text-slate-400">
                    • Módulos preservados: backtest_engine.py, data_feed_nq.py, main_dashboard_nq.py, core/, models/, simulations/
                  </span>
                </div>
                <a
                  href="/nq-dashboard/index.html"
                  target="_blank"
                  rel="noreferrer"
                  className="rounded border border-[#22d3ee]/40 bg-[#22d3ee]/10 px-2.5 py-1 text-[10px] font-bold text-[#22d3ee] transition hover:bg-[#22d3ee]/20"
                >
                  Abrir Terminal NQ en Pantalla Completa ↗
                </a>
              </div>
              <iframe
                src="/nq-dashboard/index.html"
                title="Terminal Cuantitativa NQ Anterior"
                className="h-full w-full flex-1 border-0 bg-[#030407]"
              />
            </div>
          )}
        </main>

        {/* ===================================================================
            PASO 4: TERMINAL DE LOGS INFERIOR
        ==================================================================== */}
        <footer
          aria-label="Terminal de Agentes en Segundo Plano"
          className={`shrink-0 border-t border-[#1f222d] bg-[#020204] transition-all duration-200 ${
            logsExpanded ? "h-44" : "h-8"
          }`}
        >
          <div className="flex h-8 items-center justify-between px-3 font-mono text-[11px]">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <span className="flex items-center gap-1.5 text-[#4ade80]">
                <Terminal className="h-3.5 w-3.5" />
                <span className="font-bold">CONSOLA DE AGENTES</span>
              </span>
              <span className="text-slate-600">|</span>
              <span className="shrink-0 text-slate-500">{latestLog.time}</span>
              <span
                className={`shrink-0 font-bold ${
                  latestLog.level === "green"
                    ? "text-[#4ade80]"
                    : latestLog.level === "mustard"
                    ? "text-[#eab308]"
                    : "text-[#22d3ee]"
                }`}
              >
                {latestLog.agent}:
              </span>
              <span className="truncate text-slate-400">{latestLog.message}</span>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setLogsPaused(!logsPaused)}
                className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#0a0b10] px-1.5 py-0.5 text-[9px] text-slate-400 hover:text-white"
              >
                {logsPaused ? <Play className="h-2.5 w-2.5" /> : <Pause className="h-2.5 w-2.5" />}
                <span>{logsPaused ? "Reanudar" : "Auto-Scroll"}</span>
              </button>
              <button
                type="button"
                onClick={() => setLogsExpanded(!logsExpanded)}
                className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#0a0b10] px-1.5 py-0.5 text-[9px] text-slate-400 hover:text-white"
              >
                {logsExpanded ? (
                  <>
                    <ChevronDown className="h-3 w-3" />
                    <span>Colapsar</span>
                  </>
                ) : (
                  <>
                    <ChevronUp className="h-3 w-3" />
                    <span>Expandir ({logs.length})</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {logsExpanded && (
            <div
              ref={consoleScrollRef}
              className="h-36 space-y-1 overflow-y-auto border-t border-[#1f222d]/60 px-3 py-1.5 font-mono text-[11px] scroll-smooth"
            >
              {logs.map((entry) => (
                <div key={entry.id} className="flex items-center gap-2 leading-tight">
                  <span className="text-slate-600">{entry.time}</span>
                  <span
                    className={`w-20 shrink-0 font-bold ${
                      entry.level === "green"
                        ? "text-[#4ade80]"
                        : entry.level === "mustard"
                        ? "text-[#eab308]"
                        : "text-[#22d3ee]"
                    }`}
                  >
                    [{entry.agent}]
                  </span>
                  <span className="text-slate-400">{entry.message}</span>
                </div>
              ))}
            </div>
          )}
        </footer>
      </div>

      {/* =====================================================================
          MODAL DE AUDITORÍA IA EXTERNA (DIAGNÓSTICO DE FALLOS EN TIEMPO REAL)
      ====================================================================== */}
      {showAuditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-[#22d3ee]/40 bg-[#0a0b10] shadow-[0_0_50px_rgba(34,211,238,0.18)]">
            <div className="flex items-center justify-between border-b border-[#1f222d] bg-[#050609] px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Bot className="h-4 w-4 text-[#22d3ee]" />
                <div>
                  <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                    AUDITORÍA INDEPENDIENTE DE IA — DIAGNÓSTICO DE FALLOS Y SALUD
                  </h3>
                  <p className="font-mono text-[10px] text-slate-400">
                    {auditResult?.source ?? "Analizando telemetría, WebGL, WebSockets y sobreajuste OOS..."}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowAuditModal(false)}
                className="rounded border border-[#1f222d] p-1 text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4 font-mono text-xs">
              {isAuditing ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <RefreshCw className="h-6 w-6 animate-spin text-[#22d3ee]" />
                  <p className="mt-3 text-slate-300">
                    Ejecutando inspección externa de subsistemas...
                  </p>
                </div>
              ) : auditResult ? (
                <>
                  <div className="flex items-center justify-between rounded border border-[#1f222d] bg-[#050609] p-3">
                    <div>
                      <span className="text-[10px] uppercase text-slate-500">
                        ESTADO GLOBAL AUDITADO
                      </span>
                      <p className="mt-0.5 text-sm font-bold text-[#4ade80]">
                        {auditResult.status} — Score de Salud: {auditResult.score}/100
                      </p>
                    </div>
                    <span className="rounded border border-[#4ade80]/30 bg-[#4ade80]/10 px-2.5 py-1 text-[10px] font-bold text-[#4ade80]">
                      {auditResult.timestamp ?? "Tiempo Real"}
                    </span>
                  </div>

                  <p className="rounded border border-[#1f222d] bg-[#050609] p-3 text-[11px] leading-relaxed text-slate-300">
                    {auditResult.summary}
                  </p>

                  <div className="space-y-2">
                    <span className="block text-[10px] font-bold uppercase text-slate-400">
                      VERIFICACIÓN POR MÓDULO:
                    </span>
                    {auditResult.checks.map((chk, i) => (
                      <div
                        key={i}
                        className="rounded border border-[#1f222d] bg-[#050609] p-2.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-200">{chk.module}</span>
                          <span
                            className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${
                              chk.state === "OK"
                                ? "bg-[#4ade80]/15 text-[#4ade80]"
                                : "bg-[#eab308]/15 text-[#eab308]"
                            }`}
                          >
                            {chk.state}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-400">{chk.detail}</p>
                      </div>
                    ))}
                  </div>

                  <div className="rounded border border-[#22d3ee]/30 bg-[#22d3ee]/5 p-3">
                    <span className="block text-[10px] font-bold uppercase text-[#22d3ee]">
                      RECOMENDACIONES DEL AUDITOR:
                    </span>
                    <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[11px] text-slate-300">
                      {auditResult.recommendations.map((rec, i) => (
                        <li key={i}>{rec}</li>
                      ))}
                    </ul>
                  </div>
                </>
              ) : null}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[#1f222d] bg-[#050609] px-4 py-2.5 font-mono text-xs">
              <button
                type="button"
                onClick={() => void runExternalAiAudit()}
                className="rounded border border-[#22d3ee]/40 bg-[#22d3ee]/10 px-3 py-1.5 text-[11px] font-bold text-[#22d3ee] hover:bg-[#22d3ee]/20"
              >
                Re-Analizar Ahora
              </button>
              <button
                type="button"
                onClick={() => setShowAuditModal(false)}
                className="rounded border border-[#1f222d] bg-[#0a0b10] px-3 py-1.5 text-[11px] text-slate-300 hover:text-white"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
