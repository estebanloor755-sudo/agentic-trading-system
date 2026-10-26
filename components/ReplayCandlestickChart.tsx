"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  type IPriceLine
} from "lightweight-charts";
import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";

export interface ReplayCandleItem {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface ReplayPatternDataset {
  patternId: string;
  patternName: string;
  patternDutchName: string;
  symbol: string;
  timeframe: string;
  sessionLabel: string;
  candles: ReplayCandleItem[]; // 28 velas exactas
  lowerHighIdx: number; // ej. 6 (vela 7)
  lowerLowIdx: number; // ej. 10 (vela 11)
  fvgStartIdx: number; // ej. 12 (vela 13)
  fvgEndIdx: number; // ej. 24 (vela 25)
  fvgTop: number;
  fvgBottom: number;
  chochBreakIdx: number; // ej. 17 (vela 18)
  lowerHighPrice: number;
  lowerLowPrice: number;
  chochBreakPrice: number;
}

interface ReplayCandlestickChartProps {
  dataset: ReplayPatternDataset;
  decisionBadge?: "CORRECTO" | "INCORRECTO" | null;
}

export function ReplayCandlestickChart({
  dataset,
  decisionBadge
}: ReplayCandlestickChartProps) {
  const totalBars = dataset.candles.length; // 28
  const [visibleBars, setVisibleBars] = useState<number>(10);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [speedMs, setSpeedMs] = useState<number>(420);

  const [fvgOverlay, setFvgOverlay] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
    visible: boolean;
  }>({ left: 0, top: 0, width: 0, height: 0, visible: false });

  const [chochTagCoord, setChochTagCoord] = useState<{
    x: number;
    y: number;
    visible: boolean;
  }>({ x: 0, y: 0, visible: false });

