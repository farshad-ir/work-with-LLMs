# MT5–Python Candle Synchronization and AI Debate Protocol

**Version:** 1.1 – Proposed Operational Specification  
**Scope:** H1 and H6 Candles, Synchronization, AI Debate and Theory Storage

## 1. System Objective

Establish a reliable, bidirectional communication protocol between MetaTrader 5 (MT5) and the Python backend.

The protocol has four responsibilities:

1. Initial historical candle synchronization.
2. Detection and recovery of missing or invalid candles.
3. Continuous delivery and storage of newly closed candles.
4. On-demand analytical debates between Buy Advocates and Sell Advocates, with permanent storage of their theories and conclusions.

MT5 is the source of market calculations. Python is responsible for synchronization, validation, storage, orchestration, and AI debate execution.

## 2. Initial Synchronization (INIT)

At initialization, MT5 sends:

| Timeframe | Initial candle count |
|---|---:|
| H1 | 100 |
| H6 | 20 |

Only closed candles are included.

Each timeframe is synchronized independently.

The initial payload contains candle data calculated by MT5, including River and MA Bifurcation values.

Python must not recalculate these market indicators.

## 3. Python Validation

After receiving INIT, Python must:

1. Parse and validate the incoming payload.
2. Validate every candle and its required fields.
3. Check chronological ordering.
4. Detect duplicate candles.
5. Detect missing expected candles within the synchronized range.
6. Store valid data transactionally.
7. Maintain synchronization status independently for H1 and H6.

A successful HTTP response alone does not mean synchronization is complete.

Python must explicitly determine whether the received historical range is complete.

## 4. Missing Candle Recovery

If Python detects missing candles, it sends a structured request to MT5.

The request identifies:

- Symbol.
- Timeframe.
- Missing candle timestamps or requested time range.
- Request identifier.

MT5 responds by sending the requested candle data.

Python validates and stores the response, then checks synchronization again.

This request/response cycle continues until the required historical range is complete or an explicit synchronization error is reported.

## 5. Synchronization Completion

Python maintains a separate synchronization status for each timeframe.

Possible states:

- `RECEIVING`
- `VALIDATING`
- `MISSING_DATA`
- `REQUESTING_RECOVERY`
- `SYNCHRONIZED`
- `ERROR`

The system must not report INIT as complete while unresolved missing candles remain.

## 6. Continuous Candle Updates

After successful initialization, MT5 sends each newly closed candle.

Only closed candles are accepted as completed market data.

The currently forming candle must not be treated as a closed candle.

Python validates and stores every incoming candle using an idempotent operation.

Repeated delivery of the same candle must not create duplicate records.

H1 and H6 updates are processed independently.

## 7. Candle Data Contract

The candle object is based on the existing MT5 sender:

```json
{
  "time": "2026-11-12 10:00",
  "open": 1.10000,
  "high": 1.10200,
  "low": 1.09900,
  "close": 1.10150,
  "tick_volume": 1234,
  "spread_points": 12,
  "river_center": 1.10080,
  "river_width_pips": 18.5,
  "ma_bifurcation": {
    "direction": "UP"
  }
}
```

The message envelope must identify:

- Message type.
- Symbol.
- Timeframe.
- Request or synchronization identifier, when applicable.
- Candle array.

### INIT example

```json
{
  "message_type": "INIT",
  "message_id": "init-unique-id",
  "symbol": "EURUSD",
  "timeframes": {
    "H1": {
      "candles": []
    },
    "H6": {
      "candles": []
    }
  }
}
```

The H1 array must contain 100 candles and the H6 array must contain 20 candles.

The example shows the envelope only; the actual arrays contain the candle objects defined above.

## 8. Time and Candle Identity

The timestamp must preserve the time supplied by MT5.

Python must not silently convert timestamps to another timezone.

The timestamp basis must be documented as broker-server time if confirmed.

The unique candle identity is:

`symbol + timeframe + candle_time`

This identity prevents duplicate records and supports recovery requests.

## 9. Database Design – Candle Storage

Python stores candle data in SQLite.

