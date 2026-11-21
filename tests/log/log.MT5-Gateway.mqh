#ifndef __MT5_GATEWAY_MQH__
#define __MT5_GATEWAY_MQH__


#define GATEWAY_MAX_STEPS          120
#define GATEWAY_MAX_SEND_ATTEMPTS  5
#define GATEWAY_MAX_POLL_ATTEMPTS  60
#define GATEWAY_MAX_ACK_ATTEMPTS   5
#define GATEWAY_SLEEP_SECONDS      1

#import "egg.dll"
   int SendLatestJson(string filePath);
   int PollResponses(string pathParameter, uchar &output[], int outputCapacity);
#import


#include <JAson.mqh>


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

   string m_clientId;
   string m_requestId;
   string m_lastRequestId;
   uchar  m_response[262144];

   string m_folderName;
   string m_rootDir;
   string m_feedFile;
   string m_tempDir;
   string m_receivedDir;
   string m_commandsDir;
   string m_controlDir;


   string m_requestFile;
   string m_stateFile;
   string m_responseFile;
   string m_commandsFile;
   string m_controlFile;








   bool GatewayFolderExists(const string folder)
   {
      ResetLastError();
   
      bool is_file = FileIsExist(folder, FILE_COMMON);
      int error_code = GetLastError();
   
      return (!is_file && error_code == 5018);
   }







   bool GatewayEnsureFolder(const string path)
   {

      if(!GatewayFolderExists(path))
      {
         if(!FolderCreate(path, FILE_COMMON) &&
            !GatewayFolderExists(path))
         {
            Print("[GATEWAY] Cannot create received directory.");
            return false;
         }
         
         return true;
      }

      return true;

   }











   
   
   bool GatewayCreateInitialFile( const string path, const string content )
   {
      if(FileIsExist(path, FILE_COMMON))
         return true;
   
      int h = FileOpen(
         path,
         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI
      );
   
      if(h == INVALID_HANDLE)
         return false;
   
      FileWriteString(h, content);
      FileClose(h);
   
      return true;
   }


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
         m_stateFile,
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
   
      if(!FileIsExist(m_stateFile, FILE_COMMON))
         return false;
   
      int h = FileOpen(
         m_stateFile,
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
      if(!FileIsExist(m_stateFile, FILE_COMMON))
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
         FileIsExist(m_requestFile, FILE_COMMON);
   
      bool hasResponse =
         FileIsExist(m_responseFile, FILE_COMMON);
   
      // شناسه درخواست فعال را از فایل بازیابی کن.
      if(hasRequest)
      {
         if(!GatewayLoadPendingRequest(
            m_clientId,
            m_requestId
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
         Print("[GATEWAY] Recovery failed: m_response exists without request.");
         return false;
      }
   
      // هر پاسخ ذخیره‌شده باید پاسخ نهایی و متعلق به همین درخواست باشد.
      if(hasResponse)
      {
         if(!GatewayValidateSavedResponse(
            m_clientId,
            m_requestId
         ))
         {
            Print("[GATEWAY] Recovery failed: saved m_response is invalid.");
            return false;
         }
   
         
         if(!GatewayCopySavedResponseToReceived(m_requestId))
         {
            Print("[GATEWAY] Recovery failed: cannot persist received m_response.");
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
            Print("[GATEWAY] Recovery failed: m_response file is missing.");
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
      string randomPart = "";
   
      for(int i = 0; i < 8; i++)
         randomPart += StringFormat("%04X", MathRand());
   
      return m_clientId + "-" + randomPart;
   }
   
   bool GatewayPrepareRequest(const string body)
   {
      // درخواست حل‌نشده قبلی را بازیابی کن.
      if(FileIsExist(m_requestFile, FILE_COMMON))
      {
         if(!GatewayLoadPendingRequest(
            m_clientId,
            m_requestId
         ))
            return false;
   
         Print("[GATEWAY] Existing request recovered: ",
               m_requestId);
   
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
   
      string clientId = GatewayJsonEscape(m_clientId);
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
         m_requestFile,
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
   
      m_requestId = requestId;
   
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
         m_requestFile,
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
         m_feedFile,
         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
      );
   
      if(feedHandle == INVALID_HANDLE)
         return -303;
   
      uint written = FileWriteString(feedHandle, envelope);
      FileClose(feedHandle);
   
      if(written == 0)
         return -304;
   
      // ارسال HTTP توسط DLL
      int result = SendLatestJson(
         TerminalInfoString(TERMINAL_COMMONDATA_PATH) +
         "\\Files\\" +
         m_feedFile
      );
   
      Print("[GATEWAY] SendLatestJson result: ", result);
   
      return result;
   }
   
   bool GatewayHttpGet(   const string pathParameter,   string &responseText )
   {
      responseText = "";
   
      ArrayInitialize(m_response, 0);
   
      int result = PollResponses(
         pathParameter,
         m_response,
         ArraySize(m_response)
      );
   
      if(result <= 0)
      {
         Print("[GATEWAY] GET failed. result=", result);
         return false;
      }
   
      responseText = CharArrayToString(
         m_response,
         0,
         WHOLE_ARRAY,
         CP_UTF8
      );
   
      if(StringLen(responseText) == 0)
      {
         Print("[GATEWAY] GET returned empty m_response. result=", result);
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
         Print("[GATEWAY] Poll m_response identity mismatch.");
         return false;
      }
   
      status = pollJson["status"].ToStr();
      responseId = pollJson["response_id"].ToStr();
   
      if(status != "PROCESSING" &&
         status != "COMPLETED" &&
         status != "FAILED" &&
         status != "CANCELLED")
      {
         Print("[GATEWAY] Unexpected Poll status: ", status);
         return false;
      }
   
      if((status == "COMPLETED" ||
          status == "FAILED" ||
          status == "CANCELLED") &&
         responseId == "")
      {
         Print("[GATEWAY] Final m_response has no response_id.");
         return false;
      }
   
      Print("[GATEWAY] Poll validated. status=", status,
            " response_id=", responseId);
   
      return true;
   }
   
   bool GatewaySaveResponse(const string responseText)
   {
      int h = FileOpen(
         m_responseFile,
         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_UNICODE
      );
   
      if(h == INVALID_HANDLE)
      {
         Print("[GATEWAY] Cannot open m_response file. error=", GetLastError());
         return false;
      }
   
      uint written = FileWriteString(h, responseText);
      FileClose(h);
   
      if(written == 0)
      {
         Print("[GATEWAY] Failed to write m_response file.");
         return false;
      }
   
      Print("[GATEWAY] m_response persisted.");
      return true;
   }
   
   bool GatewayCopySavedResponseToReceived(const string requestId)
   {
      int source = FileOpen(
         m_responseFile,
         FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
      );
   
      if(source == INVALID_HANDLE)
      {
         Print("[GATEWAY] Cannot read temporary m_response.");
         return false;
      }
   
      string responseText = FileReadString(source);
      FileClose(source);
   
      if(responseText == "")
         return false;

   
      string receivedFile =
         m_receivedDir + "/" + requestId + ".json";
   
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
         Print("[GATEWAY] Received m_response write failed.");
         return false;
      }
   
      Print("[GATEWAY] m_response saved to received: ", receivedFile);
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
   else if(status == "FAILED" || status == "CANCELLED")
      event = EVENT_RESPONSE_FAILED;
   
      return true;
   }
   
   bool GatewayLoadPendingRequest(   string &clientId,   string &requestId )
   {
      clientId = "";
      requestId = "";
   
      if(!FileIsExist(m_requestFile, FILE_COMMON))
      {
         Print("[GATEWAY] No pending request file.");
         return false;
      }
   
      int h = FileOpen(
         m_requestFile,
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
         clientId != m_clientId)
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
      if(!FileIsExist(m_responseFile, FILE_COMMON))
         return false;
   
      int h = FileOpen(
         m_responseFile,
         FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
      );
   
      if(h == INVALID_HANDLE)
      {
         Print("[GATEWAY] Cannot open saved m_response. error=", GetLastError());
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
   
      if(status != "COMPLETED" && status != "FAILED" && status != "CANCELLED")
      {
         Print("[GATEWAY] Saved m_response is not final. status=", status);
         return false;
      }
   
      Print("[GATEWAY] Saved final m_response validated. request_id=",
            expectedRequestId,
            " response_id=", responseId);
   
      return true;
   }
   
   bool GatewayGetSavedResponseId(   const string expectedClientId,   const string expectedRequestId,   string &responseId )
   {
      responseId = "";
   
      if(!FileIsExist(m_responseFile, FILE_COMMON))
         return false;
   
      int h = FileOpen(
         m_responseFile,
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
   
      if((status != "COMPLETED" && status != "FAILED" && status != "CANCELLED") ||
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
         m_clientId,
         m_requestId,
         responseId
      ))
      {
         Print("[GATEWAY] Cannot get response_id for ACK.");
         return false;
      }
   
      string path =
         "/gateway/mt5/responses"
         "?client_id=" + m_clientId +
         "&request_id=" + m_requestId +
         "&action=ACK"
         "&response_id=" + responseId;
   
      string responseText;
   
      if(!GatewayHttpGet(path, responseText))
         return false;
   
      CJAVal ackJson;
   
      if(!ackJson.Deserialize(responseText))
      {
         Print("[GATEWAY] Invalid ACK m_response JSON.");
         return false;
      }
   
      if(ackJson["protocol"].ToStr() != "mt5-gateway" ||
         (int)ackJson["version"].ToInt() != 1 ||
         ackJson["message_type"].ToStr() != "ACK_RESULT" ||
         ackJson["client_id"].ToStr() != m_clientId ||
         ackJson["request_id"].ToStr() != m_requestId ||
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
   
      if(FileIsExist(m_requestFile, FILE_COMMON))
         requestDeleted = FileDelete(
            m_requestFile,
            FILE_COMMON
         );
   
      if(FileIsExist(m_responseFile, FILE_COMMON))
         responseDeleted = FileDelete(
            m_responseFile,
            FILE_COMMON
         );
   
      if(!requestDeleted || !responseDeleted)
      {
         Print("[GATEWAY] Cleanup failed. request=",
               requestDeleted,
               " m_response=", responseDeleted);
         return false;
      }
   
      m_lastRequestId = m_requestId;
      m_requestId = "";
   
      Print("[GATEWAY] Request and m_response files cleaned.");
      return true;
   }
   bool GatewayLoadControlRequestIds(
      string &clientId,
      string &requestId
   )
   {
      clientId = "";
      requestId = "";
   
      if(!FileIsExist(m_requestFile, FILE_COMMON))
         return false;
   
      int h = FileOpen(
         m_requestFile,
         FILE_READ | FILE_TXT | FILE_COMMON | FILE_UNICODE
      );
   
      if(h == INVALID_HANDLE)
         return false;
   
      string content = FileReadString(h);
      FileClose(h);
   
      if(content == "")
         return false;
   
      CJAVal requestJson;
   
      if(!requestJson.Deserialize(content))
         return false;
   
      clientId = requestJson["client_id"].ToStr();
      requestId = requestJson["request_id"].ToStr();
   
      if(clientId == "" ||
         requestId == "" ||
         clientId != m_clientId)
      {
         clientId = "";
         requestId = "";
   
         Print("[CONTROL] Invalid request identity.");
         return false;
      }
   
      return true;
   }
   bool GatewayLoadControl(CJAVal &root)
   {
      if(!FileIsExist(m_controlFile, FILE_COMMON))
         return false;
   
      int h = FileOpen(
         m_controlFile,
         FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI
      );
   
      if(h == INVALID_HANDLE)
         return false;
   
      string content = "";
   
      while(!FileIsEnding(h))
         content += FileReadString(h);
   
      FileClose(h);
   
      if(content == "" || !root.Deserialize(content))
         return false;
   
      if(root.m_type != jtOBJ ||
         root["commands"].m_type != jtARRAY ||
         root["commands"].Size() != 1)
         return false;
   
      if(root["commands"][0]["command"].ToStr() != "CANCEL")
         return false;
   
      string status = root["commands"][0]["status"].ToStr();
   
      if(status != "" && status != "COMPLETED")
         return false;
   
      return true;
   }
   
   
   bool GatewaySaveControl(CJAVal &root)
   {
      string content = root.Serialize();
   
      if(content == "")
         return false;
   
      int h = FileOpen(
         m_controlFile,
         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI
      );
   
      if(h == INVALID_HANDLE)
         return false;
   
      uint written = FileWriteString(h, content);
      FileClose(h);
   
      return (written > 0);
   }


   bool GatewayProcessControl()
   {
      CJAVal root;
   
      if(!GatewayLoadControl(root))
      {
         Print("[CONTROL] Cannot load control.json.");
         return false;
      }
   
      string status = root["commands"][0]["status"].ToStr();
   
      if(status == "COMPLETED")
      {
         Print("[CONTROL] No pending emergency command.");
         return true;
      }
   
      // اگر درخواست معوقی وجود ندارد، فرمان مصرف‌شده محسوب می‌شود.
      if(!FileIsExist(m_requestFile, FILE_COMMON))
      {
         Print("[CONTROL] No pending request. CANCEL skipped.");
   
         root["commands"][0]["status"] = "COMPLETED";
   
         return GatewaySaveControl(root);
      }
   
      string clientId;
      string requestId;
      
      if(!GatewayLoadControlRequestIds(clientId, requestId))
      {
         Print("[CONTROL] Cannot identify pending request.");
         return false;
      }
   
      string path =
         "/gateway/mt5/responses"
         "?client_id=" + clientId +
         "&request_id=" + requestId +
         "&action=CANCEL";
   
      string responseText;
   
      Print("[CONTROL] Sending emergency CANCEL. request_id=",
            requestId);
   
      if(!GatewayHttpGet(path, responseText))
      {
         Print("[CONTROL] CANCEL request failed.");
         return false;
      }
   
      CJAVal result;
   
      if(!result.Deserialize(responseText))
      {
         Print("[CONTROL] Invalid CANCEL response JSON.");
         return false;
      }
   
      if(result["protocol"].ToStr() != "mt5-gateway" ||
         (int)result["version"].ToInt() != 1 ||
         result["message_type"].ToStr() != "CONTROL_RESULT" ||
         result["client_id"].ToStr() != clientId ||
         result["request_id"].ToStr() != requestId ||
         result["command"].ToStr() != "CANCEL")
      {
         Print("[CONTROL] CANCEL response validation failed.");
         return false;
      }
   
      string serverStatus = result["status"].ToStr();
   
      if(serverStatus != "CANCEL_REQUESTED" &&
         serverStatus != "ALREADY_COMPLETED")
      {
         Print("[CONTROL] Unexpected server status: ",
               serverStatus);
         return false;
      }

      // The server already knows this request.
      // Ensure the local state continues with POLL, never POST.

      GatewayState currentState;
      GatewayState nextState;

      if(!GatewayLoadState(currentState))
      {
         Print("[CONTROL] Cannot load gateway state after CANCEL.");
         return false;
      }

      // IDLE -> CREATED
      if(currentState == STATE_IDLE)
      {
         if(!GatewayTransitionAndSave(
            currentState,
            EVENT_START,
            nextState
         ))
         {
            Print("[CONTROL] Cannot recover IDLE state after CANCEL.");
            return false;
         }

         currentState = nextState;
      }

      // CREATED -> SENDING
      if(currentState == STATE_CREATED)
      {
         if(!GatewayTransitionAndSave(
            currentState,
            EVENT_REQUEST_READY,
            nextState
         ))
         {
            Print("[CONTROL] Cannot recover CREATED state after CANCEL.");
            return false;
         }

         currentState = nextState;
      }

      // SENDING -> SENT
      if(currentState == STATE_SENDING)
      {
         if(!GatewayTransitionAndSave(
            currentState,
            EVENT_SEND_OK,
            nextState
         ))
         {
            Print("[CONTROL] Cannot switch request to POLL state.");
            return false;
         }

         currentState = nextState;
      }
      
      if(currentState == STATE_ERROR)
      {
         if(!GatewaySaveState("SENT"))
         {
            Print("[CONTROL] Cannot recover ERROR state after CANCEL.");
            return false;
         }
      
         currentState = STATE_SENT;
      
         Print("[CONTROL] ERROR recovered to SENT. Poll will continue.");
      }

      root["commands"][0]["status"] = "COMPLETED";
   
      if(!GatewaySaveControl(root))
      {
         Print("[CONTROL] Cannot save completed control command.");
         return false;
      }
   
      Print("[CONTROL] Emergency CANCEL accepted. request_id=",
            requestId,
            " server_status=",
            serverStatus);
   
      return true;
   }
   bool GatewayLoadCommands(CJAVal &root)
   {
      if(!FileIsExist(m_commandsFile, FILE_COMMON))
      {
         Print("[COMMANDS] File not found: ", m_commandsFile);
         return false;
      }
   
      int h = FileOpen(
         m_commandsFile,
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
         string command =
            root["commands"][i]["command"].ToStr();
      
         string status =
            root["commands"][i]["status"].ToStr();

         if(command == "")
         {
            Print("[COMMANDS] Empty command at index ", i);
            return false;
         }

         if(root["commands"][i]["status"].m_type != jtSTR)
         {
            Print("[COMMANDS] Invalid status type at index ", i);
            return false;
         }
      }   
      
      return true;
   }
   
   bool GatewaySaveCommands(CJAVal &root)
   {
      string content = root.Serialize();
   
      if(content == "")
         return false;
   
      int h = FileOpen(
         m_commandsFile,
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
   
   bool GatewayReadCommandResponse(
      const string requestId,
      string &responseStatus,
      string &payloadJson
   )
   {
      responseStatus = "";
      payloadJson = "";

      if(requestId == "")
         return false;

      string receivedFile =
         m_receivedDir + "/" + requestId + ".json";

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
         result["client_id"].ToStr() != m_clientId ||
         result["request_id"].ToStr() != requestId)
      {
         Print("[COMMANDS] Response envelope identity validation failed.");
         return false;
      }

      responseStatus = result["status"].ToStr();

      if(responseStatus != "COMPLETED" &&
         responseStatus != "FAILED" &&
         responseStatus != "CANCELLED")
      {
         Print("[COMMANDS] Invalid final response status: ",
               responseStatus);
         return false;
      }

      if(result["response_id"].ToStr() == "")
      {
         Print("[COMMANDS] Final response has no response_id.");
         return false;
      }

      if(result["payload"].m_type == jtUNDEF)
      {
         Print("[COMMANDS] Final response has no payload.");
         return false;
      }

      payloadJson = result["payload"].Serialize();

      if(payloadJson == "")
      {
         Print("[COMMANDS] Cannot serialize response payload.");
         return false;
      }

      Print("[COMMANDS] Response received. status=",
            responseStatus);

      return true;
   }   

   
   bool GatewayRunCommands()
   {
      if(!FileIsExist(m_commandsFile, FILE_COMMON))
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
      int processedCount = 0;

      for(int i = 0; i < count; i++)
      {

         string command =
            root["commands"][i]["command"].ToStr();

         string status =
            root["commands"][i]["status"].ToStr();

         if(status != "")
            continue;

         string body = "";

         if(command == "LIST-TABL")
         {
            body =
               "{"
               "\"command\":\"CHART-INIT\","
               "\"operations\":["
                  "{"
                     "\"command\":\"LIST-TABL\""
                  "}"
               "]"
               "}";
         }
         else
         {
            CJAVal bodyObject;
            bodyObject.Clear(jtOBJ);

            for(int fieldIndex = 0;
                fieldIndex < root["commands"][i].Size();
                fieldIndex++)
            {
               string fieldName =
                  root["commands"][i].m_e[fieldIndex].m_key;

               if(fieldName == "status" ||
                  fieldName == "result")
                  continue;

               bodyObject.Add(
                  root["commands"][i].m_e[fieldIndex]
               );
            }

            body = bodyObject.Serialize();
         }

         if(body == "")
         {
            Print("[COMMANDS] Cannot serialize command body.");
            return false;
         }
         
         
         
         Print("[COMMANDS] Executing command: ", command);

         bool gatewaySuccess = GatewayExecuteRequest(body);

         if(!gatewaySuccess)
         {
            Print("[COMMANDS] Gateway execution failed.");
            return false;
         }

         if(!gatewaySuccess)
         {
            Print("[COMMANDS] Gateway execution failed.");
            return false;
         }
   
         string requestId = m_lastRequestId;

         if(requestId == "")
         {
            Print("[COMMANDS] Missing request ID after gateway execution.");
            return false;
         }

         string responseStatus = "";
         string payloadJson = "";

         if(!GatewayReadCommandResponse(
            requestId,
            responseStatus,
            payloadJson
         ))
         {
            Print("[COMMANDS] Cannot read command response.");
            return false;
         }

         root["commands"][i]["status"] = responseStatus;
         root["commands"][i]["result"] = payloadJson;

         if(!GatewaySaveCommands(root))
         {
            Print("[COMMANDS] Cannot save command response.");
            return false;
         }

         if(responseStatus != "COMPLETED")
         {
            Print("[COMMANDS] Command did not complete. status=",
                  responseStatus);
            return false;
         }

         Print("[COMMANDS] Command completed: ", command);
         processedCount++;
      }
   
      if(processedCount == 0)
         Print("[COMMANDS] No pending commands found.");
      
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
            m_clientId,
            m_requestId,
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
      

public:
   bool Initialize( const string clientId, const string folderName )
   {
      if(clientId == "" || folderName == "")
         return false;
   
      if(StringFind(folderName, "/") >= 0 ||
         StringFind(folderName, "\\") >= 0 ||
         folderName == "." ||
         folderName == "..")
         return false;
   
      m_clientId = clientId;
      m_folderName = folderName;
   
      m_rootDir = "LLM-LQ/" + folderName;
      m_feedFile = m_rootDir + "/mt5_feed.json";
   
      m_tempDir = m_rootDir + "/Gateway/temp";
      m_receivedDir = m_rootDir + "/Gateway/received";
      m_commandsDir = m_rootDir + "/Gateway/commands";
      m_controlDir = m_rootDir + "/Gateway/control";
   
      m_requestFile = m_tempDir + "/current_request.json";
      m_stateFile = m_tempDir + "/current_state.txt";
      m_responseFile = m_tempDir + "/current_response.json";
      m_commandsFile = m_commandsDir + "/commands.json";
      m_controlFile = m_controlDir + "/control.json";

      if(!GatewayEnsureFolder("LLM-LQ") ||
         !GatewayEnsureFolder(m_rootDir) ||
         !GatewayEnsureFolder(m_rootDir + "/Gateway") ||
         !GatewayEnsureFolder(m_tempDir) ||
         !GatewayEnsureFolder(m_receivedDir) ||
         !GatewayEnsureFolder(m_commandsDir) ||
         !GatewayEnsureFolder(m_controlDir))
      {
         Print("[GATEWAY] Cannot create storage directories.");
         return false;
      }
   
      MathSrand(
         (int)(GetTickCount() ^ (uint)TimeLocal() ^ (uint)ChartID())
      );
      
      if(!GatewayCreateInitialFile(m_stateFile, "IDLE") ||
         !GatewayCreateInitialFile(m_commandsFile, "{\"commands\":[]}") ||
         !GatewayCreateInitialFile(
            m_controlFile,
            "{\"commands\":[{\"command\":\"CANCEL\",\"status\":\"COMPLETED\"}]}"
         ))
      {
         Print("[GATEWAY] Cannot initialize storage files.");
         return false;
      }
   
      return true;
   }
   bool ProcessControl()
   {
      return GatewayProcessControl();
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
