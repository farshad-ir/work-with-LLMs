# MT5 Market Data Collector

### Sequential H1/H6 Market Data Collection and Delivery System

## 1. Overview

The MT5 Market Data Collector is an Expert Advisor designed to collect structured market information from MetaTrader 5 and deliver it to the Python AI infrastructure.

The collector processes two independent timeframes:

- H1 — 1-hour timeframe
- H6 — 6-hour timeframe

For each closed candle, it collects standard OHLC market data and combines it with information calculated by the River and Bifurcation components.

The resulting data is converted into JSON and transferred through the existing communication infrastructure.

The collector is designed to provide reliable, sequential, and structured market data for subsequent AI analysis.

## 2. System Architecture

The collector uses the existing communication architecture:

**MetaTrader 5 Expert Advisor → egg.dll → Laravel → Python AI Gateway**

Each component has a specific responsibility:

| Component | Responsibility |
|---|---|
| MT5 Expert Advisor | Market data collection and indicator processing |
| egg.dll | Communication bridge |
| Laravel | Existing backend receiving and forwarding infrastructure |
| Python AI Gateway | Data ingestion and subsequent AI infrastructure |

The Expert Advisor does not communicate directly with Python.

It uses the existing DLL and Laravel communication path.

## 3. Supported Timeframes

The collector maintains two independent processing pipelines.

| Property | H1 | H6 |
|---|---:|---:|
| Timeframe | 1 Hour | 6 Hours |
| Moving Average periods | 7, 14 | 42, 84 |
| River instance | H1_river | H6_river |
| Bifurcation instance | mabif_h1 | mabif_h6 |
| History capacity | 100 | 20 |

The two pipelines maintain separate indicator states, Bifurcation engines, and historical records.

No H1 calculation is used as the internal state of the H6 engine, and vice versa.

## 4. Market Data Structure

For each closed candle, the collector prepares the following information:

| Field | Description |
|---|---|
| symbol | Trading instrument |
| timeframe | H1 or H6 |
| time | Candle opening timestamp |
| open | Opening price |
| high | Highest price |
| low | Lowest price |
| close | Closing price |
| tick_volume | Tick volume |
| spread_points | Spread in points |
| river_center | River center price |
| river_width_pips | River width in pips |
| ma_bifurcation.direction | Bifurcation direction |

The Bifurcation direction can have three values:

- UP
- DOWN
- UNKNOWN

The collector reports the calculated River Center and Width rather than transmitting the individual moving average values.

## 5. River Processing

Each timeframe has its own River instance.

The moving average configurations are:

- H1: periods 7 and 14
- H6: periods 42 and 84

The River component provides two important values:

**River Center:** The central price level calculated by the River component.

**River Width:** The width of the River structure, expressed in pips.

These values provide additional market context alongside the candle's OHLC data.

## 6. Bifurcation Processing

The collector uses two independent CMABifurcation instances:

- mabif_h1
- mabif_h6

The Bifurcation engine is stateful and processes input points sequentially.

Consequently, each closed candle must be passed to its corresponding engine exactly once.

The collector follows this rule:

1. Check whether the candle timestamp already exists in the corresponding history.
2. If the candle has already been processed, do not feed it again.
3. If it is new, update the corresponding River.
4. Pass the River Center to the Bifurcation engine.
5. Store the resulting direction together with the candle timestamp.

This prevents repeated processing from changing the internal state of the Bifurcation engine.

## 7. Bifurcation History and FIFO

The collector maintains two independent circular history buffers.

| Buffer | Capacity |
|---|---:|
| H1 History | 100 records |
| H6 History | 20 records |

Each record contains:

- candleTime
- direction

The history buffers use FIFO behavior.

When a buffer reaches its maximum capacity, new records replace the oldest records.

The stored records allow the collector to retrieve previously calculated Bifurcation results without feeding the engine again.

The history lookup is based on candle timestamps.

If a required record cannot be found, the collector reports an error instead of generating an artificial direction.

## 8. Initial History Synchronization

During initialization, the Expert Advisor executes BootstrapHistory().

The bootstrap process retrieves closed candles from MetaTrader 5:

- 100 closed H1 candles
- 20 closed H6 candles

The current open candle is excluded.

Both histories are processed from oldest to newest.

For each candle:

1. The corresponding River is updated.
2. The Bifurcation engine receives the River Center.
3. The direction is stored in the corresponding FIFO.
4. The candle information is prepared and sent to the backend.