### Table: `candles`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| symbol | TEXT | Trading symbol |
| timeframe | TEXT | H1 or H6 |
| candle_time | TEXT | MT5 candle timestamp |
| open | REAL | Open price |
| high | REAL | High price |
| low | REAL | Low price |
| close | REAL | Close price |
| tick_volume | INTEGER | Tick volume |
| spread_points | INTEGER | Spread |
| river_center | REAL | River center |
| river_width_pips | REAL | River width |
| ma_bifurcation_direction | TEXT | UP, DOWN or UNKNOWN |
| received_at | TEXT | Python reception timestamp |

Unique constraint:

`UNIQUE(symbol, timeframe, candle_time)`

### Storage Rules

- H1 and H6 records remain logically independent.
- Repeated candles must not create duplicate records.
- Historical records must not be deleted during ordinary synchronization.
- Batch storage must be transactional.
- Invalid batches must not leave partially stored data.
- Existing records must not be overwritten without an explicit correction policy.

## 10. Acknowledgements

Every MT5 request must receive a structured response.

The response should identify:

- Whether the request was accepted.
- Whether validation succeeded.
- How many candles were inserted.
- How many were already present.
- Whether missing candles remain.
- Whether synchronization is complete.
- Which recovery action, if any, is required.

## 11. AI Debate Workflow

Candle ingestion and AI debate execution are separate operations.

A dedicated analysis command starts a debate.

Python prepares the current market information and sends the same evidence package to two independent analytical roles:

### Buy Advocates

The Buy Advocates must:

- Present evidence supporting a bullish position.
- Identify evidence against the bullish interpretation.
- Explain uncertainty and conflicting signals.
- Formulate a structured bullish theory.

### Sell Advocates

The Sell Advocates must:

- Present evidence supporting a bearish position.
- Identify evidence against the bearish interpretation.
- Explain uncertainty and conflicting signals.
- Formulate a structured bearish theory.

Neither side should ignore evidence that contradicts its position.

## 12. Debate Message Structure

Each debate must have a unique `debate_id`.

The following is the proposed structure for storing and exchanging a theory:

```json
{
  "debate_id": "debate-unique-id",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "stage": "INITIAL_THEORIES",
  "theories": [
    {
      "theory_id": "theory-001",
      "speaker": "BUY_ADVOCATE",
      "position": "BULLISH",
      "statement": "The current market structure supports a bullish scenario.",
      "supporting_evidence": [
        "River position supports the bullish interpretation."
      ],
      "opposing_evidence": [
        "The latest price movement introduces uncertainty."
      ],
      "assumptions": [
        "The current market structure remains valid."
      ],
      "invalidation_conditions": [
        "A confirmed bearish structural change."
      ],
      "confidence": null,
      "created_at": "2026-11-12T10:05:00"
    },
    {
      "theory_id": "theory-002",
      "speaker": "SELL_ADVOCATE",
      "position": "BEARISH",
      "statement": "The current market structure supports a bearish scenario.",
      "supporting_evidence": [
        "Price behavior provides evidence for a bearish interpretation."
      ],
      "opposing_evidence": [
        "Some market indicators do not confirm the bearish scenario."
      ],
      "assumptions": [
        "The bearish structure remains valid."
      ],
      "invalidation_conditions": [
        "A confirmed bullish structural change."
      ],
      "confidence": null,
      "created_at": "2026-11-12T10:05:00"
    }
  ]
}
```

This is a proposed logical contract. Exact field types and validation rules will be finalized during implementation.

## 13. Debate Stages

The standardized debate workflow consists of:

1. `PREPARE_EVIDENCE` – Prepare the current market evidence.
2. `INITIAL_THEORIES` – Both sides independently formulate their theories.
3. `CROSS_EXAMINATION` – Each side challenges the opposing theory.
4. `REBUTTAL` – Each side responds to the challenges.
5. `FINAL_THEORIES` – Both sides submit their revised theories.
6. `FINAL_ASSESSMENT` – Python produces the structured final report.

Each stage must be associated with the same `debate_id`.

Theories submitted at different stages must be preserved as separate historical records. New theories must not overwrite earlier theories.

## 14. Database Design – Debate and Theory Storage

Debate records and individual theories must be stored separately.

