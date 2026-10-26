//+------------------------------------------------------------------+
//|                                   BOT_NEW_YORK_25K.mq5           |
//|               Swing & Day Trader 25k Nasdaq (Institutional Trend)|
//|                                      Terminal Cuantitativa NQ    |
//+------------------------------------------------------------------+
#property copyright "Terminal Cuantitativa NQ 25k"
#property link      "https://github.com/estebanloor755-sudo/sistema-quant"
#property version   "3.00"
#property description "Estrategia Day Trading & Swing Institucional para MyFundedFutures 25k Builder Plan."
#property description "2 Contratos MNQ: T1=+60pts con Break-Even automático, T2=+110pts Runner, Stop=35pts."
#property description "Copia 1:1 de TradingView: Auto-detección GMT Wall Street (09:30-15:00 NY), EMA 50/200, Pullback EMA 21, RSI 14."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//--- Parámetros de Entrada (Idénticos a TradingView)
input group "=== GESTIÓN DE RIESGO CUENTA 25K (MYFUNDEDFUTURES) ===";
input double   InpStopLossPts     = 35.0;     // Stop Loss en Puntos (35 pts = $70 USD por MNQ)
input double   InpTarget1Pts      = 60.0;     // Target 1 - Seguro de Beneficio (+60 pts = +$120 USD)
input double   InpTarget2Pts      = 110.0;    // Target 2 - Runner Tendencial (+110 pts = +$220 USD)
input int      InpTimeStopBars    = 24;       // Time-Stop en Velas M15 (24 velas = 6 horas)
input double   InpLotsPerContract = 0.50;     // Lote por Contrato (0.50 CFD US100 = $1/pt)
input int      InpMaxDailyTrades  = 2;        // Máximo de Trades por Día (Anti-HFT)
input bool     InpCloseEOD        = true;     // Cierre Forzoso a Fin de Sesión NY (15:50 EST)
input ulong    InpMagicNumber     = 250001;   // Magic Number Identificador

input group "=== FILTRO AUTOMÁTICO DE SESIÓN NUEVA YORK (WALL STREET) ===";
input bool     InpOnlyNySession   = true;     // Operar ÚNICAMENTE en Horario Wall Street Cash
input int      InpManualGmtOffset = 99;       // Offset GMT del Broker (99 = Detección Automática)

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
int            tradesToday  = 0;
int            lastDay      = -1;
int            handle_ema21 = INVALID_HANDLE;
int            handle_ema50 = INVALID_HANDLE;
int            handle_ema200= INVALID_HANDLE;
int            handle_rsi   = INVALID_HANDLE;

// Estado de la posición (Idéntico a TradingView)
double   g_entryPrice = 0.0;
bool     g_t1Reached  = false;
bool     g_isLong     = false;
bool     g_isShort    = false;
ulong    g_ticket_c1  = 0;
ulong    g_ticket_c2  = 0;
datetime g_entryTime  = 0;

