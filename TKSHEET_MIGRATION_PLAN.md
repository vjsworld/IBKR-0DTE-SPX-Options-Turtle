# TKSheet Migration Plan - IBKR TWS Style Option Chain

## Overview
Migrate from ttk.Treeview to tksheet for professional option chain display matching IBKR TWS exactly.

## Analysis of TWS Screenshot

### Color Scheme (from user's TWS screenshot)
1. **Background Colors**:
   - Pure black base: `#000000`
   - Headers: Very dark gray `#0a0a0a` to `#1a1a1a`
   - ITM Calls (subtle green): `#001100` to `#002200` (very subtle)
   - ITM Puts (subtle red): `#110000` to `#220000` (very subtle)
   - OTM: Pure black `#000000`

2. **Text Colors**:
   - Positive changes: Bright green `#00ff00` or `#00cc00`
   - Negative changes: Bright red `#ff0000` or `#cc0000`
   - Neutral values: Light gray `#b0b0b0` to `#d0d0d0`
   - Percentage changes: Same as above (red/green)

3. **Fonts**:
   - Primary font: Arial or Helvetica
   - Size: 9-10pt for data cells
   - Headers: 10pt, bold
   - Strike column: 11pt, bold, centered

### Column Layout (from screenshot)
**CALLS (Left Side)**:
- OPTN OPRI (Option Open Interest)
- VOLUME
- CHANGE %
- BID
- ASK
- AVG PRICE
- POSITION
- UNRLZD P&L
- IMPL. BID VOL.
- DELTA
- THETA
- VEGA
- GAMMA
- TM VL. (%)

**STRIKE (Center)** - Bold, larger font

**PUTS (Right Side)** - Mirror of calls

### Key Features Observed
1. **Cell-level coloring**: Each cell can have its own foreground color
2. **Row-level backgrounds**: Subtle gradients for ITM options
3. **Percentage formatting**: Red for negative, green for positive
4. **Alignment**: Numbers right-aligned, strike centered
5. **Grid lines**: Very subtle, dark gray `#1a1a1a`
6. **Selection**: Subtle blue highlight when clicked

## Implementation Steps

### Phase 1: Basic tksheet Setup
1. Import tksheet
2. Create Sheet widget with scrollbars
3. Set up column headers
4. Configure basic dimensions

### Phase 2: TWS Color Scheme
1. Set sheet background to pure black
2. Configure header colors
3. Set up cell foreground colors (text)
4. Implement ITM/OTM background gradients
5. Add grid line colors

### Phase 3: Data Population
1. Convert current market_data structure to tksheet data format
2. Implement row insertion/update logic
3. Add strike-based row identification
4. Maintain tree_item → row_index mapping

### Phase 4: Cell Styling
1. Implement conditional formatting:
   - Positive values → green text
   - Negative values → red text
   - Percentage changes → green/red
2. ITM detection and background shading
3. Strike column bold formatting

### Phase 5: Interaction
1. Bind cell click events
2. Implement option selection (call/put chart loading)
3. Add position highlighting
4. Tooltip support

### Phase 6: Performance
1. Batch updates for real-time data
2. Debounce refresh operations
3. Optimize color calculations

## Code Structure

### New Variables Needed
```python
self.option_sheet = None  # tksheet widget
self.sheet_data = []  # 2D list of data
self.strike_to_row = {}  # Map strike to row index
```

### Key Methods to Modify
- `create_trading_tab()` - Replace Treeview with Sheet
- `subscribe_market_data()` - Update row mapping
- `update_option_chain_display()` - Rewrite for tksheet
- `on_option_chain_click()` - Update for sheet events

### TWS Color Constants
```python
TWS_COLORS = {
    'background': '#000000',
    'header_bg': '#1a1a1a',
    'header_fg': '#e0e0e0',
    'grid_line': '#2a2a2a',
    'text_neutral': '#b0b0b0',
    'text_positive': '#00ff00',
    'text_negative': '#ff0000',
    'call_itm_light': '#001a00',
    'call_itm_deep': '#002a00',
    'put_itm_light': '#1a0000',
    'put_itm_deep': '#2a0000',
    'strike_text': '#ffffff',
    'selection': '#1a2a3a'
}
```

## Testing Checklist
- [ ] Sheet displays with correct columns
- [ ] Data populates correctly
- [ ] Real-time updates work
- [ ] ITM/OTM shading appears correctly
- [ ] Cell colors update (red/green)
- [ ] Click events trigger chart loading
- [ ] Performance is smooth (< 100ms updates)
- [ ] Scrolling works properly
- [ ] Resize handles properly

## Rollback Plan
- Keep current Treeview code in git history
- Test tksheet version thoroughly before removing Treeview
- Document any issues encountered

## Resources
- tksheet documentation: https://github.com/ragardner/tksheet
- IBKR TWS color reference: User's screenshot
- Professional option chain standards: Industry best practices
