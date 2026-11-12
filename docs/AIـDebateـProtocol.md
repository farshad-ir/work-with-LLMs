# MT5–Python Candle Synchronization and AI Debate Protocol

**Version:** 1.2  
**Implementation Baseline:** Existing MT5 sender in `tests/log_a`  
**Scope:** H1 and H6 Candles, Synchronization, AI Debate and Theory Storage

## 1. Objective

Define the operational communication protocol between MetaTrader 5 (MT5) and the Python backend.

The protocol covers:

1. Initial historical candle delivery.
2. Candle validation and synchronization.
3. Missing-candle detection and recovery.
4. Continuous delivery of newly closed candles.
5. Automatic debate requests following new candle delivery.
6. Permanent storage of debate theories, messages, and final assessments.

MT5 is responsible for market calculations. Python is responsible for receiving, validating, synchronizing, storing, and analyzing the supplied data.

Python must not recalculate market indicators already calculated by MT5.

## 2. INIT – Initial Historical Data

At initialization, MT5 sends exactly one JSON message containing both timeframe datasets:

| Timeframe | Number of candles |
|---|---:|
| H1 | 100 |
| H6 | 20 |

The message contains:

- 100 closed H1 candles, ordered from oldest to newest.
- 20 closed H6 candles, ordered from oldest to newest.

Both arrays are delivered together in one HTTP request.

The initial historical data must include the market values calculated by MT5, including River and MA Bifurcation.

The current forming candle must not be included.

## 3. INIT JSON Contract

The proposed INIT envelope is:

```json
{
  "message_type": "INIT",
  "message_id": "unique-message-id",
  "symbol": "EURUSD",
  "timeframes": {
    "H1": {
      "candles": [
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
      ]
    },
    "H6": {
      "candles": [
        {
          "time": "2026-11-12 06:00",
          "open": 1.09800,
          "high": 1.10200,
          "low": 1.09700,
          "close": 1.10000,
          "tick_volume": 5432,
          "spread_points": 14,
          "river_center": 1.09950,
          "river_width_pips": 25.0,
          "ma_bifurcation": {
            "direction": "UP"
          }
        }
      ]
    }
  }
}
```

The arrays above illustrate the structure. In an actual INIT message, H1 must contain 100 candle objects and H6 must contain 20 candle objects.

The candle object must preserve the field names and data types produced by the existing MT5 sender. Any changes to those fields must be explicitly agreed upon before implementation.

## 4. INIT Processing in Python

When Python receives INIT, it must:

1. Validate the message envelope.
2. Validate the symbol and both timeframe arrays.
3. Verify the expected candle counts.
4. Validate every candle object.
5. Check chronological ordering.
6. Detect duplicate timestamps.
7. Detect missing expected candles within each timeframe.
8. Store valid candle data transactionally.
9. Determine synchronization status separately for H1 and H6.

The two timeframe arrays belong to one INIT operation.

Python must not report successful initialization while unresolved synchronization errors remain.

## 5. Missing Candle Detection and Recovery

If Python detects missing candles, it must request the missing data from MT5.

The recovery request must identify:

- Request ID.
- Symbol.
- Timeframe.
- Missing candle timestamps or requested time range.

MT5 responds with the requested candle data.

Python validates and stores the returned candles, then checks the affected timeframe again.

This cycle continues until the required historical range is complete or an explicit error is reported.

Recovery messages must be distinguishable from ordinary new-candle messages.

## 6. INIT Completion

Python maintains independent synchronization states for H1 and H6.

Possible states:

- `RECEIVING`
- `VALIDATING`
- `MISSING_DATA`
- `REQUESTING_RECOVERY`
- `SYNCHRONIZED`
- `ERROR`

INIT is complete only when both timeframe datasets have passed validation and all required missing-candle recovery operations have been resolved.

Python must return an explicit synchronization result to MT5.

## 7. Continuous New Candle Delivery

After successful INIT, MT5 sends each newly closed candle.

Each new candle is sent as a separate update message.

The message identifies:

- Symbol.
- Timeframe.
- Candle data.
- Unique message ID.
- Analysis request information.

Only closed candles are accepted as completed market data.

Python stores each candle using an idempotent operation. Repeated delivery must not create duplicate records.

H1 and H6 updates are processed independently.

## 8. New Candle and Debate Request

Starting with the first newly closed candle after INIT, MT5 requests an AI debate together with the new-candle update.

