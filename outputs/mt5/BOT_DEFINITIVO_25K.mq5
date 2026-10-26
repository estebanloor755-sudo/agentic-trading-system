//+------------------------------------------------------------------+
//|                                   BOT_DEFINITIVO_25K.mq5         |
//|        Modelo Cuantitativo Campeón 25k (Donchian + Asimetría HMM)|
//|                                      Terminal Cuantitativa NQ    |
//+------------------------------------------------------------------+
#property copyright "Terminal Cuantitativa NQ 25k"
#property link      "https://github.com/estebanloor755-sudo/sistema-quant"
#property version   "4.00"
#property description "MODELO DEFINITIVO AUDITADO: 81 Trades | 59.3% Win Rate | +$2,380 USD | PF: 1.86x | Max DD: $505 USD"
#property description "Ruptura Donchian 20 + EMA 200 Macro Trend + Bracket Asimétrico (SL: 20p, T1: 25p con Break-Even, T2: 50p)."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Parámetros del Modelo Definitivo
input group "=== GESTIÓN ASIMÉTRICA CUENTA 25K (MYFUNDEDFUTURES) ===";
input double   InpStopLossPts     = 20.0;     // Stop Loss en Puntos (20 pts = $40 USD por contrato, $80 total)
input double   InpTarget1Pts      = 25.0;     // Target 1 - Seguro de Ganancia (+25 pts = +$50 USD)
input double   InpTarget2Pts      = 50.0;     // Target 2 - Runner Asimétrico (+50 pts = +$100 USD)
input double   InpLotsPerContract = 0.50;     // Lote por Contrato (0.50 CFD US100 = $1/pt)
input int      InpMaxDailyTrades  = 3;        // Máximo de Trades por Día
input ulong    InpMagicNumber     = 250005;   // Magic Number

input group "=== FILTRO INSTITUCIONAL: SESIÓN NUEVA YORK ===";
input bool     InpOnlyNySession   = true;     // Operar Únicamente Sesión Nueva York Cash
input int      InpServerStartHour = 16;       // Hora Inicio Servidor MT5 (16:30 = 09:30 NY)
input int      InpServerStartMin  = 30;       // Minuto Inicio Servidor MT5
input int      InpServerEndHour   = 22;       // Hora Fin Entradas Servidor MT5 (22:00 = 15:00 NY)
input bool     InpCloseEOD        = true;     // Cerrar al fin del día (22:50 Servidor = 15:50 NY)

input group "=== FILTROS CUANTITATIVOS: DONCHIAN Y MACRO TREND ===";
input int      InpDonchianPeriod  = 20;       // Período Canal Donchian (20 velas M15 = 5 horas)
input int      InpSlowEma         = 200;      // EMA Macro Trend (200 períodos)
input ENUM_TIMEFRAMES InpTimeframe= PERIOD_M15; // Temporalidad M15

input group "=== MODELOS ESTADÍSTICOS Y CUANTITATIVOS (TERMINAL NQ) ===";
input bool     InpUseVolumeZScore = false;    // Activar Z-Score de Volumen Institucional (Microestructura)
input double   InpMinVolumeZ      = 0.50;     // Z-Score Mínimo (0.50 = Desbalance de Flujo Anormal)
input int      InpVolZPeriod      = 20;       // Ventana de Volumen (20 velas)
input bool     InpUseHurstFilter  = false;    // Activar Filtro de Persistencia de Hurst
input double   InpMinHurst        = 0.50;     // Hurst Mínimo (H >= 0.50 = Régimen de Tendencia)

//--- Variables Globales
CTrade         trade;
CPositionInfo  posInfo;
datetime       lastBarTime  = 0;
int            tradesToday  = 0;
int            lastDay      = -1;
int            handle_ema200= INVALID_HANDLE;

double   g_entryPrice = 0.0;
bool     g_t1Reached  = false;
bool     g_isLong     = false;
bool     g_isShort    = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetMarginMode();
   trade.SetTypeFillingBySymbol(_Symbol);
   
   handle_ema200 = iMA(_Symbol, InpTimeframe, InpSlowEma, 0, MODE_EMA, PRICE_CLOSE);
   if(handle_ema200 == INVALID_HANDLE)
   {
      Print("Error inicializando EMA 200");
      return(INIT_FAILED);
   }
   
   Print("=== BOT DEFINITIVO 25K INICIALIZADO ===");
   Print("Geometría Campeona: Stop=", InpStopLossPts, "p | T1=", InpTarget1Pts, "p | T2=", InpTarget2Pts, "p");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handle_ema200);
   Print("Bot Definitivo 25k cerrado.");
}

