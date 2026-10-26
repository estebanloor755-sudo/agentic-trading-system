//+------------------------------------------------------------------+
//|                                BOT_ORB_INSTITUCIONAL_25K.mq5     |
//|               Opening Range Breakout (ORB) + Reversión Institucional|
//|                                      Terminal Cuantitativa NQ    |
//+------------------------------------------------------------------+
#property copyright "Terminal Cuantitativa NQ 25k"
#property link      "https://github.com/estebanloor755-sudo/sistema-quant"
#property version   "5.00"
#property description "MODELO CONSISTENTE ORB 15M (Wall Street Cash Open 09:30 NY)"
#property description "Diseñado para consistencia en mercado tendencial y mercado rotativo actual."
#property description "Riesgo Fijo: Stop 28 pts ($56 USD), Target 70 pts ($140 USD) con candado Break-Even a +30 pts."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- Parámetros de Entrada
input group "=== GESTIÓN DE RIESGO CUENTA 25K (MYFUNDEDFUTURES) ===";
input double   InpLotsPerContract = 0.50;     // Lote Operativo (0.50 CFD US100 = $1/pt por contrato)
input int      InpNumContracts    = 2;        // Número de Contratos (2 contratos = $2/pt = Micro E-mini MNQ)
input double   InpStopLossPts     = 28.0;     // Stop Loss en Puntos (28 pts = $56 USD en 2 MNQ)
input double   InpTarget1Pts      = 30.0;     // Target 1 - Seguro de Ganancia (+30 pts = +$60 USD, blinda a BE)
input double   InpTarget2Pts      = 70.0;     // Target 2 - Expansión Institucional (+70 pts = +$140 USD)
input ulong    InpMagicNumber     = 250007;   // Magic Number

input group "=== FILTRO INSTITUCIONAL: WALL STREET CASH (ORB 15M) ===";
input int      InpServerOrbHour   = 16;       // Hora Apertura Servidor MT5 (16:30 = 09:30 NY Cash Open)
input int      InpServerOrbMin    = 30;       // Minuto Apertura Servidor MT5
input int      InpServerEndEntryH = 18;       // Hora Fin de Entradas ORB (18:00 = 11:00 NY)
input int      InpServerCloseH    = 22;       // Hora Cierre Obligatorio EOD (22:45 = 15:45 NY)
input int      InpServerCloseM    = 45;       // Minuto Cierre EOD
input double   InpMinOrbRangePts  = 15.0;     // Rango Mínimo Vela Apertura (evita días feriados)
input double   InpMaxOrbRangePts  = 140.0;    // Rango Máximo Vela Apertura (evita noticias extremas)

input group "=== FILTRO MACRO TREND Y CONFIRMACIÓN ===";
input bool     InpUseEmaFilter    = true;     // Exigir alineación con EMA 200 Macro
input int      InpEmaPeriod       = 200;      // Período EMA Macro
input ENUM_TIMEFRAMES InpTimeframe= PERIOD_M15; // Temporalidad M15

//--- Variables Globales
CTrade         trade;
CPositionInfo  posInfo;
datetime       lastBarTime  = 0;
int            lastDay      = -1;
int            handle_ema   = INVALID_HANDLE;

