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
// This class contains no trading knowledge.
// ============================================================

class CMADSKnowledge
{
private:
   string commonKnowledge;
   MADS_KNOWLEDGE_ITEM instructions[];

public:
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

   void Clear()
   {
      commonKnowledge = "";
      ArrayResize(instructions, 0);
   }
};

// ============================================================
// Stage 2: MADS Setup Class
// All trading knowledge and role instructions belong here.
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
