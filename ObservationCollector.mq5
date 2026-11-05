//+------------------------------------------------------------------+
//| ObservationCollector.mq5                                         |
//| MT5 -> AI Gateway Observer v2.0                                  |
//| Three-box, ZigZag, H1/H6 river, transport via egg.dll            |
//+------------------------------------------------------------------+
#property copyright "MIT"
#property version   "2.00"
#property strict

#include "Common.mqh"
#include "SimpleLogger.mqh"
#include "MovingAverages.mqh"
#include "Structure.mqh"

#include "MA_BOX\\FractalGeometry.mqh"
#include "MA_BOX\\FlatZoneSmallBoxObserver.mqh"

#include "MA_INERTIA\\RainBowDynamics.mqh"
#include "MA_INERTIA\\ZigZagEngine.mqh"
#include "MA_INERTIA\\MABifurcation.mqh"
#include "MA_INERTIA\\ZigZagAdvisor.mqh"

// egg.dll transport
#import "egg.dll"
int SendLatestJson();
#import

#import "egg.dll"
int PollResponses(string clientId, uchar &output[], int outputCapacity);
#import

#include <JAson.mqh>
CJAVal g_json;

//============================================================
// Configuration
//============================================================
string CLIENT_ID = "mt5_terminal_01";

int FAST_PERIOD  = 7;
int SLOW_PERIOD  = 14;
int H6_FAST      = 42;   // 6x H1
int H6_SLOW      = 84;   // 6x H1

int CANDLE_RANGE = 50;
int MAX_SMALL_BOXES = 10;

string OUTPUT_FOLDER = "LLM-LQ";
string OUTPUT_FILE   = "LLM-LQ\\mt5_feed.json";

//============================================================
// Global instances
//============================================================
CMovingAverages  m_maFast;
CMovingAverages  m_maSlow;
CMovingAverages  m_maH6;

CStructure       m_stc;
CFractalGeometry m_fractal;

CRainBowDynamics m_dynoSlow;
CRainBowDynamics m_dynoH6;

CZigZagAdvisor   m_zigZag;

CSimpleLogger    g;

uchar            m_responseBuf[8192];
int              m_lastSendStatus = 0;
int              m_lastPollStatus = 0;
int              m_lastPollBytes  = 0;

//============================================================
// Runtime state
//============================================================
datetime lastBarTime           = 0;
datetime lastProcessedBoxStart = 0;
datetime lastH6BarTime         = 0;

//============================================================
// JSON helpers
//============================================================
string JsonEscape(string value)
{
   StringReplace(value, "\\\\", "\\\\\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");
   return value;
}

string JsonBool(bool value)
{
   return value ? "true" : "false";
}

string JsonTime(datetime value)
{
   if(value <= 0)
      return "\"\"";
   return "\"" + JsonEscape(TimeToString(value, TIME_DATE | TIME_MINUTES)) + "\"";
}

string JsonDouble(double value, int digits)
{
   if(!MathIsValidNumber(value))
      return "null";
   return DoubleToString(value, digits);
}

//============================================================
// 3-box logic
//============================================================
bool BoxesOverlap(const FlatZone &a, const FlatZone &b)
{
   // Spatial overlap
   if(a.highPrice < b.lowPrice || b.highPrice < a.lowPrice)
      return false;
   // Temporal check: must be close in time (within 2 periods)
   long gap = (long)MathMax( a.startTime, b.startTime ) - MathMin( a.endTime, b.endTime );
   int  periodSec = PeriodSeconds(_Period);
   if(periodSec <= 0) periodSec = PeriodSeconds(PERIOD_H1);
   if(gap > periodSec * 2)
      return false;
   return true;
}

