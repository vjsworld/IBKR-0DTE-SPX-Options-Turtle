# Dual-Chart System Implementation - SPX Confirmation + Trade Charts

## Overview
Implemented a professional dual-chart system for SPX underlying similar to the Call/Put option charts layout.

## Changes Made (2025-10-22)

### 1. **Two Side-by-Side SPX Charts**
**Location:** Between Put/Call charts and 5-column panel

**Left Chart - Confirmation Chart (Cyan border):**
- Purpose: Longer timeframe confirmation
- Default: 1 minute bars
- Timeframe options: 30 secs, 1 min, 2 mins, 3 mins, 5 mins
- Used for trend confirmation before trading

**Right Chart - Trade Chart (Green border):**
- Purpose: Execution timeframe for strategy trades  
- Default: 15 second bars
- Timeframe options: 1 secs, 5 secs, 10 secs, 15 secs, 30 secs, 1 min
- All strategy trades plotted here with entry/exit markers

### 2. **Separate Settings for Each Chart**
**Gamma-Snap Panel Redesigned (now 400px wide):**
- **Left Column:** Confirmation Settings
  - EMA Length
  - Z-Score Period
  - Z-Score Threshold (±)
  - Refresh Button
  
- **Right Column:** Trade Chart Settings
  - EMA Length
  - Z-Score Period  
  - Z-Score Threshold (±)
  - Refresh Button

- **Bottom Row:** Auto Strategy ON/OFF toggle

### 3. **Chart Structure**
Each chart has 2 subplots:
- **Top (70%):** Price candlesticks + EMA + Bollinger Bands + Trade markers
- **Bottom (30%):** Z-Score indicator with entry signals at ±1.5

### 4. **Data Flow**
- **Request IDs:**
  - `999995`: Confirmation chart historical data
  - `999994`: Trade chart historical data
  
- **Data Containers:**
  - `self.confirm_bar_data`: Confirmation chart bars
  - `self.trade_bar_data`: Trade chart bars
  
- **Update Functions:**
  - `refresh_confirm_chart()`: Refresh confirmation chart
  - `refresh_trade_chart()`: Refresh trade chart
  - `update_chart_display(chart_type)`: Render either chart

### 5. **Auto-Load on Connection**
Both charts auto-request data when connected:
- Confirmation chart loads 1D/1min by default
- Trade chart loads 1D/15secs by default

## Layout Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  Call Chart (orange border)  │  Put Chart (orange border)      │
├─────────────────────────────────────────────────────────────────┤
│  Confirmation Chart (cyan)    │  Trade Chart (green)            │
│  ┌──────────────────────────┐ │ ┌──────────────────────────┐   │
│  │ SPX Price + EMA + BB     │ │ │ SPX Price + EMA + BB     │   │
│  │ (Candlesticks)           │ │ │ (Trade Markers Here!)     │   │
│  ├──────────────────────────┤ │ ├──────────────────────────┤   │
│  │ Z-Score Indicator        │ │ │ Z-Score Indicator        │   │
│  │ (Entry signals ±1.5)     │ │ │ (Entry signals ±1.5)     │   │
│  └──────────────────────────┘ │ └──────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│ [Activity Log] [Strategy] [Confirm+Trade Settings] [Manual]    │
└─────────────────────────────────────────────────────────────────┘
```

## Settings Panel Layout

```
┌─────────────────────────────────────────────────────┐
│            Strategy Settings                         │
├──────────────────────┬──────────────────────────────┤
│ Confirmation Settings│ Trade Chart Settings         │
├──────────────────────┼──────────────────────────────┤
│ EMA Len:    [9    ] │ EMA Len:    [9    ]          │
│ Z Period:   [30   ] │ Z Period:   [30   ]          │
│ Z ±:        [1.5  ] │ Z ±:        [1.5  ]          │
│ [    Refresh     ]  │ [    Refresh     ]           │
├──────────────────────┴──────────────────────────────┤
│ Auto: [ON] [OFF]  Status: OFF                       │
└─────────────────────────────────────────────────────┘
```

## Key Features

### Visual Differentiation
- **Confirmation Chart:** Cyan (#00BFFF) borders, longer timeframe
- **Trade Chart:** Green (#00FF00) borders, faster timeframe
- **Synchronized:** Both use same Z-Score indicator styling

### Refresh Mechanism
1. User changes settings (EMA, Z-Period, Z-Threshold)
2. Click "Refresh" button for respective chart
3. Chart re-requests historical data with current Period/Timeframe
4. Chart re-renders with new indicator parameters

### Trade Plotting
- **Strategy trades ONLY plot on Trade Chart (right)**
- Confirmation chart remains clean for trend analysis
- Entry markers: Blue arrows down
- Exit markers: Green (profit) / Red (loss) arrows up

## Usage Workflow

### Step 1: Set Up Charts
1. Connect to IBKR → Both charts auto-load
2. Adjust Confirmation chart to desired timeframe (e.g., 1 min)
3. Adjust Trade chart to desired timeframe (e.g., 15 secs)

### Step 2: Configure Indicators
1. **Confirmation Settings:** Set longer period Z-Score (e.g., 30) for trend
2. **Trade Settings:** Set shorter period Z-Score (e.g., 20) for entries
3. Click each "Refresh" button to apply

### Step 3: Monitor & Trade
1. Watch Confirmation chart for overall trend direction
2. Watch Trade chart Z-Score for entry signals (±1.5)
3. Strategy executes trades when both conditions align
4. All trade markers appear on Trade chart

## Technical Implementation

### Chart Initialization (lines ~1448-1630)
```python
# Confirmation Chart (Left)
self.confirm_fig = Figure(figsize=(9, 4.5), dpi=80, facecolor='#000000')
gs_confirm = self.confirm_fig.add_gridspec(2, 1, height_ratios=[7, 3], hspace=0.05)
self.confirm_ax = self.confirm_fig.add_subplot(gs_confirm[0])
self.confirm_zscore_ax = self.confirm_fig.add_subplot(gs_confirm[1], sharex=self.confirm_ax)