// Variables de Sesión Diaria ORB
double         g_orbHigh    = 0.0;
double         g_orbLow     = 0.0;
bool           g_orbFormed  = false;
bool           g_tradedToday= false;
double         g_entryPrice = 0.0;
bool           g_t1Reached  = false;
bool           g_isLong     = false;
bool           g_isShort    = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetMarginMode();
   trade.SetTypeFillingBySymbol(_Symbol);
   
   if(InpUseEmaFilter)
   {
      handle_ema = iMA(_Symbol, InpTimeframe, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(handle_ema == INVALID_HANDLE)
      {
         Print("Error inicializando EMA ", InpEmaPeriod);
         return(INIT_FAILED);
      }
   }
   
   Print("=== BOT ORB INSTITUCIONAL 25K INICIALIZADO ===");
   Print("Reglas de Fondeo: SL=", InpStopLossPts, "p | T1=", InpTarget1Pts, "p | T2=", InpTarget2Pts, "p");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(handle_ema != INVALID_HANDLE)
      IndicatorRelease(handle_ema);
   Print("Bot ORB Institucional 25k cerrado.");
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
            if(StringFind(c, "C2") >= 0 || openCount == 1)
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
   
   if(c2_tick > 0 && g_entryPrice == 0.0)
   {
      g_entryPrice = c2_open;
      g_isLong  = (posInfo.PositionType() == POSITION_TYPE_BUY);
      g_isShort = (posInfo.PositionType() == POSITION_TYPE_SELL);
   }
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // Si el precio alcanzó el Target 1 (+30 pts)
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
            Print(">>> CANDADO BREAK-EVEN ORB (BUY): Blindado a ", bePrice);
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
            Print(">>> CANDADO BREAK-EVEN ORB (SELL): Blindado a ", bePrice);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick: Detección y Ejecución                                    |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Candado Break-Even en tiempo real
   CheckBreakEven();
   
   // 2. Control de tiempo y reset diario
   MqlDateTime dt;
   TimeCurrent(dt);
   if(dt.day != lastDay)
   {
      lastDay = dt.day;
      g_orbHigh = 0.0;
      g_orbLow = 0.0;
      g_orbFormed = false;
      g_tradedToday = false;
   }
   
   int currentMin = dt.hour * 60 + dt.min;
   int orbStartMin = InpServerOrbHour * 60 + InpServerOrbMin; // 16:30 (09:30 NY)
   int orbEndMin   = orbStartMin + 15;                       // 16:45 (09:45 NY)
   int entryLimitM = InpServerEndEntryH * 60;                // 18:00 (11:00 NY)
   int closeMin    = InpServerCloseH * 60 + InpServerCloseM; // 22:45 (15:45 NY)
   
   // Cierre forzoso de posiciones al fin del día (EOD)
   if(currentMin >= closeMin)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(posInfo.SelectByIndex(i))
         {
            if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
               trade.PositionClose(posInfo.Ticket());
         }
      }
      return;
   }
   
   // 3. Evaluar solo en apertura de nueva vela M15
   if(!IsNewBar()) return;
   
   // A. Capturar el Rango de Apertura ORB (16:30 a 16:45)
   // Cuando la vela de las 16:45 abre, la vela 1 recién cerrada es la vela de las 16:30
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, InpTimeframe, 0, 10, rates) < 5) return;
   
   MqlDateTime bar1_dt;
   TimeToStruct(rates[1].time, bar1_dt);
   int bar1_min = bar1_dt.hour * 60 + bar1_dt.min;
   
   // Si la vela 1 es la vela de apertura (16:30) y aún no registramos el ORB
   if(!g_orbFormed && bar1_min == orbStartMin)
   {
      double rng = rates[1].high - rates[1].low;
      if(rng >= InpMinOrbRangePts && rng <= InpMaxOrbRangePts)
      {
         g_orbHigh = rates[1].high;
         g_orbLow  = rates[1].low;
         g_orbFormed = true;
         Print(">>> ORB 15M FORMADO: High=", g_orbHigh, " Low=", g_orbLow, " Rango=", rng, " pts");
      }
   }
   
   // B. Evaluar entrada si el ORB está activo, dentro de ventana (16:45 - 18:00) y no se ha operado hoy
   if(!g_orbFormed || g_tradedToday || currentMin > entryLimitM) return;
   
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
   
   double c1 = rates[1].close;
   double ema_val = 0.0;
   bool ema_buy_ok = true;
   bool ema_sell_ok = true;
   
   if(InpUseEmaFilter)
   {
      double ema_arr[];
      ArraySetAsSeries(ema_arr, true);
      if(CopyBuffer(handle_ema, 0, 0, 3, ema_arr) >= 2)
      {
         ema_val = ema_arr[1];
         ema_buy_ok = (c1 > ema_val);
         ema_sell_ok = (c1 < ema_val);
      }
   }
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   // 4. DISPARO ORB RUPTURA ALCISTA
   if(c1 > g_orbHigh && ema_buy_ok)
   {
      double sl  = NormalizeDouble(ask - InpStopLossPts, digits);
      double tp1 = NormalizeDouble(ask + InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(ask + InpTarget2Pts, digits);
      
      double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
      double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
      
      trade.Buy(lot1, _Symbol, ask, sl, tp1, "ORB_25k_C1");
      trade.Buy(lot2, _Symbol, ask, sl, tp2, "ORB_25k_C2");
      
      g_tradedToday = true;
      g_entryPrice  = ask;
      g_t1Reached   = false;
      g_isLong      = true;
      g_isShort     = false;
      Print(">>> DISPARO ORB COMPRA (WALL STREET CASH): Ask=", ask, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
   // 5. DISPARO ORB RUPTURA BAJISTA
   else if(c1 < g_orbLow && ema_sell_ok)
   {
      double sl  = NormalizeDouble(bid + InpStopLossPts, digits);
      double tp1 = NormalizeDouble(bid - InpTarget1Pts, digits);
      double tp2 = NormalizeDouble(bid - InpTarget2Pts, digits);
      
      double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
      double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
      
      trade.Sell(lot1, _Symbol, bid, sl, tp1, "ORB_25k_C1");
      trade.Sell(lot2, _Symbol, bid, sl, tp2, "ORB_25k_C2");
      
      g_tradedToday = true;
      g_entryPrice  = bid;
      g_t1Reached   = false;
      g_isLong      = false;
      g_isShort     = true;
      Print(">>> DISPARO ORB VENTA (WALL STREET CASH): Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
   }
}
//+------------------------------------------------------------------+