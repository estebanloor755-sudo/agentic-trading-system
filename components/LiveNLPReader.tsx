"use client";

import React, { useEffect, useMemo, useState } from "react";
import { BookOpen, Cpu, FileText, Play, Pause, Sparkles } from "lucide-react";

export interface NLPResearchSample {
  id: string;
  sourceType: "ArXiv Paper" | "YouTube Quant" | "SSRN Preprint";
  docId: string;
  title: string;
  rawExcerptEn: string;
  entities: Array<{
    term: string;
    category: "INDICADOR" | "ESTRUCTURA_SMC" | "FLUJO_ORDENES" | "METRICA_RIESGO";
    mappedVar: string;
    targetAgent: "KRONOS" | "CORTEX" | "ORION";
  }>;
  finbertSentiment: number;
}

export const LIVE_NLP_SAMPLES: NLPResearchSample[] = [
  {
    id: "nlp-01",
    sourceType: "YouTube Quant",
    docId: "YT-ICT-942",
    title: "Institutional NY Open Mean Reversion & Order Block Mechanics",
    rawExcerptEn:
      '"...most of the time we fade that move back to VWAP after the initial London liquidity sweep... entry is the first order block that aligns with an unmitigated 15m fair value gap and positive institutional Orderflow absorption before 10:30 EST..."',
    entities: [
      {
        term: "VWAP",
        category: "INDICADOR",
        mappedVar: "target_anchor = session_vwap(df)",
        targetAgent: "CORTEX"
      },
      {
        term: "liquidity sweep",
        category: "ESTRUCTURA_SMC",
        mappedVar: "low[i] < rolling_low(20) and close[i] > open[i]",
        targetAgent: "KRONOS"
      },
      {
        term: "order block",
        category: "ESTRUCTURA_SMC",
        mappedVar: "ob_zone = detect_bullish_ob(df, lookback=12)",
        targetAgent: "KRONOS"
      },
      {
        term: "fair value gap",
        category: "ESTRUCTURA_SMC",
        mappedVar: "fvg_bull = low[i] > high[i-2]",
        targetAgent: "KRONOS"
      },
      {
        term: "Orderflow",
        category: "FLUJO_ORDENES",
        mappedVar: "delta_imbalance > +1.85 * sigma",
        targetAgent: "ORION"
      }
    ],
    finbertSentiment: 0.86
  },
  {
    id: "nlp-02",
    sourceType: "ArXiv Paper",
    docId: "arXiv:2610.09412v1",
    title: "High-Frequency Hawkes Process & Fair Value Gap Microstructure in NQ Futures",
    rawExcerptEn:
      '"...empirical evidence confirms that when price re-enters a fair value gap following a Change of Character, limit order book replenishment near the institutional order block yields a mean reversion drift toward VWAP with Sharpe > 1.85 Out-of-Sample..."',
    entities: [
      {
        term: "fair value gap",
        category: "ESTRUCTURA_SMC",
        mappedVar: "fvg_gap_zone = (high[t-2], low[t])",
        targetAgent: "KRONOS"
      },
      {
        term: "Change of Character",
        category: "ESTRUCTURA_SMC",
        mappedVar: "choch_break = close[t] > swing_high[t-5]",
        targetAgent: "KRONOS"
      },
      {
        term: "order block",
        category: "ESTRUCTURA_SMC",
        mappedVar: "mitigation_level = ob_open_price",
        targetAgent: "CORTEX"
      },
      {
        term: "VWAP",
        category: "INDICADOR",
        mappedVar: "take_profit_1 = anchored_vwap",
        targetAgent: "CORTEX"
      },
      {
        term: "Sharpe > 1.85",
        category: "METRICA_RIESGO",
        mappedVar: "gate_sharpe_oos >= 1.85",
        targetAgent: "ORION"
      }
    ],
    finbertSentiment: 0.91
  },
  {
    id: "nlp-03",
    sourceType: "SSRN Preprint",
    docId: "SSRN-4891204",
    title: "Intraday Gamma Exposure (GEX) Pinning & Liquidity Sweeps on CME E-mini",
    rawExcerptEn:
      '"...during positive dealer gamma regimes, false breakouts trigger a liquidity sweep outside the opening range; the subsequent order block entry targeting session VWAP and mitigating the 5m fair value gap minimizes Max Drawdown below 3.2%..."',
    entities: [
      {
        term: "liquidity sweep",
        category: "ESTRUCTURA_SMC",
        mappedVar: "sweep_orb = high[t] > orb_high and close[t] < orb_high",
        targetAgent: "KRONOS"
      },
      {
        term: "order block",
        category: "ESTRUCTURA_SMC",
        mappedVar: "entry_trigger = ob_retest_5m",
        targetAgent: "CORTEX"
      },
      {
        term: "VWAP",
        category: "INDICADOR",
        mappedVar: "mean_target = vwap_intraday",
        targetAgent: "CORTEX"
      },
      {
        term: "fair value gap",
        category: "ESTRUCTURA_SMC",
        mappedVar: "fvg_confluence = True",
        targetAgent: "KRONOS"
      }
    ],
    finbertSentiment: 0.79
  }
];

