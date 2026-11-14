# MT5–Python–SQLite
## Implementation Plan and Warm-up Protocol

## 1. Project Objective

Build a reliable, sequential communication system between MetaTrader 5 (MT5) and Python, with Python acting as the SQLite database manager for MT5.

Development must proceed in independent, verifiable stages. Communication reliability must be established before implementing the complete MT5 application logic.

---

# Part I — Implementation Order

## Phase 1 — Python SQLite Command Interpreter

The first implementation task is to build a command interpreter in Python.

This interpreter receives predefined commands, validates their parameters, executes the corresponding SQLite operations, and returns structured responses.

MT5 must never send arbitrary SQL statements.

### 1.1 Original SQLite Commands

The following eight commands are defined in the existing integration roadmap.

| Command | Function | Description |
|---|---|---|
| `MAKE` | Make Table | Create a table. If it exists, drop and recreate it. |
| `INSR` | Insert Row | Insert a new record. |
| `SELA` | Select All | Retrieve records, subject to a configurable limit. |
| `SELR` | Select Range | Retrieve records matching validated conditions or ranges. |
| `LAST` | Select Last | Retrieve the latest N records. |
| `DELR` | Delete Row | Delete the latest record. |
| `CLER` | Clear Table | Delete all records while preserving the table structure. |
| `DROP` | Drop Table | Delete an entire table. |

### 1.2 Additional Database Discovery Commands

Four additional commands are introduced to support database discovery and initialization decisions.

| Command | Function | Description |
|---|---|---|
| `READ-STAT` | Read Status | Read Python's current operational status. |
| `READ-DATA` | Read Data | Retrieve existing database data. |
| `LIST-TABL` | List Tables | Return the available SQLite table names. |
| `INIT-DATA` | Initialize Data | Initialize the required database data. |

These commands complement the original eight commands. They do not replace them.

### 1.3 Interpreter Requirements

The Python interpreter must:

- Recognize all twelve commands.
- Validate command parameters.
- Validate table and column identifiers.
- Use parameterized SQL for values.
- Reject arbitrary SQL supplied by MT5.
- Return a consistent response structure.
- Report execution errors explicitly.
- Support safe repeated execution where applicable.

**Deliverable:** A working Python SQLite command interpreter that can be tested independently of MT5.

---

## Phase 2 — Reliable Request and Response Delivery

After the SQLite interpreter is ready, the reliable communication infrastructure must be completed.

The system consists of:

- MetaTrader 5
- WinHTTP DLL
- Laravel Gateway
- Python Gateway

### 2.1 Request Identity

MT5 owns request identity.

Every logical request must have a unique and persistent `request_id`.

Before sending a request, MT5 must persist:

- Request ID
- Request payload
- Creation timestamp
- Delivery status

A retry must always reuse the original request ID.

### 2.2 Python Request Tracking

Python must persist every received request.

The tracking record must contain:

- `request_id`
- `payload`
- `command_type`
- `status`
- `response`
- `created_at`
- `completed_at`
- `acknowledged_at`

The request lifecycle is:

`pending → completed / failed → acknowledged`

### 2.3 Response Persistence

Every response must be associated with its original request ID.

Responses must remain available until MT5 successfully consumes and acknowledges them.

### 2.4 Retry and Recovery

A timeout does not prove that a request was not executed.

If communication fails:

1. MT5 retains the original request.
2. MT5 checks for an existing response using the original request ID.
3. If a response exists, MT5 retrieves it.
4. Otherwise, MT5 retries the original request using the same ID.

Python must prevent duplicate execution.

### 2.5 Acknowledgment

MT5 sends ACK after successfully consuming the expected response.

Python records the acknowledgment persistently.

Repeated ACK operations must be safe and idempotent.

MT5 removes a request from its unresolved request storage only after successful ACK confirmation.

### 2.6 Sequential Processing

Only one unresolved application request is allowed at a time.

The next request must not begin normal processing until the previous request reaches its required completion state.

**Deliverable:** A persistent and recoverable request/response infrastructure.

---

## Phase 3 — MT5 Communication Test Using MAKE

After reliable delivery is implemented, a minimal MT5 test program will be created.

The first communication test will use the `MAKE` command.

### 3.1 Test Sequence

1. MT5 generates a unique request ID.
2. MT5 stores the request locally.
3. MT5 sends a `MAKE` request.
4. Python receives and registers the request.
5. Python executes the command.
6. Python stores the response with the original request ID.
7. MT5 retrieves the response.
8. MT5 verifies the request ID and result.
9. MT5 sends ACK.
10. Python confirms the acknowledgment.

### 3.2 Reliability Testing

The test must be repeated under different conditions:

- Normal communication
- Request timeout
- Lost response
- Repeated request
- Python restart
- MT5 restart
- Lost ACK
- Repeated ACK
- Temporary network interruption

The purpose is to establish confidence in both communication and request identity.

The `MAKE` test must be considered reliable before proceeding.

**Deliverable:** A verified MT5-to-Python request/response cycle.

---

## Phase 4 — Complete the MT5 Application

Only after the previous phases are verified should the complete MT5 application be implemented.

The application will include:

1. MA and River initialization.
2. Independent MA Bifurcation warm-up.
3. Python status discovery.
4. SQLite table discovery.
5. Database data inspection.
6. Initialization when necessary.
7. Normal market-data synchronization.
8. Continuous reliable communication.