// Returns count of non-overlapping boxes (up to 3), fills out[] oldest first
int ExtractThreeBoxes(FlatZone &out[])
{
   int total = m_fractal.SmallBoxCount();
   int found = 0;
   FlatZone temp[];
   ArrayResize(temp, total);

   // Collect all boxes
   for(int i = 0; i < total; i++)
      m_fractal.GetSmallBox(i, temp[i]);

   // Pick non-overlapping ones, newest first, up to 3
   int picked[];
   ArrayResize(picked, 0);

   for(int i = 0; i < total && ArraySize(picked) < 3; i++)
   {
      bool ok = true;
      for(int j = 0; j < ArraySize(picked); j++)
      {
         if(BoxesOverlap(temp[i], temp[picked[j]]))
         {
            ok = false;
            break;
         }
      }
      if(ok)
      {
         int pos = ArraySize(picked);
         ArrayResize(picked, pos + 1);
         picked[pos] = i;
      }
   }

   int n = ArraySize(picked);
   for(int i = 0; i < n; i++)
      out[i] = temp[picked[i]];

   return n;
}

//============================================================
// River calculation (H1)
//============================================================
void RiverValues(int shift, double &top, double &bot, double &center, double &widthPips)
{
   double e7  = m_maSlow.EMA7 (shift);
   double e14 = m_maSlow.EMA14(shift);
   double s7  = m_maSlow.SMA7 (shift);
   double s14 = m_maSlow.SMA14(shift);
   top    = MathMax(MathMax(e7, e14), MathMax(s7, s14));
   bot    = MathMin(MathMin(e7, e14), MathMin(s7, s14));
   center = (top + bot) * 0.5;
   widthPips = (top - bot) / _Point / 10.0;
   if(!MathIsValidNumber(top))
   {
      top = 0; bot = 0; center = 0; widthPips = 0;
   }
}

// River calculation (H6)
void H6RiverValues(int shift, double &center, double &widthPips)
{
   double c = m_dynoH6.RainbowCenter(shift);
   double w = m_dynoH6.RainbowWidth(shift);
   center    = c;
   widthPips = w;
   if(!MathIsValidNumber(c) || c <= 0)
      center = 0;
}

//============================================================
// Build candles (H1)
//============================================================
void BuildCandles(string &json, int range)
{
   json = "[";
   int written = 0;
   int available = Bars(_Symbol, _Period);
   int limit = range;
   if(available < limit) limit = available;

   for(int shift = 0; shift < limit; shift++)
   {
      datetime t  = iTime(_Symbol, _Period, shift);
      if(t <= 0) continue;
      double openP  = iOpen (_Symbol, _Period, shift);
      double highP  = iHigh(_Symbol, _Period, shift);
      double lowP   = iLow (_Symbol, _Period, shift);
      double closeP = iClose(_Symbol, _Period, shift);
      long   tickV  = iVolume(_Symbol, _Period, shift);
      int    spread  = iSpread(_Symbol, _Period, shift);

      if(written > 0) json += ",";
      json += "{";
      json += "\"shift\":" + IntegerToString(shift) + ",";
      json += "\"time\":" + JsonTime(t) + ",";
      json += "\"is_closed\":" + JsonBool(shift > 0) + ",";
      json += "\"open\":" + JsonDouble(openP, _Digits) + ",";
      json += "\"high\":" + JsonDouble(highP, _Digits) + ",";
      json += "\"low\":" + JsonDouble(lowP, _Digits) + ",";
      json += "\"close\":" + JsonDouble(closeP, _Digits) + ",";
      json += "\"tick_volume\":" + IntegerToString(tickV) + ",";
      json += "\"spread\":" + IntegerToString(spread);
      json += "}";
      written++;
   }
   json += "]";
}

//============================================================
// Build small boxes
//============================================================
void BuildSmallBoxes(string &json)
{
   json = "[";
   int count = m_fractal.SmallBoxCount();
   int written = 0;

   for(int i = 0; i < count && written < MAX_SMALL_BOXES; i++)
   {
      FlatZone box;
      if(!m_fractal.GetSmallBox(i, box))
         continue;
      if(written > 0) json += ",";
      json += "{";
      json += "\"index\":" + IntegerToString(i) + ",";
      json += "\"start_time\":" + JsonTime(box.startTime) + ",";
      json += "\"end_time\":" + JsonTime(box.endTime) + ",";
      json += "\"high\":" + JsonDouble(box.highPrice, _Digits) + ",";
      json += "\"low\":" + JsonDouble(box.lowPrice, _Digits) + ",";
      json += "\"window_size\":" + IntegerToString(box.windowSize);
      json += "}";
      written++;
   }
   json += "]";
}

