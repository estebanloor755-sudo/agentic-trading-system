# %% [CORE EXECUTION ENGINE: SYNTHETIC TWAP / LEVEL 1 ICEBERG & SMART ORDER ROUTING]
"""
Motor de Ejecución Cuantitativo de Nivel 1 (Algo Trading Institucional).

Características de Diseño:
  1. Smart Execution (Iceberg de Nivel 1):
     - Fragmenta órdenes institucionales (ej. 1.0 lote) en micro-órdenes de tamaño óptimo
       (ej. 10 x 0.10 lotes o micro-lotes 0.01) para eliminar market impact y slippage.
  2. Microstructure Spread-Gating:
     - Mantiene la media móvil del Spread L1 de los últimos 5 minutos (SMA 5m).
     - Condiciona la ejecución de cada rebanada (slice): solo dispara si el Spread L1 actual
       es inferior o igual a la media móvil o al umbral de liquidez (`spread <= spread_ma * 1.15`).
  3. TWAP Scheduling con Anti-Front-Running Jitter:
     - Distribuye las rebanadas en un horizonte temporal con micro-jitter estocástico
       para impedir la detección por parte de algoritmos de alta frecuencia (HFT) depredadores.
  4. Compatibilidad Dual (MT5 Live Real y Paper Simulation):
     - Interactúa nativamente con `MetaTrader5` mediante `order_send` (TRADE_ACTION_DEAL).
     - Si MT5 está en modo offline/Linux, ejecuta simulación realista con slippage y latency tracking.
"""
from __future__ import annotations

import collections
import dataclasses
import enum
import math
import random
import time
from typing import Any, Callable

try:
    import MetaTrader5 as mt5
except (ImportError, ModuleNotFoundError):
    mt5 = None


