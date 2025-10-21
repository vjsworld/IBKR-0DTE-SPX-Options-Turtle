# Greeks Calculation and Chart Loading Fix

## Issues Addressed

### Issue #1: Greeks Not Populating for Options Without Last Price
**Problem**: Options with zero or missing Last price showed dashes (—) for all greeks (Delta, Gamma, Theta, Vega, IV).

**Root Cause**: IBKR's MODEL_OPTION_COMPUTATION (tick type 13) with empty string parameter was not reliable for providing greeks on illiquid options.

**Solution**: Implemented self-calculated greeks using Black-Scholes model
- Added `calculate_greeks()` function using scipy.stats.norm
- Calculates greeks from bid/ask mid-point when IBKR data is missing
- Handles edge cases (zero time to expiry, missing IV, invalid strikes)
- Falls back to 20% implied volatility if not available from IBKR

### Issue #2: Chart Loading Spinner Getting Stuck
**Problem**: After clicking an option to view its chart, the loading spinner would sometimes show "Loading chart data..." indefinitely.

**Root Cause**: 
1. The `historicalDataEnd()` callback was checking for exact contract_key match including expiration date
2. String comparison was failing, preventing `hide_call_loading()` or `hide_put_loading()` from being called

**Solution**: Simplified contract matching logic
- Changed from exact string comparison to checking for `_C_` or `_P_` in contract_key
- Always hides loading spinner when historical data arrives for any call/put
- Maintains 30-second timeout as fallback safety mechanism

## Technical Implementation

### Black-Scholes Greeks Calculation

**Location**: `main.py` lines 52-145

**Function Signature**:
```python
def calculate_greeks(option_type: str, spot_price: float, strike: float, 
                     time_to_expiry: float, volatility: float, risk_free_rate: float = 0.05) -> dict
```

**Key Features**:
- Uses standard normal CDF (N(d1), N(d2)) and PDF (n(d1)) for Black-Scholes
- Returns delta, gamma, theta (per day), vega (per 1% IV change)
- Handles 0DTE edge cases where time_to_expiry approaches zero
- Minimum time_to_expiry clamped to 0.0001 years to avoid division by zero

**Integration Point**: `update_option_chain_display()` at lines 2257-2306
- Calculates time to expiry from `current_expiry` (YYYYMMDD format)
- Checks if delta is zero or missing for each option
- Computes greeks if bid/ask available and SPX price > 0
- Updates market_data dictionary in-place

### Chart Loading Fix

**Location**: `main.py` `historicalDataEnd()` callback at lines 498-537

**Changes**:
```python
# OLD: Strict comparison that could fail
if self.app.selected_call_contract and contract_key == f"SPX_{self.app.selected_call_contract.strike}_C_{self.app.current_expiry}":

# NEW: Simple substring check
is_call = '_C_' in contract_key
is_put = '_P_' in contract_key
if is_call and self.app.selected_call_contract:
```

**Benefits**:
- More robust matching regardless of strike format or expiration date variations
- Always hides spinner when data arrives, preventing indefinite "Loading..." state
- Reduced code complexity and improved maintainability

## Dependencies Added

**scipy>=1.11.0**: Required for `scipy.stats.norm` (normal distribution CDF/PDF)
- Already installed in environment (confirmed via pip)
- Added to `requirements.txt` for future deployments

## Testing Recommendations

1. **Greeks Validation**:
   - Connect to IBKR and load option chain
   - Look for options with bid/ask but no Last price (common on far OTM strikes)
   - Verify Delta, Gamma, Theta, Vega, IV all populate with non-zero values
   - Cross-check against other platforms (ThinkOrSwim, OptionStrat) for accuracy

2. **Chart Loading**:
   - Click on multiple call/put options rapidly
   - Verify loading spinner disappears within 1-2 seconds
   - Check Activity Log shows "Historical data complete" messages
   - Ensure 30-second timeout still works if IBKR doesn't respond

3. **Settings Persistence** (from previous commit):
   - Change chart dropdowns to non-default values (e.g., "5 days", "5 min")
   - Close and restart application
   - Verify dropdowns restore to previous values

## Known Limitations

1. **Implied Volatility Estimation**: If IBKR doesn't provide IV, we use 20% default
   - Could be improved with iterative Newton-Raphson to back-solve IV from option price
   - Current approach prioritizes speed over precision for live trading

2. **Risk-Free Rate**: Hardcoded to 5% (0.05)
   - Could pull from FRED API or treasury data for accuracy
   - Impact on greeks is minimal for 0DTE options

3. **0DTE Edge Cases**: Options at exact expiration (4:00 PM ET) treated as intrinsic value only
   - Delta becomes 0 or 1 (calls) / -1 or 0 (puts)
   - Other greeks zeroed out

## Files Modified

- `main.py`: Added greeks calculation, updated display logic, fixed chart callback
- `requirements.txt`: Added scipy>=1.11.0

## Git Commits

1. **c7ca717**: Fixed greeks population, chart settings persistence, and chart loading hang
2. **40de03c**: Implemented self-calculated greeks using Black-Scholes model and fixed chart loading

## Future Enhancements

1. **Implied Volatility Solver**: Implement Newton-Raphson to back-solve IV from option price
2. **Greeks Caching**: Cache calculated greeks for 1-2 seconds to reduce CPU load
3. **Dynamic Risk-Free Rate**: Pull current treasury yields from API
4. **Dividend Adjustment**: For equity options (non-index), incorporate dividend yield
5. **Bid-Ask Spread Alert**: Highlight options with wide spreads (> 10% of mid)