//============================================================
// Build 3-box section
//============================================================
void BuildThreeBoxes(string &json, FlatZone &three[], int threeCount)
{
   json = "[";
   for(int i = 0; i < threeCount; i++)
   {
      if(i > 0) json += ",";
      json += "{";
      json += "\"slot\":" + IntegerToString(i) + ",";
      json += "\"start_time\":" + JsonTime(three[i].startTime) + ",";
      json += "\"end_time\":" + JsonTime(three[i].endTime) + ",";
      json += "\"high\":" + JsonDouble(three[i].highPrice, _Digits) + ",";
      json += "\"low\":" + JsonDouble(three[i].lowPrice, _Digits) + ",";
      json += "\"start_shift\":" + IntegerToString(three[i].startShift) + ",";
      json += "\"end_shift\":" + IntegerToString(three[i].endShift);
      json += "}";
   }
   json += "]";
}

//============================================================
// Build ZigZag section
//============================================================
void BuildZigZag(string &json)
{
   CZigZagEngine *zz = m_zigZag.ZigZag();
   if(zz == NULL)
   {
      json = "{}";
      return;
   }

   ZZResult res;
   if(!zz.GetResult(0, res))
   {
      json = "{}";
      return;
   }

   int dir = m_zigZag.ZigZagDirection();
   int maDir = m_zigZag.MADirection();
   bool contra = m_zigZag.Contradiction();

   json = "{";
   json += "\"label\":\"" + JsonEscape(res.label) + "\",";
   json += "\"theory\":\"" + JsonEscape(res.theory) + "\",";
   json += "\"reason\":\"" + JsonEscape(res.reason) + "\",";
   json += "\"direction\":" + IntegerToString(dir) + ",";
   json += "\"ma_direction\":" + IntegerToString(maDir) + ",";
   json += "\"contradiction\":" + JsonBool(contra) + ",";
   json += "\"sse\":" + JsonDouble(res.sse, 4) + ",";
   json += "\"imbalance\":" + JsonDouble(res.imbalance, 4) + ",";
   json += "\"high_slope_deg\":" + JsonDouble(res.highSlopeDeg, 2) + ",";
   json += "\"low_slope_deg\":" + JsonDouble(res.lowSlopeDeg, 2) + ",";
   json += "\"points\":[";

   int npts = ArraySize(res.points);
   for(int i = 0; i < npts; i++)
   {
      if(i > 0) json += ",";
      json += "{";
      json += "\"shift\":" + IntegerToString(res.points[i].shift) + ",";
      json += "\"time\":" + JsonTime(res.points[i].time) + ",";
      json += "\"price\":" + JsonDouble(res.points[i].price, _Digits) + ",";
      json += "\"type\":" + IntegerToString(res.points[i].type);
      json += "}";
   }
   json += "]";
   json += "}";
}

//============================================================
// Build description
//============================================================
void BuildDescription(string &json)
{
   double ema7  = m_maSlow.EMA7 (1);
   double ema14 = m_maSlow.EMA14(1);
   double sma7  = m_maSlow.SMA7 (1);
   double sma14 = m_maSlow.SMA14(1);
   bool emaBull = (ema7 > ema14);
   bool smaBull = (sma7 > sma14);
   int maDir = 0;
   if(emaBull && smaBull)
      maDir = 1;
   else if(!emaBull && !smaBull)
      maDir = -1;

   int boxCount = m_fractal.SmallBoxCount();

   json = "{";
   json += "\"ma_direction\":" + IntegerToString(maDir) + ",";
   json += "\"ema7\":" + JsonDouble(ema7, _Digits) + ",";
   json += "\"ema14\":" + JsonDouble(ema14, _Digits) + ",";
   json += "\"sma7\":" + JsonDouble(sma7, _Digits) + ",";
   json += "\"sma14\":" + JsonDouble(sma14, _Digits) + ",";
   json += "\"zigzag_direction\":" + IntegerToString(m_zigZag.ZigZagDirection()) + ",";
   json += "\"contradiction\":" + JsonBool(m_zigZag.Contradiction()) + ",";
   json += "\"box_count\":" + IntegerToString(boxCount);
   json += "}";
}

