# LLM Trading Consultation — Workflow

## 1. Architecture

Four components work together:

| Component | Responsibility |
|---|---|
| MT5 Expert | Market data, database tables, trade detection |
| Python Gateway | LLM orchestration, command execution, debate history |
| Cabin | User interface and conversation management |
| LLM | Market analysis, debate, and final opinions |

**Data ownership:** MT5 owns the permanent database tables. Python owns the temporary debate table.

## 2. Database Initialization

Cabin sends:

`LLM-TABLES-INIT`

MT5 Expert:
- Drops and recreates the permanent LLM-related tables.
- Creates empty tables.
- Does not insert any records.

This operation must not affect the existing H1, H6, and SmallBoxes market tables.

Permanent tables:

- `opinions`
- `trades`
- `opinion_trade`

## 3. Market Data Selection

Cabin starts an LLM consultation through Python.

The LLM can request market data at any point by issuing:

```json
{
  "command": "SELECT",
  "select": 20
}
```

Python retrieves the latest N records from each market table:

- H1
- H6
- SmallBoxes

The three datasets are returned to the LLM.

The LLM may issue SELECT repeatedly and change N during the conversation.

SELECT is temporary. It does not create a permanent record.

## 4. Debate Management

Python maintains a temporary SQLite table named `debate`.

- The table belongs to Python.
- It is cleared whenever a new debate starts.
- All user and LLM messages are recorded in sequence.
- The conversation history is provided to the LLM when processing subsequent messages.

### Debate Roles

The consultation follows three perspectives:

1. **Buyer:** Develops and explains the buy scenario, including entry, stop-loss, invalidation, and supporting evidence.
2. **Seller:** Develops and explains the sell scenario independently.
3. **Critic:** Challenges both arguments, identifies contradictions, and asks questions.

Buyer and Seller respond to the challenges. Multiple discussion rounds are allowed.

The LLM may request additional market data through SELECT throughout the debate.

## 5. Final Opinion Registration

The user decides when the debate is finished and asks the LLM to submit its final opinion(s).

The LLM uses:

`SAVE-OPINION`

Each opinion contains:

```json
{
  "opinion": "Market analysis and final reasoning...",
  "select": 20
}
```

Python adds the system-generated metadata and sends the record to MT5 for permanent storage.

The number of final opinions is unrestricted:

- Zero opinions
- One opinion
- Two opinions
- Three or more opinions

Each opinion receives its own unique `opinion_id`.

The permanent `opinions` table initially contains:

- `opinion_id`
- `created_at`
- `symbol`
- `timeframe`
- `candle_reference`
- `box_reference`
- `model`
- `opinion`
- `select`

Additional analytical fields can be introduced later when needed.

After the debate, its temporary history is cleared when the next debate starts.

## 6. Trade Tracking

On every Tick, the MT5 Expert executes a trade-monitoring method.

It identifies:
- Newly opened trades.
- Closed trades.

Trade identification uses trade tickets, not just changes in the number of open positions.

The Expert sends OPEN and CLOSE events to Python.

Python coordinates the corresponding database operations through the MT5 interface:

- New trades are inserted into `trades`.
- Closed trades update their existing records with closing information and results.

Trade monitoring and recording are automatic.

## 7. Opinion–Trade Relationship

Opinions and trades have a Many-to-Many relationship.

The junction table is:

`opinion_trade`

It connects:

- One opinion to multiple trades.
- One trade to multiple opinions.

Each relationship uses `opinion_id` and `trade_id`.

The exact rule for assigning opinions to trades must be defined separately. Associations must not be guessed from symbol or time alone.

## 8. Design Principles

1. MT5 owns all permanent market, opinion, and trade tables.
2. Python owns the temporary debate table.
3. Python coordinates communication between Cabin, the LLM, and MT5.
4. SELECT retrieves market data without saving an opinion.
5. Debate history is temporary.
6. Only final opinions are stored permanently.
7. The number of final opinions is unrestricted.
8. Trade tracking is automatic through the Expert.
9. Opinions and trades remain independent records connected through a junction table.
10. Keep the core database small. Add optional analytical and performance fields only when they become necessary.

## 9. Implementation Order

1. Finalize command and communication contracts.
2. Implement `LLM-TABLES-INIT` and permanent MT5 tables.
3. Implement Python debate management.
4. Implement dynamic SELECT handling.
5. Implement `SAVE-OPINION`.
6. Implement automatic trade event tracking.
7. Implement Opinion–Trade associations.
8. Add trade outcome analysis in a later phase.