class OrderDirection(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class PlanStatus(enum.Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    PAUSED_SPREAD = "PAUSED_SPREAD"
    CANCELLED = "CANCELLED"
    HALTED = "HALTED"


@dataclasses.dataclass
class ChildSlice:
    slice_id: int
    parent_plan_id: str
    target_volume: float
    scheduled_time: float
    executed_volume: float = 0.0
    fill_price: float = 0.0
    slippage_pts: float = 0.0
    status: str = "PENDING"
    timestamp_filled: float = 0.0
    mt5_ticket: int = 0
    error_msg: str = ""


@dataclasses.dataclass
class ExecutionPlan:
    plan_id: str
    symbol: str
    direction: OrderDirection
    total_volume: float
    strategy_name: str
    time_window_sec: float
    num_slices: int
    arrival_price: float
    max_spread_limit: float = 2.0
    spread_multiplier: float = 1.15
    created_at: float = dataclasses.field(default_factory=time.time)
    slices: list[ChildSlice] = dataclasses.field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    filled_volume: float = 0.0
    weighted_avg_price: float = 0.0
    total_slippage_pts: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.status in (PlanStatus.PENDING, PlanStatus.EXECUTING, PlanStatus.PAUSED_SPREAD)

    @property
    def progress_pct(self) -> float:
        return (self.filled_volume / self.total_volume * 100.0) if self.total_volume > 0 else 0.0


class ExecutionEngine:
    """
    Motor Algorítmico de Ejecución Institucional basado en Microestructura de Nivel 1.
    """

    def __init__(
        self,
        symbol: str = "US100-DEC26",
        magic_number: int = 20261020,
        max_spread_limit: float = 2.0,
        paper_trading: bool = False,
    ):
        self.symbol = symbol
        self.magic_number = magic_number
        self.max_spread_limit = max_spread_limit
        self.paper_trading = paper_trading or (mt5 is None)

        self.is_halted = False
        self.halt_reason = ""
        self.is_stationary = True
        self.risk_model_valid = True
        self.risk_audit_status = "✓ VaR 99% Validado (Kupiec & Christoffersen)"

        # Almacenamiento de planes activos e históricos
        self.active_plans: dict[str, ExecutionPlan] = {}
        self.completed_plans: list[ExecutionPlan] = []

        # Buffer circular de spreads L1 para media móvil de 5 minutos (300 muestras a 1 tick/s aprox)
        self.spread_history: collections.deque[float] = collections.deque(maxlen=300)
        self.last_spot_price: float = 0.0
        self.last_spread_pts: float = 0.50
        self.last_tick_time: float = time.time()

        # Telemetría de ejecución acumulada
        self.stats = {
            "total_orders_dispatched": 0,
            "total_volume_executed": 0.0,
            "total_slippage_pts": 0.0,
            "paused_by_spread_count": 0,
            "execution_mode": "PAPER_SIMULATION" if self.paper_trading else "MT5_LIVE",
        }

    @property
    def spread_ma_5m(self) -> float:
        """Media móvil del Spread L1 en los últimos 5 minutos."""
        if not self.spread_history:
            return self.last_spread_pts
        return float(sum(self.spread_history) / len(self.spread_history))

    def update_tick(self, spot: float, spread: float, timestamp: float | None = None) -> None:
        """
        Alimenta el motor con cada tick en vivo de Nivel 1.
        Actualiza la ventana de spread y evalúa rebanadas de ejecución programadas.
        """
        if spot and spot > 0:
            self.last_spot_price = float(spot)
        if spread and spread > 0:
            self.last_spread_pts = float(spread)
            self.spread_history.append(float(spread))
        self.last_tick_time = timestamp or time.time()

        if self.is_halted:
            return

        # Procesar planes activos
        now = time.time()
        for plan in list(self.active_plans.values()):
            if plan.is_active:
                self._process_plan_tick(plan, now)

    def update_stationarity(self, is_stationary: bool, adf_pvalue: float | None = None) -> None:
        """Actualiza la condición de estacionariedad dictaminada por el test ADF."""
        self.is_stationary = bool(is_stationary)
        if not self.is_stationary:
            p_str = f"{adf_pvalue:.4f}" if adf_pvalue is not None else ">=0.05"
            print(f"  [EXECUTION-PAUSED] Bloqueo econométrico: Serie no estacionaria (ADF p={p_str}). Órdenes automáticas pausadas.")

    def update_risk_audit(self, is_valid: bool, status_msg: str = "", kupiec_p: float | None = None, christoffersen_p: float | None = None) -> None:
        """
        Actualiza el resultado de la auditoría de riesgo Kupiec POF y Christoffersen.
        Si el modelo VaR 99% falla (p < 0.05), pausa el despacho algorítmico preventivamente.
        """
        self.risk_model_valid = bool(is_valid)
        self.risk_audit_status = status_msg
        if not self.risk_model_valid:
            k_str = f"Kupiec p={kupiec_p:.3f}" if kupiec_p is not None else "p<0.05"
            c_str = f"Christoffersen p={christoffersen_p:.3f}" if christoffersen_p is not None else "p<0.05"
            print(f"  [EXECUTION-PAUSED] ⚠️ Riesgo no validado: {status_msg} ({k_str}, {c_str}). Órdenes bloqueadas preventivamente.")

    def submit_twap_iceberg(
        self,
        direction: str | OrderDirection,
        total_volume: float,
        strategy_name: str = "VOLATILITY_REVERSION",
        time_window_sec: float = 60.0,
        num_slices: int = 10,
        max_spread_limit: float | None = None,
    ) -> ExecutionPlan | None:
        """
        Crea e inicia un plan de ejecución institucional TWAP / Iceberg de Nivel 1.
        
        Divide `total_volume` (ej. 1.0 lote) en `num_slices` (ej. 10 x 0.10)
        distribuidos en `time_window_sec` con anti-front-running jitter.
        """
        if self.is_halted:
            print(f"  [EXECUTION-REJECTED] Sistema en estado HALT por Kill Switch ({self.halt_reason}).")
            return None

        if not self.is_stationary:
            print("  [EXECUTION-REJECTED] Auditoría econométrica: Serie no estacionaria (ADF p >= 0.05). Operativa bloqueada.")
            return None

        dir_enum = OrderDirection(direction.upper()) if isinstance(direction, str) else direction
        plan_id = f"TWAP_{int(time.time()*1000)}_{random.randint(100, 999)}"
        arrival_px = self.last_spot_price

        # Asegurar un mínimo de 2 rebanadas y cálculo de lotaje por rebanada
        n_slices = max(int(num_slices), 2)
        slice_vol = round(float(total_volume) / n_slices, 2)
        if slice_vol < 0.01:
            slice_vol = 0.01
            n_slices = max(1, int(round(total_volume / slice_vol)))

        plan = ExecutionPlan(
            plan_id=plan_id,
            symbol=self.symbol,
            direction=dir_enum,
            total_volume=round(float(total_volume), 2),
            strategy_name=strategy_name,
            time_window_sec=float(time_window_sec),
            num_slices=n_slices,
            arrival_price=arrival_px,
            max_spread_limit=max_spread_limit or self.max_spread_limit,
            status=PlanStatus.EXECUTING,
        )

        # Generar cronograma de rebanadas con Jitter estocástico (±15%)
        base_interval = float(time_window_sec) / n_slices
        current_schedule = time.time()

        for s_idx in range(n_slices):
            # En la primera rebanada, disparo casi inmediato (0.1 a 0.5s)
            if s_idx == 0:
                sched_time = current_schedule + 0.1
            else:
                jitter = random.uniform(-0.15, 0.15) * base_interval
                current_schedule += max(0.5, base_interval + jitter)
                sched_time = current_schedule

            # La última rebanada ajusta el remanente de volumen exacto
            if s_idx == n_slices - 1:
                cur_vol = round(plan.total_volume - sum(s.target_volume for s in plan.slices), 2)
                if cur_vol <= 0:
                    cur_vol = slice_vol
            else:
                cur_vol = slice_vol

            child = ChildSlice(
                slice_id=s_idx + 1,
                parent_plan_id=plan_id,
                target_volume=cur_vol,
                scheduled_time=sched_time,
            )
            plan.slices.append(child)

        self.active_plans[plan_id] = plan
        print(
            f"\n  [EXECUTION-PLAN INICIADO] {plan_id} | {plan.direction.value} {plan.total_volume} Lotes {self.symbol} "
            f"({plan.strategy_name}) | TWAP: {n_slices} micro-rebanadas de ~{slice_vol} en {time_window_sec:.0f}s"
        )
        return plan

    def _process_plan_tick(self, plan: ExecutionPlan, now_t: float) -> None:
        """Evalúa las rebanadas pendientes de un plan contra las condiciones de microestructura."""
        if self.is_halted or not self.is_stationary or not self.risk_model_valid:
            return

        # 1. Validación de Microestructura: Spread-Gating
        spread_threshold = min(self.spread_ma_5m * plan.spread_multiplier, plan.max_spread_limit)
        is_spread_clean = self.last_spread_pts <= spread_threshold

        if not is_spread_clean:
            if plan.status != PlanStatus.PAUSED_SPREAD:
                plan.status = PlanStatus.PAUSED_SPREAD
                self.stats["paused_by_spread_count"] += 1
                print(
                    f"  [SPREAD-GATING ACTIVO] Plan {plan.plan_id} pausado temporalmente: "
                    f"Spread {self.last_spread_pts:.2f}p > Umbral {spread_threshold:.2f}p"
                )
            return
        elif plan.status == PlanStatus.PAUSED_SPREAD:
            plan.status = PlanStatus.EXECUTING
            print(f"  [SPREAD-GATING NORMALIZADO] Reanudando ejecución en Plan {plan.plan_id} (Spread: {self.last_spread_pts:.2f}p)")

        # 2. Despacho de rebanadas cuyo tiempo programado haya llegado
        for s in plan.slices:
            if s.status == "PENDING" and now_t >= s.scheduled_time:
                self._dispatch_slice(plan, s)

        # 3. Verificar si el plan ya se completó
        if all(s.status in ("FILLED", "FAILED", "CANCELLED") for s in plan.slices):
            plan.status = PlanStatus.COMPLETED
            if plan.plan_id in self.active_plans:
                del self.active_plans[plan.plan_id]
            self.completed_plans.append(plan)
            print(
                f"\n  [EXECUTION-PLAN COMPLETADO] {plan.plan_id} | Total Llenado: {plan.filled_volume:.2f}/{plan.total_volume:.2f} "
                f"| Px Promedio: {plan.weighted_avg_price:,.2f} | Slippage Total: {plan.total_slippage_pts:+.2f} pts"
            )

    def _dispatch_slice(self, plan: ExecutionPlan, s: ChildSlice) -> None:
        """Ejecuta una rebanada vía MT5 o simulador de baja latencia."""
        s.status = "EXECUTING"
        t_start = time.perf_counter()

        if not self.paper_trading and mt5 is not None:
            # Ejecución en Vivo en MetaTrader 5
            try:
                action_type = mt5.ORDER_TYPE_BUY if plan.direction == OrderDirection.BUY else mt5.ORDER_TYPE_SELL
                tk = mt5.symbol_info_tick(self.symbol)
                px = float(tk.ask if plan.direction == OrderDirection.BUY else tk.bid) if tk else self.last_spot_price

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": float(s.target_volume),
                    "type": action_type,
                    "price": px,
                    "deviation": 10,
                    "magic": self.magic_number,
                    "comment": f"TWAP-{s.slice_id}/{plan.num_slices}",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                res = mt5.order_send(request)
                latency_ms = (time.perf_counter() - t_start) * 1000.0

                if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                    fill_px = float(res.price) if res.price > 0 else px
                    s.fill_price = fill_px
                    s.executed_volume = float(res.volume) if res.volume > 0 else s.target_volume
                    s.status = "FILLED"
                    s.mt5_ticket = int(res.order)
                    s.timestamp_filled = time.time()
                    s.slippage_pts = (fill_px - plan.arrival_price) if plan.direction == OrderDirection.BUY else (plan.arrival_price - fill_px)
                    self._update_plan_metrics(plan, s)
                    print(
                        f"    -> [MT5-FILL] Slice #{s.slice_id}/{plan.num_slices} {plan.direction.value} {s.executed_volume:.2f} "
                        f"@ {fill_px:,.2f} ({latency_ms:.1f}ms | Slippage: {s.slippage_pts:+.2f}p | Ticket: #{s.mt5_ticket})"
                    )
                else:
                    err_code = res.retcode if res else "TIMEOUT"
                    s.status = "FAILED"
                    s.error_msg = f"Retcode: {err_code}"
                    print(f"    -> [MT5-ERROR] Slice #{s.slice_id} falló con código {err_code}")
            except Exception as exc:
                s.status = "FAILED"
                s.error_msg = str(exc)
                print(f"    -> [MT5-EXCEPTION] Slice #{s.slice_id}: {exc}")
        else:
            # Simulación Paper de Nivel 1 Ultra-Realista
            latency_ms = (time.perf_counter() - t_start) * 1000.0 + random.uniform(0.8, 3.2)
            # Simular micro-slippage estocástico en función del spread
            sim_slip = random.gauss(0.0, self.last_spread_pts * 0.15)
            if plan.direction == OrderDirection.BUY:
                fill_px = self.last_spot_price + (self.last_spread_pts * 0.5) + max(0.0, sim_slip)
            else:
                fill_px = self.last_spot_price - (self.last_spread_pts * 0.5) - max(0.0, sim_slip)

            s.fill_price = fill_px
            s.executed_volume = s.target_volume
            s.status = "FILLED"
            s.mt5_ticket = 9000000 + random.randint(1000, 9999)
            s.timestamp_filled = time.time()
            s.slippage_pts = (fill_px - plan.arrival_price) if plan.direction == OrderDirection.BUY else (plan.arrival_price - fill_px)
            self._update_plan_metrics(plan, s)
            print(
                f"    -> [PAPER-FILL] Slice #{s.slice_id}/{plan.num_slices} {plan.direction.value} {s.executed_volume:.2f} "
                f"@ {fill_px:,.2f} (Sim Latency: {latency_ms:.1f}ms | Slippage: {s.slippage_pts:+.2f}p)"
            )

    def _update_plan_metrics(self, plan: ExecutionPlan, s: ChildSlice) -> None:
        """Actualiza el precio promedio ponderado y métricas de slippage del plan."""
        current_total = plan.filled_volume + s.executed_volume
        if current_total > 0:
            plan.weighted_avg_price = (
                (plan.weighted_avg_price * plan.filled_volume) + (s.fill_price * s.executed_volume)
            ) / current_total
        plan.filled_volume = current_total
        plan.total_slippage_pts += s.slippage_pts

        self.stats["total_orders_dispatched"] += 1
        self.stats["total_volume_executed"] += s.executed_volume
        self.stats["total_slippage_pts"] += s.slippage_pts

    def cancel_all_orders(self, reason: str = "MANUAL_CANCEL") -> int:
        """Cancela todas las rebanadas pendientes de ejecución."""
        cancelled_count = 0
        for plan in list(self.active_plans.values()):
            plan.status = PlanStatus.CANCELLED
            for s in plan.slices:
                if s.status in ("PENDING", "EXECUTING"):
                    s.status = "CANCELLED"
                    s.error_msg = f"Cancelled: {reason}"
                    cancelled_count += 1
            self.completed_plans.append(plan)
        self.active_plans.clear()
        print(f"  [EXECUTION-CANCEL] Se cancelaron {cancelled_count} rebanadas activas. Motivo: {reason}")
        return cancelled_count

    def emergency_close_all_positions(self) -> dict[str, Any]:
        """
        FAIL-SAFE CRÍTICO: Cierre de emergencia inmediato de TODAS las posiciones en MT5
        y eliminación de órdenes pendientes.
        """
        closed_positions = []
        removed_orders = []

        # 1. Cancelar rebanadas internas del motor
        self.cancel_all_orders(reason="KILL_SWITCH_EMERGENCY")

        # 2. Cierre forzoso de posiciones vivas en MT5
        if mt5 is not None:
            try:
                positions = mt5.positions_get(symbol=self.symbol)
                if positions:
                    for pos in positions:
                        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        tk = mt5.symbol_info_tick(pos.symbol)
                        close_px = float(tk.bid if close_type == mt5.ORDER_TYPE_SELL else tk.ask) if tk else pos.price_current

                        close_req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "position": pos.ticket,
                            "symbol": pos.symbol,
                            "volume": pos.volume,
                            "type": close_type,
                            "price": close_px,
                            "deviation": 25,
                            "magic": self.magic_number,
                            "comment": "KILL_SWITCH_CLOSE",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        res = mt5.order_send(close_req)
                        closed_positions.append({
                            "ticket": pos.ticket,
                            "volume": pos.volume,
                            "retcode": getattr(res, "retcode", -1) if res else "TIMEOUT"
                        })
                # Eliminar órdenes pendientes en MT5
                orders = mt5.orders_get(symbol=self.symbol)
                if orders:
                    for ord_item in orders:
                        cancel_req = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": ord_item.ticket,
                        }
                        mt5.order_send(cancel_req)
                        removed_orders.append(ord_item.ticket)
            except Exception as exc:
                print(f"  [KILL-SWITCH MT5 EXCEPTION] Error cerrando posiciones en terminal: {exc}")

        return {
            "closed_positions": closed_positions,
            "removed_orders": removed_orders,
            "timestamp": time.time(),
        }

    def halt(self, reason: str) -> None:
        """Detiene de forma irreversible el motor de ejecución."""
        self.is_halted = True
        self.halt_reason = reason
        print(f"\n[ENGINE HALTED] El motor de ejecución ha sido apagado. Motivo: {reason}")
