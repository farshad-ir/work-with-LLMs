# Thinker Room Architecture

**Repository:** `farshad-ir/work-with-LLMs`  
**Branch:** `hotfix/laravel-stream`  
**Document Version:** 1.0 — Initial Proposal for Agreement Before Implementation

## 1. Purpose and Design Principles

The goal is to establish a reliable data flow from MetaTrader to the Thinker Room:

- MetaTrader generates market data and market events.
- Python receives, validates, and coordinates the data.
- SQLite serves as the persistent memory of the Thinker Room.
- AI performs analysis, debate, and theory evaluation.

Core principles:

1. Market facts must remain separate from AI interpretations.
2. Only closed candles are transmitted. In MT5, shift 1 represents the most recently closed candle, while shift 0 represents the currently forming candle. Shift 0 must never be transmitted.
3. The initial transmission is a full synchronization, and subsequent transmissions are incremental.
4. Each section maintains an independent synchronization state.
5. If a section is invalid, only that section is requested again through a full synchronization.
6. Processing a duplicate message must not create duplicate records.
7. Events, theories, and evaluations must be historical and immutable.
8. Market calculations are performed in MT5; Python must not recalculate market data from incomplete information.

## 2. Component Responsibilities

### 2.1 MetaTrader Collector

Responsibilities:

- Generate 60 closed H1 candles.
- Generate 10 closed H6 candles.
- Include OHLC, MA Bifurcation direction, and River Center/Width in each candle record.
- Publish Box events with their actual start time, end time, and detection time.
- Identify independent Boxes based on temporal criteria.
- Execute ZigZag only when a new independent Box is identified.
- Support Full Sync and Delta transmissions.
- Preserve raw ZigZag information even when the final analysis is unavailable.

The current Sender in `tests/log_a` will remain untouched unless a specific technical requirement justifies changing it.

### 2.2 Python / FastAPI

Responsibilities:

- Validate JSON and the contract version.
- Manage message identifiers and prevent duplicate processing.
- Persist data in SQLite.
- Manage the synchronization state of each section.
- Respond to MT5 with either an acknowledgment or a Full Resync request.
- Execute the Thinker Room workflow and record theories and evaluations.

### 2.3 SQLite

SQLite is the persistent memory and the source of truth for the Thinker Room's state.

The existing `mt5_stats` table may be retained for traffic statistics, but it is not a substitute for actual market data storage.

### 2.4 AI Debate Room

There are two independent analysts:

- Bullish: represents buyers.
- Bearish: represents sellers.

Both must record their theories, evidence, predictions, confidence levels, and invalidation conditions. Previous theories must never be overwritten.

## 3. Market Data Contract

### 3.1 Candle Windows

| Series | Full Sync Count | Description |
|---|---:|---|
| H1 | 60 | The most recent 60 closed candles |
| H6 | 10 | The most recent 10 closed candles |

H1 and H6 are two independent series. An H6 candle must not be artificially duplicated into six H1 records.

### 3.2 Candle Record Structure

Conceptual example:

```json
{
  "time": "2026-11-12T10:00:00Z",
  "open": 1.10000,
  "high": 1.10200,
  "low": 1.09900,
  "close": 1.10150,
  "tick_volume": 1234,
  "spread_points": 12,
  "ma_bifurcation": {
    "direction": "up"
  },
  "river": {
    "center": 1.10080,
    "width_pips": 18.5
  }
}
```

Allowed MA direction values:

- `up`
- `down`
- `unknown`

Notes:

- MA direction and River information are stored together with the corresponding candle.
- H1 and H6 each have independent records.
- Only closed candles are accepted.
- An uncalculated value must be `null`, not an artificially assigned zero.
- The measurement unit of River Width must be explicitly specified.

## 4. Boxes and Temporal Independence

### 4.1 Box Recording

Each Box is an independent entity and must contain at least the following information:

- `box_id`
- `symbol`
- `timeframe`
- `start_time`
- `end_time`
- `high`
- `low`
- `detected_at`
- Source message identifier or sequence

The actual end time of a Box and the time at which it is detected are two different concepts.

A Box may have ended during the second candle but only be detected and announced during the third candle. Both timestamps must be recorded.

### 4.2 Independence Criteria

Box independence is determined exclusively by time, not by price overlap.

- Previous Box: 11 to 15
- New Box: 15 to 19 — not independent.
- New Box: 17 to 21 — independent, because there is at least one complete free H1 candle between them.

All detected Boxes must be recorded, including those that are not independent.

However, only an independent Box can generate a new independent event and trigger ZigZag execution.

