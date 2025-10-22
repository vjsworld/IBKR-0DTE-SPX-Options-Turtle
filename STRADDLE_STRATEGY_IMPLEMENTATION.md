# Straddle Strategy Implementation

**Date**: October 22, 2025  
**Status**: ✅ Complete

## Overview
Converted the old hard-coded "hourly straddle entry" into a fully configurable **Straddle Strategy** with its own dedicated panel in the Master Settings row. The strategy now operates independently from the Gamma-Trap Z-Score strategy and uses the same Master Settings for delta targeting and position sizing.

---

## 🎯 Key Changes

### 1. **New Straddle Strategy Panel** (Column 5)
Added a dedicated panel between Master Settings and Manual Mode with:

- **ON/OFF Toggle Buttons**: Independent enable/disable control
- **Frequency Input**: Configurable entry interval (default: 60 minutes)
- **Status Display**: Shows "ACTIVE" (green) or "INACTIVE" (red)
- **Countdown Timer**: Displays next entry time (e.g., "Next: 14:45")
- **Info Text**: Clarifies use of Master Settings for delta and position sizing

**Location**: Lines ~2006-2076 (GUI construction)

### 2. **Strategy Settings**
Added new configuration variables:

```python
# In __init__ (lines ~926-929)
self.straddle_enabled = False  # Independent on/off switch
self.straddle_frequency_minutes = 60  # Configurable interval
self.last_straddle_time = None  # Timestamp tracking
```

### 3. **Settings Persistence**
Updated `save_settings()`, `auto_save_settings()`, and `load_settings()`:

**Saved Fields**:
- `straddle_enabled`: Boolean on/off state
- `straddle_frequency_minutes`: Integer interval (minutes)

**Location**: 
- Lines ~2862-2867 (save_settings)
- Lines ~2943-2945 (auto_save_settings)
- Lines ~3002-3004 (load_settings)

### 4. **Strategy Control Functions**

#### `update_straddle_button_states()`
- Updates visual appearance of ON/OFF buttons
- Changes status label color and text
- **Location**: Lines ~3077-3091

#### `set_straddle_enabled(enabled: bool)`
- Enables/disables the straddle strategy
- Logs configuration details (frequency, delta, position sizing mode)
- Resets timer (`last_straddle_time = None`)
- Auto-saves settings
- **Location**: Lines ~3093-3130

### 5. **Timing & Entry Logic**

#### `check_trade_time()` - **COMPLETELY REWRITTEN**
**Old Behavior**:
- Hard-coded hourly check (minute == 0, second == 0)
- Used `last_trade_hour` to prevent duplicate entries

**New Behavior**:
- Only checks if `straddle_enabled == True`
- First entry: Immediate on activation
- Subsequent entries: Based on `straddle_frequency_minutes`
- Calculates elapsed time since `last_straddle_time`
- Updates countdown display every second
- **Location**: Lines ~3909-3945

**Example**:
```
Frequency: 30 minutes
Last entry: 14:00
Current time: 14:15
Display: "Next: 14:30"
```

#### `enter_straddle()` - **COMPLETELY REWRITTEN**
**Old Behavior**:
- Scanned for cheapest options with ask ≤ $0.50
- Fixed quantity of 1 contract each
- Used ask price directly (no mid-price chasing)

**New Behavior**:
- Emulates clicking "BUY CALL" and "BUY PUT" buttons
- Calls `manual_buy_call()` and `manual_buy_put()` directly
- Uses **Master Settings** for all parameters:
  - Target Delta (e.g., 30)
  - Position Size Mode (Fixed Qty or Calc by Risk)
  - Max Risk (if calculated mode)
  - Trade Qty (if fixed mode)
- Mid-price chasing enabled automatically
- **Location**: Lines ~3947-3978

**Key Code**:
```python
self.log_message("Entering CALL leg...", "INFO")
self.manual_buy_call()

self.root.after(500, lambda: self.log_message("Entering PUT leg...", "INFO"))
self.root.after(1000, self.manual_buy_put)
```

---

## 📊 User Workflow

### Scenario 1: Fixed Quantity Straddle
1. Set **Master Settings**:
   - Target Delta: 30
   - Position Size Mode: "Fixed Qty"
   - Trade Qty: 5
2. Enable **Straddle Strategy**:
   - Click "ON" button
   - Set Frequency: 30 minutes
3. **Result**: Every 30 minutes, buys 5 contracts each of:
   - Call option nearest 30 delta
   - Put option nearest 30 delta
   - Both at mid-price with aggressive chasing

### Scenario 2: Risk-Based Straddle
1. Set **Master Settings**:
   - Target Delta: 30
   - Max Risk: $1000
   - Position Size Mode: "Calc by Risk"
2. Enable **Straddle Strategy**:
   - Click "ON" button
   - Set Frequency: 60 minutes
