"""
SPX 0DTE Options Trading Application
Professional Bloomberg-style GUI for Interactive Brokers API
Author: VJS World
Date: October 15, 2025
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, YES, X, Y, LEFT, RIGHT, BOTTOM, TOP, CENTER, END, W, SUNKEN, HORIZONTAL, VERTICAL
import threading
import queue
import time
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import json
import os
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import pandas as pd
import numpy as np
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from ttkbootstrap import Window
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Interactive Brokers API imports
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.common import TickerId, TickAttrib
from ibapi.ticktype import TickType


# ============================================================================
# CONNECTION STATE MACHINE
# ============================================================================

class ConnectionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


# ============================================================================
# IBKR API WRAPPER
# ============================================================================

class IBKRWrapper(EWrapper):
    """Wrapper to handle all incoming messages from IBKR"""
    
    def __init__(self, app):
        EWrapper.__init__(self)
        self.app = app
    
    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        """Handle error messages"""
        error_msg = f"Error {errorCode}: {errorString}"
        self.app.log_message(error_msg, "ERROR")
        
        # Connection-related errors
        if errorCode in [502, 503, 504, 1100, 2110]:
            self.app.connection_state = ConnectionState.DISCONNECTED
            self.app.schedule_reconnect()
        
        # Market data errors
        elif errorCode == 354:  # Requested market data is not subscribed
            self.app.log_message(f"Market data not available for reqId {reqId}", "WARNING")
    
    def connectAck(self):
        """Called when connection is acknowledged"""
        self.app.log_message("Connection acknowledged", "INFO")
    
    def nextValidId(self, orderId: int):
        """Receives next valid order ID"""
        self.app.next_order_id = orderId
        self.app.connection_state = ConnectionState.CONNECTED
        self.app.log_message(f"Connected! Next Order ID: {orderId}", "SUCCESS")
        self.app.on_connected()
    
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str,
                                         underlyingConId: int, tradingClass: str,
                                         multiplier: str, expirations: set,
                                         strikes: set):
        """Receives option chain parameters"""
        self.app.option_chain_data[reqId] = {
            'exchange': exchange,
            'tradingClass': tradingClass,
            'multiplier': multiplier,
            'expirations': expirations,
            'strikes': sorted(list(strikes))
        }
    
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        """Called when option parameter request is complete"""
        self.app.log_message(f"Option chain data received for reqId {reqId}", "INFO")
        self.app.process_option_chain()
    
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float,
                  attrib: TickAttrib):
        """Receives real-time price updates"""
        if reqId in self.app.market_data_map:
            contract_key = self.app.market_data_map[reqId]
            
            if tickType == 1:  # BID
                self.app.market_data[contract_key]['bid'] = price
            elif tickType == 2:  # ASK
                self.app.market_data[contract_key]['ask'] = price
            elif tickType == 4:  # LAST
                self.app.market_data[contract_key]['last'] = price
                
                # Update position PnL if this is a held position
                self.app.update_position_pnl(contract_key, price)
    
    def tickSize(self, reqId: TickerId, tickType: TickType, size: int):
        """Receives real-time size updates"""
        if reqId in self.app.market_data_map:
            contract_key = self.app.market_data_map[reqId]
            
            if tickType == 8:  # VOLUME
                self.app.market_data[contract_key]['volume'] = size
    
    def tickOptionComputation(self, reqId: TickerId, tickType: TickType,
                             tickAttrib: int, impliedVol: float,
                             delta: float, optPrice: float, pvDividend: float,
                             gamma: float, vega: float, theta: float,
                             undPrice: float):
        """Receives option greeks"""
        if reqId in self.app.market_data_map:
            contract_key = self.app.market_data_map[reqId]
            
            self.app.market_data[contract_key].update({
                'delta': delta if delta != -2 else 0,
                'gamma': gamma if gamma != -2 else 0,
                'theta': theta if theta != -2 else 0,
                'vega': vega if vega != -2 else 0,
                'impliedVol': impliedVol if impliedVol != -2 else 0
            })
    
    def orderStatus(self, orderId: int, status: str, filled: float,
                   remaining: float, avgFillPrice: float, permId: int,
                   parentId: int, lastFillPrice: float, clientId: int,
                   whyHeld: str, mktCapPrice: float):
        """Receives order status updates"""
        order_info = {
            'orderId': orderId,
            'status': status,
            'filled': filled,
            'remaining': remaining,
            'avgFillPrice': avgFillPrice,
            'lastFillPrice': lastFillPrice
        }
        
        self.app.order_status[orderId] = order_info
        self.app.log_message(f"Order {orderId}: {status} - Filled: {filled} @ {avgFillPrice}", "INFO")
        
        # If order is filled, update position
        if status == "Filled" and orderId in self.app.pending_orders:
            contract_key, action, quantity = self.app.pending_orders[orderId]
            self.app.update_position_on_fill(contract_key, action, quantity, avgFillPrice)
            del self.app.pending_orders[orderId]
    
    def openOrder(self, orderId: int, contract: Contract, order: Order,
                 orderState):
        """Receives open order information"""
        contract_key = f"{contract.symbol}_{contract.strike}_{contract.right}"
        self.app.log_message(f"Open Order {orderId}: {contract_key} {order.action} {order.totalQuantity}", "INFO")
    
    def position(self, account: str, contract: Contract, position: float,
                avgCost: float):
        """Receives position updates"""
        contract_key = f"{contract.symbol}_{contract.strike}_{contract.right}"
        
        if position != 0:
            self.app.positions[contract_key] = {
                'contract': contract,
                'position': position,
                'avgCost': avgCost,
                'currentPrice': 0,
                'pnl': 0,
                'entryTime': datetime.now()
            }
    
    def historicalData(self, reqId: int, bar):
        """Receives historical bar data"""
        if reqId in self.app.historical_data_requests:
            contract_key = self.app.historical_data_requests[reqId]
            
            if contract_key not in self.app.historical_data:
                self.app.historical_data[contract_key] = []
            
            self.app.historical_data[contract_key].append({
                'date': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })
    
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        """Called when historical data request is complete"""
        if reqId in self.app.historical_data_requests:
            contract_key = self.app.historical_data_requests[reqId]
            self.app.calculate_supertrend(contract_key)


# ============================================================================
# IBKR API CLIENT
# ============================================================================

class IBKRClient(EClient):
    """Client to send requests to IBKR"""
    
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class SPXTradingApp(IBKRWrapper, IBKRClient):
    """Main SPX 0DTE Trading Application"""
    
    def __init__(self):
        IBKRWrapper.__init__(self, self)
        IBKRClient.__init__(self, wrapper=self)
        
        # Connection management
        self.connection_state = ConnectionState.DISCONNECTED
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        
        # API settings
        self.host = "127.0.0.1"
        self.port = 7497  # Paper trading
        self.client_id = 101
        
        # Strategy parameters
        self.atr_period = 14
        self.chandelier_multiplier = 3.0
        
        # Request ID management
        self.next_order_id = 1
        self.next_req_id = 1000
        
        # Data storage
        self.option_chain_data = {}
        self.market_data = {}
        self.market_data_map = {}  # reqId -> contract_key
        self.historical_data = {}
        self.historical_data_requests = {}  # reqId -> contract_key
        self.positions = {}
        self.order_status = {}
        self.pending_orders = {}  # orderId -> (contract_key, action, quantity)
        
        # Option chain
        self.current_expiry = datetime.now().strftime("%Y%m%d")
        self.spx_contracts = []  # List of all 0DTE contracts
        
        # Trading state
        self.last_trade_hour = -1
        self.active_straddles = []  # List of active straddle positions
        
        # Supertrend data for each position
        self.supertrend_data = {}  # contract_key -> supertrend values
        
        # Queues for thread communication
        self.gui_queue = queue.Queue()
        self.api_queue = queue.Queue()
        
        # Threading
        self.api_thread = None
        self.running = False
        
        # GUI - Will be initialized in setup_gui()
        self.root: Optional['ttk.Window'] = None
        self.setup_gui()
        
    def setup_gui(self):
        """Initialize the GUI"""
        self.root = ttk.Window(themename="darkly")
        self.root.title("SPX 0DTE Options Trader - Professional Edition")
        self.root.geometry("1600x900")
        
        # Apply custom color scheme
        style = ttk.Style()
        style.configure('.', background='#181818', foreground='#E0E0E0')
        style.configure('TFrame', background='#181818')
        style.configure('TLabel', background='#181818', foreground='#E0E0E0')
        style.configure('TButton', bordercolor='#FF8C00', focuscolor='#FF8C00')
        style.configure('Treeview', background='#202020', foreground='#E0E0E0',
                       fieldbackground='#202020', bordercolor='#FF8C00')
        style.configure('Treeview.Heading', background='#2A2A2A', foreground='#FF8C00',
                       bordercolor='#FF8C00')
        
        # Create main container
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=BOTH, expand=YES)
        
        # Tab 1: Trading Dashboard
        self.create_trading_tab()
        
        # Tab 2: Settings
        self.create_settings_tab()
        
        # Status bar at bottom
        self.create_status_bar()
        
        # Start GUI update loop
        self.root.after(100, self.process_gui_queue)
        
        # Start time checker for hourly trades
        self.root.after(1000, self.check_trade_time)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_trading_tab(self):
        """Create the main trading dashboard tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Option Chain & Trading Dashboard")
        
        # Create main paned window for resizable sections
        paned = ttk.PanedWindow(tab, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=YES)
        
        # Left panel: Option Chain
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=3)
        
        # Option Chain label and controls
        chain_header = ttk.Frame(left_frame)
        chain_header.pack(fill=X, padx=5, pady=5)
        
        ttk.Label(chain_header, text="SPX 0DTE Option Chain", 
                 font=("Arial", 14, "bold")).pack(side=LEFT)
        
        ttk.Button(chain_header, text="Refresh Chain", 
                  command=self.request_option_chain,
                  style="warning.TButton").pack(side=RIGHT, padx=5)
        
        # Option Chain Treeview
        chain_frame = ttk.Frame(left_frame)
        chain_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Scrollbars
        chain_vsb = ttk.Scrollbar(chain_frame, orient="vertical")
        chain_vsb.pack(side=RIGHT, fill=Y)
        
        chain_hsb = ttk.Scrollbar(chain_frame, orient="horizontal")
        chain_hsb.pack(side=BOTTOM, fill=X)
        
        # Treeview
        columns = ("Type", "Strike", "Bid", "Ask", "Last", "Volume", 
                  "Delta", "Gamma", "Theta", "Vega")
        self.option_tree = ttk.Treeview(chain_frame, columns=columns, 
                                       show="headings", height=25,
                                       yscrollcommand=chain_vsb.set,
                                       xscrollcommand=chain_hsb.set)
        
        chain_vsb.config(command=self.option_tree.yview)
        chain_hsb.config(command=self.option_tree.xview)
        
        # Configure columns
        col_widths = {"Type": 60, "Strike": 80, "Bid": 70, "Ask": 70, 
                     "Last": 70, "Volume": 80, "Delta": 70, "Gamma": 70, 
                     "Theta": 70, "Vega": 70}
        
        for col in columns:
            self.option_tree.heading(col, text=col)
            self.option_tree.column(col, width=col_widths.get(col, 100), 
                                   anchor=CENTER)
        
        self.option_tree.pack(fill=BOTH, expand=YES)
        
        # Right panel: Positions, Orders, and Log
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=2)
        
        # Positions section
        pos_label = ttk.Label(right_frame, text="Open Positions", 
                             font=("Arial", 12, "bold"))
        pos_label.pack(fill=X, padx=5, pady=(5, 0))
        
        pos_frame = ttk.Frame(right_frame)
        pos_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        pos_vsb = ttk.Scrollbar(pos_frame, orient="vertical")
        pos_vsb.pack(side=RIGHT, fill=Y)
        
        pos_columns = ("Contract", "Qty", "Avg Cost", "Last", "PnL", "PnL%")
        self.position_tree = ttk.Treeview(pos_frame, columns=pos_columns,
                                         show="headings", height=8,
                                         yscrollcommand=pos_vsb.set)
        pos_vsb.config(command=self.position_tree.yview)
        
        for col in pos_columns:
            self.position_tree.heading(col, text=col)
            self.position_tree.column(col, width=100, anchor=CENTER)
        
        self.position_tree.pack(fill=BOTH, expand=YES)
        
        # Orders section
        order_label = ttk.Label(right_frame, text="Active Orders", 
                               font=("Arial", 12, "bold"))
        order_label.pack(fill=X, padx=5, pady=(5, 0))
        
        order_frame = ttk.Frame(right_frame)
        order_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        order_vsb = ttk.Scrollbar(order_frame, orient="vertical")
        order_vsb.pack(side=RIGHT, fill=Y)
        
        order_columns = ("Order ID", "Contract", "Action", "Qty", "Status")
        self.order_tree = ttk.Treeview(order_frame, columns=order_columns,
                                      show="headings", height=6,
                                      yscrollcommand=order_vsb.set)
        order_vsb.config(command=self.order_tree.yview)
        
        for col in order_columns:
            self.order_tree.heading(col, text=col)
            self.order_tree.column(col, width=100, anchor=CENTER)
        
        self.order_tree.pack(fill=BOTH, expand=YES)
        
        # Chart section with Matplotlib
        chart_label = ttk.Label(right_frame, text="Supertrend Chart", 
                               font=("Arial", 12, "bold"))
        chart_label.pack(fill=X, padx=5, pady=(5, 0))
        
        chart_frame = ttk.Frame(right_frame)
        chart_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        self.fig = Figure(figsize=(6, 3), dpi=80, facecolor='#181818')
        self.ax = self.fig.add_subplot(111, facecolor='#202020')
        self.ax.tick_params(colors='#E0E0E0')
        self.ax.spines['bottom'].set_color('#FF8C00')
        self.ax.spines['top'].set_color('#FF8C00')
        self.ax.spines['left'].set_color('#FF8C00')
        self.ax.spines['right'].set_color('#FF8C00')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
        
        # Log section
        log_label = ttk.Label(right_frame, text="Activity Log", 
                             font=("Arial", 12, "bold"))
        log_label.pack(fill=X, padx=5, pady=(5, 0))
        
        log_frame = ttk.Frame(right_frame)
        log_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical")
        log_vsb.pack(side=RIGHT, fill=Y)
        
        self.log_text = tk.Text(log_frame, height=10, bg='#202020', 
                               fg='#E0E0E0', font=("Consolas", 9),
                               yscrollcommand=log_vsb.set, wrap=tk.WORD)
        log_vsb.config(command=self.log_text.yview)
        self.log_text.pack(fill=BOTH, expand=YES)
        
        # Configure tags for different log levels
        self.log_text.tag_config("ERROR", foreground="#FF4444")
        self.log_text.tag_config("WARNING", foreground="#FFA500")
        self.log_text.tag_config("SUCCESS", foreground="#44FF44")
        self.log_text.tag_config("INFO", foreground="#E0E0E0")
    
    def create_settings_tab(self):
        """Create the settings tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Settings")
        
        # Create scrollable frame
        canvas = tk.Canvas(tab, bg='#181818', highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Connection Settings Section
        conn_frame = ttk.LabelFrame(scrollable_frame, text="Connection Settings", 
                                   padding=20)
        conn_frame.pack(fill=X, padx=20, pady=10)
        
        ttk.Label(conn_frame, text="Host IP:").grid(row=0, column=0, sticky=W, pady=5)
        self.host_entry = ttk.Entry(conn_frame, width=30)
        self.host_entry.insert(0, self.host)
        self.host_entry.grid(row=0, column=1, sticky=W, padx=10, pady=5)
        
        ttk.Label(conn_frame, text="Port:").grid(row=1, column=0, sticky=W, pady=5)
        self.port_entry = ttk.Entry(conn_frame, width=30)
        self.port_entry.insert(0, str(self.port))
        self.port_entry.grid(row=1, column=1, sticky=W, padx=10, pady=5)
        
        ttk.Label(conn_frame, text="Client ID:").grid(row=2, column=0, sticky=W, pady=5)
        self.client_entry = ttk.Entry(conn_frame, width=30)
        self.client_entry.insert(0, str(self.client_id))
        self.client_entry.grid(row=2, column=1, sticky=W, padx=10, pady=5)
        
        # Strategy Settings Section
        strategy_frame = ttk.LabelFrame(scrollable_frame, text="Strategy Parameters",
                                       padding=20)
        strategy_frame.pack(fill=X, padx=20, pady=10)
        
        ttk.Label(strategy_frame, text="ATR Period:").grid(row=0, column=0, 
                                                           sticky=W, pady=5)
        self.atr_entry = ttk.Entry(strategy_frame, width=30)
        self.atr_entry.insert(0, str(self.atr_period))
        self.atr_entry.grid(row=0, column=1, sticky=W, padx=10, pady=5)
        
        ttk.Label(strategy_frame, text="Chandelier Exit Multiplier:").grid(
            row=1, column=0, sticky=W, pady=5)
        self.chandelier_entry = ttk.Entry(strategy_frame, width=30)
        self.chandelier_entry.insert(0, str(self.chandelier_multiplier))
        self.chandelier_entry.grid(row=1, column=1, sticky=W, padx=10, pady=5)
        
        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=X, padx=20, pady=20)
        
        ttk.Button(button_frame, text="Save & Reconnect", 
                  command=self.save_and_reconnect,
                  style="success.TButton", width=20).pack(side=LEFT, padx=5)
        
        ttk.Button(button_frame, text="Save Settings", 
                  command=self.save_settings,
                  style="info.TButton", width=20).pack(side=LEFT, padx=5)
        
        canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)
    
    def create_status_bar(self):
        """Create status bar at bottom of window"""
        status_frame = ttk.Frame(self.root, relief=tk.SUNKEN)
        status_frame.pack(side=BOTTOM, fill=X)
        
        # Connection status
        self.status_label = ttk.Label(status_frame, text="Status: Disconnected",
                                     font=("Arial", 10))
        self.status_label.pack(side=LEFT, padx=10, pady=5)
        
        # Connect/Disconnect button
        self.connect_btn = ttk.Button(status_frame, text="Connect",
                                     command=self.toggle_connection,
                                     style="success.TButton", width=15)
        self.connect_btn.pack(side=LEFT, padx=5, pady=5)
        
        # Total PnL
        self.pnl_label = ttk.Label(status_frame, text="Total PnL: $0.00",
                                  font=("Arial", 10, "bold"))
        self.pnl_label.pack(side=RIGHT, padx=10, pady=5)
        
        # Time
        self.time_label = ttk.Label(status_frame, text="",
                                   font=("Arial", 10))
        self.time_label.pack(side=RIGHT, padx=10, pady=5)
        
        self.update_time()
    
    def update_time(self):
        """Update time display"""
        if not self.root:
            return
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self.update_time)
    
    # ========================================================================
    # CONNECTION MANAGEMENT
    # ========================================================================
    
    def toggle_connection(self):
        """Connect or disconnect from IBKR"""
        if self.connection_state == ConnectionState.CONNECTED:
            self.disconnect_from_ib()
        else:
            self.connect_to_ib()
    
    def connect_to_ib(self):
        """Establish connection to IBKR"""
        if self.connection_state != ConnectionState.DISCONNECTED:
            self.log_message("Already connected or connecting", "WARNING")
            return
        
        self.connection_state = ConnectionState.CONNECTING
        self.status_label.config(text="Status: Connecting...")
        self.connect_btn.config(state=tk.DISABLED)
        
        # Start API thread
        self.running = True
        self.api_thread = threading.Thread(target=self.run_api_thread, daemon=True)
        self.api_thread.start()
        
        self.log_message(f"Connecting to {self.host}:{self.port}...", "INFO")
    
    def run_api_thread(self):
        """Run the API thread"""
        try:
            EClient.connect(self, self.host, self.port, self.client_id)
            self.run()
        except Exception as e:
            self.log_message(f"API thread error: {str(e)}", "ERROR")
            self.connection_state = ConnectionState.DISCONNECTED
            self.schedule_reconnect()
    
    def disconnect_from_ib(self):
        """Disconnect from IBKR"""
        self.running = False
        EClient.disconnect(self)
        self.connection_state = ConnectionState.DISCONNECTED
        self.status_label.config(text="Status: Disconnected")
        self.connect_btn.config(text="Connect", state=tk.NORMAL)
        self.log_message("Disconnected from IBKR", "INFO")
    
    def schedule_reconnect(self):
        """Schedule automatic reconnection"""
        if not self.root:
            return
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.log_message("Max reconnection attempts reached. Please reconnect manually.", 
                           "ERROR")
            self.reconnect_attempts = 0
            return
        
        self.reconnect_attempts += 1
        self.log_message(f"Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} "
                        f"in {self.reconnect_delay} seconds...", "WARNING")
        
        self.root.after(self.reconnect_delay * 1000, self.connect_to_ib)
    
    def on_connected(self):
        """Called when successfully connected"""
        self.reconnect_attempts = 0
        self.status_label.config(text="Status: Connected")
        self.connect_btn.config(text="Disconnect", state=tk.NORMAL)
        
        # Request option chain
        self.request_option_chain()
        
        # Request account updates
        self.reqAccountUpdates(True, "")
    
    def save_and_reconnect(self):
        """Save settings and reconnect"""
        if not self.root:
            return
        self.save_settings()
        
        if self.connection_state == ConnectionState.CONNECTED:
            self.disconnect_from_ib()
            self.root.after(1000, self.connect_to_ib)
        else:
            self.connect_to_ib()
    
    def save_settings(self):
        """Save settings to file"""
        try:
            self.host = self.host_entry.get()
            self.port = int(self.port_entry.get())
            self.client_id = int(self.client_entry.get())
            self.atr_period = int(self.atr_entry.get())
            self.chandelier_multiplier = float(self.chandelier_entry.get())
            
            settings = {
                'host': self.host,
                'port': self.port,
                'client_id': self.client_id,
                'atr_period': self.atr_period,
                'chandelier_multiplier': self.chandelier_multiplier
            }
            
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            
            self.log_message("Settings saved successfully", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error saving settings: {str(e)}", "ERROR")
    
    def load_settings(self):
        """Load settings from file"""
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    settings = json.load(f)
                
                self.host = settings.get('host', self.host)
                self.port = settings.get('port', self.port)
                self.client_id = settings.get('client_id', self.client_id)
                self.atr_period = settings.get('atr_period', self.atr_period)
                self.chandelier_multiplier = settings.get('chandelier_multiplier', 
                                                         self.chandelier_multiplier)
                
                self.log_message("Settings loaded successfully", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error loading settings: {str(e)}", "ERROR")
    
    # ========================================================================
    # OPTION CHAIN MANAGEMENT
    # ========================================================================
    
    def create_spxw_contract(self, strike: float, right: str) -> Contract:
        """Create a SPXW 0DTE option contract"""
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.tradingClass = "SPXW"
        contract.strike = strike
        contract.right = right  # "C" or "P"
        contract.lastTradeDateOrContractMonth = self.current_expiry
        contract.multiplier = "100"
        return contract
    
    def request_option_chain(self):
        """Request the 0DTE SPX option chain"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Not connected to IBKR", "WARNING")
            return
        
        self.log_message("Requesting option chain...", "INFO")
        
        # Create SPX underlying contract
        spx_contract = Contract()
        spx_contract.symbol = "SPX"
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Request option parameters
        req_id = self.next_req_id
        self.next_req_id += 1
        
        self.reqSecDefOptParams(req_id, "SPX", "", "IND", 416563234)
    
    def process_option_chain(self):
        """Process received option chain data"""
        if not self.option_chain_data:
            self.log_message("No option chain data received", "WARNING")
            return
        
        # Get today's strikes
        for req_id, data in self.option_chain_data.items():
            expirations = data['expirations']
            strikes = data['strikes']
            
            # Filter for today's expiration
            if self.current_expiry in expirations:
                self.log_message(f"Found {len(strikes)} strikes for {self.current_expiry}", 
                               "SUCCESS")
                
                # Create contracts for all strikes
                self.spx_contracts = []
                
                for strike in strikes:
                    # Create call and put contracts
                    call_contract = self.create_spxw_contract(strike, "C")
                    put_contract = self.create_spxw_contract(strike, "P")
                    
                    self.spx_contracts.append(('C', strike, call_contract))
                    self.spx_contracts.append(('P', strike, put_contract))
                
                # Subscribe to market data
                self.subscribe_market_data()
                break
    
    def subscribe_market_data(self):
        """Subscribe to real-time market data for all contracts"""
        if not self.root:
            return
        self.log_message(f"Subscribing to market data for {len(self.spx_contracts)} contracts...", 
                        "INFO")
        
        # Clear existing data
        self.market_data.clear()
        self.market_data_map.clear()
        
        # Clear treeview
        for item in self.option_tree.get_children():
            self.option_tree.delete(item)
        
        for right, strike, contract in self.spx_contracts:
            req_id = self.next_req_id
            self.next_req_id += 1
            
            contract_key = f"SPX_{strike}_{right}"
            
            # Initialize market data
            self.market_data[contract_key] = {
                'contract': contract,
                'right': right,
                'strike': strike,
                'bid': 0,
                'ask': 0,
                'last': 0,
                'volume': 0,
                'delta': 0,
                'gamma': 0,
                'theta': 0,
                'vega': 0,
                'tree_item': None
            }
            
            # Map reqId to contract_key
            self.market_data_map[req_id] = contract_key
            
            # Insert into treeview
            values = (right, f"{strike:.2f}", "0.00", "0.00", "0.00", "0",
                     "0.00", "0.00", "0.00", "0.00")
            item = self.option_tree.insert("", tk.END, values=values)
            self.market_data[contract_key]['tree_item'] = item
            
            # Request market data
            self.reqMktData(req_id, contract, "", False, False, [])
        
        self.log_message("Market data subscription complete", "SUCCESS")
        
        # Start updating GUI with market data
        self.root.after(500, self.update_option_chain_display)
    
    def update_option_chain_display(self):
        """Update the option chain display with latest market data"""
        if not self.root:
            return
        for contract_key, data in self.market_data.items():
            if data['tree_item']:
                values = (
                    data['right'],
                    f"{data['strike']:.2f}",
                    f"{data['bid']:.2f}",
                    f"{data['ask']:.2f}",
                    f"{data['last']:.2f}",
                    f"{data['volume']}",
                    f"{data['delta']:.4f}",
                    f"{data['gamma']:.4f}",
                    f"{data['theta']:.4f}",
                    f"{data['vega']:.4f}"
                )
                self.option_tree.item(data['tree_item'], values=values)
        
        # Schedule next update
        self.root.after(500, self.update_option_chain_display)
    
    # ========================================================================
    # TRADING LOGIC
    # ========================================================================
    
    def check_trade_time(self):
        """Check if it's time to enter a new straddle"""
        if not self.root:
            return
        now = datetime.now()
        
        # Check if it's the top of the hour
        if now.minute == 0 and now.second == 0:
            if self.last_trade_hour != now.hour:
                self.last_trade_hour = now.hour
                self.log_message(f"Hourly trigger at {now.strftime('%H:%M:%S')}", "INFO")
                self.enter_straddle()
        
        # Schedule next check
        self.root.after(1000, self.check_trade_time)
    
    def enter_straddle(self):
        """Enter a long straddle at the top of the hour"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot enter straddle: Not connected", "WARNING")
            return
        
        self.log_message("Scanning for straddle entry opportunities...", "INFO")
        
        # Find cheapest call and put with ask <= $0.50
        best_call = None
        best_call_key = None
        best_put = None
        best_put_key = None
        
        for contract_key, data in self.market_data.items():
            ask = data['ask']
            
            if ask <= 0.50 and ask > 0:
                if data['right'] == 'C':
                    if best_call is None or ask < best_call['ask']:
                        best_call = data
                        best_call_key = contract_key
                elif data['right'] == 'P':
                    if best_put is None or ask < best_put['ask']:
                        best_put = data
                        best_put_key = contract_key
        
        # Place orders if we found both legs
        if best_call and best_put:
            self.log_message(f"Selected Call: Strike {best_call['strike']:.2f} @ ${best_call['ask']:.2f}", 
                           "SUCCESS")
            self.log_message(f"Selected Put: Strike {best_put['strike']:.2f} @ ${best_put['ask']:.2f}", 
                           "SUCCESS")
            
            # Place call order
            call_order_id = self.place_limit_order(best_call['contract'], "BUY", 1, 
                                                   best_call['ask'])
            self.pending_orders[call_order_id] = (best_call_key, "BUY", 1)
            
            # Place put order
            put_order_id = self.place_limit_order(best_put['contract'], "BUY", 1, 
                                                  best_put['ask'])
            self.pending_orders[put_order_id] = (best_put_key, "BUY", 1)
            
            # Track straddle
            self.active_straddles.append({
                'call_key': best_call_key,
                'put_key': best_put_key,
                'entry_time': datetime.now(),
                'call_entry_price': best_call['ask'],
                'put_entry_price': best_put['ask']
            })
        else:
            self.log_message("No suitable options found for straddle (ask <= $0.50)", "WARNING")
    
    def place_limit_order(self, contract: Contract, action: str, quantity: int, 
                         limit_price: float) -> int:
        """Place a limit order"""
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = "LMT"
        order.lmtPrice = limit_price
        order.tif = "DAY"
        order.transmit = True
        
        order_id = self.next_order_id
        self.next_order_id += 1
        
        self.placeOrder(order_id, contract, order)
        
        self.log_message(f"Placed {action} order #{order_id}: {quantity} @ ${limit_price:.2f}", 
                        "INFO")
        
        # Add to order tree
        self.add_order_to_tree(order_id, contract, action, quantity, "Submitted")
        
        return order_id
    
    def place_stop_limit_order(self, contract: Contract, action: str, quantity: int,
                              stop_price: float, limit_price: float) -> int:
        """Place a stop-limit order"""
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = "STP LMT"
        order.auxPrice = stop_price
        order.lmtPrice = limit_price
        order.tif = "DAY"
        order.transmit = True
        
        order_id = self.next_order_id
        self.next_order_id += 1
        
        self.placeOrder(order_id, contract, order)
        
        self.log_message(f"Placed {action} STP LMT order #{order_id}: {quantity} @ "
                        f"Stop ${stop_price:.2f} Limit ${limit_price:.2f}", "INFO")
        
        # Add to order tree
        self.add_order_to_tree(order_id, contract, action, quantity, "Submitted")
        
        return order_id
    
    def update_position_on_fill(self, contract_key: str, action: str, 
                               quantity: int, fill_price: float):
        """Update position when order is filled"""
        if contract_key not in self.positions:
            # New position
            data = self.market_data[contract_key]
            self.positions[contract_key] = {
                'contract': data['contract'],
                'position': quantity if action == "BUY" else -quantity,
                'avgCost': fill_price,
                'currentPrice': fill_price,
                'pnl': 0,
                'entryTime': datetime.now()
            }
            
            # Start tracking historical data for supertrend
            self.request_historical_data(contract_key)
        else:
            # Update existing position
            pos = self.positions[contract_key]
            old_qty = pos['position']
            old_cost = pos['avgCost']
            
            if action == "BUY":
                new_qty = old_qty + quantity
                new_cost = ((old_qty * old_cost) + (quantity * fill_price)) / new_qty
            else:  # SELL
                new_qty = old_qty - quantity
                new_cost = old_cost  # Keep original cost basis
            
            pos['position'] = new_qty
            pos['avgCost'] = new_cost
            
            # Remove position if closed
            if new_qty == 0:
                del self.positions[contract_key]
        
        self.update_positions_display()
    
    def update_position_pnl(self, contract_key: str, current_price: float):
        """Update position PnL with current price"""
        if contract_key in self.positions:
            pos = self.positions[contract_key]
            pos['currentPrice'] = current_price
            pos['pnl'] = (current_price - pos['avgCost']) * pos['position'] * 100
    
    def request_historical_data(self, contract_key: str):
        """Request historical data for supertrend calculation"""
        data = self.market_data[contract_key]
        contract = data['contract']
        
        req_id = self.next_req_id
        self.next_req_id += 1
        
        self.historical_data_requests[req_id] = contract_key
        
        # Request 1-minute bars for last hour
        self.reqHistoricalData(req_id, contract, "", "1 D", "1 min", 
                              "TRADES", 1, 1, False, [])
    
    def calculate_supertrend(self, contract_key: str):
        """Calculate supertrend indicator"""
        if contract_key not in self.historical_data:
            return
        
        bars = self.historical_data[contract_key]
        
        if len(bars) < self.atr_period:
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(bars)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        
        # Calculate ATR
        df['tr'] = df.apply(lambda row: max(
            row['high'] - row['low'],
            abs(row['high'] - df['close'].shift(1).iloc[row.name]) if row.name > 0 else 0,
            abs(row['low'] - df['close'].shift(1).iloc[row.name]) if row.name > 0 else 0
        ), axis=1)
        
        df['atr'] = df['tr'].rolling(window=self.atr_period).mean()
        
        # Calculate Supertrend
        df['basic_upper'] = (df['high'] + df['low']) / 2 + (self.chandelier_multiplier * df['atr'])
        df['basic_lower'] = (df['high'] + df['low']) / 2 - (self.chandelier_multiplier * df['atr'])
        
        df['supertrend_upper'] = df['basic_upper']
        df['supertrend_lower'] = df['basic_lower']
        df['supertrend'] = 0
        
        for i in range(1, len(df)):
            # Upper band
            if df['close'].iloc[i-1] <= df['supertrend_upper'].iloc[i-1]:
                df.loc[df.index[i], 'supertrend_upper'] = min(df['basic_upper'].iloc[i], 
                                                              df['supertrend_upper'].iloc[i-1])
            else:
                df.loc[df.index[i], 'supertrend_upper'] = df['basic_upper'].iloc[i]
            
            # Lower band
            if df['close'].iloc[i-1] >= df['supertrend_lower'].iloc[i-1]:
                df.loc[df.index[i], 'supertrend_lower'] = max(df['basic_lower'].iloc[i], 
                                                              df['supertrend_lower'].iloc[i-1])
            else:
                df.loc[df.index[i], 'supertrend_lower'] = df['basic_lower'].iloc[i]
            
            # Supertrend direction
            if df['close'].iloc[i] <= df['supertrend_upper'].iloc[i]:
                df.loc[df.index[i], 'supertrend'] = df['supertrend_upper'].iloc[i]
            else:
                df.loc[df.index[i], 'supertrend'] = df['supertrend_lower'].iloc[i]
        
        self.supertrend_data[contract_key] = df
        
        # Check for exit signal
        self.check_exit_signal(contract_key)
        
        # Update chart
        self.update_chart(contract_key)
    
    def check_exit_signal(self, contract_key: str):
        """Check if supertrend signals an exit"""
        if contract_key not in self.positions or contract_key not in self.supertrend_data:
            return
        
        df = self.supertrend_data[contract_key]
        
        if len(df) < 2:
            return
        
        current_price = df['close'].iloc[-1]
        supertrend = df['supertrend'].iloc[-1]
        
        # Exit if price crosses below supertrend
        if current_price < supertrend:
            pos = self.positions[contract_key]
            if pos['position'] > 0:  # Long position
                self.log_message(f"Supertrend exit signal for {contract_key}", "WARNING")
                
                # Place market order to exit
                contract = pos['contract']
                quantity = pos['position']
                
                # Use current bid as limit price
                current_bid = self.market_data[contract_key]['bid']
                self.place_limit_order(contract, "SELL", quantity, current_bid)
    
    def update_chart(self, contract_key: str):
        """Update the matplotlib chart with supertrend"""
        if contract_key not in self.supertrend_data:
            return
        
        df = self.supertrend_data[contract_key]
        
        self.ax.clear()
        
        # Plot price
        self.ax.plot(df['close'], label='Price', color='#E0E0E0', linewidth=2)
        
        # Plot supertrend
        self.ax.plot(df['supertrend'], label='Supertrend', color='#FF8C00', linewidth=2)
        
        # Fill between
        self.ax.fill_between(range(len(df)), df['close'], df['supertrend'],
                            where=df['close'] > df['supertrend'], 
                            alpha=0.3, color='#44FF44', label='Long')
        self.ax.fill_between(range(len(df)), df['close'], df['supertrend'],
                            where=df['close'] <= df['supertrend'], 
                            alpha=0.3, color='#FF4444', label='Short')
        
        self.ax.set_title(f'Supertrend: {contract_key}', color='#E0E0E0')
        self.ax.set_xlabel('Time', color='#E0E0E0')
        self.ax.set_ylabel('Price', color='#E0E0E0')
        self.ax.legend(facecolor='#181818', edgecolor='#FF8C00', labelcolor='#E0E0E0')
        self.ax.grid(True, alpha=0.2, color='#FF8C00')
        
        self.canvas.draw()
    
    # ========================================================================
    # GUI UPDATES
    # ========================================================================
    
    def add_order_to_tree(self, order_id: int, contract: Contract, action: str,
                         quantity: int, status: str):
        """Add order to the order treeview"""
        contract_key = f"{contract.symbol}_{contract.strike}_{contract.right}"
        values = (order_id, contract_key, action, quantity, status)
        self.order_tree.insert("", tk.END, values=values, tags=(str(order_id),))
    
    def update_order_in_tree(self, order_id: int, status: str):
        """Update order status in treeview"""
        for item in self.order_tree.get_children():
            if str(order_id) in self.order_tree.item(item, "tags"):
                values = list(self.order_tree.item(item, "values"))
                values[4] = status
                self.order_tree.item(item, values=values)
                
                # Remove if filled or cancelled
                if status in ["Filled", "Cancelled"]:
                    self.order_tree.delete(item)
                break
    
    def update_positions_display(self):
        """Update the positions treeview"""
        if not self.root:
            return
        # Clear existing items
        for item in self.position_tree.get_children():
            self.position_tree.delete(item)
        
        total_pnl = 0
        
        # Add current positions
        for contract_key, pos in self.positions.items():
            pnl = pos['pnl']
            pnl_pct = (pos['currentPrice'] / pos['avgCost'] - 1) * 100 if pos['avgCost'] > 0 else 0
            
            values = (
                contract_key,
                pos['position'],
                f"${pos['avgCost']:.2f}",
                f"${pos['currentPrice']:.2f}",
                f"${pnl:.2f}",
                f"{pnl_pct:.2f}%"
            )
            
            self.position_tree.insert("", tk.END, values=values)
            total_pnl += pnl
        
        # Update total PnL label
        pnl_color = "#44FF44" if total_pnl >= 0 else "#FF4444"
        self.pnl_label.config(text=f"Total PnL: ${total_pnl:.2f}", 
                             foreground=pnl_color)
        
        # Schedule next update
        self.root.after(1000, self.update_positions_display)
    
    def process_gui_queue(self):
        """Process messages from API thread to GUI thread"""
        if not self.root:
            return
        try:
            while not self.gui_queue.empty():
                message = self.gui_queue.get_nowait()
                # Process message (if needed)
        except queue.Empty:
            pass
        
        # Schedule next check
        self.root.after(100, self.process_gui_queue)
    
    def log_message(self, message: str, level: str = "INFO"):
        """Log a message to the GUI"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        self.log_text.insert(tk.END, log_entry, level)
        self.log_text.see(tk.END)
        
        # Keep log size manageable
        if int(self.log_text.index('end-1c').split('.')[0]) > 1000:
            self.log_text.delete('1.0', '500.0')
    
    # ========================================================================
    # MAIN LOOP
    # ========================================================================
    
    def on_closing(self):
        """Handle window closing"""
        if not self.root:
            return
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.running = False
            if self.connection_state == ConnectionState.CONNECTED:
                self.disconnect_from_ib()
            self.root.destroy()
    
    def run_gui(self):
        """Start the GUI main loop"""
        if not self.root:
            return
        self.load_settings()
        self.root.mainloop()


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    app = SPXTradingApp()
    app.run_gui()
