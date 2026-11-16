#ifndef __MT5_GATEWAY_MQH__
#define __MT5_GATEWAY_MQH__


#define GATEWAY_MAX_STEPS          120
#define GATEWAY_MAX_SEND_ATTEMPTS  5
#define GATEWAY_MAX_POLL_ATTEMPTS  60
#define GATEWAY_MAX_ACK_ATTEMPTS   5
#define GATEWAY_SLEEP_SECONDS      1

#import "egg.dll"
   int SendLatestJson();
   int PollResponses(string pathParameter, uchar &output[], int outputCapacity);
#import


#define GATEWAY_FEED_FILE     "LLM-LQ/mt5_feed.json"
#define GATEWAY_REQUEST_FILE  "LLM-LQ/Gateway/temp/current_request.json"
#define GATEWAY_SEQUENCE_FILE "LLM-LQ/Gateway/temp/request_sequence.txt"
#define GATEWAY_STATE_FILE    "LLM-LQ/Gateway/temp/current_state.txt"
#define GATEWAY_RESPONSE_FILE "LLM-LQ/Gateway/temp/current_response.json"
#define GATEWAY_RECEIVED_DIR  "LLM-LQ/Gateway/received"
#define GATEWAY_COMMANDS_FILE  "LLM-LQ/Gateway/commands/commands.json"


#include <JAson.mqh>


uchar response[16384];


string g_gatewayClientId = "";
string g_gatewayRequestId = "";
string g_gatewayLastRequestId = "";


enum GatewayState
{
   STATE_IDLE = 0,
   STATE_CREATED,
   STATE_SENDING,
   STATE_SENT,
   STATE_PROCESSING,
   STATE_RESPONSE_RECEIVED,
   STATE_ACK_SENDING,
   STATE_ACKNOWLEDGED,
   STATE_ERROR
};

enum GatewayEvent
{
   EVENT_NONE = 0,
   EVENT_START,
   EVENT_REQUEST_READY,
   EVENT_SEND_OK,
   EVENT_SEND_FAILED,
   EVENT_POLL_PROCESSING,
   EVENT_RESPONSE_COMPLETED,
   EVENT_RESPONSE_FAILED,
   EVENT_NETWORK_ERROR,
   EVENT_ACK_READY,
   EVENT_ACK_OK,
   EVENT_ACK_FAILED,
   EVENT_CLEANUP_OK,
   EVENT_CLEANUP_FAILED
};

class CMT5Gateway
{
private:

string GatewayStateToText(const GatewayState state)
{
   switch(state)
   {
      case STATE_IDLE:             return "IDLE";
      case STATE_CREATED:          return "CREATED";
      case STATE_SENDING:          return "SENDING";
      case STATE_SENT:             return "SENT";
      case STATE_PROCESSING:       return "PROCESSING";
      case STATE_RESPONSE_RECEIVED:return "RESPONSE_RECEIVED";
      case STATE_ACK_SENDING:      return "ACK_SENDING";
      case STATE_ACKNOWLEDGED:     return "ACKNOWLEDGED";
      case STATE_ERROR:            return "ERROR";
   }

   return "ERROR";
}

bool GatewayTextToState(   const string text,   GatewayState &state )
{
   if(text == "IDLE")              state = STATE_IDLE;
   else if(text == "CREATED")      state = STATE_CREATED;
   else if(text == "SENDING")      state = STATE_SENDING;
   else if(text == "SENT")         state = STATE_SENT;
   else if(text == "PROCESSING")   state = STATE_PROCESSING;
   else if(text == "RESPONSE_RECEIVED") state = STATE_RESPONSE_RECEIVED;
   else if(text == "ACK_SENDING")  state = STATE_ACK_SENDING;
   else if(text == "ACKNOWLEDGED") state = STATE_ACKNOWLEDGED;
   else if(text == "ERROR")        state = STATE_ERROR;
   else return false;

   return true;
}

bool GatewayTransition(   const GatewayState currentState,   const GatewayEvent event,   GatewayState &nextState )
{
   nextState = currentState;

   switch(currentState)
   {
      case STATE_IDLE:
         if(event == EVENT_START)
            nextState = STATE_CREATED;
         else
            return false;
         break;

      case STATE_CREATED:
         if(event == EVENT_REQUEST_READY)
            nextState = STATE_SENDING;
         else
            return false;
         break;

      case STATE_SENDING:
         if(event == EVENT_SEND_OK)
            nextState = STATE_SENT;
         else if(event == EVENT_SEND_FAILED ||
                 event == EVENT_NETWORK_ERROR)
            nextState = STATE_SENDING;
         else
            return false;
         break;

      case STATE_SENT:
         if(event == EVENT_POLL_PROCESSING)
            nextState = STATE_PROCESSING;
         else if(event == EVENT_RESPONSE_COMPLETED ||
                 event == EVENT_RESPONSE_FAILED)
            nextState = STATE_RESPONSE_RECEIVED;
         else if(event == EVENT_NETWORK_ERROR)
            nextState = STATE_SENT;
         else
            return false;
         break;

      case STATE_PROCESSING:
         if(event == EVENT_POLL_PROCESSING ||
            event == EVENT_NETWORK_ERROR)
            nextState = STATE_PROCESSING;
         else if(event == EVENT_RESPONSE_COMPLETED ||
                 event == EVENT_RESPONSE_FAILED)
            nextState = STATE_RESPONSE_RECEIVED;
         else
            return false;
         break;

      case STATE_RESPONSE_RECEIVED:
         if(event == EVENT_ACK_READY)
            nextState = STATE_ACK_SENDING;
         else
            return false;
         break;

      case STATE_ACK_SENDING:
         if(event == EVENT_ACK_OK)
            nextState = STATE_ACKNOWLEDGED;
         else if(event == EVENT_ACK_FAILED ||
                 event == EVENT_NETWORK_ERROR)
            nextState = STATE_ACK_SENDING;
         else
            return false;
         break;

      case STATE_ACKNOWLEDGED:
         if(event == EVENT_CLEANUP_OK)
            nextState = STATE_IDLE;
         else if(event == EVENT_CLEANUP_FAILED)
            nextState = STATE_ACKNOWLEDGED;
         else
            return false;
         break;

      case STATE_ERROR:
         return false;
   }

   return true;
}

bool GatewayTransitionAndSave(   const GatewayState currentState,   const GatewayEvent event,   GatewayState &nextState )
{
   GatewayState calculatedState;

   if(!GatewayTransition(
      currentState,
      event,
      calculatedState
   ))
   {
      Print("[GATEWAY] Invalid transition. state=",
            GatewayStateToText(currentState),
            " event=", (int)event);
      return false;
   }

   // وضعیت جدید باید پیش از اجرای عملیات بعدی پایدار شود.
   if(!GatewaySaveState(GatewayStateToText(calculatedState)))
   {
      Print("[GATEWAY] Failed to persist state: ",
            GatewayStateToText(calculatedState));
      return false;
   }

   nextState = calculatedState;

   Print("[GATEWAY] State transition: ",
         GatewayStateToText(currentState),
         " -> ",
         GatewayStateToText(nextState));

   return true;
}

string GatewayJsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");