//============================================================
// Build market info
//============================================================
void BuildMarketInfo(string &json)
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   long   sp  = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   json = "{";
   json += "\"symbol\":\"" + JsonEscape(_Symbol) + "\",";
   json += "\"timeframe\":\"" + EnumToString(_Period) + "\",";
   json += "\"digits\":" + IntegerToString(_Digits) + ",";
   json += "\"point\":" + JsonDouble(_Point, _Digits + 2) + ",";
   json += "\"bid\":" + JsonDouble(bid, _Digits) + ",";
   json += "\"ask\":" + JsonDouble(ask, _Digits) + ",";
   json += "\"spread_points\":" + IntegerToString(sp);
   json += "}";
}

//============================================================
// Build H6 info
//============================================================
void BuildH6Info(string &json)
{
   double e42 = m_maH6.EMA7 (1);
   double e84 = m_maH6.EMA14(1);
   double s42 = m_maH6.SMA7 (1);
   double s84 = m_maH6.SMA14(1);

   json = "{";
   json += "\"timeframe\":\"H6\",";
   json += "\"ema42\":" + JsonDouble(e42, _Digits) + ",";
   json += "\"ema84\":" + JsonDouble(e84, _Digits) + ",";
   json += "\"sma42\":" + JsonDouble(s42, _Digits) + ",";
   json += "\"sma84\":" + JsonDouble(s84, _Digits);
   json += "}";
}

//============================================================
// Build H6 candles + river
//============================================================
void BuildH6Candles(string &json, int h6Start, int h6End)
{
   json = "[";
   int written = 0;

   for(int s = h6Start; s <= h6End; s++)
   {
      datetime t = iTime(_Symbol, PERIOD_H6, s);
      if(t <= 0)
         continue;

      double openP  = iOpen (_Symbol, PERIOD_H6, s);
      double highP  = iHigh(_Symbol, PERIOD_H6, s);
      double lowP   = iLow (_Symbol, PERIOD_H6, s);
      double closeP = iClose(_Symbol, PERIOD_H6, s);

      double center, widthPips;
      H6RiverValues(s, center, widthPips);

      if(written > 0)
         json += ",";

      json += "{";
      json += "\"h6_shift\":" + IntegerToString(s) + ",";
      json += "\"time\":" + JsonTime(t) + ",";
      json += "\"is_closed\":" + JsonBool(s > 0) + ",";
      json += "\"open\":" + JsonDouble(openP, _Digits) + ",";
      json += "\"high\":" + JsonDouble(highP, _Digits) + ",";
      json += "\"low\":" + JsonDouble(lowP, _Digits) + ",";
      json += "\"close\":" + JsonDouble(closeP, _Digits) + ",";
      json += "\"river_center\":" + JsonDouble(center, _Digits) + ",";
      json += "\"river_width_pips\":" + JsonDouble(widthPips, 1);
      json += "}";
      written++;
   }
   json += "]";
}

//============================================================
// Build H1 river from 3rd box to now
//============================================================
void BuildH1River(string &json, int fromShift, int toShift)
{
   json = "[";
   int written = 0;

   for(int s = fromShift; s <= toShift; s++)
   {
      datetime t = iTime(_Symbol, _Period, s);
      if(t <= 0)
         continue;

      double top, bot, center, widthPips;
      RiverValues(s, top, bot, center, widthPips);

      if(written > 0)
         json += ",";

      json += "{";
      json += "\"shift\":" + IntegerToString(s) + ",";
      json += "\"time\":" + JsonTime(t) + ",";
      json += "\"close\":" + JsonDouble(iClose(_Symbol,_Period,s), _Digits) + ",";
      json += "\"river_top\":" + JsonDouble(top, _Digits) + ",";
      json += "\"river_bottom\":" + JsonDouble(bot, _Digits) + ",";
      json += "\"river_center\":" + JsonDouble(center, _Digits) + ",";
      json += "\"river_width_pips\":" + JsonDouble(widthPips, 1);
      json += "}";
      written++;
   }
   json += "]";
}

