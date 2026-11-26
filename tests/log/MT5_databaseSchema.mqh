//+------------------------------------------------------------------+
//| MT5-DatabaseSchema.mqh                                           |
//| Central catalog of SQLite CREATE statements.                    |
//| SQL definitions only - no database execution functions.         |
//+------------------------------------------------------------------+
#ifndef MT5_DATABASE_SCHEMA_MQH
#define MT5_DATABASE_SCHEMA_MQH

class CMT5DatabaseSchema
{
public:

   //===============================================================
   // CONFIRMED: Extracted from HassanAgha Expert
   //===============================================================

   static const string H1_CANDLES;
   static const string H6_CANDLES;
   static const string SMALL_BOXES;
   static const string SMALL_BOXES_INDEX;


   //===============================================================
   // DOCUMENTED: LLM-Trading-Consultation-Workflow.md
   //===============================================================

   static const string OPINIONS;


   //===============================================================
   // PROVISIONAL: Schema needs future confirmation
   //===============================================================

   static const string TRADES;
   static const string OPINION_TRADE;
   static const string DEBATE;
   static const string HUMAN_INTERVENTION;


   //===============================================================
   // DOCUMENTED MINIMUM:
   // Historical-Simulation-and-LLM-Data-Isolation.md
   //===============================================================

   static const string SIMULATED_TRADES;
};


//+------------------------------------------------------------------+
//| H1 Candles                                                       |
//| Exact columns extracted from GoSend()                            |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::H1_CANDLES =
   "CREATE TABLE IF NOT EXISTS h1Candles ("
   "symbol TEXT, "
   "time TEXT, "
   "open REAL, "
   "high REAL, "
   "low REAL, "
   "close REAL, "
   "tick_volume INTEGER, "
   "spread_points INTEGER, "
   "river_center REAL, "
   "river_width_pips REAL, "
   "MABIF TEXT"
   ");";


//+------------------------------------------------------------------+
//| H6 Candles                                                       |
//| Exact columns extracted from GoSend()                            |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::H6_CANDLES =
   "CREATE TABLE IF NOT EXISTS h6Candles ("
   "symbol TEXT, "
   "time TEXT, "
   "open REAL, "
   "high REAL, "
   "low REAL, "
   "close REAL, "
   "tick_volume INTEGER, "
   "spread_points INTEGER, "
   "river_center REAL, "
   "river_width_pips REAL, "
   "MABIF TEXT"
   ");";


//+------------------------------------------------------------------+
//| SmallBoxes                                                       |
//| Exact columns extracted from SendSmallBoxRecords()               |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::SMALL_BOXES =
   "CREATE TABLE IF NOT EXISTS SmallBoxes ("
   "StartTime TEXT NOT NULL, "
   "EndTime TEXT NOT NULL, "
   "High REAL NOT NULL, "
   "Low REAL NOT NULL"
   ");";

const string CMT5DatabaseSchema::SMALL_BOXES_INDEX =
   "CREATE UNIQUE INDEX IF NOT EXISTS SmallBoxes_EndTime_uq "
   "ON SmallBoxes (EndTime);";


//+------------------------------------------------------------------+
//| Opinions                                                         |
//| Initial fields documented in consultation workflow              |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::OPINIONS =
   "CREATE TABLE IF NOT EXISTS opinions ("
   "opinion_id INTEGER PRIMARY KEY AUTOINCREMENT, "
   "created_at TEXT, "
   "symbol TEXT, "
   "timeframe TEXT, "
   "candle_reference TEXT, "
   "box_reference TEXT, "
   "model TEXT, "
   "opinion TEXT, "
   "\`select\` INTEGER"
   ");";


//+------------------------------------------------------------------+
//| Trades                                                           |
//| PROVISIONAL                                                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::TRADES =
   "CREATE TABLE IF NOT EXISTS trades ("
   "trade_id INTEGER PRIMARY KEY, "
   "ticket INTEGER NOT NULL UNIQUE, "
   "symbol TEXT, "
   "open_time TEXT, "
   "open_price REAL, "
   "close_time TEXT, "
   "close_price REAL, "
   "profit REAL"
   ");";


//+------------------------------------------------------------------+
//| Opinion - Trade relationship                                     |
//| PROVISIONAL                                                       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::OPINION_TRADE =
   "CREATE TABLE IF NOT EXISTS opinion_trade ("
   "opinion_id INTEGER NOT NULL, "
   "trade_id INTEGER NOT NULL, "
   "PRIMARY KEY (opinion_id, trade_id)"
   ");";


//+------------------------------------------------------------------+
//| Debate                                                           |
//| PROVISIONAL - currently described as Python-owned and temporary  |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::DEBATE =
   "CREATE TABLE IF NOT EXISTS debate ("
   "id INTEGER PRIMARY KEY AUTOINCREMENT, "
   "sequence INTEGER NOT NULL, "
   "role TEXT NOT NULL, "
   "content TEXT NOT NULL, "
   "created_at TEXT"
   ");";


//+------------------------------------------------------------------+
//| Human Intervention                                               |
//| PROVISIONAL - minimal prompt/role instructions managed by Cabin  |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::HUMAN_INTERVENTION =
   "CREATE TABLE IF NOT EXISTS human_intervention ("
   "id INTEGER PRIMARY KEY AUTOINCREMENT, "
   "prompt TEXT NOT NULL, "
   "role TEXT, "
   "enabled INTEGER NOT NULL DEFAULT 1, "
   "position INTEGER NOT NULL DEFAULT 0"
   ");";


//+------------------------------------------------------------------+
//| Simulated Trades                                                 |
//| Minimum fields documented in historical simulation vision       |
//+------------------------------------------------------------------+
const string CMT5DatabaseSchema::SIMULATED_TRADES =
   "CREATE TABLE IF NOT EXISTS simulated_trades ("
   "ticket INTEGER PRIMARY KEY, "
   "open_price REAL"
   ");";


#endif // MT5_DATABASE_SCHEMA_MQH

//+------------------------------------------------------------------+