   return value;
}


string GatewayUtcNow()
{
   MqlDateTime t;
   TimeToStruct(TimeGMT(), t);

   return StringFormat(
      "%04d-%02d-%02dT%02d:%02d:%02dZ",
      t.year, t.mon, t.day,
      t.hour, t.min, t.sec
   );
}

bool GatewaySaveState(const string state)
{
   int h = FileOpen(
      GATEWAY_STATE_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI
   );

   if(h == INVALID_HANDLE)
      return false;

   FileWriteString(h, state);
   FileClose(h);

   return true;
}

bool GatewayLoadState(string &state)
{
   state = "";

   if(!FileIsExist(GATEWAY_STATE_FILE, FILE_COMMON))
      return false;

   int h = FileOpen(
      GATEWAY_STATE_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI
   );

   if(h == INVALID_HANDLE)
      return false;

   state = FileReadString(h);
   FileClose(h);

   return (state != "");
}

bool GatewayLoadState(GatewayState &state)
{
   // نبودن فایل وضعیت یعنی شروع یک چرخه جدید.
   if(!FileIsExist(GATEWAY_STATE_FILE, FILE_COMMON))
   {
      state = STATE_IDLE;
      return true;
   }

   string savedState;

   if(!GatewayLoadState(savedState))
      return false;

   if(!GatewayTextToState(savedState, state))
   {
      Print("[GATEWAY] Invalid persisted state: ", savedState);
      return false;
   }

   return true;
}