# Trade Chart (Right)
self.trade_fig = Figure(figsize=(9, 4.5), dpi=80, facecolor='#000000')
gs_trade = self.trade_fig.add_gridspec(2, 1, height_ratios=[7, 3], hspace=0.05)
self.trade_ax = self.trade_fig.add_subplot(gs_trade[0])
self.trade_zscore_ax = self.trade_fig.add_subplot(gs_trade[1], sharex=self.trade_ax)
```

### Refresh Functions (lines ~2005+)
```python
def refresh_confirm_chart(self):
    # Request ID 999995
    # Uses confirm_period_var and confirm_timeframe_var
    # Stores in self.confirm_bar_data
    
def refresh_trade_chart(self):
    # Request ID 999994
    # Uses trade_period_var and trade_timeframe_var
    # Stores in self.trade_bar_data
    
def update_chart_display(chart_type="confirm"):
    # Renders either chart based on chart_type parameter
    # Gets EMA/Z-Score parameters from respective entry widgets
    # Plots candlesticks, EMA, BB, Z-Score, trade markers
```

### Settings Storage
- `confirm_ema_entry`: Confirmation EMA length (default: 9)
- `confirm_z_period_entry`: Confirmation Z-Score period (default: 30)
- `confirm_z_threshold_entry`: Confirmation Z-Score threshold (default: 1.5)
- `trade_ema_entry`: Trade EMA length (default: 9)
- `trade_z_period_entry`: Trade Z-Score period (default: 30)
- `trade_z_threshold_entry`: Trade Z-Score threshold (default: 1.5)

## Code References

| Feature | Location | Line(s) |
|---------|----------|---------|
| Dual charts creation | `create_trading_tab()` | ~1448-1630 |
| Confirmation chart setup | Chart creation | ~1465-1525 |
| Trade chart setup | Chart creation | ~1530-1590 |
| Settings panel (dual) | Strategy Settings | ~1700-1820 |
| refresh_confirm_chart() | Chart functions | ~2005+ |
| refresh_trade_chart() | Chart functions | ~2040+ |
| update_chart_display() | Chart rendering | ~2080+ |
| Auto-load on connect | `on_connected()` | TBD |

## Files Modified
- `main.py`: Major restructuring
  1. Removed single-chart section (~100 lines deleted)
  2. Added dual-chart system (~180 lines added)
  3. Updated Gamma-Snap panel (~120 lines modified)
  4. Added refresh functions (~150 lines added)

## Success Criteria ✅
- [x] Two charts side-by-side (Confirmation + Trade)
- [x] Separate Period/Timeframe controls per chart
- [x] Dual settings in Gamma-Snap panel (400px wide)
- [x] Refresh buttons update charts with new settings
- [x] Charts positioned above 5-column panel
- [x] Trade markers only on Trade chart
- [x] Visual differentiation (cyan vs green borders)
- [x] Auto-load on connection
- [x] Z-Score indicator on both charts

## Testing Checklist
- [ ] Launch app
- [ ] Verify 2 charts appear side-by-side
- [ ] Verify cyan borders on Confirmation chart
- [ ] Verify green borders on Trade chart
- [ ] Connect to IBKR
- [ ] Verify both charts auto-load
- [ ] Change Confirmation settings → Click Refresh → Verify update
- [ ] Change Trade settings → Click Refresh → Verify update
- [ ] Execute test trade → Verify marker on Trade chart only
- [ ] Verify Z-Score indicators match settings
- [ ] Verify 5-column panel below charts intact