//============================================================
// Assemble the full JSON packet
//============================================================
string BuildJsonPacket(FlatZone &three[], int threeCount)
{
   int lastClosed = iBarShift(_Symbol, _Period, iTime(_Symbol,_Period,1), false);

   // H1 candles: from 3rd box start to last closed candle
   int candleStartShift;
   if(threeCount >= 3)
      candleStartShift = three[2].startShift;
   else
      candleStartShift = 1;

   if(candleStartShift < lastClosed)
      candleStartShift = lastClosed;

   // Candles array
   string candlesJson;
   BuildCandles(candlesJson, CANDLE_RANGE);

   // Small boxes
   string smallBoxesJson;
   BuildSmallBoxes(smallBoxesJson);

   // Three boxes
   string threeBoxesJson;
   BuildThreeBoxes(threeBoxesJson, three, threeCount);

   // ZigZag
   string zzJson;
   BuildZigZag(zzJson);

   // Description
   string descJson;
   BuildDescription(descJson);

   // Market
   string marketJson;
   BuildMarketInfo(marketJson);

   // H6 info
   string h6Json;
   BuildH6Info(h6Json);

   // H6 candles: around the three boxes
   int h6Start = 0, h6End = 0;
   if(threeCount >= 1)
   {
      datetime oldest = three[threeCount-1].startTime;
      datetime newest = three[0].endTime;
      h6Start = iBarShift(_Symbol, PERIOD_H6, newest, false);
      h6End   = iBarShift(_Symbol, PERIOD_H6, oldest, false);
      if(h6Start < 0) h6Start = 0;
      if(h6End < 0)   h6End   = 0;
      if(h6Start > h6End)
      {
         int t = h6Start;
         h6Start = h6End;
         h6End   = t;
      }
   }
   else
   {
      h6Start = 0;
      h6End   = 0;
   }

   string h6CandlesJson;
   BuildH6Candles(h6CandlesJson, h6Start, h6End);

   // H1 river: from 3rd box start to last closed
   string h1RiverJson;
   BuildH1River(h1RiverJson, candleStartShift, lastClosed);

   string timestamp = JsonTime(TimeCurrent());

   string json = "{";
   json += "\"client_id\":\"" + JsonEscape(CLIENT_ID) + "\",";
   json += "\"timestamp\":" + timestamp + ",";
   json += "\"market\":" + marketJson + ",";
   json += "\"h6_market\":" + h6Json + ",";
   json += "\"candles\":" + candlesJson + ",";
   json += "\"small_boxes\":" + smallBoxesJson + ",";
   json += "\"three_boxes\":" + threeBoxesJson + ",";
   json += "\"zigzag\":" + zzJson + ",";
   json += "\"description\":" + descJson + ",";
   json += "\"h1_river\":" + h1RiverJson + ",";
   json += "\"h6_candles\":" + h6CandlesJson;
   json += "}";

   return json;
}

//============================================================
// Write to file and send
//============================================================
void WriteAndSend(string &json)
{
   FolderCreate(OUTPUT_FOLDER);

   int handle = FileOpen(
      OUTPUT_FILE,
      FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ
   );

   if(handle == INVALID_HANDLE)
   {
      int err = GetLastError();
      Print("ObservationCollector: FileOpen failed. Error = ", err);
      g.Log("FileOpen failed, error=" + IntegerToString(err));
      return;
   }

   FileWriteString(handle, json);
   FileWriteString(handle, "\r\n");
   FileFlush(handle);
   FileClose(handle);

   g.Log("JSON written, " + IntegerToString(StringLen(json)) + " chars");

   m_lastSendStatus = SendLatestJson();
   if(m_lastSendStatus >= 200 && m_lastSendStatus < 300)
      g.Log("Send OK, status=" + IntegerToString(m_lastSendStatus));
   else if(m_lastSendStatus == 204)
      g.Log("Send skipped (same hash)");
   else
      g.Log("Send failed, status=" + IntegerToString(m_lastSendStatus));
}

