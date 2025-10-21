# SPX 0DTE Options Trading Application - AI Agent Instructions

## Project Overview
Bloomberg-style GUI application for automated 0DTE (Zero Days To Expiration) SPX options trading via Interactive Brokers API. Single-file Python architecture with multi-threaded design for non-blocking GUI + real-time market data streaming.

## Python Environment (CRITICAL!)

### Virtual Environment: `.venv`
**⚠️ ALWAYS use the virtual environment - NEVER install to root Python!**

- **Location**: `.venv/` folder in project root
- **Python Version**: 3.11
- **Activation**: 
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **Installing packages**: 
  ```powershell
  .\.venv\Scripts\python.exe -m pip install <package>
  # OR (if venv activated)
  pip install <package>
  ```

### Dependency Management Rules
1. **ALWAYS install to `.venv`**, not global Python
2. **Update `requirements.txt`** after adding new dependencies
3. **Test imports** in venv before committing:
   ```powershell
   .\.venv\Scripts\python.exe -c "import <module>; print('✓ Import successful')"
   ```
4. **VS Code Python interpreter** should point to `.venv\Scripts\python.exe`

### Current Dependencies
- `ibapi>=9.81.1`: Interactive Brokers API
- `ttkbootstrap>=1.10.1`: Modern tkinter theming
- `tksheet>=7.2.0`: Excel-like grid for option chain
- `pandas>=2.0.0`, `numpy>=1.24.0`: Data processing
- `scipy>=1.11.0`: Black-Scholes greeks calculations
- `matplotlib>=3.7.0`: Chart rendering

**Install all dependencies**: 
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Core Architecture

### Single-File Design Pattern
- **Everything in `main.py`**: 2,699 lines containing all classes, GUI, trading logic, and IBKR integration
- No modules/packages - optimize for vertical navigation within one file
- Section markers use `# ============` for major components, `# ========` for subsections

### Class Hierarchy (lines 47-335)
```
ConnectionState(Enum) → Connection state machine
IBKRWrapper(EWrapper) → Handles IBKR API callbacks (incoming data)
IBKRClient(EClient) → Manages IBKR API commands (outgoing requests)
SPXTradingApp(IBKRWrapper, IBKRClient) → Main app with multiple inheritance
```

### Threading Model (Critical!)
- **Main/GUI Thread**: Runs `tkinter` mainloop, updates UI via `root.after()` polling
- **Background/API Thread**: Runs `EClient.run()` message loop in separate thread
- **Communication**: Thread-safe `queue.Queue()` for inter-thread messaging (`gui_queue`, `api_queue`)
- **Never call GUI methods from API thread directly** - always queue updates and process in main thread

## Key Data Structures

### Contract Key Format
All options identified by standardized string: `"SPX_{strike}_{right}"` (e.g., `"SPX_5800.0_C"`)
- Used as dictionary keys throughout: `market_data`, `positions`, `historical_data`
- Generated in `create_spxw_contract()` and `IBKRWrapper` callbacks

### Critical State Dictionaries
- `market_data`: Live bid/ask/last/volume/greeks keyed by contract_key
- `market_data_map`: Maps IBKR reqId → contract_key for callback routing
- `positions`: Active positions with entry price, quantity, PnL
- `pending_orders`: Tracks orders between submission and fill (orderId → tuple)
- `historical_data_requests`: Maps reqId → contract_key for historical data callbacks

### Connection State Machine
```
DISCONNECTED → CONNECTING → CONNECTED
       ↑ (auto-retry)          ↓ (on error)
       └─────────────────────────┘
```
- Max 10 reconnection attempts with 5-second delays
- Client ID rotation (1-10) if ID conflicts occur
- Auto-reconnect on errors: 502, 503, 504, 1100, 2110

## SPXW Contract Specifications

### Trading Class: "SPXW"
- **Symbol**: "SPX" (NOT "SPXW" - `contract.symbol = "SPX"`)
- **TradingClass**: "SPXW" (`contract.tradingClass = "SPXW"`)
- **Exchange**: "SMART"
- **Currency**: "USD"
- **Multiplier**: "100"
- **SecType**: "OPT"

### Expiration Date Handling
- Format: "YYYYMMDD" (e.g., "20251020")
- Calculated by `calculate_expiry_date(offset)` - handles weekends/holidays
- Monday-Friday expirations for 0DTE
- User can switch expirations via dropdown (0 DTE, 1 DTE, etc.)

