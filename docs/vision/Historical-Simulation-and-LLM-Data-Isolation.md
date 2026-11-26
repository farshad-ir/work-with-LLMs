# Historical Simulation and LLM Data Isolation

## 1. Objective

The system uses historical market data starting from 2023 to train and evaluate Cabin's trading consultation workflow.

The LLM must analyze historical charts as if it were operating in a live market environment, without knowing the actual calendar date or subsequent market events.

The goal is to minimize historical knowledge bias and look-ahead bias.

## 2. Hide Calendar Time from the LLM

Python must not expose actual candle dates or timestamps to the LLM.

The LLM receives stable candle IDs and the market data required for analysis.

- Candle IDs remain unchanged.
- Actual timestamps remain in the MT5 database.
- The LLM uses IDs to identify and reference candles.

## 3. SmallBox ID References

SmallBoxes currently use `startTime` and `endTime` to identify their boundaries.

Two additional columns will be introduced:

| Column | Purpose |
|---|---|
| `start_id` | ID of the candle corresponding to the box start |
| `end_id` | ID of the candle corresponding to the box end |

These IDs directly reference the existing, stable candle IDs.

No temporary ID mapping is required.

When Python handles a SELECT request:

1. It retrieves the requested SmallBox records.
2. It includes `start_id` and `end_id`.
3. It excludes actual start and end timestamps.
4. It sends the records to the LLM.

The LLM can understand chronological relationships through stable IDs without seeing calendar dates.

## 4. Historical Simulation Trades

Since real trades cannot be opened retroactively on the 2023 historical chart, a separate table is required for simulated trades.

Proposed table:

`simulated_trades`

Initial fields:

| Field | Purpose |
|---|---|
| `ticket` | Simulated trade identifier |
| `open_price` | Simulated opening price |

These records represent historical or emulated open positions for Cabin training.

They must remain separate from real trades in the `trades` table.

The simulated trade table is populated by the existing MT5 simulation method.

## 5. Simulation and Bias Prevention Rules

1. The LLM must not receive actual calendar timestamps.
2. Candle IDs must remain stable.
3. SmallBox references must use stable candle IDs.
4. Python must return only data available up to the current simulation reference point.
5. Future candles and subsequent market events must never be included in a consultation.
6. Simulated trades must not be confused with real trades.
7. The LLM should be instructed to behave as if it were analyzing a live market.

Suggested LLM instruction:

> Treat this as a live market simulation. Analyze only the market data explicitly provided to you. Do not use historical market knowledge, future events, subsequent price movements, or external information.

## 6. Design Principle

The LLM receives market structure and chronological relationships, but not calendar dates.

MT5 retains the original timestamps and permanent IDs.

Python controls the data exposed to the LLM.

Simulated trades remain separate from real trading records.
