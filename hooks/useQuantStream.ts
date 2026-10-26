"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  INITIAL_AGENT_LOGS,
  type AgentLogEntry,
  type SubAgentId
} from "../components/mockData";

export type StreamConnectionStatus =
  | "CONNECTING"
  | "CONNECTED"
  | "RECONNECTING"
  | "DISCONNECTED";

export interface FunnelTelemetry {
  read: number;
  tested: number;
  passed: number;
  approved: number;
  live: number;
}

export interface IncomingLogPayload {
  agent: SubAgentId;
  message: string;
  tone: "green" | "cyan" | "mustard" | "purple" | "muted";
}

export interface SystemTickPayload {
  type: "SYSTEM_TICK";
  timestamp: string;
  hmm_regime: string;
  finbert_score: number;
  funnel: FunnelTelemetry;
  latest_log?: IncomingLogPayload;
}

export interface HumanValidationCommand {
  action: "human_validation";
  setup_id: string;
  decision: "APPROVED" | "REJECTED";
  notes?: string;
}

const DEFAULT_WS_ENDPOINT =
  process.env.NEXT_PUBLIC_QUANT_WS_URL || "ws://localhost:4100";

const INITIAL_TICK_STATE: SystemTickPayload = {
  type: "SYSTEM_TICK",
  timestamp: "17:54:12.04",
  hmm_regime: "DIRECTIONAL_RUNNER",
  finbert_score: 0.84,
  funnel: {
    read: 1308,
    tested: 1251,
    passed: 343,
    approved: 12,
    live: 3
  },
  latest_log: {
    agent: "ORION",
    message: "Ejecutando backtest Reversión-Media NQ v4... 87% completado",
    tone: "cyan"
  }
};

export function useQuantStream(wsEndpoint: string = DEFAULT_WS_ENDPOINT) {
  const [lastTick, setLastTick] = useState<SystemTickPayload>(INITIAL_TICK_STATE);
  const [logs, setLogs] = useState<AgentLogEntry[]>(INITIAL_AGENT_LOGS);
  const [connectionStatus, setConnectionStatus] =
    useState<StreamConnectionStatus>("CONNECTING");
  const [reconnectAttempt, setReconnectAttempt] = useState<number>(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffMsRef = useRef<number>(500);

  const sendHumanValidation = useCallback(
    (setupId: string, decision: "APPROVED" | "REJECTED", notes?: string): boolean => {
      const payload: HumanValidationCommand = {
        action: "human_validation",
        setup_id: setupId,
        decision,
        notes
      };

      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify(payload));
          return true;
        } catch {
          // Fallback local si ocurre un error de escritura en el socket
        }
      }

      const now = new Date();
      const timestamp =
        now.toTimeString().slice(0, 8) +
        "." +
        String(Math.floor(now.getMilliseconds() / 10)).padStart(2, "0");

      setLastTick((prev) => ({
        ...prev,
        timestamp,
        funnel: {
          ...prev.funnel,
          approved:
            decision === "APPROVED" ? prev.funnel.approved + 1 : prev.funnel.approved
        }
      }));

      setLogs((prev) => [
        ...prev.slice(-49),
        {
          id: `local-val-${Date.now()}`,
          time: timestamp,
          agent: "SENTINEL",
          message: `[VALIDACIÓN HUMANA] ${setupId} -> ${
            decision === "APPROVED" ? "APROBADO (CORRECTO)" : "RECHAZADO (INCORRECTO)"
          }${notes ? ` (${notes})` : ""}`,
          level: decision === "APPROVED" ? "green" : "mustard"
        }
      ]);

      return false;
    },
    []
  );

  useEffect(() => {
    let active = true;

    function connectWebSocket() {
      if (!active) return;

      if (wsRef.current) {
        try {
          wsRef.current.onopen = null;
          wsRef.current.onmessage = null;
          wsRef.current.onerror = null;
          wsRef.current.onclose = null;
          wsRef.current.close();
        } catch {}
        wsRef.current = null;
      }

      setConnectionStatus((prev) =>
        prev === "CONNECTING" ? "CONNECTING" : "RECONNECTING"
      );

      try {
        const socket = new WebSocket(wsEndpoint);
        wsRef.current = socket;

        socket.onopen = () => {
          if (!active || wsRef.current !== socket) return;
          setConnectionStatus("CONNECTED");
          setReconnectAttempt(0);
          backoffMsRef.current = 500;
        };

        socket.onmessage = (event: MessageEvent) => {
          if (!active || wsRef.current !== socket) return;
          try {
            const parsed = JSON.parse(event.data) as SystemTickPayload;
            if (parsed && parsed.type === "SYSTEM_TICK") {
              setLastTick(parsed);

              if (parsed.latest_log && parsed.latest_log.message) {
                const rawAgent = parsed.latest_log.agent || "ORION";
                const normalizedAgent: SubAgentId =
                  rawAgent === "FINBERT" ? "HERMES" : rawAgent;
                const newEntry: AgentLogEntry = {
                  id: `ws-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                  time: parsed.timestamp,
                  agent: normalizedAgent,
                  message: parsed.latest_log.message,
                  level: parsed.latest_log.tone || "cyan"
                };

                setLogs((prev) => {
                  const last = prev[prev.length - 1];
                  if (last && last.message === newEntry.message && last.time === newEntry.time) {
                    return prev;
                  }
                  return [...prev.slice(-59), newEntry];
                });
              }
            }
          } catch {}
        };

        socket.onerror = () => {
          if (!active || wsRef.current !== socket) return;
        };

        socket.onclose = () => {
          if (!active || wsRef.current !== socket) return;
          setConnectionStatus("DISCONNECTED");

          const delay = Math.min(10000, backoffMsRef.current);
          backoffMsRef.current = Math.min(10000, backoffMsRef.current * 2);
          setReconnectAttempt((prev) => prev + 1);

          reconnectTimerRef.current = setTimeout(() => {
            if (active) {
              connectWebSocket();
            }
          }, delay);
        };
      } catch {
        if (!active) return;
        setConnectionStatus("DISCONNECTED");

        const delay = Math.min(10000, backoffMsRef.current);
        backoffMsRef.current = Math.min(10000, backoffMsRef.current * 2);
        setReconnectAttempt((prev) => prev + 1);

        reconnectTimerRef.current = setTimeout(() => {
          if (active) {
            connectWebSocket();
          }
        }, delay);
      }
    }

    connectWebSocket();

    return () => {
      active = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.onopen = null;
          wsRef.current.onmessage = null;
          wsRef.current.onerror = null;
          wsRef.current.onclose = null;
          wsRef.current.close();
        } catch {}
        wsRef.current = null;
      }
    };
  }, [wsEndpoint]);

  return {
    lastTick,
    logs,
    connectionStatus,
    reconnectAttempt,
    sendHumanValidation
  };
}