The three most recent independent Boxes must be retrievable as the active FIFO view. This must not result in the deletion of Box history.

**Important technical note:** The exact definitions of the Box start and end boundaries must be established in the Collector in relation to candle opening times and interval-ending boundaries. This is necessary to prevent a one-hour error when applying the condition requiring one complete free candle.

## 5. ZigZag Analysis

When a new independent Box is detected, the free interval between it and the previous independent Box is passed to ZigZag.

Only free candles within this interval are examined. Candles belonging to the Boxes themselves are excluded from this analysis.

Each ZigZag analysis is stored as an independent record:

- `analysis_id`
- `symbol`
- `timeframe`
- `from_independent_box_id`
- `to_independent_box_id`
- `window_start`
- `window_end`
- `created_at`
- `raw_points`
- `analysis_result`
- `status`

Very important:

If the ZigZag theory or analysis result is unavailable, the raw points must not be deleted.

Therefore:

- `raw_points` must be stored independently of the analysis result.
- An unavailable result must not be confused with missing raw data.
- Previous analyses must never be overwritten.

## 6. Full Sync and Incremental Update

### 6.1 Proposed Envelope

```json
{
  "schema_version": 1,
  "client_id": "mt5_terminal_01",
  "conversation_id": "stable-conversation-id",
  "message_id": "unique-message-id",
  "message_type": "market_data",
  "sync_mode": "full",
  "generated_at": "2026-11-12T10:05:00Z",
  "sections": {
    "market_h1": {
      "mode": "replace",
      "data": []
    },
    "market_h6": {
      "mode": "replace",
      "data": []
    },
    "boxes": {
      "mode": "replace",
      "data": []
    },
    "independent_boxes": {
      "mode": "replace",
      "data": []
    },
    "zigzag_analyses": {
      "mode": "replace",
      "data": []
    }
  }
}
```

This is a proposed contract design, not a claim about the current implementation.

In Delta mode, only new data or events are transmitted. The operation for each section must be explicit, such as `append` or another clearly defined operation.

### 6.2 Synchronization Lifecycle

1. MT5 sends a Full Sync during the initial connection.
2. Python validates the message.
3. Data is stored in SQLite within a single transaction.
4. Python independently records the synchronization state of each section.
5. If all required sections are valid, MT5 begins sending Delta updates.
6. If a section is incomplete or invalid, only that section is requested again through a Full Resync.
7. Valid sections are not retransmitted without a specific reason.

### 6.3 Proposed Response

```json
{
  "success": true,
  "message_id": "unique-message-id",
  "acknowledged": true,
  "sections": {
    "market_h1": {
      "status": "valid",
      "last_sequence": 120
    },
    "market_h6": {
      "status": "valid",
      "last_sequence": 20
    },
    "boxes": {
      "status": "valid",
      "last_sequence": 35
    },
    "independent_boxes": {
      "status": "valid",
      "last_sequence": 8
    },
    "zigzag_analyses": {
      "status": "resync_required"
    }
  },
  "requested_full_sections": [
    "zigzag_analyses"
  ]
}
```

### 6.4 Duplicate Message Prevention

- Each message has a unique `message_id`.
- A duplicate message is not processed again.
- The previous response can be returned for a retry.
- Each section has its own independent, incrementing sequence.
- A late-arriving message must not roll back a more recent state.
- Message registration, data storage, and synchronization-state updates must be performed within a single transaction.

## 7. Proposed SQLite Structure

| Table | Responsibility |
|---|---|
| `conversations` | Market conversations and their metadata |
| `ingest_messages` | Received messages and idempotency |
| `sync_states` | Synchronization state of each section |
| `market_candles` | H1 and H6 candles and their associated information |
| `boxes` | All detected Boxes |
| `independent_boxes` | Independent Boxes and their ordering |
| `zigzag_analyses` | Independent ZigZag analyses |
| `theories` | Bullish and Bearish theories |
| `theory_evidence` | Evidence supporting theories |
| `predictions` | Measurable predictions |
| `evaluations` | Prediction evaluations |
| `debate_rounds` | Debate rounds and their summaries |

### Important Notes

- Candles are stored in a single table with a `timeframe` column.
- The unique candle key consists of conversation, symbol, timeframe, and candle_time.
- Raw ZigZag data may be stored in SQLite as valid JSON.
- Theories and predictions are append-only.
- The active FIFO window must not delete the learning history.
- The existing `mt5_stats` table remains separate.

## 8. Theories and Debate

Each theory must contain at least the following:

