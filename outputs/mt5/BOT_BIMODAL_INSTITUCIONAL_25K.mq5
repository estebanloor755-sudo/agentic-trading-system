//+------------------------------------------------------------------+
//|                            BOT_BIMODAL_INSTITUCIONAL_25K.mq5     |
//|               Opening Range Breakout (ORB) + Late Fusion Bimodal |
//|                     FinBERT Cross-Attention & Terminal Ensemble  |
//+------------------------------------------------------------------+
#property copyright "Terminal Cuantitativa NQ 25k"
#property link      "https://github.com/estebanloor755-sudo/sistema-quant"
#property version   "12.00"
#property description "DIRECTIVA MAESTRA V12: ARQUITECTURA BIMODAL Y ANÁLISIS DE SENTIMIENTO (FINBERT + CROSS-ATTENTION)"
#property description "Combina el ORB 15M (Cash Open NY) con el filtro macro de Noticias FinBERT y Ponderación de la Terminal."
#property description "Riesgo Fijo: Stop 28 pts ($56 USD), TP1 30 pts ($60 USD, blinda BE), TP2 70 pts ($140 USD)."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- Parámetros de Entrada
input group "=== GESTIÓN DE RIESGO CUENTA 25K (MYFUNDEDFUTURES) ===";
input double   InpLotsPerContract = 0.50;     // Lote Operativo (0.50 CFD US100 = $1/pt por contrato)
input int      InpNumContracts    = 2;        // Número de Contratos (2 contratos = $2/pt = Micro E-mini MNQ)
input double   InpStopLossPts     = 35.0;     // Stop Loss Amplio en Puntos (35 pts = $70 USD en 2 MNQ, da aire a wicks)
input double   InpTarget1Pts      = 35.0;     // Target 1 - Seguro de Ganancia (+35 pts = +$70 USD)
input double   InpLockProfitPts   = 12.0;     // Bloqueo de Ganancias en C2 tras TP1 (+12 pts = +$24 USD garantizado)
input double   InpTarget2Pts      = 105.0;    // Target 2 Ampliado - Runner de Expansión (+105 pts = +$210 USD)
input ulong    InpMagicNumber     = 250012;   // Magic Number V12

input group "=== FILTRO INSTITUCIONAL: WALL STREET CASH (ORB 15M) ===";
input int      InpMaxDailyTrades  = 2;        // Máximo de Operaciones por Día (1 o 2)
input int      InpServerOrbHour   = 16;       // Hora Apertura Servidor MT5 (16:30 = 09:30 NY Cash Open)
input int      InpServerOrbMin    = 30;       // Minuto Apertura Servidor MT5
input int      InpServerEndEntryH = 19;       // Hora Fin de Entradas Tendencia NY (19:00 = 12:00 NY)
input int      InpServerCloseH    = 22;       // Hora Cierre Obligatorio EOD (22:45 = 15:45 NY)
input int      InpServerCloseM    = 45;       // Minuto Cierre EOD
input double   InpMinOrbRangePts  = 15.0;     // Rango Mínimo Vela Apertura (evita días feriados)
input double   InpMaxOrbRangePts  = 140.0;    // Rango Máximo Vela Apertura (evita noticias extremas)

input group "=== CAPA BIMODAL: FINBERT + CROSS-ATTENTION & TERMINAL ===";
input bool     InpUseBimodalFilter= true;     // Activar Validación Bimodal previa a Órdenes
input string   InpSignalFileName  = "live_bimodal_signal.json"; // Archivo de Señal Cuantitativa
input double   InpMinConviction   = 0.20;     // Umbral Mínimo de Convicción Ponderada (0.20 a 1.0)
input bool     InpStrictVeto      = true;     // Respetar Veto de FinBERT ante noticias contradictorias

