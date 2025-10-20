# SPX 0DTE Options Trading Application - AI Coding Guide

## Project Overview
This is a professional Bloomberg-style options trading application for SPX 0DTE (Zero Days To Expiration) options using Interactive Brokers API. The entire application is contained in a single `main.py` file (~2700 lines) with a multi-threaded architecture.

## Architecture & Core Components

### Single-File Design
- **Everything in `main.py`**: All classes, GUI, trading logic, and API handlers in one file
- **Class Hierarchy**: `SPXTradingApp(IBKRWrapper, IBKRClient)` - inherits from both IBKR wrapper and client
- **Threading Model**: GUI thread (tkinter) + Background API thread (IBKR EClient.run())
- **Communication**: Thread-safe queues for inter-thread messaging

### Key Classes & Patterns
```python
# Main application inherits from both IBKR classes
class SPXTradingApp(IBKRWrapper, IBKRClient):
    # Connection state machine
    ConnectionState.DISCONNECTED → CONNECTING → CONNECTED
    
    # Market data structure
    self.market_data[contract_key] = {
        'contract': contract, 'right': 'C'/'P', 'strike': float,
        'bid': float, 'ask': float, 'last': float, 'volume': int,
        'delta': float, 'gamma': float, 'theta': float, 'vega': float
    }
```

### IBKR API Integration Specifics
- **Client ID Auto-Increment**: Automatically tries client IDs 1-10 if one is in use (error 326)
- **SPX Contract Creation**: Uses `tradingClass = "SPXW"` for SPX weekly options
- **Manual Option Chain**: Creates strikes dynamically around SPX price (no IBKR chain request)
- **Real-time Data**: Subscribes to market data for all strikes, updates GUI every 500ms

## Trading Strategy Implementation

### Hourly Straddle Entry
- **Trigger**: `now.minute == 0 and now.second == 0` (top of every hour)
- **Selection Logic**: Find cheapest call/put with `ask <= $0.50`
- **Order Placement**: Limit orders at ask price for both legs

### Option Chain Generation
```python
# Around current SPX price, every 5 points
center_strike = round(self.spx_price / 5) * 5
strikes = range(center_strike - (strikes_below * 5), 
               center_strike + (strikes_above * 5), 5)
```

### Risk Management Components
- **Supertrend Indicator**: ATR-based trend following for exits
- **Pyramiding**: Scale into profitable positions on doubling moves
- **Position Tracking**: Self-calculated PnL using `(current_price - avg_cost) * position * 100`

## GUI Architecture (Bloomberg-Style)

### Color Scheme (IBKR TWS Theme)
- **ITM Options**: Dark green/red backgrounds for in-the-money options
- **OTM Options**: Pure black backgrounds for out-of-the-money options
- **ATM Options**: Dark gray for at-the-money strikes
- **Text Colors**: Bright green/red for gains/losses, gray for neutral values

### Treeview Layout (IBKR Style)
- **Calls Left**: Bid, Ask, Last, Volume, Gamma, Vega, Theta, Delta, IV
- **Center**: Strike (bold, centered)
- **Puts Right**: Delta, Theta, Vega, Gamma, Volume, Last, Ask, Bid

### Chart Integration
- **Dual Charts**: Call chart (left) + Put chart (right)
- **Click Selection**: Click option chain row to load candlestick chart
- **Historical Data**: Requests via `reqHistoricalData()` with contract-specific settings

## Critical Development Patterns

### Connection Management
```python
# Auto-reconnection with backoff
self.reconnect_attempts < self.max_reconnect_attempts (10)
self.reconnect_delay = 5  # seconds between attempts

# Connection state updates
def on_connected(self):
    self.subscribe_spx_price()      # SPX underlying
    self.request_option_chain()     # Build strikes around SPX
    self.subscribe_market_data()    # All option contracts
```

### Error Handling Specifics
- **Error 326** (Client ID in use): Auto-increment client ID and retry
- **Error 502/503/504**: Connection issues trigger reconnection
- **Historical Data Errors**: Paper trading accounts have limited access

### Data Request IDs
```python
# Request ID management pattern
self.next_req_id = 1000  # Start high to avoid conflicts
req_id = self.next_req_id
self.next_req_id += 1
self.reqMktData(req_id, contract, "", False, False, [])
```

## Development Workflows

### Setup & Testing
```bash
# Virtual environment setup
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# IBKR Connection Required
# Paper Trading: port 7497, Live: port 7496
python main.py
```

### Key Configuration Points
- **`settings.json`**: Connection params, strategy settings (auto-created)
- **TWS/Gateway Setup**: Enable API, socket clients, port configuration
- **Market Data**: Requires SPX + SPXW subscriptions

### Debugging Patterns
- **Activity Log**: Color-coded by severity in GUI text widget
- **Connection State**: Monitor `ConnectionState` enum in status bar
- **Request Tracking**: Each API request gets unique ID for debugging

## Common Modifications

### Adding New Option Strategies
1. Modify `check_trade_time()` for different triggers
2. Update `enter_straddle()` selection logic
3. Add position tracking in `update_position_on_fill()`

### UI Customization
- **Color Scheme**: Modify ttkbootstrap style configurations in `setup_gui()`
- **Chart Settings**: Update `draw_candlestick_chart()` for different indicators
- **Layout Changes**: Edit `create_trading_tab()` frame structure

### Performance Optimization
- **Chart Debouncing**: Uses 100ms debounce delay for responsiveness
- **Market Data Updates**: 500ms GUI update cycle
- **Memory Management**: Auto-truncates logs at 1000 lines

## Integration Points & Dependencies

### External Services
- **Interactive Brokers API**: Core dependency via `ibapi` package
- **Market Data**: Real-time quotes require active IBKR subscriptions
- **Historical Data**: Limited availability in paper trading accounts

### Critical Files
- **`main.py`**: Entire application (modify with caution)
- **`settings.json`**: User preferences (auto-generated)
- **`requirements.txt`**: Python dependencies

This is a single-file application optimized for rapid development and professional trading use. When modifying, always test with paper trading first and maintain the existing threading model.