The bootstrap process is considered successful only when the requested history is available for both timeframes.

After successful processing, the collector records the opening time of the current H1 and H6 candles.

This establishes the reference points for detecting future closed candles.

## 9. New Candle Detection

After initialization, the Expert Advisor monitors the market through OnTick().

Two independent functions are executed:

- CheckNewH1Candle()
- CheckNewH6Candle()

Each function compares the current candle opening time with the previously recorded value.

When a new candle is detected:

1. The previously active candle is now considered closed.
2. The latest closed candle is retrieved.
3. The corresponding moving average and River data are updated.
4. The candle is fed to its Bifurcation engine exactly once.
5. The result is saved in the corresponding FIFO.
6. The completed candle data is sent to the backend.

H1 and H6 are monitored independently.

## 10. JSON Serialization

BuildCandleJson() converts the collected information into a JSON payload.

Each payload contains:

- Symbol
- Timeframe
- Candle timestamp
- OHLC values
- Tick volume
- Spread
- River Center
- River Width
- Bifurcation direction

The current payload represents one candle.

This allows the backend to receive individual market events with explicit timeframe and timestamp information.

## 11. Communication and Delivery

The collector uses the existing DLL interface.

The JSON payload is written to:

`LLM-LQ/mt5_feed.json`

The file is opened using the MT5 FILE_COMMON mechanism.

After writing and closing the file, the Expert Advisor calls:

`SendLatestJson()`

The DLL handles the existing communication process.

The response is subsequently read using:

`PollResponses()`

The response parser checks the success field and reports communication statistics, including:

- Requests
- Bytes
- Characters
- Words

The collector also reports the result returned by SendLatestJson().

## 12. Logging and Diagnostics

The Expert Advisor provides diagnostic messages for the main processing stages.

| Log Prefix | Purpose |
|---|---|
| [BOOTSTRAP] | Initial history synchronization |
| [H1 FEED] | H1 Bifurcation input processing |
| [H6 FEED] | H6 Bifurcation input processing |
| [H1] | H1 candle processing results |
| [H6] | H6 candle processing results |
| [COLLECTOR] | Candle delivery |
| [SENDER] | Communication and response statistics |
| [INIT] | Initialization status |
| [STOP] | Expert Advisor shutdown |

These logs help diagnose history synchronization, sequential processing, and communication behavior.

## 13. Responsibilities and Limitations

The Market Data Collector is responsible for collecting, calculating, structuring, and delivering market information.

It does not perform trading decisions.

Specifically, it does not:

- Generate buy or sell signals.
- Predict future market prices.
- Open or close trades.
- Determine position sizes.
- Manage trading risk.
- Conduct AI-based market interpretation.

Its responsibility ends with delivering structured market information to the backend.

The Python infrastructure and subsequent AI components are responsible for processing and interpreting the received information.

## 14. Operational Considerations

Several design constraints are important for correct operation.

**Sequential Bifurcation Processing**

Each closed candle must enter its corresponding Bifurcation engine exactly once.

**Independent Timeframes**

H1 and H6 must maintain separate calculation states and histories.

**Timestamp-Based Identification**

Candle timestamps are used to prevent duplicate Bifurcation processing.

**Missing History Records**

If a Bifurcation record is unavailable, the collector reports an error rather than inventing a result.

**Restart Behavior**

The history buffers are runtime memory structures. After restarting the Expert Advisor, the Bootstrap process reconstructs the available history and Bifurcation states from the configured historical window.

Therefore, the reconstructed state is based on the available 100 H1 and 20 H6 candles.

## 15. Future Development Direction

The Market Data Collector is intended to serve as the market-data acquisition layer of a larger AI-assisted trading research architecture.

Future components may use its structured output to:

- Build richer market context.
- Compare evidence from different timeframes.
- Maintain historical market observations.
- Provide structured evidence for AI analysis.
- Support multi-model discussions and analysis.
- Evaluate competing bullish and bearish scenarios.

The collector itself remains focused on accurate and consistent market-data delivery.

---

**Component:** MT5 Market Data Collector  
**Platform:** MetaTrader 5  
**Communication:** egg.dll → Laravel → Python  
**Timeframes:** H1 and H6  
**Processing Model:** Sequential, timestamp-based, independent timeframe pipelines  
**Primary Purpose:** Structured market data acquisition for AI infrastructure
