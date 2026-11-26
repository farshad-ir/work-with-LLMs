//+------------------------------------------------------------------+
//| MT5_databaseSchema.mqh                                           |
//| Central database schema catalog for MT5 Gateway                  |
//| JSON definitions compatible with Gateway MAKE command            |
//+------------------------------------------------------------------+
#ifndef MT5_DATABASE_SCHEMA_MQH
#define MT5_DATABASE_SCHEMA_MQH


class CMT5DatabaseSchema
{
public:

   //===============================================================
   // CONFIRMED: Extracted from HassanAgha Expert
   //===============================================================

   static const string H1_CANDLES_COLUMNS;
   static const string H6_CANDLES_COLUMNS;

   static const string SMALL_BOXES_COLUMNS;
   static const string SMALL_BOXES_UNIQUE;


   //===============================================================
   // DOCUMENTED: LLM-Trading-Consultation-Workflow.md
   //===============================================================

   static const string OPINIONS_COLUMNS;


   //===============================================================
   // PROVISIONAL: Schema requires future confirmation
   //===============================================================

   static const string TRADES_COLUMNS;
   static const string OPINION_TRADE_COLUMNS;
   static const string DEBATE_COLUMNS;
   static const string HUMAN_INTERVENTION_COLUMNS;


   //===============================================================
   // DOCUMENTED MINIMUM:
   // Historical-Simulation-and-LLM-Data-Isolation.md
   //===============================================================

   static const string SIMULATED_TRADES_COLUMNS;
};


//+------------------------------------------------------------------+
//| H1 Candles                                                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::H1_CANDLES_COLUMNS =
   "["
   "{\"name\":\"symbol\",\"type\":\"TEXT\"},"
   "{\"name\":\"time\",\"type\":\"TEXT\"},"
   "{\"name\":\"open\",\"type\":\"REAL\"},"
   "{\"name\":\"high\",\"type\":\"REAL\"},"
   "{\"name\":\"low\",\"type\":\"REAL\"},"
   "{\"name\":\"close\",\"type\":\"REAL\"},"
   "{\"name\":\"tick_volume\",\"type\":\"INTEGER\"},"
   "{\"name\":\"spread_points\",\"type\":\"INTEGER\"},"
   "{\"name\":\"river_center\",\"type\":\"REAL\"},"
   "{\"name\":\"river_width_pips\",\"type\":\"REAL\"},"
   "{\"name\":\"MABIF\",\"type\":\"TEXT\"}"
   "]";


//+------------------------------------------------------------------+
//| H6 Candles                                                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::H6_CANDLES_COLUMNS =
   "["
   "{\"name\":\"symbol\",\"type\":\"TEXT\"},"
   "{\"name\":\"time\",\"type\":\"TEXT\"},"
   "{\"name\":\"open\",\"type\":\"REAL\"},"
   "{\"name\":\"high\",\"type\":\"REAL\"},"
   "{\"name\":\"low\",\"type\":\"REAL\"},"
   "{\"name\":\"close\",\"type\":\"REAL\"},"
   "{\"name\":\"tick_volume\",\"type\":\"INTEGER\"},"
   "{\"name\":\"spread_points\",\"type\":\"INTEGER\"},"
   "{\"name\":\"river_center\",\"type\":\"REAL\"},"
   "{\"name\":\"river_width_pips\",\"type\":\"REAL\"},"
   "{\"name\":\"MABIF\",\"type\":\"TEXT\"}"
   "]";


//+------------------------------------------------------------------+
//| SmallBoxes                                                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::SMALL_BOXES_COLUMNS =
   "["
   "{\"name\":\"StartTime\",\"type\":\"TEXT\",\"not_null\":true},"
   "{\"name\":\"EndTime\",\"type\":\"TEXT\",\"not_null\":true},"
   "{\"name\":\"High\",\"type\":\"REAL\",\"not_null\":true},"
   "{\"name\":\"Low\",\"type\":\"REAL\",\"not_null\":true}"
   "]";


const string CMT5DatabaseSchema::SMALL_BOXES_UNIQUE =
   "["
   "{"
   "\"name\":\"SmallBoxes_EndTime_uq\","
   "\"columns\":[\"EndTime\"]"
   "}"
   "]";


//+------------------------------------------------------------------+
//| Opinions                                                         |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::OPINIONS_COLUMNS =
   "["
   "{\"name\":\"opinion_id\",\"type\":\"INTEGER\"},"
   "{\"name\":\"created_at\",\"type\":\"TEXT\"},"
   "{\"name\":\"symbol\",\"type\":\"TEXT\"},"
   "{\"name\":\"timeframe\",\"type\":\"TEXT\"},"
   "{\"name\":\"candle_reference\",\"type\":\"TEXT\"},"
   "{\"name\":\"box_reference\",\"type\":\"TEXT\"},"
   "{\"name\":\"model\",\"type\":\"TEXT\"},"
   "{\"name\":\"opinion\",\"type\":\"TEXT\"},"
   "{\"name\":\"select\",\"type\":\"INTEGER\"}"
   "]";


//+------------------------------------------------------------------+
//| Trades - PROVISIONAL                                             |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::TRADES_COLUMNS =
   "["
   "{\"name\":\"trade_id\",\"type\":\"INTEGER\"},"
   "{\"name\":\"ticket\",\"type\":\"INTEGER\",\"not_null\":true},"
   "{\"name\":\"symbol\",\"type\":\"TEXT\"},"
   "{\"name\":\"open_time\",\"type\":\"TEXT\"},"
   "{\"name\":\"open_price\",\"type\":\"REAL\"},"
   "{\"name\":\"close_time\",\"type\":\"TEXT\"},"
   "{\"name\":\"close_price\",\"type\":\"REAL\"},"
   "{\"name\":\"profit\",\"type\":\"REAL\"}"
   "]";


//+------------------------------------------------------------------+
//| Opinion - Trade relationship - PROVISIONAL                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::OPINION_TRADE_COLUMNS =
   "["
   "{\"name\":\"opinion_id\",\"type\":\"INTEGER\",\"not_null\":true},"
   "{\"name\":\"trade_id\",\"type\":\"INTEGER\",\"not_null\":true}"
   "]";


//+------------------------------------------------------------------+
//| Debate - PROVISIONAL                                             |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::DEBATE_COLUMNS =
   "["
   "{\"name\":\"sequence\",\"type\":\"INTEGER\",\"not_null\":true},"
   "{\"name\":\"role\",\"type\":\"TEXT\",\"not_null\":true},"
   "{\"name\":\"content\",\"type\":\"TEXT\",\"not_null\":true},"
   "{\"name\":\"created_at\",\"type\":\"TEXT\"}"
   "]";


//+------------------------------------------------------------------+
//| Human Intervention - PROVISIONAL                                 |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::HUMAN_INTERVENTION_COLUMNS =
   "["
   "{\"name\":\"prompt\",\"type\":\"TEXT\",\"not_null\":true},"
   "{\"name\":\"role\",\"type\":\"TEXT\"},"
   "{\"name\":\"trigger\",\"type\":\"TEXT\"},"
   "{\"name\":\"enabled\",\"type\":\"INTEGER\",\"not_null\":true}"
   "]";



//+------------------------------------------------------------------+
//| Simulated Trades - DOCUMENTED MINIMUM                            |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::SIMULATED_TRADES_COLUMNS =
   "["
   "{\"name\":\"ticket\",\"type\":\"INTEGER\"},"
   "{\"name\":\"open_price\",\"type\":\"REAL\"}"
   "]";


#endif // MT5_DATABASE_SCHEMA_MQH

//+------------------------------------------------------------------+
