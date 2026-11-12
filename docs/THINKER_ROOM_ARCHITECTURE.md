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
- The