bool GatewayRecoverState(GatewayState &state)
{

   // در حالت ACKNOWLEDGED فقط پاک‌سازی باقی مانده است.
   if(state == STATE_ACKNOWLEDGED)
      return true;


   bool hasRequest =
      FileIsExist(GATEWAY_REQUEST_FILE, FILE_COMMON);

   bool hasResponse =
      FileIsExist(GATEWAY_RESPONSE_FILE, FILE_COMMON);

   // شناسه درخواست فعال را از فایل بازیابی کن.
   if(hasRequest)
   {
      if(!GatewayLoadPendingRequest(
         g_gatewayClientId,
         g_gatewayRequestId
      ))
      {
         Print("[GATEWAY] Recovery failed: invalid request file.");
         return false;
      }
   }



   if(state == STATE_ERROR)
   {
      Print("[GATEWAY] Recovery stopped: persisted state is ERROR.");
      return false;
   }

   // پاسخ بدون درخواست متناظر قابل اعتماد نیست.
   if(hasResponse && !hasRequest)
   {
      Print("[GATEWAY] Recovery failed: response exists without request.");
      return false;
   }

   // هر پاسخ ذخیره‌شده باید پاسخ نهایی و متعلق به همین درخواست باشد.
   if(hasResponse)
   {
      if(!GatewayValidateSavedResponse(
         g_gatewayClientId,
         g_gatewayRequestId
      ))
      {
         Print("[GATEWAY] Recovery failed: saved response is invalid.");
         return false;
      }

      
      if(!GatewayCopySavedResponseToReceived(g_gatewayRequestId))
      {
         Print("[GATEWAY] Recovery failed: cannot persist received response.");
         return false;
      }

      // پاسخ نهایی ذخیره شده؛ دیگر نباید درخواست را ارسال یا Poll کنیم.
      if(state != STATE_RESPONSE_RECEIVED &&
         state != STATE_ACK_SENDING)
      {
         if(!GatewaySaveState("RESPONSE_RECEIVED"))
            return false;

         state = STATE_RESPONSE_RECEIVED;

         Print("[GATEWAY] Recovery promoted state to RESPONSE_RECEIVED.");
      }

      return true;
   }

   // وضعیت‌های فعال باید فایل درخواست داشته باشند.
   if(state == STATE_CREATED ||
      state == STATE_SENDING ||
      state == STATE_SENT ||
      state == STATE_PROCESSING ||
      state == STATE_RESPONSE_RECEIVED ||
      state == STATE_ACK_SENDING)
   {
      if(!hasRequest)
      {
         Print("[GATEWAY] Recovery failed: request file is missing.");
         return false;
      }
   }

   // این دو وضعیت حتماً به پاسخ نهایی ذخیره‌شده نیاز دارند.
   if(state == STATE_RESPONSE_RECEIVED ||
      state == STATE_ACK_SENDING)
   {
      if(!hasResponse)
      {
         Print("[GATEWAY] Recovery failed: response file is missing.");
         return false;
      }
   }

   // اگر state گم شده یا IDLE است ولی درخواست وجود دارد،
   // همان درخواست قبلی باید دوباره ارسال شود.
   if(state == STATE_IDLE && hasRequest)
   {
      if(!GatewaySaveState("SENDING"))
         return false;

      state = STATE_SENDING;

      Print("[GATEWAY] Recovery promoted IDLE to SENDING.");
   }

   return true;
}

string GatewayNextRequestId()
{
   long sequence = 0;

   if(FileIsExist(GATEWAY_SEQUENCE_FILE, FILE_COMMON))
   {
      int h = FileOpen(
         GATEWAY_SEQUENCE_FILE,
         FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI
      );

      if(h == INVALID_HANDLE)
         return "";

      string saved = FileReadString(h);
      FileClose(h);

      sequence = StringToInteger(saved);
   }

   sequence++;

   int h = FileOpen(
      GATEWAY_SEQUENCE_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI
   );

   if(h == INVALID_HANDLE)
      return "";

   FileWriteString(h, IntegerToString(sequence));
   FileClose(h);

   return g_gatewayClientId + "-" +
          StringFormat("%06d", sequence);
}

bool GatewayPrepareRequest(const string body)
{
   // درخواست حل‌نشده قبلی را بازیابی کن.
   if(FileIsExist(GATEWAY_REQUEST_FILE, FILE_COMMON))
   {
      if(!GatewayLoadPendingRequest(
         g_gatewayClientId,
         g_gatewayRequestId
      ))
         return false;

      Print("[GATEWAY] Existing request recovered: ",
            g_gatewayRequestId);

      return true;
   }

   // اعتبارسنجی اولیه JSON
   string payload = body;
   StringTrimLeft(payload);
   StringTrimRight(payload);

   int bodyLength = StringLen(payload);

   if(bodyLength < 2 ||
      StringSubstr(payload, 0, 1) != "{" ||
      StringSubstr(payload, bodyLength - 1, 1) != "}")
   {
      Print("[GATEWAY] Invalid JSON object body.");
      return false;
   }

   // ساخت شناسه جدید
   string requestId = GatewayNextRequestId();

   if(requestId == "")
      return false;

   string clientId = GatewayJsonEscape(g_gatewayClientId);
   string escapedRequestId = GatewayJsonEscape(requestId);

   // ساخت Envelope
   string envelope = "{";

   envelope += "\"protocol\":\"mt5-gateway\",";
   envelope += "\"version\":1,";
   envelope += "\"message_type\":\"INGEST\",";
   envelope += "\"client_id\":\"" + clientId + "\",";
   envelope += "\"request_id\":\"" + escapedRequestId + "\",";
   envelope += "\"created_at\":\"" + GatewayUtcNow() + "\",";
   envelope += "\"payload\":" + payload;

   envelope += "}";

   // ذخیره پایدار پیش از ارسال
   int h = FileOpen(
      GATEWAY_REQUEST_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot persist request. error=", GetLastError());
      return false;
   }

   uint written = FileWriteString(h, envelope);
   FileClose(h);

   if(written == 0)
   {
      Print("[GATEWAY] Request persistence failed.");
      return false;
   }

   g_gatewayRequestId = requestId;

   Print("[GATEWAY] Request persisted: ", requestId);

   return true;
}

