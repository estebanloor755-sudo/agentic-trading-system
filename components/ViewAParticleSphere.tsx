"use client";

import React, { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { LiveNLPReader } from "./LiveNLPReader";

interface SourceTodayItem {
  id: string;
  name: string;
  count: number;
  unit: string;
  rate: string;
  sparkline: number[];
  anchorY: number;
}

interface OutputTodayItem {
  id: string;
  label: string;
  value: string;
  subvalue: string;
  progress: number;
  accent: "cyan" | "green" | "mustard";
  sparkline: number[];
  anchorY: number;
}

const FUENTES_HOY: SourceTodayItem[] = [
  {
    id: "yt",
    name: "YouTube",
    count: 45,
    unit: "transcripciones de video",
    rate: "+6.2/h",
    sparkline: [12, 18, 15, 24, 29, 26, 35, 31, 40, 38, 42, 45],
    anchorY: 22
  },
  {
    id: "gh",
    name: "GitHub",
    count: 23,
    unit: "repositorios alpha",
    rate: "+3.4/h",
    sparkline: [8, 10, 9, 14, 13, 17, 16, 19, 18, 21, 20, 23],
    anchorY: 41
  },
  {
    id: "ax",
    name: "arXiv",
    count: 12,
    unit: "papers cuantitativos",
    rate: "+1.8/h",
    sparkline: [3, 4, 4, 6, 5, 7, 8, 7, 9, 10, 11, 12],
    anchorY: 60
  },
  {
    id: "wb",
    name: "Web",
    count: 20,
    unit: "foros y blogs técnicos",
    rate: "+2.9/h",
    sparkline: [6, 9, 8, 11, 13, 12, 15, 14, 17, 16, 19, 20],
    anchorY: 79
  }
];

const SALIDAS_HOY: OutputTodayItem[] = [
  {
    id: "ideadas",
    label: "ESTRATEGIAS IDEADAS",
    value: "142",
    subvalue: "Nuevas recetas algorítmicas generadas hoy (+18.4% vs. ayer)",
    progress: 78,
    accent: "cyan",
    sparkline: [20, 32, 45, 51, 68, 79, 92, 104, 118, 129, 135, 142],
    anchorY: 28
  },
  {
    id: "variantes",
    label: "VARIANTES PROBADAS",
    value: "684",
    subvalue: "Ejecuciones paramétricas y multi-timeframe en motor VectorBT",
    progress: 91,
    accent: "green",
    sparkline: [80, 140, 210, 290, 340, 410, 465, 520, 580, 615, 650, 684],
    anchorY: 54
  },
  {
    id: "aprobadas",
    label: "POR EL FILTRO HOY",
    value: "38 → 4",
    subvalue: "38 superaron filtro IS • 4 nuevas candidatas listas para validación",
    progress: 42,
    accent: "mustard",
    sparkline: [4, 7, 9, 12, 15, 19, 22, 26, 29, 33, 35, 38],
    anchorY: 78
  }
];

function BreinKernParticleSphere({ pulseSpeed = 1 }: { pulseSpeed?: number }) {
  const groupRef = useRef<THREE.Group>(null);
  const pointsRef = useRef<THREE.Points>(null);
  const innerWireRef = useRef<THREE.Mesh>(null);

  const particleCount = 1900;
  const radius = 2.25;

  const { basePositions, positions, colors } = useMemo(() => {
    const basePos = new Float32Array(particleCount * 3);
    const pos = new Float32Array(particleCount * 3);
    const col = new Float32Array(particleCount * 3);

    const goldenRatio = (1 + Math.sqrt(5)) / 2;

    for (let i = 0; i < particleCount; i++) {
      const theta = (2 * Math.PI * i) / goldenRatio;
      const phi = Math.acos(1 - (2 * (i + 0.5)) / particleCount);

      const x = radius * Math.sin(phi) * Math.cos(theta);
      const y = radius * Math.cos(phi);
      const z = radius * Math.sin(phi) * Math.sin(theta);

      basePos[i * 3] = x;
      basePos[i * 3 + 1] = y;
      basePos[i * 3 + 2] = z;

      pos[i * 3] = x;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = z;

      col[i * 3] = 0.82;
      col[i * 3 + 1] = 0.86;
      col[i * 3 + 2] = 0.92;
    }

    return { basePositions: basePos, positions: pos, colors: col };
  }, [particleCount, radius]);

  useFrame((state, delta) => {
    const t = state.clock.getElapsedTime() * pulseSpeed;

    if (groupRef.current) {
      groupRef.current.rotation.y += delta * 0.18;
      groupRef.current.rotation.x = Math.sin(t * 0.25) * 0.08;
    }

    if (innerWireRef.current) {
      innerWireRef.current.rotation.y -= delta * 0.09;
      innerWireRef.current.rotation.z = Math.cos(t * 0.2) * 0.06;
    }

    if (pointsRef.current) {
      const geo = pointsRef.current.geometry;
      const posAttr = geo.getAttribute("position") as THREE.BufferAttribute;
      const colAttr = geo.getAttribute("color") as THREE.BufferAttribute;

      for (let i = 0; i < particleCount; i++) {
        const bx = basePositions[i * 3];
        const by = basePositions[i * 3 + 1];
        const bz = basePositions[i * 3 + 2];

        const wave1 = Math.sin(bx * 2.1 + t * 2.6) * Math.cos(by * 2.1 - t * 1.9);
        const wave2 = Math.sin(bz * 2.8 + t * 3.2);
        const activity = wave1 * 0.65 + wave2 * 0.35;

        if (activity > 0.52) {
          const boost = 1 + (activity - 0.52) * 0.09;
          posAttr.setXYZ(i, bx * boost, by * boost, bz * boost);
          colAttr.setXYZ(i, 0.13, 0.83, 0.93);
        } else if (activity < -0.68) {
          const boost = 1 + Math.abs(activity + 0.68) * 0.05;
          posAttr.setXYZ(i, bx * boost, by * boost, bz * boost);
          colAttr.setXYZ(i, 0.29, 0.87, 0.5);
        } else {
          posAttr.setXYZ(i, bx, by, bz);
          const shade = 0.68 + 0.22 * ((bz + radius) / (2 * radius));
          colAttr.setXYZ(i, shade * 0.9, shade * 0.94, shade);
        }
      }

      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;
    }
  });

  return (
    <group ref={groupRef}>
      <mesh ref={innerWireRef}>
        <icosahedronGeometry args={[radius * 0.95, 3]} />
        <meshBasicMaterial color="#22d3ee" wireframe transparent opacity={0.07} />
      </mesh>

      <mesh>
        <sphereGeometry args={[radius * 0.88, 24, 24]} />
        <meshBasicMaterial color="#05070c" transparent opacity={0.62} />
      </mesh>

      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            count={particleCount}
            array={positions}
            itemSize={3}
          />
          <bufferAttribute
            attach="attributes-color"
            count={particleCount}
            array={colors}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          size={0.046}
          vertexColors
          transparent
          opacity={0.95}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>

      <mesh rotation={[Math.PI / 2.2, 0.2, 0]}>
        <ringGeometry args={[radius * 1.12, radius * 1.135, 96]} />
        <meshBasicMaterial
          color="#22d3ee"
          side={THREE.DoubleSide}
          transparent
          opacity={0.18}
        />
      </mesh>
    </group>
  );
}

export function ViewAParticleSphere() {
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [showNlpReader, setShowNlpReader] = useState<boolean>(true);
  const eqBars = [0.35, 0.85, 0.55, 0.95, 0.45, 0.75, 0.9, 0.4, 0.8, 0.6, 0.95, 0.5];

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col justify-between overflow-hidden rounded-lg border border-[#1f222d] bg-[#0a0b10] p-3">
      {/* HEADER INTERNO */}
      <div className="z-20 flex flex-wrap items-center justify-between gap-2 border-b border-[#1f222d] pb-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse rounded-full bg-[#22d3ee] shadow-[0_0_8px_#22d3ee]" />
          <h2 className="font-mono text-xs font-bold tracking-wide text-slate-200">
            • NÚCLEO NEURONAL — hoy — entran fuentes crudas, salen recetas y variantes probadas
          </h2>
        </div>

        <div className="flex items-center gap-3 font-mono text-[10px] text-slate-400">
          <span>
            Ingesta hoy: <strong className="text-[#22d3ee]">100 fuentes</strong>
          </span>
          <span className="text-slate-600">→</span>
          <span>
            Recetas: <strong className="text-slate-100">142</strong>
          </span>
          <span className="text-slate-600">→</span>
          <span>
            Variantes: <strong className="text-[#4ade80]">684 probadas</strong>
          </span>
          <button
            type="button"
            onClick={() => setShowNlpReader((prev) => !prev)}
            className={`rounded border px-2 py-0.5 font-mono text-[9px] font-bold transition ${
              showNlpReader
                ? "border-[#4ade80]/50 bg-[#4ade80]/15 text-[#4ade80]"
                : "border-[#1f222d] bg-[#030407] text-slate-400 hover:text-white"
            }`}
          >
            {showNlpReader ? "▼ Ocultar Lector NLP (HERMES)" : "▲ Abrir Lector NLP (HERMES)"}
          </button>
        </div>
      </div>

      {/* ÁREA SUPERIOR (70% DEL ALTO DISPONIBLE): ENTRADAS + ESFERA 3D + SALIDAS */}
      <div className="relative my-1.5 grid min-h-0 flex-grow basis-[68%] grid-cols-1 items-center gap-3 overflow-hidden lg:grid-cols-12">
        <svg
          viewBox="0 0 1000 500"
          preserveAspectRatio="none"
          className="pointer-events-none absolute inset-0 z-0 hidden h-full w-full lg:block"
        >
          <defs>
            <linearGradient id="inStreamGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.38" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.12" />
            </linearGradient>
            <linearGradient id="outStreamGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#4ade80" stopOpacity="0.14" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.38" />
            </linearGradient>
          </defs>

          {FUENTES_HOY.map((src) => {
            const startY = (src.anchorY / 100) * 500;
            const endY = 250 + (startY - 250) * 0.28;
            const pathD = `M 245 ${startY} C 330 ${startY}, 355 ${endY}, 420 ${endY}`;
            return (
              <g key={src.id}>
                <path d={pathD} fill="none" stroke="url(#inStreamGrad)" strokeWidth="1.4" />
                <circle cx="420" cy={endY} r="2.5" fill="#22d3ee" fillOpacity="0.5" />
              </g>
            );
          })}

          {SALIDAS_HOY.map((out) => {
            const endY = (out.anchorY / 100) * 500;
            const startY = 250 + (endY - 250) * 0.28;
            const pathD = `M 580 ${startY} C 645 ${startY}, 670 ${endY}, 755 ${endY}`;
            return (
              <g key={out.id}>
                <path d={pathD} fill="none" stroke="url(#outStreamGrad)" strokeWidth="1.5" />
                <circle cx="580" cy={startY} r="2.5" fill="#4ade80" fillOpacity="0.55" />
              </g>
            );
          })}
        </svg>

        {/* LADO IZQUIERDO: FUENTES DE HOY (INPUTS) */}
        <div className="z-10 flex h-full min-h-0 flex-col justify-between overflow-y-auto py-0.5 lg:col-span-3">
          <div className="mb-1 flex shrink-0 items-center justify-between px-1">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400">
              FUENTES DE HOY (ENTRADAS)
            </span>
            <span className="font-mono text-[10px] text-[#22d3ee]">100 Total</span>
          </div>

          <div className="flex min-h-0 flex-1 flex-col justify-around gap-1.5">
            {FUENTES_HOY.map((src) => {
              const isSelected = selectedSource === src.id;
              return (
                <button
                  key={src.id}
                  type="button"
                  onClick={() => setSelectedSource(isSelected ? null : src.id)}
                  className={`group relative flex flex-col justify-between rounded-lg border px-2.5 py-1.5 text-left transition ${
                    isSelected
                      ? "border-[#22d3ee]/60 bg-[#0d1320]"
                      : "border-[#1f222d] bg-[#050609]/90 hover:border-[#22d3ee]/40"
                  }`}
                >
                  <div className="flex items-baseline justify-between">
                    <div className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#22d3ee]" />
                      <span className="font-mono text-xs font-bold text-slate-200">
                        {src.name}
                      </span>
                      <span className="font-mono text-[9px] text-slate-500">
                        ({src.unit})
                      </span>
                    </div>
                    <span className="font-mono text-base font-extrabold text-slate-100">
                      {src.count}
                    </span>
                  </div>

                  <div className="mt-0.5 flex items-center justify-between gap-2">
                    <SourceSparkline data={src.sparkline} color="#22d3ee" />
                    <span className="font-mono text-[9px] text-[#22d3ee]/80">
                      {src.rate}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* CENTRO: CANVAS 3D THREE.JS (ESFERA DE PARTÍCULAS - 70% ALTO SUPERIOR) */}
        <div className="relative z-10 flex h-full min-h-0 flex-grow flex-col items-center justify-center lg:col-span-6">
          <div className="pointer-events-none absolute h-64 w-64 rounded-full bg-[radial-gradient(circle_at_center,rgba(34,211,238,0.14)_0%,rgba(74,222,128,0.04)_50%,transparent_72%)]" />

          <div className="h-full w-full flex-grow cursor-grab active:cursor-grabbing">
            <Canvas
              camera={{ position: [0, 0, 5.4], fov: 45 }}
              gl={{ alpha: true, antialias: true }}
            >
              <ambientLight intensity={0.8} />
              <BreinKernParticleSphere pulseSpeed={selectedSource ? 1.65 : 1} />
              <OrbitControls enableZoom={false} enablePan={false} rotateSpeed={0.45} />
            </Canvas>
          </div>

          <div className="pointer-events-none absolute bottom-1 flex items-center gap-2 rounded-full border border-[#1f222d] bg-[#050609]/90 px-3 py-0.5 font-mono text-[9.5px] text-slate-400">
            <span className="h-1.5 w-1.5 animate-ping rounded-full bg-[#22d3ee]" />
            <span>RED NEURONAL • 1,900 NODOS ACTIVOS • ARRASTRA PARA ROTAR</span>
          </div>
        </div>

        {/* LADO DERECHO: SALIDAS DE HOY (OUTPUTS) */}
        <div className="z-10 flex h-full min-h-0 flex-col justify-between overflow-y-auto py-0.5 lg:col-span-3">
          <div className="mb-1 flex shrink-0 items-center justify-between px-1">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400">
              SALIDAS DE HOY (OUTPUTS)
            </span>
            <span className="font-mono text-[10px] text-[#4ade80]">Síntesis en Vivo</span>
          </div>

          <div className="flex min-h-0 flex-1 flex-col justify-around gap-1.5">
            {SALIDAS_HOY.map((out) => {
              const valueColor =
                out.accent === "green"
                  ? "text-[#4ade80]"
                  : out.accent === "mustard"
                  ? "text-[#eab308]"
                  : "text-[#22d3ee]";

              const barColor =
                out.accent === "green"
                  ? "bg-[#4ade80]"
                  : out.accent === "mustard"
                  ? "bg-[#eab308]"
                  : "bg-[#22d3ee]";

              const sparkColor =
                out.accent === "green"
                  ? "#4ade80"
                  : out.accent === "mustard"
                  ? "#eab308"
                  : "#22d3ee";

              return (
                <div
                  key={out.id}
                  className="flex flex-col justify-between rounded-lg border border-[#1f222d] bg-[#050609]/90 px-2.5 py-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {out.label}
                    </span>
                    <SourceSparkline data={out.sparkline} color={sparkColor} />
                  </div>

                  <div className="my-0.5 flex items-baseline justify-between">
                    <span className={`font-mono text-xl font-extrabold tracking-tight ${valueColor}`}>
                      {out.value}
                    </span>
                    <span className="font-mono text-[9.5px] text-slate-500">
                      {out.progress}% capacidad
                    </span>
                  </div>

                  <p className="mb-1 text-[9.5px] leading-snug text-slate-400">
                    {out.subvalue}
                  </p>

                  <div className="h-1 w-full overflow-hidden rounded-full bg-[#141824]">
                    <div
                      className={`h-full rounded-full ${barColor}`}
                      style={{ width: `${out.progress}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ÁREA INFERIOR (30% RÍGIDO CON OVERFLOW-Y-AUTO): LECTOR NLP EN VIVO (AGENTE HERMES) */}
      {showNlpReader && (
        <div className="z-20 mb-1.5 h-44 shrink-0 overflow-y-auto xl:h-48">
          <LiveNLPReader compact />
        </div>
      )}

      {/* FOOTER INTERNO DE ACTIVIDAD */}
      <div className="z-20 flex flex-wrap items-center justify-between gap-3 rounded-md border border-[#1f222d] bg-[#050609] px-3 py-2 font-mono text-[10px]">
        <div className="flex items-center gap-3">
          <div
            aria-label="Ecualizador de actividad del modelo"
            className="flex h-4 items-end gap-[2px] rounded border border-[#1f222d] bg-[#0a0b10] px-1.5 py-0.5"
          >
            {eqBars.map((ratio, idx) => (
              <span
                key={idx}
                className="w-[2.5px] rounded-t bg-[#22d3ee] animate-pulse"
                style={{
                  height: `${Math.round(ratio * 100)}%`,
                  animationDelay: `${idx * 95}ms`,
                  animationDuration: `${650 + (idx % 4) * 180}ms`,
                  backgroundColor: idx % 3 === 0 ? "#4ade80" : "#22d3ee"
                }}
              />
            ))}
          </div>

          <span className="font-bold uppercase tracking-wider text-slate-300">
            ÚLTIMO CICLO DEL MOTOR
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-400">
            Ciclo #4,812 completado • <strong className="text-[#22d3ee]">arXiv:2610.09412</strong> analizado → 3 nuevas variantes en{" "}
            <strong className="text-[#4ade80]">Reversión-Media NQ</strong>
          </span>
        </div>

        <div className="flex items-center gap-2 text-slate-500">
          <span>Latencia Embedding: <strong className="text-slate-300">18ms</strong></span>
          <span>•</span>
          <span className="text-[#4ade80]">Escuchando nuevas fuentes...</span>
        </div>
      </div>
    </div>
  );
}

function SourceSparkline({ data, color }: { data: number[]; color: string }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(1, max - min);
  const width = 92;
  const height = 18;

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
        strokeOpacity="0.65"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
