# CBOE SPX Options Trading Reference

**Source**: [Interactive Brokers CBOE Trading Page](https://www.interactivebrokers.com/en/trading/cboe.php)  
**Date**: October 22, 2025  
**Application**: SPX 0DTE Options Trading

---

## 🕒 Trading Hours (Eastern Time)

### Standard Trading Hours (Regular Session)
**8:30 AM - 3:15 PM ET** (Monday - Friday)

### Global Trading Hours (GTH) - Extended Session
**8:15 PM - 9:15 AM ET** (Nearly 24/5 trading)

**Important Notes**:
- GTH available for SPX, SPXW (SPX Weeklys), and XSP
- Trading hours determined by Chicago time zone
- Daylight Saving Time (DST) affects times for international traders
- GTH allows trading reaction to global market events outside regular hours

### Time Zone Reference (Regular Session)

| Location | GTH Hours | Regular Session |
|----------|-----------|-----------------|
| **Chicago** | 7:15 PM - 8:25 AM | 8:30 AM - 3:15 PM |
| **London*** | 1:15 AM - 2:25 PM | 2:30 PM - 9:15 PM |
| **Hong Kong/Singapore*** | 9:15 AM - 10:25 PM | 10:30 PM - 5:15 AM |
| **Sydney*** | 12:15 AM - 1:25 PM | 1:30 AM - 8:15 AM |

*Times shown may shift by one hour when U.S. changes DST

---

## 📊 Product Comparison: SPX Suite

| Feature | SPX | SPXW | XSP (Mini) | NANOS |
|---------|-----|------|------------|-------|
| **Ticker Symbol** | SPX | SPXW | XSP | NANOS |
| **Contract Multiplier** | $100 | $100 | $100 | $1 |
| **Approx. Notional** (@ 4100) | $410,000 | $410,000 | $41,000 | $410 |
| **ATM Premium Example** (2-day) | $3,000 | $3,000 | $300 | $3 |
| **Settlement Type** | Cash (no physical delivery) | Cash | Cash | Cash |
| **Settlement Time** | **A.M.** | **P.M.** | **P.M.** | **P.M.** |
| **Expiration Schedule** | 3rd Friday | Every Trading Day + End-of-Month | Mon/Tue/Wed/Thu/Fri + 3rd Fri + EOM | Mon/Wed/Fri |
| **Exercise Style** | European (no early assignment) | European | European | European |
| **Tax Treatment** | 60% long-term / 40% short-term | Same | Same | Same |
| **Global Trading Hours** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No |

---

## 💰 Commission Structure

| Product | Commission Range* | Notes |
|---------|-------------------|-------|
| **SPX** | $0.70 - $2.51 per contract | All-in pricing |
| **XSP** | $0.31 - $0.60 per contract | All-in pricing |
| **NANOS** | $0.12 - $0.13 per contract | All-in pricing |

*Depends on monthly traded volume and other factors

[View Full Options Commissions](https://www.interactivebrokers.com/en/pricing/commissions-options.php)

---

## 🎯 Key Product Features

### SPX (Standard S&P 500 Index Options)
- **Best For**: High net-worth traders, institutional accounts
- **Notional Size**: ~$410,000 (at SPX 4100)
- **Settlement**: **A.M. Settlement** (settled before market open)
- **Expiration**: 3rd Friday of month
- **Use Case**: Large hedging positions, professional traders

### SPXW (SPX Weeklys)
- **Best For**: Short-term traders, 0DTE strategies
- **Notional Size**: Same as SPX (~$410,000)
- **Settlement**: **P.M. Settlement** (settled at market close)
- **Expiration**: **Every Trading Day** + End-of-Month
- **Use Case**: Daily expirations, intraday trading, 0DTE strategies
- **Trading Class**: "SPXW" in IBKR API

### XSP (Mini S&P 500 Index Options)
- **Best For**: Retail traders, smaller accounts, precise position sizing
- **Notional Size**: 1/10th of SPX (~$41,000)
- **Settlement**: P.M. Settlement
- **Expiration**: Mon/Tue/Wed/Thu/Fri + 3rd Friday + End-of-Month
- **Use Case**: Flexible position sizing, lower capital requirements
- **Trading Class**: "XSP" in IBKR API

### NANOS
- **Best For**: Very small accounts, learning/testing
- **Notional Size**: 1/100th of XSP (~$410)
- **Multiplier**: $1 (vs $100 for others)
- **Settlement**: P.M. Settlement
- **Expiration**: Mon/Wed/Fri only
- **Use Case**: Minimal capital risk, beginner-friendly

---

## 🔑 Critical Trading Characteristics

### 1. Cash Settlement
- **No Physical Delivery**: All contracts settled in cash
- **No Assignment Risk**: European-style (no early exercise)
- **Account Impact**: Cash credited/debited automatically on settlement

### 2. European Exercise Style
- **Cannot be exercised early**: Only at expiration
- **No early assignment risk**: Unlike equity options (American-style)
- **Simplifies risk management**: Position can only change on expiration

### 3. Tax Treatment (Section 1256)
- **60% Long-Term / 40% Short-Term**: Regardless of holding period
- **Applies to**: SPX, SPXW, XSP, NANOS
- **Benefit**: More favorable than standard equity options (100% short-term if held <1 year)
- **Disclaimer**: Consult tax advisor for specific situations

### 4. Daily Expirations (SPXW)
- **Every Trading Day**: Mon/Tue/Wed/Thu/Fri
- **0DTE Trading**: Trade up to last day at market close
- **High Liquidity**: Most active on 0DTE
- **Theta Decay**: Accelerated decay on expiration day

---

## 📈 Strategy Considerations

### Market Hours for Strategies

#### Regular Hours (8:30 AM - 3:15 PM ET)
✅ **Safe for all strategies**:
- High liquidity
- Tight bid-ask spreads
- Full order book depth
- Real-time market makers

#### Extended Hours (8:15 PM - 9:15 AM ET)
⚠️ **Use with caution**:
- Lower liquidity
- Wider spreads possible
- Limited market makers
- Higher volatility potential
- Best for: Reacting to overnight news, Asian/European market events

#### After Hours (3:15 PM - 8:15 PM ET)
❌ **Market CLOSED**:
- No trading allowed
- Cannot place/modify orders
- Positions held overnight exposed to gap risk

---

## 🚨 Important Rules for Automated Trading

### 1. Market Hours Validation
**CRITICAL**: Always check market hours before automated entry:
```python
def is_market_open():
    """Check if SPX options market is open for trading"""
    now = datetime.now(timezone('US/Eastern'))
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Check if in regular trading hours (8:30 AM - 3:15 PM ET)
    time_now = now.time()
    market_open = time(8, 30)
    market_close = time(15, 15)
    
    return market_open <= time_now <= market_close
```

### 2. 0DTE Expiration Timing
- **Last trade time**: 3:15 PM ET on expiration day
- **Settlement**: P.M. settlement at 4:00 PM ET (using closing auction)
- **Exit before 3:00 PM**: Leave buffer for order fills
- **Avoid holding into close**: High risk of adverse settlement price

### 3. Volume and Liquidity Patterns
- **Peak liquidity**: 9:30 AM - 11:00 AM and 2:00 PM - 3:15 PM
- **Lunch lull**: 11:30 AM - 1:30 PM (lower volume)
- **0DTE spike**: Final 30 minutes (3:00 PM - 3:15 PM) sees huge volume

---

## 🔄 Contract Specifications for IBKR API

### SPX Standard
```python
contract = Contract()
contract.symbol = "SPX"
contract.secType = "IND"  # For underlying price
contract.exchange = "CBOE"
contract.currency = "USD"
```

### SPXW (Weeklys - for 0DTE)
```python
contract = Contract()
contract.symbol = "SPX"
contract.secType = "OPT"
contract.exchange = "SMART"
contract.currency = "USD"
contract.tradingClass = "SPXW"  # Critical for 0DTE
contract.strike = 5800.0
contract.right = "C"  # or "P"
contract.lastTradeDateOrContractMonth = "20251022"
contract.multiplier = "100"
```

### XSP (Mini)
```python
contract = Contract()
contract.symbol = "XSP"
contract.secType = "OPT"
contract.exchange = "SMART"
contract.currency = "USD"
contract.tradingClass = "XSP"
contract.strike = 580.0  # 1/10th of SPX
contract.right = "C"  # or "P"
contract.lastTradeDateOrContractMonth = "20251022"
contract.multiplier = "100"
```

---

## 📊 Comparison: SPX vs XSP for Our Application

| Factor | SPX/SPXW | XSP (Mini) | Recommendation |
|--------|----------|------------|----------------|
| **Capital Required** | ~$410k notional | ~$41k notional | XSP for smaller accounts |
| **Liquidity** | Highest (most active) | Good but lower | SPX for fastest fills |
| **Commissions** | $0.70-$2.51 | $0.31-$0.60 | XSP cheaper per contract |
| **Bid-Ask Spread** | Tightest | Slightly wider | SPX for best pricing |
| **Position Sizing** | Large increments | Granular (10x more flexible) | **XSP WINNER** |
| **0DTE Availability** | ✅ Every day (SPXW) | ✅ Mon/Tue/Wed/Thu/Fri | Both excellent |
| **Settlement** | A.M. (SPX) / P.M. (SPXW) | P.M. | SPXW/XSP better for 0DTE |

### **Recommendation for This Application**:
**Use XSP** for most strategies because:
1. ✅ More flexible position sizing (1/10th size allows 10x granularity)
2. ✅ Lower capital requirements (better for smaller accounts)
3. ✅ Lower commissions per contract
4. ✅ Daily expirations (Mon-Fri)
5. ✅ P.M. settlement (better for 0DTE exit timing)
6. ✅ Same tax benefits (60/40 treatment)

**Use SPX/SPXW only if**:
- Very large account (>$500k)
- Need absolute tightest spreads
- Trading size where XSP requires too many contracts

---

## 🎓 Additional Resources

- [Cboe Index Options Guide](https://cdn.cboe.com/resources/spx/Cboe_IndexOptionsGuide_Digital.pdf) - Comprehensive benefits guide
- [Trading Hours Details](https://go.cboe.com/24x5) - Official GTH information
- [Characteristics and Risks of Standardized Options](https://www.theocc.com/about/publications/character-risks.jsp) - ODD document
- [IBKR Options Commissions](https://www.interactivebrokers.com/en/pricing/commissions-options.php) - Full pricing breakdown

---

## ⚠️ Risk Disclaimers

1. **Capital Risk**: Options involve substantial risk of loss
2. **Not Suitable for All**: Only trade with risk capital
3. **Tax Advice**: Consult tax professional for your situation
4. **Margin Requirements**: Selling options requires adequate margin
5. **0DTE Risks**: High volatility and theta decay on expiration day
6. **Early Exit Recommended**: Close 0DTE positions before 3:00 PM ET

---

## 📝 Summary for Strategy Development

### Market Hours Check (Critical!)
```
✅ Trade only during: 8:30 AM - 3:15 PM ET, Monday-Friday
❌ Block trading during: 3:15 PM - 8:30 AM, weekends, holidays
⚠️ Extended hours available but not recommended for automated strategies
```

### Product Selection
```
Primary: XSP (Mini SPX) - Best for flexible position sizing
Alternative: SPXW - Use for very large accounts
Symbol in Code: XSP (change from SPX)
Trading Class: "XSP"
```

### Settlement Times
```
SPXW: P.M. Settlement at 4:00 PM ET
XSP: P.M. Settlement at 4:00 PM ET
⚠️ Exit 0DTE positions by 3:00 PM to avoid settlement risk
```

### Tax Treatment
```
All SPX/SPXW/XSP/NANOS qualify for Section 1256:
- 60% long-term capital gains rate
- 40% short-term capital gains rate
- Regardless of holding period
```