3. **Result**: Every 60 minutes, calculates position size:
   - Finds call/put near 30 delta
   - Call @ $2.50 → Quantity = 1000/2.50 = 400 contracts
   - Put @ $2.30 → Quantity = 1000/2.30 = 434 contracts

---

## 🔧 Technical Details

### Shared Master Settings
All three trading modes now use identical parameters:

| Setting | Manual Mode | Gamma-Trap | Straddle Strategy |
|---------|-------------|------------|-------------------|
| Target Delta | ✅ | ❌ (uses Z-Score) | ✅ |
| Max Risk | ✅ | ✅ | ✅ |
| Trade Qty | ✅ | ✅ | ✅ |
| Position Size Mode | ✅ | ✅ | ✅ |

### Timer Precision
- **Check Interval**: 1000ms (1 second)
- **Countdown Update**: Real-time display
- **Entry Accuracy**: ±1 second of configured frequency

### Entry Delay
Small delay between call and put legs to prevent overwhelming the API:
```python
self.manual_buy_call()  # Immediate
# 500ms delay
self.log_message("Entering PUT leg...", "INFO")
# 1000ms delay
self.manual_buy_put()
```

---

## 🗑️ Removed Code

### Deleted Old Straddle Logic (~60 lines)
- Removed cheapest option scanning (ask ≤ $0.50 logic)
- Removed fixed quantity=1 placement
- Removed separate straddle tracking in `active_straddles`
- Removed hourly-only trigger (minute == 0, second == 0)
- Removed `last_trade_hour` usage in straddle context

**Location**: Lines ~3988-4048 (old version)

---

## 📝 Logging Examples

### Enabling Strategy
```
============================================================
✓ STRADDLE STRATEGY ENABLED
  Frequency: Every 30 minutes
  Uses Master Settings:
    Target Delta: 30
    Position Size: 5 contracts (Fixed)
============================================================
```

### Entry Trigger
```
============================================================
🔔 STRADDLE STRATEGY ENTRY TRIGGERED 🔔
============================================================
Entering CALL leg...
MANUAL BUY CALL INITIATED - Target Delta: 30.0
Contract found: SPX_5800.0_C_20251022
Delta: 31.2 (Target: 30)
Position sizing: Fixed quantity = 5 contracts
Manual CALL order #12345 submitted: 5 contracts @ $2.45
Entering PUT leg...
MANUAL BUY PUT INITIATED - Target Delta: 30.0
Contract found: SPX_5790.0_P_20251022
Delta: 29.8 (Target: 30)
Position sizing: Fixed quantity = 5 contracts
Manual PUT order #12346 submitted: 5 contracts @ $2.35
============================================================
```

---

## ✅ Testing Checklist

- [x] Straddle panel displays correctly in bottom row
- [x] ON/OFF buttons toggle state
- [x] Frequency input validates and saves
- [x] Countdown timer updates every second
- [x] First entry triggers immediately on enable
- [x] Subsequent entries respect configured frequency
- [x] Uses Master Settings (delta, position size)
- [x] Calls `manual_buy_call()` and `manual_buy_put()`
- [x] Settings persist across restarts
- [x] No conflicts with Gamma-Trap strategy
- [x] No conflicts with Manual Mode

---

## 🎨 UI Layout
```
┌─────────────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│   Confirm   │    Trade     │  Call Chart  │   Put Chart  │   Master     │  Straddle    │
│   Chart     │    Chart     │   Settings   │   Settings   │  Settings    │  Strategy    │
│  Settings   │   Settings   │              │              │              │              │
├─────────────┼──────────────┼──────────────┼──────────────┼──────────────┼──────────────┤
│             │              │              │              │  Target Δ:   │ Straddle:    │
│             │              │              │              │  Max Risk:   │ [ON] [OFF]   │
│             │              │              │              │  Trade Qty:  │              │
│             │              │              │              │  Pos. Size:  │ Frequency:   │
│             │              │              │              │  ( ) Fixed   │ [60] min     │
│             │              │              │              │  ( ) Calc    │              │
│             │              │              │              │              │ Uses Master  │
│             │              │              │              │              │ Settings     │
│             │              │              │              │              │ Next: 14:30  │
└─────────────┴──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
│                                  Manual Mode                                            │
│                              [BUY CALL] [BUY PUT]                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📚 Related Documentation
- `MASTER_SETTINGS_REDESIGN.md` - Delta-based trading and position sizing
- `STRATEGY_MID_PRICE_CHASING.md` - Order chasing logic
- `AGGRESSIVE_ORDER_CHASING.md` - Time-based concessions

---

## 🚀 Future Enhancements (Not Implemented)
- [ ] Maximum straddles per day limit
- [ ] Profit target for auto-exit of straddles
- [ ] Separate delta targets for calls vs puts
- [ ] Volatility-based frequency adjustment
- [ ] Time-of-day restrictions (e.g., only 9:30-15:00)
