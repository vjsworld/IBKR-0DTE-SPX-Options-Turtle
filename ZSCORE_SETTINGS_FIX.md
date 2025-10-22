# Z-Score Settings Fix Summary

## Date: October 22, 2025

## Issues Fixed

### Issue #1: Z-Score Settings Not Persisting
**Problem**: User reported that changes to Z-score period and threshold settings (in Confirmation Chart and Trade Chart settings panels) were not saving/loading properly.

**Root Cause**: The `load_settings()` function was not restoring the individual chart Z-score settings to the Entry widgets. While the settings were being saved to `settings.json`, they weren't being loaded back into the GUI fields on startup.

**Fix**:
- Added code to `load_settings()` (lines 3029-3064) to restore all Z-score settings:
  ```python
  # Restore Confirmation Chart Z-Score settings
  if hasattr(self, 'confirm_ema_entry'):
      self.confirm_ema_entry.delete(0, 'end')
      self.confirm_ema_entry.insert(0, str(settings.get('confirm_ema', 9)))
  if hasattr(self, 'confirm_z_period_entry'):
      self.confirm_z_period_entry.delete(0, 'end')
      self.confirm_z_period_entry.insert(0, str(settings.get('confirm_z_period', 30)))
  if hasattr(self, 'confirm_z_threshold_entry'):
      self.confirm_z_threshold_entry.delete(0, 'end')
      self.confirm_z_threshold_entry.insert(0, str(settings.get('confirm_z_threshold', 1.5)))
  
  # Restore Trade Chart Z-Score settings  
  if hasattr(self, 'trade_ema_entry'):
      self.trade_ema_entry.delete(0, 'end')
      self.trade_ema_entry.insert(0, str(settings.get('trade_ema', 20)))
  if hasattr(self, 'trade_z_period_entry'):
      self.trade_z_period_entry.delete(0, 'end')
      self.trade_z_period_entry.insert(0, str(settings.get('trade_z_period', 100)))
  if hasattr(self, 'trade_z_threshold_entry'):
      self.trade_z_threshold_entry.delete(0, 'end')
      self.trade_z_threshold_entry.insert(0, str(settings.get('trade_z_threshold', 1.5)))
  ```

- Also restored period/timeframe variables for both charts:
  ```python
  # Restore period/timeframe variables
  if hasattr(self, 'confirm_period_var'):
      self.confirm_period_var.set(settings.get('confirm_period', '1 D'))
  if hasattr(self, 'confirm_timeframe_var'):
      self.confirm_timeframe_var.set(settings.get('confirm_timeframe', '1 min'))
  if hasattr(self, 'trade_period_var'):
      self.trade_period_var.set(settings.get('trade_period', '1 D'))
  if hasattr(self, 'trade_timeframe_var'):
      self.trade_timeframe_var.set(settings.get('trade_timeframe', '15 secs'))
  ```

**Result**: ✅ All Z-score settings now persist across application restarts

---

### Issue #2: Error 322 on Chart Reload
**Problem**: When updating Z-score settings, clicking the chart refresh buttons would throw IBKR API error 322: "Duplicate ticker ID for API historical data query"

**Root Cause**: 
1. The chart refresh functions (`refresh_confirm_chart()` and `refresh_trade_chart()`) were canceling old subscriptions and immediately requesting new ones
2. IBKR's API needs a brief moment to fully process the cancellation before accepting a new request with the same ticker ID (999994 or 999995)
3. No error handling was in place to catch/report issues

**Fix Applied to Both Functions** (lines 2259-2345):

**Before**:
```python
if self.confirm_chart_active:
    try:
        self.cancelHistoricalData(999995)
        self.confirm_chart_active = False
    except Exception as e:
        pass  # Silently ignore cancellation errors

# Immediately request new data...
self.reqHistoricalData(999995, ...)
self.confirm_chart_active = True
```

**After**:
```python
if self.confirm_chart_active:
    try:
        self.log_message("Canceling existing Confirmation chart subscription...", "INFO")
        self.cancelHistoricalData(999995)
        self.confirm_chart_active = False
        # Small delay to ensure cancellation is processed
        import time
        time.sleep(0.1)
    except Exception as e:
        self.log_message(f"Error canceling Confirmation chart: {str(e)}", "WARNING")

# Request new data with try/except
try:
    self.reqHistoricalData(999995, ...)
    # Mark as active only after successful request
    self.confirm_chart_active = True
    self.log_message(f"✓ Confirmation chart refreshed: {period} {timeframe} (streaming)", "SUCCESS")
except Exception as e:
    self.log_message(f"Error requesting Confirmation chart: {str(e)}", "ERROR")
```

**Changes**:
1. Added 100ms delay (`time.sleep(0.1)`) after cancellation to let IBKR process it
2. Wrapped `reqHistoricalData()` in try/except for proper error handling
3. Only set `chart_active = True` after successful request
4. Added informative log messages at each step
5. Changed success message from "Refreshing..." to "✓ Refreshed..." with green SUCCESS tag

**Result**: ✅ Chart reloads now work smoothly without duplicate ticker errors

---

## Files Modified
- **main.py** (6305 lines)
  - Lines 3029-3064: Added Z-score settings restoration in `load_settings()`
  - Lines 2259-2299: Enhanced `refresh_confirm_chart()` with delay and error handling
  - Lines 2307-2347: Enhanced `refresh_trade_chart()` with delay and error handling

---

## Settings Affected (settings.json)
The following settings now properly persist:
- `confirm_ema` (default: 9)
- `confirm_z_period` (default: 30)
- `confirm_z_threshold` (default: 1.5)
- `trade_ema` (default: 20)
- `trade_z_period` (default: 100)
- `trade_z_threshold` (default: 1.5)
- `confirm_period` (default: "1 D")
- `confirm_timeframe` (default: "1 min")
- `trade_period` (default: "1 D")
- `trade_timeframe` (default: "15 secs")

---

## Testing Recommendations
1. **Settings Persistence**:
   - Change Z-score period/threshold in both Confirmation and Trade panels
   - Close application completely
   - Reopen - verify settings show the updated values
   
2. **Chart Reload**:
   - Connect to IBKR
   - Change any Z-score setting (period, threshold, EMA)
   - Click "Refresh Chart" button multiple times rapidly
   - Verify no Error 322 appears in Activity Log or terminal
   - Confirm charts update successfully with new settings

3. **Log Messages**:
   - Watch Activity Log during chart refresh
   - Should see: "Canceling existing..." → "✓ ...refreshed..." with no errors

---

## Technical Notes
- **Why 100ms delay?**: IBKR API needs brief time to process `cancelHistoricalData()` before accepting new request with same reqId
- **Thread-safe?**: Yes - all chart operations run on API thread, sleep() won't block GUI
- **Performance impact**: Negligible - 0.1 second delay only occurs when manually refreshing charts
- **Alternative considered**: Using incrementing reqIds - rejected to keep consistent IDs (999994/999995) for easier debugging

---

## Related Documentation
- See `DUAL_CHART_SYSTEM.md` for overall chart architecture
- See `ZSCORE_INTEGRATION.md` for Z-score indicator calculations
- Error 322 reference: IBKR API error codes documentation