//+------------------------------------------------------------------+
//| Detección de la Hora de Wall Street (Nueva York EST / EDT)       |
//+------------------------------------------------------------------+
bool IsNySessionActive(bool &isEodClose)
{
   isEodClose = false;
   if(!InpOnlyNySession) return true;
   
   datetime curTime = TimeCurrent();
   datetime gmtTime = TimeGMT();
   
   int brokerOffsetHours = 0;
   if(InpManualGmtOffset != 99)
   {
      brokerOffsetHours = InpManualGmtOffset;
   }
   else
   {
      if(gmtTime > 0)
         brokerOffsetHours = (int)MathRound((double)(curTime - gmtTime) / 3600.0);
      else
         brokerOffsetHours = 3; // Estándar EET
   }
   
   // Nueva York está en GMT-4 (verano EDT) o GMT-5 (invierno EST)
   // Calculamos la hora de Nueva York restando la diferencia
   int nyOffsetGmt = -4; // EDT por defecto en temporada regular
   int diffToNy = brokerOffsetHours - nyOffsetGmt; // ej. 3 - (-4) = +7 horas
   
   datetime nyTime = curTime - (diffToNy * 3600);
   MqlDateTime dtNy;
   TimeToStruct(nyTime, dtNy);
   
   int nyMinOfDay = dtNy.hour * 60 + dtNy.min;
   int openMin    = 9 * 60 + 30;  // 09:30 NY = 570 min
   int endMin     = 15 * 60;      // 15:00 NY = 900 min
   int closeMin   = 15 * 60 + 50; // 15:50 NY = 950 min
   
   if(nyMinOfDay >= closeMin)
      isEodClose = true;
      
   return (nyMinOfDay >= openMin && nyMinOfDay < endMin);
}

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
   
   Print("=== BOT NEW YORK 25K INICIALIZADO ===");
   Print("Símbolo: ", _Symbol, " | Stop: ", InpStopLossPts, " pts | T1: ", InpTarget1Pts, " pts | T2: ", InpTarget2Pts, " pts");
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
   Print("Bot New York 25k finalizado.");
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
//| Gestión de Salidas, Break-Even Real y Time-Stop                  |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   int openCount = 0;
   ulong c1_tick = 0;
   ulong c2_tick = 0;
   double c2_open = 0.0;
   double c2_sl   = 0.0;
   long   pos_type= -1;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
         {
            openCount++;
            string c = posInfo.Comment();
            if(StringFind(c, "C1") >= 0)
               c1_tick = posInfo.Ticket();
            if(StringFind(c, "C2") >= 0)
            {
               c2_tick = posInfo.Ticket();
               c2_open = posInfo.PriceOpen();
               c2_sl   = posInfo.StopLoss();
               pos_type= posInfo.PositionType();
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
      g_ticket_c1  = 0;
      g_ticket_c2  = 0;
      return;
   }
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // Chequear si el precio realmente tocó o superó Target 1 (+60 pts)
   if(g_isLong)
   {
      if(bid >= g_entryPrice + InpTarget1Pts)
         g_t1Reached = true;
         
      // Si tocó T1 y Contrato 2 sigue abierto, blindar Stop a Break-Even (+0.50 pts)
      if(g_t1Reached && c2_tick > 0)
      {
         double bePrice = NormalizeDouble(c2_open + 0.50, digits);
         if(c2_sl < c2_open && bid > bePrice)
         {
            trade.PositionModify(c2_tick, bePrice, NormalizeDouble(c2_open + InpTarget2Pts, digits));
            Print(">>> CANDADO BREAK-EVEN (BUY): Stop de C2 blindado a entrada (+0.5p): ", bePrice);
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
            Print(">>> CANDADO BREAK-EVEN (SELL): Stop de C2 blindado a entrada (-0.5p): ", bePrice);
         }
      }
   }
   
   // Time-Stop: 24 velas M15 (6 horas)
   if(c2_tick > 0 && g_entryTime > 0)
   {
      int bars_open = iBarShift(_Symbol, InpTimeframe, g_entryTime);
      if(InpTimeStopBars > 0 && bars_open >= InpTimeStopBars)
      {
         trade.PositionClose(c2_tick);
         Print(">>> TIME-STOP: C2 cerrado tras 6 horas de holding.");
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick: Gestión de operaciones                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Control de posiciones abiertas y Break-Even en cada tick
   ManageOpenPositions();
   
   // 2. Control diario
   MqlDateTime dt;
   TimeCurrent(dt);
   if(dt.day != lastDay)
   {
      lastDay = dt.day;
      tradesToday = 0;
   }
   
   bool isEod = false;
   bool isNyActive = IsNySessionActive(isEod);
   
   // Cierre forzoso EOD si está activado
   if(InpCloseEOD && isEod)
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
   
   // FILTRO ESTRICTO: Solo operar en horario de Nueva York
   if(!isNyActive) return;
   
   // Evitar sobreoperar
   if(tradesToday >= InpMaxDailyTrades) return;
   
   // No abrir si ya hay una posición abierta
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
      g_entryPrice = ask;
      g_t1Reached  = false;
      g_isLong     = true;
      g_isShort    = false;
      g_entryTime  = TimeCurrent();
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
      g_entryPrice = bid;
      g_t1Reached  = false;
      g_isLong     = false;
      g_isShort    = true;
      g_entryTime  = TimeCurrent();
      Print(">>> DISPARO VENTA SESIÓN NY (2 CONTRATOS): Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
}
//+------------------------------------------------------------------+
