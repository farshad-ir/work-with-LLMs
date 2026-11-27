#ifndef MT5_MADS_SETUP_MQH
#define MT5_MADS_SETUP_MQH

// ============================================================
// MADS Roles
// ============================================================

#define MADS_ROLE_BUYER  "BUYER"
#define MADS_ROLE_SELLER "SELLER"
#define MADS_ROLE_CRITIC "CRITIC"

// ============================================================
// Knowledge Item Structure
// ============================================================

struct MADS_KNOWLEDGE_ITEM
{
   string role;
   string prompt;
   string trigger;
};

// ============================================================
// Stage 1: Knowledge Management Class
// ============================================================

class CMADSKnowledge
{
private:
   string commonKnowledge;
   MADS_KNOWLEDGE_ITEM instructions[];

   // ---------------------------------------------------------
   // JSON String Escape
   // ---------------------------------------------------------

   string JsonEscape(const string value)
   {
      string result = "";

      for(int i = 0; i < StringLen(value); i++)
      {
         ushort ch = StringGetCharacter(value, i);

         if(ch == 34)
            result += "\\\"";
         else if(ch == 92)
            result += "\\\\";
         else if(ch == 8)
            result += "\\b";
         else if(ch == 9)
            result += "\\t";
         else if(ch == 10)
            result += "\\n";
         else if(ch == 12)
            result += "\\f";
         else if(ch == 13)
            result += "\\r";
         else if(ch < 32)
            result += StringFormat("\\u%04X", (int)ch);
         else
            result += ShortToString(ch);
      }

      return result;
   }

public:


CMADSKnowledge()
{
   commonKnowledge = "";
   ArrayResize(instructions, 0);
}

   // ---------------------------------------------------------
   // Common Knowledge
   // ---------------------------------------------------------

   void AddCommonKnowledge(const string text)
   {
      if(text == "")
         return;

      if(commonKnowledge != "")
         commonKnowledge += "\n\n";

      commonKnowledge += text;
   }

   string GetCommonKnowledge()
   {
      return commonKnowledge;
   }

   // ---------------------------------------------------------
   // Role Instructions
   // ---------------------------------------------------------

   bool AddInstruction(
      const string role,
      const string prompt,
      const string trigger = ""
   )
   {
      if(prompt == "")
         return false;

      if(role != MADS_ROLE_BUYER &&
         role != MADS_ROLE_SELLER &&
         role != MADS_ROLE_CRITIC)
         return false;

      int count = ArraySize(instructions);

      if(ArrayResize(instructions, count + 1) != count + 1)
         return false;

      instructions[count].role = role;
      instructions[count].prompt = prompt;
      instructions[count].trigger = trigger;

      return true;
   }

   int InstructionCount()
   {
      return ArraySize(instructions);
   }

   bool GetInstruction(
      const int index,
      string &role,
      string &prompt,
      string &trigger
   )
   {
      int count = ArraySize(instructions);

      if(index < 0 || index >= count)
         return false;

      role    = instructions[index].role;
      prompt  = instructions[index].prompt;
      trigger = instructions[index].trigger;

      return true;
   }

   // ---------------------------------------------------------
   // JSON: Human_Intervention
   //
   // Columns:
   // prompt, role, trigger, enabled
   // ---------------------------------------------------------

   string GetHumanInterventionJSON()
   {
      string json = "[";
      int count = ArraySize(instructions);

      for(int i = 0; i < count; i++)
      {
         if(i > 0)
            json += ",";

         json += "{";
         json += "\"prompt\":\"" + JsonEscape(instructions[i].prompt) + "\",";
         json += "\"role\":\"" + JsonEscape(instructions[i].role) + "\",";
         json += "\"trigger\":\"" + JsonEscape(instructions[i].trigger) + "\",";
         json += "\"enabled\":1";
         json += "}";
      }

      json += "]";

      return json;
   }

   // ---------------------------------------------------------
   // JSON: Debate
   //
   // Columns:
   // sequence, role, event_type, tool_call_id,
   // content, created_at
   //
   // Common knowledge is inserted as one CONTEXT record.
   // ---------------------------------------------------------

   string GetDebateKnowledgeJSON()
   {
      if(commonKnowledge == "")
         return "[]";

      string json = "[";

      json += "{";
      json += "\"sequence\":1,";
      json += "\"role\":\"SYSTEM\",";
      json += "\"event_type\":\"CONTEXT\",";
      json += "\"content\":\"" + JsonEscape(commonKnowledge) + "\"";
      json += "}";

      json += "]";

      return json;
   }



   // ---------------------------------------------------------
   // Clear
   // ---------------------------------------------------------

   void Clear()
   {
      commonKnowledge = "";
      ArrayResize(instructions, 0);
   }
};

// ============================================================
// Stage 2: MADS Setup Class
// Trading knowledge and role instructions belong here.
// ============================================================

class CMADSSetup : public CMADSKnowledge
{
public:

   CMADSSetup()
   {
      // ------------------------------------------------------
      // Common Knowledge
      // ------------------------------------------------------

      AddCommonKnowledge(
         "MARKET UNDERSTANDING:\n"
         "The market continuously evaluates price levels.\n"
         "Instability in the Moving Average River may indicate "
         "that the market is making a decision."
      );

      AddCommonKnowledge(
         "TOOLS AND METHODOLOGY:\n"
         "MABIF, River and Box structures are tools for "
         "understanding market behavior.\n"
         "Overlapping Boxes across time may indicate "
         "consolidation.\n"
         "A decisive move outside a consolidation area "
         "may indicate a change in market behavior."
      );

      // ------------------------------------------------------
      // Buyer Instructions
      // ------------------------------------------------------

      AddInstruction(
         MADS_ROLE_BUYER,
         "Look for buying opportunities.\n"
         "Examine previous Boxes as potential support areas.\n"
         "Evaluate the behavior and direction of the River.\n"
         "Present evidence supporting a buying decision."
      );

      // ------------------------------------------------------
      // Seller Instructions
      // ------------------------------------------------------

      AddInstruction(
         MADS_ROLE_SELLER,
         "Look for selling opportunities.\n"
         "Examine previous Boxes as potential resistance areas.\n"
         "Pay attention to price weakness or rejection "
         "after an upward movement.\n"
         "Evaluate the behavior and direction of the River.\n"
         "Present evidence supporting a selling decision."
      );

      // ------------------------------------------------------
      // Critic Instructions
      // ------------------------------------------------------

      AddInstruction(
         MADS_ROLE_CRITIC,
         "Evaluate the arguments presented by Buyer and Seller.\n"
         "Identify contradictions, missing evidence and weak assumptions.\n"
         "Ask for clarification or additional evidence when necessary.\n"
         "You decide which role should speak next: BUYER, SELLER or CRITIC.\n"
         "You may request additional market data through LLM-SELECTION.\n"
         "You are responsible for deciding when the debate has "
         "reached a sufficient conclusion.",
         "Use these instructions throughout the debate. "
         "Select the next role according to the current state "
         "of the discussion. End the debate when further discussion "
         "is unlikely to improve the conclusion."
      );
   }
};

#endif
