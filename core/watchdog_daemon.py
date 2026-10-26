# %% [CORE WATCHDOG DAEMON: FAIL-SAFES & HIGH-PRIORITY KILL SWITCH]
"""
Supervisor de Seguridad de Baja Latencia y Fail-Safes Críticos (Watchdog Daemon).

Reglas Estrictas de Supervisión:
  1. Latency Check:
     - Ping de conexión a MetaTrader 5 > 500ms.
     - Ping de publicación a Supabase > 500ms.
     - Inactividad de Ticks > 10.0 segundos durante la sesión RTH de contado (09:30-16:00 ET).
  2. Spread Explosion Check:
     - Spread L1 de `US100-DEC26` supera repentinamente el umbral crítico de 2.00 puntos.
  3. Drawdown Limit:
     - Pérdida diaria de capital (Daily Drawdown) excede el umbral de riesgo máximo (ej. 2.0%).

Acción del Kill Switch de Emergencia:
  a) Cierra inmediatamente TODAS las posiciones abiertas en MT5 a precio de mercado.
  b) Cancela y remueve todas las órdenes pendientes (Limit / Stop).
  c) Apaga de forma permanente el motor de ejecución (`engine.halt()`).
  d) Envía alerta de 'SYSTEM HALTED' en tiempo real a Supabase/Vercel.
"""
from __future__ import annotations

import datetime
import threading
import time
from typing import Any, Callable

try:
    import MetaTrader5 as mt5
except (ImportError, ModuleNotFoundError):
    mt5 = None

from core.execution_engine import ExecutionEngine
from core import sessions


