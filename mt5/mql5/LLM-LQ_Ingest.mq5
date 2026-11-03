//+------------------------------------------------------------------+
//|                                          LLM-LQ_Ingest.mq5       |
//|                        MetaTrader 5 OHLC Data Ingest Expert       |
//|                                                                  |
//+------------------------------------------------------------------+
#property strict
#property description "LLM-LQ MT5 OHLC Ingest Expert"
#property version   "1.00"
#property library

#include <DLL_Ingest.h>

// ── Configuration inputs ──────────────────────────────────────────────
input string InpGatewayUrl  = "http://192.168.11.175:8088/api/mt5/ingest";
input int    InpCandleCount = 10;
input string InpJsonFolder  = "LLM-LQ";
input int    InpTimeoutMs   = 30000;

// ── State ─────────────────────────────────────────────────────────────
datetime lastCandleOpenTime = 0;
bool     dllLoaded          = false;

// ── EA lifecycle ──────────────────────────────────────────────────────
int OnInit()
{
   // Try to load the DLL.  MQL5's LoadLibrary only resolves via the
   // terminal directory + system paths, so place lq_ingest.dll in the
   // terminal's Experts\DLLs\ folder OR copy it to Common\Files\LLM-LQ\
   // and rely on the DLL's own path resolution (see DLL_Ingest_Init).
   dllLoaded = DLL_Ingest_Init();
   if(!dllLoaded)
   {
      PrintFormat("LQ: DLL not loaded (err=%d). OHLC will be written to file but not sent.", GetLastError());
   }
   else
   {
      Print("LQ: DLL loaded. Gateway: ", InpGatewayUrl);
   }

   lastCandleOpenTime = iTime(_Symbol, _Period, 0);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   DLL_Ingest_Deinit();
}

void OnTick()
{
   datetime currentOpenTime = iTime(_Symbol, _Period, 0);
   if(currentOpenTime == lastCandleOpenTime)
      return;

   // New candle detected – process the previous completed candle's batch.
   lastCandleOpenTime = currentOpenTime;
   ProcessAndSendOHLC();
}

// ── Core logic ────────────────────────────────────────────────────────
void ProcessAndSendOHLC()
{
   int needed = InpCandleCount;
   int bars   = iBars(_Symbol, _Period);
   if(bars < needed + 1)
   {
      PrintFormat("LQ: not enough bars (%d) to collect %d completed candles. Wait.", bars, needed);
      return;
   }

   // We need the last 'needed' COMPLETED candles (shift 1 is newest completed,
   // shift 'needed' is oldest).  Store oldest-first in arrays.
   double openArr[], highArr[], lowArr[], closeArr[];
   datetime timeArr[];

   ArrayResize(openArr,  needed);
   ArrayResize(highArr,  needed);
   ArrayResize(lowArr,   needed);
   ArrayResize(closeArr, needed);
   ArrayResize(timeArr,  needed);

   for(int i = 0; i < needed; i++)
   {
      int shift = needed - i;   // shift 1 = newest completed, shift needed = oldest
      timeArr[i]    = iTime(_Symbol, _Period, shift);
      openArr[i]    = iOpen(_Symbol, _Period, shift);
      highArr[i]    = iHigh(_Symbol, _Period, shift);
      lowArr[i]     = iLow(_Symbol, _Period, shift);
      closeArr[i]   = iClose(_Symbol, _Period, shift);
   }

   // ── Build JSON payload ──────────────────────────────────────────────
   string tfStr  = EnumToString(_Period);
   string symbol = _Symbol;
   string reqId  = symbol + "_" + tfStr + "_" + TimeToString(timeArr[0], TIME_DATE|TIME_SECONDS);
   string ts     = TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS);

   string json = "{";
   json += "\"request_id\":\""   + reqId   + "\",";
   json += "\"symbol\":\""       + symbol  + "\",";
   json += "\"timeframe\":\""    + tfStr   + "\",";
   json += "\"timestamp\":\""    + ts      + "\",";
   json += "\"candle_count\":"   + IntegerToString(needed) + ",";
   json += "\"candles\":[";

   for(int i = 0; i < needed; i++)
   {
      if(i > 0) json += ",";
      json += "{";
      json += "\"time\":\""  + TimeToString(timeArr[i], TIME_DATE|TIME_SECONDS) + "\",";
      json += "\"open\":"    + DoubleToString(openArr[i], 8) + ",";
      json += "\"high\":"    + DoubleToString(highArr[i], 8) + ",";
      json += "\"low\":"     + DoubleToString(lowArr[i], 8) + ",";
      json += "\"close\":"   + DoubleToString(closeArr[i], 8) + "}";
   }

   json += "]}";

   // ── Write to Common Files as UTF-16 ─────────────────────────────────
   string fileName = reqId + ".json";
   int    handle   = FileOpen(fileName, FILE_WRITE | FILE_READ | FILE_COMMON, CP_UTF16);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("LQ: FileOpen failed, err=%d", GetLastError());
      return;
   }

   int written = FileWriteString(handle, json);
   FileClose(handle);

   if(written < 0)
   {
      PrintFormat("LQ: FileWriteString failed, err=%d", GetLastError());
      return;
   }

   PrintFormat("LQ: Wrote %d chars to Common Files\\%s", written, fileName);

   // ── Send via DLL ────────────────────────────────────────────────────
   if(dllLoaded)
   {
      int result = DLL_Ingest_Send(fileName, InpGatewayUrl, InpTimeoutMs);
      PrintFormat("LQ: DLL_Ingest_Send result=%d", result);
   }
   else
   {
      Print("LQ: DLL not available – file written to disk, not sent.");
   }
}
//+------------------------------------------------------------------+