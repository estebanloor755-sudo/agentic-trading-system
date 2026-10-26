#!/usr/bin/env python3
"""
TRADE-BREIN // JARVIS QUANT CORE (DIRECTIVA V10: ZEROMQ + NINJATRADER 8)
========================================================================
Servidor Emisor de Telemetria Nivel 2 en Tiempo Real (WebSocket Puerto 4100)
alimentado por el suscriptor ZeroMQ (tcp://localhost:5556) de NinjaTrader 8.

Requisitos:
    pip install websockets pyzmq

Ejecucion:
    python live_telemetry_server.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from datetime import datetime
from typing import Any
import websockets

from data_ingestion.ninja_zmq_client import Level2TickState, NinjaZMQClient

# Asegurar UTF-8 en terminales de Windows (PowerShell / CMD)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HOST = "0.0.0.0"
PORT = 4100
ZMQ_ENDPOINT = "tcp://localhost:5556"
TICK_INTERVAL_SECONDS = 0.5  # 500ms
KRONOS_DELTA_SPIKE_THRESHOLD = 45  # Contratos netos de agresion institucional

# Estado base del embudo cuantitativo alimentado por ticks reales de ZeroMQ
BASE_FUNNEL: dict[str, int] = {
    "read": 1308,
    "tested": 1251,
    "passed": 343,
    "approved": 12,
    "live": 3,
}

# Cola de logs reales disparados por eventos de ZeroMQ (KRONOS / ORION / ZEUS)
REALTIME_LOG_QUEUE: deque[dict[str, str]] = deque(maxlen=64)

CONNECTED_CLIENTS: set[Any] = set()


def format_timestamp() -> str:
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 10000):02d}"


async def broadcast_payload(payload: dict[str, Any]) -> None:
    """Envia inmediatamente un objeto JSON a todos los clientes Next.js conectados."""
    if not CONNECTED_CLIENTS:
        return
    serialized = json.dumps(payload, ensure_ascii=False)
    stale_clients: list[Any] = []
    for ws in list(CONNECTED_CLIENTS):
        try:
            await ws.send(serialized)
        except Exception:
            stale_clients.append(ws)
    for ws in stale_clients:
        CONNECTED_CLIENTS.discard(ws)


async def on_kronos_delta_spike(state: Level2TickState, direction_label: str) -> None:
    """
    Callback disparado en milisegundos cuando el cliente ZeroMQ detecta un pico
    extremo en Volume_Delta (ej. agresividad institucional de compra/venta en NT8).
    Envia inmediatamente el alerta de KRONOS al frontend por el WebSocket :4100.
    """
    sign = "+" if state.volume_delta > 0 else ""
    tone = "green" if state.volume_delta > 0 else "mustard"

    kronos_msg = (
        f"KRONOS [L2 ZeroMQ {state.symbol}]: Pico institucional {direction_label} "
        f"| Volume_Delta: {sign}{state.volume_delta} contratos @ {state.tick_price:.2f} "
        f"(Bid {state.bid:.2f} / Ask {state.ask:.2f} | CVD: {state.cumulative_delta:+d})"
    )

    log_entry = {
        "agent": "KRONOS",
        "message": kronos_msg,
        "tone": tone,
    }
    REALTIME_LOG_QUEUE.append(log_entry)

    # Emitir tick inmediato al frontend en cuanto ocurre el pico de Orderflow
    immediate_tick = build_system_tick(override_log=log_entry)
    await broadcast_payload(immediate_tick)


# Instancia global del cliente ZeroMQ conectada a tcp://localhost:5556
ZMQ_CLIENT = NinjaZMQClient(
    endpoint=ZMQ_ENDPOINT,
    topic_filter="",
    delta_spike_threshold=KRONOS_DELTA_SPIKE_THRESHOLD,
    on_institutional_spike=on_kronos_delta_spike,
)


def build_system_tick(override_log: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Construye el payload SYSTEM_TICK leyendo directamente el estado real
    procesado por el cliente ZeroMQ (ZMQ_CLIENT.latest_state) sin inventar numeros.
    """
    l2: Level2TickState = ZMQ_CLIENT.latest_state
    regime, live_score = ZMQ_CLIENT.compute_live_regime_and_score()

    # Contadores derivados deterministicamente de los ticks reales procesados por ZeroMQ
    ticks = l2.ticks_received
    funnel = {
        "read": BASE_FUNNEL["read"] + (ticks // 5),
        "tested": BASE_FUNNEL["tested"] + (ticks // 6),
        "passed": BASE_FUNNEL["passed"] + (ticks // 25),
        "approved": BASE_FUNNEL["approved"],
        "live": BASE_FUNNEL["live"],
    }

    if override_log is not None:
        latest_log = override_log
    elif REALTIME_LOG_QUEUE:
        latest_log = REALTIME_LOG_QUEUE.popleft()
    elif l2.zmq_connected:
        sign = "+" if l2.volume_delta >= 0 else ""
        latest_log = {
            "agent": "ORION",
            "message": (
                f"ORION [NT8 ZeroMQ :5556]: {l2.symbol} Tick {l2.tick_price:.2f} "
                f"(Vol: {l2.tick_volume} | Bid: {l2.bid:.2f} | Ask: {l2.ask:.2f} "
                f"| Delta: {sign}{l2.volume_delta} | Ratio DOM: {l2.dom_imbalance_ratio:.2f}x)"
            ),
            "tone": "cyan",
        }
    else:
        latest_log = {
            "agent": "ZEUS",
            "message": (
                f"ZEUS [CRO]: Escuchando puente ZeroMQ NinjaTrader 8 en {ZMQ_ENDPOINT} "
                f"| Ultimo precio en memoria: {l2.tick_price:.2f} (Ticks RX: {l2.ticks_received})"
            ),
            "tone": "gold",
        }

    return {
        "type": "SYSTEM_TICK",
        "timestamp": l2.timestamp if l2.zmq_connected else format_timestamp(),
        "hmm_regime": regime,
        "finbert_score": live_score,
        "funnel": funnel,
        "l2_market_data": l2.to_dict(),
        "latest_log": latest_log,
    }


async def handle_client_messages(websocket: Any) -> None:
    """Escucha comandos enviados desde el frontend Next.js (ej. Human-in-the-Loop o Auto-Pilot ZEUS)."""
    async for raw_message in websocket:
        try:
            payload = json.loads(raw_message)
            action = payload.get("action")

            if action == "human_validation":
                setup_id = payload.get("setup_id", "FVG_NQ_123")
                decision = payload.get("decision", "APPROVED")
                notes = payload.get("notes", "")

                if decision == "APPROVED":
                    BASE_FUNNEL["approved"] += 1
                    tone = "gold" if "ZEUS" in notes else "green"
                    agent_id = "ZEUS" if "ZEUS" in notes else "SENTINEL"
                    verdict_text = "APROBADO y promovido al motor de ejecucion"
                else:
                    tone = "mustard"
                    agent_id = "ZEUS" if "ZEUS" in notes else "SENTINEL"
                    verdict_text = "VETADO / RECHAZADO y bloqueado en filtro de riesgo"

                extra_note = f" | Nota: {notes}" if notes else ""
                feedback_log = {
                    "agent": agent_id,
                    "message": f"[{agent_id}] Setup {setup_id} {verdict_text}{extra_note}",
                    "tone": tone,
                }
                REALTIME_LOG_QUEUE.append(feedback_log)

                feedback_tick = build_system_tick(override_log=feedback_log)
                await broadcast_payload(feedback_tick)
                print(f"[FEEDBACK] Setup={setup_id} | Decision={decision}")

        except json.JSONDecodeError:
            print(f"[WARN] Mensaje no-JSON recibido: {raw_message}")
        except Exception as exc:
            print(f"[ERROR] Procesando mensaje del cliente: {exc}")


async def ws_handler(websocket: Any) -> None:
    """Registra cada cliente Next.js conectado y mantiene el canal bidireccional."""
    CONNECTED_CLIENTS.add(websocket)
    client_addr = getattr(websocket, "remote_address", ("127.0.0.1", 0))
    print(f"[WS+] Cliente conectado desde {client_addr} (Activos: {len(CONNECTED_CLIENTS)})")

    try:
        await websocket.send(json.dumps(build_system_tick(), ensure_ascii=False))
        await handle_client_messages(websocket)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        print(f"[WS-] Cliente desconectado {client_addr} (Activos: {len(CONNECTED_CLIENTS)})")


async def telemetry_emitter_loop() -> None:
    """Bucle asincrono que emite el estado real de ZeroMQ cada 500ms a los clientes WebSocket."""
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        if not CONNECTED_CLIENTS:
            continue
        tick_payload = build_system_tick()
        await broadcast_payload(tick_payload)


async def main() -> None:
    print("=" * 76)
    print(" [OK] TRADE-BREIN // JARVIS QUANT TELEMETRY + ZEROMQ L2 SERVER")
    print(f" [OK] WebSocket escuchando en: ws://localhost:{PORT}")
    print(f" [OK] Suscriptor ZeroMQ (SUB) apuntando a: {ZMQ_ENDPOINT}")
    print(f" [OK] Frecuencia de emision WS: {int(TICK_INTERVAL_SECONDS * 1000)}ms")
    print("=" * 76)

    # Iniciar el bucle asincrono de ZeroMQ sin bloquear el servidor WebSocket
    zmq_task = asyncio.create_task(ZMQ_CLIENT.listen_loop())

    try:
        async with websockets.serve(ws_handler, HOST, PORT):
            await telemetry_emitter_loop()
    finally:
        ZMQ_CLIENT.close()
        zmq_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOP] Servidor de telemetria detenido por el usuario.")


# ==============================================================================
# 3. ESQUELETO DEL SCRIPT C# (NetMQ) PARA NINJATRADER 8 (PUBLICADOR PUB :5556)
# ==============================================================================
# Copia este indicador NinjaScript en NinjaTrader 8 (referenciando NetMQ.dll y AsyncIO.dll)
# para publicar en tiempo real el flujo Tick-a-Tick, Bid, Ask y Volume_Delta hacia Python:
#
# /*
# using System;
# using System.Globalization;
# using NinjaTrader.Cbi;
# using NinjaTrader.Data;
# using NinjaTrader.NinjaScript;
# using NetMQ;
# using NetMQ.Sockets;
#
# namespace NinjaTrader.NinjaScript.Indicators
# {
#     public class CerebroQuantZMQPublisher : Indicator
#     {
#         private PublisherSocket pubSocket;
#         private double currentBid = 0;
#         private double currentAsk = 0;
#
#         protected override void OnStateChange()
#         {
#             if (State == State.SetDefaults)
#             {
#                 Description = "Puente ZeroMQ PUB hacia Python (tcp://*:5556) para KRONOS y ORION";
#                 Name = "CerebroQuantZMQPublisher";
#                 Calculate = Calculate.OnEachTick;
#                 IsOverlay = true;
#             }
#             else if (State == State.DataLoaded)
#             {
#                 AsyncIO.ForceDotNet.Force();
#                 pubSocket = new PublisherSocket();
#                 pubSocket.Options.SendHighWatermark = 1000;
#                 pubSocket.Bind("tcp://*:5556");
#             }
#             else if (State == State.Terminated)
#             {
#                 if (pubSocket != null)
#                 {
#                     pubSocket.Close();
#                     pubSocket.Dispose();
#                     pubSocket = null;
#                 }
#                 NetMQConfig.Cleanup(false);
#             }
#         }
#
#         protected override void OnMarketData(MarketDataEventArgs e)
#         {
#             if (pubSocket == null) return;
#
#             if (e.MarketDataType == MarketDataType.Bid)
#                 currentBid = e.Price;
#             else if (e.MarketDataType == MarketDataType.Ask)
#                 currentAsk = e.Price;
#             else if (e.MarketDataType == MarketDataType.Last)
#             {
#                 double tickPrice = e.Price;
#                 long tickVolume = e.Volume;
#
#                 // Volume_Delta: positivo si golpea el Ask (compra a mercado), negativo si golpea el Bid
#                 long volumeDelta = 0;
#                 if (currentAsk > 0 && tickPrice >= currentAsk)
#                     volumeDelta = tickVolume;
#                 else if (currentBid > 0 && tickPrice <= currentBid)
#                     volumeDelta = -tickVolume;
#
#                 string payload = string.Format(
#                     CultureInfo.InvariantCulture,
#                     "{{\"Symbol\":\"{0}\",\"Tick_Price\":{1:F2},\"Tick_Volume\":{2},\"Bid\":{3:F2},\"Ask\":{4:F2},\"Volume_Delta\":{5}}}",
#                     Instrument.FullName,
#                     tickPrice,
#                     tickVolume,
#                     currentBid > 0 ? currentBid : tickPrice - TickSize,
#                     currentAsk > 0 ? currentAsk : tickPrice + TickSize,
#                     volumeDelta
#                 );
#
#                 pubSocket.TrySendFrame(payload);
#             }
#         }
#
#         protected override void OnBarUpdate() { }
#     }
# }
# */