int GatewaySendRequest()
{
   string clientId;
   string requestId;

   if(!GatewayLoadPendingRequest(clientId, requestId))
      return -300;

   // خواندن همان Envelope ذخیره‌شده
   int requestHandle = FileOpen(
      GATEWAY_REQUEST_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(requestHandle == INVALID_HANDLE)
      return -301;

   string envelope = FileReadString(requestHandle);
   FileClose(requestHandle);

   if(envelope == "")
      return -302;

   // تحویل Envelope به فایل مورد انتظار DLL
   int feedHandle = FileOpen(
      GATEWAY_FEED_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(feedHandle == INVALID_HANDLE)
      return -303;

   uint written = FileWriteString(feedHandle, envelope);
   FileClose(feedHandle);

   if(written == 0)
      return -304;

   // ارسال HTTP توسط DLL
   int result = SendLatestJson();

   Print("[GATEWAY] SendLatestJson result: ", result);

   return result;
}

bool GatewayHttpGet(   const string pathParameter,   string &responseText )
{
   responseText = "";

   ArrayInitialize(response, 0);

   int result = PollResponses(
      pathParameter,
      response,
      ArraySize(response)
   );

   if(result <= 0)
   {
      Print("[GATEWAY] GET failed. result=", result);
      return false;
   }

   responseText = CharArrayToString(
      response,
      0,
      WHOLE_ARRAY,
      CP_UTF8
   );

   if(StringLen(responseText) == 0)
   {
      Print("[GATEWAY] GET returned empty response. result=", result);
      return false;
   }

   return true;
}

bool GatewayPoll(   const string clientId,   const string requestId,   string &responseText )
{
   string path =
      "/gateway/mt5/responses"
      "?client_id=" + clientId +
      "&request_id=" + requestId;

   return GatewayHttpGet(path, responseText);
}

bool GatewayParsePollResponse(   const string responseText,   const string expectedClientId,   const string expectedRequestId,   string &status,   string &responseId )
{
   status = "";
   responseId = "";

   CJAVal pollJson;

   if(!pollJson.Deserialize(responseText))
   {
      Print("[GATEWAY] Invalid Poll JSON.");
      return false;
   }

   string protocol = pollJson["protocol"].ToStr();
   int version = (int)pollJson["version"].ToInt();
   string messageType = pollJson["message_type"].ToStr();
   string clientId = pollJson["client_id"].ToStr();
   string requestId = pollJson["request_id"].ToStr();

   if(protocol != "mt5-gateway" ||
      version != 1 ||
      messageType != "POLL_RESULT")
   {
      Print("[GATEWAY] Invalid Poll protocol envelope.");
      return false;
   }

   if(clientId != expectedClientId ||
      requestId != expectedRequestId)
   {
      Print("[GATEWAY] Poll response identity mismatch.");
      return false;
   }

   status = pollJson["status"].ToStr();
   responseId = pollJson["response_id"].ToStr();

   if(status != "PROCESSING" &&
      status != "COMPLETED" &&
      status != "FAILED")
   {
      Print("[GATEWAY] Unexpected Poll status: ", status);
      return false;
   }

   if((status == "COMPLETED" || status == "FAILED") &&
      responseId == "")
   {
      Print("[GATEWAY] Final response has no response_id.");
      return false;
   }

   Print("[GATEWAY] Poll validated. status=", status,
         " response_id=", responseId);

   return true;
}

bool GatewaySaveResponse(const string responseText)
{
   int h = FileOpen(
      GATEWAY_RESPONSE_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot open response file. error=", GetLastError());
      return false;
   }

   uint written = FileWriteString(h, responseText);
   FileClose(h);

   if(written == 0)
   {
      Print("[GATEWAY] Failed to write response file.");
      return false;
   }

   Print("[GATEWAY] Response persisted.");
   return true;
}

bool GatewayCopySavedResponseToReceived(const string requestId)
{
   int source = FileOpen(
      GATEWAY_RESPONSE_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(source == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot read temporary response.");
      return false;
   }

   string responseText = FileReadString(source);
   FileClose(source);

   if(responseText == "")
      return false;

   //if(!FolderIsExist(GATEWAY_RECEIVED_DIR, FILE_COMMON))
   //{
   //   if(!FolderCreate(GATEWAY_RECEIVED_DIR, FILE_COMMON) &&
   //      !FolderIsExist(GATEWAY_RECEIVED_DIR, FILE_COMMON))
   //    {
   //      Print("[GATEWAY] Cannot create received directory.");
   //      return false;
   //   }
   //}

   string receivedFile =
      GATEWAY_RECEIVED_DIR + "/" + requestId + ".json";

   int target = FileOpen(
      receivedFile,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(target == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot create received file. error=",
            GetLastError());
      return false;
   }

   uint written = FileWriteString(target, responseText);
   FileClose(target);

   if(written == 0)
   {
      Print("[GATEWAY] Received response write failed.");
      return false;
   }

   Print("[GATEWAY] Response saved to received: ", receivedFile);
   return true;
}

bool GatewayPollAndPersist(   const string clientId,   const string requestId,   GatewayEvent &event)
{
   event = EVENT_NONE;

   string responseText;
   string status;
   string responseId;

   if(!GatewayPoll(clientId, requestId, responseText))
   {
      event = EVENT_NETWORK_ERROR;
      return true;
   }

   if(!GatewayParsePollResponse(
      responseText,
      clientId,
      requestId,
      status,
      responseId
   ))
   {
      event = EVENT_NETWORK_ERROR;
      return true;
   }

   if(status == "PROCESSING")
   {
      event = EVENT_POLL_PROCESSING;
      return true;
   }

   // پاسخ نهایی باید قبل از تغییر وضعیت ذخیره شود.
   if(!GatewaySaveResponse(responseText))
      return false;

   if(!GatewayCopySavedResponseToReceived(requestId))
      return false;

   if(status == "COMPLETED")
      event = EVENT_RESPONSE_COMPLETED;
   else if(status == "FAILED")
      event = EVENT_RESPONSE_FAILED;

   return true;
}

bool GatewayLoadPendingRequest(   string &clientId,   string &requestId )
{
   clientId = "";
   requestId = "";

   if(!FileIsExist(GATEWAY_REQUEST_FILE, FILE_COMMON))
   {
      Print("[GATEWAY] No pending request file.");
      return false;
   }

   int h = FileOpen(
      GATEWAY_REQUEST_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot open pending request. error=", GetLastError());
      return false;
   }

   string envelope = FileReadString(h);
   FileClose(h);

   if(StringLen(envelope) == 0)
   {
      Print("[GATEWAY] Pending request file is empty.");
      return false;
   }

   CJAVal requestJson;

   if(!requestJson.Deserialize(envelope))
   {
      Print("[GATEWAY] Pending request JSON is invalid.");
      return false;
   }

   string protocol = requestJson["protocol"].ToStr();
   int version = (int)requestJson["version"].ToInt();
   string messageType = requestJson["message_type"].ToStr();

   clientId = requestJson["client_id"].ToStr();
   requestId = requestJson["request_id"].ToStr();

   if(protocol != "mt5-gateway" ||
      version != 1 ||
      messageType != "INGEST")
   {
      Print("[GATEWAY] Invalid pending request envelope.");
      clientId = "";
      requestId = "";
      return false;
   }

   if(clientId == "" ||
      requestId == "" ||
      clientId != InpGatewayClientId)
   {
      Print("[GATEWAY] Pending request identity is invalid.");
      clientId = "";
      requestId = "";
      return false;
   }

   Print("[GATEWAY] Pending request recovered. request_id=", requestId);

   return true;
}

bool GatewayValidateSavedResponse(   const string expectedClientId,   const string expectedRequestId )
{
   if(!FileIsExist(GATEWAY_RESPONSE_FILE, FILE_COMMON))
      return false;

   int h = FileOpen(
      GATEWAY_RESPONSE_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
   {
      Print("[GATEWAY] Cannot open saved response. error=", GetLastError());
      return false;
   }

   string responseText = FileReadString(h);
   FileClose(h);

   if(responseText == "")
      return false;

   string status;
   string responseId;

   if(!GatewayParsePollResponse(
      responseText,
      expectedClientId,
      expectedRequestId,
      status,
      responseId
   ))
      return false;

   if(status != "COMPLETED" && status != "FAILED")
   {
      Print("[GATEWAY] Saved response is not final. status=", status);
      return false;
   }

   Print("[GATEWAY] Saved final response validated. request_id=",
         expectedRequestId,
         " response_id=", responseId);

   return true;
}

bool GatewayGetSavedResponseId(   const string expectedClientId,   const string expectedRequestId,   string &responseId )
{
   responseId = "";

   if(!FileIsExist(GATEWAY_RESPONSE_FILE, FILE_COMMON))
      return false;

   int h = FileOpen(
      GATEWAY_RESPONSE_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
      return false;

   string responseText = FileReadString(h);
   FileClose(h);

   string status;

   if(!GatewayParsePollResponse(
      responseText,
      expectedClientId,
      expectedRequestId,
      status,
      responseId
   ))
      return false;

   if((status != "COMPLETED" && status != "FAILED") ||
      responseId == "")
   {
      responseId = "";
      return false;
   }

   return true;
}

bool GatewaySendAck()
{
   string responseId;

   if(!GatewayGetSavedResponseId(
      g_gatewayClientId,
      g_gatewayRequestId,
      responseId
   ))
   {
      Print("[GATEWAY] Cannot get response_id for ACK.");
      return false;
   }

   string path =
      "/gateway/mt5/responses"
      "?client_id=" + g_gatewayClientId +
      "&request_id=" + g_gatewayRequestId +
      "&action=ACK"
      "&response_id=" + responseId;

   string responseText;

   if(!GatewayHttpGet(path, responseText))
      return false;

   CJAVal ackJson;

   if(!ackJson.Deserialize(responseText))
   {
      Print("[GATEWAY] Invalid ACK response JSON.");
      return false;
   }

   if(ackJson["protocol"].ToStr() != "mt5-gateway" ||
      (int)ackJson["version"].ToInt() != 1 ||
      ackJson["message_type"].ToStr() != "ACK_RESULT" ||
      ackJson["client_id"].ToStr() != g_gatewayClientId ||
      ackJson["request_id"].ToStr() != g_gatewayRequestId ||
      ackJson["response_id"].ToStr() != responseId ||
      ackJson["status"].ToStr() != "ACKNOWLEDGED")
   {
      Print("[GATEWAY] ACK_RESULT validation failed.");
      return false;
   }

   Print("[GATEWAY] ACKNOWLEDGED. response_id=", responseId);
   return true;
}

bool GatewayCleanup()
{
   bool requestDeleted = true;
   bool responseDeleted = true;

   if(FileIsExist(GATEWAY_REQUEST_FILE, FILE_COMMON))
      requestDeleted = FileDelete(
         GATEWAY_REQUEST_FILE,
         FILE_COMMON
      );

   if(FileIsExist(GATEWAY_RESPONSE_FILE, FILE_COMMON))
      responseDeleted = FileDelete(
         GATEWAY_RESPONSE_FILE,
         FILE_COMMON
      );

   if(!requestDeleted || !responseDeleted)
   {
      Print("[GATEWAY] Cleanup failed. request=",
            requestDeleted,
            " response=", responseDeleted);
      return false;
   }

   g_gatewayLastRequestId = g_gatewayRequestId;
   g_gatewayRequestId = "";

   Print("[GATEWAY] Request and response files cleaned.");
   return true;
}

bool GatewayLoadCommands(CJAVal &root)
{
   if(!FileIsExist(GATEWAY_COMMANDS_FILE, FILE_COMMON))
   {
      Print("[COMMANDS] File not found: ", GATEWAY_COMMANDS_FILE);
      return false;
   }

   int h = FileOpen(
      GATEWAY_COMMANDS_FILE,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI
   );

   if(h == INVALID_HANDLE)
   {
      Print("[COMMANDS] Cannot open commands file. error=", GetLastError());
      return false;
   }

   string content = "";

   while(!FileIsEnding(h))
      content += FileReadString(h);

   FileClose(h);

   if(content == "")
   {
      Print("[COMMANDS] Commands file is empty.");
      return false;
   }

   if(!root.Deserialize(content))
   {
      Print("[COMMANDS] Invalid JSON.");
      return false;
   }

   if(root.m_type != jtOBJ ||
      root["commands"].m_type != jtARRAY)
   {
      Print("[COMMANDS] Expected an object with commands array.");
      return false;
   }

   int count = root["commands"].Size();

   for(int i = 0; i < count; i++)
   {
      string id = root["commands"][i]["id"].ToStr();
      string command = root["commands"][i]["command"].ToStr();
      string status = root["commands"][i]["status"].ToStr();

      if(id == "" || command == "")
      {
         Print("[COMMANDS] Invalid command entry at index ", i);
         return false;
      }

      if(status != "PENDING" && status != "COMPLETED")
      {
         Print("[COMMANDS] Invalid status. id=", id,
               " status=", status);
         return false;
      }

      for(int j = 0; j < i; j++)
      {
         if(root["commands"][j]["id"].ToStr() == id)
         {
            Print("[COMMANDS] Duplicate command id: ", id);
            return false;
         }
      }
   }

   Print("[COMMANDS] Loaded ", count, " commands.");
   return true;
}

bool GatewaySaveCommands(CJAVal &root)
{
   string content = root.Serialize();

   if(content == "")
      return false;

   int h = FileOpen(
      GATEWAY_COMMANDS_FILE,
      FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI
   );

   if(h == INVALID_HANDLE)
   {
      Print("[COMMANDS] Cannot write commands file. error=", GetLastError());
      return false;
   }

   uint written = FileWriteString(h, content);
   FileClose(h);

   if(written == 0)
   {
      Print("[COMMANDS] Failed to save commands file.");
      return false;
   }

   Print("[COMMANDS] Commands file saved.");
   return true;
}

bool GatewayReceivedCommandSucceeded( const string requestId,   const string expectedCommand )
{
   if(requestId == "")
      return false;

   string receivedFile =
      GATEWAY_RECEIVED_DIR + "/" + requestId + ".json";

   if(!FileIsExist(receivedFile, FILE_COMMON))
   {
      Print("[COMMANDS] Received response not found: ", receivedFile);
      return false;
   }

   int h = FileOpen(
      receivedFile,
      FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
   );

   if(h == INVALID_HANDLE)
      return false;

   string content = "";

   while(!FileIsEnding(h))
      content += FileReadString(h);

   FileClose(h);

   CJAVal result;

   if(content == "" || !result.Deserialize(content))
   {
      Print("[COMMANDS] Invalid received response JSON.");
      return false;
   }

   if(result["protocol"].ToStr() != "mt5-gateway" ||
      (int)result["version"].ToInt() != 1 ||
      result["message_type"].ToStr() != "POLL_RESULT" ||
      result["client_id"].ToStr() != g_gatewayClientId ||
      result["request_id"].ToStr() != requestId ||
      result["status"].ToStr() != "COMPLETED")
   {
      Print("[COMMANDS] Response identity or status validation failed.");
      return false;
   }

   if(result["payload"]["operations"].m_type != jtARRAY ||
      result["payload"]["operations"].Size() != 1)
   {
      Print("[COMMANDS] Expected exactly one operation result.");
      return false;
   }

   if(result["payload"]["operations"][0]["command"].ToStr()
      != expectedCommand)
   {
      Print("[COMMANDS] Operation command mismatch.");
      return false;
   }

   if(result["payload"]["operations"][0]["success"].m_type != jtBOOL ||
      !result["payload"]["operations"][0]["success"].ToBool())
   {
      Print("[COMMANDS] Operation failed: ", expectedCommand);
      return false;
   }

   Print("[COMMANDS] Operation succeeded: ", expectedCommand);
   return true;
}

bool GatewayRunCommands()
{
   if(!FileIsExist(GATEWAY_COMMANDS_FILE, FILE_COMMON))
   {
      Print("[COMMANDS] No commands file. Skipping.");
      return true;
   }

   CJAVal root;

   if(!GatewayLoadCommands(root))
   {
      Print("[COMMANDS] Cannot load commands.");
      return false;
   }

   int count = root["commands"].Size();

   for(int i = 0; i < count; i++)
   {
      string commandId =
         root["commands"][i]["id"].ToStr();

      string command =
         root["commands"][i]["command"].ToStr();

      string status =
         root["commands"][i]["status"].ToStr();

      if(status == "COMPLETED")
         continue;

      if(status != "PENDING")
         return false;

      string body = "";

      if(command == "LIST-TABL")
      {
         body =
            "{"
            "\"command\":\"INIT\","
            "\"operations\":["
               "{"
                  "\"command\":\"LIST-TABL\""
               "}"
            "]"
            "}";
      }
      else
      {
         Print("[COMMANDS] Unsupported command: ",
               command,
               " id=", commandId);
         return false;
      }

      Print("[COMMANDS] Executing command: ",
            command,
            " id=", commandId);

      if(!GatewayExecuteRequest(body))
      {
         Print("[COMMANDS] Gateway execution failed. id=",
               commandId);
         return false;
      }

      string requestId = g_gatewayLastRequestId;

      if(!GatewayReceivedCommandSucceeded(
         requestId,
         command
      ))
      {
         Print("[COMMANDS] Command operation failed. id=",
               commandId);
         return false;
      }

      root["commands"][i]["status"] = "COMPLETED";

      if(!GatewaySaveCommands(root))
      {
         Print("[COMMANDS] Cannot save command status. id=",
               commandId);
         return false;
      }

      Print("[COMMANDS] Command completed: ",
            commandId);
   }

   Print("[COMMANDS] All pending commands processed.");
   return true;
}

bool GatewayExecuteAction(   const GatewayState previousState,   const GatewayState nextState,   const GatewayEvent event,   GatewayEvent &actionEvent )
{
   actionEvent = EVENT_NONE;

   // ارسال درخواست
   if(nextState == STATE_SENDING)
   {
      int result = GatewaySendRequest();

      if(result >= 200 && result < 300)
         actionEvent = EVENT_SEND_OK;
      else
         actionEvent = EVENT_SEND_FAILED;

      return true;
   }

   // Poll پاسخ
   if(nextState == STATE_SENT ||
      nextState == STATE_PROCESSING)
   {
      return GatewayPollAndPersist(
         g_gatewayClientId,
         g_gatewayRequestId,
         actionEvent
      );
   }

   // ارسال ACK
   if(nextState == STATE_ACK_SENDING)
   {
      if(GatewaySendAck())
         actionEvent = EVENT_ACK_OK;
      else
         actionEvent = EVENT_ACK_FAILED;

      return true;
   }

   // پاک‌سازی پس از تأیید ACK
   if(previousState == STATE_ACKNOWLEDGED &&
      nextState == STATE_ACKNOWLEDGED &&
      event == EVENT_NONE)
   {
      if(GatewayCleanup())
         actionEvent = EVENT_CLEANUP_OK;
      else
         actionEvent = EVENT_CLEANUP_FAILED;

      return true;
   }

   Print("[GATEWAY] No action defined. previous=",
         GatewayStateToText(previousState),
         " next=", GatewayStateToText(nextState),
         " event=", (int)event);

   return false;
}

bool GatewayExecuteRequest(   const string body,   const bool allowNewRequest = true )
{
   GatewayState state;

   // بازیابی وضعیت پایدار
   if(!GatewayLoadState(state))
   {
      Print("[GATEWAY] Cannot load persisted state.");
      return false;
   }

   if(!GatewayRecoverState(state))
   {
      Print("[GATEWAY] State recovery failed.");
      return false;
   }

   int sendAttempts = 0;
   int pollAttempts = 0;
   int ackAttempts  = 0;

   for(int step = 0; step < GATEWAY_MAX_STEPS; step++)
   {
      GatewayState nextState;
      GatewayEvent event = EVENT_NONE;
      GatewayEvent actionEvent = EVENT_NONE;

      // --------------------------------------------------
      // IDLE: شروع درخواست جدید
      // --------------------------------------------------
      if(state == STATE_IDLE)
      {
         if(!allowNewRequest)
            return true;

         if(!GatewayTransitionAndSave(
            state,
            EVENT_START,
            nextState
         ))
            return false;

         state = nextState;
         continue;
      }

      // --------------------------------------------------
      // CREATED: ساخت و ذخیره پایدار درخواست
      // --------------------------------------------------
      if(state == STATE_CREATED)
      {
         if(!GatewayPrepareRequest(body))
         {
            Print("[GATEWAY] Request preparation failed.");
            return false;
         }

         if(!GatewayTransitionAndSave(
            state,
            EVENT_REQUEST_READY,
            nextState
         ))
            return false;

         state = nextState;
         continue;
      }

      // --------------------------------------------------
      // SENDING: ارسال درخواست
      // --------------------------------------------------
      if(state == STATE_SENDING)
      {
         if(sendAttempts >= GATEWAY_MAX_SEND_ATTEMPTS)
         {
            Print("[GATEWAY] Maximum send attempts reached.");
            return false;
         }

         sendAttempts++;

         if(!GatewayExecuteAction(
            state,
            state,
            EVENT_NONE,
            actionEvent
         ))
            return false;

         if(!GatewayTransitionAndSave(
            state,
            actionEvent,
            nextState
         ))
            return false;

         state = nextState;

         if(actionEvent == EVENT_SEND_FAILED)
            Sleep(GATEWAY_SLEEP_SECONDS * 1000);

         continue;
      }

      // --------------------------------------------------
      // SENT / PROCESSING: دریافت وضعیت پاسخ
      // --------------------------------------------------
      if(state == STATE_SENT ||
         state == STATE_PROCESSING)
      {
         if(pollAttempts >= GATEWAY_MAX_POLL_ATTEMPTS)
         {
            Print("[GATEWAY] Maximum poll attempts reached.");
            return false;
         }

         pollAttempts++;

         if(!GatewayExecuteAction(
            state,
            state,
            EVENT_NONE,
            actionEvent
         ))
         {
            Print("[GATEWAY] Poll action failed.");
            return false;
         }

         if(!GatewayTransitionAndSave(
            state,
            actionEvent,
            nextState
         ))
            return false;

         state = nextState;

         if(state == STATE_SENT ||
            state == STATE_PROCESSING)
         {
            Sleep(GATEWAY_SLEEP_SECONDS * 1000);
         }

         continue;
      }

      // --------------------------------------------------
      // RESPONSE_RECEIVED: آماده‌سازی ACK
      // --------------------------------------------------
      if(state == STATE_RESPONSE_RECEIVED)
      {
         if(!GatewayTransitionAndSave(
            state,
            EVENT_ACK_READY,
            nextState
         ))
            return false;

         state = nextState;
         continue;
      }

      // --------------------------------------------------
      // ACK_SENDING: تأیید دریافت پاسخ در سرور
      // --------------------------------------------------
      if(state == STATE_ACK_SENDING)
      {
         if(ackAttempts >= GATEWAY_MAX_ACK_ATTEMPTS)
         {
            Print("[GATEWAY] Maximum ACK attempts reached.");
            return false;
         }

         ackAttempts++;

         if(!GatewayExecuteAction(
            state,
            state,
            EVENT_NONE,
            actionEvent
         ))
            return false;

         if(!GatewayTransitionAndSave(
            state,
            actionEvent,
            nextState
         ))
            return false;

         state = nextState;

         if(actionEvent == EVENT_ACK_FAILED)
            Sleep(GATEWAY_SLEEP_SECONDS * 1000);

         continue;
      }

      // --------------------------------------------------
      // ACKNOWLEDGED: پاک‌سازی فایل‌های درخواست و پاسخ
      // --------------------------------------------------
      if(state == STATE_ACKNOWLEDGED)
      {
         if(!GatewayExecuteAction(
            state,
            state,
            EVENT_NONE,
            actionEvent
         ))
            return false;

         if(!GatewayTransitionAndSave(
            state,
            actionEvent,
            nextState
         ))
            return false;

         if(nextState == STATE_IDLE)
         {
            Print("[GATEWAY] Request cycle completed.");
            return true;
         }

         state = nextState;

         if(actionEvent == EVENT_CLEANUP_FAILED)
            Sleep(GATEWAY_SLEEP_SECONDS * 1000);

         continue;
      }

      // --------------------------------------------------
      // ERROR یا وضعیت ناشناخته
      // --------------------------------------------------
      Print("[GATEWAY] Execution stopped. state=",
            GatewayStateToText(state));

      return false;
   }

   Print("[GATEWAY] Maximum execution steps reached.");
   return false;
}

bool GatewayResumePendingRequest()
{
   return GatewayExecuteRequest("", false);
}


public:

   bool Initialize(const string clientId)
   {
      if(clientId == "")
         return false;

      g_gatewayClientId = clientId;
      return true;
   }

   bool ResumePendingRequest()
   {
      return GatewayResumePendingRequest();
   }

   bool RunCommands()
   {
      return GatewayRunCommands();
   }

   bool ExecuteRequest(const string body)
   {
      return GatewayExecuteRequest(body);
   }

};
#endif // __MT5_GATEWAY_MQH__
