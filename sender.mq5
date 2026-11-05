#import "egg.dll"
int SendLatestJson();
#import


#import "egg.dll"
int PollResponses(string clientId, uchar &output[], int outputCapacity);
#import


#include <JAson.mqh>
CJAVal json;

#property copyright "forex-decision-skill (MIT)"
#property strict


//+------------------------------------------------------------------+
//| MT5 JSON Builder                                                 |
//+------------------------------------------------------------------+

datetime lastBarTime = 0;

// Convert timeframe enum to plain text for the Gateway
string GetTimeframe()
{
   string tf = EnumToString(_Period);
   StringReplace(tf, "PERIOD_", "");
   return tf;
}

// Build JSON with five closed candles plus a cover letter
string BuildCandleJson()
{
   MqlRates rates[];

   // Copy five closed candles; oldest first
   int copied = CopyRates(_Symbol, _Period, 1, 5, rates);

   if(copied != 5)
   {
      Print("Could not copy candles. Error: ", GetLastError());
      return "";
   }

   string symbol = _Symbol;
   string timeframe = GetTimeframe();

   string a_json = "{";

   a_json += "\"cover_letter\":\"From MT5 to AI\",";
   a_json += "\"symbol\":\"" + symbol + "\",";
   a_json += "\"timeframe\":\"" + timeframe + "\",";
   a_json += "\"candles\":[";

   for(int i = 4; i >= 0; i--)
   {
      string timeStr = TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES);

      if(i != 4)
         a_json += ",";

      a_json += "{";
      a_json += "\"time\":\"" + timeStr + "\",";
      a_json += "\"open\":" + DoubleToString(rates[i].open, _Digits) + ",";
      a_json += "\"high\":" + DoubleToString(rates[i].high, _Digits) + ",";
      a_json += "\"low\":" + DoubleToString(rates[i].low, _Digits) + ",";
      a_json += "\"close\":" + DoubleToString(rates[i].close, _Digits);
      a_json += "}";
   }

   a_json += "]}";

   return a_json;
}





uchar response[4096];




//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   lastBarTime = iTime(_Symbol, _Period, 0);

   Print("MT5 JSON Builder started.");
   Print("Symbol: ", _Symbol);
   Print("Timeframe: ", GetTimeframe());
   

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Tick event                                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime currentBarTime = iTime(_Symbol, _Period, 0);

   if(currentBarTime == 0 || currentBarTime == lastBarTime)
      return;

   lastBarTime = currentBarTime;

   string a_json = BuildCandleJson();

   if(a_json == "")
      return;

   SaveSendFile(a_json);
   ReadPoling();

}

void SaveSendFile(string w)

{


   int fileH = FileOpen("LLM-LQ/mt5_feed.json",
                       FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE);
   
   if(fileH != INVALID_HANDLE)
   {
      FileWriteString(fileH, w);
      FileClose(fileH);
      
      SendLatestJson();
   
   }
   else
   {
      Print("FileOpen failed. Error: ", GetLastError());
   }
   
}

void ReadPoling()
{
    int bytesRead = PollResponses(
        "mt5_terminal_01",
        response,
        ArraySize(response)
    );

    if (bytesRead <= 0)
        return;

    string jsonResponse = CharArrayToString(
        response,
        0,
        bytesRead,
        CP_UTF8
    );

    if (!json.Deserialize(jsonResponse, CP_UTF8))
        return;

    if (json["success"].ToBool() == false)
        return;

    int count = (int)json["count"].ToInt();

    if (count <= 0)
        return;

    CJAVal *responses = json.FindKey("responses");

    if (CheckPointer(responses) == POINTER_INVALID)
        return;

    for (int i = 0; i < responses.Size(); i++)
    {
        Print("Thinker response: ", responses[i].Serialize());
    }
}
