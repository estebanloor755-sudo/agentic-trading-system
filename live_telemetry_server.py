#!/usr/bin/env python3
"""
TRADE-BREIN // JARVIS QUANT CORE
Servidor Emisor de Telemetria en Tiempo Real (WebSocket Puerto 4100)
--------------------------------------------------------------------
Requisitos:
    pip install websockets

Ejecucion:
    python live_telemetry_server.py
"""

import asyncio
import json
import random
import sys
from datetime import datetime
from typing import Any
import websockets

# Asegurar UTF-8 en terminales de Windows (PowerShell / CMD)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HOST = "0.0.0.0"
PORT = 4100
TICK_INTERVAL_SECONDS = 0.5  # 500ms

# Estado global mutable del embudo cuantitativo (Funnel)
ENGINE_STATE: dict[str, Any] = {
    "hmm_regime": "DIRECTIONAL_RUNNER",
    "finbert_score": 0.84,
    "funnel": {
        "read": 1308,
        "tested": 1251,
        "passed": 343,
        "approved": 12,
        "live": 3,
    },
}

REGIMES = [
    ("DIRECTIONAL_RUNNER", 0.84),
    ("DIRECTIONAL_RUNNER", 0.88),
    ("VOLATILITY_EXPANSION", 0.62),
    ("MEAN_REVERSION_CLAMP", 0.74),
]

AGENT_EVENTS = [
    ("ZEUS", "ZEUS: Veto de seguridad activado. Divergencia entre ATHENA (Hawkish) y ORION (Bullish). Operaciones pausadas.", "gold"),
    ("ZEUS", "ZEUS: Consenso positivo alcanzado. Autorizando paso a Produccion (CME Live) para 'Trend-volger ES'.", "gold"),
    ("ZEUS", "ZEUS: Limite de Drawdown diario al 80%. Reduciendo apalancamiento a la mitad (Risk-Off).", "gold"),
    ("ATHENA", "ATHENA: Tono 'Hawkish' detectado en actas del FOMC. Bloqueando estrategias de Mean Reversion para NQ.", "purple"),
    ("ATHENA", "ATHENA: Rumor de shock geopolitico en Medio Oriente. Aumentando ponderacion en setups de liquidez de XAU/USD.", "purple"),
    ("ATHENA", "ATHENA: Divergencia cualitativa. Precio subiendo, pero sentimiento de flujo institucional negativo (-0.65). Precaucion.", "purple"),
    ("KRONOS", "[Agente Tecnico] Liquidity Sweep + Fair Value Gap (FVG) detectado en NQ 5m (Confluencia Orderflow 92%)", "green"),
    ("ORION", "[Agente Cuantitativo] Evaluando riesgo Reversion-Media NQ v4... {pct}% | Sharpe IS: 2.94 | Sortino: 3.48 | DD < 4.5%", "cyan"),
    ("HERMES", "[Agente Investigador NLP] Paper arXiv '2610.{doc}' analizado -> NER: 'VWAP', 'order block' | FinBERT +{score}", "mustard"),
    ("CORTEX", "[Agente Codificador] Logica compilada a Python vectorizado NumPy (AST limpio, 0 lookahead bias) en 12ms", "cyan"),
]

CONNECTED_CLIENTS: set[Any] = set()


def format_timestamp() -> str:
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 10000):02d}"


def build_system_tick() -> dict[str, Any]:
    """Actualiza incrementalmente las metricas y construye el payload SYSTEM_TICK cada 500ms."""
    funnel = ENGINE_STATE["funnel"]

    # Incrementos estocasticos realistas del motor autonomo
    if random.random() < 0.45:
        funnel["read"] += random.choice([0, 1, 1, 2])
    if funnel["tested"] < funnel["read"] and random.random() < 0.55:
        funnel["tested"] = min(funnel["read"], funnel["tested"] + random.choice([1, 2]))
    if random.random() < 0.18:
        funnel["passed"] += 1

    # Variacion suave de FinBERT y regimen HMM
    if random.random() < 0.08:
        regime, base_score = random.choice(REGIMES)
        ENGINE_STATE["hmm_regime"] = regime
        ENGINE_STATE["finbert_score"] = round(base_score + random.uniform(-0.05, 0.05), 2)
    else:
        drift = random.uniform(-0.01, 0.01)
        ENGINE_STATE["finbert_score"] = round(
            max(-0.99, min(0.99, ENGINE_STATE["finbert_score"] + drift)), 2
        )

    agent, template, tone = random.choice(AGENT_EVENTS)
    msg = template.format(
        pct=random.randint(68, 99),
        doc=random.randint(1020, 9980),
        score=f"{ENGINE_STATE['finbert_score']:.2f}",
    )

    return {
        "type": "SYSTEM_TICK",
        "timestamp": format_timestamp(),
        "hmm_regime": ENGINE_STATE["hmm_regime"],
        "finbert_score": ENGINE_STATE["finbert_score"],
        "funnel": dict(funnel),
        "latest_log": {
            "agent": agent,
            "message": msg,
            "tone": tone,
        },
    }