interface LiveNLPReaderProps {
  compact?: boolean;
}

export function LiveNLPReader({ compact = false }: LiveNLPReaderProps) {
  const [sampleIndex, setSampleIndex] = useState<number>(0);
  const [autoCycle, setAutoCycle] = useState<boolean>(true);
  const [activeEntityTerm, setActiveEntityTerm] = useState<string | null>(null);

  const sample = LIVE_NLP_SAMPLES[sampleIndex];

  useEffect(() => {
    if (!autoCycle) return;
    const timer = setInterval(() => {
      setSampleIndex((prev) => (prev + 1) % LIVE_NLP_SAMPLES.length);
      setActiveEntityTerm(null);
    }, 8500);
    return () => clearInterval(timer);
  }, [autoCycle]);

  // Tokenizador NER que resalta palabras clave con fondo verde neón (#4ade80) y texto negro
  const highlightedNodes = useMemo(() => {
    const terms = sample.entities.map((e) => e.term);
    if (terms.length === 0) return [sample.rawExcerptEn];

    const escaped = terms
      .slice()
      .sort((a, b) => b.length - a.length)
      .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const regex = new RegExp(`(${escaped.join("|")})`, "gi");
    const parts = sample.rawExcerptEn.split(regex);

    return parts.map((part, idx) => {
      const matchedEntity = sample.entities.find(
        (e) => e.term.toLowerCase() === part.toLowerCase()
      );
      if (!matchedEntity) {
        return <span key={idx}>{part}</span>;
      }

      const isFocused =
        activeEntityTerm &&
        activeEntityTerm.toLowerCase() === matchedEntity.term.toLowerCase();

      return (
        <button
          key={idx}
          type="button"
          onClick={() =>
            setActiveEntityTerm(isFocused ? null : matchedEntity.term)
          }
          className={`mx-0.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] font-extrabold text-black transition-all ${
            isFocused
              ? "bg-[#22d3ee] ring-2 ring-white shadow-[0_0_14px_#22d3ee]"
              : "bg-[#4ade80] shadow-[0_0_10px_rgba(74,222,128,0.45)] hover:brightness-110"
          }`}
          title={`NER Detectado [${matchedEntity.category}] -> ${matchedEntity.mappedVar}`}
        >
          <span>{part}</span>
          <span className="rounded bg-black/20 px-1 text-[8px] font-bold uppercase tracking-tighter text-black/90">
            NER
          </span>
        </button>
      );
    });
  }, [sample, activeEntityTerm]);

  const focusedEntity =
    sample.entities.find(
      (e) =>
        activeEntityTerm &&
        e.term.toLowerCase() === activeEntityTerm.toLowerCase()
    ) ?? sample.entities[0];

  return (
    <div className="flex h-full min-h-0 flex-col justify-between overflow-y-auto rounded-lg border border-[#1f222d] bg-[#0a0b10] p-2.5">
      {/* HEADER DEL LECTOR NLP (AGENTE HERMES) */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-1.5">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded border border-[#eab308]/40 bg-[#eab308]/10">
            <Sparkles className="h-3.5 w-3.5 text-[#eab308]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-100">
                LECTOR NLP EN VIVO (Live Research Feed)
              </h3>
              <span className="rounded border border-[#eab308]/40 bg-[#eab308]/10 px-1.5 py-0.2 font-mono text-[9px] font-bold text-[#eab308]">
                AGENTE: HERMES (NLP / NER)
              </span>
            </div>
            <p className="font-mono text-[9px] text-slate-500">
              Reconocimiento de Entidades Nombradas (NER) en tiempo real → Inyección hacia{" "}
              <strong className="text-[#4ade80]">KRONOS</strong> y{" "}
              <strong className="text-[#22d3ee]">CORTEX</strong>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 font-mono text-[9px]">
          {LIVE_NLP_SAMPLES.map((s, idx) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setSampleIndex(idx);
                setAutoCycle(false);
              }}
              className={`rounded border px-2 py-0.5 transition ${
                sampleIndex === idx
                  ? "border-[#4ade80]/50 bg-[#4ade80]/15 font-bold text-[#4ade80]"
                  : "border-[#1f222d] bg-[#030407] text-slate-400 hover:text-slate-200"
              }`}
            >
              {s.docId}
            </button>
          ))}

          <button
            type="button"
            onClick={() => setAutoCycle((prev) => !prev)}
            className="flex items-center gap-1 rounded border border-[#1f222d] bg-[#030407] px-2 py-0.5 text-slate-400 hover:text-white"
            title={autoCycle ? "Pausar rotación de papers" : "Reanudar rotación automática"}
          >
            {autoCycle ? <Pause className="h-2.5 w-2.5 text-[#4ade80]" /> : <Play className="h-2.5 w-2.5" />}
            <span>{autoCycle ? "Auto" : "Manual"}</span>
          </button>
        </div>
      </div>

      {/* CUERPO: TEXTO EN INGLÉS CON RESALTADO NER VERDE NEÓN (#4ade80) Y TEXTO NEGRO */}
      <div className="mt-1.5 grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-12">
        <div className="flex min-h-0 flex-col justify-between overflow-y-auto rounded border border-[#1f222d] bg-[#050608] p-2 lg:col-span-7">
          <div className="mb-1.5 flex items-center justify-between font-mono text-[9px] text-slate-400">
            <span className="flex items-center gap-1.5 text-[#22d3ee]">
              <FileText className="h-3 w-3" />
              <strong>[{sample.sourceType}]</strong> {sample.title}
            </span>
            <span className="rounded bg-[#4ade80]/15 px-1.5 py-0.5 text-[#4ade80]">
              FinBERT: +{sample.finbertSentiment.toFixed(2)}
            </span>
          </div>

          <div
            className={`font-mono ${
              compact ? "text-[11px] leading-relaxed" : "text-xs leading-relaxed"
            } text-slate-300`}
          >
            {highlightedNodes}
          </div>
        </div>

        {/* VARIABLES EXTRAÍDAS POR HERMES -> KRONOS / CORTEX */}
        <div className="flex flex-col justify-between rounded border border-[#1f222d] bg-[#050608] p-2.5 font-mono lg:col-span-5">
          <div className="flex items-center justify-between border-b border-[#1f222d] pb-1 text-[9px] text-slate-400">
            <span className="flex items-center gap-1 font-bold uppercase text-slate-200">
              <Cpu className="h-3 w-3 text-[#4ade80]" />
              Variables Extraídas ({sample.entities.length} Entidades)
            </span>
            <span className="text-[#22d3ee]">AST Ready</span>
          </div>

          <div className="my-1.5 space-y-1 overflow-y-auto max-h-24 pr-1">
            {sample.entities.map((ent, idx) => {
              const isSelected = focusedEntity.term === ent.term;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setActiveEntityTerm(ent.term)}
                  className={`flex w-full items-center justify-between gap-2 rounded border px-2 py-1 text-left text-[9px] transition ${
                    isSelected
                      ? "border-[#4ade80]/40 bg-[#4ade80]/10 text-white"
                      : "border-[#1f222d]/60 bg-[#0a0b10] text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <span className="rounded bg-[#4ade80] px-1 py-0.2 font-bold text-black">
                      {ent.term}
                    </span>
                    <span className="truncate text-slate-300">{ent.mappedVar}</span>
                  </div>
                  <span className="shrink-0 text-[8px] font-bold text-[#22d3ee]">
                    → {ent.targetAgent}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center justify-between border-t border-[#1f222d] pt-1 text-[9px] text-slate-500">
            <span className="flex items-center gap-1">
              <BookOpen className="h-2.5 w-2.5 text-[#eab308]" />
              Regla compilada: <strong className="text-[#4ade80]">{focusedEntity.mappedVar}</strong>
            </span>
            <span className="text-slate-400">Destino: {focusedEntity.targetAgent}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