//============================================================
// Poll responses
//============================================================
void PollResponses_()
{
   int bytes = PollResponses(
      CLIENT_ID,
      m_responseBuf,
      ArraySize(m_responseBuf)
   );

   m_lastPollBytes = bytes;

   if(bytes > 0)
   {
      string respStr = CharArrayToString(m_responseBuf, 0, bytes, CP_UTF8);
      g_json.Deserialize(respStr, CP_UTF8);

      bool ok = g_json["success"].ToBool();
      int  cnt = (int)g_json["count"].ToInt();

      if(ok && cnt > 0)
      {
         CJAVal *arr = g_json.FindKey("responses");
         if(CheckPointer(arr) != POINTER_INVALID)
         {
            for(int i = 0; i < arr.Size(); i++)
            {
               string msg = arr[i].Serialize();
               Print("AI response [", i, "]: ", msg);
               g.Log("AI_RESP: " + msg);
            }
         }
      }
      else
      {
         m_lastPollStatus = 0;
      }
   }
}

//============================================================
// Draw boxes on chart
//============================================================
void DrawBox(const FlatZone &box, const int slotIdx)
{
   string name = "OC_BOX_" + IntegerToString(slotIdx);
   datetime t1 = box.startTime;
   datetime t2 = box.endTime;
   double   p1 = box.highPrice;
   double   p2 = box.lowPrice;

   color clr;
   if(slotIdx == 0)
      clr = clrLime;
   else if(slotIdx == 1)
      clr = clrGold;
   else
      clr = clrSilver;

   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);

   ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, name, OBJPROP_FILL, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetString(0, name, OBJPROP_TOOLTIP,
      "Box " + IntegerToString(slotIdx) + "\n" +
      "High: " + DoubleToString(box.highPrice, _Digits) + "\n" +
      "Low:  " + DoubleToString(box.lowPrice, _Digits) + "\n" +
      "Start: " + TimeToString(t1, TIME_DATE|TIME_MINUTES) + "\n" +
      "End:   " + TimeToString(t2, TIME_DATE|TIME_MINUTES));
}

//============================================================
// Draw ZigZag points on chart
//============================================================
void DrawZigZagPoints()
{
   CZigZagEngine *zz = m_zigZag.ZigZag();
   if(zz == NULL)
      return;

   ZZResult res;
   if(!zz.GetResult(0, res))
      return;

   int n = ArraySize(res.points);
   for(int i = 0; i < n; i++)
   {
      string tag = "OC_ZZ_" + IntegerToString(i);
      ObjectCreate(0, tag, OBJ_ARROW, 0, res.points[i].time, res.points[i].price);
      ObjectSetInteger(0, tag, OBJPROP_COLOR, clrYellow);
      ObjectSetInteger(0, tag, OBJPROP_ANCHOR, res.points[i].type > 0 ? ANCHOR_LOWER : ANCHOR_UPPER);
      ObjectSetInteger(0, tag, OBJPROP_ARROWCODE, res.points[i].type > 0 ? 234 : 251);
   }
}

//============================================================
// Draw river lines
//============================================================
void DrawRiver()
{
   int lastClosed = iBarShift(_Symbol, _Period, iTime(_Symbol,_Period,1), false);
   int startShift = MathMax(lastClosed - CANDLE_RANGE, 1);

   for(int s = startShift; s <= lastClosed; s++)
   {
      double top, bot, center, widthPips;
      RiverValues(s, top, bot, center, widthPips);
      if(!MathIsValidNumber(top))
         continue;

      datetime t = iTime(_Symbol, _Period, s);

      string tName = "OC_RIV_TOP_" + IntegerToString(s);
      string bName = "OC_RIV_BOT_" + IntegerToString(s);

      ObjectCreate(0, tName, OBJ_HLINE, 0, 0, 0, 0, top);
      ObjectSetInteger(0, tName, OBJPROP_COLOR, clrDodgerBlue);
      ObjectSetInteger(0, tName, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, tName, OBJPROP_WIDTH, 1);

      ObjectCreate(0, bName, OBJ_HLINE, 0, 0, 0, 0, bot);
      ObjectSetInteger(0, bName, OBJPROP_COLOR, clrOrange);
      ObjectSetInteger(0, bName, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, bName, OBJPROP_WIDTH, 1);
   }
}