input group "=== EXPLOTACIÓN ACTIVA DE DIVERGENCIAS (TURTLE SOUP / TRAP REVERSAL) ===";
input bool     InpExploitDivergence   = true;     // Acoplarse y operar la divergencia (no congelar)
input double   InpDivStopLossPts      = 30.0;     // Stop Ceñido en Divergencia Ampliado (30 pts = $60 USD para dar aire)
input double   InpDivTarget1Pts       = 30.0;     // Target 1 en Divergencia (+30 pts = +$60 USD, blinda BE)
input double   InpDivTarget2Pts       = 65.0;     // Target 2 en Divergencia (+65 pts = +$130 USD)

input group "=== FILTRO MACRO TREND (CONFIRMACIÓN) ===";
input bool     InpUseEmaFilter    = true;     // Exigir alineación con EMA 200 Macro
input int      InpEmaPeriod       = 200;      // Período EMA Macro
input ENUM_TIMEFRAMES InpTimeframe= PERIOD_M15; // Temporalidad M15

//--- Variables Globales
CTrade         trade;
CPositionInfo  posInfo;
datetime       lastBarTime  = 0;
int            lastDay      = -1;
int            handle_ema   = INVALID_HANDLE;

// Variables de Sesión Diaria ORB y Tendencia Fuerte NY
double         g_orbHigh          = 0.0;
double         g_orbLow           = 0.0;
bool           g_orbFormed        = false;
int            g_dailyTrades      = 0;
string         g_lastTradeSide    = "";
bool           g_lastTradeWasWin  = false;
double         g_sessionHigh      = 0.0;
double         g_sessionLow       = 0.0;
double         g_entryPrice       = 0.0;
bool           g_t1Reached        = false;
bool           g_isLong           = false;
bool           g_isShort          = false;

// Variables de Estado Bimodal
string         g_bimodalAction      = "SYNCING";
double         g_bimodalConviction  = 0.0;
double         g_bimodalConfidence  = 0.0;
bool           g_bimodalVeto        = false;
string         g_bimodalTopNews     = "Inicializando motor...";
double         g_bimodalNewsSent    = 0.0;
datetime       g_lastSignalRead     = 0;

//+------------------------------------------------------------------+
//| Funciones Auxiliares de Parsing JSON para MQL5                   |
//+------------------------------------------------------------------+
string ExtractJsonString(const string json, const string key)
{
   string searchKey = "\"" + key + "\"";
   int pos = StringFind(json, searchKey);
   if(pos < 0) return "";
   
   int colonPos = StringFind(json, ":", pos);
   if(colonPos < 0) return "";
   
   int start = colonPos + 1;
   while(start < StringLen(json) && (json[start] == ' ' || json[start] == '\t' || json[start] == '\"' || json[start] == '\r' || json[start] == '\n'))
      start++;
      
   int end = start;
   while(end < StringLen(json) && json[end] != '\"' && json[end] != ',' && json[end] != '}' && json[end] != '\r' && json[end] != '\n')
      end++;
      
   return StringSubstr(json, start, end - start);
}

double ExtractJsonDouble(const string json, const string key)
{
   string val = ExtractJsonString(json, key);
   return StringToDouble(val);
}

bool ExtractJsonBool(const string json, const string key)
{
   string val = ExtractJsonString(json, key);
   StringToLower(val);
   return (StringFind(val, "true") >= 0);
}

//+------------------------------------------------------------------+
//| Lectura de la Señal Bimodal desde Archivo JSON                   |
//+------------------------------------------------------------------+
bool ReadBimodalSignal()
{
   int fileHandle = INVALID_HANDLE;
   
   // Intentar primero en el directorio local de MQL5\Files
   fileHandle = FileOpen(InpSignalFileName, FILE_READ | FILE_TXT | FILE_SHARE_READ | FILE_ANSI);
   
   // Si no se encuentra, buscar en el directorio común de MetaTrader
   if(fileHandle == INVALID_HANDLE)
   {
      fileHandle = FileOpen(InpSignalFileName, FILE_READ | FILE_TXT | FILE_SHARE_READ | FILE_COMMON | FILE_ANSI);
   }
   
   if(fileHandle == INVALID_HANDLE)
      return false;
      
   string content = "";
   while(!FileIsEnding(fileHandle))
   {
      content += FileReadString(fileHandle) + "\n";
   }
   FileClose(fileHandle);
   
   if(StringLen(content) < 10)
      return false;
      
   g_bimodalAction      = ExtractJsonString(content, "action");
   g_bimodalConviction  = ExtractJsonDouble(content, "conviction_score");
   g_bimodalConfidence  = ExtractJsonDouble(content, "confidence_pct");
   g_bimodalVeto        = ExtractJsonBool(content, "bimodal_veto");
   g_bimodalTopNews     = ExtractJsonString(content, "top_news_driver");
   g_bimodalNewsSent    = ExtractJsonDouble(content, "news_sentiment_score");
   g_lastSignalRead     = TimeCurrent();
   
   return true;
}

