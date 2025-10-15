# SPX 0DTE Options Trading Application

A professional Bloomberg-style trading application for SPX 0DTE options trading using Interactive Brokers API.

## Features

- **Professional Dark-Themed GUI**: Bloomberg-style interface with ttkbootstrap
- **Real-Time Option Chain**: Live streaming quotes for all 0DTE SPX options
- **Automated Hourly Trading**: Enters long straddles at the top of every hour
- **Advanced Risk Management**: 
  - Pyramiding (scaling in on profitable moves)
  - Adaptive trailing stops using Supertrend indicator
- **Real-Time PnL Tracking**: Self-calculated positions and PnL
- **Live Charts**: Matplotlib integration for Supertrend visualization
- **Robust Connection Management**: Auto-reconnection with finite state machine
- **Multi-Threaded Architecture**: Non-blocking GUI with dedicated API thread

## Requirements

- Python 3.8+
- Interactive Brokers TWS or IB Gateway (Paper Trading recommended)
- Active IB account with market data subscriptions

## Installation

1. **Clone the repository**:
```bash
git clone https://github.com/vjsworld/IBKR-Options-Turtle.git
cd IBKR-Options-Turtle
```

2. **Create and activate virtual environment**:
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Setup

### Interactive Brokers Setup

1. **Download and install TWS or IB Gateway**:
   - [Download TWS](https://www.interactivebrokers.com/en/index.php?f=16040)
   - [Download IB Gateway](https://www.interactivebrokers.com/en/index.php?f=16457)

2. **Configure API Settings**:
   - Open TWS/IB Gateway
   - Go to: File → Global Configuration → API → Settings
   - Enable "Enable ActiveX and Socket Clients"
   - Set Socket Port: `7497` (Paper Trading) or `7496` (Live)
   - Uncheck "Read-Only API"
   - Add `127.0.0.1` to "Trusted IP Addresses"

3. **Market Data Subscriptions**:
   - Ensure you have subscriptions for:
     - US Securities Snapshot and Futures Value Bundle (required for SPX)
     - CBOE Options (required for SPXW)

### Application Configuration

The application uses default settings that can be modified in the Settings tab:

- **Host**: `127.0.0.1` (localhost)
- **Port**: `7497` (Paper Trading) / `7496` (Live Trading)
- **Client ID**: `101`
- **ATR Period**: `14` (for Supertrend calculation)
- **Chandelier Exit Multiplier**: `3.0`

Settings are saved to `settings.json` and persisted between sessions.

## Usage

### Starting the Application

```bash
python main.py
```

### Connecting to IBKR

1. Ensure TWS/IB Gateway is running and logged in
2. Click the "Connect" button in the status bar
3. Wait for connection confirmation
4. Option chain will automatically load

### Trading Dashboard (Tab 1)

- **Option Chain**: Real-time quotes for all 0DTE SPX options
  - Displays: Type, Strike, Bid, Ask, Last, Volume, Delta, Gamma, Theta, Vega
  - Updates every 500ms
  
- **Open Positions**: Shows all current positions
  - Real-time PnL calculation
  - Position size and average cost
  - Percentage gain/loss

- **Active Orders**: Displays pending orders
  - Order ID, contract, action, quantity, status
  - Auto-removes filled/cancelled orders

- **Supertrend Chart**: Matplotlib chart showing:
  - 1-minute price bars
  - Supertrend indicator
  - Long/short zones

- **Activity Log**: Timestamped event log
  - Color-coded by severity (ERROR, WARNING, SUCCESS, INFO)
  - Connection status, trades, fills, errors

### Settings (Tab 2)

- **Connection Settings**: Modify host, port, client ID
- **Strategy Parameters**: Adjust ATR period and Chandelier multiplier
- **Save & Reconnect**: Apply settings and reconnect
- **Save Settings**: Save without reconnecting

### Trading Strategy

#### Hourly Straddle Entry
- **Trigger**: Top of every hour (minute == 0, second == 0)
- **Selection Criteria**: 
  - Find call and put with Ask ≤ $0.50
  - Select cheapest option for each leg
- **Order Type**: Limit orders at Ask price

#### Pyramiding (Scaling In)
- Only adds to profitable positions
- Triggers on full doubling moves in SPX price
- Adds one additional contract per trigger

#### Supertrend Exit
- Calculates Supertrend on 1-minute bars
- Exit signal: Price crosses below Supertrend
- Automatic exit order placement

## Architecture

### Threading Model
- **Main/GUI Thread**: Runs tkinter mainloop, handles UI updates
- **Background/API Thread**: Runs IBKR API message loop (EClient.run())
- **Communication**: Thread-safe queues for inter-thread messaging

### Connection State Machine
```
DISCONNECTED → CONNECTING → CONNECTED
        ↑                        ↓
        └────── (on error) ──────┘
```
- Max 5 reconnection attempts
- 5-second delay between attempts
- Manual reconnect after max attempts

### Data Flow
1. IBKR API → `IBKRWrapper` callbacks
2. Wrapper → Updates internal data structures
3. GUI thread polls data via `root.after()`
4. Treeviews and charts updated every 500ms-1s

## File Structure

```
IBKR-0DTE-SPX-Options-Turtle/
├── main.py               # Main application (single file)
├── requirements.txt      # Python dependencies
├── README.md             # This file
├── LICENSE               # MIT License
├── settings.json         # User settings (created on first save)
└── .venv/               # Virtual environment
```

## Risk Warnings

⚠️ **IMPORTANT DISCLAIMERS**:

1. **Use Paper Trading First**: Always test with paper trading before live trading
2. **Options Risk**: Options can expire worthless. Never trade with money you can't afford to lose
3. **0DTE Risk**: Zero Days To Expiration options are extremely volatile
4. **Market Data Costs**: Ensure you have proper market data subscriptions
5. **No Guarantees**: Past performance does not guarantee future results
6. **Educational Purpose**: This software is for educational purposes only

## Troubleshooting

### Connection Issues
- Verify TWS/IB Gateway is running
- Check API settings are enabled
- Confirm correct port (7497 for paper, 7496 for live)
- Check firewall settings

### Market Data Issues
- Verify market data subscriptions are active
- Check subscription includes SPX and SPXW
- Ensure market is open (9:30 AM - 4:00 PM ET)

### Order Placement Issues
- Verify account permissions allow option trading
- Check buying power is sufficient
- Ensure orders comply with option trading rules

## Support

For issues, questions, or contributions:
- GitHub Issues: [https://github.com/vjsworld/IBKR-Options-Turtle/issues](https://github.com/vjsworld/IBKR-Options-Turtle/issues)
- Pull Requests Welcome

## License

MIT License - See LICENSE file for details

## Acknowledgments

- Interactive Brokers API documentation
- ttkbootstrap for the modern GUI framework
- The quantitative finance community

---

**Developed by VJS World** | October 2025
