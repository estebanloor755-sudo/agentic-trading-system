"use client";

import React from "react";
import { Check, Code2, Cpu, Database, FileText, GitCommit, Globe, Play, Terminal, X } from "lucide-react";

/**
 * Esqueleto Estructural para VISTA A (Esfera de Partículas 3D + Inputs/Outputs)
 */
export function ViewAParticleSphereSkeleton() {
  const inputs = [
    { source: "YouTube Quant Channels", count: "418 videos", rate: "+14/h", color: "text-[#22d3ee]" },
    { source: "GitHub Alpha Repos", count: "512 scripts", rate: "+22/h", color: "text-[#4ade80]" },
    { source: "ArXiv Financial Math", count: "249 papers", rate: "+6/h", color: "text-[#eab308]" },
    { source: "SSRN / Web Forums", count: "129 threads", rate: "+9/h", color: "text-slate-300" }
  ];

  const outputs = [
    { name: "Trend-volger ES v4.2", status: "LIVE (CME)", metric: "SR 2.52" },
    { name: "Mean-rev NQ Micro", status: "LIVE (CME)", metric: "SR 2.68" },
    { name: "Liquidity-sweep GC", status: "LIVE (COMEX)", metric: "SR 2.31" },
    { name: "VWAP-anker NQ", status: "PAPER (OOS)", metric: "SR 2.08" }
  ];

  return (
    <div className="grid h-full min-h-0 w-full grid-cols-1 gap-3 lg:grid-cols-12">
      {/* Izquierda: Fuentes de Entrada */}
      <div className="flex flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-4 lg:col-span-3">
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            INGESTIE STROOM (BRONNEN)
          </span>
          <h3 className="mt-1 font-mono text-xs font-bold text-slate-100">
            RAW KNOWLEDGE INPUTS (1,308)
          </h3>
        </div>
        <div className="my-auto space-y-2.5">
          {inputs.map((inp) => (
            <div key={inp.source} className="rounded border border-[#1f222d] bg-[#030407] p-3">
              <div className="flex items-center justify-between font-mono text-xs">
                <span className="font-bold text-slate-200">{inp.source}</span>
                <span className="text-[10px] text-[#4ade80]">{inp.rate}</span>
              </div>
              <p className={`mt-1 font-mono text-sm font-bold ${inp.color}`}>{inp.count}</p>
            </div>
          ))}
        </div>
        <p className="font-mono text-[10px] text-slate-500">
          Parser: Whisper-v3 + LLM AST Extractor
        </p>
      </div>

      {/* Centro: Nodo Esfera 3D (Three.js / R3F Slot) */}
      <div className="relative flex flex-col items-center justify-center overflow-hidden rounded-lg border border-[#1f222d] bg-[#0a0b10] p-4 lg:col-span-6">
        <div className="absolute left-4 top-3 font-mono text-[10px] text-slate-400">
          [VISTA A • ESQUELETO THREE.JS / @REACT-THREE/FIBER PARTICLE GLOBE]
        </div>
        <div className="relative flex h-64 w-64 items-center justify-center rounded-full border border-dashed border-[#22d3ee]/40 bg-[radial-gradient(circle_at_center,rgba(34,211,238,0.14)_0%,rgba(74,222,128,0.04)_55%,transparent_75%)] shadow-[0_0_60px_rgba(34,211,238,0.12)]">
          <div className="flex h-40 w-40 flex-col items-center justify-center rounded-full border border-[#4ade80]/40 bg-[#030407]/90 text-center">
            <Globe className="h-7 w-7 animate-pulse text-[#22d3ee]" />
            <span className="mt-1.5 font-mono text-xs font-bold text-slate-100">
              TRADE-BREIN CORE
            </span>
            <span className="font-mono text-[10px] text-[#4ade80]">
              14,280 Embeddings
            </span>
          </div>
        </div>
      </div>

      {/* Derecha: Outputs / Estrategias Generadas */}
      <div className="flex flex-col justify-between rounded-lg border border-[#1f222d] bg-[#0a0b10] p-4 lg:col-span-3">
        <div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            GEGENEREERDE OUTPUTS
          </span>
          <h3 className="mt-1 font-mono text-xs font-bold text-slate-100">
            ALPHA STRATEGIEËN (343 → 3 LIVE)
          </h3>
        </div>
        <div className="my-auto space-y-2.5">
          {outputs.map((out) => (
            <div key={out.name} className="rounded border border-[#1f222d] bg-[#030407] p-3">
              <div className="flex items-center justify-between font-mono text-xs">
                <span className="font-bold text-[#4ade80]">{out.name}</span>
                <span className="text-[10px] text-[#22d3ee]">{out.metric}</span>
              </div>
              <p className="mt-1 font-mono text-[10px] text-slate-400">{out.status}</p>
            </div>
          ))}
        </div>
        <p className="font-mono text-[10px] text-slate-500">
          Auto-Compiler: Python VectorBT + NinjaScript
        </p>
      </div>
    </div>
  );
}