## Trading Strategy Implementation

### Manual Trading Mode (NEW - lines 2118-2430)
**Risk-based one-click trading with intelligent order management**

#### Entry System:
- **BUY CALL** button: Finds call option closest to max risk without exceeding
- **BUY PUT** button: Finds put option closest to max risk without exceeding  
- Max risk input: Dollar amount (e.g., $500 = $5.00 per contract, accounting for 100x multiplier)
- Scans entire loaded chain for optimal strike matching risk tolerance

#### Order Management (Mid-Price Chasing):
1. Initial order placed at mid-price (bid+ask)/2 with SPX rounding:
   - Prices ≥ $3.00: Round to $0.10 increments
   - Prices < $3.00: Round to $0.05 increments
2. Monitor every 1 second (`manual_order_update_interval`)
3. If mid-price moves ≥ $0.05 and order unfilled → cancel and replace at new mid
4. Continue chasing until filled or manually cancelled
5. Tracked in `manual_orders` dict with attempt counters and timestamps

#### Exit System:
- "[Close]" button in Positions grid Action column
- Clicks trigger `on_position_tree_click()` handler
- Exit orders use same mid-price chasing logic as entries
- Confirmation dialog shows current P&L before closing

#### Key Functions:
- `manual_buy_call()` / `manual_buy_put()`: Entry point handlers
- `find_option_by_max_risk()`: Scans chain for optimal strike
- `calculate_mid_price()`: Computes mid with proper rounding
- `round_to_spx_increment()`: Enforces CBOE SPX tick sizes
- `place_manual_order()`: Initiates order with tracking
- `update_manual_orders()`: Background monitoring loop

### Hourly Straddle Entry (`enter_straddle()` line 1918)
1. Triggered at top of hour by `schedule_hourly_trading()` checking `datetime.now().minute == 0`
2. Scans `market_data` for cheapest call/put with ask ≤ $0.50
3. Places limit orders at ask price for both legs
4. Tracks in `active_straddles` list with entry prices and timestamps

### Supertrend Indicator (`calculate_supertrend()` line 2042)
- Uses ATR (Average True Range) with configurable period (default: 14)
- Chandelier multiplier for trailing distance (default: 3.0)
- Calculates on 1-minute historical bars
- Returns directional signal and stop levels for exit logic