//+------------------------------------------------------------------+
//| Actualización de Dashboard HUD en Gráfico                        |
//+------------------------------------------------------------------+
void UpdateHud()
{
   string vetoStatus = g_bimodalVeto ? "ALERTA: VETO ACTIVO POR FINBERT" : "AUTORIZADO PARA OPERAR";
   string hud = "";
   hud += "========================================================================\n";
   hud += "        BOT BIMODAL INSTITUCIONAL 25K (V12 FinBERT + Cross-Attention)   \n";
   hud += "========================================================================\n";
   hud += StringFormat(" [ESTADO BIMODAL]  : %s | Confianza: %.1f%%\n", g_bimodalAction, g_bimodalConfidence);
   hud += StringFormat(" [CONVICCIÓN ENSEMBLE]: %+.3f (Umbral Requerido: %.2f)\n", g_bimodalConviction, InpMinConviction);
   hud += StringFormat(" [NOTICIA ATENDIDA]: '%s'\n", StringSubstr(g_bimodalTopNews, 0, 55));
   hud += StringFormat(" [SENTIMIENTO NETO]: %+.3f | Estado Veto: %s\n", g_bimodalNewsSent, vetoStatus);
   hud += "------------------------------------------------------------------------\n";
   hud += StringFormat(" [SESIÓN CASH 15M] : ORB H: %.2f | L: %.2f | Sesión Max: %.2f | Min: %.2f\n", 
                       g_orbHigh, g_orbLow, g_sessionHigh, g_sessionLow);
   hud += StringFormat(" [OPERACIONES HOY] : %d de %d permitidas | Fuerte Tendencia NY: 10:15 - 12:00 (Post-Manipulación)\n",
                       g_dailyTrades, InpMaxDailyTrades);
   hud += StringFormat(" [GESTIÓN 25K]     : %d Contratos ($%.1f/pt) | SL: %.1f pts ($%.0f) | TP2: %.1f pts ($%.0f)\n",
                       InpNumContracts, InpNumContracts * InpLotsPerContract * 2.0, InpStopLossPts, InpStopLossPts * 2.0, InpTarget2Pts, InpTarget2Pts * 2.0);
   hud += StringFormat(" [PROFIT-LOCK C2]  : Al tocar TP1 (+%.1f pts), el Stop de C2 sube a GANANCIAS (+%.1f pts)\n", InpTarget1Pts, InpLockProfitPts);
   hud += "========================================================================";
   
   Comment(hud);
}

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
   
   ReadBimodalSignal();
   UpdateHud();
   
   Print("=== BOT BIMODAL INSTITUCIONAL 25K INICIALIZADO ===");
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
   Comment("");
   Print("Bot Bimodal Institucional 25k cerrado.");
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
      if(g_entryPrice > 0.0)
      {
         g_lastTradeWasWin = g_t1Reached;
         Print(">>> Posición previa cerrada. Resultado Trade ", g_dailyTrades, ": ", (g_lastTradeWasWin ? "GANADOR (TP1 Alcanzado)" : "STOP LOSS"));
      }
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
   
   // Si el precio alcanzó el Target 1
   if(g_isLong)
   {
      if(bid >= g_entryPrice + InpTarget1Pts)
         g_t1Reached = true;
         
      if(g_t1Reached && c2_tick > 0)
      {
         double lockPrice = NormalizeDouble(c2_open + InpLockProfitPts, digits);
         double target2Price = NormalizeDouble(c2_open + InpTarget2Pts, digits);
         if(c2_sl < lockPrice && bid > lockPrice)
         {
            trade.PositionModify(c2_tick, lockPrice, target2Price);
            Print(">>> CANDADO PROFIT-LOCK C2 (BUY): Stop asegurado en GANANCIAS a ", lockPrice, " (+", InpLockProfitPts, " pts) | TP2: ", target2Price);
         }
      }
   }
   else if(g_isShort)
   {
      if(ask <= g_entryPrice - InpTarget1Pts)
         g_t1Reached = true;
         
      if(g_t1Reached && c2_tick > 0)
      {
         double lockPrice = NormalizeDouble(c2_open - InpLockProfitPts, digits);
         double target2Price = NormalizeDouble(c2_open - InpTarget2Pts, digits);
         if((c2_sl > lockPrice || c2_sl == 0.0) && ask < lockPrice)
         {
            trade.PositionModify(c2_tick, lockPrice, target2Price);
            Print(">>> CANDADO PROFIT-LOCK C2 (SELL): Stop asegurado en GANANCIAS a ", lockPrice, " (+", InpLockProfitPts, " pts) | TP2: ", target2Price);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| OnTick: Detección, Validación Bimodal y Ejecución                |
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
      g_dailyTrades = 0;
      g_lastTradeSide = "";
      g_lastTradeWasWin = false;
      g_sessionHigh = 0.0;
      g_sessionLow = 0.0;
   }
   
   int currentMin = dt.hour * 60 + dt.min;
   int orbStartMin = InpServerOrbHour * 60 + InpServerOrbMin; // 16:30 (09:30 NY)
   int entryLimitM = InpServerEndEntryH * 60;                // 19:00 (12:00 NY)
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
   
   // 3. Sincronizar archivo bimodal cada minuto
   if(TimeCurrent() - g_lastSignalRead >= 60)
   {
      ReadBimodalSignal();
      UpdateHud();
   }
   
   // 4. Evaluar solo en apertura de nueva vela M15
   if(!IsNewBar()) return;
   
   // A. Capturar el Rango de Apertura ORB (16:30 a 16:45)
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
         g_sessionHigh = rates[1].high;
         g_sessionLow  = rates[1].low;
         g_orbFormed = true;
         Print(">>> ORB 15M FORMADO: High=", g_orbHigh, " Low=", g_orbLow, " Rango=", rng, " pts");
      }
   }
   
   // Actualizar máximos y mínimos de la sesión activa
   if(g_orbFormed)
   {
      if(rates[1].high > g_sessionHigh) g_sessionHigh = rates[1].high;
      if(rates[1].low < g_sessionLow)   g_sessionLow  = rates[1].low;
   }
   
   UpdateHud();
   
   // B. Evaluar entrada si el ORB está activo, dentro de ventana (16:45 - 19:00) y trades hoy < InpMaxDailyTrades
   if(!g_orbFormed || g_dailyTrades >= InpMaxDailyTrades || currentMin > entryLimitM) return;
   
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
   
   // C. VALIDACIÓN PREVIA DE LA CAPA BIMODAL (FINBERT + CROSS-ATTENTION)
   ReadBimodalSignal();
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   
   //==================================================================
   // OPERACIÓN 1: RUPTURA ORB 15M O ACOPLAMIENTO A DIVERGENCIA (16:45 - 17:30)
   //==================================================================
   if(g_dailyTrades == 0)
   {
      // 5. DISPARO ORB RUPTURA ALCISTA CON VALIDACIÓN BIMODAL
      if(c1 > g_orbHigh && ema_buy_ok)
      {
         if(InpUseBimodalFilter)
         {
            // DIVERGENCIA BAJISTA: Gráfico rompe al alza pero Terminal / FinBERT indican VENTA
            if(g_bimodalAction == "SELL" || g_bimodalConviction < -InpMinConviction || (InpStrictVeto && g_bimodalVeto))
            {
               if(InpExploitDivergence)
               {
                  // ACOPLARSE A LA DIVERGENCIA: Operar la trampa alcista vendiendo (Fade) con Stop ceñido
                  double sl_div  = NormalizeDouble(bid + InpDivStopLossPts, digits);
                  double tp1_div = NormalizeDouble(bid - InpDivTarget1Pts, digits);
                  double tp2_div = NormalizeDouble(bid - InpDivTarget2Pts, digits);
                  
                  double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
                  double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
                  
                  trade.Sell(lot1, _Symbol, bid, sl_div, tp1_div, "BIMODAL_TRAP_SELL_T1_C1");
                  trade.Sell(lot2, _Symbol, bid, sl_div, tp2_div, "BIMODAL_TRAP_SELL_T1_C2");
                  
                  g_dailyTrades++;
                  g_lastTradeSide = "SELL";
                  g_entryPrice  = bid;
                  g_t1Reached   = false;
                  g_isLong      = false;
                  g_isShort     = true;
                  Print(">>> [TRADE 1 - DIVERGENCIA] Trampa alcista detectada: Terminal en VENTA (Convicción: ", g_bimodalConviction, "). DISPARO VENTA: Bid=", bid);
                  return;
               }
               else
               {
                  Print(">>> [DIVERGENCIA CUANTITATIVA] Terminal con sesgo VENTA (Convicción: ", g_bimodalConviction, "). Compra abortada.");
                  return;
               }
            }
            
            if(g_bimodalConviction < InpMinConviction)
            {
               Print(">>> [CONVICCIÓN INSUFICIENTE] Convicción de ", g_bimodalConviction, " < umbral ", InpMinConviction, ". Esperando confirmación.");
               return;
            }
         }
         
         double sl  = NormalizeDouble(ask - InpStopLossPts, digits);
         double tp1 = NormalizeDouble(ask + InpTarget1Pts, digits);
         double tp2 = NormalizeDouble(ask + InpTarget2Pts, digits);
         
         double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
         double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
         
         trade.Buy(lot1, _Symbol, ask, sl, tp1, "BIMODAL_T1_BUY_C1");
         trade.Buy(lot2, _Symbol, ask, sl, tp2, "BIMODAL_T1_BUY_C2");
         
         g_dailyTrades++;
         g_lastTradeSide = "BUY";
         g_entryPrice  = ask;
         g_t1Reached   = false;
         g_isLong      = true;
         g_isShort     = false;
         Print(">>> [TRADE 1] DISPARO ORB COMPRA BIMODAL (VALIDADO): Ask=", ask, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
      }
      // 6. DISPARO ORB RUPTURA BAJISTA CON VALIDACIÓN BIMODAL
      else if(c1 < g_orbLow && ema_sell_ok)
      {
         if(InpUseBimodalFilter)
         {
            // DIVERGENCIA ALCISTA: Gráfico rompe a la baja pero Terminal / FinBERT indican COMPRA
            if(g_bimodalAction == "BUY" || g_bimodalConviction > InpMinConviction || (InpStrictVeto && g_bimodalVeto))
            {
               if(InpExploitDivergence)
               {
                  // ACOPLARSE A LA DIVERGENCIA: Operar la trampa bajista comprando (Fade) con Stop ceñido
                  double sl_div  = NormalizeDouble(ask - InpDivStopLossPts, digits);
                  double tp1_div = NormalizeDouble(ask + InpDivTarget1Pts, digits);
                  double tp2_div = NormalizeDouble(ask + InpDivTarget2Pts, digits);
                  
                  double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
                  double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
                  
                  trade.Buy(lot1, _Symbol, ask, sl_div, tp1_div, "BIMODAL_TRAP_BUY_T1_C1");
                  trade.Buy(lot2, _Symbol, ask, sl_div, tp2_div, "BIMODAL_TRAP_BUY_T1_C2");
                  
                  g_dailyTrades++;
                  g_lastTradeSide = "BUY";
                  g_entryPrice  = ask;
                  g_t1Reached   = false;
                  g_isLong      = true;
                  g_isShort     = false;
                  Print(">>> [TRADE 1 - DIVERGENCIA] Trampa bajista detectada: Terminal en COMPRA (Convicción: ", g_bimodalConviction, "). DISPARO COMPRA: Ask=", ask);
                  return;
               }
               else
               {
                  Print(">>> [DIVERGENCIA CUANTITATIVA] Terminal con sesgo COMPRA (Convicción: ", g_bimodalConviction, "). Venta abortada.");
                  return;
               }
            }
            
            if(g_bimodalConviction > -InpMinConviction)
            {
               Print(">>> [CONVICCIÓN INSUFICIENTE] Convicción de ", g_bimodalConviction, " > umbral -", InpMinConviction, ". Esperando confirmación.");
               return;
            }
         }
         
         double sl  = NormalizeDouble(bid + InpStopLossPts, digits);
         double tp1 = NormalizeDouble(bid - InpTarget1Pts, digits);
         double tp2 = NormalizeDouble(bid - InpTarget2Pts, digits);
         
         double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
         double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
         
         trade.Sell(lot1, _Symbol, bid, sl, tp1, "BIMODAL_T1_SELL_C1");
         trade.Sell(lot2, _Symbol, bid, sl, tp2, "BIMODAL_T1_SELL_C2");
         
         g_dailyTrades++;
         g_lastTradeSide = "SELL";
         g_entryPrice  = bid;
         g_t1Reached   = false;
         g_isLong      = false;
         g_isShort     = true;
         Print(">>> [TRADE 1] DISPARO ORB VENTA BIMODAL (VALIDADO): Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
      }
   }
   //==================================================================
   // OPERACIÓN 2: FUERTE TENDENCIA POST-MANIPULACIÓN DE NEW YORK (17:15 - 19:00)
   //==================================================================
   else if(g_dailyTrades == 1 && currentMin >= (orbStartMin + 45))
   {
      double lot1 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);
      double lot2 = (InpNumContracts == 2) ? InpLotsPerContract : (InpLotsPerContract * 0.5);

      // CASO A: Continuación de Tendencia Fuerte tras Ganar Trade 1
      if(g_lastTradeWasWin)
      {
         // Continuación Alcista (Rompe nuevo máximo de sesión por encima de EMA)
         if(g_lastTradeSide == "BUY" && c1 > g_sessionHigh && ema_buy_ok)
         {
            if(InpUseBimodalFilter && (g_bimodalAction == "SELL" || (InpStrictVeto && g_bimodalVeto)))
            {
               Print(">>> [TRADE 2 BLOQUEADO] Veto bimodal activo ante continuación alcista.");
               return;
            }
            double sl  = NormalizeDouble(ask - InpStopLossPts, digits);
            double tp1 = NormalizeDouble(ask + InpTarget1Pts, digits);
            double tp2 = NormalizeDouble(ask + InpTarget2Pts, digits);
            
            trade.Buy(lot1, _Symbol, ask, sl, tp1, "BIMODAL_T2_TREND_BUY_C1");
            trade.Buy(lot2, _Symbol, ask, sl, tp2, "BIMODAL_T2_TREND_BUY_C2");
            
            g_dailyTrades++;
            g_entryPrice = ask;
            g_t1Reached  = false;
            g_isLong     = true;
            g_isShort    = false;
            Print(">>> [TRADE 2 - CONTINUACIÓN NY] Fuerte Tendencia Alcista Confirmada: Ask=", ask, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
         }
         // Continuación Bajista (Rompe nuevo mínimo de sesión por debajo de EMA)
         else if(g_lastTradeSide == "SELL" && c1 < g_sessionLow && ema_sell_ok)
         {
            if(InpUseBimodalFilter && (g_bimodalAction == "BUY" || (InpStrictVeto && g_bimodalVeto)))
            {
               Print(">>> [TRADE 2 BLOQUEADO] Veto bimodal activo ante continuación bajista.");
               return;
            }
            double sl  = NormalizeDouble(bid + InpStopLossPts, digits);
            double tp1 = NormalizeDouble(bid - InpTarget1Pts, digits);
            double tp2 = NormalizeDouble(bid - InpTarget2Pts, digits);
            
            trade.Sell(lot1, _Symbol, bid, sl, tp1, "BIMODAL_T2_TREND_SELL_C1");
            trade.Sell(lot2, _Symbol, bid, sl, tp2, "BIMODAL_T2_TREND_SELL_C2");
            
            g_dailyTrades++;
            g_entryPrice = bid;
            g_t1Reached  = false;
            g_isLong     = false;
            g_isShort    = true;
            Print(">>> [TRADE 2 - CONTINUACIÓN NY] Fuerte Tendencia Bajista Confirmada: Bid=", bid, " SL=", sl, " TP1=", tp1, " TP2=", tp2);
         }
      }
      // CASO B: Reversión a la Verdadera Tendencia Post-Manipulación (si Trade 1 fue sacudido por trampa)
      else
      {
         // Trade 1 compró pero fue falso rompimiento de apertura (Judas Swing) y ahora el mercado se hunde por debajo del ORB Low
         if(g_lastTradeSide == "BUY" && c1 < g_orbLow && ema_sell_ok)
         {
            if(InpUseBimodalFilter && (g_bimodalAction == "BUY" || (InpStrictVeto && g_bimodalVeto)))
            {
               Print(">>> [TRADE 2 BLOQUEADO] Veto bimodal activo ante reversión post-manipulación.");
               return;
            }
            double sl_rev  = NormalizeDouble(bid + InpDivStopLossPts, digits);
            double tp1_rev = NormalizeDouble(bid - InpDivTarget1Pts, digits);
            double tp2_rev = NormalizeDouble(bid - InpTarget2Pts, digits);
            
            trade.Sell(lot1, _Symbol, bid, sl_rev, tp1_rev, "BIMODAL_T2_POST_MANIP_SELL_C1");
            trade.Sell(lot2, _Symbol, bid, sl_rev, tp2_rev, "BIMODAL_T2_POST_MANIP_SELL_C2");
            
            g_dailyTrades++;
            g_entryPrice = bid;
            g_t1Reached  = false;
            g_isLong     = false;
            g_isShort    = true;
            Print(">>> [TRADE 2 - REVERSIÓN POST-MANIPULACIÓN] Verdadera Tendencia Bajista NY Iniciada: Bid=", bid, " SL=", sl_rev, " TP1=", tp1_rev, " TP2=", tp2_rev);
         }
         // Trade 1 vendió pero fue trampa bajista de apertura que barrió liquidez y ahora explota sobre el ORB High
         else if(g_lastTradeSide == "SELL" && c1 > g_orbHigh && ema_buy_ok)
         {
            if(InpUseBimodalFilter && (g_bimodalAction == "SELL" || (InpStrictVeto && g_bimodalVeto)))
            {
               Print(">>> [TRADE 2 BLOQUEADO] Veto bimodal activo ante reversión post-manipulación.");
               return;
            }
            double sl_rev  = NormalizeDouble(ask - InpDivStopLossPts, digits);
            double tp1_rev = NormalizeDouble(ask + InpDivTarget1Pts, digits);
            double tp2_rev = NormalizeDouble(ask + InpTarget2Pts, digits);
            
            trade.Buy(lot1, _Symbol, ask, sl_rev, tp1_rev, "BIMODAL_T2_POST_MANIP_BUY_C1");
            trade.Buy(lot2, _Symbol, ask, sl_rev, tp2_rev, "BIMODAL_T2_POST_MANIP_BUY_C2");
            
            g_dailyTrades++;
            g_entryPrice = ask;
            g_t1Reached  = false;
            g_isLong     = true;
            g_isShort    = false;
            Print(">>> [TRADE 2 - REVERSIÓN POST-MANIPULACIÓN] Verdadera Tendencia Alcista NY Iniciada: Ask=", ask, " SL=", sl_rev, " TP1=", tp1_rev, " TP2=", tp2_rev);
         }
      }
   }
}
//+------------------------------------------------------------------+