### Table: `debates`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| debate_id | TEXT | Unique debate identifier |
| symbol | TEXT | Trading symbol |
| timeframe | TEXT | Main analytical timeframe |
| status | TEXT | Current debate status |
| started_at | TEXT | Debate start time |
| completed_at | TEXT | Debate completion time |
| final_assessment | TEXT | Final structured assessment |

### Table: `debate_theories`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| theory_id | TEXT | Unique theory identifier |
| debate_id | TEXT | Associated debate |
| stage | TEXT | Debate stage |
| speaker | TEXT | BUY_ADVOCATE or SELL_ADVOCATE |
| position | TEXT | BULLISH, BEARISH or NEUTRAL |
| statement | TEXT | Main theory |
| supporting_evidence | TEXT | JSON array of supporting evidence |
| opposing_evidence | TEXT | JSON array of opposing evidence |
| assumptions | TEXT | JSON array of assumptions |
| invalidation_conditions | TEXT | JSON array of invalidation conditions |
| confidence | REAL | Optional confidence value |
| created_at | TEXT | Theory creation time |

### Table: `debate_messages`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| debate_id | TEXT | Associated debate |
| stage | TEXT | Message stage |
| sender | TEXT | Role or participant |
| recipient | TEXT | Intended recipient |
| content | TEXT | Full message content |
| created_at | TEXT | Message creation time |

### Storage Principles

- Every debate has a unique identifier.
- Every theory belongs to a specific debate.
- Each theory is stored as an independent historical record.
- Revised theories are inserted as new records.
- Debate messages are preserved.
- Final assessments do not replace the original theories.
- The complete debate history must remain available for future review.

## 15. Final Debate Response to MT5

After the debate is complete, Python returns a structured result.

The response should include:

```json
{
  "message_type": "DEBATE_RESULT",
  "debate_id": "debate-unique-id",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "status": "COMPLETED",
  "summary": {
    "bullish_case": "Summary of bullish evidence.",
    "bearish_case": "Summary of bearish evidence.",
    "main_conflict": "The most important disagreement.",
    "risks": [
      "Important uncertainty or risk."
    ],
    "final_assessment": "A reasoned analytical assessment.",
    "invalidation_conditions": [
      "Conditions that would invalidate the assessment."
    ]
  }
}
```

The result must also reference the stored `debate_id` so that MT5 or another application can retrieve the complete debate history.

The AI must distinguish market facts from its own interpretations.

The final assessment is analytical information, not an automatic trading instruction.

## 16. Separation of Responsibilities

### MT5

- Calculates market data.
- Calculates River and MA Bifurcation.
- Sends 100 H1 and 20 H6 candles during INIT.
- Responds to missing-candle requests.
- Sends newly closed candles.
- Sends analysis commands.
- Receives debate results.

### Python

- Receives and validates candle messages.
- Detects missing data.
- Requests recovery from MT5.
- Stores candles in SQLite.
- Tracks synchronization status.
- Prepares analytical evidence.
- Orchestrates Buy/Sell debates.
- Stores all debate theories and messages.
- Preserves debate history.
- Returns structured results to MT5.

## 17. Implementation Order

Implementation must follow this order:

1. Finalize the candle message envelope.
2. Implement INIT reception for 100 H1 and 20 H6 candles.
3. Implement SQLite candle storage.
4. Implement missing-candle detection.
5. Implement the Python-to-MT5 recovery request.
6. Implement the MT5 recovery response.
7. Implement synchronization completion reporting.
8. Implement continuous closed-candle delivery.
9. Implement debate and theory database tables.
10. Implement the standardized debate workflow.
11. Implement structured debate results returned to MT5.

## 18. Acceptance Criteria

The implementation is accepted when:

- INIT delivers 100 H1 and 20 H6 candles.
- Python can detect missing candles.
- Python can request missing data from MT5.
- MT5 can return the requested candles.
- Python can verify that synchronization is complete.
- Newly closed candles are stored without duplication.
- H1 and H6 synchronization remain independent.
- A debate command starts the standardized Buy/Sell workflow.
- Both sides can submit and revise theories.
- Every theory and debate message is permanently preserved.
- MT5 receives a structured final analytical report.
- The complete debate history can be retrieved using its debate identifier.