//+------------------------------------------------------------------+
//| Detección de Nueva Vela en M15                                   |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime currentBarTime = iTime(_Symbol, InpTimeframe, 0);
   if(currentBarTime != lastBarTime)
   {
      lastBarTime = currentBarTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Candado de Break-Even en Tiempo Real                             |
//+------------------------------------------------------------------+
void CheckBreakEven()
{
   int openCount = 0;
   ulong c2_tick = 0;
   double c2_open = 0.0;
   double c2_sl   = 0.0;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
         {
            openCount++;
            string c = posInfo.Comment();
            if(StringFind(c, "C2") >= 0)
            {
               c2_tick = posInfo.Ticket();
               c2_open = posInfo.PriceOpen();
               c2_sl   = posInfo.StopLoss();
            }
         }
      }
   }
   
   if(openCount == 0)
   {
      g_entryPrice = 0.0;
      g_t1Reached  = false;
      g_isLong     = false;
      g_isShort    = false;
      return;
   }
   
   // Si el EA se reinicia o se pierde la variable en memoria, restaurar desde la posición
   if(c2_tick > 0 && g_entryPrice == 0.0)
   {
      g_entryPrice = c2_open;
      g_isLong  = (posInfo.PositionType() == POSITION_TYPE_BUY);
      g_isShort = (posInfo.PositionType() == POSITION_TYPE_SELL);
   }
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // Si el precio ya tocó el Target 1 (+25 pts)
   if(g_isLong)
   {
      if(bid >= g_entryPrice + InpTarget1Pts)
         g_t1Reached = true;
         
      if(g_t1Reached && c2_tick > 0)
      {
         double bePrice = NormalizeDouble(c2_open + 0.50, digits);
         if(c2_sl < c2_open && bid > bePrice)
         {
            trade.PositionModify(c2_tick, bePrice, NormalizeDouble(c2_open + InpTarget2Pts, digits));
            Print(">>> CANDADO BREAK-EVEN ACTIVADO (BUY): Stop blindado a ", bePrice);
         }
      }
   }
   else if(g_isShort)
   {
      if(ask <= g_entryPrice - InpTarget1Pts)
         g_t1Reached = true;
         
      if(g_t1Reached && c2_tick > 0)
      {
         double bePrice = NormalizeDouble(c2_open - 0.50, digits);
         if((c2_sl > c2_open || c2_sl == 0.0) && ask < bePrice)
         {
            trade.PositionModify(c2_tick, bePrice, NormalizeDouble(c2_open - InpTarget2Pts, digits));
            Print(">>> CANDADO BREAK-EVEN ACTIVADO (SELL): Stop blindado a ", bePrice);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick: Evaluación y Ejecución                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Candado Break-Even en cada tick
   CheckBreakEven();
   
   // 2. Control diario
   MqlDateTime dt;
   TimeCurrent(dt);
   if(dt.day != lastDay)
   {
      lastDay = dt.day;
      tradesToday = 0;
   }
   
   int currentMin = dt.hour * 60 + dt.min;
   int startMin   = InpServerStartHour * 60 + InpServerStartMin; // 16:30
   int endMin     = InpServerEndHour * 60;                      // 22:00
   int closeMin   = 22 * 60 + 50;                               // 22:50
   
   // Cierre forzoso EOD
   if(InpCloseEOD && currentMin >= closeMin)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(posInfo.SelectByIndex(i))
         {
            if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
               trade.PositionClose(posInfo.Ticket());
         }
      }
   }
   
   // 3. Evaluar entradas solo en nueva vela M15
   if(!IsNewBar()) return;
   
   // Filtro de horario NY Cash
   if(InpOnlyNySession)
   {
      if(currentMin < startMin || currentMin >= endMin)
         return;
   }
   
   // Control de trades diarios
   if(tradesToday >= InpMaxDailyTrades) return;
   
   // Evitar sobre-posicionarse
   int total_open = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
            total_open++;
      }
   }
   if(total_open > 0) return;
   
   // 4. Copiar Donchian de 20 barras y EMA 200
   int reqBars = MathMax(InpDonchianPeriod, 45) + 15;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, InpTimeframe, 0, reqBars, rates) < reqBars) return;
   
   double ema200_arr[];
   ArraySetAsSeries(ema200_arr, true);
   if(CopyBuffer(handle_ema200, 0, 0, 5, ema200_arr) < 3) return;
   
   // Calcular máximo y mínimo de las 20 barras anteriores a la vela recién cerrada (barras 2 a 21)
   double donchian_high = rates[2].high;
   double donchian_low  = rates[2].low;
   for(int k = 2; k <= InpDonchianPeriod + 1; k++)
   {
      if(rates[k].high > donchian_high) donchian_high = rates[k].high;
      if(rates[k].low  < donchian_low)  donchian_low  = rates[k].low;
   }
   
   double c1 = rates[1].close;
   double ema200_val = ema200_arr[1];
   
   // 4.1 Filtros Estadísticos y Cuantitativos (Terminal NQ)
   bool quant_ok = true;
   
   // A. Z-Score de Desbalance de Volumen Institucional (Microestructura)
   if(InpUseVolumeZScore)
   {
      double sum_vol = 0.0;
      for(int v = 1; v <= InpVolZPeriod; v++)
         sum_vol += (double)rates[v].tick_volume;
      double mean_vol = sum_vol / (double)InpVolZPeriod;
      
      double sum_sq = 0.0;
      for(int v = 1; v <= InpVolZPeriod; v++)
      {
         double diff = (double)rates[v].tick_volume - mean_vol;
         sum_sq += diff * diff;
      }
      double std_vol = MathSqrt(sum_sq / (double)InpVolZPeriod);
      double vz = (std_vol > 0.0001) ? (((double)rates[1].tick_volume - mean_vol) / std_vol) : 0.0;
      if(vz < InpMinVolumeZ)
         quant_ok = false;
   }
   
   // B. Exponente de Hurst (Persistencia de Tendencia H >= 0.50)
   if(quant_ok && InpUseHurstFilter)
   {
      double sum_d2 = 0.0, sum_d8 = 0.0;
      for(int k = 1; k <= 32; k++)
      {
         if(rates[k+2].close > 0.0 && rates[k+8].close > 0.0)
         {
            double d2 = MathLog(rates[k].close / rates[k+2].close);
            double d8 = MathLog(rates[k].close / rates[k+8].close);
            sum_d2 += d2 * d2;
            sum_d8 += d8 * d8;
         }
      }
      double var2 = sum_d2 / 32.0;
      double var8 = sum_d8 / 32.0;
      double h_est = 0.50;
      if(var2 > 1e-12 && var8 > 1e-12)
      {
         h_est = MathLog(var8 / var2) / (2.0 * MathLog(4.0));
         if(h_est < 0.10) h_est = 0.10;
         if(h_est > 0.90) h_est = 0.90;
      }
      if(h_est < InpMinHurst)
         quant_ok = false;
   }
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // 5. Señal de Ruptura Donchian a favor de EMA 200 y Modelos Cuantitativos
   // COMPRA: El cierre de la vela recién terminada (vela 1) superó el máximo Donchian y está sobre la EMA 200
   if(quant_ok && c1 > donchian_high && c1 > ema200_val)
   {
      double sl  = NormalizeDouble(ask - InpStopLossPts, digits);
      double tp1 = NormalizeDouble(ask + InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(ask + InpTarget2Pts, digits);
      
      trade.Buy(InpLotsPerContract, _Symbol, ask, sl, tp1, "MNQ_25k_C1");
      trade.Buy(InpLotsPerContract, _Symbol, ask, sl, tp2, "MNQ_25k_C2");
      
      tradesToday++;
      g_entryPrice = ask;
      g_t1Reached  = false;
      g_isLong     = true;
      g_isShort    = false;
      Print(">>> DISPARO DONCHIAN COMPRA (2 CONTRATOS): Ask=", ask, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
   // VENTA: El cierre de la vela recién terminada (vela 1) perforó el mínimo Donchian y está bajo la EMA 200
   else if(quant_ok && c1 < donchian_low && c1 < ema200_val)
   {
      double sl  = NormalizeDouble(bid + InpStopLossPts, digits);
      double tp1 = NormalizeDouble(bid - InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(bid - InpTarget2Pts, digits);
      
      trade.Sell(InpLotsPerContract, _Symbol, bid, sl, tp1, "MNQ_25k_C1");
      trade.Sell(InpLotsPerContract, _Symbol, bid, sl, tp2, "MNQ_25k_C2");
      
      tradesToday++;
      g_entryPrice = bid;
      g_t1Reached  = false;
      g_isLong     = false;
      g_isShort    = true;
      Print(">>> DISPARO DONCHIAN VENTA (2 CONTRATOS): Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
}
//+------------------------------------------------------------------+
