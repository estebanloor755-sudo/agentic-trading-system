#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
==================================================================================
SIMULADOR & MOTOR DE BACKTEST CUANTITATIVO CME (NASDAQ 100 — NQ & MNQ)
==================================================================================
Directiva Maestra V11: Microestructura CME y Comisiones de Fondeo (Rithmic/Tradovate).
==================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.backtest_engine import (
    BacktestEngine,
    BacktestReport,
    CME_FEE_SCHEDULE,
    ExitReason,
    OrderType,
    PositionSide,
    TradeExecution,
    evaluate_trade,
)
from core.config import CONTRACTS
from core.tables import Table, banner, section
from data_feed_nq import DataFeedNQ


def print_backtest_summary(report: BacktestReport, initial_capital: float = 50_000.0) -> None:
    """Imprime en consola un reporte institucional de alto rigor para cuentas de fondeo."""
    GREEN = "\033[92m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    GOLD = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    pnl_col = GREEN if report.net_pnl >= 0 else RED
    surv_col = GREEN if report.funding_account_survived else RED
    surv_str = f"{surv_col}{'✓ SUPERVIVENCIA EXITOSA (DENTRO DEL LÍMITE)' if report.funding_account_survived else '⚠️ REGLA VIOLADA: LÍMITE DE TRAILING DRAWDOWN SUPERADO'}{RESET}"

    spec = CME_FEE_SCHEDULE.get(report.symbol, CME_FEE_SCHEDULE["NQ"])

    print("\n" + banner(
        f"REPORTE INSTITUCIONAL DE BACKTESTING CME ({spec['NAME']} — {report.symbol})",
        f"Contratos: {report.contracts} | Comisiones: ${spec['COMMISSION_PER_SIDE']:.2f}/lado (${spec['ROUND_TRIP_COMMISSION']:.2f} RT) | "
        f"Tick: {spec['TICK_SIZE']}p (${spec['TICK_VALUE']:.2f}) | Fricción All-In Rithmic/Tradovate",
        width=120,
    ))

    print(section("1. MÉTRICAS DE PNL Y COSTES DE FRICCIÓN FINANCIERA", width=120))
    t_pnl = Table(
        ["Métrica de Fricción", "Valor en USD", "Impacto / Detalle Operativo"],
        aligns="lrr",
    )
    t_pnl.add_row(["Gross PnL (Bruto de Mercado)", f"${report.gross_pnl:+,.2f}", f"{report.total_trades} trades ejecutados"])
    t_pnl.add_row(["Comisiones All-In (Entrada + Salida)", f"-${report.total_commissions:,.2f}", f"${spec['COMMISSION_PER_SIDE']:.2f}/lado x {report.contracts} x 2 RT"])
    t_pnl.add_row(["Slippage Dinámico (Fricción de Liquidez)", f"-${report.total_slippage:,.2f}", "1 Tick en Market/Stop, 0 Ticks en Limit"])
    t_pnl.add_row(["Net PnL (Beneficio Neto Real)", f"{pnl_col}${report.net_pnl:+,.2f}{RESET}", f"Rentabilidad sobre cuenta: {(report.net_pnl/initial_capital)*100:+.2f}%"])
    t_pnl.add_row(["Profit Factor Bruto", f"{report.profit_factor:.2f}x", "Ganancia Bruta / Pérdida Bruta"])
    t_pnl.add_row(["Profit Factor Neto Institucional", f"{report.net_profit_factor:.2f}x", "Ganancia Neta / Pérdida Neta tras Comisiones"])
    print(t_pnl.render())

    print("\n" + section("2. GESTIÓN DE RIESGO & SUPERVIVENCIA DE CUENTA DE FONDEO", width=120))
    t_risk = Table(
        ["Parámetro de Supervivencia", "Valor Registrado", "Límite / Regla de Cuenta"],
        aligns="lrr",
    )
    t_risk.add_row(["Win Rate (Tasa de Acierto)", f"{report.win_rate_pct:.1f}%", f"{report.winning_trades}W / {report.losing_trades}L"])
    t_risk.add_row(["Avg Trade Net", f"${report.avg_trade_net:+,.2f}", "Expectativa matemática por operación"])
    t_risk.add_row(["Payoff Ratio (Avg Win / Avg Loss)", f"{report.payoff_ratio:.2f}x", f"+${report.avg_win:,.2f} / -${report.avg_loss:,.2f}"])
    t_risk.add_row(["Max Trailing Drawdown ($)", f"${report.max_drawdown_usd:,.2f}", f"Límite Máximo: ${report.funding_drawdown_limit_usd:,.2f}"])
    t_risk.add_row(["Max Drawdown (%)", f"{report.max_drawdown_pct:.2f}%", "Desde el High-Water Mark"])
    t_risk.add_row(["Sharpe Ratio Anualizado", f"{report.sharpe_ratio:.2f}", "Retorno ajustado por volatilidad"])
    t_risk.add_row(["Estado de Cuenta de Fondeo", surv_str, "Apex / Tradovate Trailing Threshold"])
    print(t_risk.render())

    if len(report.trades) > 0:
        print("\n" + section("3. ÚLTIMOS TRADES EJECUTADOS (AUDITORÍA DE PRECISIÓN DE TICK)", width=120))
        t_trades = Table(
            ["#", "Lado", "Entrada", "Salida", "Ticks", "Gross PnL", "Comisión", "Slippage", "Net PnL", "Razón Salida"],
            aligns="rllrrrrrrl",
        )
        for tr in report.trades[-12:]:
            net_c = GREEN if tr.is_win else RED
            t_trades.add_row([
                str(tr.trade_id),
                tr.side.value,
                f"{tr.entry_price:,.2f} ({tr.entry_type.value})",
                f"{tr.exit_price:,.2f} ({tr.exit_type.value})",
                f"{tr.captured_ticks:+.1f}t",
                f"${tr.gross_pnl:+,.2f}",
                f"-${tr.commission_paid:,.2f}",
                f"-${tr.slippage_cost:,.2f}",
                f"{net_c}${tr.net_pnl:+,.2f}{RESET}",
                tr.exit_reason.value,
            ])
        print(t_trades.render())