The new-candle message must explicitly indicate that a debate is requested.

Proposed message structure:

```json
{
  "message_type": "CANDLE_UPDATE",
  "message_id": "unique-message-id",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "candle": {
    "time": "2026-11-12 11:00",
    "open": 1.10150,
    "high": 1.10300,
    "low": 1.10050,
    "close": 1.10250,
    "tick_volume": 1450,
    "spread_points": 11,
    "river_center": 1.10180,
    "river_width_pips": 19.0,
    "ma_bifurcation": {
      "direction": "UP"
    }
  },
  "analysis": {
    "request_debate": true
  }
}
```

The example illustrates an H1 update. H6 updates use the same structure with `"timeframe": "H6"`.

Python must process the message in this order:

1. Validate the incoming candle.
2. Store the candle.
3. Confirm that the candle has been accepted.
4. If `request_debate` is true, create a debate using the latest available market data.
5. Send the same evidence package to the Buy Advocates and Sell Advocates.
6. Run the standardized debate workflow.
7. Store all theories and debate messages.
8. Return the final assessment to MT5.

The debate must not start using an uncommitted or invalid candle.

A repeated message must not unintentionally create a second debate for the same analysis request. The message ID and analysis request identity must support idempotency.

## 9. Candle Data Contract

The candle object follows the existing MT5 sender structure:

| Field | Type | Description |
|---|---|---|
| time | TEXT | Candle timestamp |
| open | NUMBER | Opening price |
| high | NUMBER | Highest price |
| low | NUMBER | Lowest price |
| close | NUMBER | Closing price |
| tick_volume | INTEGER | Tick volume |
| spread_points | INTEGER | Spread in points |
| river_center | NUMBER | River center |
| river_width_pips | NUMBER | River width in pips |
| ma_bifurcation.direction | TEXT | UP, DOWN or UNKNOWN |

The current sender's field names and meanings are the implementation baseline.

Python must preserve MT5-calculated River and Bifurcation values. It must not independently recalculate them.

## 10. Time and Candle Identity

Python must preserve the timestamp supplied by MT5 without silently converting it to another timezone.

The timestamp basis must be documented as broker-server time once confirmed.

The unique candle identity is:

`symbol + timeframe + candle_time`

This identity prevents duplicate records and supports missing-candle recovery.

## 11. SQLite – Candle Storage

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

Storage requirements:

- H1 and H6 records remain logically independent.
- Duplicate candles must not create duplicate records.
- Historical records must not be deleted during ordinary synchronization.
- Batch storage must be transactional.
- Invalid batches must not leave partially stored data.
- Historical corrections must follow an explicit correction policy.

## 12. AI Debate Workflow

Every debate has a unique `debate_id`.

Python prepares a market evidence package using the latest successfully stored candle data and relevant historical context.

The same evidence package is provided to two independent analytical roles.

### BUY_ADVOCATE

The Buy Advocate must:

- Present evidence supporting a bullish scenario.
- Identify evidence against the bullish scenario.
- Explain uncertainty and conflicting signals.
- Formulate a structured bullish theory.

### SELL_ADVOCATE

The Sell Advocate must:

- Present evidence supporting a bearish scenario.
- Identify evidence against the bearish scenario.
- Explain uncertainty and conflicting signals.
- Formulate a structured bearish theory.

Both sides must evaluate opposing evidence rather than ignore it.

## 13. Debate Theory JSON Contract

Each theory is an independent historical record.

Proposed structure:

```json
{
  "debate_id": "debate-unique-id",
  "theories": [
    {
      "theory_id": "theory-001",
      "stage": "INITIAL_THEORIES",
      "speaker": "BUY_ADVOCATE",
      "position": "BULLISH",
      "statement": "The current market structure supports a bullish scenario.",
      "supporting_evidence": [
        "Evidence supporting the bullish interpretation."
      ],
      "opposing_evidence": [
        "Evidence challenging the bullish interpretation."
      ],
      "assumptions": [
        "Assumption used in the analysis."
      ],
      "invalidation_conditions": [
        "Condition that would invalidate the theory."
      ],
      "confidence": null,
      "created_at": "2026-11-12T11:05:00"
    },
    {
      "theory_id": "theory-002",
      "stage": "INITIAL_THEORIES",
      "speaker": "SELL_ADVOCATE",
      "position": "BEARISH",
      "statement": "The current market structure supports a bearish scenario.",
      "supporting_evidence": [
        "Evidence supporting the bearish interpretation."
      ],
      "opposing_evidence": [
        "Evidence challenging the bearish interpretation."
      ],
      "assumptions": [
        "Assumption used in the analysis."
      ],
      "invalidation_conditions": [
        "Condition that would invalidate the theory."
      ],
      "confidence": null,
      "created_at": "2026-11-12T11:05:00"
    }
  ]
}
```

