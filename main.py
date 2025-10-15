"""
SPX 0DTE Options Trading Application
Professional Bloomberg-style GUI for Interactive Brokers API
Author: VJS World
Date: October 15, 2025
"""

import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont
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
from matplotlib.patches import Rectangle

if TYPE_CHECKING:
    from ttkbootstrap import Window
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends._backend_tk import NavigationToolbar2Tk
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
        """
        Handle error messages from IBKR API.
        
        Error codes:
        - 326: Client ID already in use
        - 502: Couldn't connect to TWS
        - 503: TWS socket port is already in use
        - 504: Not connected
        - 1100: Connectivity between IB and TWS has been lost
        - 2110: Connectivity between TWS and server is broken
        """
        error_msg = f"Error {errorCode}: {errorString}"
        
        # Only log non-trivial errors
        if errorCode not in [2104, 2106, 2158]:  # Informational messages
            self.app.log_message(error_msg, "ERROR")
        
        # Client ID already in use - try next client ID
        if errorCode == 326:
            self.app.log_message(f"Client ID {self.app.client_id} already in use", "WARNING")
            if self.app.client_id_iterator < self.app.max_client_id:
                self.app.client_id_iterator += 1
                self.app.client_id = self.app.client_id_iterator
                self.app.log_message(f"Retrying with Client ID {self.app.client_id}...", "INFO")
                # Mark that we're handling this error specially (don't use normal reconnect logic)
                self.app.handling_client_id_error = True
                # Update state
                self.app.connection_state = ConnectionState.DISCONNECTED
                self.app.running = False  # Stop current connection loop
                # Schedule reconnect with new client ID
                if self.app.root:
                    self.app.root.after(2000, self.app.retry_connection_with_new_client_id)
            else:
                self.app.log_message(f"Exhausted all client IDs (1-{self.app.max_client_id}). Please close other connections.", "ERROR")
                self.app.connection_state = ConnectionState.DISCONNECTED
                self.app.running = False
        
        # Connection-related errors - trigger reconnection
        elif errorCode in [502, 503, 504, 1100, 2110]:
            self.app.log_message(f"Connection error detected (code {errorCode}). Initiating reconnection...", "WARNING")
            self.app.connection_state = ConnectionState.DISCONNECTED
            self.app.schedule_reconnect()
        
        # Market data errors
        elif errorCode == 354:  # Requested market data is not subscribed
            self.app.log_message(f"Market data not available for reqId {reqId}", "WARNING")
        
        # Historical data errors
        elif errorCode == 162:  # Historical market data Service error
            self.app.log_message(f"Historical data permission issue for reqId {reqId}: {errorString}", "WARNING")
            # Check if this is a historical data request
            if reqId in self.app.historical_data_requests:
                contract_key = self.app.historical_data_requests[reqId]
                self.app.log_message(
                    f"Historical data unavailable for {contract_key}. "
                    f"Paper trading accounts may have limited historical data access.",
                    "WARNING"
                )
        elif errorCode == 200:  # No security definition found
            self.app.log_message(f"Security definition not found for reqId {reqId}: {errorString}", "WARNING")
        elif errorCode == 366:  # No historical data query found
            if reqId in self.app.historical_data_requests:
                contract_key = self.app.historical_data_requests[reqId]
                self.app.log_message(f"No historical data available for {contract_key}", "WARNING")
        elif errorCode in [165, 321]:  # Historical data errors
            if reqId in self.app.historical_data_requests:
                contract_key = self.app.historical_data_requests[reqId]
                self.app.log_message(
                    f"Historical data error for {contract_key}: {errorString}",
                    "WARNING"
                )
    
    def connectAck(self):
        """Called when connection is acknowledged"""
        self.app.log_message("Connection acknowledged", "INFO")
    
    def nextValidId(self, orderId: int):
        """
        Receives next valid order ID - signals successful connection.
        This is the definitive confirmation that we are connected to IBKR.
        """
        self.app.next_order_id = orderId
        self.app.connection_state = ConnectionState.CONNECTED
        self.app.reconnect_attempts = 0  # Reset reconnect counter on successful connection
        self.app.client_id_iterator = 1  # Reset client ID iterator for next connection
        self.app.log_message(f"Successfully connected to IBKR with Client ID {self.app.client_id}! Next Order ID: {orderId}", "SUCCESS")
        self.app.on_connected()
    
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str,
                                         underlyingConId: int, tradingClass: str,
                                         multiplier: str, expirations: set,
                                         strikes: set):
        """
        Receives option chain parameters from IBKR.
        NOT USED - Application uses manual strike calculation instead.
        """
        self.app.log_message(
            f"Received option parameters (not used - manual chain generation enabled)", 
            "INFO"
        )
    
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        """
        Called when option parameter request is complete.
        NOT USED - Application uses manual strike calculation instead.
        """
        self.app.log_message(
            f"Option chain request complete for reqId {reqId} (not used - manual chain generation enabled)", 
            "INFO"
        )
    
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float,
                  attrib: TickAttrib):
        """Receives real-time price updates"""
        # Check if this is SPX underlying price
        if reqId == self.app.spx_req_id:
            if tickType == 4:  # LAST price
                self.app.spx_price = price
                self.app.update_spx_price_display()
            return
        
        # Handle option contract prices
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
                'iv': impliedVol if impliedVol != -2 else 0  # Changed from 'impliedVol' to 'iv'
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
                self.app.log_message(f"Receiving historical data for {contract_key} (reqId: {reqId})", "INFO")
            
            self.app.historical_data[contract_key].append({
                'date': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })
        else:
            self.app.log_message(f"Received historical data for unknown reqId: {reqId}", "WARNING")
    
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        """Called when historical data request is complete"""
        if reqId in self.app.historical_data_requests:
            contract_key = self.app.historical_data_requests[reqId]
            bar_count = len(self.app.historical_data.get(contract_key, []))
            
            if bar_count > 0:
                self.app.log_message(
                    f"Historical data complete for {contract_key} - {bar_count} bars ({start} to {end})", 
                    "SUCCESS"
                )
            else:
                self.app.log_message(
                    f"Historical data request complete for {contract_key} but no data received. "
                    f"Paper trading accounts have limited historical data access.",
                    "WARNING"
                )
            
            # Update the appropriate chart based on contract type
            if self.app.selected_call_contract and contract_key == f"SPX_{self.app.selected_call_contract.strike}_C":
                self.app.log_message("Updating call chart with new data", "INFO")
                if self.app.root:
                    self.app.root.after(100, self.app.update_call_chart)
            elif self.app.selected_put_contract and contract_key == f"SPX_{self.app.selected_put_contract.strike}_P":
                self.app.log_message("Updating put chart with new data", "INFO")
                if self.app.root:
                    self.app.root.after(100, self.app.update_put_chart)
        else:
            self.app.log_message(f"Historical data end for unknown reqId: {reqId}", "WARNING")


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
        self.max_reconnect_attempts = 10  # Increased to 10 attempts
        self.reconnect_delay = 5
        self.auto_connect = True  # Auto-connect at startup
        self.subscribed_contracts = []  # Track subscribed contracts for reconnection
        
        # API settings
        self.host = "127.0.0.1"
        self.port = 7497  # Paper trading
        self.client_id = 1  # Start with client ID 1
        self.client_id_iterator = 1  # Current client ID being tried
        self.max_client_id = 10  # Maximum client ID to try
        self.handling_client_id_error = False  # Flag to prevent double reconnect
        
        # Strategy parameters
        self.atr_period = 14
        self.chandelier_multiplier = 3.0
        
        # Option chain parameters
        self.strikes_above = 20  # Number of strikes above SPX price
        self.strikes_below = 20  # Number of strikes below SPX price
        self.chain_refresh_interval = 3600  # Refresh chain every hour (in seconds)
        
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
        
        # SPX underlying price tracking
        self.spx_price = 0.0
        self.spx_req_id = None
        
        # Expiration management
        self.expiry_offset = 0  # 0 = today (0DTE), 1 = next expiry, etc.
        self.current_expiry = self.calculate_expiry_date(self.expiry_offset)
        
        # Option chain
        self.spx_contracts = []  # List of all option contracts
        
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
        
        # Auto-connect to IBKR on startup (after GUI is ready)
        if self.auto_connect:
            self.log_message("Auto-connect enabled - connecting to IBKR in 2 seconds...", "INFO")
            self.root.after(2000, self.connect_to_ib)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_trading_tab(self):
        """Create the main trading dashboard tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Option Chain & Trading Dashboard")
        
        # Option Chain header with SPX price and controls
        chain_header = ttk.Frame(tab)
        chain_header.pack(fill=X, padx=5, pady=5)
        
        ttk.Label(chain_header, text="SPX Option Chain", 
                 font=("Arial", 14, "bold")).pack(side=LEFT, padx=5)
        
        # SPX Price display (large and prominent)
        self.spx_price_label = ttk.Label(chain_header, text="SPX: Loading...", 
                                         font=("Arial", 14, "bold"),
                                         foreground="#FF8C00")
        self.spx_price_label.pack(side=LEFT, padx=20)
        
        # Expiration selector       
        self.expiry_offset_var = tk.StringVar(value="0 DTE (Today)")
        self.expiry_dropdown = ttk.Combobox(
            chain_header, 
            textvariable=self.expiry_offset_var,
            values=self.get_expiration_options(),
            width=20, 
            state="readonly"
        )
        self.expiry_dropdown.pack(side=RIGHT, padx=5)
        self.expiry_dropdown.bind('<<ComboboxSelected>>', self.on_expiry_changed)
        
        # Refresh button with white text
        refresh_btn = ttk.Button(chain_header, text="Refresh Chain", 
                                command=self.refresh_option_chain)
        refresh_btn.pack(side=RIGHT, padx=5)
        # Configure button style to have white text
        style = ttk.Style()
        style.configure('RefreshChain.TButton', foreground='white')
        refresh_btn.configure(style='RefreshChain.TButton')
        
        # Option Chain Treeview - IBKR Style (Calls on left, Puts on right)
        chain_frame = ttk.Frame(tab)
        chain_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Scrollbars
        chain_vsb = ttk.Scrollbar(chain_frame, orient=VERTICAL)
        chain_vsb.pack(side=RIGHT, fill=Y)
        
        chain_hsb = ttk.Scrollbar(chain_frame, orient=HORIZONTAL)
        chain_hsb.pack(side=BOTTOM, fill=X)
        
        # Treeview columns matching IBKR layout
        # CALLS: Bid, Ask, Last, Volume, Gamma, Vega, Theta, Delta, Imp Volatility
        # STRIKE (center)
        # PUTS: Delta, Theta, Vega, Gamma, Volume, Last, Ask, Bid
        columns = (
            # Call side (left)
            "C_Bid", "C_Ask", "C_Last", "C_Vol", "C_Gamma", "C_Vega", "C_Theta", "C_Delta", "C_IV",
            # Strike (center)
            "Strike",
            # Put side (right)
            "P_Delta", "P_Theta", "P_Vega", "P_Gamma", "P_Vol", "P_Last", "P_Ask", "P_Bid"
        )
        
        self.option_tree = ttk.Treeview(
            chain_frame, 
            columns=columns, 
            show="headings", 
            height=30,
            yscrollcommand=chain_vsb.set,
            xscrollcommand=chain_hsb.set
        )
        
        chain_vsb.config(command=self.option_tree.yview)
        chain_hsb.config(command=self.option_tree.xview)
        
        # Configure column headers and widths
        call_headers = {
            "C_Bid": "Bid", "C_Ask": "Ask", "C_Last": "Last", "C_Vol": "Volume",
            "C_Gamma": "Gamma", "C_Vega": "Vega", "C_Theta": "Theta", 
            "C_Delta": "Delta", "C_IV": "Imp Vol"
        }
        
        put_headers = {
            "P_Delta": "Delta", "P_Theta": "Theta", "P_Vega": "Vega", 
            "P_Gamma": "Gamma", "P_Vol": "Volume", "P_Last": "Last",
            "P_Ask": "Ask", "P_Bid": "Bid"
        }
        
        # Set column widths
        col_width = 70
        strike_width = 100  # Slightly wider for bold text
        
        # Create a custom font for strike column
        strike_font = tkfont.Font(family="Arial", size=11, weight="bold")
        
        for col in columns:
            if col == "Strike":
                self.option_tree.heading(col, text="● STRIKE ●")  # Make heading stand out
                self.option_tree.column(col, width=strike_width, anchor=CENTER)
            elif col.startswith("C_"):
                self.option_tree.heading(col, text=call_headers[col])
                self.option_tree.column(col, width=col_width, anchor=CENTER)
            else:  # Put columns
                self.option_tree.heading(col, text=put_headers[col])
                self.option_tree.column(col, width=col_width, anchor=CENTER)
        
        # Configure row tags for ITM/OTM color coding
        strike_font = tkfont.Font(family="Arial", size=11, weight="bold")
        self.option_tree.tag_configure("call_itm", background="#1e3a1e", font=strike_font)  # Dark green for ITM calls
        self.option_tree.tag_configure("call_otm", background="#181818", font=strike_font)  # Default dark
        self.option_tree.tag_configure("put_itm", background="#3a1e1e", font=strike_font)   # Dark red for ITM puts
        self.option_tree.tag_configure("put_otm", background="#181818", font=strike_font)   # Default dark
        self.option_tree.tag_configure("atm", background="#2e2e2e", font=strike_font)       # Slightly lighter for ATM
        
        self.option_tree.pack(fill=BOTH, expand=YES)
        
        # Bind click event for option chain
        self.option_tree.bind('<ButtonRelease-1>', self.on_option_chain_click)
        
        # Bottom panel: Positions/Orders side-by-side, then Charts, then Log
        bottom_frame = ttk.Frame(tab)
        bottom_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Row 1: Positions and Orders side-by-side
        pos_order_frame = ttk.Frame(bottom_frame)
        pos_order_frame.pack(fill=BOTH, expand=False, padx=5, pady=5)
        
        # Positions section (left side)
        pos_container = ttk.Frame(pos_order_frame)
        pos_container.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 2))
        
        pos_label = ttk.Label(pos_container, text="Open Positions", 
                             font=("Arial", 12, "bold"))
        pos_label.pack(fill=X, padx=5, pady=(5, 0))
        
        pos_frame = ttk.Frame(pos_container)
        pos_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        pos_vsb = ttk.Scrollbar(pos_frame, orient="vertical")
        pos_vsb.pack(side=RIGHT, fill=Y)
        
        pos_columns = ("Contract", "Qty", "Avg Cost", "Last", "PnL", "PnL%")
        self.position_tree = ttk.Treeview(pos_frame, columns=pos_columns,
                                         show="headings", height=6,
                                         yscrollcommand=pos_vsb.set)
        pos_vsb.config(command=self.position_tree.yview)
        
        for col in pos_columns:
            self.position_tree.heading(col, text=col)
            self.position_tree.column(col, width=100, anchor=CENTER)
        
        self.position_tree.pack(fill=BOTH, expand=YES)
        
        # Orders section (right side)
        order_container = ttk.Frame(pos_order_frame)
        order_container.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        order_label = ttk.Label(order_container, text="Active Orders", 
                               font=("Arial", 12, "bold"))
        order_label.pack(fill=X, padx=5, pady=(5, 0))
        
        order_frame = ttk.Frame(order_container)
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
        
        # Row 2: Charts side-by-side (Calls on left, Puts on right)
        charts_frame = ttk.Frame(bottom_frame)
        charts_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Call chart (left side)
        call_chart_container = ttk.Frame(charts_frame)
        call_chart_container.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 2))
        
        call_chart_header = ttk.Frame(call_chart_container)
        call_chart_header.pack(fill=X, padx=5, pady=(5, 0))
        
        ttk.Label(call_chart_header, text="Call Chart", 
                 font=("Arial", 12, "bold")).pack(side=LEFT)
        
        # Days back selector for calls
        ttk.Label(call_chart_header, text="Days:").pack(side=RIGHT, padx=(5, 2))
        self.call_days_var = tk.StringVar(value="1")
        call_days = ttk.Combobox(call_chart_header, textvariable=self.call_days_var,
                                 values=["1", "2", "5", "10", "20"],
                                 width=5, state="readonly")
        call_days.pack(side=RIGHT, padx=2)
        call_days.bind('<<ComboboxSelected>>', lambda e: self.on_call_settings_changed())
        
        # Timeframe dropdown for calls
        ttk.Label(call_chart_header, text="Interval:").pack(side=RIGHT, padx=(5, 2))
        self.call_timeframe_var = tk.StringVar(value="1 min")
        call_timeframe = ttk.Combobox(call_chart_header, textvariable=self.call_timeframe_var,
                                      values=["1 min", "5 min", "15 min", "30 min", "1 hour"],
                                      width=8, state="readonly")
        call_timeframe.pack(side=RIGHT, padx=0)
        call_timeframe.bind('<<ComboboxSelected>>', lambda e: self.on_call_settings_changed())
        
        call_chart_frame = ttk.Frame(call_chart_container)
        call_chart_frame.pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        self.call_fig = Figure(figsize=(5, 4), dpi=80, facecolor='#181818')
        self.call_fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.10)
        self.call_ax = self.call_fig.add_subplot(111, facecolor='#202020')
        self.call_ax.tick_params(colors='#E0E0E0', labelsize=8)
        self.call_ax.spines['bottom'].set_color('#FF8C00')
        self.call_ax.spines['top'].set_color('#FF8C00')
        self.call_ax.spines['left'].set_color('#FF8C00')
        self.call_ax.spines['right'].set_color('#FF8C00')
        self.call_ax.set_title("Select a Call from chain", color='#E0E0E0', fontsize=10)
        
        self.call_canvas = FigureCanvasTkAgg(self.call_fig, master=call_chart_frame)
        self.call_canvas.get_tk_widget().pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Add loading spinner overlay for call chart (initially hidden)
        self.call_loading_frame = tk.Frame(call_chart_frame, bg='#181818')
        self.call_loading_label = ttk.Label(self.call_loading_frame, 
                                            text="⟳ Loading chart data...",
                                            font=("Arial", 12),
                                            foreground="#FF8C00",
                                            background="#181818")
        self.call_loading_label.pack(expand=True)
        self.call_loading_timeout_id = None  # For timeout tracking
        
        # Add navigation toolbar for zoom/pan
        call_toolbar = NavigationToolbar2Tk(self.call_canvas, call_chart_frame)
        call_toolbar.update()
        call_toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Put chart (right side)
        put_chart_container = ttk.Frame(charts_frame)
        put_chart_container.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        put_chart_header = ttk.Frame(put_chart_container)
        put_chart_header.pack(fill=X, padx=5, pady=(5, 0))
        
        ttk.Label(put_chart_header, text="Put Chart", 
                 font=("Arial", 12, "bold")).pack(side=LEFT)
        
        # Days back selector for puts
        ttk.Label(put_chart_header, text="Days:").pack(side=RIGHT, padx=(5, 2))
        self.put_days_var = tk.StringVar(value="5")
        put_days = ttk.Combobox(put_chart_header, textvariable=self.put_days_var,
                                values=["1", "2", "5", "10", "20"],
                                width=5, state="readonly")
        put_days.pack(side=RIGHT, padx=2)
        put_days.bind('<<ComboboxSelected>>', lambda e: self.on_put_settings_changed())
        
        # Timeframe dropdown for puts
        ttk.Label(put_chart_header, text="Interval:").pack(side=RIGHT, padx=(5, 2))
        self.put_timeframe_var = tk.StringVar(value="1 min")
        put_timeframe = ttk.Combobox(put_chart_header, textvariable=self.put_timeframe_var,
                                     values=["1 min", "5 min", "15 min", "30 min", "1 hour"],
                                     width=8, state="readonly")
        put_timeframe.pack(side=RIGHT, padx=2)
        put_timeframe.bind('<<ComboboxSelected>>', lambda e: self.on_put_settings_changed())
        
        put_chart_frame = ttk.Frame(put_chart_container)
        put_chart_frame.pack(fill=BOTH, expand=YES, padx=2, pady=2)
        
        self.put_fig = Figure(figsize=(5, 4), dpi=80, facecolor='#181818')
        self.put_fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.10)
        self.put_ax = self.put_fig.add_subplot(111, facecolor='#202020')
        self.put_ax.tick_params(colors='#E0E0E0', labelsize=8)
        self.put_ax.spines['bottom'].set_color('#FF8C00')
        self.put_ax.spines['top'].set_color('#FF8C00')
        self.put_ax.spines['left'].set_color('#FF8C00')
        self.put_ax.spines['right'].set_color('#FF8C00')
        self.put_ax.set_title("Select a Put from chain", color='#E0E0E0', fontsize=10)
        
        self.put_canvas = FigureCanvasTkAgg(self.put_fig, master=put_chart_frame)
        self.put_canvas.get_tk_widget().pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Add loading spinner overlay for put chart (initially hidden)
        self.put_loading_frame = tk.Frame(put_chart_frame, bg='#181818')
        self.put_loading_label = ttk.Label(self.put_loading_frame, 
                                           text="⟳ Loading chart data...",
                                           font=("Arial", 12),
                                           foreground="#FF8C00",
                                           background="#181818")
        self.put_loading_label.pack(expand=True)
        self.put_loading_timeout_id = None  # For timeout tracking
        
        # Add navigation toolbar for zoom/pan
        put_toolbar = NavigationToolbar2Tk(self.put_canvas, put_chart_frame)
        put_toolbar.update()
        put_toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Row 3: Log section
        log_label = ttk.Label(bottom_frame, text="Activity Log", 
                             font=("Arial", 12, "bold"))
        log_label.pack(fill=X, padx=5, pady=(5, 0))
        
        log_frame = ttk.Frame(bottom_frame)
        log_frame.pack(fill=BOTH, expand=False, padx=5, pady=5)
        
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical")
        log_vsb.pack(side=RIGHT, fill=Y)
        
        self.log_text = tk.Text(log_frame, height=8, bg='#202020', 
                               fg='#E0E0E0', font=("Consolas", 9),
                               yscrollcommand=log_vsb.set, wrap=tk.WORD)
        log_vsb.config(command=self.log_text.yview)
        self.log_text.pack(fill=BOTH, expand=YES)
        
        # Configure tags for different log levels
        self.log_text.tag_config("ERROR", foreground="#FF4444")
        self.log_text.tag_config("WARNING", foreground="#FFA500")
        self.log_text.tag_config("SUCCESS", foreground="#44FF44")
        self.log_text.tag_config("INFO", foreground="#E0E0E0")
        
        # Initialize chart tracking variables
        self.selected_call_contract = None
        self.selected_put_contract = None
        self.chart_update_interval = 5000  # Legacy variable (no longer used for auto-refresh)
        
        # Debounce variables for responsive chart updates
        self.call_chart_update_pending = None
        self.put_chart_update_pending = None
        self.chart_debounce_delay = 100  # 100ms debounce for TradingView-like responsiveness
    
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
        
        ttk.Label(strategy_frame, text="Strikes Above SPX:").grid(
            row=2, column=0, sticky=W, pady=5)
        self.strikes_above_entry = ttk.Entry(strategy_frame, width=30)
        self.strikes_above_entry.insert(0, str(self.strikes_above))
        self.strikes_above_entry.grid(row=2, column=1, sticky=W, padx=10, pady=5)
        
        ttk.Label(strategy_frame, text="Strikes Below SPX:").grid(
            row=3, column=0, sticky=W, pady=5)
        self.strikes_below_entry = ttk.Entry(strategy_frame, width=30)
        self.strikes_below_entry.insert(0, str(self.strikes_below))
        self.strikes_below_entry.grid(row=3, column=1, sticky=W, padx=10, pady=5)
        
        ttk.Label(strategy_frame, text="Chain Refresh Interval (seconds):").grid(
            row=4, column=0, sticky=W, pady=5)
        self.chain_refresh_entry = ttk.Entry(strategy_frame, width=30)
        self.chain_refresh_entry.insert(0, str(self.chain_refresh_interval))
        self.chain_refresh_entry.grid(row=4, column=1, sticky=W, padx=10, pady=5)
        
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
        """
        Establish connection to IBKR.
        Creates a new API thread and initiates socket connection.
        Will automatically try client IDs 1-10 if one is already in use.
        """
        if self.connection_state != ConnectionState.DISCONNECTED:
            self.log_message("Connection already in progress or established", "WARNING")
            return
        
        # Read connection parameters from UI if not already set (during reconnection)
        try:
            if self.host_entry and self.host_entry.get():
                self.host = self.host_entry.get()
            if self.port_entry and self.port_entry.get():
                self.port = int(self.port_entry.get())
        except:
            pass  # Use existing values if entries aren't available
        
        # Ensure we have valid host and port
        if not self.host or not self.port:
            self.log_message("Invalid host or port configuration", "ERROR")
            self.connection_state = ConnectionState.DISCONNECTED
            return
        
        # Ensure client_id matches the iterator (in case of retries)
        self.client_id = self.client_id_iterator
        
        self.log_message(f"Initiating connection to IBKR at {self.host}:{self.port} (Client ID: {self.client_id})", "INFO")
        
        self.connection_state = ConnectionState.CONNECTING
        self.status_label.config(text=f"Status: Connecting (ID: {self.client_id})...")
        self.connect_btn.config(state=tk.DISABLED)
        
        # Start API thread - this will handle all IBKR communication
        self.running = True
        self.api_thread = threading.Thread(target=self.run_api_thread, daemon=True)
        self.api_thread.start()
        
        self.log_message("API thread started, establishing socket connection...", "INFO")
    
    def run_api_thread(self):
        """
        Main API thread loop.
        Establishes socket connection and runs the message processing loop.
        Will catch any exceptions and trigger reconnection if needed.
        """
        try:
            self.log_message(f"Connecting to socket {self.host}:{self.port}...", "INFO")
            EClient.connect(self, self.host, self.port, self.client_id)
            self.log_message("Socket connected, waiting for nextValidId confirmation...", "INFO")
            
            # Run the message loop - this blocks until disconnection
            self.run()
            
            self.log_message("API message loop terminated", "WARNING")
        except Exception as e:
            self.log_message(f"API thread exception: {str(e)}", "ERROR")
        finally:
            # Connection lost - update state and schedule reconnection
            self.connection_state = ConnectionState.DISCONNECTED
            self.log_message("Connection lost, scheduling reconnection attempt...", "WARNING")
            self.schedule_reconnect()
    
    def disconnect_from_ib(self):
        """
        Disconnect from IBKR.
        Stops the API thread and closes the socket connection.
        """
        self.log_message("Initiating disconnect from IBKR...", "INFO")
        self.running = False
        
        try:
            EClient.disconnect(self)
        except Exception as e:
            self.log_message(f"Error during disconnect: {str(e)}", "WARNING")
        
        self.connection_state = ConnectionState.DISCONNECTED
        self.client_id_iterator = 1  # Reset client ID iterator for next connection
        self.status_label.config(text="Status: Disconnected")
        self.connect_btn.config(text="Connect", state=tk.NORMAL)
        self.log_message("Disconnected from IBKR successfully", "INFO")
    
    def retry_connection_with_new_client_id(self):
        """Retry connection with new client ID after error 326"""
        self.handling_client_id_error = False
        self.connect_to_ib()
    
    def schedule_reconnect(self):
        """
        Schedule automatic reconnection after connection loss.
        Will attempt up to max_reconnect_attempts times with reconnect_delay between attempts.
        """
        if not self.root:
            return
        
        # Don't schedule reconnect if we're handling client ID error separately
        if self.handling_client_id_error:
            return
            
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.log_message(
                f"Maximum reconnection attempts ({self.max_reconnect_attempts}) reached. "
                "Please check your connection and reconnect manually.", 
                "ERROR"
            )
            self.reconnect_attempts = 0
            self.status_label.config(text="Status: Disconnected (Manual reconnect required)")
            self.connect_btn.config(text="Connect", state=tk.NORMAL)
            return
        
        self.reconnect_attempts += 1
        self.log_message(
            f"Scheduling reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} "
            f"in {self.reconnect_delay} seconds...", 
            "WARNING"
        )
        
        # Update UI to show reconnection status
        self.status_label.config(
            text=f"Status: Reconnecting ({self.reconnect_attempts}/{self.max_reconnect_attempts})..."
        )
        
        # Schedule reconnection
        self.root.after(self.reconnect_delay * 1000, self.connect_to_ib)
    
    def on_connected(self):
        """
        Called when successfully connected to IBKR.
        This is where we initialize all data subscriptions and requests.
        """
        self.log_message("Connection established successfully!", "SUCCESS")
        self.reconnect_attempts = 0  # Reset reconnect counter
        
        # Update UI
        self.status_label.config(text="Status: Connected")
        self.connect_btn.config(text="Disconnect", state=tk.NORMAL)
        
        # Initialize data subscriptions
        self.log_message("Requesting account updates...", "INFO")
        self.reqAccountUpdates(True, "")
        
        # Subscribe to SPX underlying price
        self.log_message("Subscribing to SPX underlying price...", "INFO")
        self.subscribe_spx_price()
        
        # Request option chain - this will automatically subscribe to market data
        self.log_message("Requesting SPX option chain for 0DTE...", "INFO")
        self.request_option_chain()
        
        # If we're reconnecting, resubscribe to previously subscribed contracts
        if self.subscribed_contracts:
            self.log_message(f"Reconnection detected - resubscribing to {len(self.subscribed_contracts)} contracts...", "INFO")
            self.resubscribe_market_data()
    
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
            self.strikes_above = int(self.strikes_above_entry.get())
            self.strikes_below = int(self.strikes_below_entry.get())
            self.chain_refresh_interval = int(self.chain_refresh_entry.get())
            
            settings = {
                'host': self.host,
                'port': self.port,
                'client_id': self.client_id,
                'atr_period': self.atr_period,
                'chandelier_multiplier': self.chandelier_multiplier,
                'strikes_above': self.strikes_above,
                'strikes_below': self.strikes_below,
                'chain_refresh_interval': self.chain_refresh_interval
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
                self.strikes_above = settings.get('strikes_above', self.strikes_above)
                self.strikes_below = settings.get('strikes_below', self.strikes_below)
                self.chain_refresh_interval = settings.get('chain_refresh_interval', 
                                                          self.chain_refresh_interval)
                
                self.log_message("Settings loaded successfully", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error loading settings: {str(e)}", "ERROR")
    
    # ========================================================================
    # SPX UNDERLYING PRICE
    # ========================================================================
    
    def subscribe_spx_price(self):
        """
        Subscribe to SPX underlying index price.
        This provides real-time price updates for the SPX index.
        """
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot subscribe to SPX price - not connected", "WARNING")
            return
        
        # Create SPX index contract
        spx_contract = Contract()
        spx_contract.symbol = "SPX"
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Get unique request ID
        self.spx_req_id = self.next_req_id
        self.next_req_id += 1
        
        # Request market data for SPX
        self.reqMktData(self.spx_req_id, spx_contract, "", False, False, [])
        self.log_message(f"Subscribed to SPX underlying price (reqId: {self.spx_req_id})", "INFO")
    
    def update_spx_price_display(self):
        """Update the SPX price display in the GUI"""
        if self.spx_price > 0:
            self.spx_price_label.config(text=f"SPX: ${self.spx_price:.2f}")
    
    # ========================================================================
    # OPTION CHAIN MANAGEMENT
    # ========================================================================
    
    def calculate_expiry_date(self, offset: int) -> str:
        """
        Calculate expiration date based on offset.
        offset = 0: Today (0DTE)
        offset = 1: Next trading day
        offset = 2: Day after next, etc.
        
        For SPX options, expirations are Mon/Wed/Fri.
        """
        from datetime import timedelta
        
        current_date = datetime.now()
        target_date = current_date
        
        # SPX has options expiring Monday, Wednesday, Friday
        # 0 = Monday, 2 = Wednesday, 4 = Friday
        expiry_days = [0, 2, 4]
        
        days_checked = 0
        expirations_found = 0
        
        # Find the Nth expiration (where N = offset)
        while expirations_found <= offset:
            if target_date.weekday() in expiry_days:
                if expirations_found == offset:
                    return target_date.strftime("%Y%m%d")
                expirations_found += 1
            target_date += timedelta(days=1)
            days_checked += 1
            
            # Safety check
            if days_checked > 60:
                self.log_message("Error calculating expiry date - exceeded max days", "ERROR")
                return datetime.now().strftime("%Y%m%d")
        
        return target_date.strftime("%Y%m%d")
    
    def get_expiration_options(self) -> list:
        """Get list of expiration options for dropdown"""
        options = []
        
        for i in range(10):  # Show next 10 expirations
            expiry_date = self.calculate_expiry_date(i)
            date_obj = datetime.strptime(expiry_date, "%Y%m%d")
            
            if i == 0:
                label = f"0 DTE (Today - {date_obj.strftime('%m/%d/%Y')})"
            elif i == 1:
                label = f"1 DTE (Next - {date_obj.strftime('%m/%d/%Y')})"
            else:
                label = f"{i} DTE ({date_obj.strftime('%m/%d/%Y')})"
            
            options.append(label)
        
        return options
    
    def on_expiry_changed(self, event=None):
        """Handle expiration dropdown change"""
        selected = self.expiry_offset_var.get()
        
        # Extract offset from label (first number)
        offset = int(selected.split()[0])
        
        self.expiry_offset = offset
        self.current_expiry = self.calculate_expiry_date(offset)
        
        self.log_message(f"Expiration changed to: {self.current_expiry} (offset: {offset})", "INFO")
        
        # Refresh the option chain with new expiration
        if self.connection_state == ConnectionState.CONNECTED:
            self.refresh_option_chain()
    
    def create_spxw_contract(self, strike: float, right: str) -> Contract:
        """Create a SPXW option contract with current expiration"""
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
    
    def refresh_option_chain(self):
        """
        Refresh the option chain - called manually or automatically every hour.
        Unsubscribes from old data and requests new chain.
        """
        self.log_message("Refreshing option chain...", "INFO")
        
        # Cancel existing market data subscriptions
        for req_id in list(self.market_data_map.keys()):
            self.cancelMktData(req_id)
        
        # Clear data structures
        self.market_data.clear()
        self.market_data_map.clear()
        self.option_chain_data.clear()
        
        # Request new chain
        self.request_option_chain()
        
        # Schedule next automatic refresh
        if self.root and self.chain_refresh_interval > 0:
            self.root.after(self.chain_refresh_interval * 1000, self.refresh_option_chain)
    
    def request_option_chain(self):
        """
        Build option chain using manual strike calculation.
        Always uses manual method instead of requesting from IBKR API.
        """
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot create option chain - not connected to IBKR", "WARNING")
            return
        
        self.log_message("Building option chain using manual strike calculation...", "INFO")
        
        # Always use manual option chain generation
        self.manual_option_chain_fallback()
    
    def manual_option_chain_fallback(self):
        """
        Manually create option chain based on SPX price.
        Primary method for building the option chain - creates strikes dynamically
        around the current SPX price based on configured strike ranges.
        """
        self.log_message("Building option chain from SPX price and strike settings...", "INFO")
        
        # Wait for SPX price if not available yet
        if self.spx_price == 0:
            self.log_message("Waiting for SPX price before creating manual chain...", "INFO")
            # Retry after 2 seconds
            if self.root:
                self.root.after(2000, self.manual_option_chain_fallback)
            return
        
        self.log_message(f"Creating option chain around SPX price: ${self.spx_price:.2f}", "INFO")
        
        # Create strikes around current SPX price (every 5 points)
        center_strike = round(self.spx_price / 5) * 5  # Round to nearest 5
        strikes = []
        
        # Generate strikes: strikes_below below ATM, then ATM, then strikes_above above ATM
        # Start from (ATM - strikes_below*5) and go to (ATM + strikes_above*5)
        start_strike = center_strike - (self.strikes_below * 5)
        end_strike = center_strike + (self.strikes_above * 5)
        
        current_strike = start_strike
        while current_strike <= end_strike:
            strikes.append(current_strike)
            current_strike += 5
        
        self.log_message(
            f"Created {len(strikes)} strikes from ${min(strikes):.2f} to ${max(strikes):.2f} "
            f"(center: ${center_strike:.2f}, {self.strikes_below} below, {self.strikes_above} above)",
            "INFO"
        )
        
        # Create contracts for all strikes
        self.spx_contracts = []
        
        for strike in strikes:
            call_contract = self.create_spxw_contract(strike, "C")
            put_contract = self.create_spxw_contract(strike, "P")
            
            self.spx_contracts.append(('C', strike, call_contract))
            self.spx_contracts.append(('P', strike, put_contract))
        
        self.log_message(
            f"Created {len(self.spx_contracts)} option contracts ({len(strikes)} calls + {len(strikes)} puts)", 
            "SUCCESS"
        )
        
        # Subscribe to market data
        self.subscribe_market_data()
    
    def process_option_chain(self):
        """
        Process received option chain data and create contracts for 0DTE options.
        This is called after securityDefinitionOptionParameterEnd callback.
        """
        if not self.option_chain_data:
            self.log_message("No option chain data received from IBKR", "WARNING")
            return
        
        self.log_message("Processing option chain data...", "INFO")
        
        # Get today's strikes
        for req_id, data in self.option_chain_data.items():
            expirations = data['expirations']
            strikes = data['strikes']
            
            self.log_message(f"Received {len(expirations)} expirations and {len(strikes)} strikes", "INFO")
            
            # Filter for today's expiration (0DTE)
            if self.current_expiry in expirations:
                self.log_message(
                    f"Found 0DTE expiration {self.current_expiry} with {len(strikes)} strikes", 
                    "SUCCESS"
                )
                
                # Create contracts for all strikes (calls and puts)
                self.spx_contracts = []
                
                for strike in strikes:
                    # Create call and put contracts for each strike
                    call_contract = self.create_spxw_contract(strike, "C")
                    put_contract = self.create_spxw_contract(strike, "P")
                    
                    self.spx_contracts.append(('C', strike, call_contract))
                    self.spx_contracts.append(('P', strike, put_contract))
                
                self.log_message(
                    f"Created {len(self.spx_contracts)} option contracts ({len(strikes)} calls + {len(strikes)} puts)",
                    "SUCCESS"
                )
                
                # Subscribe to market data for all contracts
                self.subscribe_market_data()
                break
            else:
                self.log_message(f"0DTE expiration {self.current_expiry} not found in available expirations", "WARNING")
    
    def subscribe_market_data(self):
        """
        Subscribe to real-time market data for all option contracts.
        Creates treeview rows with calls on left and puts on right (IBKR style).
        """
        if not self.root:
            return
            
        self.log_message(
            f"Subscribing to real-time market data for {len(self.spx_contracts)} contracts...", 
            "INFO"
        )
        
        # Clear existing data structures
        self.market_data.clear()
        self.market_data_map.clear()
        self.subscribed_contracts.clear()
        
        # Clear treeview display
        for item in self.option_tree.get_children():
            self.option_tree.delete(item)
        
        # Organize contracts by strike (calls and puts together)
        strikes_dict = {}
        
        for right, strike, contract in self.spx_contracts:
            if strike not in strikes_dict:
                strikes_dict[strike] = {'call': None, 'put': None, 'call_contract': None, 'put_contract': None}
            
            if right == 'C':
                strikes_dict[strike]['call'] = right
                strikes_dict[strike]['call_contract'] = contract
            else:
                strikes_dict[strike]['put'] = right
                strikes_dict[strike]['put_contract'] = contract
        
        # Sort strikes
        sorted_strikes = sorted(strikes_dict.keys())
        
        # Subscribe and create display rows
        for strike in sorted_strikes:
            strike_data = strikes_dict[strike]
            
            # Subscribe to call
            if strike_data['call']:
                req_id = self.next_req_id
                self.next_req_id += 1
                
                contract_key = f"SPX_{strike}_C"
                self.market_data_map[req_id] = contract_key
                
                self.market_data[contract_key] = {
                    'contract': strike_data['call_contract'],
                    'right': 'C',
                    'strike': strike,
                    'bid': 0, 'ask': 0, 'last': 0, 'volume': 0,
                    'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0
                }
                
                self.subscribed_contracts.append(('C', strike, strike_data['call_contract']))
                self.reqMktData(req_id, strike_data['call_contract'], "", False, False, [])
            
            # Subscribe to put
            if strike_data['put']:
                req_id = self.next_req_id
                self.next_req_id += 1
                
                contract_key = f"SPX_{strike}_P"
                self.market_data_map[req_id] = contract_key
                
                self.market_data[contract_key] = {
                    'contract': strike_data['put_contract'],
                    'right': 'P',
                    'strike': strike,
                    'bid': 0, 'ask': 0, 'last': 0, 'volume': 0,
                    'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0
                }
                
                self.subscribed_contracts.append(('P', strike, strike_data['put_contract']))
                self.reqMktData(req_id, strike_data['put_contract'], "", False, False, [])
            
            # Create treeview row with call on left, strike in center, put on right
            # Format: C_Bid, C_Ask, C_Last, C_Vol, C_Gamma, C_Vega, C_Theta, C_Delta, C_IV, Strike, P_Delta, P_Theta, P_Vega, P_Gamma, P_Vol, P_Last, P_Ask, P_Bid
            values = (
                "0.00", "0.00", "0.00", "0", "0.00", "0.00", "0.00", "0.00", "0.00",  # Call data
                f"{strike:.2f}",  # Strike
                "0.00", "0.00", "0.00", "0.00", "0", "0.00", "0.00", "0.00"  # Put data
            )
            
            item = self.option_tree.insert("", tk.END, values=values, tags=(str(strike),))
            
            # Store tree item reference in both call and put data
            if f"SPX_{strike}_C" in self.market_data:
                self.market_data[f"SPX_{strike}_C"]['tree_item'] = item
            if f"SPX_{strike}_P" in self.market_data:
                self.market_data[f"SPX_{strike}_P"]['tree_item'] = item
        
        self.log_message(
            f"Successfully subscribed to {len(sorted_strikes) * 2} contracts ({len(sorted_strikes)} strikes)", 
            "SUCCESS"
        )
        
        # Start periodic GUI update loop
        self.root.after(500, self.update_option_chain_display)
        
        # Schedule automatic chain refresh based on settings
        refresh_ms = self.chain_refresh_interval * 1000  # Convert seconds to milliseconds
        self.log_message(f"Automatic chain refresh scheduled every {self.chain_refresh_interval} seconds", "INFO")
        self.root.after(refresh_ms, self.refresh_option_chain)
    
    def resubscribe_market_data(self):
        """
        Resubscribe to market data after reconnection.
        Uses the tracked subscribed_contracts list to restore all subscriptions.
        """
        if not self.subscribed_contracts:
            self.log_message("No previous subscriptions to restore", "INFO")
            return
        
        self.log_message(
            f"Resubscribing to {len(self.subscribed_contracts)} previously subscribed contracts...",
            "INFO"
        )
        
        # Use the existing subscribe_market_data method with stored contracts
        self.spx_contracts = self.subscribed_contracts
        self.subscribe_market_data()
    
    def update_option_chain_display(self):
        """
        Update the option chain display with latest market data.
        Updates rows with call data on left and put data on right (IBKR style).
        """
        if not self.root:
            return
        
        try:
            # Helper function to safely format values
            def safe_format(value, format_str, default="—"):
                """Safely format a value, returning default if None or invalid"""
                if value is None:
                    return default
                try:
                    if format_str == "int":
                        return str(int(value)) if value != 0 else "0"
                    elif format_str == ".2f":
                        return f"{float(value):.2f}" if value != 0 else "0.00"
                    elif format_str == ".4f":
                        return f"{float(value):.4f}" if value != 0 else "0.0000"
                    else:
                        return str(value)
                except (ValueError, TypeError):
                    return default
            
            # Group updates by strike (each row has both call and put)
            strikes_to_update = {}
            
            for contract_key, data in self.market_data.items():
                strike = data['strike']
                right = data['right']
                tree_item = data.get('tree_item')
                
                if tree_item and self.option_tree.exists(tree_item):
                    if strike not in strikes_to_update:
                        strikes_to_update[strike] = {
                            'tree_item': tree_item,
                            'call': None,
                            'put': None
                        }
                    
                    if right == 'C':
                        strikes_to_update[strike]['call'] = data
                    else:
                        strikes_to_update[strike]['put'] = data
            
            # Update each row with complete call/put data
            for strike, strike_data in strikes_to_update.items():
                call_data = strike_data['call']
                put_data = strike_data['put']
                tree_item = strike_data['tree_item']
                
                # Format: C_Bid, C_Ask, C_Last, C_Vol, C_Gamma, C_Vega, C_Theta, C_Delta, C_IV, Strike, P_Delta, P_Theta, P_Vega, P_Gamma, P_Vol, P_Last, P_Ask, P_Bid
                values = [
                    # Call columns (left side)
                    safe_format(call_data['bid'] if call_data else None, ".2f"),
                    safe_format(call_data['ask'] if call_data else None, ".2f"),
                    safe_format(call_data['last'] if call_data else None, ".2f"),
                    safe_format(call_data['volume'] if call_data else None, "int"),
                    safe_format(call_data['gamma'] if call_data else None, ".4f"),
                    safe_format(call_data['vega'] if call_data else None, ".4f"),
                    safe_format(call_data['theta'] if call_data else None, ".4f"),
                    safe_format(call_data['delta'] if call_data else None, ".4f"),
                    safe_format(call_data.get('iv', 0) if call_data else None, ".2f"),
                    
                    # Strike (center)
                    f"{strike:.2f}",
                    
                    # Put columns (right side)
                    safe_format(put_data['delta'] if put_data else None, ".4f"),
                    safe_format(put_data['theta'] if put_data else None, ".4f"),
                    safe_format(put_data['vega'] if put_data else None, ".4f"),
                    safe_format(put_data['gamma'] if put_data else None, ".4f"),
                    safe_format(put_data['volume'] if put_data else None, "int"),
                    safe_format(put_data['last'] if put_data else None, ".2f"),
                    safe_format(put_data['ask'] if put_data else None, ".2f"),
                    safe_format(put_data['bid'] if put_data else None, ".2f"),
                ]
                
                # Determine ITM/OTM/ATM status for color coding
                tags = []
                if self.spx_price > 0:
                    # Tolerance for ATM (within 0.5% of SPX price)
                    atm_tolerance = self.spx_price * 0.005
                    
                    if abs(strike - self.spx_price) <= atm_tolerance:
                        tags.append("atm")
                    elif strike < self.spx_price:
                        # Calls ITM when strike < spot, Puts OTM
                        tags.append("call_itm")
                    else:
                        # Calls OTM when strike > spot, Puts ITM
                        tags.append("put_itm")
                
                self.option_tree.item(tree_item, values=values, tags=tags)
            
            # Schedule next update
            self.root.after(500, self.update_option_chain_display)
            
        except Exception as e:
            self.log_message(f"Error updating option chain display: {e}", "ERROR")
            # Continue updating even if there was an error
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
        """
        Enter a long straddle at the top of the hour.
        Searches for the cheapest call and put with ask price <= $0.50.
        """
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot enter straddle: Not connected to IBKR", "WARNING")
            return
        
        self.log_message("=" * 60, "INFO")
        self.log_message("HOURLY STRADDLE ENTRY INITIATED", "INFO")
        self.log_message("Scanning option chain for entry opportunities (ask <= $0.50)...", "INFO")
        
        # Find cheapest call and put with ask <= $0.50
        best_call = None
        best_call_key = None
        best_put = None
        best_put_key = None
        
        calls_found = 0
        puts_found = 0
        
        for contract_key, data in self.market_data.items():
            ask = data['ask']
            
            # Only consider options with valid ask prices
            if ask <= 0.50 and ask > 0:
                if data['right'] == 'C':
                    calls_found += 1
                    if best_call is None or ask < best_call['ask']:
                        best_call = data
                        best_call_key = contract_key
                elif data['right'] == 'P':
                    puts_found += 1
                    if best_put is None or ask < best_put['ask']:
                        best_put = data
                        best_put_key = contract_key
        
        self.log_message(f"Found {calls_found} calls and {puts_found} puts with ask <= $0.50", "INFO")
        
        # Place orders if we found both legs
        if best_call and best_put:
            total_cost = best_call['ask'] + best_put['ask']
            self.log_message(
                f"STRADDLE SELECTED - Total cost: ${total_cost:.2f}", 
                "SUCCESS"
            )
            self.log_message(
                f"  Call: Strike {best_call['strike']:.2f} @ ${best_call['ask']:.2f} "
                f"(Delta: {best_call['delta']:.4f})", 
                "INFO"
            )
            self.log_message(
                f"  Put:  Strike {best_put['strike']:.2f} @ ${best_put['ask']:.2f} "
                f"(Delta: {best_put['delta']:.4f})", 
                "INFO"
            )
            
            # Place call order
            self.log_message("Placing CALL order...", "INFO")
            call_order_id = self.place_limit_order(best_call['contract'], "BUY", 1, 
                                                   best_call['ask'])
            self.pending_orders[call_order_id] = (best_call_key, "BUY", 1)
            
            # Place put order
            self.log_message("Placing PUT order...", "INFO")
            put_order_id = self.place_limit_order(best_put['contract'], "BUY", 1, 
                                                  best_put['ask'])
            self.pending_orders[put_order_id] = (best_put_key, "BUY", 1)
            
            # Track straddle for risk management
            straddle_info = {
                'call_key': best_call_key,
                'put_key': best_put_key,
                'entry_time': datetime.now(),
                'call_entry_price': best_call['ask'],
                'put_entry_price': best_put['ask'],
                'call_order_id': call_order_id,
                'put_order_id': put_order_id
            }
            self.active_straddles.append(straddle_info)
            
            self.log_message(f"Straddle orders placed (Call Order: {call_order_id}, Put Order: {put_order_id})", "SUCCESS")
        else:
            self.log_message(
                "STRADDLE ENTRY SKIPPED - No suitable options found with ask <= $0.50", 
                "WARNING"
            )
        
        self.log_message("=" * 60, "INFO")
    
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
            
            # Position tracking initialized
            # Historical data will be requested when chart is clicked
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
    
    def request_historical_data_for_supertrend(self, contract_key: str):
        """Request historical data for supertrend calculation - DEPRECATED"""
        # This method is deprecated - use request_historical_data instead
        pass
    
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
        """Update the matplotlib chart with supertrend - DEPRECATED, kept for compatibility"""
        # This method is no longer used - charts are now updated via update_call_chart and update_put_chart
        pass
    
    def on_option_chain_click(self, event):
        """Handle click on option chain to update charts"""
        try:
            selection = self.option_tree.selection()
            if not selection:
                self.log_message("No row selected in option chain", "WARNING")
                return
                
            item = selection[0]
            values = self.option_tree.item(item, 'values')
            
            if not values or len(values) < 10:
                self.log_message("Invalid row data in option chain", "WARNING")
                return
            
            # Get strike from center column (index 9) - convert to int to match contract keys
            strike = int(float(values[9]))
            
            # Determine if user clicked on call or put side based on column
            region = self.option_tree.identify_region(event.x, event.y)
            column = self.option_tree.identify_column(event.x)
            
            self.log_message(f"Clicked: region={region}, column={column}, strike={strike}", "INFO")
            
            if region == "cell":
                col_index = int(column.replace('#', '')) - 1
                
                # Columns 0-8 are calls, 9 is strike, 10-17 are puts
                if col_index < 9:
                    # Clicked on call side
                    contract_key = f"SPX_{strike}_C"
                    self.log_message(f"Looking for call contract: {contract_key}", "INFO")
                    
                    if contract_key in self.market_data:
                        self.selected_call_contract = self.market_data[contract_key]['contract']
                        self.log_message(f"✓ Selected CALL: Strike {strike} - Requesting chart data...", "SUCCESS")
                        self.update_call_chart()
                    else:
                        self.log_message(f"Contract {contract_key} not found in market_data", "WARNING")
                        self.log_message(f"Available contracts: {list(self.market_data.keys())[:5]}...", "DEBUG")
                        
                elif col_index > 9:
                    # Clicked on put side
                    contract_key = f"SPX_{strike}_P"
                    self.log_message(f"Looking for put contract: {contract_key}", "INFO")
                    
                    if contract_key in self.market_data:
                        self.selected_put_contract = self.market_data[contract_key]['contract']
                        self.log_message(f"✓ Selected PUT: Strike {strike} - Requesting chart data...", "SUCCESS")
                        self.update_put_chart()
                    else:
                        self.log_message(f"Contract {contract_key} not found in market_data", "WARNING")
                        self.log_message(f"Available contracts: {list(self.market_data.keys())[:5]}...", "DEBUG")
                else:
                    self.log_message("Clicked on strike column - please click on call or put columns", "INFO")
                        
        except Exception as e:
            self.log_message(f"Error handling option chain click: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
    
    def show_call_loading(self):
        """Show loading spinner on call chart with animated rotation"""
        if self.root:
            # Place the loading frame over the chart
            self.call_loading_frame.place(relx=0.5, rely=0.5, anchor=CENTER, relwidth=0.5, relheight=0.3)
            self.animate_call_spinner()
            
            # Set 30-second timeout
            if self.call_loading_timeout_id:
                self.root.after_cancel(self.call_loading_timeout_id)
            self.call_loading_timeout_id = self.root.after(30000, self.call_loading_timeout)
    
    def hide_call_loading(self):
        """Hide loading spinner on call chart"""
        if self.root:
            self.call_loading_frame.place_forget()
            if self.call_loading_timeout_id:
                self.root.after_cancel(self.call_loading_timeout_id)
                self.call_loading_timeout_id = None
    
    def animate_call_spinner(self):
        """Animate the call chart loading spinner"""
        if self.call_loading_frame.winfo_ismapped():
            current_text = self.call_loading_label.cget("text")
            # Rotate through different spinner states
            if "⟳" in current_text:
                new_text = current_text.replace("⟳", "⟲")
            else:
                new_text = current_text.replace("⟲", "⟳")
            self.call_loading_label.config(text=new_text)
            if self.root:
                self.root.after(500, self.animate_call_spinner)
    
    def call_loading_timeout(self):
        """Handle call chart loading timeout"""
        self.hide_call_loading()
        self.log_message("Call chart failed to load data within 30 seconds", "WARNING")
    
    def show_put_loading(self):
        """Show loading spinner on put chart with animated rotation"""
        if self.root:
            # Place the loading frame over the chart
            self.put_loading_frame.place(relx=0.5, rely=0.5, anchor=CENTER, relwidth=0.5, relheight=0.3)
            self.animate_put_spinner()
            
            # Set 30-second timeout
            if self.put_loading_timeout_id:
                self.root.after_cancel(self.put_loading_timeout_id)
            self.put_loading_timeout_id = self.root.after(30000, self.put_loading_timeout)
    
    def hide_put_loading(self):
        """Hide loading spinner on put chart"""
        if self.root:
            self.put_loading_frame.place_forget()
            if self.put_loading_timeout_id:
                self.root.after_cancel(self.put_loading_timeout_id)
                self.put_loading_timeout_id = None
    
    def animate_put_spinner(self):
        """Animate the put chart loading spinner"""
        if self.put_loading_frame.winfo_ismapped():
            current_text = self.put_loading_label.cget("text")
            # Rotate through different spinner states
            if "⟳" in current_text:
                new_text = current_text.replace("⟳", "⟲")
            else:
                new_text = current_text.replace("⟲", "⟳")
            self.put_loading_label.config(text=new_text)
            if self.root:
                self.root.after(500, self.animate_put_spinner)
    
    def put_loading_timeout(self):
        """Handle put chart loading timeout"""
        self.hide_put_loading()
        self.log_message("Put chart failed to load data within 30 seconds", "WARNING")
    
    def on_call_settings_changed(self):
        """Handle call chart settings change - clear data and refresh"""
        if self.selected_call_contract:
            contract_key = f"SPX_{self.selected_call_contract.strike}_{self.selected_call_contract.right}"
            # Clear historical data to force re-request with new settings
            if contract_key in self.historical_data:
                del self.historical_data[contract_key]
        self.update_call_chart()
    
    def on_put_settings_changed(self):
        """Handle put chart settings change - clear data and refresh"""
        if self.selected_put_contract:
            contract_key = f"SPX_{self.selected_put_contract.strike}_{self.selected_put_contract.right}"
            # Clear historical data to force re-request with new settings
            if contract_key in self.historical_data:
                del self.historical_data[contract_key]
        self.update_put_chart()
    
    def update_call_chart(self):
        """
        Update the call candlestick chart for selected contract.
        Uses debouncing to prevent rapid successive updates for better responsiveness.
        """
        if not self.root:
            return
            
        # Cancel any pending update
        if self.call_chart_update_pending:
            self.root.after_cancel(self.call_chart_update_pending)
            self.call_chart_update_pending = None
        
        # Schedule debounced update
        self.call_chart_update_pending = self.root.after(
            self.chart_debounce_delay, 
            self._update_call_chart_immediate
        )
    
    def _update_call_chart_immediate(self):
        """Immediate chart update (called after debounce delay)"""
        self.call_chart_update_pending = None
        
        if not self.selected_call_contract:
            return
        
        contract_key = f"SPX_{self.selected_call_contract.strike}_{self.selected_call_contract.right}"
        
        # Request historical data if not already requested or if settings changed
        if contract_key not in self.historical_data or len(self.historical_data.get(contract_key, [])) == 0:
            self.log_message(f"Requesting {self.call_days_var.get()}D historical data for {contract_key}...", "INFO")
            self.show_call_loading()  # Show loading spinner
            self.request_historical_data(self.selected_call_contract, contract_key, 'call')
            return
        
        # Draw candlestick chart (suppress repetitive log)
        self.hide_call_loading()  # Hide loading spinner when data is available
        self.draw_candlestick_chart(self.call_ax, self.call_canvas, contract_key, "Call")
    
    def update_put_chart(self):
        """
        Update the put candlestick chart for selected contract.
        Uses debouncing to prevent rapid successive updates for better responsiveness.
        """
        if not self.root:
            return
            
        # Cancel any pending update
        if self.put_chart_update_pending:
            self.root.after_cancel(self.put_chart_update_pending)
            self.put_chart_update_pending = None
        
        # Schedule debounced update
        self.put_chart_update_pending = self.root.after(
            self.chart_debounce_delay, 
            self._update_put_chart_immediate
        )
    
    def _update_put_chart_immediate(self):
        """Immediate chart update (called after debounce delay)"""
        self.put_chart_update_pending = None
        
        if not self.selected_put_contract:
            return
        
        contract_key = f"SPX_{self.selected_put_contract.strike}_{self.selected_put_contract.right}"
        
        # Request historical data if not already requested or if settings changed
        if contract_key not in self.historical_data or len(self.historical_data.get(contract_key, [])) == 0:
            self.log_message(f"Requesting {self.put_days_var.get()}D historical data for {contract_key}...", "INFO")
            self.show_put_loading()  # Show loading spinner
            self.request_historical_data(self.selected_put_contract, contract_key, 'put')
            return
        
        # Draw candlestick chart (suppress repetitive log)
        self.hide_put_loading()  # Hide loading spinner when data is available
        self.draw_candlestick_chart(self.put_ax, self.put_canvas, contract_key, "Put")
    
    def request_historical_data(self, contract, contract_key, option_type):
        """Request historical bar data for charting"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot request historical data - not connected", "WARNING")
            return
        
        req_id = self.next_req_id
        self.next_req_id += 1
        
        self.historical_data_requests[req_id] = contract_key
        
        # Map timeframe to bar size
        timeframe = self.call_timeframe_var.get() if option_type == 'call' else self.put_timeframe_var.get()
        bar_size_map = {
            "1 min": "1 min",
            "5 min": "5 mins",
            "15 min": "15 mins",
            "30 min": "30 mins",
            "1 hour": "1 hour"
        }
        bar_size = bar_size_map.get(timeframe, "1 min")
        
        # Get days back from selector
        days_back = int(self.call_days_var.get() if option_type == 'call' else self.put_days_var.get())
        duration = f"{days_back} D"  # Days in format "5 D"
        
        try:
            # For options, we need to use different parameters
            # Paper trading may not have full historical data for options
            self.reqHistoricalData(
                req_id,
                contract,
                "",  # End date/time (empty = now)
                duration,
                bar_size,
                "MIDPOINT",  # Use MIDPOINT for options (more reliable than TRADES)
                0,  # Include extended hours (0 = all hours)
                1,  # Format date as string
                False,  # Keep up to date
                []  # Chart options
            )
            
            self.log_message(f"Historical data request sent (reqId: {req_id})", "INFO")
            
        except Exception as e:
            self.log_message(f"Error requesting historical data: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
    
    def draw_candlestick_chart(self, ax, canvas, contract_key, chart_type):
        """
        Draw professional candlestick chart with mid-price using optimized rendering.
        Uses efficient data structures and minimal redraws for TradingView-like responsiveness.
        """
        try:
            # Clear previous artists efficiently
            ax.clear()
            
            # Check if we have historical data
            if contract_key not in self.historical_data or len(self.historical_data[contract_key]) < 2:
                # FALLBACK: Display current market data instead
                strike = contract_key.split('_')[1]
                
                if contract_key in self.market_data:
                    md = self.market_data[contract_key]
                    bid = md.get('bid', 0)
                    ask = md.get('ask', 0)
                    last = md.get('last', 0)
                    
                    # Display text information
                    ax.text(0.5, 0.6, f"{chart_type} Option - Strike {strike}", 
                           ha='center', va='center', fontsize=12, color='#E0E0E0',
                           transform=ax.transAxes, weight='bold')
                    
                    ax.text(0.5, 0.45, f"Bid: ${bid:.2f}  |  Ask: ${ask:.2f}  |  Last: ${last:.2f}", 
                           ha='center', va='center', fontsize=10, color='#FF8C00',
                           transform=ax.transAxes)
                    
                    ax.text(0.5, 0.3, "Historical data unavailable", 
                           ha='center', va='center', fontsize=9, color='#888888',
                           transform=ax.transAxes, style='italic')
                    
                    ax.text(0.5, 0.2, "(Paper trading accounts have limited historical data access)", 
                           ha='center', va='center', fontsize=8, color='#666666',
                           transform=ax.transAxes, style='italic')
                else:
                    ax.text(0.5, 0.5, f"{chart_type} Option - Strike {strike}\n\nNo market data available", 
                           ha='center', va='center', fontsize=11, color='#888888',
                           transform=ax.transAxes)
                
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.axis('off')
                canvas.draw()
                return
            
            # OPTIMIZATION 1: Use numpy for fast array operations
            data = self.historical_data[contract_key]
            n_bars = len(data)
            
            # Pre-allocate numpy arrays for better performance
            indices = np.arange(n_bars)
            opens = np.array([bar['open'] for bar in data])
            highs = np.array([bar['high'] for bar in data])
            lows = np.array([bar['low'] for bar in data])
            closes = np.array([bar['close'] for bar in data])
            dates = [bar['date'] for bar in data]
            
            # Calculate mid prices using numpy (faster than list comprehension)
            mids = (highs + lows) / 2
            
            # OPTIMIZATION 2: Vectorized color determination
            is_bullish = closes >= opens
            
            # OPTIMIZATION 3: Draw candlesticks in batches instead of individually
            # Separate bullish and bearish candles for batch drawing
            bullish_indices = indices[is_bullish]
            bearish_indices = indices[~is_bullish]
            
            # Draw high-low lines in batches
            for idx_arr, color in [(bullish_indices, '#44FF44'), (bearish_indices, '#FF4444')]:
                if len(idx_arr) > 0:
                    for i in idx_arr:
                        i_scalar = int(i)  # Convert numpy int to Python int
                        ax.plot([i_scalar, i_scalar], [float(lows[i]), float(highs[i])], 
                               color=color, linewidth=1, solid_capstyle='butt', antialiased=True)
            
            # Draw bodies using collections for better performance
            for idx_arr, color in [(bullish_indices, '#44FF44'), (bearish_indices, '#FF4444')]:
                if len(idx_arr) > 0:
                    for i in idx_arr:
                        i_scalar = int(i)  # Convert numpy int to Python int
                        body_height = float(abs(closes[i] - opens[i]))
                        body_bottom = float(min(opens[i], closes[i]))
                        rect = Rectangle((i_scalar - 0.3, body_bottom), 0.6, body_height, 
                                       facecolor=color, edgecolor=color, linewidth=0.5)
                        ax.add_patch(rect)
            
            # OPTIMIZATION 4: Plot mid-price line once (vectorized)
            ax.plot(indices, mids, color='#FF8C00', linewidth=1.5, 
                   label='Mid Price', alpha=0.7, antialiased=True, zorder=10)
            
            # OPTIMIZATION 5: Efficient styling - set all at once
            strike = contract_key.split('_')[1]
            ax.set_title(f"{chart_type} Chart - Strike {strike}", 
                        color='#E0E0E0', fontsize=10, pad=5)
            ax.set_xlabel('Time', color='#E0E0E0', fontsize=8)
            ax.set_ylabel('Price', color='#E0E0E0', fontsize=8)
            ax.grid(True, alpha=0.2, color='#444444', linewidth=0.5, linestyle='-')
            
            # Legend with minimal overhead
            ax.legend(facecolor='#181818', edgecolor='#FF8C00', 
                     labelcolor='#E0E0E0', fontsize=8, loc='best', framealpha=0.9)
            
            # OPTIMIZATION 6: Smart x-axis labeling - show fewer ticks for large datasets
            if n_bars > 0:
                # Adaptive tick spacing based on data size
                tick_spacing = max(1, n_bars // 15)  # Show ~15 ticks maximum
                xtick_positions = list(range(0, n_bars, tick_spacing))
                
                # Ensure we include the last point
                if xtick_positions[-1] != n_bars - 1:
                    xtick_positions.append(n_bars - 1)
                
                # Extract time from date strings efficiently
                xtick_labels = [dates[i].split()[1] if ' ' in dates[i] else dates[i] 
                               for i in xtick_positions]
                
                ax.set_xticks(xtick_positions)
                ax.set_xticklabels(xtick_labels, rotation=45, ha='right', fontsize=7)
            
            # Set reasonable limits to avoid auto-scaling overhead
            ax.set_xlim(-0.5, n_bars - 0.5)
            y_min, y_max = np.min(lows), np.max(highs)
            y_padding = (y_max - y_min) * 0.05  # 5% padding
            ax.set_ylim(y_min - y_padding, y_max + y_padding)
            
            # OPTIMIZATION 7: Use draw_idle() for non-blocking updates
            # This queues the redraw instead of blocking immediately
            canvas.draw_idle()
            
            # OPTIMIZATION 8: No auto-refresh - let users manually refresh for better responsiveness
            # Remove automatic chart updates that cause sluggishness
            
        except Exception as e:
            self.log_message(f"Error drawing {chart_type} chart: {e}", "ERROR")
    
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
        """
        Log a message to both the GUI and console.
        
        Args:
            message: The message to log
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # GUI log entry (can include emojis)
        log_entry = f"[{timestamp}] {message}\n"
        self.log_text.insert(tk.END, log_entry, level)
        self.log_text.see(tk.END)
        
        # Console log (no emojis, plain text)
        console_message = f"[{timestamp}] [{level}] {message}"
        print(console_message)
        
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
    try:
        print("=" * 70)
        print("SPX 0DTE Options Trading Application - Professional Edition")
        print("=" * 70)
        print("[STARTUP] Initializing application components...")
        
        app = SPXTradingApp()
        
        print("[STARTUP] Application initialized successfully")
        print("[STARTUP] Launching GUI...")
        print("[STARTUP] Auto-connect is ENABLED - will connect to IBKR after GUI loads")
        print("=" * 70)
        
        app.run_gui()
        
    except Exception as e:
        print(f"[FATAL ERROR] Application crashed: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