//============================================================
// Update observers
//============================================================
void UpdateObservers()
{
   datetime closedBarTime = iTime(_Symbol, _Period, 1);
   if(closedBarTime <= 0)
      return;

   double rainbowCenter = m_dynoSlow.RainbowCenter(1);
   if(MathIsValidNumber(rainbowCenter) && rainbowCenter > 0.0)
      m_zigZag.FeedMA(closedBarTime, rainbowCenter);

   int boxCount = m_fractal.SmallBoxCount();
   if(boxCount < 2)
      return;

   FlatZone box0, box1;
   if(!m_fractal.GetSmallBox(0, box0) || !m_fractal.GetSmallBox(1, box1))
      return;

   if(box0.startTime == lastProcessedBoxStart)
      return;

   int olderShift = iBarShift(_Symbol, _Period, box1.startTime, false);
   int newerShift = iBarShift(_Symbol, _Period, box0.startTime, false);

   if(olderShift < 0 || newerShift < 1 || olderShift <= newerShift)
   {
      Print("ObservationCollector: Invalid ZigZag window");
      return;
   }

   m_zigZag.RunZigZag(olderShift, newerShift, closedBarTime);
   lastProcessedBoxStart = box0.startTime;
}

//============================================================
// Update H6
//============================================================
void UpdateH6()
{
   m_maH6.Update();
   m_dynoH6.UpdateNode();
}

//============================================================
// Cleanup all chart objects
//============================================================
void CleanupChartObjects()
{
   for(int i = ObjectsTotal() - 1; i >= 0; i--)
   {
      string name = ObjectName(i);
      if(StringFind(name, "OC_") == 0)
         ObjectDelete(0, name);
   }
}

//============================================================
// Expert initialization
//============================================================
int OnInit()
{
   g.Init(true);

   if(!m_maFast.Init(FAST_PERIOD, FAST_PERIOD, PERIOD_H1))
   {
      Print("Failed to init H1 fast MA");
      return INIT_FAILED;
   }

   if(!m_maSlow.Init(SLOW_PERIOD, SLOW_PERIOD, PERIOD_H1))
   {
      Print("Failed to init H1 slow MA");
      return INIT_FAILED;
   }

   if(!m_maH6.Init(H6_FAST, H6_SLOW, PERIOD_H6))
   {
      Print("Failed to init H6 MA");
      return INIT_FAILED;
   }

   if(!m_stc.Init())
   {
      Print("Failed to init structure");
      return INIT_FAILED;
   }

   m_fractal.Set(m_stc, m_maSlow);
   m_dynoSlow.Set(m_maSlow, g);
   m_dynoH6.Set(m_maH6, g);

   m_zigZag.Configure(_Symbol, _Period, 4, 80, 3, 0, 2, 5);

   lastBarTime           = 0;
   lastProcessedBoxStart = 0;
   lastH6BarTime         = 0;

   Print("ObservationCollector v2.00 initialized for ", _Symbol, " ", EnumToString(_Period));
   g.Log("ObservationCollector initialized");

   return INIT_SUCCEEDED;
}

//============================================================
// Expert deinitialization
//============================================================
void OnDeinit(const int reason)
{
   g.Log("ObservationCollector stopped. Reason = " + IntegerToString(reason));
}

//============================================================
// On tick handler
//============================================================
void OnTick()
{
   datetime currentBar = iTime(_Symbol, _Period, 0);
   if(currentBar == 0 || currentBar == lastBarTime)
      return;
   lastBarTime = currentBar;

   // H1 MAs
   m_maFast.Update();
   m_maSlow.Update();

   // H6
   UpdateH6();

   // Structure
   m_stc.Update(300);
   m_fractal.Build();

   // Observers
   UpdateObservers();

   // 3-box analysis
   FlatZone three[3];
   int threeCount = ExtractThreeBoxes(three);
   if(ArraySize(three) < threeCount)
      threeCount = 0;

   // JSON
   string json = BuildJsonPacket(three, threeCount);

   // Write + Send
   WriteAndSend(json);

   // Poll
   PollResponses_();

   // Draw on chart
   CleanupChartObjects();
   for(int i = 0; i < threeCount; i++)
      DrawBox(three[i], i);
   DrawZigZagPoints();
   DrawRiver();
}