## 14. Debate Stages

The standardized debate consists of:

1. `PREPARE_EVIDENCE`
2. `INITIAL_THEORIES`
3. `CROSS_EXAMINATION`
4. `REBUTTAL`
5. `FINAL_THEORIES`
6. `FINAL_ASSESSMENT`

Every stage is associated with the same `debate_id`.

Theories submitted at different stages must be stored as separate records.

A revised theory must never overwrite the original theory.

## 15. SQLite – Debate and Theory Storage

### Table: `debates`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| debate_id | TEXT | Unique debate identifier |
| symbol | TEXT | Trading symbol |
| timeframe | TEXT | H1 or H6 |
| trigger_message_id | TEXT | Candle update that triggered the debate |
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
| supporting_evidence | TEXT | JSON array |
| opposing_evidence | TEXT | JSON array |
| assumptions | TEXT | JSON array |
| invalidation_conditions | TEXT | JSON array |
| confidence | REAL | Optional confidence value |
| created_at | TEXT | Theory creation time |

### Table: `debate_messages`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| debate_id | TEXT | Associated debate |
| stage | TEXT | Debate stage |
| sender | TEXT | Participant or role |
| recipient | TEXT | Intended recipient |
| content | TEXT | Full message content |
| created_at | TEXT | Message creation time |

### Storage Requirements

- Every debate must have a unique identifier.
- Every theory must reference its debate.
- Every theory revision must be stored separately.
- All debate messages must be preserved.
- Final assessments must not replace original theories.
- Debate history must be retrievable using `debate_id`.

## 16. Final Debate Response to MT5

When the debate is complete, Python returns a structured result:

```json
{
  "message_type": "DEBATE_RESULT",
  "debate_id": "debate-unique-id",
  "trigger_message_id": "unique-message-id",
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

The response references `debate_id` and `trigger_message_id`.

The final assessment is analytical information, not an automatic trading instruction.

## 17. Responsibilities

### MT5

- Calculate market data.
- Calculate River and MA Bifurcation.
- Send one INIT JSON message containing 100 H1 and 20 H6 candles.
- Respond to missing-candle recovery requests.
- Send each newly closed candle.
- Set `request_debate` to true for new-candle updates after INIT.
- Receive synchronization acknowledgements and debate results.

### Python

- Receive and validate INIT.
- Store both timeframe datasets.
- Detect missing candles.
- Request missing data from MT5.
- Confirm synchronization completion.
- Receive and store new candles.
- Start debates when explicitly requested.
- Orchestrate Buy/Sell analysis.
- Store all theories and debate messages.
- Return structured debate results to MT5.

## 18. Implementation Order

Implementation must follow this order:

1. Inspect the existing sender in `tests/log_a`.
2. Finalize the INIT JSON envelope against the existing sender.
3. Implement one-request INIT reception for 100 H1 and 20 H6 candles.
4. Implement validation and SQLite candle storage.
5. Implement missing-candle detection.
6. Implement Python-to-MT5 recovery requests.
7. Implement MT5 recovery responses.
8. Implement synchronization completion acknowledgements.
9. Implement new-candle update messages.
10. Implement debate triggering from the first new candle after INIT.
11. Implement debate and theory storage tables.
12. Implement the standardized debate workflow.
13. Implement structured debate results returned to MT5.

## 19. Acceptance Criteria

The implementation is accepted when:

- INIT sends exactly one JSON message.
- That message contains 100 H1 and 20 H6 candles.
- Python validates and stores both arrays.
- Python detects missing candles and requests recovery.
- MT5 can return the requested missing candles.
- Python confirms successful synchronization.
- Newly closed candles are delivered individually.
- The first new candle after INIT triggers a debate request.
- Repeated messages do not create duplicate candles or unintended duplicate debates.
- Both analytical roles submit and revise theories.
- All theories and messages are permanently stored.
- MT5 receives the structured final assessment.
- The complete debate history can be retrieved using `debate_id`.