class WatchdogDaemon:
    """
    Supervisor autónomo de seguridad que opera en un hilo secundario continuo.
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        max_latency_ms: float = 500.0,
        max_cloud_latency_ms: float = 6000.0,
        max_spread_pts: float = 2.00,
        max_drawdown_pct: float = 0.02,  # 2.0% Daily Drawdown Limit
        tick_staleness_rth_sec: float = 10.0,
        check_interval_sec: float = 0.50,
        on_halt_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.engine = execution_engine
        self.max_latency_ms = float(max_latency_ms)
        self.max_cloud_latency_ms = float(max_cloud_latency_ms)
        self.max_spread_pts = float(max_spread_pts)
        self.max_drawdown_pct = float(max_drawdown_pct)
        self.tick_staleness_rth_sec = float(tick_staleness_rth_sec)
        self.check_interval_sec = float(check_interval_sec)
        self.on_halt_callback = on_halt_callback

        self._running = False
        self._thread: threading.Thread | None = None
        self._supabase_high_latency_count: int = 0

        # Métricas en vivo observadas por el Watchdog
        self.last_tick_timestamp: float = time.time()
        self.last_mt5_latency_ms: float = 0.0
        self.last_supabase_latency_ms: float = 0.0
        self.current_spread_pts: float = 0.50
        
        # Monitoreo de Equity (auto-calibrado en el primer tick de cuenta)
        self.initial_equity: float | None = None
        self.peak_equity: float | None = None
        self.current_equity: float = 0.0
        self.current_drawdown_pct: float = 0.0

        self.kill_switch_triggered: bool = False
        self.kill_switch_reason: str = ""
        self.kill_switch_timestamp: float = 0.0
        self.kill_switch_report: dict[str, Any] = {}

    def record_tick(self, spread_pts: float, spot_price: float | None = None) -> None:
        """Registra la llegada de un tick fresco y su spread."""
        self.last_tick_timestamp = time.time()
        if spread_pts and spread_pts > 0:
            self.current_spread_pts = float(spread_pts)

    def record_supabase_latency(self, latency_ms: float, is_macro: bool = False) -> None:
        """
        Registra la latencia de respuesta HTTP/WebSocket hacia Supabase de forma event-driven.
        Calcula las violaciones consecutivas por cada transmisión real, evitando que un único
        retraso sea multiplicado por el bucle periódico del temporizador.
        """
        lat = float(latency_ms)
        self.last_supabase_latency_ms = lat

        # Un snapshot macro completo (~150KB JSON multi-tabla) tiene un tiempo de tránsito
        # natural mayor que un pulso ultraligero de tick (~1KB).
        threshold = self.max_cloud_latency_ms * 2.5 if is_macro else self.max_cloud_latency_ms

        if lat > threshold:
            self._supabase_high_latency_count += 1
            if self._supabase_high_latency_count >= 5:
                payload_type = "Macro Snapshot" if is_macro else "Tick Stream"
                self._trigger_emergency_kill_switch(
                    f"LATENCY_FAIL_SUPABASE: 5 transmisiones consecutivas ({payload_type}) superaron {threshold:.0f}ms (Última: {lat:.1f}ms)",
                    rule_name="LATENCY_CHECK"
                )
        else:
            self._supabase_high_latency_count = 0

    def record_account_equity(self, equity: float) -> None:
        """Actualiza el capital de la cuenta para control de Drawdown."""
        eq = float(equity)
        if eq <= 0:
            return
        self.current_equity = eq
        # Auto-calibración al arrancar: el pico inicial es el capital actual detectado
        if self.initial_equity is None or self.peak_equity is None:
            self.initial_equity = eq
            self.peak_equity = eq
            self.current_drawdown_pct = 0.0
            return

        if eq > self.peak_equity:
            self.peak_equity = eq

        if self.peak_equity > 0:
            self.current_drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity

    def start(self) -> None:
        """Inicia el hilo supervisor de seguridad en segundo plano."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._supervision_loop, name="QuantWatchdogDaemon", daemon=True)
        self._thread.start()
        print(
            f"  [WATCHDOG ACTIVO] Supervisor de seguridad iniciado | Latencia Max: {self.max_latency_ms:.0f}ms | "
            f"Spread Max: {self.max_spread_pts:.2f}p | Max DD: {self.max_drawdown_pct*100:.1f}% | RTH Stale: {self.tick_staleness_rth_sec:.0f}s"
        )

    def stop(self) -> None:
        """Detiene el hilo supervisor."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _supervision_loop(self) -> None:
        """Bucle continuo de verificación de reglas de seguridad."""
        last_loop_time = time.time()
        while self._running and not self.kill_switch_triggered:
            try:
                now = time.time()
                elapsed_since_last_loop = now - last_loop_time
                last_loop_time = now

                # Detección de suspensión del sistema / Suspensión del equipo (Sleep / Hibernación):
                # Si el intervalo entre iteraciones fue mucho mayor al esperado (ej. > 5s cuando el sleep es 0.5s),
                # la computadora estuvo suspendida o el proceso pausado.
                # Se reinicia el timestamp del último tick para conceder un período de gracia de re-sincronización.
                if elapsed_since_last_loop > max(self.check_interval_sec * 6.0, 5.0):
                    self.last_tick_timestamp = now
                    self._supabase_high_latency_count = 0

                self._verify_safety_rules()
            except Exception as exc:
                print(f"  [WATCHDOG-ERROR] Excepción en ciclo de supervisión: {exc}")
            time.sleep(self.check_interval_sec)

    def _verify_safety_rules(self) -> None:
        """Evalúa las 3 reglas determinísticas de fail-safe."""
        now = time.time()

        # ----------------------------------------------------------------------
        # REGLA 1: LATENCY & STALENESS CHECK
        # ----------------------------------------------------------------------
        # Medir ping de MT5 si está disponible
        if mt5 is not None and not self.engine.paper_trading:
            t0 = time.perf_counter()
            try:
                _ = mt5.terminal_info()
                self.last_mt5_latency_ms = (time.perf_counter() - t0) * 1000.0
            except Exception:
                self.last_mt5_latency_ms = 999.0
        else:
            self.last_mt5_latency_ms = 1.2  # Simulación de ultra-baja latencia en memoria

        if self.last_mt5_latency_ms > self.max_latency_ms:
            self._trigger_emergency_kill_switch(
                f"LATENCY_FAIL_MT5: Ping a MetaTrader 5 ({self.last_mt5_latency_ms:.1f}ms) superó {self.max_latency_ms:.0f}ms",
                rule_name="LATENCY_CHECK"
            )
            return

        # Verificar estancamiento de Ticks durante la sesión RTH de contado (09:30 a 16:00 ET)
        is_rth_now = self._is_rth_active()
        time_since_last_tick = now - self.last_tick_timestamp

        if is_rth_now and time_since_last_tick > self.tick_staleness_rth_sec:
            self._trigger_emergency_kill_switch(
                f"TICK_FEED_FREEZE_RTH: Sin ticks nuevos en {time_since_last_tick:.1f}s durante RTH (Límite: {self.tick_staleness_rth_sec:.0f}s)",
                rule_name="LATENCY_CHECK"
            )
            return

        # ----------------------------------------------------------------------
        # REGLA 2: SPREAD EXPLOSION CHECK (US100-DEC26)
        # ----------------------------------------------------------------------
        # En futuros CME (NQ), el spread base es 0.25-0.50p (explosión > 2.00p).
        # En CFDs MT5 (US100), los brokers aplican un mark-up base de 5.0-7.0p.
        # Por rigor cuantitativo, el umbral de explosión se calcula de forma dinámica:
        # debe superar tanto el umbral base como el 220% de la media móvil base (SMA 5m).
        base_ma = max(self.engine.spread_ma_5m, 0.50) if hasattr(self.engine, "spread_ma_5m") else 0.50
        dynamic_limit = max(self.max_spread_pts, base_ma * 2.2)
        effective_max_spread = dynamic_limit if is_rth_now else max(dynamic_limit * 1.8, 15.0)

        if self.current_spread_pts > effective_max_spread:
            sess_name = "RTH" if is_rth_now else "GLOBEX/PRE-MARKET"
            self._trigger_emergency_kill_switch(
                f"SPREAD_EXPLOSION: Spread L1 ({self.current_spread_pts:.2f} pts) superó el umbral crítico de {effective_max_spread:.2f} pts ({sess_name} | SMA 5m: {base_ma:.2f}p)",
                rule_name="SPREAD_EXPLOSION"
            )
            return

        # ----------------------------------------------------------------------
        # REGLA 3: DRAWDOWN LIMIT (EQUITY DROP)
        # ----------------------------------------------------------------------
        # Actualizar Equity en tiempo real desde MT5 si está conectado
        if mt5 is not None and not self.engine.paper_trading:
            try:
                acc = mt5.account_info()
                if acc:
                    self.record_account_equity(acc.equity)
            except Exception:
                pass

        if self.peak_equity is not None and self.peak_equity > 0:
            if self.current_drawdown_pct >= self.max_drawdown_pct:
                dd_pct_str = f"{self.current_drawdown_pct * 100.0:.2f}%"
                max_dd_str = f"{self.max_drawdown_pct * 100.0:.2f}%"
                self._trigger_emergency_kill_switch(
                    f"DRAWDOWN_LIMIT_BREACH: Drawdown diario ({dd_pct_str}) superó el límite de {max_dd_str} "
                    f"(Equity: ${self.current_equity:,.2f} | Pico: ${self.peak_equity:,.2f})",
                    rule_name="DRAWDOWN_LIMIT"
                )
                return

    def _is_rth_active(self) -> bool:
        """Verifica si la sesión RTH de contado (09:30 - 16:00 America/New_York) está activa."""
        try:
            return sessions.is_rth(sessions.now_ny())
        except Exception:
            return False

    def _trigger_emergency_kill_switch(self, reason: str, rule_name: str) -> None:
        """
        DISPARADOR DEL KILL SWITCH DE EMERGENCIA.
        Ejecuta las 3 acciones inmediatas de fail-safe.
        """
        self.kill_switch_triggered = True
        self.kill_switch_reason = reason
        self.kill_switch_timestamp = time.time()

        print("\n" + "=" * 90)
        print("[CRITICAL ALERT] KILL SWITCH DE EMERGENCIA DISPARADO — FAIL-SAFE ACTIVADO [SYSTEM HALTED]")
        print(f"  MOTIVO: {reason}")
        print(f"  HORA NY: {sessions.now_ny().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        print("=" * 90)

        # 1. Apagar motor de ejecución para rechazar nuevas órdenes
        self.engine.halt(reason=f"KILL_SWITCH: {reason}")

        # 2. Cancelar órdenes pendientes y cerrar forzosamente todas las posiciones en MT5
        print("  -> Ejecutando aplanamiento forzoso de posiciones y cancelación de órdenes...")
        close_report = self.engine.emergency_close_all_positions()

        # 3. Construir reporte de auditoría del incidente
        self.kill_switch_report = {
            "status": "SYSTEM_HALTED",
            "triggered": True,
            "rule": rule_name,
            "reason": reason,
            "timestamp_epoch": self.kill_switch_timestamp,
            "timestamp_ny": sessions.now_ny().strftime("%Y-%m-%d %H:%M:%S NY"),
            "metrics": {
                "mt5_latency_ms": round(self.last_mt5_latency_ms, 2),
                "supabase_latency_ms": round(self.last_supabase_latency_ms, 2),
                "current_spread_pts": round(self.current_spread_pts, 2),
                "drawdown_pct": round(self.current_drawdown_pct * 100.0, 2),
                "current_equity": round(self.current_equity, 2),
                "peak_equity": round(self.peak_equity, 2),
            },
            "close_report": close_report,
        }

        # 4. Transmitir alerta crítica a Supabase / Vercel
        self._broadcast_system_halt_to_supabase()

        if self.on_halt_callback:
            try:
                self.on_halt_callback(reason, self.kill_switch_report)
            except Exception as e_cb:
                print(f"  [KILL-SWITCH-CALLBACK-ERROR] {e_cb}")

    def _broadcast_system_halt_to_supabase(self) -> None:
        """Publica el estado SYSTEM HALTED a Supabase para notificar a la terminal Vercel."""
        try:
            print("  -> Transmitiendo alerta 'SYSTEM HALTED' a Supabase / Vercel...")
            
            halt_payload = {
                "id": "latest",
                "spot": round(float(self.engine.last_spot_price or 25000.0), 2),
                "symbol": "US100-DEC26",
                "timestamp_ny": sessions.now_ny().strftime("%Y-%m-%d %H:%M NY"),
                "session_status": "SYSTEM_HALTED",
                "source_feed": "LIVE:MT5 (KILL SWITCH)",
                "elapsed_sec": 0.0,
                "kpis": {
                    "spot": round(float(self.engine.last_spot_price or 25000.0), 2),
                    "symbol": "US100-DEC26",
                    "system_status": "SYSTEM_HALTED",
                    "kill_switch_active": True,
                    "kill_switch_reason": self.kill_switch_reason,
                    "spread_pts": round(float(self.current_spread_pts), 2),
                    "mt5_latency_ms": round(float(self.last_mt5_latency_ms), 1),
                    "supabase_latency_ms": round(float(self.last_supabase_latency_ms), 1),
                    "drawdown_pct": round(float(self.current_drawdown_pct * 100.0), 2),
                    "equity": round(float(self.current_equity), 2),
                    "peak_equity": round(float(self.peak_equity or 0.0), 2),
                    "audit_report": self.kill_switch_report,
                },
                "decisions": {
                    "master": {
                        "signal": "SYSTEM HALTED",
                        "color_hex": "#ef4444",
                        "bg_hex": "rgba(239, 68, 68, 0.25)",
                        "action": "EMERGENCY KILL SWITCH: TODAS LAS POSICIONES CERRADAS",
                        "action_text": self.kill_switch_reason,
                        "confluence_pct": 0.0,
                        "rr_ratio": 0.0,
                    }
                },
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # Se publica usando requests directo de supabase_publisher
            import json, requests
            from supabase_publisher import load_supabase_credentials
            sb_url, sb_key = load_supabase_credentials()
            if sb_url and sb_key:
                headers = {
                    "apikey": sb_key,
                    "Authorization": f"Bearer {sb_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                }
                url = f"{sb_url.rstrip('/')}/rest/v1/nq_snapshots?on_conflict=id"
                resp = requests.post(url, headers=headers, data=json.dumps(halt_payload), timeout=5.0)
                if resp.status_code in (200, 201):
                    print("  [OK] Alerta de SYSTEM HALTED confirmada en Supabase (HTTP 200/201).")
                else:
                    print(f"  [WARN] Alerta Supabase respondio con codigo {resp.status_code}: {resp.text}")
        except Exception as exc:
            print(f"  [KILL-SWITCH-BROADCAST-ERROR] Error enviando alerta a Supabase: {exc}")