  const [hoveredCandle, setHoveredCandle] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
  } | null>(null);

  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const seriesInstanceRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  // Resetear a vela 10 cuando cambia el patrón seleccionado en la taxonomía
  useEffect(() => {
    setIsPlaying(false);
    setVisibleBars(10);
  }, [dataset.patternId]);

  // Temporizador de reproducción vela a vela (Bar-by-Bar Replay)
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => {
      setVisibleBars((prev) => {
        if (prev >= totalBars) {
          setIsPlaying(false);
          return totalBars;
        }
        return prev + 1;
      });
    }, speedMs);

    return () => clearInterval(timer);
  }, [isPlaying, speedMs, totalBars]);

  // Inicialización del gráfico TradingView Lightweight Charts
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
          style: LineStyle.Dashed,
          labelBackgroundColor: "#1e293b"
        },
        horzLine: {
          color: "#334155",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#1e293b"
        }
      },
      rightPriceScale: {
        borderColor: "#1f222d",
        scaleMargins: {
          top: 0.16,
          bottom: 0.16
        }
      },
      timeScale: {
        borderColor: "#1f222d",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
        barSpacing: 13
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
        }
      }
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartInstanceRef.current = null;
      seriesInstanceRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  // Inyección dinámica de velas y anotaciones progresivas según visibleBars
  useEffect(() => {
    const chart = chartInstanceRef.current;
    const candleSeries = seriesInstanceRef.current;
    if (!chart || !candleSeries) return;

    const slicedCandles = dataset.candles.slice(
      0,
      visibleBars
    ) as CandlestickData<Time>[];
    candleSeries.setData(slicedCandles);

    // Limpiar líneas de precio previas
    for (const line of priceLinesRef.current) {
      try {
        candleSeries.removePriceLine(line);
      } catch {}
    }
    priceLinesRef.current = [];

    const dynamicMarkers: SeriesMarker<Time>[] = [];

    // 1. Anotación dinámica: Lower High (aparece cuando el replay alcanza lowerHighIdx + 1)
    if (visibleBars > dataset.lowerHighIdx) {
      const lhCandle = dataset.candles[dataset.lowerHighIdx];
      dynamicMarkers.push({
        time: lhCandle.time as Time,
        position: "aboveBar",
        color: "#94a3b8",
        shape: "circle",
        text: "Lower high (Máx. decreciente)"
      });

      const lhLine = candleSeries.createPriceLine({
        price: dataset.lowerHighPrice,
        color: "#64748b",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Lower high"
      });
      priceLinesRef.current.push(lhLine);
    }

    // 2. Anotación dinámica: Lower Low / Barrido (aparece cuando el replay alcanza lowerLowIdx + 1)
    if (visibleBars > dataset.lowerLowIdx) {
      const llCandle = dataset.candles[dataset.lowerLowIdx];
      dynamicMarkers.push({
        time: llCandle.time as Time,
        position: "belowBar",
        color: "#eab308",
        shape: "arrowUp",
        text: "Lower low (Sweep)"
      });

      const llLine = candleSeries.createPriceLine({
        price: dataset.lowerLowPrice,
        color: "#eab308",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Lower low"
      });
      priceLinesRef.current.push(llLine);
    }

    // 3. Anotación dinámica: Change of Character (CHoCH) en la vela de ruptura
    if (visibleBars > dataset.chochBreakIdx) {
      const chochCandle = dataset.candles[dataset.chochBreakIdx];
      dynamicMarkers.push({
        time: chochCandle.time as Time,
        position: "belowBar",
        color: "#4ade80",
        shape: "arrowUp",
        text: "Change of character (CHoCH)"
      });

      const chochLine = candleSeries.createPriceLine({
        price: dataset.chochBreakPrice,
        color: "#4ade80",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "CHoCH Break"
      });
      priceLinesRef.current.push(chochLine);
    }

    candleSeries.setMarkers(dynamicMarkers);

    // Sincronizar overlays flotantes (FVG Box y etiqueta CHoCH)
    const syncOverlays = () => {
      if (!chartInstanceRef.current || !seriesInstanceRef.current) return;

      // Overlay de zona FVG / Desplazamiento si ya se formó la vela fvgStartIdx
      if (visibleBars > dataset.fvgStartIdx + 1) {
        const startC = dataset.candles[dataset.fvgStartIdx];
        const endIdx = Math.min(visibleBars - 1, dataset.fvgEndIdx);
        const endC = dataset.candles[endIdx];

        const x1 = chart.timeScale().timeToCoordinate(startC.time as Time);
        const x2 = chart.timeScale().timeToCoordinate(endC.time as Time);
        const yTop = candleSeries.priceToCoordinate(dataset.fvgTop);
        const yBot = candleSeries.priceToCoordinate(dataset.fvgBottom);

        if (x1 !== null && x2 !== null && yTop !== null && yBot !== null) {
          setFvgOverlay({
            left: Math.min(x1, x2),
            top: Math.min(yTop, yBot),
            width: Math.max(28, Math.abs(x2 - x1)),
            height: Math.max(12, Math.abs(yBot - yTop)),
            visible: true
          });
        } else {
          setFvgOverlay((prev) => ({ ...prev, visible: false }));
        }
      } else {
        setFvgOverlay((prev) => ({ ...prev, visible: false }));
      }

      // Etiqueta flotante de ruptura CHoCH
      if (visibleBars > dataset.chochBreakIdx) {
        const chochC = dataset.candles[dataset.chochBreakIdx];
        const cx = chart.timeScale().timeToCoordinate(chochC.time as Time);
        const cy = candleSeries.priceToCoordinate(dataset.chochBreakPrice);
        if (cx !== null && cy !== null) {
          setChochTagCoord({ x: cx, y: cy, visible: true });
        } else {
          setChochTagCoord((prev) => ({ ...prev, visible: false }));
        }
      } else {
        setChochTagCoord((prev) => ({ ...prev, visible: false }));
      }
    };

    const id = setTimeout(syncOverlays, 30);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncOverlays);
    chart.timeScale().subscribeVisibleTimeRangeChange(syncOverlays);

    return () => {
      clearTimeout(id);
    };
  }, [dataset, visibleBars]);

  function handlePlayPause() {
    if (visibleBars >= totalBars) {
      setVisibleBars(5);
      setIsPlaying(true);
    } else {
      setIsPlaying((prev) => !prev);
    }
  }

  function handlePrevBar() {
    setIsPlaying(false);
    setVisibleBars((prev) => Math.max(3, prev - 1));
  }

  function handleNextBar() {
    setIsPlaying(false);
    setVisibleBars((prev) => Math.min(totalBars, prev + 1));
  }

  const currentLastCandle =
    dataset.candles[Math.max(0, visibleBars - 1)] ?? dataset.candles[0];
  const displayCandle = hoveredCandle ?? currentLastCandle;

  // Fase actual narrada por KRONOS según la vela visible
  const currentPhaseLabel =
    visibleBars <= dataset.lowerHighIdx
      ? "Fase 1/4: Impulso bajista previo formándose..."
      : visibleBars <= dataset.lowerLowIdx
      ? "Fase 2/4: Lower high confirmado (punteado gris)"
      : visibleBars <= dataset.chochBreakIdx
      ? "Fase 3/4: Lower low (Sweep) completado → Iniciando desplazamiento FVG"
      : "Fase 4/4: ¡Change of Character (CHoCH) confirmado al romper el Lower High!";

  return (
    <div className="flex h-full min-h-0 flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-2.5">
      {/* HEADER DEL REPLAY VELA A VELA */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-[#4ade80] shadow-[0_0_8px_#4ade80]" />
          <div>
            <h3 className="font-mono text-[11px] font-bold tracking-wide text-slate-100">
              • REPLAY — cómo se forma el patrón, vela a vela{" "}
              <span className="text-slate-500">
                (hoe het patroon zich vormt, kaars voor kaars)
              </span>
            </h3>
            <p className="font-mono text-[9px] text-[#22d3ee]">
              [KRONOS] {currentPhaseLabel}
            </p>
          </div>
        </div>

        {/* CONTROLES DE REPRODUCCIÓN ESTILO TERMINAL */}
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
          <button
            type="button"
            onClick={handlePlayPause}
            className={`flex items-center gap-1.5 rounded border px-2.5 py-1 font-bold transition ${
              isPlaying
                ? "border-[#eab308]/60 bg-[#eab308]/15 text-[#eab308]"
                : "border-[#4ade80]/60 bg-[#4ade80]/15 text-[#4ade80] hover:bg-[#4ade80]/25"
            }`}
          >
            {isPlaying ? (
              <>
                <Pause className="h-3 w-3" />
                <span>[Pausar]</span>
              </>
            ) : (
              <>
                <Play className="h-3 w-3" />
                <span>[Afspelen (Play)]</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handlePrevBar}
            disabled={visibleBars <= 3}
            className="rounded border border-[#1f222d] bg-[#030407] px-2 py-1 font-bold text-slate-300 transition hover:border-[#22d3ee]/50 hover:text-white disabled:opacity-40"
            title="Retroceder 1 vela"
          >
            [ &lt; ]
          </button>

          <button
            type="button"
            onClick={handleNextBar}
            disabled={visibleBars >= totalBars}
            className="rounded border border-[#1f222d] bg-[#030407] px-2 py-1 font-bold text-slate-300 transition hover:border-[#22d3ee]/50 hover:text-white disabled:opacity-40"
            title="Avanzar 1 vela"
          >
            [ &gt; ]
          </button>

          <button
            type="button"
            onClick={() => {
              setIsPlaying(false);
              setVisibleBars(6);
            }}
            className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-slate-400 hover:text-white"
            title="Reiniciar Replay desde la vela 6"
          >
            <RotateCcw className="h-3 w-3" />
          </button>

          <button
            type="button"
            onClick={() => {
              setIsPlaying(false);
              setVisibleBars(totalBars);
            }}
            className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-slate-400 hover:text-white"
            title="Ir a la vela 28 de 28"
          >
            <SkipForward className="h-3 w-3" />
          </button>

          {/* Selector de velocidad */}
          <button
            type="button"
            onClick={() =>
              setSpeedMs((s) => (s === 420 ? 200 : s === 200 ? 700 : 420))
            }
            className="rounded border border-[#1f222d] bg-[#030407] px-2 py-1 text-[9px] text-[#22d3ee]"
            title="Cambiar velocidad de reproducción"
          >
            {speedMs === 200 ? "2x" : speedMs === 700 ? "0.5x" : "1x"}
          </button>

          {/* Indicador kaars X van 28 */}
          <span className="rounded border border-[#1f222d] bg-[#030407] px-2.5 py-1 text-slate-300">
            vela <strong className="text-[#4ade80]">{visibleBars}</strong> de{" "}
            <strong>{totalBars}</strong>{" "}
            <span className="text-[9px] text-slate-500">
              (kaars {visibleBars} van {totalBars})
            </span>
          </span>
        </div>
      </div>

      {/* CONTENEDOR DEL GRÁFICO LIGHTWEIGHT CHARTS + OVERLAYS DINÁMICOS */}
      <div className="relative my-1.5 min-h-0 flex-1 overflow-hidden rounded border border-[#1f222d]/80 bg-[#0a0b10]">
        {/* Leyenda OHLC superior izquierda */}
        <div className="pointer-events-none absolute left-2.5 top-2 z-20 flex flex-wrap items-center gap-2.5 rounded border border-[#1f222d] bg-[#050608]/90 px-2.5 py-1 font-mono text-[10px]">
          <span className="font-bold text-[#22d3ee]">{dataset.symbol}</span>
          <span className="text-slate-500">•</span>
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
        </div>

        {decisionBadge && (
          <div
            className={`pointer-events-none absolute right-16 top-2 z-20 rounded border px-2.5 py-1 font-mono text-[10px] font-bold ${
              decisionBadge === "CORRECTO"
                ? "border-[#4ade80]/50 bg-[#4ade80]/15 text-[#4ade80]"
                : "border-slate-500 bg-slate-800/80 text-slate-300"
            }`}
          >
            {decisionBadge === "CORRECTO"
              ? "✓ VALIDADO: CORRECTO (KLOPT)"
              : "✕ RECHAZADO: INCORRECTO"}
          </div>
        )}

        {/* Overlay técnico de Zona FVG / Desplazamiento */}
        {fvgOverlay.visible && (
          <div
            style={{
              left: `${fvgOverlay.left}px`,
              top: `${fvgOverlay.top}px`,
              width: `${fvgOverlay.width}px`,
              height: `${fvgOverlay.height}px`
            }}
            className="pointer-events-none absolute z-10 rounded-sm border border-[#22d3ee]/45 bg-[#22d3ee]/10 shadow-[0_0_20px_rgba(34,211,238,0.12)] transition-all duration-100"
          >
            <div className="flex items-center justify-between px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider text-[#22d3ee]">
              <span>ZONA FVG / DESPLAZAMIENTO</span>
              <span>
                {dataset.fvgBottom.toFixed(1)} - {dataset.fvgTop.toFixed(1)}
              </span>
            </div>
          </div>
        )}

        {/* Etiqueta flotante de Ruptura Change of Character */}
        {chochTagCoord.visible && (
          <div
            style={{
              left: `${Math.max(12, chochTagCoord.x - 90)}px`,
              top: `${Math.max(28, chochTagCoord.y - 30)}px`
            }}
            className="pointer-events-none absolute z-20 rounded border border-[#4ade80] bg-[#051209]/95 px-2 py-0.5 font-mono text-[9px] font-extrabold text-[#4ade80] shadow-[0_0_12px_rgba(74,222,128,0.35)]"
          >
            ⚡ Change of character (Ruptura {dataset.chochBreakPrice.toFixed(2)})
          </div>
        )}

        {/* Canvas de Lightweight Charts */}
        <div ref={chartContainerRef} className="h-full w-full" />
      </div>

      {/* BARRA DE PROGRESO DE VELAS E HITOS ESTRUCTURALES */}
      <div className="flex flex-col gap-1 border-t border-[#1f222d] pt-1.5 font-mono text-[9px]">
        <div className="flex items-center justify-between text-slate-400">
          <div className="flex items-center gap-3">
            <span
              className={
                visibleBars > dataset.lowerHighIdx
                  ? "font-bold text-slate-200"
                  : "text-slate-600"
              }
            >
              ● Vela #{dataset.lowerHighIdx + 1}: Lower high
            </span>
            <span
              className={
                visibleBars > dataset.lowerLowIdx
                  ? "font-bold text-[#eab308]"
                  : "text-slate-600"
              }
            >
              ● Vela #{dataset.lowerLowIdx + 1}: Lower low (Sweep)
            </span>
            <span
              className={
                visibleBars > dataset.chochBreakIdx
                  ? "font-bold text-[#4ade80]"
                  : "text-slate-600"
              }
            >
              ● Vela #{dataset.chochBreakIdx + 1}: Change of character (CHoCH)
            </span>
          </div>
          <span className="text-slate-500">{dataset.sessionLabel}</span>
        </div>

        {/* Barra interactiva para arrastrar o saltar a cualquier vela 1..28 */}
        <div className="flex items-center gap-1">
          {dataset.candles.map((_, idx) => {
            const barNum = idx + 1;
            const isRevealed = barNum <= visibleBars;
            const isMilestone =
              idx === dataset.lowerHighIdx ||
              idx === dataset.lowerLowIdx ||
              idx === dataset.chochBreakIdx;

            return (
              <button
                key={barNum}
                type="button"
                onClick={() => {
                  setIsPlaying(false);
                  setVisibleBars(barNum);
                }}
                className={`h-1.5 flex-1 rounded-full transition-all ${
                  barNum === visibleBars
                    ? "bg-[#22d3ee] shadow-[0_0_6px_#22d3ee]"
                    : isRevealed
                    ? isMilestone
                      ? "bg-[#4ade80]"
                      : "bg-slate-400/70"
                    : "bg-[#151824] hover:bg-slate-700"
                }`}
                title={`Ir a vela ${barNum} de ${totalBars}`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
