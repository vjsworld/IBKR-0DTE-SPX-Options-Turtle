# Chart Refresh Error 162 Fix

## Date: October 22, 2025

## Issue: False Error Messages on Chart Refresh

### Problem
When clicking the "Refresh Chart" button after changing Z-score settings, users would see alarming red ERROR messages in the Activity Log:

```
[ERROR] 🚨 [ORDER ERROR] Order #999995, Code=162, Msg=Historical Market Data Service error message:API historical data query cancelled: 999995
[ERROR] Error 162: Historical Market Data Service error message:API historical data query cancelled: 999995
[WARNING] Historical data permission issue for reqId 999995: Historical Market Data Service error message:API historical data query cancelled: 999995
```

### Root Cause
When refreshing a chart:
1. The code cancels the existing historical data subscription: `self.cancelHistoricalData(999995)`
2. IBKR API sends back error code 162 to confirm the cancellation
3. Our error handler was logging this as an ERROR, even though it's expected behavior
4. The message "API historical data query cancelled" is IBKR's way of saying "OK, I cancelled it as you requested"

This is NOT an actual error - it's IBKR acknowledging our intentional cancellation.

### Fix Applied
Updated the error handler (line 351-355) to suppress error 162 when it's a chart cancellation:

```python
# Historical data errors
elif errorCode == 162:  # Historical market data Service error
    # Check if this is a chart cancellation (expected when refreshing charts)
    if reqId in [999994, 999995] and "cancelled" in errorString.lower():
        # This is expected when we cancel a chart subscription - ignore it
        return
    
    # ... rest of error 162 handling for actual errors
```

### Logic
- Check if the reqId is 999994 (Trade Chart) or 999995 (Confirmation Chart)
- Check if the error message contains "cancelled"
- If both conditions are true → suppress the error (return early)
- Otherwise → log it as a real error

### Chart Request IDs
- **999994**: Trade Chart (bottom right panel)
- **999995**: Confirmation Chart (bottom left panel)
- **999996**: SPX underlying 1-min chart
- **999997**: VIX for Z-Score calculations
- **999998**: VIX price subscription

### Result
✅ Chart refresh now works silently without alarming error messages  
✅ Real historical data errors (permissions, network issues) still logged properly  
✅ Cleaner Activity Log experience

### Testing
1. Connect to IBKR
2. Change any Z-score setting (period, threshold, EMA)
3. Click "Refresh Chart" button
4. **Before**: Red ERROR messages appear
5. **After**: Clean refresh with only success messages

### Files Modified
- **main.py** (line 351-355): Added suppression for chart cancellation errors

---

## Technical Notes

### Why Error 162 Happens
IBKR's API design pattern for modifying real-time subscriptions:
1. Client cancels existing subscription
2. Server acknowledges with error code 162 + "cancelled" message
3. Client requests new subscription with updated parameters

This is **expected behavior**, not an error condition.

### Similar Patterns in IBKR API
Other IBKR error codes that are actually "informational acknowledgments":
- **2104/2106**: Market data connection OK (we already handle these)
- **2158**: Security definition server OK (we already handle these)
- **162 + "cancelled"**: Historical data cancelled (NOW handled by this fix)

### Why Not Suppress All 162 Errors?
Error 162 can also indicate real problems:
- No market data subscription for the requested instrument
- Historical data permissions issue (common in paper trading)
- Network/connectivity problems

By checking for "cancelled" in the message, we only suppress the intentional cancellations while still catching real errors.

---

## Related Documentation
- See `ZSCORE_SETTINGS_FIX.md` for the original chart refresh implementation
- See `DUAL_CHART_SYSTEM.md` for overall chart architecture
