//+------------------------------------------------------------------+
//|                                   1_BOT_OFICIAL_25K_NASDAQ.mq5   |
//|               Swing & Day Trader 25k Nasdaq (Institutional Trend)|
//|                                      Terminal Cuantitativa NQ    |
//+------------------------------------------------------------------+
#property copyright "Terminal Cuantitativa NQ 25k"
#property link      "https://github.com/estebanloor755-sudo/sistema-quant"
#property version   "2.20"
#property description "Estrategia Day Trading & Swing Institucional para MyFundedFutures 25k Builder Plan."
#property description "2 Contratos MNQ: T1=+60pts con Break-Even automático, T2=+110pts Runner, Stop=35pts."
#property description "FILTRO ESTRICTO: Solo opera en Sesión Regular de Nueva York (09:30-15:00 NY = 16:30-22:00 Servidor)."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Parámetros de Entrada (Configuración Oficial Idéntica a TradingView)
input group "=== GESTIÓN DE RIESGO CUENTA 25K (MYFUNDEDFUTURES) ===";
input double   InpStopLossPts     = 35.0;     // Stop Loss en Puntos (35 pts = $70 USD por MNQ)
input double   InpTarget1Pts      = 60.0;     // Target 1 - Seguro de Beneficio (+60 pts = +$120 USD)
input double   InpTarget2Pts      = 110.0;    // Target 2 - Runner Tendencial (+110 pts = +$220 USD)
input int      InpTimeStopBars    = 24;       // Time-Stop en Velas (24 velas M15 = 6 horas)
input double   InpLotsPerContract = 0.50;     // Lote por Contrato (CFD US100)
input int      InpMaxDailyTrades  = 2;        // Máximo de Trades por Día (Anti-HFT)
input ulong    InpMagicNumber     = 250001;   // Magic Number Identificador

input group "=== FILTRO ESTRICTO: SESIÓN NUEVA YORK (WALL STREET) ===";
input bool     InpOnlyNySession   = true;     // Operar ÚNICAMENTE en Sesión de Nueva York
input int      InpServerStartHour = 16;       // Hora Inicio Servidor Broker (16:30 = 09:30 NY)
input int      InpServerStartMin  = 30;       // Minuto Inicio Servidor Broker (30 min)
input int      InpServerEndHour   = 22;       // Hora Fin Entradas Servidor Broker (22:00 = 15:00 NY)
input bool     InpCloseEOD        = true;     // Cierre Forzoso al Fin de Sesión NY
input int      InpServerCloseHour = 22;       // Hora Cierre Forzoso Servidor (22:50 = 15:50 NY)
input int      InpServerCloseMin  = 50;       // Minuto Cierre Forzoso Servidor (50 min)

input group "=== FILTRO INSTITUCIONAL DE TENDENCIA Y PULLBACK ===";
input int      InpFastEma         = 21;       // EMA Rápida (Zona de Valor Pullback)
input int      InpMidEma          = 50;       // EMA Media (Estructura Intradiaria)
input int      InpSlowEma         = 200;      // EMA Lenta (Tendencia Macro 200)
input int      InpRsiPeriod       = 14;       // Período RSI
input bool     InpUseVolFilter    = true;     // Exigir Volumen Superior a Media
input ENUM_TIMEFRAMES InpTimeframe= PERIOD_M15; // Temporalidad Operativa (M15)

