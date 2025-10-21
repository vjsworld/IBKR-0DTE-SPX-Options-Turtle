# Order Placement Issues - RESOLVED ✅

## Date: October 21, 2025

## Problems Identified and Fixed

### 🔴 Critical Issue 1: Invalid Order Object Fields
**Problem**: TWS was silently rejecting orders due to toxic default values in the Order object.

**Root Cause**: The IBKR `Order()` class has problematic default values:
```python
auxPrice: 1.7976931348623157e+308  # Float max - invalid for LMT orders!
eTradeOnly: True                    # Wrong - should be False
firmQuoteOnly: True                 # Wrong - should be False
minQty: 2147483647                  # Int max - invalid!
```

**Fix Applied**:
```python
# Import UNSET constants
from ibapi.order import Order, UNSET_DOUBLE, UNSET_INTEGER

# Set proper values
order.eTradeOnly = False
order.firmQuoteOnly = False
order.auxPrice = UNSET_DOUBLE  # Use IBKR's UNSET constant
order.minQty = UNSET_INTEGER   # Use IBKR's UNSET constant
```

**Impact**: Orders now accepted by TWS! 🎉

---

### 🔴 Critical Issue 2: Wrong Expiration Date (0 DTE Bug)
**Problem**: When user selected "0 DTE", the app was creating options for tomorrow instead of today.

**Root Cause**: Logic error in `calculate_expiry_date()`:
```python
# WRONG: This would find one extra expiration
while expirations_found <= offset:
    # ... logic
```

**Fix Applied**:
```python
# CORRECT: Find exactly the Nth expiration
while True:
    if target_date.weekday() in expiry_days:
        if expirations_found == offset:
            return target_date.strftime("%Y%m%d")
        expirations_found += 1
    target_date += timedelta(days=1)
```

**Impact**: 0 DTE now correctly uses today's expiration (Oct 21 instead of Oct 22).

---

### 🟡 Issue 3: Filled Orders Not Removed from Grid
**Problem**: When an order filled, it remained visible in the Active Orders grid.

**Root Cause**: The `orderStatus()` callback wasn't calling the GUI update function.

**Fix Applied**:
```python
def orderStatus(self, orderId: int, status: str, ...):
    # Update order display in GUI
    self.app.update_order_in_tree(orderId, status, avgFillPrice)
    
    # If filled, also clean up tracking dicts
    if status == "Filled":
        # ... existing cleanup code
        # Also remove from manual_orders
        if orderId in self.app.manual_orders:
            del self.app.manual_orders[orderId]
```

**Impact**: Filled/cancelled orders now automatically removed from Active Orders grid.

---

## Diagnostic Systems Added

### 📁 File Logging System
**Location**: `logs/YYYY-MM-DD.txt`

**Features**:
- One log file per day
- All GUI messages also written to file
- Timestamped entries: `[2025-10-21 14:48:24] [LEVEL] message`
- Persistent across sessions

**Usage**: Check `logs/2025-10-21.txt` to analyze order placement issues.

### ✅ Contract Validation
Added pre-flight validation before placing orders:
- Checks all required contract fields
- Logs detailed contract and order object fields
- Validates field types and values

### ⏰ Callback Timeout Warnings
Added 3-second timeout warning if no callbacks received from TWS.

---

## Testing Results

### Before Fixes ❌
- placeOrder() API call successful
- No callbacks from TWS (silent rejection)
- Orders never appeared in TWS
- Wrong expiration date (Oct 22 instead of Oct 21)
- Filled orders stuck in Active Orders grid

### After Fixes ✅
- ✅ placeOrder() API call successful
- ✅ orderStatus() callback received
- ✅ openOrder() callback received
- ✅ Orders appear in TWS Order Management
- ✅ Correct expiration date (Oct 21 for 0 DTE)
- ✅ Filled orders automatically removed from grid
- ✅ Positions updated correctly
- ✅ Order fills successfully! 🎉

---

## Technical Details

### Contract Format (Working)
```python
symbol: SPX
secType: OPT
exchange: SMART
currency: USD
tradingClass: SPXW  # CRITICAL for SPX weeklies
strike: 6778.0
right: C
lastTradeDateOrContractMonth: 20251021  # Now correct!
multiplier: 100
```

### Order Format (Working)
```python
action: BUY
totalQuantity: 1
orderType: LMT
lmtPrice: 4.00
tif: DAY
transmit: True
account: DU5330979
eTradeOnly: False          # Fixed!
firmQuoteOnly: False       # Fixed!
auxPrice: UNSET_DOUBLE     # Fixed!
minQty: UNSET_INTEGER      # Fixed!
```

---

## Lessons Learned

1. **Always use file logging** - The log file revealed the toxic default values that were causing silent rejections.

2. **IBKR Order object has toxic defaults** - Never assume the default Order() object is safe to use as-is. Always set:
   - `eTradeOnly = False`
   - `firmQuoteOnly = False`
   - `auxPrice = UNSET_DOUBLE`
   - `minQty = UNSET_INTEGER`

3. **Off-by-one errors are sneaky** - The `<=` vs `<` in the expiration calculation caused 0 DTE to return the wrong date.

4. **GUI updates need explicit calls** - Don't assume GUI will update automatically on data changes. Must call update functions explicitly.

5. **Paper trading is your friend** - All these issues were caught in paper trading before risking real money.

---

## Files Modified

1. `main.py`:
   - Added logging import
   - Created `setup_file_logger()` function
   - Updated `log_message()` to write to file
   - Fixed `calculate_expiry_date()` logic
   - Fixed `place_order()` to set proper Order fields
   - Updated `orderStatus()` callback to remove filled orders
   - Added contract validation

2. `logs/` folder created for daily log files

3. Documentation:
   - `DEBUGGING_LOG_SYSTEM.md`
   - `ORDER_PLACEMENT_FIXES.md` (this file)

---

## Status: ✅ RESOLVED

All critical issues fixed. Orders now placing successfully to TWS!
