#!/usr/bin/env python3
"""
DIRECTIVA QUANT V10: CLIENTE ZEROMQ NIVEL 2 (NINJATRADER 8 -> PYTHON)
=====================================================================
Suscriptor asincrono ZeroMQ (SUB) conectado a tcp://localhost:5556.
Recibe flujo Tick-a-Tick, Bid/Ask (Nivel 1/2) y Volume_Delta (Orderflow)
desde NinjaTrader 8 en milisegundos sin bloquear el bucle de eventos asyncio.

Requisitos:
    pip install pyzmq websockets
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

try:
    import zmq
    import zmq.asyncio

    HAS_PYZMQ = True
except ImportError:
    HAS_PYZMQ = False


@dataclass
class Level2TickState:
    """Estructura normalizada de un Tick Nivel 2 / Orderflow proveniente de NinjaTrader 8."""

    symbol: str = "NQ 12-26"
    timestamp: str = "00:00:00.00"
    tick_price: float = 21482.50
    tick_volume: int = 1
    bid: float = 21482.25
    ask: float = 21482.50
    volume_delta: int = 0
    cumulative_delta: int = 0
    dom_imbalance_ratio: float = 1.0
    ticks_received: int = 0
    zmq_connected: bool = False
    last_rx_epoch: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NinjaZMQClient:
    """
    Cliente suscriptor (SUB) ZeroMQ para NinjaTrader 8 en tcp://localhost:5556.
    Soporta payloads en formato JSON o cadena delimitada por pipes/comas desde C# NetMQ.
    """

    def __init__(
        self,
        endpoint: str = "tcp://localhost:5556",
        topic_filter: str = "",
        delta_spike_threshold: int = 45,
        on_institutional_spike: Optional[
            Callable[[Level2TickState, str], Coroutine[Any, Any, None]]
        ] = None,
    ) -> None:
        self.endpoint = endpoint
        self.topic_filter = topic_filter
        self.delta_spike_threshold = delta_spike_threshold
        self.on_institutional_spike = on_institutional_spike

        self.latest_state = Level2TickState()
        self._running = False
        self._ctx: Optional[Any] = None
        self._socket: Optional[Any] = None
        self._recent_prices: list[float] = []
        self._recent_deltas: list[int] = []

    @staticmethod
    def _now_str() -> str:
        now = datetime.now()
        return now.strftime("%H:%M:%S.") + f"{int(now.microsecond / 10000):02d}"

    def decode_raw_message(self, raw_payload: str) -> Optional[dict[str, Any]]:
        """
        Decodifica un mensaje entrante desde NinjaTrader 8.
        Formatos soportados:
        1. JSON directo o con prefijo de topico:
           'NQ {"Tick_Price": 21485.25, "Tick_Volume": 18, "Bid": 21485.0, "Ask": 21485.25, "Volume_Delta": 64}'
        2. CSV / Pipe-delimited de baja latencia:
           'NQ|21485.25|18|21485.00|21485.25|64'
        """
        text = raw_payload.strip()
        if not text:
            return None

        # Caso 1: JSON puro o con prefijo de topico antes de '{'
        brace_idx = text.find("{")
        if brace_idx != -1:
            json_part = text[brace_idx:]
            try:
                data = json.loads(json_part)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        # Caso 2: Formato pipe 'SYMBOL|Tick_Price|Tick_Volume|Bid|Ask|Volume_Delta'
        sep = "|" if "|" in text else (";" if ";" in text else ",")
        parts = [p.strip() for p in text.split(sep)]
        if len(parts) >= 5:
            try:
                # Si el primer campo no es numerico, es el simbolo (ej. NQ)
                try:
                    float(parts[0])
                    symbol = self.latest_state.symbol
                    num_parts = parts
                except ValueError:
                    symbol = parts[0]
                    num_parts = parts[1:]

                return {
                    "Symbol": symbol,
                    "Tick_Price": float(num_parts[0]),
                    "Tick_Volume": int(float(num_parts[1])),
                    "Bid": float(num_parts[2]),
                    "Ask": float(num_parts[3]),
                    "Volume_Delta": int(float(num_parts[4])) if len(num_parts) >= 5 else 0,
                }
            except (ValueError, IndexError):
                return None

        return None

    async def process_decoded_tick(self, payload: dict[str, Any]) -> Level2TickState:
        """Actualiza el estado Nivel 2 y verifica picos institucionales de Volume_Delta para KRONOS."""
        symbol = str(
            payload.get("Symbol")
            or payload.get("symbol")
            or self.latest_state.symbol
        )
        tick_price = float(
            payload.get("Tick_Price")
            or payload.get("tick_price")
            or payload.get("price")
            or self.latest_state.tick_price
        )
        tick_volume = int(
            payload.get("Tick_Volume")
            or payload.get("tick_volume")
            or payload.get("volume")
            or 1
        )
        bid = float(
            payload.get("Bid")
            or payload.get("bid")
            or (tick_price - 0.25)
        )
        ask = float(
            payload.get("Ask")
            or payload.get("ask")
            or (tick_price + 0.25)
        )

        # Si NinjaTrader envia Volume_Delta explicito lo usamos; si no, lo inferimos por agresion en Ask vs Bid
        if "Volume_Delta" in payload or "volume_delta" in payload:
            volume_delta = int(
                payload.get("Volume_Delta")
                if "Volume_Delta" in payload
                else payload.get("volume_delta", 0)
            )
        else:
            if tick_price >= ask:
                volume_delta = tick_volume
            elif tick_price <= bid:
                volume_delta = -tick_volume
            else:
                volume_delta = 0

        self.latest_state.symbol = symbol
        self.latest_state.timestamp = str(payload.get("timestamp") or self._now_str())
        self.latest_state.tick_price = round(tick_price, 2)
        self.latest_state.tick_volume = tick_volume
        self.latest_state.bid = round(bid, 2)
        self.latest_state.ask = round(ask, 2)
        self.latest_state.volume_delta = volume_delta
        self.latest_state.cumulative_delta += volume_delta
        self.latest_state.ticks_received += 1
        self.latest_state.zmq_connected = True
        self.latest_state.last_rx_epoch = time.time()

        # Mantener ventana corta para estimar regimen y ratio de desequilibrio
        self._recent_prices.append(self.latest_state.tick_price)
        self._recent_deltas.append(volume_delta)
        if len(self._recent_prices) > 60:
            self._recent_prices.pop(0)
        if len(self._recent_deltas) > 60:
            self._recent_deltas.pop(0)

        pos_flow = sum(d for d in self._recent_deltas if d > 0) + 1
        neg_flow = abs(sum(d for d in self._recent_deltas if d < 0)) + 1
        self.latest_state.dom_imbalance_ratio = round(pos_flow / neg_flow, 2)

        # Disparo de KRONOS si hay un pico extremo de Volume_Delta (agresividad institucional)
        if abs(volume_delta) >= self.delta_spike_threshold and self.on_institutional_spike:
            direction = (
                "COMPRA AGRESIVA (Ask Sweep)"
                if volume_delta > 0
                else "VENTA AGRESIVA (Bid Absorption)"
            )
            await self.on_institutional_spike(self.latest_state, direction)

        return self.latest_state

    def compute_live_regime_and_score(self) -> tuple[str, float]:
        """Calcula el regimen de mercado y el score de flujo a partir de los ticks reales recibidos."""
        if len(self._recent_prices) < 5:
            return "DIRECTIONAL_RUNNER", 0.84

        price_change = self._recent_prices[-1] - self._recent_prices[0]
        net_delta = sum(self._recent_deltas)
        normalized_score = max(-0.99, min(0.99, round(net_delta / 250.0, 2)))

        if abs(price_change) >= 6.0 and abs(net_delta) >= 60:
            regime = "DIRECTIONAL_RUNNER"
        elif abs(net_delta) >= 110:
            regime = "VOLATILITY_EXPANSION"
        else:
            regime = "MEAN_REVERSION_CLAMP"

        return regime, normalized_score

    async def listen_loop(self) -> None:
        """
        Bucle asincrono principal de suscripcion ZeroMQ en tcp://localhost:5556.
        No bloquea el servidor WebSocket.
        """
        self._running = True

        if not HAS_PYZMQ:
            print(
                "[WARN] pyzmq no esta instalado. Ejecuta: pip install pyzmq para habilitar tcp://localhost:5556"
            )
            while self._running:
                await asyncio.sleep(2.0)
            return

        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        # Evitar acumulacion de colas viejas en alta frecuencia (High Water Mark = 1000 ticks)
        self._socket.setsockopt(zmq.RCVHWM, 1000)
        self._socket.setsockopt_string(zmq.SUBSCRIBE, self.topic_filter)
        self._socket.connect(self.endpoint)

        print(
            f"[OK] ZeroMQ SUB conectado a NinjaTrader 8 en {self.endpoint} (Umbral Delta KRONOS: +/-{self.delta_spike_threshold})"
        )

        try:
            while self._running:
                try:
                    # Poll con timeout de 1000ms para mantener latido limpio con asyncio
                    events = await self._socket.poll(timeout=1000)
                    if events & zmq.POLLIN:
                        raw_bytes = await self._socket.recv()
                        raw_str = raw_bytes.decode("utf-8", errors="ignore")
                        decoded = self.decode_raw_message(raw_str)
                        if decoded is not None:
                            await self.process_decoded_tick(decoded)
                    else:
                        # Si no han llegado ticks en los ultimos 5 segundos, marcar espera de feed NT8
                        if time.time() - self.latest_state.last_rx_epoch > 5.0:
                            self.latest_state.zmq_connected = False
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    print(f"[WARN] Error decodificando frame ZeroMQ: {exc}")
                    await asyncio.sleep(0.25)
        finally:
            self.close()

    def close(self) -> None:
        self._running = False
        if self._socket is not None:
            try:
                self._socket.close(0)
            except Exception:
                pass
            self._socket = None
        if self._ctx is not None:
            try:
                self._ctx.term()
            except Exception:
                pass
            self._ctx = None


# ==============================================================================
# 3. ESQUELETO DEL SCRIPT C# (NetMQ) PARA NINJATRADER 8 (INDICADOR / ADD-ON)
# ==============================================================================
# Para instalar NetMQ en NinjaTrader 8:
# 1. Descarga NetMQ.dll y AsyncIO.dll (.NET 4.8) y copialos en:
#    Documentos\NinjaTrader 8\bin\Custom\
# 2. En NinjaScript Editor -> Click derecho -> References -> agrega NetMQ.dll y AsyncIO.dll.
# 3. Crea un nuevo Indicador llamado "CerebroQuantZMQPublisher" y pega este esqueleto:
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
#         private double lastBid = 0;
#         private double lastAsk = 0;
#         private long cumulativeWindowDelta = 0;
#
#         protected override void OnStateChange()
#         {
#             if (State == State.SetDefaults)
#             {
#                 Description = "Publicador Nivel 1/2 y Orderflow (Volume_Delta) hacia Python por ZeroMQ (tcp://*:5556)";
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
#                 lastBid = e.Price;
#             else if (e.MarketDataType == MarketDataType.Ask)
#                 lastAsk = e.Price;
#             else if (e.MarketDataType == MarketDataType.Last)
#             {
#                 double tickPrice = e.Price;
#                 long tickVol = e.Volume;
#
#                 // Calcular Volume_Delta instantaneo segun agresion en Ask o Bid
#                 long volumeDelta = 0;
#                 if (lastAsk > 0 && tickPrice >= lastAsk)
#                     volumeDelta = tickVol;
#                 else if (lastBid > 0 && tickPrice <= lastBid)
#                     volumeDelta = -tickVol;
#
#                 string jsonPayload = string.Format(
#                     CultureInfo.InvariantCulture,
#                     "{{\"Symbol\":\"{0}\",\"Tick_Price\":{1:F2},\"Tick_Volume\":{2},\"Bid\":{3:F2},\"Ask\":{4:F2},\"Volume_Delta\":{5}}}",
#                     Instrument.FullName,
#                     tickPrice,
#                     tickVol,
#                     lastBid > 0 ? lastBid : tickPrice - TickSize,
#                     lastAsk > 0 ? lastAsk : tickPrice + TickSize,
#                     volumeDelta
#                 );
#
#                 pubSocket.TrySendFrame(jsonPayload);
#             }
#         }
#
#         protected override void OnBarUpdate() { }
#     }
# }
# */