async def handle_client_messages(websocket: Any) -> None:
    """Escucha comandos enviados desde el frontend Next.js (ej. Human-in-the-Loop Vista D)."""
    async for raw_message in websocket:
        try:
            payload = json.loads(raw_message)
            action = payload.get("action")

            if action == "human_validation":
                setup_id = payload.get("setup_id", "FVG_NQ_123")
                decision = payload.get("decision", "APPROVED")
                notes = payload.get("notes", "")

                if decision == "APPROVED":
                    ENGINE_STATE["funnel"]["approved"] += 1
                    ack_tone = "green"
                    ack_msg = (
                        f"[VALIDACION HUMANA] Setup {setup_id} APROBADO (CORRECTO). "
                        f"Total aprobados: {ENGINE_STATE['funnel']['approved']}. Nota: '{notes}'"
                    )
                else:
                    ack_tone = "mustard"
                    ack_msg = (
                        f"[VALIDACION HUMANA] Setup {setup_id} RECHAZADO (INCORRECTO). "
                        f"Regla de exclusion aplicada: '{notes}'"
                    )

                ack_tick = {
                    "type": "SYSTEM_TICK",
                    "timestamp": format_timestamp(),
                    "hmm_regime": ENGINE_STATE["hmm_regime"],
                    "finbert_score": ENGINE_STATE["finbert_score"],
                    "funnel": dict(ENGINE_STATE["funnel"]),
                    "latest_log": {
                        "agent": "SENTINEL",
                        "message": ack_msg,
                        "tone": ack_tone,
                    },
                }

                print(f"[{ack_tick['timestamp']}] Recibido {action}: {setup_id} -> {decision}", flush=True)
                await broadcast(json.dumps(ack_tick))

        except json.JSONDecodeError:
            print("[WARN] Payload JSON invalido recibido desde el cliente.", flush=True)


async def broadcast(message: str) -> None:
    if not CONNECTED_CLIENTS:
        return
    await asyncio.gather(
        *(client.send(message) for client in list(CONNECTED_CLIENTS)),
        return_exceptions=True,
    )


async def telemetry_emitter_loop() -> None:
    """Bucle principal que emite SYSTEM_TICK cada 500ms a todos los clientes conectados."""
    while True:
        if CONNECTED_CLIENTS:
            tick_payload = build_system_tick()
            await broadcast(json.dumps(tick_payload))
        await asyncio.sleep(TICK_INTERVAL_SECONDS)


async def ws_handler(websocket: Any) -> None:
    CONNECTED_CLIENTS.add(websocket)
    client_addr = getattr(websocket, "remote_address", "client")
    print(f"[+] Cliente Next.js conectado: {client_addr} (Activos: {len(CONNECTED_CLIENTS)})", flush=True)

    # Emitir tick inmediato al conectar
    await websocket.send(json.dumps(build_system_tick()))

    try:
        await handle_client_messages(websocket)
    except websockets.ConnectionClosed:
        pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        print(f"[-] Cliente desconectado: {client_addr} (Activos: {len(CONNECTED_CLIENTS)})", flush=True)


async def main() -> None:
    print("=================================================================", flush=True)
    print(f"[OK] TRADE-BREIN TELEMETRY SERVER ACTIVO EN ws://localhost:{PORT}", flush=True)
    print(f"[OK] Emitiendo SYSTEM_TICK cada {int(TICK_INTERVAL_SECONDS * 1000)}ms", flush=True)
    print("=================================================================", flush=True)

    async with websockets.serve(ws_handler, HOST, PORT):
        await telemetry_emitter_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Servidor detenido por el operador.", flush=True)