- `theory_id`
- `conversation_id`
- `analyst_role`
- `created_at`
- Identifier of the latest market data used
- `market_view`
- Reasoning
- Evidence
- Analytical handles
- Confidence level
- Invalidation conditions
- Debate round identifier

### Measurable Predictions

As far as possible, a prediction must specify:

- Expected direction
- Target level or event
- Time horizon or number of candles
- Success condition
- Failure condition
- Invalidation condition
- Expiration time

For example, "The specified high will be broken within the next six H1 candles" is more measurable and evaluable than "The market will become bullish."

### Evaluation

Evaluations must use data received after the prediction was issued.

Each evaluation includes its timestamp, reference data, evaluation criteria, and result.

The original theory remains unchanged; evaluations are linked to it.

## 9. Analytical Handles

### Information Generated in MT5

- MA Bifurcation direction on H1 and H6
- River Center and Width for each candle
- Box ranges and timestamps
- Temporal independence of Boxes
- Raw ZigZag points within free intervals

### Interpretive Information Generated by AI

- Trends in Box highs and lows
- River expansion or contraction
- H1 and H6 alignment or divergence
- Price movement structure within free intervals
- Supporting and opposing evidence for each scenario
- Scenarios and their invalidation conditions

AI outputs must reference the identifiers of their source data and events. Facts and interpretations must never be mixed.

## 10. Items Requiring Final Decisions

These items have intentionally been left open so that no assumptions are introduced into the implementation without agreement:

1. **Box ID:** The ordering and stability of Box identifiers in the Observer must be verified against its source code.
2. **Box Time Boundaries:** It must be determined whether start and end refer exactly to candle opening times or to the boundaries marking the end of an interval.
3. **Box Detection Time:** Any detection delay until the third candle is recorded through `detected_at`.
4. **MA Bifurcation:** The exact conditions for producing `up`/`down`/`unknown` must be extracted from the actual Observer. A simple comparison of two moving averages is not a substitute.
5. **River:** The Center and Width formulas and the Width unit must be specified and standardized across both timeframes.
6. **H1/H6 Windows:** Each series is constructed independently, based on its own most recently closed candle.
7. **History Retention:** The retention period for Boxes, ZigZag analyses, theories, and evaluations must be determined.
8. **Prediction Evaluation:** Success criteria, evaluation horizons, and scoring rules must be finalized before implementing the final ranking system.
9. **Conversation ID:** It must be determined how a conversation is created based on symbol, account, or strategy, and when a new conversation begins.

## 11. Implementation Sequence

Implementation will be incremental, with no more than four specific changes in each iteration:

1. Fully inspect the existing paths in `app/main.py` and the SQLite state without changing behavior.
2. Finalize the JSON contract and response structure.
3. Add SQLite migrations and tables.
4. Implement transactional and idempotent ingestion.
5. Implement Full Sync and independent section states.
6. Implement Delta and Full Resync requests.
7. Update the Collector to handle closed H1/H6 candles and per-candle information.
8. Update Box handling and temporal independence logic.
9. Store independent ZigZag analyses and preserve raw points.
10. Build the Debate Room and record theories and predictions.
11. Implement evaluation and end-to-end testing.

## 12. Current Code Status

Based on the version inspected from the branch:

- `app/main.py` contains the `/v1/mt5/ingest` endpoint, but it does not store market data in operational tables and currently records statistics only.
- `tests/log_a` is the current Sender and is outside the scope of changes in this proposal.
- `tests/log` is the current Collector.
- In the inspected version, H1 is constructed using 50 candles and starts from shift zero.
- The H6 construction path must also be corrected to exclude shift zero.
- The simple MA direction in `BuildDescription` is not, by itself, equivalent to the actual MA Bifurcation Observer.
- The current `BoxesOverlap` logic does not match the agreed temporal independence criteria.
- The current ZigZag lifecycle does not yet maintain an independent analysis history as defined in this proposal.

This document describes the target design. The JSON examples and table names do not imply that these features or tables already exist in the current code.

## 13. Acceptance Criteria for the First Version

- No shift-zero candle is stored or analyzed.
- Full Sync stores exactly the defined H1 and H6 windows.
- Duplicate messages do not create duplicate records.
- Delta stores only new information.
- Resynchronizing one section does not modify other valid sections.
- All Boxes are preserved, even if they are not independent.
- Box independence is confirmed only when at least one complete free H1 candle exists between the Boxes.
- Each free interval between two independent Boxes has its own independent ZigZag analysis.
- Raw points are not lost when the analysis result is unavailable.
- Theories, predictions, and evaluations are linked to their source data and creation timestamps.
- It must be possible to reconstruct exactly what information was available to an analyst at the moment a theory was issued.