//--- Objetos Globales de Trading
CTrade         trade;
CPositionInfo  posInfo;
datetime       lastBarTime  = 0;
ulong          ticket_c1    = 0;
ulong          ticket_c2    = 0;
int            tradesToday  = 0;
int            lastDay      = -1;
int            handle_ema21 = INVALID_HANDLE;
int            handle_ema50 = INVALID_HANDLE;
int            handle_ema200= INVALID_HANDLE;
int            handle_rsi   = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetMarginMode();
   trade.SetTypeFillingBySymbol(_Symbol);
   
   handle_ema21  = iMA(_Symbol, InpTimeframe, InpFastEma,  0, MODE_EMA, PRICE_CLOSE);
   handle_ema50  = iMA(_Symbol, InpTimeframe, InpMidEma,   0, MODE_EMA, PRICE_CLOSE);
   handle_ema200 = iMA(_Symbol, InpTimeframe, InpSlowEma,  0, MODE_EMA, PRICE_CLOSE);
   handle_rsi    = iRSI(_Symbol, InpTimeframe, InpRsiPeriod, PRICE_CLOSE);
   
   if(handle_ema21 == INVALID_HANDLE || handle_ema50 == INVALID_HANDLE || 
      handle_ema200 == INVALID_HANDLE || handle_rsi == INVALID_HANDLE)
   {
      Print("Error inicializando indicadores técnicos.");
      return(INIT_FAILED);
   }
   
   Print("=== BOT OFICIAL 25K NASDAQ (SESIÓN NY ESTRICTA) INICIALIZADO ===");
   Print("Símbolo: ", _Symbol, " | Stop: ", InpStopLossPts, " pts | T1: ", InpTarget1Pts, " pts | T2: ", InpTarget2Pts, " pts");
   Print("Horario Permitido Servidor: ", InpServerStartHour, ":", InpServerStartMin, " a ", InpServerEndHour, ":00 (NY Cash)");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handle_ema21);
   IndicatorRelease(handle_ema50);
   IndicatorRelease(handle_ema200);
   IndicatorRelease(handle_rsi);
   Print("Bot 25k Oficial finalizado.");
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
//| Monitor de Posición: Break-Even Inmediato y Time-Stop            |
//+------------------------------------------------------------------+
void CheckBreakEvenAndTimeStop()
{
   bool has_c1 = false;
   bool has_c2 = false;
   double c2_open_price = 0.0;
   double c2_current_sl = 0.0;
   long   c2_type = -1;
   datetime c2_time = 0;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
         {
            string comment = posInfo.Comment();
            if(StringFind(comment, "C1") >= 0)
            {
               has_c1 = true;
               ticket_c1 = posInfo.Ticket();
            }
            if(StringFind(comment, "C2") >= 0)
            {
               has_c2 = true;
               ticket_c2 = posInfo.Ticket();
               c2_open_price = posInfo.PriceOpen();
               c2_current_sl = posInfo.StopLoss();
               c2_type = posInfo.PositionType();
               c2_time = posInfo.Time();
            }
         }
      }
   }
   
   // Si C1 ya cerró con ganancia (+60 pts), mover Contrato 2 a Break-Even (+0.50 pts)
   if(!has_c1 && has_c2)
   {
      int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
      
      if(c2_type == POSITION_TYPE_BUY)
      {
         if(c2_current_sl < c2_open_price)
         {
            trade.PositionModify(ticket_c2, NormalizeDouble(c2_open_price + 0.50, digits), NormalizeDouble(c2_open_price + InpTarget2Pts, digits));
            Print(">>> CANDADO BREAK-EVEN (BUY): Stop de C2 blindado a entrada (+0.5p): ", c2_open_price + 0.50);
         }
      }
      else if(c2_type == POSITION_TYPE_SELL)
      {
         if(c2_current_sl > c2_open_price || c2_current_sl == 0.0)
         {
            trade.PositionModify(ticket_c2, NormalizeDouble(c2_open_price - 0.50, digits), NormalizeDouble(c2_open_price - InpTarget2Pts, digits));
            Print(">>> CANDADO BREAK-EVEN (SELL): Stop de C2 blindado a entrada (-0.5p): ", c2_open_price - 0.50);
         }
      }
      
      int bars_open = iBarShift(_Symbol, InpTimeframe, c2_time);
      if(InpTimeStopBars > 0 && bars_open >= InpTimeStopBars)
      {
         trade.PositionClose(ticket_c2);
         Print(">>> TIME-STOP (6 Horas): C2 cerrado a mercado tras ", bars_open, " velas.");
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick: Gestión de operaciones                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Candado Break-Even en cada tick
   CheckBreakEvenAndTimeStop();
   
   // 2. Control horario y reinicio de trades diarios
   MqlDateTime dt;
   TimeCurrent(dt);
   if(dt.day != lastDay)
   {
      lastDay = dt.day;
      tradesToday = 0;
   }
   
   int currentMinOfDay = dt.hour * 60 + dt.min;
   int startMinOfDay   = InpServerStartHour * 60 + InpServerStartMin; // 16:30 = 990 min
   int endMinOfDay     = InpServerEndHour * 60;                      // 22:00 = 1320 min
   int closeMinOfDay   = InpServerCloseHour * 60 + InpServerCloseMin;// 22:50 = 1370 min
   
   // Cierre forzoso intradiario EOD (15:50 NY Time = 22:50 Servidor)
   if(InpCloseEOD && currentMinOfDay >= closeMinOfDay)
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
   
   // 3. Evaluar señales de entrada únicamente al comenzar una nueva vela M15
   if(!IsNewBar()) return;
   
   // FILTRO ESTRICTO SESIÓN NUEVA YORK:
   // Si está fuera del rango 16:30 a 22:00 del servidor (09:30 a 15:00 Nueva York), NO OPERAR
   if(InpOnlyNySession)
   {
      if(currentMinOfDay < startMinOfDay || currentMinOfDay >= endMinOfDay)
         return; // FUERA DE HORARIO DE NUEVA YORK
   }
   
   // Evitar sobreoperar (Máximo 2 trades al día)
   if(tradesToday >= InpMaxDailyTrades) return;
   
   // Evitar abrir nuevas órdenes si ya hay una posición abierta
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
   
   // 4. Copiar indicadores técnicos
   double ema21_arr[], ema50_arr[], ema200_arr[], rsi_arr[];
   ArraySetAsSeries(ema21_arr, true);
   ArraySetAsSeries(ema50_arr, true);
   ArraySetAsSeries(ema200_arr, true);
   ArraySetAsSeries(rsi_arr, true);
   
   if(CopyBuffer(handle_ema21, 0, 0, 3, ema21_arr) < 3) return;
   if(CopyBuffer(handle_ema50, 0, 0, 3, ema50_arr) < 3) return;
   if(CopyBuffer(handle_ema200, 0, 0, 3, ema200_arr) < 3) return;
   if(CopyBuffer(handle_rsi, 0, 0, 3, rsi_arr) < 3) return;
   
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, InpTimeframe, 0, 25, rates) < 25) return;
   
   // Volumen promedio de 20 barras
   double sum_vol = 0.0;
   for(int v = 1; v <= 20; v++) sum_vol += (double)rates[v].tick_volume;
   double vol_ma = sum_vol / 20.0;
   bool vol_ok = (!InpUseVolFilter) || (rates[1].tick_volume >= vol_ma * 0.85);
   
   double c1 = rates[1].close;
   double o1 = rates[1].open;
   double h1 = rates[1].high;
   double l1 = rates[1].low;
   double h2 = rates[2].high;
   double l2 = rates[2].low;
   double rsi_val = rsi_arr[1];
   
   bool trend_bull = (c1 > ema200_arr[1]) && (ema50_arr[1] > ema200_arr[1]);
   bool trend_bear = (c1 < ema200_arr[1]) && (ema50_arr[1] < ema200_arr[1]);
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // 5. Disparo de Entradas
   // Compra: Macro Alcista, Pullback a EMA 21, Giro alcista rompe máximo previo, RSI >= 48
   if(trend_bull && vol_ok && (l2 <= ema21_arr[2] || l1 <= ema21_arr[1]) && (c1 > h2) && (c1 > o1) && (rsi_val >= 48))
   {
      double sl  = NormalizeDouble(ask - InpStopLossPts, digits);
      double tp1 = NormalizeDouble(ask + InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(ask + InpTarget2Pts, digits);
      
      trade.Buy(InpLotsPerContract, _Symbol, ask, sl, tp1, "MNQ_25k_C1");
      trade.Buy(InpLotsPerContract, _Symbol, ask, sl, tp2, "MNQ_25k_C2");
      tradesToday++;
      Print(">>> DISPARO COMPRA SESIÓN NY (2 CONTRATOS): Ask=", ask, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
   // Venta: Macro Bajista, Pullback a EMA 21, Giro bajista rompe mínimo previo, RSI <= 52
   else if(trend_bear && vol_ok && (h2 >= ema21_arr[2] || h1 >= ema21_arr[1]) && (c1 < l2) && (c1 < o1) && (rsi_val <= 52))
   {
      double sl  = NormalizeDouble(bid + InpStopLossPts, digits);
      double tp1 = NormalizeDouble(bid - InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(bid - InpTarget2Pts, digits);
      
      trade.Sell(InpLotsPerContract, _Symbol, bid, sl, tp1, "MNQ_25k_C1");
      trade.Sell(InpLotsPerContract, _Symbol, bid, sl, tp2, "MNQ_25k_C2");
      tradesToday++;
      Print(">>> DISPARO VENTA SESIÓN NY (2 CONTRATOS): Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
}
//+------------------------------------------------------------------+
