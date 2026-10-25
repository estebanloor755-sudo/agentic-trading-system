"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp
} from "lightweight-charts";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  FileCode2,
  Sparkles,
  X
} from "lucide-react";

interface SetupCandle {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface DetectedSetupSample {
  id: number;
  symbol: string;
  timeframe: string;
  session: string;
  dateLabel: string;
  fvgTop: number;
  fvgBottom: number;
  fvgStartIdx: number;
  fvgEndIdx: number;
  sweepIdx: number;
  impulseIdx: number;
  chochIdx: number;
  rrRatio: string;
  confidence: number;
  candles: SetupCandle[];
}

function buildDetectedSamples(): DetectedSetupSample[] {
  const baseTimestamp = 1729866600;

  const rawPattern: Array<[number, number, number, number]> = [
    [5851.0, 5852.25, 5848.5, 5849.0],
    [5849.0, 5850.0, 5846.75, 5847.25],
    [5847.25, 5848.5, 5845.0, 5845.5],
    [5845.5, 5847.0, 5844.25, 5846.25],
    [5846.25, 5846.75, 5842.5, 5843.0],
    [5843.0, 5844.0, 5840.75, 5841.25],
    [5841.25, 5842.5, 5839.5, 5840.0],
    [5840.0, 5841.75, 5838.75, 5841.0],
    [5841.0, 5841.5, 5837.5, 5838.0],
    [5838.0, 5839.0, 5836.25, 5836.75],
    [5836.75, 5839.25, 5833.5, 5838.75],
    [5838.75, 5841.5, 5838.0, 5841.0],
    [5841.0, 5848.25, 5840.75, 5847.75],
    [5847.75, 5850.5, 5845.75, 5849.5],
    [5849.5, 5851.25, 5847.5, 5848.25],
    [5848.25, 5848.75, 5845.25, 5845.75],
    [5845.75, 5847.5, 5842.75, 5846.75],
    [5846.75, 5852.75, 5846.25, 5852.25],
    [5852.25, 5854.5, 5851.0, 5853.75],
    [5853.75, 5855.0, 5852.0, 5852.75],
    [5852.75, 5856.25, 5852.25, 5855.75],
    [5855.75, 5858.0, 5854.75, 5857.25],
    [5857.25, 5858.5, 5855.5, 5856.25],
    [5856.25, 5859.75, 5855.75, 5859.25],
    [5859.25, 5861.5, 5858.25, 5860.75],
    [5860.75, 5862.25, 5859.5, 5860.25],
    [5860.25, 5863.5, 5859.75, 5862.75],
    [5862.75, 5864.75, 5861.5, 5864.25],
    [5864.25, 5866.0, 5863.25, 5865.5],
    [5865.5, 5867.25, 5864.5, 5866.75]
  ];

  return Array.from({ length: 12 }, (_, sampleIndex) => {
    const offset = sampleIndex * 12.5;
    const candles: SetupCandle[] = rawPattern.map(([o, h, l, c], i) => ({
      time: (baseTimestamp + sampleIndex * 86400 + i * 300) as UTCTimestamp,
      open: Number((o + offset).toFixed(2)),
      high: Number((h + offset).toFixed(2)),
      low: Number((l + offset).toFixed(2)),
      close: Number((c + offset).toFixed(2))
    }));

    return {
      id: sampleIndex + 1,
      symbol: "ES (E-mini S&P 500)",
      timeframe: "5m",
      session: "Sesión NY (09:30 - 11:00 EST)",
      dateLabel: `2026-10-${String(12 + sampleIndex).padStart(2, "0")} • CME Globex`,
      fvgBottom: Number((5841.5 + offset).toFixed(2)),
      fvgTop: Number((5845.75 + offset).toFixed(2)),
      fvgStartIdx: 11,
      fvgEndIdx: 22,
      sweepIdx: 10,
      impulseIdx: 12,
      chochIdx: 17,
      rrRatio: "1 : 3.2",
      confidence: 94 - (sampleIndex % 3) * 2,
      candles
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
  const samples = useMemo(() => buildDetectedSamples(), []);
  const [currentSampleIdx, setCurrentSampleIdx] = useState<number>(0);
  const [exclusionNote, setExclusionNote] = useState<string>(
    "Solo operar en Sesión NY (09:30 - 11:30 EST), excluir minutos previos a CPI/FOMC"
  );
  const [decisions, setDecisions] = useState<
    Record<number, "CORRECTO" | "INCORRECTO">
  >({});
  const [lastFeedback, setLastFeedback] = useState<string | null>(null);

  const [fvgBox, setFvgBox] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
    visible: boolean;
  }>({ left: 0, top: 0, width: 0, height: 0, visible: false });

  const [hoveredCandle, setHoveredCandle] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
  } | null>(null);

  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const seriesInstanceRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const currentSample = samples[currentSampleIdx] ?? samples[0];
  const currentDecision = decisions[currentSample.id];

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#0a0b10" },
        textColor: "#64748b",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false }
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "#334155",
          width: 1,
          style: 2,
          labelBackgroundColor: "#1e293b"
        },
        horzLine: {
          color: "#334155",
          width: 1,
          style: 2,
          labelBackgroundColor: "#1e293b"
        }
      },
      rightPriceScale: {
        borderColor: "#1f222d",
        scaleMargins: {
          top: 0.14,
          bottom: 0.14
        }
      },
      timeScale: {
        borderColor: "#1f222d",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
        barSpacing: 14
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#cbd5e1",
      downColor: "#161923",
      borderUpColor: "#f8fafc",
      borderDownColor: "#475569",
      wickUpColor: "#94a3b8",
      wickDownColor: "#475569"
    });

    chartInstanceRef.current = chart;
    seriesInstanceRef.current = candleSeries;

    const candles = currentSample.candles as CandlestickData<Time>[];
    candleSeries.setData(candles);

    const markers: SeriesMarker<Time>[] = [
      {
        time: currentSample.candles[currentSample.sweepIdx].time as Time,
        position: "belowBar",
        color: "#eab308",
        shape: "arrowUp",
        text: "1. BARRIDO LIQ"
      },
      {
        time: currentSample.candles[currentSample.impulseIdx].time as Time,
        position: "aboveBar",
        color: "#22d3ee",
        shape: "circle",
        text: "2. IMPULSO FVG"
      },
      {
        time: currentSample.candles[currentSample.chochIdx].time as Time,
        position: "belowBar",
        color: "#4ade80",
        shape: "arrowUp",
        text: "3. CHoCH + ENTRADA"
      }
    ];
    candleSeries.setMarkers(markers);

    chart.timeScale().fitContent();

    const syncFvgOverlay = () => {
      if (
        !chartInstanceRef.current ||
        !seriesInstanceRef.current ||
        !chartContainerRef.current
      ) {
        return;
      }
      const startCandle = currentSample.candles[currentSample.fvgStartIdx];
      const endCandle = currentSample.candles[currentSample.fvgEndIdx];
      if (!startCandle || !endCandle) return;

      const x1 = chart.timeScale().timeToCoordinate(startCandle.time as Time);
      const x2 = chart.timeScale().timeToCoordinate(endCandle.time as Time);
      const yTop = candleSeries.priceToCoordinate(currentSample.fvgTop);
      const yBottom = candleSeries.priceToCoordinate(currentSample.fvgBottom);

      if (x1 === null || x2 === null || yTop === null || yBottom === null) {
        setFvgBox((prev) => ({ ...prev, visible: false }));
        return;
      }

      const left = Math.min(x1, x2);
      const width = Math.max(24, Math.abs(x2 - x1));
      const top = Math.min(yTop, yBottom);
      const height = Math.max(12, Math.abs(yBottom - yTop));

      setFvgBox({
        left,
        top,
        width,
        height,
        visible: true
      });
    };

    const timer = setTimeout(syncFvgOverlay, 50);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncFvgOverlay);
    chart.timeScale().subscribeVisibleTimeRangeChange(syncFvgOverlay);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setHoveredCandle(null);
        return;
      }
      const data = param.seriesData.get(candleSeries) as
        | CandlestickData<Time>
        | undefined;
      if (data) {
        setHoveredCandle({
          open: data.open,
          high: data.high,
          low: data.low,
          close: data.close
        });
      }
    });

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          chart.applyOptions({ width, height });
          syncFvgOverlay();
        }
      }
    });

    resizeObserver.observe(container);

    return () => {
      clearTimeout(timer);
      resizeObserver.disconnect();
      chart.remove();
      chartInstanceRef.current = null;
      seriesInstanceRef.current = null;
    };
  }, [currentSample]);

  function handleDecision(verdict: "CORRECTO" | "INCORRECTO") {
    const setupId = `FVG_NQ_${122 + currentSample.id}`;
    const wsDecision = verdict === "CORRECTO" ? "APPROVED" : "REJECTED";
    const sentViaWs = onValidateSetup?.(setupId, wsDecision, exclusionNote);

    setDecisions((prev) => ({
      ...prev,
      [currentSample.id]: verdict
    }));
    setLastFeedback(
      verdict === "CORRECTO"
        ? `WS Payload enviado {"action":"human_validation","setup_id":"${setupId}","decision":"APPROVED"} ${
            sentViaWs ? "(ACK Python :4100)" : "(Cola Local)"
          }`
        : `WS Payload enviado {"action":"human_validation","setup_id":"${setupId}","decision":"REJECTED"} ${
            sentViaWs ? "(ACK Python :4100)" : "(Cola Local)"
          }`
    );
    setTimeout(() => {
      setCurrentSampleIdx((prev) => (prev + 1) % samples.length);
    }, 450);
  }

  const lastCandle = currentSample.candles[currentSample.candles.length - 1];
  const displayCandle = hoveredCandle ?? lastCandle;
  const approvedCount = Object.values(decisions).filter(
    (d) => d === "CORRECTO"
  ).length;
  const rejectedCount = Object.values(decisions).filter(
    (d) => d === "INCORRECTO"
  ).length;

  return (
    <div className="grid h-full min-h-0 w-full grid-cols-1 gap-3 lg:grid-cols-12">
      {/* COLUMNA IZQUIERDA (7 COLS): AUDITORÍA VISUAL (LIGHTWEIGHT CHARTS) */}
      <div className="flex min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3 lg:col-span-7">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded border border-[#22d3ee]/40 bg-[#22d3ee]/10">
              <Crosshair className="h-3.5 w-3.5 text-[#22d3ee]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-100">
                  {currentSample.symbol} • {currentSample.timeframe}
                </h2>
                <span className="rounded border border-[#22d3ee]/30 bg-[#22d3ee]/10 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#22d3ee]">
                  SETUP FVG + CHoCH #{currentSample.id}/12
                </span>
              </div>
              <p className="font-mono text-[10px] text-slate-400">
                {currentSample.dateLabel} • {currentSample.session}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 font-mono text-[10px]">
            <button
              type="button"
              onClick={() =>
                setCurrentSampleIdx(
                  (prev) => (prev - 1 + samples.length) % samples.length
                )
              }
              className="flex h-6 w-6 items-center justify-center rounded border border-[#1f222d] bg-[#030407] text-slate-400 hover:border-[#22d3ee]/40 hover:text-white"
              title="Ejemplo anterior"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span className="rounded border border-[#1f222d] bg-[#030407] px-2.5 py-1 text-slate-300">
              Ejemplo <strong className="text-[#4ade80]">{currentSample.id}</strong> / 12
            </span>
            <button
              type="button"
              onClick={() =>
                setCurrentSampleIdx((prev) => (prev + 1) % samples.length)
              }
              className="flex h-6 w-6 items-center justify-center rounded border border-[#1f222d] bg-[#030407] text-slate-400 hover:border-[#22d3ee]/40 hover:text-white"
              title="Siguiente ejemplo"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="relative my-2 min-h-0 flex-1 overflow-hidden rounded border border-[#1f222d]/80 bg-[#0a0b10]">
          <div className="pointer-events-none absolute left-3 top-2.5 z-20 flex flex-wrap items-center gap-3 rounded border border-[#1f222d] bg-[#050608]/90 px-2.5 py-1 font-mono text-[10px]">
            <span className="text-slate-400">
              A <strong className="text-slate-200">{displayCandle.open.toFixed(2)}</strong>
            </span>
            <span className="text-slate-400">
              M <strong className="text-slate-200">{displayCandle.high.toFixed(2)}</strong>
            </span>
            <span className="text-slate-400">
              m <strong className="text-slate-200">{displayCandle.low.toFixed(2)}</strong>
            </span>
            <span className="text-slate-400">
              C <strong className="text-[#4ade80]">{displayCandle.close.toFixed(2)}</strong>
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-[#22d3ee]">
              Zona FVG: {currentSample.fvgBottom.toFixed(2)} –{" "}
              {currentSample.fvgTop.toFixed(2)}
            </span>
          </div>

          {currentDecision && (
            <div
              className={`pointer-events-none absolute right-16 top-2.5 z-20 rounded border px-2.5 py-1 font-mono text-[10px] font-bold ${
                currentDecision === "CORRECTO"
                  ? "border-[#4ade80]/50 bg-[#4ade80]/15 text-[#4ade80]"
                  : "border-slate-500 bg-slate-800/80 text-slate-300"
              }`}
            >
              {currentDecision === "CORRECTO"
                ? "✓ VALIDADO: CORRECTO"
                : "✕ RECHAZADO: INCORRECTO"}
            </div>
          )}

          {fvgBox.visible && (
            <div
              style={{
                left: `${fvgBox.left}px`,
                top: `${fvgBox.top}px`,
                width: `${fvgBox.width}px`,
                height: `${fvgBox.height}px`
              }}
              className="pointer-events-none absolute z-10 rounded-sm border border-[#22d3ee]/45 bg-[#22d3ee]/10 shadow-[0_0_20px_rgba(34,211,238,0.08)]"
            >
              <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-[#22d3ee]/50" />
              <div className="absolute -top-4 left-1.5 flex items-center gap-1.5 whitespace-nowrap rounded border border-[#22d3ee]/30 bg-[#050608]/95 px-1.5 py-0.5 font-mono text-[9px] font-bold text-[#22d3ee]">
                <span>ZONA FVG ALCISTA (17 Ticks)</span>
                <span className="text-slate-400">• Mitigación 50%</span>
              </div>
            </div>
          )}

          <div ref={chartContainerRef} className="h-full w-full" />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#1f222d] pt-2 font-mono text-[10px] text-slate-400">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-[#eab308]" />
              1. Barrido Liquidez
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-[#22d3ee]" />
              2. Desplazamiento FVG
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-[#4ade80]" />
              3. Mitigación CHoCH
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span>
              R:R Esperado:{" "}
              <strong className="text-[#4ade80]">{currentSample.rrRatio}</strong>
            </span>
            <span>
              Confianza IA:{" "}
              <strong className="text-[#22d3ee]">
                {currentSample.confidence}%
              </strong>
            </span>
          </div>
        </div>
      </div>

      {/* COLUMNA DERECHA (5 COLS): AUDITORÍA LÓGICA (CÓDIGO PYTHON & DECISIÓN) */}
      <div className="flex min-h-0 flex-col gap-3 lg:col-span-5">
        <div className="flex min-h-0 flex-[1.2] flex-col overflow-hidden rounded-lg border border-[#1f222d] bg-[#050608]">
          <div className="flex items-center justify-between border-b border-[#1f222d] bg-[#0a0b10] px-3 py-2">
            <div className="flex items-center gap-2">
              <FileCode2 className="h-3.5 w-3.5 text-[#22d3ee]" />
              <span className="font-mono text-xs font-bold text-slate-200">
                detector_fvg_liquidez.py
              </span>
              <span className="rounded bg-[#4ade80]/10 px-1.5 py-0.2 font-mono text-[9px] text-[#4ade80]">
                AST Validado
              </span>
            </div>
            <span className="font-mono text-[10px] text-slate-500">
              Python 3.11 • VectorBT
            </span>
          </div>

          <div className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
            <div className="grid grid-cols-[24px_1fr] gap-x-2">
              <span className="select-none text-right text-slate-600">01</span>
              <span>
                <span className="text-purple-400">import</span>{" "}
                <span className="text-slate-200">numpy</span>{" "}
                <span className="text-purple-400">as</span>{" "}
                <span className="text-slate-200">np</span>
              </span>

              <span className="select-none text-right text-slate-600">02</span>
              <span>
                <span className="text-purple-400">import</span>{" "}
                <span className="text-slate-200">pandas</span>{" "}
                <span className="text-purple-400">as</span>{" "}
                <span className="text-slate-200">pd</span>
              </span>

              <span className="select-none text-right text-slate-600">03</span>
              <span>&nbsp;</span>

              <span className="select-none text-right text-slate-600">04</span>
              <span>
                <span className="font-bold text-purple-400">def</span>{" "}
                <span className="font-bold text-[#22d3ee]">
                  detect_fair_value_gap
                </span>
                <span className="text-slate-300">(</span>
                <span className="text-amber-300">candles</span>
                <span className="text-slate-400">: pd.DataFrame, </span>
                <span className="text-amber-300">min_ticks</span>
                <span className="text-slate-300">=</span>
                <span className="text-[#4ade80]">2</span>
                <span className="text-slate-300">):</span>
              </span>

              <span className="select-none text-right text-slate-600">05</span>
              <span className="pl-4 italic text-slate-500">
                &quot;&quot;&quot;Detecta Fair Value Gap alcista + Choque de Liquidez en ES 5m.&quot;&quot;&quot;
              </span>

              <span className="select-none text-right text-slate-600">06</span>
              <span className="pl-4">
                <span className="text-slate-200">tick_size</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-[#4ade80]">0.25</span>{" "}
                <span className="text-slate-500"># Tick CME E-mini S&amp;P 500</span>
              </span>

              <span className="select-none text-right text-slate-600">07</span>
              <span className="pl-4">
                <span className="text-slate-200">min_gap</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-amber-300">min_ticks</span>{" "}
                <span className="text-[#22d3ee]">*</span>{" "}
                <span className="text-slate-200">tick_size</span>
              </span>

              <span className="select-none text-right text-slate-600">08</span>
              <span>&nbsp;</span>

              <span className="select-none text-right text-slate-600">09</span>
              <span className="pl-4 text-slate-500">
                # 1. Barrido de liquidez previo (Sell-Side Liquidity Sweep)
              </span>

              <span className="select-none text-right text-slate-600">10</span>
              <span className="pl-4">
                <span className="text-slate-200">prior_low</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-amber-300">candles</span>
                <span className="text-slate-300">[</span>
                <span className="text-[#eab308]">&apos;low&apos;</span>
                <span className="text-slate-300">].rolling(</span>
                <span className="text-[#4ade80]">10</span>
                <span className="text-slate-300">).min().shift(</span>
                <span className="text-[#4ade80]">3</span>
                <span className="text-slate-300">)</span>
              </span>

              <span className="select-none text-right text-slate-600">11</span>
              <span className="pl-4">
                <span className="text-slate-200">liq_sweep</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-amber-300">candles</span>
                <span className="text-slate-300">[</span>
                <span className="text-[#eab308]">&apos;low&apos;</span>
                <span className="text-slate-300">].shift(</span>
                <span className="text-[#4ade80]">2</span>
                <span className="text-slate-300">) &lt; </span>
                <span className="text-slate-200">prior_low</span>
              </span>

              <span className="select-none text-right text-slate-600">12</span>
              <span>&nbsp;</span>

              <span className="select-none text-right text-slate-600">13</span>
              <span className="pl-4 text-slate-500">
                # 2. Ineficiencia de 3 velas (Bullish Fair Value Gap)
              </span>

              <span className="select-none text-right text-slate-600">14</span>
              <span className="pl-4">
                <span className="text-slate-200">candle_1_high</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-amber-300">candles</span>
                <span className="text-slate-300">[</span>
                <span className="text-[#eab308]">&apos;high&apos;</span>
                <span className="text-slate-300">].shift(</span>
                <span className="text-[#4ade80]">2</span>
                <span className="text-slate-300">)</span>
              </span>

              <span className="select-none text-right text-slate-600">15</span>
              <span className="pl-4">
                <span className="text-slate-200">candle_3_low</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-amber-300">candles</span>
                <span className="text-slate-300">[</span>
                <span className="text-[#eab308]">&apos;low&apos;</span>
                <span className="text-slate-300">]</span>
              </span>

              <span className="select-none text-right text-slate-600">16</span>
              <span className="pl-4">
                <span className="text-slate-200">fvg_size</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-slate-200">candle_3_low</span>{" "}
                <span className="text-[#22d3ee]">-</span>{" "}
                <span className="text-slate-200">candle_1_high</span>
              </span>

              <span className="select-none text-right text-slate-600">17</span>
              <span className="pl-4">
                <span className="text-slate-200">is_valid_fvg</span>{" "}
                <span className="text-[#22d3ee]">=</span>{" "}
                <span className="text-slate-200">fvg_size</span>{" "}
                <span className="text-[#22d3ee]">&gt;=</span>{" "}
                <span className="text-slate-200">min_gap</span>
              </span>

              <span className="select-none text-right text-slate-600">18</span>
              <span>&nbsp;</span>

              <span className="select-none text-right text-slate-600">19</span>
              <span className="pl-4">
                <span className="font-bold text-purple-400">return</span>{" "}
                <span className="text-slate-300">{"{"}</span>
                <span className="text-[#eab308]">&apos;signal&apos;</span>
                <span className="text-slate-300">
                  : liq_sweep &amp; is_valid_fvg,{" "}
                </span>
                <span className="text-[#eab308]">&apos;gap&apos;</span>
                <span className="text-slate-300">: fvg_size</span>
                <span className="text-slate-300">{"}"}</span>
              </span>
            </div>
          </div>
        </div>

        {/* BLOQUE INFERIOR: PANEL DE DECISIÓN "HUMAN-IN-THE-LOOP" */}
        <div className="flex shrink-0 flex-col justify-between gap-3 rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3.5">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-[#4ade80]/40 bg-[#4ade80]/10">
                <Sparkles className="h-3.5 w-3.5 text-[#4ade80]" />
              </div>
              <div>
                <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-[#22d3ee]">
                  AUDITORÍA DE SETUPS HUMAN-IN-THE-LOOP
                </span>
                <p className="mt-0.5 font-mono text-xs font-bold text-slate-100">
                  &quot;12 de 12 ejemplos encontrados en ES 5m. Choque de liquidez detectado.&quot;
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-1.5 font-mono text-[10px]">
              <span className="rounded border border-[#4ade80]/30 bg-[#4ade80]/10 px-1.5 py-0.5 text-[#4ade80]">
                ✓ {approvedCount}
              </span>
              <span className="rounded border border-slate-700 bg-slate-800/60 px-1.5 py-0.5 text-slate-400">
                ✕ {rejectedCount}
              </span>
            </div>
          </div>

          <div>
            <label
              htmlFor="exclusion-notes"
              className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-slate-400"
            >
              Notas de exclusión / Reglas de sesión para el Agente:
            </label>
            <input
              id="exclusion-notes"
              type="text"
              value={exclusionNote}
              onChange={(e) => setExclusionNote(e.target.value)}
              placeholder="Ej. Solo operar en Sesión NY..."
              className="h-8 w-full rounded border border-[#1f222d] bg-[#050608] px-2.5 font-mono text-[11px] text-slate-200 placeholder-slate-600 outline-none transition focus:border-[#22d3ee]/60"
            />
          </div>

          {lastFeedback && (
            <div className="rounded border border-[#1f222d] bg-[#050608] px-2.5 py-1 font-mono text-[10px] text-[#22d3ee]">
              {lastFeedback}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 pt-0.5">
            <button
              type="button"
              onClick={() => handleDecision("CORRECTO")}
              className="flex items-center justify-center gap-2 rounded-md border border-[#4ade80] bg-[#4ade80]/10 py-2.5 font-mono text-xs font-bold text-[#4ade80] shadow-[0_0_20px_rgba(74,222,128,0.12)] transition hover:bg-[#4ade80]/20 active:scale-[0.99]"
            >
              <Check className="h-4 w-4" />
              <span>[Correcto (Aprobar)]</span>
            </button>

            <button
              type="button"
              onClick={() => handleDecision("INCORRECTO")}
              className="flex items-center justify-center gap-2 rounded-md border border-[#334155] bg-[#0e1118] py-2.5 font-mono text-xs font-bold text-slate-300 transition hover:border-slate-500 hover:bg-[#161b26] hover:text-white active:scale-[0.99]"
            >
              <X className="h-4 w-4 text-slate-400" />
              <span>[Incorrecto (Rechazar)]</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