The warm-up procedure is defined in Part II.

---

# Part II — MT5 MA Bifurcation Warm-up Protocol

## 2.1 Purpose

The `CMABifurcation` class maintains an internal computational state based on sequential price inputs.

After an MT5 restart, this in-memory state must be reconstructed.

MT5 must therefore reset and warm up its Bifurcation instances using its own available market history.

This process is completely independent of Python and SQLite.

**MT5 must never depend on the Python database to reconstruct its internal Bifurcation calculations.**

## 2.2 Required Historical Data

Two independent Bifurcation instances are used.

| Instance | Required Closed Candles |
|---|---:|
| H1 | 100 |
| H6 | 20 |

These counts are fixed warm-up requirements.

They are independent of the number of candles sent to SQLite during database initialization.

## 2.3 Initialization Order

During EA startup:

1. Initialize the Moving Average objects.
2. Configure the River observers.
3. Reset the H1 Bifurcation instance.
4. Reset the H6 Bifurcation instance.
5. Clear the EA-side direction-history counters and indexes.
6. Retrieve 100 closed H1 candles.
7. Feed the H1 candles chronologically.
8. Retrieve 20 closed H6 candles.
9. Feed the H6 candles chronologically.
10. Confirm that both warm-up operations completed successfully.

The corresponding reset operations are:

`mabif_h1.Reset()`

`mabif_h6.Reset()`

## 2.4 Chronological Feed

MetaTrader time-series arrays use the following indexing convention:

- Index `0` represents the newest candle.
- Larger indexes represent older candles.

Therefore, historical candles must be processed from the largest index toward index `0`.

The feed must proceed from the oldest candle to the newest candle.

Only closed candles may be used.

The currently forming candle must not be included.

Every candle must be fed exactly once.

## 2.5 Feed Must Be Independent of JSON

Bifurcation feeding must be separated from JSON construction.

The Feed operation is responsible for:

1. Receiving candle information.
2. Updating the corresponding River observer.
3. Obtaining the River center price.
4. Calling `AddPoint()` on the corresponding Bifurcation instance.
5. Recording the resulting direction for later use.

JSON construction is responsible only for reading previously calculated information.

JSON functions must never update River or Bifurcation state.

## 2.6 Runtime Feeding

After successful warm-up, normal operation continues.

Whenever a new candle closes:

1. Detect the new closed candle.
2. Check that it has not already been fed.
3. Update the corresponding River observer.
4. Obtain its center price.
5. Feed the price into the corresponding Bifurcation instance.
6. Store the calculated direction.
7. Make the candle available for JSON construction.

Duplicate processing must never feed the same candle twice.

## 2.7 Independent H1 and H6 Streams

H1 and H6 are independent computational streams.

Each stream has:

- Its own historical data.
- Its own warm-up count.
- Its own River observer.
- Its own Bifurcation instance.
- Its own direction history.
- Its own readiness state.

## 2.8 Warm-up Readiness

The EA may enter normal operation only when:

- Exactly 100 closed H1 candles have been successfully fed.
- Exactly 20 closed H6 candles have been successfully fed.
- All corresponding River updates have succeeded.
- All Bifurcation updates have succeeded.

If the required history is unavailable or incomplete, the EA must not declare itself ready.

Normal database initialization and normal market-data transmission must not start before successful warm-up.

## 2.9 Python and SQLite Discovery After Warm-up

After successful warm-up, MT5 checks the Python database environment.

The discovery sequence is:

1. `READ-STAT` — Read Python's current status.
2. `LIST-TABL` — Discover available tables.
3. `READ-DATA` — Inspect the required existing records.
4. Decide whether initialization is necessary.
5. If required, execute `INIT-DATA` and the appropriate database commands.

If valid data already exists, MT5 must not unnecessarily resend the entire initial dataset.

If the required tables or records are missing or invalid, initialization or recovery must be performed.

Python's database is the authority for persisted records.

MT5's own market history is the authority for its current market-data and computational warm-up.

These responsibilities must remain separate.

---

# Part III — Final Startup Sequence

The complete MT5 startup sequence is:

1. Initialize Moving Averages.
2. Configure River observers.
3. Reset both Bifurcation instances.
4. Warm up H1 using 100 closed candles.
5. Warm up H6 using 20 closed candles.
6. Confirm computational readiness.
7. Read Python status using `READ-STAT`.
8. Discover tables using `LIST-TABL`.
9. Inspect existing records using `READ-DATA`.
10. Initialize database data only when necessary.
11. Enter normal operation.

---

# Part IV — Core Development Rules

1. Implement and verify one phase at a time.
2. Do not skip the Python command interpreter.
3. Do not begin full MT5 implementation before communication reliability is verified.
4. Preserve request IDs across retries.
5. Keep application-level delivery logic outside the DLL.
6. Do not allow arbitrary SQL from MT5.
7. Keep request processing sequential.
8. Keep Bifurcation feeding independent of JSON construction.
9. Feed each closed candle exactly once.
10. Never use SQLite to reconstruct MT5's internal Bifurcation state.
11. Never trigger destructive database operations merely because of a communication timeout.
12. Require actual test evidence before declaring a phase complete.

## Final Principle

**First build the Python SQLite interpreter. Then establish reliable delivery. Next verify MT5 communication with MAKE. Finally complete the MT5 application, beginning with independent H1/H6 Bifurcation warm-up.**

Every phase must be independently testable and verified before the next phase begins.