def parse_args():
    p = argparse.ArgumentParser(description="Simulador de Microestructura CME y Backtesting Institucional (NQ / MNQ)")
    p.add_argument("--symbol", choices=["NQ", "MNQ"], default="NQ", help="Contrato a simular (default: NQ)")
    p.add_argument("--contracts", type=int, default=1, help="Número de contratos por trade (default: 1)")
    p.add_argument("--strategy", choices=["markov", "hawkes", "25k", "multitarget", "all"], default="all", help="Estrategia estocástica a backtestear (default: all)")
    p.add_argument("--capital", type=float, default=50_000.0, help="Capital base de la cuenta (default: $50,000 USD)")
    p.add_argument("--drawdown-limit", type=float, default=2_500.0, help="Límite máximo de Trailing Drawdown (default: $2,500 USD)")
    p.add_argument("--sample-bars", type=int, default=0, help="Barras históricas a simular (0 = todo el historial)")
    p.add_argument("--offline", action="store_true", help="Usa caché local de datos históricos")
    return p.parse_args()


def main():
    args = parse_args()
    feed = DataFeedNQ(offline=args.offline)

    # Si se selecciona la estrategia 25k, configurar automáticamente los límites de la cuenta
    if args.strategy in ("25k", "multitarget"):
        capital = 25_000.0 if args.capital == 50_000.0 else args.capital
        dd_limit = 1_000.0 if args.drawdown_limit == 2_500.0 else args.drawdown_limit
        symbol = "MNQ"
        contracts = 2
    else:
        capital = args.capital
        dd_limit = args.drawdown_limit
        symbol = args.symbol
        contracts = args.contracts

    engine = BacktestEngine(
        symbol=symbol,
        contracts=contracts,
        initial_capital=capital,
        trailing_drawdown_limit=dd_limit,
    )

    bars_15m = feed.bars("NQ", "15m")
    bars_5m = feed.bars("NQ", "5m")

    if args.strategy in ("25k", "multitarget"):
        print(f"\n[EJECUTANDO ESTRATEGIA DE FONDEO 25K: MULTI-TARGET 2 CONTRATOS MNQ (SUELO: $24,000)]")
        rep_25k = engine.run_25k_multitarget_strategy(
            bars_15m,
            stop_pts=20.0,
            target_1_pts=20.0,
            target_2_pts=40.0,
            prob_threshold=0.55,
            time_stop_bars=6,
            sample_bars=args.sample_bars,
        )
        print_backtest_summary(rep_25k, initial_capital=capital)
        return

    if args.strategy in ("markov", "all"):
        print(f"\n[EJECUTANDO BACKTEST: MODELO OCULTO DE MARKOV (HMM 3 ESTADOS) — {args.symbol}]")
        rep_markov = engine.run_markov_hmm_backtest(
            bars_15m,
            prob_threshold=0.55,
            target_pts=60.0,
            stop_pts=30.0,
            sample_bars=args.sample_bars,
        )
        print_backtest_summary(rep_markov, initial_capital=args.capital)

    if args.strategy in ("hawkes", "all"):
        print(f"\n[EJECUTANDO BACKTEST: PROCESO DE HAWKES (ORDER FLOW BVC EN MUROS) — {args.symbol}]")
        rep_hawkes = engine.run_hawkes_order_flow_backtest(
            bars_5m,
            target_pts=30.0,
            stop_pts=15.0,
            sample_bars=args.sample_bars,
        )
        print_backtest_summary(rep_hawkes, initial_capital=args.capital)


if __name__ == "__main__":
    main()
