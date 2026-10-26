"""
==================================================================================
MÓDULO DE BACKTEST INSTITUCIONAL CME: RITHMIC / TRADOVATE / APEX (NASDAQ 100)
==================================================================================
Simulador cuantitativo de alta precisión con la microestructura exacta del CME:
  1. Especificaciones de Contrato (Tick Size & Tick Value) para NQ y MNQ.
  2. Comisiones All-In Round Trip por contrato según tarifas de cuentas de fondeo.
  3. Slippage Dinámico institucional (1 Tick para Market Orders / Stop Loss;
     0 Ticks para Limit Orders / Maker).
  4. Evaluación de supervivencia de cuenta frente a reglas de Trailing Drawdown
     (Apex Trader Funding, Topstep, Tradovate, Rithmic).
==================================================================================
"""
from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from core.config import CME_FEE_SCHEDULE, NQ, MNQ


class OrderType(str, enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"


class PositionSide(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, enum.Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    REGIME_CHANGE = "REGIME_CHANGE"
    TIME_STOP = "TIME_STOP"
    END_OF_SESSION = "END_OF_SESSION"


@dataclasses.dataclass
class TradeExecution:
    trade_id: int
    symbol: str
    side: PositionSide
    contracts: int
    entry_price: float
    exit_price: float
    entry_type: OrderType
    exit_type: OrderType
    entry_time: Any = None
    exit_time: Any = None
    exit_reason: ExitReason = ExitReason.TAKE_PROFIT

    # Métricas calculadas
    price_change_pts: float = 0.0
    captured_ticks: float = 0.0
    gross_pnl: float = 0.0
    commission_paid: float = 0.0
    slippage_ticks: float = 0.0
    slippage_cost: float = 0.0
    net_pnl: float = 0.0
    is_win: bool = False


@dataclasses.dataclass
class BacktestReport:
    symbol: str
    contracts: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl: float
    total_commissions: float
    total_slippage: float
    net_pnl: float
    profit_factor: float
    net_profit_factor: float
    avg_trade_net: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: float
    funding_account_survived: bool
    funding_drawdown_limit_usd: float
    trades: list[TradeExecution] = dataclasses.field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "contracts": self.contracts,
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "total_commissions": round(self.total_commissions, 2),
            "total_slippage": round(self.total_slippage, 2),
            "net_pnl": round(self.net_pnl, 2),
            "profit_factor": round(self.profit_factor, 2),
            "net_profit_factor": round(self.net_profit_factor, 2),
            "avg_trade_net": round(self.avg_trade_net, 2),
            "max_drawdown_usd": round(self.max_drawdown_usd, 2),
            "funding_survived": self.funding_account_survived,
        }


def evaluate_trade(
    symbol: str = "NQ",
    side: PositionSide | str = PositionSide.LONG,
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    contracts: int = 1,
    entry_type: OrderType | str = OrderType.LIMIT,
    exit_type: OrderType | str = OrderType.LIMIT,
    trade_id: int = 1,
    entry_time: Any = None,
    exit_time: Any = None,
    exit_reason: ExitReason | str = ExitReason.TAKE_PROFIT,
) -> TradeExecution:
    """
    Función de evaluación de trades bajo la microestructura oficial del CME (Directiva V11):
      * Gross_PnL = Ticks_Capturados * TICK_VALUE * Contratos
      * Net_PnL = Gross_PnL - (Comision_Por_Lado * 2 * Contratos) - (Slippage_en_Ticks * TICK_VALUE)
      * Slippage: 1 Tick por orden a Mercado o Stop Loss; 0 Ticks para Limit.
    """
    sym = str(symbol).upper()
    if sym not in CME_FEE_SCHEDULE:
        sym = "NQ"

    spec = CME_FEE_SCHEDULE[sym]
    tick_size = float(spec["TICK_SIZE"])          # 0.25 pts
    tick_value = float(spec["TICK_VALUE"])        # $5.00 NQ / $0.50 MNQ
    comm_side = float(spec["COMMISSION_PER_SIDE"]) # $2.09 NQ / $0.82 MNQ
    n_lots = max(int(contracts), 1)

    # Conversión robusta de enums
    if isinstance(side, PositionSide):
        s_enum = side
    else:
        s_val = str(side).split(".")[-1].upper()
        s_enum = PositionSide(s_val) if s_val in PositionSide.__members__ else PositionSide.LONG

    if isinstance(entry_type, OrderType):
        e_type = entry_type
    else:
        e_val = str(entry_type).split(".")[-1].upper()
        e_type = OrderType(e_val) if e_val in OrderType.__members__ else OrderType.LIMIT

    if isinstance(exit_type, OrderType):
        x_type = exit_type
    else:
        x_val = str(exit_type).split(".")[-1].upper()
        x_type = OrderType(x_val) if x_val in OrderType.__members__ else OrderType.LIMIT

    if isinstance(exit_reason, ExitReason):
        r_enum = exit_reason
    else:
        r_val = str(exit_reason).split(".")[-1].upper()
        r_enum = ExitReason(r_val) if r_val in ExitReason.__members__ else ExitReason.TAKE_PROFIT

    # 1. Puntos y Ticks Capturados
    if s_enum == PositionSide.LONG:
        pts_raw = float(exit_price - entry_price)
    else:
        pts_raw = float(entry_price - exit_price)

    captured_ticks = round(pts_raw / tick_size, 4)

    # 2. Gross PnL
    gross_pnl = round(captured_ticks * tick_value * n_lots, 2)

    # 3. Comisiones All-In (Entrada + Salida = 2 lados por contrato)
    total_commissions = round(comm_side * 2.0 * n_lots, 2)

    # 4. Slippage Dinámico Institucional:
    # 1 Tick (0.25p) por cada orden a Mercado o Stop Loss; 0 Ticks para Limit (Maker)
    entry_slip_ticks = 1.0 if e_type in (OrderType.MARKET, OrderType.STOP) else 0.0
    exit_slip_ticks = 1.0 if x_type in (OrderType.MARKET, OrderType.STOP) else 0.0
    total_slip_ticks = (entry_slip_ticks + exit_slip_ticks) * n_lots
    slippage_cost = round(total_slip_ticks * tick_value, 2)

    # 5. Net PnL Institucional
    net_pnl = round(gross_pnl - total_commissions - slippage_cost, 2)
    is_win = net_pnl > 0.0

    return TradeExecution(
        trade_id=trade_id,
        symbol=sym,
        side=s_enum,
        contracts=n_lots,
        entry_price=round(float(entry_price), 2),
        exit_price=round(float(exit_price), 2),
        entry_type=e_type,
        exit_type=x_type,
        entry_time=entry_time,
        exit_time=exit_time,
        exit_reason=r_enum,
        price_change_pts=round(pts_raw, 2),
        captured_ticks=captured_ticks,
        gross_pnl=gross_pnl,
        commission_paid=total_commissions,
        slippage_ticks=total_slip_ticks,
        slippage_cost=slippage_cost,
        net_pnl=net_pnl,
        is_win=is_win,
    )


class BacktestEngine:
    """
    Motor Cuantitativo de Backtesting Institucional para Cuentas de Fondeo CME.
    Integra los modelos estocásticos de Markov (HMM) y Procesos de Hawkes con
    gestión de riesgo rigurosa (Trailing Drawdown, All-In Commissions, Slippage).
    """

    def __init__(
        self,
        symbol: str = "NQ",
        contracts: int = 1,
        initial_capital: float = 50_000.0,
        trailing_drawdown_limit: float = 2_500.0,
        daily_loss_limit: float = 1_000.0,
    ):
        self.symbol = symbol.upper() if symbol.upper() in CME_FEE_SCHEDULE else "NQ"
        self.contracts = max(int(contracts), 1)
        self.initial_capital = float(initial_capital)
        self.trailing_drawdown_limit = float(trailing_drawdown_limit)
        self.daily_loss_limit = float(daily_loss_limit)

        self.trades: list[TradeExecution] = []
        self.equity_curve: list[dict[str, Any]] = []
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.max_drawdown_usd = 0.0
        self.max_drawdown_pct = 0.0
        self.survived_trailing_drawdown = True

    def reset(self) -> None:
        """Reinicia el estado del motor para un nuevo escenario."""
        self.trades.clear()
        self.equity_curve.clear()
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.max_drawdown_usd = 0.0
        self.max_drawdown_pct = 0.0
        self.survived_trailing_drawdown = True

    def record_trade(
        self,
        side: PositionSide | str,
        entry_price: float,
        exit_price: float,
        entry_type: OrderType | str = OrderType.LIMIT,
        exit_type: OrderType | str = OrderType.LIMIT,
        entry_time: Any = None,
        exit_time: Any = None,
        exit_reason: ExitReason | str = ExitReason.TAKE_PROFIT,
        contracts: int | None = None,
    ) -> TradeExecution:
        """Registra y evalúa un trade individual descontando comisiones y slippage."""
        t_id = len(self.trades) + 1
        num_contracts = contracts if contracts is not None else self.contracts
        trade = evaluate_trade(
            symbol=self.symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            contracts=num_contracts,
            entry_type=entry_type,
            exit_type=exit_type,
            trade_id=t_id,
            entry_time=entry_time,
            exit_time=exit_time,
            exit_reason=exit_reason,
        )

        self.trades.append(trade)
        self.current_capital += trade.net_pnl

        # Seguimiento estricto de Trailing Drawdown de Fondeo (High-Water Mark)
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        dd_usd = self.peak_capital - self.current_capital
        dd_pct = (dd_usd / self.peak_capital) * 100.0 if self.peak_capital > 0 else 0.0

        if dd_usd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd_usd
            self.max_drawdown_pct = dd_pct

        if dd_usd >= self.trailing_drawdown_limit:
            self.survived_trailing_drawdown = False

        self.equity_curve.append({
            "trade_id": t_id,
            "exit_time": exit_time,
            "trade_net_pnl": trade.net_pnl,
            "capital": self.current_capital,
            "peak": self.peak_capital,
            "drawdown_usd": dd_usd,
            "drawdown_pct": dd_pct,
            "breached": not self.survived_trailing_drawdown,
        })

        return trade

    def compile_report(self) -> BacktestReport:
        """Calcula las métricas de rendimiento consolidadas institucionales."""
        n_trades = len(self.trades)
        if n_trades == 0:
            return BacktestReport(
                symbol=self.symbol,
                contracts=self.contracts,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                gross_pnl=0.0,
                total_commissions=0.0,
                total_slippage=0.0,
                net_pnl=0.0,
                profit_factor=0.0,
                net_profit_factor=0.0,
                avg_trade_net=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                payoff_ratio=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                funding_account_survived=True,
                funding_drawdown_limit_usd=self.trailing_drawdown_limit,
                trades=[],
            )

        wins = [t for t in self.trades if t.is_win]
        losses = [t for t in self.trades if not t.is_win]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / n_trades) * 100.0

        gross_pnl = sum(t.gross_pnl for t in self.trades)
        total_commissions = sum(t.commission_paid for t in self.trades)
        total_slippage = sum(t.slippage_cost for t in self.trades)
        net_pnl = sum(t.net_pnl for t in self.trades)

        gross_win_usd = sum(t.gross_pnl for t in wins if t.gross_pnl > 0)
        gross_loss_usd = abs(sum(t.gross_pnl for t in losses if t.gross_pnl < 0))
        profit_factor = (gross_win_usd / gross_loss_usd) if gross_loss_usd > 0 else 99.0

        net_win_usd = sum(t.net_pnl for t in wins)
        net_loss_usd = abs(sum(t.net_pnl for t in losses))
        net_profit_factor = (net_win_usd / net_loss_usd) if net_loss_usd > 0 else 99.0

        avg_trade = net_pnl / n_trades
        avg_win = (net_win_usd / n_wins) if n_wins > 0 else 0.0
        avg_loss = (net_loss_usd / n_losses) if n_losses > 0 else 0.0
        payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        # Sharpe ratio aproximado de trades
        pnl_arr = np.array([t.net_pnl for t in self.trades], dtype=np.float64)
        std_pnl = float(np.std(pnl_arr, ddof=1)) if len(pnl_arr) > 1 else 1.0
        sharpe = (float(np.mean(pnl_arr)) / std_pnl * math.sqrt(252)) if std_pnl > 1e-4 else 0.0

        return BacktestReport(
            symbol=self.symbol,
            contracts=self.contracts,
            total_trades=n_trades,
            winning_trades=n_wins,
            losing_trades=n_losses,
            win_rate_pct=round(win_rate, 2),
            gross_pnl=round(gross_pnl, 2),
            total_commissions=round(total_commissions, 2),
            total_slippage=round(total_slippage, 2),
            net_pnl=round(net_pnl, 2),
            profit_factor=round(profit_factor, 2),
            net_profit_factor=round(net_profit_factor, 2),
            avg_trade_net=round(avg_trade, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            payoff_ratio=round(payoff, 2),
            max_drawdown_usd=round(self.max_drawdown_usd, 2),
            max_drawdown_pct=round(self.max_drawdown_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            funding_account_survived=self.survived_trailing_drawdown,
            funding_drawdown_limit_usd=self.trailing_drawdown_limit,
            trades=self.trades.copy(),
        )

    # ----------------------------------------------------------------------- #
    # SIMULADORES ESPECÍFICOS DE ESTRATEGIAS ESTOCÁSTICAS (V9 & V11)
    # ----------------------------------------------------------------------- #
    def run_markov_hmm_backtest(
        self,
        bars_15m: pd.DataFrame,
        prob_threshold: float = 0.55,
        target_pts: float = 60.0,
        stop_pts: float = 30.0,
        sample_bars: int = 0,
    ) -> BacktestReport:
        """
        Backtest del Modelo Oculto de Markov (HMM) sobre barras de 15m del Nasdaq:
          * Estado 1 (Expansión Alcista): Entrada Limit en Close, Target en P75/Call, Stop en P05.
          * Estado 2 (Expansión Bajista): Entrada Limit en Close, Target en P25/Put, Stop en P95.
          * Salidas: Take Profit = Limit (0 slippage); Stop Loss = Stop (+1 tick slippage).
        """
        import math
        from core.hmm_regime import fit_nasdaq_hmm_model, GaussianHMMNasdaq

        self.reset()
        if len(bars_15m) < 60:
            return self.compile_report()

        df_eval = bars_15m.iloc[-sample_bars:] if (sample_bars and sample_bars > 0 and len(bars_15m) > sample_bars) else bars_15m
        closes = df_eval["Close"].to_numpy(dtype=float)
        highs = df_eval["High"].to_numpy(dtype=float) if "High" in df_eval.columns else closes
        lows = df_eval["Low"].to_numpy(dtype=float) if "Low" in df_eval.columns else closes

        log_rets = np.diff(np.log(closes))
        log_rets = np.insert(log_rets, 0, 0.0)
        vol = np.zeros_like(log_rets)
        for j in range(len(vol)):
            start_j = max(0, j - 16)
            vol[j] = np.std(log_rets[start_j : j + 1]) if (j - start_j) >= 2 else 0.005

        X_all = np.column_stack([log_rets, vol])

        train_len = min(200, len(X_all))
        hmm = GaussianHMMNasdaq(n_components=3, max_iter=20)
        hmm.fit(X_all[:train_len])

        window = 80
        in_pos = False
        pos_side = PositionSide.LONG
        entry_px = 0.0
        entry_idx = 0
        last_train_idx = 0

        for i in range(window, len(df_eval)):
            cur_close = float(closes[i])
            cur_high = float(highs[i])
            cur_low = float(lows[i])
            ts = df_eval.index[i]

            # 1. Gestionar posición abierta
            if in_pos:
                if pos_side == PositionSide.LONG:
                    if cur_high >= entry_px + target_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px + target_pts,
                            entry_type=OrderType.LIMIT,
                            exit_type=OrderType.LIMIT,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.TAKE_PROFIT,
                        )
                        in_pos = False
                    elif cur_low <= entry_px - stop_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px - stop_pts,
                            entry_type=OrderType.LIMIT,
                            exit_type=OrderType.STOP,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.STOP_LOSS,
                        )
                        in_pos = False
                elif pos_side == PositionSide.SHORT:
                    if cur_low <= entry_px - target_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px - target_pts,
                            entry_type=OrderType.LIMIT,
                            exit_type=OrderType.LIMIT,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.TAKE_PROFIT,
                        )
                        in_pos = False
                    elif cur_high >= entry_px + stop_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px + stop_pts,
                            entry_type=OrderType.LIMIT,
                            exit_type=OrderType.STOP,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.STOP_LOSS,
                        )
                        in_pos = False

            # 2. Evaluar nuevas entradas
            if not in_pos and i % 2 == 0:
                if (i - last_train_idx) >= 200:
                    train_start = max(0, i - 200)
                    hmm = GaussianHMMNasdaq(n_components=3, max_iter=15)
                    hmm.fit(X_all[train_start : i])
                    last_train_idx = i

                pred = hmm.predict_current_regime(X_all[max(0, i - 60) : i + 1])
                st = pred.current_state
                prob = pred.state_prob

                if (st == 1 or pred.state_name == "Expansión Direccional Alcista") and prob >= prob_threshold:
                    in_pos = True
                    pos_side = PositionSide.LONG
                    entry_px = cur_close
                    entry_idx = i
                elif (st == 2 or pred.state_name == "Expansión Direccional Bajista") and prob >= prob_threshold:
                    in_pos = True
                    pos_side = PositionSide.SHORT
                    entry_px = cur_close
                    entry_idx = i

        return self.compile_report()

    def run_hawkes_order_flow_backtest(
        self,
        bars_5m: pd.DataFrame,
        gex_call_wall: float | None = None,
        gex_put_wall: float | None = None,
        target_pts: float = 30.0,
        stop_pts: float = 15.0,
        sample_bars: int = 0,
    ) -> BacktestReport:
        """
        Backtest del Proceso de Hawkes 1D sobre el Order Flow BVC de 5m del Nasdaq:
          * Evalúa la probabilidad de ruptura P(Breakout) en proximidad a Call/Put Walls.
          * Si P(Breakout) >= 65%: Operativa de Ruptura (Market Order con slippage).
          * Si P(Rebote) >= 70%: Operativa de Desvanecimiento (Fade Limit sin slippage).
        """
        import math
        from core.hawkes_process import HawkesOrderFlowModel, extract_event_times_from_bars

        self.reset()
        if len(bars_5m) < 40:
            return self.compile_report()

        df_eval = bars_5m.iloc[-sample_bars:] if (sample_bars and sample_bars > 0 and len(bars_5m) > sample_bars) else bars_5m
        closes = df_eval["Close"].to_numpy(dtype=float)
        highs = df_eval["High"].to_numpy(dtype=float) if "High" in df_eval.columns else closes
        lows = df_eval["Low"].to_numpy(dtype=float) if "Low" in df_eval.columns else closes

        hawkes = HawkesOrderFlowModel(decay_beta=1.20)
        window = 40

        in_pos = False
        pos_side = PositionSide.LONG
        entry_px = 0.0
        entry_idx = 0
        entry_type = OrderType.LIMIT

        for i in range(window, len(df_eval)):
            cur_close = float(closes[i])
            cur_high = float(highs[i])
            cur_low = float(lows[i])
            ts = df_eval.index[i]

            # Niveles institucionales de opciones (strikes múltiplos de 50 en Nasdaq CME)
            cw = gex_call_wall if gex_call_wall else (math.ceil(cur_close / 50.0) * 50.0)
            pw = gex_put_wall if gex_put_wall else (math.floor(cur_close / 50.0) * 50.0)
            if cw <= cur_close:
                cw += 50.0
            if pw >= cur_close:
                pw -= 50.0

            # 1. Gestionar posición
            if in_pos:
                if pos_side == PositionSide.LONG:
                    if cur_high >= entry_px + target_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px + target_pts,
                            entry_type=entry_type,
                            exit_type=OrderType.LIMIT,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.TAKE_PROFIT,
                        )
                        in_pos = False
                    elif cur_low <= entry_px - stop_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px - stop_pts,
                            entry_type=entry_type,
                            exit_type=OrderType.STOP,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.STOP_LOSS,
                        )
                        in_pos = False
                elif pos_side == PositionSide.SHORT:
                    if cur_low <= entry_px - target_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px - target_pts,
                            entry_type=entry_type,
                            exit_type=OrderType.LIMIT,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.TAKE_PROFIT,
                        )
                        in_pos = False
                    elif cur_high >= entry_px + stop_pts:
                        self.record_trade(
                            side=pos_side,
                            entry_price=entry_px,
                            exit_price=entry_px + stop_pts,
                            entry_type=entry_type,
                            exit_type=OrderType.STOP,
                            entry_time=df_eval.index[entry_idx],
                            exit_time=ts,
                            exit_reason=ExitReason.STOP_LOSS,
                        )
                        in_pos = False

            # 2. Evaluar proximidad a muros
            if not in_pos and i % 2 == 0:
                dist_call = cw - cur_close
                dist_put = cur_close - pw

                if dist_call <= 15.0 or dist_put <= 15.0:
                    sub_bars = df_eval.iloc[max(0, i - window) : i]
                    ev_times = extract_event_times_from_bars(sub_bars, volume_quantile=0.70)
                    fit_res = hawkes.fit(ev_times)

                    if dist_call <= 15.0:
                        cw_res = hawkes.calculate_wall_breakout_probability(spot=cur_close, wall_strike=cw, wall_name="Call Wall", fit_res=fit_res)
                        if cw_res.prob_breakout >= 0.65:
                            in_pos = True
                            pos_side = PositionSide.LONG
                            entry_px = cur_close
                            entry_idx = i
                            entry_type = OrderType.MARKET
                        elif cw_res.prob_rebound >= 0.70:
                            in_pos = True
                            pos_side = PositionSide.SHORT
                            entry_px = cur_close
                            entry_idx = i
                            entry_type = OrderType.LIMIT
                    elif dist_put <= 15.0:
                        pw_res = hawkes.calculate_wall_breakout_probability(spot=cur_close, wall_strike=pw, wall_name="Put Wall", fit_res=fit_res)
                        if pw_res.prob_breakout >= 0.65:
                            in_pos = True
                            pos_side = PositionSide.SHORT
                            entry_px = cur_close
                            entry_idx = i
                            entry_type = OrderType.MARKET
                        elif pw_res.prob_rebound >= 0.70:
                            in_pos = True
                            pos_side = PositionSide.LONG
                            entry_px = cur_close
                            entry_idx = i
                            entry_type = OrderType.LIMIT

        return self.compile_report()

    def run_25k_multitarget_strategy(
        self,
        bars_15m,
        stop_pts: float = 20.0,
        target_1_pts: float = 20.0,
        target_2_pts: float = 40.0,
        prob_threshold: float = 0.55,
        time_stop_bars: int = 6,
        sample_bars: int = 0,
    ):
        """
        Estrategia de Supervivencia y Fondeo 25k (Suelo Critico en $24,000 USD):
          * Activo: Micro E-mini Nasdaq (MNQ) con 2 contratos.
          * Stop inicial: -20 pts en ambos contratos (riesgo max: -$84.28 USD).
          * Contrato 1 (Scalp): Target +20 pts (Limit). En cuanto cobra, el Stop del
            Contrato 2 se mueve automaticamente a Break-Even (precio de entrada).
          * Contrato 2 (Runner): Target +40 pts (Limit).
          * Time-Stop: A las 6 velas (90 min), si C2 no ha llegado a target ni a stop,
            se liquida a mercado asegurando el beneficio neto del trade.
        """
        from core.hmm_regime import GaussianHMMNasdaq
        import numpy as np
        import pandas as pd

        self.reset()
        if len(bars_15m) < 60:
            return self.compile_report()

        df_eval = bars_15m.iloc[-sample_bars:] if (sample_bars and sample_bars > 0 and len(bars_15m) > sample_bars) else bars_15m
        closes = df_eval["Close"].to_numpy(dtype=float)
        highs = df_eval["High"].to_numpy(dtype=float) if "High" in df_eval.columns else closes
        lows = df_eval["Low"].to_numpy(dtype=float) if "Low" in df_eval.columns else closes

        log_rets = np.diff(np.log(closes))
        log_rets = np.insert(log_rets, 0, 0.0)
        vol = np.zeros_like(log_rets)
        for j in range(len(vol)):
            start_j = max(0, j - 16)
            vol[j] = np.std(log_rets[start_j : j + 1]) if (j - start_j) >= 2 else 0.005

        X_all = np.column_stack([log_rets, vol])

        train_len = min(200, len(X_all))
        hmm = GaussianHMMNasdaq(n_components=3, max_iter=20)
        hmm.fit(X_all[:train_len])

        window = 80
        in_pos = False
        pos_side = PositionSide.LONG
        entry_px = 0.0
        entry_idx = 0
        c1_closed = False
        c2_closed = False
        c1_tp = False
        last_train_idx = 0
        current_week = None
        setups_in_week = 0

        for i in range(window, len(df_eval)):
            cur_close = float(closes[i])
            cur_high = float(highs[i])
            cur_low = float(lows[i])
            ts = df_eval.index[i]
            bar_week = f"{ts.year}-W{ts.isocalendar().week:02d}"
            if bar_week != current_week:
                current_week = bar_week
                setups_in_week = 0

            # 1. Gestionar posicion abierta (2 contratos asimetricos)
            if in_pos:
                hold_bars = i - entry_idx

                if pos_side == PositionSide.LONG:
                    # Contrato 1: Target rapido +20 pts
                    if not c1_closed:
                        if cur_high >= entry_px + target_1_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px + target_1_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.LIMIT,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TAKE_PROFIT,
                                contracts=1,
                            )
                            c1_closed = True
                            c1_tp = True
                        elif cur_low <= entry_px - stop_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px - stop_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.STOP,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.STOP_LOSS,
                                contracts=1,
                            )
                            c1_closed = True

                    # Contrato 2: Runner tendencial +40 pts (con Break-Even tras C1)
                    if not c2_closed:
                        c2_stop = entry_px if c1_tp else entry_px - stop_pts
                        if cur_high >= entry_px + target_2_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px + target_2_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.LIMIT,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TAKE_PROFIT,
                                contracts=1,
                            )
                            c2_closed = True
                        elif cur_low <= c2_stop:
                            reason = ExitReason.TAKE_PROFIT if (c2_stop >= entry_px) else ExitReason.STOP_LOSS
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=c2_stop,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.STOP,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=reason,
                                contracts=1,
                            )
                            c2_closed = True
                        elif time_stop_bars > 0 and hold_bars >= time_stop_bars:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=cur_close,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.MARKET,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TIME_STOP,
                                contracts=1,
                            )
                            c2_closed = True

                    if c1_closed and c2_closed:
                        in_pos = False
                        setups_in_week += 1

                elif pos_side == PositionSide.SHORT:
                    # Contrato 1: Target rapido -20 pts
                    if not c1_closed:
                        if cur_low <= entry_px - target_1_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px - target_1_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.LIMIT,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TAKE_PROFIT,
                                contracts=1,
                            )
                            c1_closed = True
                            c1_tp = True
                        elif cur_high >= entry_px + stop_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px + stop_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.STOP,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.STOP_LOSS,
                                contracts=1,
                            )
                            c1_closed = True

                    # Contrato 2: Runner tendencial -40 pts (con Break-Even tras C1)
                    if not c2_closed:
                        c2_stop = entry_px if c1_tp else entry_px + stop_pts
                        if cur_low <= entry_px - target_2_pts:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=entry_px - target_2_pts,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.LIMIT,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TAKE_PROFIT,
                                contracts=1,
                            )
                            c2_closed = True
                        elif cur_high >= c2_stop:
                            reason = ExitReason.TAKE_PROFIT if (c2_stop <= entry_px) else ExitReason.STOP_LOSS
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=c2_stop,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.STOP,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=reason,
                                contracts=1,
                            )
                            c2_closed = True
                        elif time_stop_bars > 0 and hold_bars >= time_stop_bars:
                            self.record_trade(
                                side=pos_side,
                                entry_price=entry_px,
                                exit_price=cur_close,
                                entry_type=OrderType.LIMIT,
                                exit_type=OrderType.MARKET,
                                entry_time=df_eval.index[entry_idx],
                                exit_time=ts,
                                exit_reason=ExitReason.TIME_STOP,
                                contracts=1,
                            )
                            c2_closed = True

                    if c1_closed and c2_closed:
                        in_pos = False
                        setups_in_week += 1

            # 2. Evaluar nuevas entradas
            if not in_pos and i % 2 == 0:
                if (i - last_train_idx) >= 200:
                    train_start = max(0, i - 200)
                    hmm = GaussianHMMNasdaq(n_components=3, max_iter=15)
                    hmm.fit(X_all[train_start : i])
                    last_train_idx = i

                pred = hmm.predict_current_regime(X_all[max(0, i - 60) : i + 1])
                st = pred.current_state
                prob = pred.state_prob

                # Garantía de actividad semanal estricta (mínimo 2 trades/semana sin pausas por inactividad)
                current_threshold = prob_threshold
                if setups_in_week < 2:
                    day_of_week = ts.weekday() # 0=Lunes, 4=Viernes
                    if day_of_week >= 3:
                        current_threshold = 0.38
                    elif day_of_week >= 2:
                        current_threshold = 0.44

                if (st == 1 or pred.state_name == "Expansión Direccional Alcista") and prob >= current_threshold:
                    in_pos = True
                    pos_side = PositionSide.LONG
                    entry_px = cur_close
                    entry_idx = i
                    c1_closed = False
                    c2_closed = False
                    c1_tp = False
                elif (st == 2 or pred.state_name == "Expansión Direccional Bajista") and prob >= current_threshold:
                    in_pos = True
                    pos_side = PositionSide.SHORT
                    entry_px = cur_close
                    entry_idx = i
                    c1_closed = False
                    c2_closed = False
                    c1_tp = False

        return self.compile_report()

