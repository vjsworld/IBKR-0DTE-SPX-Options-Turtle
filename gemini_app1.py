"""
SPX 0DTE Options Trading Application
Professional Bloomberg-style GUI for Interactive Brokers API
Author: VJS World & Gemini
Date: October 22, 2025

Features:
- Gamma-Snap HFS v3.0 (Z-Score) Automated Trading Strategy.
- Integrated TradingView Lightweight Charts for professional analysis.
- Advanced Manual Trading Mode with risk-based entry and mid-price chasing.
- Professional IBKR TWS-themed GUI with detailed option chain.
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, YES, X, Y, LEFT, RIGHT, BOTTOM, TOP, CENTER, W
from tksheet import Sheet
import threading
import queue
from datetime import datetime, timedelta
from collections import deque, defaultdict
from enum import Enum
import json
import os
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import webbrowser

# New dependency for embedding web-based charts
from tkwebview2.tkwebview2 import WebView2, have_runtime, install_runtime

# Interactive Brokers API imports
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.common import TickerId, TickAttrib
from ibapi.ticktype import TickType
from scipy.stats import norm
import math


# ============================================================================
# FILE LOGGING SETUP
# ============================================================================

def setup_file_logger():
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    log_filename = datetime.now().strftime('%Y-%m-%d.txt')
    log_filepath = os.path.join(logs_dir, log_filename)
    
    file_logger = logging.getLogger('SPXTradingApp')
    file_logger.setLevel(logging.DEBUG)
    file_logger.handlers.clear()
    
    file_handler = logging.FileHandler(log_filepath, mode='a', encoding='utf-8')
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    file_logger.addHandler(file_handler)
    
    file_logger.info("=" * 80)
    file_logger.info("SPX 0DTE Options Trading Application - Session Started")
    file_logger.info("=" * 80)
    return file_logger

file_logger = setup_file_logger()


# ============================================================================
# BLACK-SCHOLES GREEKS CALCULATIONS
# ============================================================================

def calculate_greeks(option_type: str, spot_price: float, strike: float, 
                     time_to_expiry: float, volatility: float, risk_free_rate: float = 0.05) -> dict:
    try:
        if time_to_expiry <= 0:
            delta = 1.0 if (option_type == 'C' and spot_price > strike) else (-1.0 if (option_type == 'P' and spot_price < strike) else 0.0)
            return {'delta': delta, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'iv': volatility}
        if volatility <= 0 or spot_price <= 0 or strike <= 0:
            return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'iv': 0.0}
        d1 = (math.log(spot_price / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        N_d1, n_d1 = norm.cdf(d1), norm.pdf(d1)
        delta = N_d1 if option_type == 'C' else N_d1 - 1.0
        gamma = n_d1 / (spot_price * volatility * math.sqrt(time_to_expiry))
        if option_type == 'C':
            theta = (-(spot_price * n_d1 * volatility) / (2 * math.sqrt(time_to_expiry)) - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * norm.cdf(d2)) / 365
        else:
            theta = (-(spot_price * n_d1 * volatility) / (2 * math.sqrt(time_to_expiry)) + risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * (1 - norm.cdf(d2))) / 365
        vega = spot_price * math.sqrt(time_to_expiry) * n_d1 / 100
        return {'delta': round(float(delta), 4), 'gamma': round(float(gamma), 4), 'theta': round(float(theta), 4), 'vega': round(float(vega), 4), 'iv': round(volatility, 4)}
    except Exception:
        return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'iv': 0.0}

# ============================================================================
# CONNECTION & API WRAPPER
# ============================================================================

class ConnectionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"

class IBKRWrapper(EWrapper):
    def __init__(self, app):
        EWrapper.__init__(self)
        self.app = app
    
    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        if errorCode in [10268, 2104, 2106, 2158, 10147]:
            if errorCode in [2104, 2106]:
                self.app.log_message("✓ Data server connection confirmed - ready for trading", "SUCCESS")
                self.app.data_server_ok = True
            return
        self.app.log_message(f"[ERROR] Req={reqId}, Code={errorCode}, Msg={errorString}", "ERROR")
        if errorCode in [502, 504, 1100, 2110]:
            self.app.connection_state = ConnectionState.DISCONNECTED
            self.app.schedule_reconnect()
        elif errorCode == 162 and reqId in [self.app.spx_1min_req_id, self.app.chart_hist_req_id]:
            msg = "Strategy" if reqId == self.app.spx_1min_req_id else "Charting"
            self.app.log_message(f"CRITICAL: Historical data for {msg} not subscribed.", "ERROR")
            if hasattr(self.app, 'strategy_status_var'):
                 self.app.strategy_status_var.set("Strategy Status: FAILED (No SPX Data)")

    def nextValidId(self, orderId: int):
        self.app.next_order_id = orderId
        self.app.connection_state = ConnectionState.CONNECTED
        self.app.reconnect_attempts = 0
        self.app.log_message(f"Successfully connected! Next Order ID: {orderId}", "SUCCESS")
        self.app.on_connected()

    def orderStatus(self, orderId: int, status: str, filled: float, remaining: float, avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        self.app.log_message(f"Order {orderId}: {status} - Filled: {filled} @ {avgFillPrice}", "INFO")
        self.app.update_order_in_tree(orderId, status, avgFillPrice if avgFillPrice > 0 else None)
        if status == "Filled" and orderId in self.app.pending_orders:
            contract_key, action, quantity = self.app.pending_orders[orderId]
            self.app.update_position_on_fill(contract_key, action, quantity, avgFillPrice)
            
            if self.app.active_trade_info and self.app.active_trade_info.get('order_id') == orderId:
                if action == "BUY":
                    self.app.active_trade_info['status'] = 'FILLED'
                    self.app.active_trade_info['entry_price'] = avgFillPrice
                    self.app.log_message(f"STRATEGY: Entry order {orderId} filled.", "SUCCESS")
                    self.app.add_trade_marker_to_chart(self.app.active_trade_info, 'entry')
                elif action == "SELL":
                    self.app.log_message(f"STRATEGY: Exit order {orderId} filled. Trade complete.", "SUCCESS")
                    self.app.add_trade_marker_to_chart(self.app.active_trade_info, 'exit', avgFillPrice)
                    self.app.trade_history.append(self.app.active_trade_info)
                    self.app.active_trade_info = {}
            del self.app.pending_orders[orderId]

    def historicalData(self, reqId: int, bar):
        if reqId == self.app.spx_1min_req_id:
            self.app.spx_1min_bars.append({'time': bar.date, 'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close})
        elif reqId == self.app.chart_hist_req_id:
            self.app.chart_bar_data.append({'time': bar.date, 'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close, 'volume': bar.volume})

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        if reqId == self.app.spx_1min_req_id:
            self.app.log_message(f"Initial SPX 1-min history received ({len(self.app.spx_1min_bars)} bars).", "SUCCESS")
            self.app.calculate_indicators()
        elif reqId == self.app.chart_hist_req_id:
            self.app.log_message(f"Chart historical data received ({len(self.app.chart_bar_data)} bars).", "INFO")
            self.app.update_tv_chart()

    def historicalDataUpdate(self, reqId: int, bar):
        # Update needs to convert date to datetime
        if reqId == self.app.spx_1min_req_id:
            bar_time = datetime.strptime(bar.date, '%Y%m%d  %H:%M:%S')
            self.app.spx_1min_bars.append({'time': bar_time, 'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close})
            self.app.calculate_indicators()

    def tickPrice(self, reqId, tickType, price, attrib):
        if reqId == self.app.spx_req_id and tickType == 4: self.app.spx_price = price; self.app.update_spx_price_display()
        elif reqId == self.app.vix_req_id and tickType == 4: self.app.vix_price = price
        elif reqId in self.app.market_data_map:
            key = self.app.market_data_map[reqId]
            if tickType == 1: self.app.market_data[key]['bid'] = price
            elif tickType == 2: self.app.market_data[key]['ask'] = price
            elif tickType == 4: self.app.market_data[key]['last'] = price
            if key in self.app.positions: self.app.update_position_pnl(key)
    
    def openOrder(self, orderId, contract, order, orderState): self.app.log_message(f"TWS Received Order #{orderId} for {self.app.get_contract_key(contract)}", "SUCCESS")
    def position(self, account, contract, position, avgCost):
        contract_key = self.app.get_contract_key(contract)
        if position != 0:
            per_option_cost = avgCost / 100 if contract.secType == "OPT" else avgCost
            self.app.positions[contract_key] = {'contract': contract, 'position': position, 'avgCost': per_option_cost, 'currentPrice': 0, 'pnl': 0, 'entryTime': datetime.now()}
        else:
            if contract_key in self.app.positions: del self.app.positions[contract_key]
    def positionEnd(self): self.app.update_positions_display()
    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        if reqId in self.app.market_data_map:
            self.app.market_data[self.app.market_data_map[reqId]].update({'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega, 'iv': impliedVol})
    def tickSize(self, reqId, tickType, size):
        if reqId in self.app.market_data_map: self.app.market_data[self.app.market_data_map[reqId]]['volume'] = size

class IBKRClient(EClient):
    def __init__(self, wrapper): EClient.__init__(self, wrapper)


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class SPXTradingApp(IBKRWrapper, IBKRClient):
    def __init__(self):
        IBKRWrapper.__init__(self, self)
        IBKRClient.__init__(self, wrapper=self)
        
        self.connection_state = ConnectionState.DISCONNECTED
        self.data_server_ok = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        self.auto_connect = True
        self.host, self.port, self.client_id, self.account = "127.0.0.1", 7497, 1, ""
        
        # Gamma-Snap Strategy Parameters & State (v3.0 Z-Score)
        self.strategy_enabled = False
        self.vix_threshold = 25.0
        self.z_score_period = 20         # NEW: Z-Score Lookback
        self.z_score_threshold = 2.5     # NEW: Z-Score Entry Trigger
        self.time_stop_minutes, self.trade_qty = 5, 1
        self.spx_1min_bars = deque(maxlen=200)
        self.indicators = {'ema9': 0.0, 'z_score': 0.0} # UPDATED
        self.vix_price = 0.0
        self.active_trade_info = {}
        self.trade_history = []
        self.spx_1min_req_id, self.vix_req_id = 9001, 9002

        # Charting
        self.chart_hist_req_id = 9003
        self.selected_chart_contract = None
        self.chart_bar_data = []
        
        # Data storage & IDs
        self.next_order_id, self.next_req_id = 1, 1000
        self.market_data, self.market_data_map, self.strike_to_row = {}, {}, {}
        self.positions, self.pending_orders, self.manual_orders = {}, {}, {}
        self.spx_price, self.spx_req_id = 0.0, 9000
        self.current_expiry = self.calculate_expiry_date(0)
        
        self.root: Optional[ttk.Window] = None
        self.check_webview_runtime()
        self.setup_gui()
        
    def check_webview_runtime(self):
        if not have_runtime():
            self.log_message("WebView2 runtime not found.", "WARNING")
            if messagebox.askyesno("WebView2 Runtime Required", "This application requires the Microsoft Edge WebView2 runtime. Install it now?"):
                try:
                    install_runtime()
                    messagebox.showinfo("Installation Complete", "Runtime installed. Please restart the application.")
                except Exception as e:
                    messagebox.showerror("Installation Failed", f"Could not install runtime: {e}")
            exit()

    def setup_gui(self):
        self.root = ttk.Window(themename="darkly")
        self.root.title("SPX 0DTE Trader - Gamma-Snap Z-Score v3.0 (with TradingView Charts)")
        self.root.geometry("1920x1080")
        
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=BOTH, expand=YES)
        
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        self.create_trading_tab()
        self.create_settings_tab()
        
        self.create_status_bar(main_container)
        
        self.root.after(1000, self.update_time)
        self.root.after(5000, self.run_gamma_snap_strategy) # Strategy runs every 5s

        if self.auto_connect: self.root.after(2000, self.connect_to_ib)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_trading_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Trading Dashboard")

        top_pane = ttk.PanedWindow(tab, orient=HORIZONTAL)
        top_pane.pack(fill=BOTH, expand=YES, padx=5, pady=5)

        left_frame = ttk.Frame(top_pane)
        top_pane.add(left_frame, weight=2)

        right_frame = ttk.Frame(top_pane)
        top_pane.add(right_frame, weight=3)
        
        # --- Contents of Left Frame ---
        left_top_frame = ttk.Frame(left_frame)
        left_top_frame.pack(fill=X, pady=5, padx=5)

        # Strategy Panel (UPDATED for Z-Score)
        strategy_panel = ttk.LabelFrame(left_top_frame, text="Gamma-Snap Strategy Control (Z-Score v3.0)")
        strategy_panel.pack(side=LEFT, fill=Y, padx=(0,10), expand=YES)
        self.strategy_status_var = tk.StringVar(value="Status: INACTIVE")
        ttk.Label(strategy_panel, textvariable=self.strategy_status_var, font=("Arial", 10, "bold")).pack(pady=5)
        indicator_frame = ttk.Frame(strategy_panel); indicator_frame.pack(pady=2, padx=10, fill=X)
        self.indicator_labels = {}
        # UPDATED Indicator List
        for indicator in ["SPX Price", "9-EMA (Target)", "Z-Score", "VIX"]:
            frame = ttk.Frame(indicator_frame); frame.pack(fill=X)
            ttk.Label(frame, text=f"{indicator}:", width=12, anchor='w').pack(side=LEFT)
            self.indicator_labels[indicator] = tk.StringVar(value="--")
            ttk.Label(frame, textvariable=self.indicator_labels[indicator], width=12, anchor='e').pack(side=RIGHT)
        
        # Manual Trading Panel
        manual_trade_frame = ttk.LabelFrame(left_top_frame, text="Manual Trading")
        manual_trade_frame.pack(side=LEFT, fill=BOTH, expand=YES)
        manual_controls = ttk.Frame(manual_trade_frame); manual_controls.pack(fill=X, pady=5, padx=5)
        entry_frame = ttk.Frame(manual_controls); entry_frame.pack(side=LEFT, padx=(0, 20))
        ttk.Label(entry_frame, text="Quick Entry:", font=("Arial", 10, "bold")).pack(side=LEFT, padx=(0, 10))
        self.buy_button = ttk.Button(entry_frame, text="BUY CALL", command=self.manual_buy_call, style='success.TButton', width=12); self.buy_button.pack(side=LEFT, padx=2)
        self.sell_button = ttk.Button(entry_frame, text="BUY PUT", command=self.manual_buy_put, style='danger.TButton', width=12); self.sell_button.pack(side=LEFT, padx=2)
        risk_frame = ttk.Frame(manual_controls); risk_frame.pack(side=LEFT)
        ttk.Label(risk_frame, text="Max Risk $:").pack(side=LEFT, padx=(0, 5))
        self.max_risk_var = tk.StringVar(value="500"); self.max_risk_entry = ttk.Entry(risk_frame, textvariable=self.max_risk_var, width=10); self.max_risk_entry.pack(side=LEFT, padx=2)

        # Option Chain
        chain_container = ttk.LabelFrame(left_frame, text="SPX 0DTE Option Chain")
        chain_container.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        self.spx_price_label = ttk.Label(chain_container, text="SPX: Loading...", font=("Arial", 12, "bold"), foreground="#FF8C00"); self.spx_price_label.pack(pady=5)
        headers = ["IV", "Delta", "Theta", "Vega", "Gamma", "Vol", "CHANGE %", "Last", "Ask", "Bid", "● STRIKE ●", "Bid", "Ask", "Last", "CHANGE %", "Vol", "Gamma", "Vega", "Theta", "Delta", "IV"]
        self.option_sheet = Sheet(chain_container, headers=headers, theme="dark", show_row_index=False, height=250); self.option_sheet.pack(fill=BOTH, expand=YES)
        self.option_sheet.bind("<ButtonRelease-1>", self.on_option_sheet_click)

        # Positions and Orders
        pos_order_pane = ttk.PanedWindow(left_frame, orient=VERTICAL)
        pos_order_pane.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        pos_container = ttk.LabelFrame(pos_order_pane, text="Open Positions"); pos_order_pane.add(pos_container, weight=1)
        self.position_sheet = Sheet(pos_container, headers=["Contract", "Qty", "Entry", "Mid", "PnL", "PnL%", "Action"], theme="dark"); self.position_sheet.pack(fill=BOTH, expand=YES)
        order_container = ttk.LabelFrame(pos_order_pane, text="Active Orders"); pos_order_pane.add(order_container, weight=1)
        self.order_sheet = Sheet(order_container, headers=["ID", "Contract", "Action", "Qty", "Price", "Status", "Cancel"], theme="dark"); self.order_sheet.pack(fill=BOTH, expand=YES)
        self.order_sheet.bind("<ButtonRelease-1>", self.on_order_sheet_click)
        self.position_sheet.bind("<ButtonRelease-1>", self.on_position_sheet_click)

        # --- Contents of Right Frame ---
        chart_frame = ttk.LabelFrame(right_frame, text="TradingView Chart")
        chart_frame.pack(fill=BOTH, expand=YES, pady=5, padx=5)
        self.tv_chart = WebView2(chart_frame, 100, 100); self.tv_chart.pack(fill=BOTH, expand=YES)
        self.tv_chart.load_html(self.get_chart_html())

    def get_chart_html(self):
        # No change to chart HTML
        return """
        <!DOCTYPE html><html><head><meta charset="UTF-8"><script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script><style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #181818; } #chart-container { width: 100%; height: 100%; }</style></head><body><div id="chart-container"></div><script>
            const chartContainer = document.getElementById('chart-container');
            let chart = null; let candlestickSeries = null, emaSeries = null, bbUpperSeries = null, bbLowerSeries = null;
            function initChart() {
                if (chart) chart.remove();
                chart = LightweightCharts.createChart(chartContainer, { layout: { backgroundColor: '#181818', textColor: '#E0E0E0' }, grid: { vertLines: { color: '#2a2a2a' }, horzLines: { color: '#2a2a2a' } }, timeScale: { timeVisible: true, secondsVisible: true }});
                candlestickSeries = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
                emaSeries = chart.addLineSeries({ color: '#FF8C00', lineWidth: 2, crosshairMarkerVisible: false });
                bbUpperSeries = chart.addLineSeries({ color: '#2962FF', lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
                bbLowerSeries = chart.addLineSeries({ color: '#2962FF', lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
            }
            function updateData(data) {
                if (!chart) initChart();
                if (data.candlestick) candlestickSeries.setData(data.candlestick);
                if (data.ema) emaSeries.setData(data.ema);
                if (data.bb_upper) bbUpperSeries.setData(data.bb_upper);
                if (data.bb_lower) bbLowerSeries.setData(data.bb_lower);
                if (data.markers) candlestickSeries.setMarkers(data.markers);
                chart.timeScale().fitContent();
            }
            function addMarker(marker) { if (candlestickSeries) { const existingMarkers = candlestickSeries.markers(); candlestickSeries.setMarkers([...existingMarkers, marker]); } }
            new ResizeObserver(() => chart && chart.resize(chartContainer.clientWidth, chartContainer.clientHeight)).observe(chartContainer);
            window.addEventListener('DOMContentLoaded', initChart);
        </script></body></html>"""

    def on_option_sheet_click(self, event):
        try:
            region = self.option_sheet.identify_region(event)
            if region != "table": return
            row_idx = self.option_sheet.identify_row(event, exclude_index=True)
            col_idx = self.option_sheet.identify_column(event, exclude_header=True)
            if row_idx is None or col_idx is None: return

            strike = None
            for s, r_idx in self.strike_to_row.items():
                if r_idx == row_idx: strike = s; break
            if strike is None: return

            option_type = 'C' if col_idx < 10 else 'P'
            contract_key, contract = None, None
            for key, data in self.market_data.items():
                if data.get('strike') == float(strike) and data.get('right') == option_type:
                    contract_key, contract = key, data.get('contract'); break
            
            if contract:
                self.selected_chart_contract = contract
                self.request_chart_data()
            else:
                self.log_message(f"Contract not found for strike {strike} {option_type}", "WARNING")
        except Exception as e: self.log_message(f"Error on sheet click: {e}", "ERROR")

    # ========================================================================
    # UTILITIES AND CORE LOGIC (MERGED & PRESERVED)
    # ========================================================================
    
    # Charting (TradingView)
    def request_chart_data(self):
        if not self.selected_chart_contract: return
        self.chart_bar_data.clear()
        self.log_message(f"Requesting chart data for: {self.get_contract_key(self.selected_chart_contract)}", "INFO")
        self.reqHistoricalData(self.chart_hist_req_id, self.selected_chart_contract, "", "1 D", "1 min", "MIDPOINT", 1, 1, False, [])

    def update_tv_chart(self):
        if not self.chart_bar_data: return
        df = pd.DataFrame(self.chart_bar_data); df['time'] = df['time'].apply(lambda x: datetime.strptime(x, '%Y%m%d  %H:%M:%S').timestamp())
        candlestick_data = df[['time', 'open', 'high', 'low', 'close']].to_dict(orient='records')
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean(); ema_data = df[['time', 'ema9']].rename(columns={'ema9': 'value'}).to_dict(orient='records')
        sma20 = df['close'].rolling(window=self.z_score_period).mean(); std20 = df['close'].rolling(window=self.z_score_period).std()
        df['bb_upper'] = sma20 + (std20 * 2); df['bb_lower'] = sma20 - (std20 * 2)
        bb_upper_data = df[['time', 'bb_upper']].rename(columns={'bb_upper': 'value'}).dropna().to_dict(orient='records')
        bb_lower_data = df[['time', 'bb_lower']].rename(columns={'bb_lower': 'value'}).dropna().to_dict(orient='records')
        contract_key = self.get_contract_key(self.selected_chart_contract)
        markers = []
        for trade in self.trade_history:
            if trade['contract_key'] == contract_key:
                markers.append({'time': trade['entry_time'].timestamp(), 'position': 'aboveBar', 'color': '#2196F3', 'shape': 'arrowDown', 'text': f"B @ {trade['entry_price']:.2f}"})
                if trade.get('exit_time'): markers.append({'time': trade['exit_time'].timestamp(), 'position': 'belowBar', 'color': '#FF8C00', 'shape': 'arrowUp', 'text': f"S @ {trade['exit_price']:.2f}"})
        chart_payload = {'candlestick': candlestick_data, 'ema': ema_data, 'bb_upper': bb_upper_data, 'bb_lower': bb_lower_data, 'markers': markers}
        self.tv_chart.evaluate_js(f"updateData({json.dumps(chart_payload)})")
    
    def add_trade_marker_to_chart(self, trade_info, trade_type, price=None):
        if not self.selected_chart_contract or self.get_contract_key(self.selected_chart_contract) != trade_info['contract_key']: return
        if trade_type == 'entry':
            marker = {'time': trade_info['entry_time'].timestamp(), 'position': 'aboveBar', 'color': '#2196F3', 'shape': 'arrowDown', 'text': f"B @ {trade_info['entry_price']:.2f}"}
            trade_info['exit_time'] = None; trade_info['exit_price'] = None
        elif trade_type == 'exit':
            marker = {'time': datetime.now().timestamp(), 'position': 'belowBar', 'color': '#FF8C00', 'shape': 'arrowUp', 'text': f"S @ {price:.2f}"}
            trade_info['exit_time'] = datetime.now(); trade_info['exit_price'] = price
        self.tv_chart.evaluate_js(f"addMarker({json.dumps(marker)})")

    # Strategy (Gamma-Snap v3.0 Z-Score)
    def calculate_indicators(self):
        if len(self.spx_1min_bars) < self.z_score_period: return
        
        # Convert to DataFrame
        bar_data = [{'time': b['time'], 'close': b['close']} for b in self.spx_1min_bars]
        df = pd.DataFrame(bar_data).set_index('time')

        # 1. Calculate 9-EMA (for Profit Target)
        self.indicators['ema9'] = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
        
        # 2. Calculate Z-Score
        sma = df['close'].rolling(window=self.z_score_period).mean()
        std = df['close'].rolling(window=self.z_score_period).std()
        
        last_sma = sma.iloc[-1]
        last_std = std.iloc[-1]
        last_close = df['close'].iloc[-1]
        
        if last_std > 0:
            self.indicators['z_score'] = (last_close - last_sma) / last_std
        else:
            self.indicators['z_score'] = 0.0
            
        self.update_indicator_display()

    def run_gamma_snap_strategy(self):
        if self.root: self.root.after(5000, self.run_gamma_snap_strategy)
        now = datetime.now()
        if not self.strategy_enabled: self.strategy_status_var.set("Status: INACTIVE"); return
        if not (now.hour >= 9 and now.minute >= 30 and now.hour < 15): self.strategy_status_var.set("Status: Outside Trading Window"); return
        if self.vix_price > self.vix_threshold: self.strategy_status_var.set(f"Status: PAUSED (VIX High: {self.vix_price:.2f})"); return
        if len(self.spx_1min_bars) < self.z_score_period + 1: self.strategy_status_var.set("Status: Waiting for Data..."); return
        if self.active_trade_info: self.check_trade_exit(); return
        
        self.strategy_status_var.set("Status: SCANNING...")
        
        # Get last two Z-Scores for crossover logic
        bar_data = [{'time': b['time'], 'close': b['close']} for b in self.spx_1min_bars]
        df = pd.DataFrame(bar_data).set_index('time')
        sma = df['close'].rolling(window=self.z_score_period).mean()
        std = df['close'].rolling(window=self.z_score_period).std()
        z_scores = (df['close'] - sma) / std
        
        last_z_score = z_scores.iloc[-1]
        prev_z_score = z_scores.iloc[-2]
        
        # Long Entry: Z-Score crosses UP from below the threshold
        if (prev_z_score < -self.z_score_threshold and last_z_score > -self.z_score_threshold):
            self.enter_trade('LONG')
            
        # Short Entry: Z-Score crosses DOWN from above the threshold
        elif (prev_z_score > self.z_score_threshold and last_z_score < self.z_score_threshold):
            self.enter_trade('SHORT')

    def enter_trade(self, direction: str):
        option_type, target_delta = ('C', 0.45) if direction == 'LONG' else ('P', -0.45)
        best_option_key, min_delta_diff = None, float('inf')
        for key, data in self.market_data.items():
            if data.get('right') == option_type:
                delta = data.get('delta', 0)
                if delta != 0: # Ensure delta is calculated
                    delta_diff = abs(delta - target_delta)
                    if delta_diff < min_delta_diff: min_delta_diff, best_option_key = delta_diff, key
        if not best_option_key: self.log_message(f"STRATEGY: Could not find suitable {option_type} option.", "WARNING"); return
        
        option_data = self.market_data[best_option_key]; 
        limit_price = option_data.get('ask') if direction == 'LONG' else option_data.get('bid') # Buy at Ask, Sell at Bid logic
        if not limit_price or limit_price <= 0: self.log_message(f"STRATEGY: Invalid limit price for {best_option_key}.", "ERROR"); return
        
        order_id = self.place_order(best_option_key, option_data['contract'], "BUY", self.trade_qty, limit_price, enable_chasing=False)
        if order_id:
            self.active_trade_info = {
                'contract_key': best_option_key, 
                'direction': direction, 
                'entry_time': datetime.now(), 
                'order_id': order_id, 
                'status': 'SUBMITTED', 
                'profit_target_price': self.indicators['ema9'], 
                'entry_price': None
            }
            self.strategy_status_var.set(f"Status: IN TRADE ({direction})")

    def check_trade_exit(self):
        trade = self.active_trade_info
        if not trade or trade['status'] != 'FILLED': return
        
        # Use live SPX price for exit check
        current_price = self.spx_price 
        if current_price == 0: return # Wait for valid price
        
        # 1. Profit Target: Price touches the 9-EMA
        # We must re-calculate the 9-EMA on the *most recent* data
        self.calculate_indicators() 
        profit_target = self.indicators['ema9']
        
        if ((trade['direction'] == 'LONG' and current_price >= profit_target) or 
            (trade['direction'] == 'SHORT' and current_price <= profit_target)):
            self.exit_trade("Profit Target"); return
        
        # 2. Time Stop
        if (datetime.now() - trade['entry_time']).total_seconds() / 60 >= self.time_stop_minutes:
            self.exit_trade("Time Stop"); return
        
        # 3. Stop Loss: Removed BB-crossover. Z-Score crossover is entry.
        # Exits are now purely Profit Target or Time Stop.

    def exit_trade(self, reason: str):
        trade = self.active_trade_info; contract_key = trade['contract_key']
        option_data = self.market_data.get(contract_key)
        if not option_data: self.log_message(f"STRATEGY: Cannot exit, no market data for {contract_key}.", "ERROR"); self.active_trade_info = {}; return
        
        # Exit at the bid
        limit_price = option_data.get('bid') or option_data.get('last')
        if not limit_price or limit_price <= 0:
            self.log_message(f"STRATEGY: Invalid exit price for {contract_key}, using 0.01", "ERROR")
            limit_price = 0.01 # Failsafe
            
        self.log_message(f"STRATEGY: Exiting {contract_key} due to: {reason}", "INFO")
        self.place_order(contract_key, option_data['contract'], "SELL", self.trade_qty, limit_price, enable_chasing=False)
        # active_trade_info is cleared when the SELL order is FILLED (in orderStatus)
    
    # Settings Tab (UPDATED for Z-Score)
    def create_settings_tab(self):
        tab = ttk.Frame(self.notebook); self.notebook.add(tab, text="Settings")
        settings_frame = ttk.Frame(tab); settings_frame.pack(padx=20, pady=20)
        conn_frame = ttk.LabelFrame(settings_frame, text="Connection"); conn_frame.pack(fill=X, pady=10)
        ttk.Label(conn_frame, text="Host IP:").grid(row=0, column=0, sticky=W, pady=2); self.host_entry = ttk.Entry(conn_frame, width=20); self.host_entry.insert(0, self.host); self.host_entry.grid(row=0, column=1, sticky=W, padx=5)
        ttk.Label(conn_frame, text="Port:").grid(row=1, column=0, sticky=W, pady=2); self.port_entry = ttk.Entry(conn_frame, width=20); self.port_entry.insert(0, str(self.port)); self.port_entry.grid(row=1, column=1, sticky=W, padx=5)
        
        strat_ctrl_frame = ttk.LabelFrame(settings_frame, text="Strategy Automation"); strat_ctrl_frame.pack(fill=X, pady=10)
        self.strategy_on_btn = ttk.Button(strat_ctrl_frame, text="ON", command=lambda: self.set_strategy_enabled(True)); self.strategy_on_btn.pack(side=LEFT, padx=5)
        self.strategy_off_btn = ttk.Button(strat_ctrl_frame, text="OFF", command=lambda: self.set_strategy_enabled(False)); self.strategy_off_btn.pack(side=LEFT, padx=5)
        self.strategy_status_label = ttk.Label(strat_ctrl_frame, text=""); self.strategy_status_label.pack(side=LEFT, padx=10)
        self.update_strategy_button_states()
        
        gs_frame = ttk.LabelFrame(settings_frame, text="Gamma-Snap (Z-Score) Parameters"); gs_frame.pack(fill=X, pady=10)
        ttk.Label(gs_frame, text="VIX Threshold:").grid(row=0, column=0, sticky=W, pady=2); self.vix_entry = ttk.Entry(gs_frame, width=20); self.vix_entry.insert(0, str(self.vix_threshold)); self.vix_entry.grid(row=0, column=1, sticky=W, padx=5)
        ttk.Label(gs_frame, text="Z-Score Period:").grid(row=1, column=0, sticky=W, pady=2); self.z_period_entry = ttk.Entry(gs_frame, width=20); self.z_period_entry.insert(0, str(self.z_score_period)); self.z_period_entry.grid(row=1, column=1, sticky=W, padx=5)
        ttk.Label(gs_frame, text="Z-Score Threshold:").grid(row=2, column=0, sticky=W, pady=2); self.z_thresh_entry = ttk.Entry(gs_frame, width=20); self.z_thresh_entry.insert(0, str(self.z_score_threshold)); self.z_thresh_entry.grid(row=2, column=1, sticky=W, padx=5)
        ttk.Label(gs_frame, text="Time Stop (mins):").grid(row=3, column=0, sticky=W, pady=2); self.time_stop_entry = ttk.Entry(gs_frame, width=20); self.time_stop_entry.insert(0, str(self.time_stop_minutes)); self.time_stop_entry.grid(row=3, column=1, sticky=W, padx=5)
        ttk.Label(gs_frame, text="Trade Quantity:").grid(row=4, column=0, sticky=W, pady=2); self.trade_qty_entry = ttk.Entry(gs_frame, width=20); self.trade_qty_entry.insert(0, str(self.trade_qty)); self.trade_qty_entry.grid(row=4, column=1, sticky=W, padx=5)
        
        ttk.Button(settings_frame, text="Save & Apply", command=self.save_settings).pack(pady=20)
        
    def save_settings(self):
        try:
            self.host, self.port = self.host_entry.get(), int(self.port_entry.get())
            self.vix_threshold = float(self.vix_entry.get())
            self.z_score_period = int(self.z_period_entry.get())
            self.z_score_threshold = float(self.z_thresh_entry.get())
            self.time_stop_minutes, self.trade_qty = int(self.time_stop_entry.get()), int(self.trade_qty_entry.get())
            settings = {'host': self.host, 'port': self.port, 'vix_threshold': self.vix_threshold, 
                        'z_score_period': self.z_score_period, 'z_score_threshold': self.z_score_threshold,
                        'time_stop_minutes': self.time_stop_minutes, 'trade_qty': self.trade_qty}
            with open('settings.json', 'w') as f: json.dump(settings, f, indent=4)
            self.log_message("Settings saved successfully.", "SUCCESS")
        except Exception as e: self.log_message(f"Error saving settings: {e}", "ERROR")

    def load_settings(self):
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f: settings = json.load(f)
                self.host, self.port = settings.get('host', self.host), settings.get('port', self.port)
                self.vix_threshold = settings.get('vix_threshold', self.vix_threshold)
                self.z_score_period = settings.get('z_score_period', self.z_score_period)
                self.z_score_threshold = settings.get('z_score_threshold', self.z_score_threshold)
                self.time_stop_minutes = settings.get('time_stop_minutes', self.time_stop_minutes)
                self.trade_qty = settings.get('trade_qty', self.trade_qty)
                # Update GUI
                self.host_entry.insert(0, self.host); self.port_entry.insert(0, str(self.port))
                self.vix_entry.insert(0, str(self.vix_threshold)); self.z_period_entry.insert(0, str(self.z_score_period))
                self.z_thresh_entry.insert(0, str(self.z_score_threshold)); self.time_stop_entry.insert(0, str(self.time_stop_minutes))
                self.trade_qty_entry.insert(0, str(self.trade_qty))
                self.log_message("Settings loaded.", "SUCCESS")
        except Exception as e: self.log_message(f"Error loading settings: {e}", "ERROR")

    # All other methods from user's file are preserved below...
    def create_status_bar(self, parent):
        status_frame = ttk.Frame(parent, relief=tk.SUNKEN)
        status_frame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
        self.status_label = ttk.Label(status_frame, text="Status: Disconnected", font=("Arial", 10))
        self.status_label.pack(side=LEFT, padx=10, pady=5)
        self.connect_btn = ttk.Button(status_frame, text="Connect", command=self.toggle_connection, style="success.TButton", width=15)
        self.connect_btn.pack(side=LEFT, padx=5, pady=5)
        self.pnl_label = ttk.Label(status_frame, text="Total PnL: $0.00", font=("Arial", 10, "bold"))
        self.pnl_label.pack(side=RIGHT, padx=10, pady=5)
        self.time_label = ttk.Label(status_frame, text="", font=("Arial", 10))
        self.time_label.pack(side=RIGHT, padx=10, pady=5)

    def on_connected(self):
        self.log_message("Connection established.", "SUCCESS")
        self.status_label.config(text="Status: Connected")
        self.connect_btn.config(text="Disconnect", state=tk.NORMAL)
        self.reqAccountUpdates(True, "")
        self.reqPositions()
        self.subscribe_spx_price()
        self.subscribe_vix_price()
        self.subscribe_spx_1min_bars()
        self.request_option_chain()

    def subscribe_spx_price(self): 
        spx_contract = Contract(); spx_contract.symbol = "SPX"; spx_contract.secType = "IND"; spx_contract.currency = "USD"; spx_contract.exchange = "CBOE"
        self.spx_req_id = self.next_req_id; self.next_req_id += 1
        self.reqMktData(self.spx_req_id, spx_contract, "", False, False, [])
    def subscribe_vix_price(self):
        vix_contract = Contract(); vix_contract.symbol = "VIX"; vix_contract.secType = "IND"; vix_contract.currency = "USD"; vix_contract.exchange = "CBOE"
        self.vix_req_id = self.next_req_id; self.next_req_id += 1
        self.reqMktData(self.vix_req_id, vix_contract, "", False, False, [])
    def subscribe_spx_1min_bars(self):
        spx_contract = Contract(); spx_contract.symbol = "SPX"; spx_contract.secType = "IND"; spx_contract.currency = "USD"; spx_contract.exchange = "CBOE"
        self.spx_1min_req_id = self.next_req_id; self.next_req_id += 1
        self.reqHistoricalData(self.spx_1min_req_id, spx_contract, "", "1 D", "1 min", "TRADES", 1, 1, True, [])

    def update_indicator_display(self):
        if self.root:
            self.indicator_labels["SPX Price"].set(f"{self.spx_price:.2f}")
            self.indicator_labels["9-EMA (Target)"].set(f"{self.indicators.get('ema9', 0):.2f}")
            self.indicator_labels["Z-Score"].set(f"{self.indicators.get('z_score', 0):.3f}")
            self.indicator_labels["VIX"].set(f"{self.vix_price:.2f}")
            
    def set_strategy_enabled(self, enabled: bool): 
        self.strategy_enabled = enabled
        self.update_strategy_button_states()
        self.save_settings()
        status = "ENABLED" if enabled else "DISABLED"
        self.log_message(f"Automated Strategy {status}", "SUCCESS" if enabled else "INFO")

    def update_strategy_button_states(self):
        if self.strategy_enabled:
            self.strategy_on_btn.config(style="success.TButton"); self.strategy_off_btn.config(style="TButton")
            self.strategy_status_label.config(text="ACTIVE", foreground="#00FF00")
        else:
            self.strategy_on_btn.config(style="TButton"); self.strategy_off_btn.config(style="danger.TButton")
            self.strategy_status_label.config(text="INACTIVE", foreground="#FF0000")

    def connect_to_ib(self): 
        self.log_message(f"Connecting to {self.host}:{self.port} (Client ID: {self.client_id})...", "INFO")
        self.connection_state = ConnectionState.CONNECTING
        self.status_label.config(text="Status: Connecting...")
        self.connect_btn.config(state=tk.DISABLED)
        self.running = True
        self.api_thread = threading.Thread(target=self.run_api_thread, daemon=True)
        self.api_thread.start()
    def run_api_thread(self):
        try:
            self.connect(self.host, self.port, self.client_id)
            self.run()
        except Exception as e:
            self.log_message(f"API Thread Error: {e}", "ERROR")
        finally:
            if self.running: self.schedule_reconnect() # Only reconnect if disconnect was not intentional
    def schedule_reconnect(self): pass
    def toggle_connection(self): 
        if self.connection_state == ConnectionState.CONNECTED: self.disconnect_from_ib()
        else: self.connect_to_ib()
    def disconnect_from_ib(self):
        self.running = False; self.disconnect(); self.connection_state = ConnectionState.DISCONNECTED
        self.status_label.config(text="Status: Disconnected"); self.connect_btn.config(text="Connect", state=tk.NORMAL)
        self.log_message("Disconnected.", "INFO")

    def place_order(self, contract_key: str, contract: Contract, action: str, quantity: int, limit_price: float, enable_chasing: bool) -> Optional[int]:
        if self.connection_state != ConnectionState.CONNECTED or not self.data_server_ok:
            self.log_message("Cannot place order: Not connected or data server not ready.", "ERROR"); return None
        order = Order(); order.action = action; order.totalQuantity = quantity; order.orderType = "LMT"
        order.lmtPrice = self.round_to_spx_increment(limit_price); order.tif = "DAY"; order.transmit = True
        order.account = self.account
        order_id = self.next_order_id; self.next_order_id += 1
        self.log_message(f"Placing Order {order_id}: {action} {quantity} {contract_key} @ {order.lmtPrice}", "INFO")
        self.pending_orders[order_id] = (contract_key, action, quantity)
        if enable_chasing: self.manual_orders[order_id] = {'contract_key': contract_key, 'contract': contract, 'action': action, 'quantity': quantity, 'last_mid': order.lmtPrice}
        self.placeOrder(order_id, contract, order)
        self.add_order_to_tree(order_id, contract, action, quantity, order.lmtPrice, "Submitted")
        if enable_chasing and self.root: self.root.after(1000, self.update_manual_orders)
        return order_id
        
    def round_to_spx_increment(self, price: float) -> float: return round(price / 0.10) * 0.10 if price >= 3.00 else round(price / 0.05) * 0.05
    def get_contract_key(self, contract: Contract) -> str: return f"{contract.symbol}_{int(contract.strike)}_{contract.right}_{contract.lastTradeDateOrContractMonth}"
    def update_time(self): self.root.after(1000, self.update_time); self.time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    def calculate_expiry_date(self, offset): return (datetime.now() + timedelta(days=offset)).strftime("%Y%m%d")
    def on_closing(self): self.disconnect_from_ib(); self.root.destroy()
    def log_message(self, message: str, level: str = "INFO"): 
        print(f"[{level}] {message}"); file_logger.info(f"[{level}] {message}")
        if hasattr(self, 'log_text'): # Log to GUI if available
            self.log_text.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n", level)
            self.log_text.see(tk.END)
            
    def request_option_chain(self):
        # Using manual chain generation
        if self.spx_price == 0: self.root.after(2000, self.request_option_chain); return
        self.log_message("Building manual option chain...", "INFO")
        center_strike = round(self.spx_price / 5) * 5
        strikes = [center_strike + (i * 5) for i in range(-20, 21)]
        sheet_data, self.market_data, self.market_data_map, self.strike_to_row = [], {}, {}, {}
        for row_idx, strike in enumerate(strikes):
            self.strike_to_row[strike] = row_idx
            sheet_data.append(["--"] * 21); sheet_data[row_idx][10] = f"{strike:.2f}"
            for right in ['C', 'P']:
                contract = self.create_option_contract(strike, right)
                contract_key = self.get_contract_key(contract)
                req_id = self.next_req_id; self.next_req_id += 1
                self.market_data_map[req_id] = contract_key
                self.market_data[contract_key] = {'contract': contract, 'right': right, 'strike': strike, 'row_index': row_idx, 'bid': 0, 'ask': 0, 'last': 0, 'volume': 0, 'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0}
                self.reqMktData(req_id, contract, "", False, False, [])
        self.option_sheet.set_sheet_data(sheet_data)
        self.root.after(500, self.update_option_chain_display)
        
    def create_option_contract(self, strike: float, right: str) -> Contract:
        contract = Contract(); contract.symbol = "SPX"; contract.secType = "OPT"; contract.currency = "USD"
        contract.exchange = "SMART"; contract.tradingClass = "SPXW"; contract.strike = strike
        contract.right = right; contract.lastTradeDateOrContractMonth = self.current_expiry; contract.multiplier = "100"
        return contract

    def update_option_chain_display(self):
        if not self.root: return
        try:
            for key, data in self.market_data.items():
                row_idx = data['row_index']
                if data['right'] == 'C':
                    cols = {"iv": 0, "delta": 1, "theta": 2, "vega": 3, "gamma": 4, "volume": 5, "last": 7, "ask": 8, "bid": 9}
                else: # 'P'
                    cols = {"bid": 11, "ask": 12, "last": 13, "volume": 16, "gamma": 17, "vega": 18, "theta": 19, "delta": 20, "iv": 21} # Note: IV is 21 in user's 21-col layout
                    # My layout has 21 columns (0-20), user's has 21 (0-20). User's P_IV is 11, mine is 20.
                    # My header: ["IV", "Delta", "Theta", "Vega", "Gamma", "Vol", "CHANGE %", "Last", "Ask", "Bid", "● STRIKE ●", "Bid", "Ask", "Last", "CHANGE %", "Vol", "Gamma", "Vega", "Theta", "Delta", "IV"]
                    # Col map:
                    # C: IV=0, Delta=1, Theta=2, Vega=3, Gamma=4, Vol=5, Last=7, Ask=8, Bid=9
                    # P: Bid=11, Ask=12, Last=13, Vol=16, Gamma=17, Vega=18, Theta=19, Delta=20, IV=10 ??? Oh, user has two IVs.
                    # My header from merge: ["IV", "Delta", "Theta", "Vega", "Gamma", "Vol", "CHANGE %", "Last", "Ask", "Bid", "● STRIKE ●", "Bid", "Ask", "Last", "CHANGE %", "Vol", "Gamma", "Vega", "Theta", "Delta", "IV"]
                    # Let's re-check user's old header:
                    # c_iv: 9, c_delta: 8 ... c_bid: 0
                    # p_bid: 11, p_ask: 12 ... p_iv: 20
                    # Ok, user's *old* header was: "Imp Vol", "Delta", "Theta", "Vega", "Gamma", "Volume", "CHANGE %", "Last", "Ask", "Bid", "● STRIKE ●", "Bid", "Ask", "Last", "CHANGE %", "Volume", "Gamma", "Vega", "Theta", "Delta", "Imp Vol"
                    # This is 21 columns (0-20). My header is identical.
                    # My Col Map:
                    # C: IV=0, Delta=1, Theta=2, Vega=3, Gamma=4, Vol=5, Last=7, Ask=8, Bid=9
                    # P: Bid=11, Ask=12, Last=13, Vol=16, Gamma=17, Vega=18, Theta=19, Delta=20, IV=10 <-- No, IV is 20. Wait, Delta is 19, IV is 20.
                    # P_Bid=11, P_Ask=12, P_Last=13, P_Change=14, P_Vol=15, P_Gamma=16, P_Vega=17, P_Theta=18, P_Delta=19, P_IV=20
                    cols = {"bid": 11, "ask": 12, "last": 13, "volume": 15, "gamma": 16, "vega": 17, "theta": 18, "delta": 19, "iv": 20}
                    
                for name, col_idx in cols.items():
                    val = data.get(name, 0)
                    if isinstance(val, float): val_str = f"{val:.2f}"
                    else: val_str = str(val)
                    self.option_sheet.set_cell_data(row_idx, col_idx, val_str, redraw=False)
            self.option_sheet.redraw()
        except Exception as e: self.log_message(f"Error updating chain: {e}", "ERROR")
        if self.root: self.root.after(500, self.update_option_chain_display)

    def update_position_on_fill(self, contract_key: str, action: str, quantity: int, fill_price: float):
        if contract_key not in self.positions:
            data = self.market_data[contract_key]
            self.positions[contract_key] = {'contract': data['contract'], 'position': quantity if action == "BUY" else -quantity, 'avgCost': fill_price, 'currentPrice': fill_price, 'pnl': 0, 'entryTime': datetime.now()}
        else:
            pos = self.positions[contract_key]; old_qty, old_cost = pos['position'], pos['avgCost']
            new_qty = (old_qty + quantity) if action == "BUY" else (old_qty - quantity)
            pos['avgCost'] = ((old_qty * old_cost) + (quantity * fill_price)) / new_qty if new_qty != 0 and action == "BUY" else old_cost
            pos['position'] = new_qty
            if new_qty == 0: del self.positions[contract_key]
        self.update_positions_display()

    def update_order_in_tree(self, order_id: int, status: str, price: Optional[float] = None):
        try:
            data = self.order_sheet.get_sheet_data()
            for i, row in enumerate(data):
                if row and len(row) > 0 and str(row[0]) == str(order_id):
                    if status in ["Filled", "Cancelled", "Inactive"]: data.pop(i); self.order_sheet.set_sheet_data(data); break
                    else:
                        if price is not None: self.order_sheet.set_cell_data(i, 4, f"${price:.2f}")
                        self.order_sheet.set_cell_data(i, 5, status)
                        break
        except Exception as e: self.log_message(f"Error updating order sheet: {e}", "ERROR")
        
    def add_order_to_tree(self, order_id: int, contract: Contract, action: str, quantity: int, price: float, status: str):
        try:
            new_row = [str(order_id), self.get_contract_key(contract), action, str(quantity), f"${price:.2f}", status, "Cancel"]
            self.order_sheet.insert_row(new_row)
        except Exception as e: self.log_message(f"Error adding to order sheet: {e}", "ERROR")

    def update_spx_price_display(self): self.spx_price_label.config(text=f"SPX: {self.spx_price:.2f}")
    
    def update_positions_display(self):
        if not self.root: return
        rows = []
        total_pnl = 0
        for contract_key, pos in self.positions.items():
            self.update_position_pnl(contract_key)
            pnl = pos['pnl']; pnl_pct = (pos['currentPrice'] / pos['avgCost'] - 1) * 100 if pos['avgCost'] > 0 else 0
            rows.append([contract_key, f"{pos['position']:.0f}", f"${pos['avgCost']:.2f}", f"${pos['currentPrice']:.2f}", f"${pnl:.2f}", f"{pnl_pct:.2f}%", "Close"])
            total_pnl += pnl
        self.position_sheet.set_sheet_data(rows)
        for row_idx, (key, pos) in enumerate(self.positions.items()):
            fg = "#00FF00" if pos['pnl'] > 0 else ("#FF0000" if pos['pnl'] < 0 else "#FFFFFF")
            self.position_sheet.highlight_cells(row=row_idx, column=4, fg=fg); self.position_sheet.highlight_cells(row=row_idx, column=5, fg=fg)
            self.position_sheet.highlight_cells(row=row_idx, column=6, fg="#FFFFFF", bg="#CC0000")
        self.pnl_label.config(text=f"Total PnL: ${total_pnl:.2f}", foreground="#00FF00" if total_pnl >= 0 else "#FF0000")
        if self.root: self.root.after(1000, self.update_positions_display)

    def update_position_pnl(self, contract_key: str, current_price: float | None = None):
        if contract_key in self.positions:
            pos = self.positions[contract_key]
            if current_price is None and contract_key in self.market_data:
                data = self.market_data[contract_key]; bid, ask = data.get('bid', 0), data.get('ask', 0)
                current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else data.get('last', pos['avgCost'])
            elif current_price is None: current_price = pos.get('currentPrice', pos['avgCost'])
            if current_price: pos['currentPrice'] = current_price; pos['pnl'] = (current_price - pos['avgCost']) * pos['position'] * 100
            
    # Manual Trading
    def manual_buy_call(self): self.manual_trade_action("C")
    def manual_buy_put(self): self.manual_trade_action("P")
    def manual_trade_action(self, option_type: str):
        if self.connection_state != ConnectionState.CONNECTED or not self.data_server_ok:
            messagebox.showerror("Not Connected", "Please connect to IBKR and wait for data server confirmation."); return
        try: max_risk = float(self.max_risk_var.get())
        except ValueError: messagebox.showerror("Invalid Input", "Please enter a valid max risk amount"); return
        self.log_message(f"MANUAL TRADE: Finding {option_type} with max risk ${max_risk:.2f}", "INFO")
        result = self.find_option_by_max_risk(option_type, max_risk)
        if not result: messagebox.showwarning("No Options Found", f"No {option_type} options found with ask price <= ${max_risk/100:.2f}"); return
        contract_key, contract, ask_price = result
        mid_price = self.calculate_mid_price(contract_key) or ask_price
        self.place_order(contract_key, contract, "BUY", 1, mid_price, enable_chasing=True)

    def find_option_by_max_risk(self, option_type: str, max_risk_dollars: float) -> Optional[Tuple[str, Contract, float]]:
        max_price, best_option, best_price, best_contract_key = max_risk_dollars / 100.0, None, 0.0, None
        for key, data in self.market_data.items():
            if data.get('right') == option_type:
                ask = data.get('ask', 0)
                if 0 < ask <= max_price and ask > best_price:
                    best_price, best_option, best_contract_key = ask, data.get('contract'), key
        if best_option: return (best_contract_key, best_option, best_price)
        return None
        
    def calculate_mid_price(self, contract_key: str) -> float:
        data = self.market_data.get(contract_key); bid, ask = data.get('bid', 0), data.get('ask', 0)
        return self.round_to_spx_increment((bid + ask) / 2.0) if bid > 0 and ask > 0 else 0.0
        
    def update_manual_orders(self):
        orders_to_remove = []
        for order_id, info in self.manual_orders.items():
            if order_id not in self.pending_orders: orders_to_remove.append(order_id); continue
            current_mid = self.calculate_mid_price(info['contract_key'])
            if current_mid > 0 and abs(current_mid - info['last_mid']) >= 0.05:
                self.log_message(f"Order {order_id}: Mid price moved. Chasing from {info['last_mid']:.2f} to {current_mid:.2f}", "INFO")
                order = Order(); order.action = info['action']; order.totalQuantity = info['quantity']; order.orderType = "LMT"
                order.lmtPrice = current_mid; order.tif = "DAY"; order.transmit = True; order.account = self.account
                self.placeOrder(order_id, info['contract'], order) # Modify order
                info['last_mid'] = current_mid
                self.update_order_in_tree(order_id, "Chasing Mid", current_mid)
        for oid in orders_to_remove: del self.manual_orders[oid]
        if self.manual_orders and self.root: self.root.after(1000, self.update_manual_orders)

    def on_position_sheet_click(self, event):
        try:
            selected = self.position_sheet.get_currently_selected()
            if not selected or selected.column != 6: return # Col 6 is "Action"
            contract_key = self.position_sheet.get_row_data(selected.row)[0]
            if contract_key not in self.positions: return
            pos = self.positions[contract_key]
            if not messagebox.askyesno("Close Position", f"Close {pos['position']}x {contract_key}?"): return
            mid_price = self.calculate_mid_price(contract_key) or pos['currentPrice']
            self.place_order(contract_key, pos['contract'], "SELL", int(abs(pos['position'])), mid_price, enable_chasing=True)
        except Exception as e: self.log_message(f"Error closing position: {e}", "ERROR")

    def on_order_sheet_click(self, event):
        try:
            selected = self.order_sheet.get_currently_selected()
            if not selected or selected.column != 6: return # Col 6 is "Cancel"
            order_id = int(self.order_sheet.get_row_data(selected.row)[0])
            if not messagebox.askyesno("Cancel Order", f"Cancel order {order_id}?"): return
            self.cancelOrder(order_id); self.log_message(f"Cancelling order {order_id}", "INFO")
            if order_id in self.manual_orders: del self.manual_orders[order_id]
            if order_id in self.pending_orders: del self.pending_orders[order_id]
        except Exception as e: self.log_message(f"Error cancelling order: {e}", "ERROR")

    def run_gui(self):
        self.load_settings()
        self.update_positions_display() # Start position update loop
        self.root.mainloop()

if __name__ == "__main__":
    app = SPXTradingApp()
    app.run_gui()