### Position Tracking
- Self-calculated PnL (not relying on IBKR's position updates)
- Real-time update via `tickPrice()` callback → `update_position_pnl()`
- Greeks streamed live via `tickOptionComputation()` callback

## GUI Architecture (ttkbootstrap)

### Theme: "darkly" with IBKR TWS Color Matching
- **Background**: Pure black (#000000) to match TWS
- **ITM Options**: Subtle green (#001a00 calls) / red (#1a0000 puts) tints
- **OTM Options**: Pure black (#000000) with dimmed text (#808080)
- **Text**: Green (#00ff00) for gains, Red (#ff0000) for losses

### Main Components
- **Tab 1 (Trading)**: Option chain treeview, positions, orders, Supertrend chart, activity log
- **Tab 2 (Settings)**: Connection params, strategy params, save functionality
- **Status Bar**: Connection status, SPX price display, connect/disconnect buttons

### Option Chain Treeview Layout
Mirrors IBKR TWS layout with calls on left, strike centered, puts on right:
```
C_Bid | C_Ask | C_Last | ... | STRIKE | ... | P_Last | P_Ask | P_Bid
```
- Real-time updates every 500ms via `update_option_chain_display()`
- Click handler for manual trading: `on_option_chain_click()`

## Settings Persistence
- **File**: `settings.json` (auto-created on first save)
- **Fields**: host, port, client_id, atr_period, chandelier_multiplier, strikes_above/below
- **Load**: Automatic on startup via `load_settings()` in `__init__`
- **Save**: Manual via Settings tab or auto-save on reconnect

## Development Workflows

### Running the Application
**ALWAYS use the virtual environment:**
```powershell
# Option 1: Direct execution with venv python
.\.venv\Scripts\python.exe main.py

# Option 2: Activate venv first, then run
.\.venv\Scripts\Activate.ps1
python main.py
```
No build step - direct execution. Requires TWS/IB Gateway running and configured.

### Installing New Dependencies
**CRITICAL: Never use global Python - always use `.venv`!**
```powershell
# Install package in venv
.\.venv\Scripts\python.exe -m pip install <package>

# Update requirements.txt
.\.venv\Scripts\python.exe -m pip freeze > requirements.txt

# Verify installation
.\.venv\Scripts\python.exe -c "import <module>; print('✓ Installed in venv')"
```

### Testing Requirements
1. **IBKR Setup**: TWS or IB Gateway must be running on specified port
2. **Paper Trading**: Always use port 7497 for testing (7496 is live)
3. **Market Data Subscriptions**: Requires SPX + SPXW data subscriptions
4. **Market Hours**: 9:30 AM - 4:00 PM ET for full functionality

### Common Development Tasks

**Adding New Market Data Fields:**
1. Update `market_data` dict initialization (line ~1500s)
2. Add column to option chain treeview setup (line ~640)
3. Update `update_option_chain_display()` to populate new column
4. Add callback handling in `IBKRWrapper.tickPrice/tickSize/tickOptionComputation`

**Modifying Trading Logic:**
- Entry logic: `enter_straddle()` (line 1851)
- Exit logic: `calculate_supertrend()` + position monitoring loops
- Risk management: Check `active_straddles` tracking and PnL calculations

**Connection Issues:**
- Review `ConnectionState` enum and state transitions
- Check `error()` callback for error code handling (line 63)
- Verify client ID rotation logic (line 86-93)

## IBKR API Quirks & Gotchas

### Request ID Management
- Start at 1000: `next_req_id = 1000` (line 370)
- Auto-increment for each market data or historical data request
- Must track mapping: `reqId → contract_key` in `market_data_map`

### Market Data Subscriptions
- Each option requires separate `reqMktData()` call
- Subscriptions persist until `cancelMktData()` called
- Reconnection requires re-subscribing to ALL contracts (tracked in `subscribed_contracts`)

### Error Code Reference (from `error()` callback)
- **326**: Client ID in use → rotate to next ID
- **502/503/504**: Connection errors → trigger reconnect
- **1100/2110**: Network disconnection → trigger reconnect
- **354**: Market data not subscribed → warning only
- **162/165/321**: Historical data permission issues (common in paper trading)

### Historical Data Limitations
- Paper trading accounts have restricted historical data access
- Requests may fail with error 162 - handle gracefully with fallback logic
- Always check `if reqId in historical_data_requests` before processing

## Code Style & Patterns

### Logging Convention
Use `log_message(msg, level)` with levels: "ERROR", "WARNING", "SUCCESS", "INFO"
- Separator bars: `"=" * 60` for major events
- Detailed trade logging with strike, prices, deltas

### Error Handling Pattern
```python
if self.connection_state != ConnectionState.CONNECTED:
    self.log_message("Cannot perform action: Not connected", "WARNING")
    return
```
Always check connection state before IBKR API calls.

### GUI Updates from Background Thread
```python
# WRONG: Direct GUI update from API thread
self.position_tree.insert(...)

# CORRECT: Queue update for main thread
self.gui_queue.put(("update_position", contract_key, data))
# Then process in main thread via root.after() polling
```

## Virtual Environment Setup (IMPORTANT!)

### First-Time Setup
If cloning the repository for the first time:
```powershell
# Create virtual environment
python -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# Install all dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Troubleshooting Import Errors
If VS Code shows import errors (red squiggles):
1. **Check Python interpreter**: Press `Ctrl+Shift+P` → "Python: Select Interpreter" → Choose `.venv\Scripts\python.exe`
2. **Verify package installed in venv**:
   ```powershell
   .\.venv\Scripts\python.exe -m pip list
   ```
3. **Reinstall if missing**:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install <package>
   ```
4. **Restart language server**: Press `Ctrl+Shift+P` → "Python: Restart Language Server"

### Common Mistakes to Avoid
- ❌ **DON'T**: Run `pip install <package>` without activating venv (installs to global Python)
- ❌ **DON'T**: Use `python` command directly (might use wrong interpreter)
- ✅ **DO**: Always use `.\.venv\Scripts\python.exe -m pip install <package>`
- ✅ **DO**: Verify installation location with `pip show <package>`

## Critical Constraints
- **Windows-primary**: Paths and shell commands assume Windows (PowerShell)
- **Real-money risk**: Always test with paper trading first (port 7497)
- **Market hours dependency**: Most functionality requires active market hours
- **Single-file philosophy**: Keep all code in `main.py` - avoid splitting into modules
