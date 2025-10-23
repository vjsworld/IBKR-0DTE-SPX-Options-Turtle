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
from ttkbootstrap.constants import BOTH, YES, X, Y, LEFT, RIGHT, BOTTOM, TOP, CENTER, END, W, E, EW, SUNKEN, HORIZONTAL, VERTICAL
from tksheet import Sheet
import threading
import queue
import time
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import json
import os
import logging
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from collections import deque
import pandas as pd
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates
from tksheet import Sheet

# Lightweight-charts for professional TradingView-style charting
try:
    from lightweight_charts import Chart
    LIGHTWEIGHT_CHARTS_AVAILABLE = True
except ImportError:
    LIGHTWEIGHT_CHARTS_AVAILABLE = False
    print("WARNING: lightweight-charts not installed. Run: pip install lightweight-charts")

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
from ibapi.order import Order, UNSET_DOUBLE, UNSET_INTEGER
from ibapi.common import TickerId, TickAttrib
from ibapi.ticktype import TickType
from scipy.stats import norm
import math


# ============================================================================
# TRADING SYMBOL CONFIGURATION
# ============================================================================
# Change this to switch between SPX (standard) and XSP (mini, 1/10th size)
# SPX: Full-size contracts (~$410k notional, $100 multiplier)
# XSP: Mini contracts (~$41k notional, $100 multiplier, 1/10th SPX value)
# 
# XSP ADVANTAGES:
# - 10x more flexible position sizing
# - Lower capital requirements
# - Lower commissions ($0.31-$0.60 vs $0.70-$2.51)
# - Daily expirations (Mon-Fri)
# - Same 60/40 tax treatment
#
# See CBOE_TRADING_REFERENCE.md for full details

TRADING_SYMBOL = "XSP"  # Options: "SPX" or "XSP"
TRADING_CLASS = "XSP"   # Must match TRADING_SYMBOL
UNDERLYING_SYMBOL = "XSP"  # For underlying price subscription


# ============================================================================
# FILE LOGGING SETUP
# ============================================================================

def setup_file_logger():
    """
    Setup file logging with daily log files in logs/ directory
    
    Creates a new log file each day with format: YYYY-MM-DD.txt
    All log entries are timestamped and arranged vertically
    """
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create log filename with today's date
    log_filename = datetime.now().strftime('%Y-%m-%d.txt')
    log_filepath = os.path.join(logs_dir, log_filename)
    
    # Configure file logger
    file_logger = logging.getLogger('SPXTradingApp')
    file_logger.setLevel(logging.DEBUG)  # Capture everything
    
    # Remove existing handlers to avoid duplicates
    file_logger.handlers.clear()
    
    # Create file handler
    file_handler = logging.FileHandler(log_filepath, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatter with timestamp
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Add handler to logger
    file_logger.addHandler(file_handler)
    
    # Log startup
    file_logger.info("=" * 80)
    file_logger.info("SPX 0DTE Options Trading Application - Session Started")
    file_logger.info("=" * 80)
    
    return file_logger

# Initialize file logger
file_logger = setup_file_logger()


# ============================================================================
# BLACK-SCHOLES GREEKS CALCULATIONS
# ============================================================================

def calculate_greeks(option_type: str, spot_price: float, strike: float, 
                     time_to_expiry: float, volatility: float, risk_free_rate: float = 0.05) -> dict:
    """
    Calculate option greeks using Black-Scholes model
    
    Args:
        option_type: 'C' for call, 'P' for put
        spot_price: Current price of underlying (SPX)
        strike: Strike price of option
        time_to_expiry: Time to expiration in years (e.g., 0.00274 for 1 day assuming 365 days/year)
        volatility: Implied volatility as decimal (e.g., 0.20 for 20%)
        risk_free_rate: Risk-free interest rate as decimal (default 0.05 for 5%)
    
    Returns:
        dict with keys: delta, gamma, theta, vega, iv
    """
    try:
        # Handle edge cases
        if time_to_expiry <= 0:
            # At expiration
            if option_type == 'C':
                delta = 1.0 if spot_price > strike else 0.0
            else:
                delta = -1.0 if spot_price < strike else 0.0
            return {
                'delta': delta,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0,
                'iv': volatility
            }
        
        if volatility <= 0 or spot_price <= 0 or strike <= 0:
            return {
                'delta': 0.0,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0,
                'iv': 0.0
            }
        
        # Calculate d1 and d2
        d1 = (math.log(spot_price / strike) + (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        
        # Standard normal CDF and PDF
        N_d1 = norm.cdf(d1)
        N_d2 = norm.cdf(d2)
        n_d1 = norm.pdf(d1)  # PDF for gamma and vega
        
        # Delta
        if option_type == 'C':
            delta = N_d1
        else:  # Put
            delta = N_d1 - 1.0
        
        # Gamma (same for calls and puts)
        gamma = n_d1 / (spot_price * volatility * math.sqrt(time_to_expiry))
        
        # Theta (per day, not per year)
        if option_type == 'C':
            theta = (-(spot_price * n_d1 * volatility) / (2 * math.sqrt(time_to_expiry)) 
                    - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * N_d2) / 365
        else:  # Put
            theta = (-(spot_price * n_d1 * volatility) / (2 * math.sqrt(time_to_expiry)) 
                    + risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * (1 - N_d2)) / 365
        
        # Vega (per 1% change in volatility)
        vega = spot_price * math.sqrt(time_to_expiry) * n_d1 / 100
        
        return {
            'delta': round(float(delta), 4),
            'gamma': round(float(gamma), 4),
            'theta': round(float(theta), 4),
            'vega': round(float(vega), 4),
            'iv': round(volatility, 4)
        }
        
    except Exception as e:
        # Return zeros on any calculation error
        return {
            'delta': 0.0,
            'gamma': 0.0,
            'theta': 0.0,
            'vega': 0.0,
            'iv': 0.0
        }


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
        - 10147: Order not found (expected during rapid cancel/replace)
        - 10268: EtradeOnly attribute not supported (benign, can ignore)
        """
        error_msg = f"Error {errorCode}: {errorString}"
        
        # Handle benign error codes first (before logging)
        if errorCode == 10268:  # EtradeOnly attribute error (benign warning)
            # This is a benign warning from TWS - orders still process correctly
            # Log once to inform user, then suppress
            if not hasattr(self.app, '_logged_10268'):
                self.app._logged_10268 = True
                self.app.log_message("ℹ Note: TWS reports 'eTradeOnly' attribute warnings - this is normal and can be ignored", "INFO")
            return
        
        # CRITICAL: Log ALL errors for debugging order placement issues
        # For order-related errors (reqId >= order_id range), always log
        if reqId >= 1000 or errorCode not in [2104, 2106, 2158]:
            # Special highlighting for order-related errors
            if reqId >= 1000:
                self.app.log_message(f"🚨 [ORDER ERROR] Order #{reqId}, Code={errorCode}, Msg={errorString}", "ERROR")
            else:
                self.app.log_message(f"[ERROR CALLBACK] ReqId={reqId}, Code={errorCode}, Msg={errorString}", "WARNING")
        
        # Data server connection confirmed (CRITICAL for order placement!)
        if errorCode in [2104, 2106]:  # "Market data farm connection is OK"
            self.app.log_message("✓ Data server connection confirmed - ready for trading", "SUCCESS")
            self.app.data_server_ok = True
            return
        
        # Security definition server OK
        if errorCode == 2158:  # "Sec-def data farm connection is OK"
            self.app.log_message("✓ Security definition server OK", "INFO")
            return
        
        if errorCode == 10147:  # Order already filled/cancelled
            self.app.log_message(f"Order {reqId} already processed (fill or cancel)", "INFO")
            return
        
        # Log all other errors
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
        
        # Order rejection errors
        elif errorCode in [201, 202, 203, 204, 205, 206, 207]:  # Order rejected
            self.app.log_message(f"ORDER REJECTED (orderId={reqId}): {errorString}", "ERROR")
            # Remove from pending orders if exists
            if reqId in self.app.pending_orders:
                del self.app.pending_orders[reqId]
            # Remove from manual orders tracking
            if reqId in self.app.manual_orders:
                del self.app.manual_orders[reqId]
            # Update order sheet
            self.app.update_order_in_tree(reqId, status="REJECTED", price=0)
        elif errorCode == 110:  # Price is out of range
            self.app.log_message(f"ORDER PRICE OUT OF RANGE (orderId={reqId}): {errorString}", "ERROR")
        elif errorCode == 200:  # No security definition found
            self.app.log_message(f"ORDER ERROR - Security not found (orderId={reqId}): {errorString}", "ERROR")
            # Remove from pending orders if exists
            if reqId in self.app.pending_orders:
                del self.app.pending_orders[reqId]
            if reqId in self.app.manual_orders:
                del self.app.manual_orders[reqId]
            self.app.update_order_in_tree(reqId, status="REJECTED", price=0)
        
        # Historical data errors
        elif errorCode == 162:  # Historical market data Service error
            # Check if this is a chart cancellation (expected when refreshing charts)
            if reqId in [999994, 999995] and "cancelled" in errorString.lower():
                # This is expected when we cancel a chart subscription - ignore it
                return
            
            self.app.log_message(f"Historical data permission issue for reqId {reqId}: {errorString}", "WARNING")
            # Check if this is a historical data request
            if reqId in self.app.historical_data_requests:
                contract_key = self.app.historical_data_requests[reqId]
                self.app.log_message(
                    f"Historical data unavailable for {contract_key}. "
                    f"Paper trading accounts may have limited historical data access.",
                    "WARNING"
                )
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
    
    def managedAccounts(self, accountsList: str):
        """
        Receives the list of managed accounts.
        CRITICAL: Must set account in orders or TWS may silently reject them!
        Per working example: use LAST account in list (usually paper trading account)
        """
        self.app.managed_accounts = accountsList.split(',')
        # Use LAST account (per working example - usually the paper trading account)
        self.app.account = self.app.managed_accounts[-1] if self.app.managed_accounts else ""
        self.app.log_message(f"✓ Managed accounts: {accountsList}", "SUCCESS")
        self.app.log_message(f"✓ Using account (LAST in list): {self.app.account}", "SUCCESS")
    
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
        
        # Check if this is VIX price
        if reqId == self.app.vix_req_id:
            if tickType == 4:  # LAST price
                self.app.vix_price = price
                if hasattr(self.app, 'update_vix_display'):
                    self.app.update_vix_display()
            return
        
        # Handle option contract prices
        if reqId in self.app.market_data_map:
            contract_key = self.app.market_data_map[reqId]
            
            if tickType == 1:  # BID
                self.app.market_data[contract_key]['bid'] = price
                # Update position P&L with new mid-price
                if contract_key in self.app.positions:
                    self.app.update_position_pnl(contract_key)
                    
            elif tickType == 2:  # ASK
                self.app.market_data[contract_key]['ask'] = price
                # Update position P&L with new mid-price
                if contract_key in self.app.positions:
                    self.app.update_position_pnl(contract_key)
                    
            elif tickType == 4:  # LAST
                self.app.market_data[contract_key]['last'] = price
                # Update position P&L if this is a held position
                if contract_key in self.app.positions:
                    self.app.update_position_pnl(contract_key, price)
                    
            elif tickType == 9:  # CLOSE PRICE (previous day's close)
                self.app.market_data[contract_key]['prev_close'] = price
    
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
        """
        Receives option greeks.
        Tick Type 13 (MODEL_OPTION) = Model-based greeks that work without Last price.
        This uses bid/ask mid-price for calculations when Last is unavailable.
        """
        if reqId in self.app.market_data_map:
            contract_key = self.app.market_data_map[reqId]
            
            # Accept greeks from any tick type, but prioritize MODEL (13)
            # Tick type 13 = MODEL_OPTION (always calculated even without Last)
            # Tick types 10, 11, 12 = BID, ASK, LAST based greeks
            self.app.market_data[contract_key].update({
                'delta': delta if delta != -2 and delta != -1 else 0,
                'gamma': gamma if gamma != -2 and gamma != -1 else 0,
                'theta': theta if theta != -2 and theta != -1 else 0,
                'vega': vega if vega != -2 and vega != -1 else 0,
                'iv': impliedVol if impliedVol != -2 and impliedVol != -1 else 0
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
        
        # Update order display in GUI
        self.app.update_order_in_tree(orderId, status, avgFillPrice if avgFillPrice > 0 else None)
        
        # If order is filled, update position
        if status == "Filled" and orderId in self.app.pending_orders:
            contract_key, action, quantity = self.app.pending_orders[orderId]
            self.app.update_position_on_fill(contract_key, action, quantity, avgFillPrice)
            del self.app.pending_orders[orderId]
            
            # Also remove from manual_orders tracking if present
            if orderId in self.app.manual_orders:
                del self.app.manual_orders[orderId]
        
        # Handle Z-Score strategy order fills
        if self.app.active_trade_info:
            trade = self.app.active_trade_info
            
            # Entry order filled
            if orderId == trade.get('order_id') and status == "Filled":
                trade['status'] = 'FILLED'
                trade['entry_price'] = avgFillPrice
                self.app.log_message(
                    f"STRATEGY: Entry filled @ ${avgFillPrice:.2f}",
                    "SUCCESS"
                )
                if hasattr(self.app, 'strategy_status_var'):
                    direction = trade.get('direction', 'UNKNOWN')
                    self.app.strategy_status_var.set(f"Status: IN TRADE ({direction})")
            
            # Exit order filled - trade complete
            elif orderId == trade.get('exit_order_id') and status == "Filled":
                # Calculate final P&L
                entry_price = trade.get('entry_price', 0)
                pnl = (avgFillPrice - entry_price) * self.app.trade_qty * 100
                
                # Log trade completion
                self.app.log_message(
                    f"STRATEGY: Exit filled @ ${avgFillPrice:.2f} | P&L: ${pnl:.2f} | "
                    f"Reason: {trade.get('exit_reason', 'Unknown')}",
                    "SUCCESS" if pnl > 0 else "WARNING"
                )
                
                # Add to trade history
                trade['exit_price_final'] = avgFillPrice
                trade['pnl'] = pnl
                trade['exit_status'] = 'FILLED'
                self.app.trade_history.append(trade.copy())
                
                # Clear active trade
                self.app.active_trade_info = {}
                
                # Update status display
                if hasattr(self.app, 'strategy_status_var'):
                    self.app.strategy_status_var.set("Status: SCANNING...")
    
    def openOrder(self, orderId: int, contract: Contract, order: Order,
                 orderState):
        """Receives open order information - confirms TWS received the order"""
        contract_key = self.app.get_contract_key(contract)
        self.app.log_message(f"=" * 60, "SUCCESS")
        self.app.log_message(f"✓✓✓ TWS RECEIVED Order #{orderId} ✓✓✓", "SUCCESS")
        self.app.log_message(f"Contract: {contract_key}", "INFO")
        self.app.log_message(f"Action: {order.action} {order.totalQuantity} @ ${order.lmtPrice:.2f}", "INFO")
        self.app.log_message(f"Order State: {orderState.status}", "INFO")
        self.app.log_message(f"=" * 60, "SUCCESS")
    
    def position(self, account: str, contract: Contract, position: float,
                avgCost: float):
        """Receives position updates from IBKR"""
        contract_key = self.app.get_contract_key(contract)
        
        if position != 0:
            # For options, avgCost from IBKR is total cost per contract (includes 100x multiplier)
            # Divide by 100 to get per-option price for display
            per_option_cost = avgCost / 100 if contract.secType == "OPT" else avgCost
            
            self.app.positions[contract_key] = {
                'contract': contract,
                'position': position,
                'avgCost': per_option_cost,  # Per-option price for display
                'currentPrice': 0,
                'pnl': 0,
                'entryTime': datetime.now()
            }
            self.app.log_message(
                f"Position update: {contract_key} - Qty: {position} @ ${per_option_cost:.2f}",
                "INFO"
            )
            
            # Subscribe to market data for this position if not already subscribed
            # Check if we have an active subscription (not just market_data entry)
            is_subscribed = any(contract_key == v for v in self.app.market_data_map.values())
            
            if not is_subscribed:
                self.app.log_message(f"Subscribing to market data for position: {contract_key}", "INFO")
                
                # Create market data entry and subscribe
                req_id = self.app.next_req_id
                self.app.next_req_id += 1
                
                # Ensure contract has required fields for market data subscription
                # IBKR position callback may not include exchange, so set it explicitly
                if not contract.exchange:
                    contract.exchange = "SMART"
                if not contract.tradingClass:
                    contract.tradingClass = TRADING_CLASS
                
                self.app.market_data_map[req_id] = contract_key
                
                # Create market_data entry if it doesn't exist
                if contract_key not in self.app.market_data:
                    self.app.market_data[contract_key] = {
                        'contract': contract,
                        'right': contract.right,
                        'strike': contract.strike,
                        'bid': 0, 'ask': 0, 'last': 0, 'volume': 0,
                        'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0
                    }
                    self.app.log_message(f"Created market_data entry for {contract_key}", "INFO")
                
                self.app.reqMktData(req_id, contract, "", False, False, [])
                self.app.log_message(f"Requested market data (reqId={req_id}) for {contract_key}", "INFO")
            else:
                self.app.log_message(f"Position {contract_key} already has active subscription", "INFO")
        else:
            # Position closed - remove from tracking
            if contract_key in self.app.positions:
                del self.app.positions[contract_key]
                self.app.log_message(
                    f"Position closed: {contract_key}",
                    "INFO"
                )
    
    def positionEnd(self):
        """Called when initial position data is complete"""
        self.app.log_message(
            f"Position subscription complete - {len(self.app.positions)} position(s)",
            "INFO"
        )
        self.app.update_positions_display()
    
    def execDetails(self, reqId: int, contract: Contract, execution):
        """Receives execution details - recommended by IBKR for comprehensive monitoring"""
        contract_key = self.app.get_contract_key(contract)
        self.app.log_message(
            f"Execution: Order #{execution.orderId} - {contract_key} "
            f"{execution.side} {execution.shares} @ ${execution.price:.2f}",
            "SUCCESS"
        )
    
    def execDetailsEnd(self, reqId: int):
        """Called when execution details request is complete"""
        pass
    
    def historicalData(self, reqId: int, bar):
        """Receives historical bar data"""
        # Handle SPX 1-min data for Z-Score strategy
        if reqId == self.app.spx_1min_req_id:
            self.app.spx_1min_bars.append({
                'time': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close
            })
        # Handle Confirmation chart data (reqId 999995)
        elif reqId == 999995:
            self.app.confirm_bar_data.append({
                'time': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })
        # Handle Trade chart data (reqId 999994)
        elif reqId == 999994:
            self.app.trade_bar_data.append({
                'time': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })
        # Handle option historical data (existing code)
        elif reqId in self.app.historical_data_requests:
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
        # Handle SPX 1-min data completion
        if reqId == self.app.spx_1min_req_id:
            self.app.log_message(
                f"SPX 1-min history received ({len(self.app.spx_1min_bars)} bars) for Z-Score",
                "SUCCESS"
            )
            self.app.calculate_indicators()
        # Handle Confirmation chart completion (reqId 999995)
        elif reqId == 999995:
            self.app.log_message(
                f"Confirmation chart historical data received ({len(self.app.confirm_bar_data)} bars)",
                "SUCCESS"
            )
            # Update confirmation chart
            if hasattr(self.app, 'update_chart_display'):
                self.app.root.after(100, lambda: self.app.update_chart_display("confirm"))
        # Handle Trade chart completion (reqId 999994)
        elif reqId == 999994:
            self.app.log_message(
                f"Trade chart historical data received ({len(self.app.trade_bar_data)} bars)",
                "SUCCESS"
            )
            # Update trade chart
            if hasattr(self.app, 'update_chart_display'):
                self.app.root.after(100, lambda: self.app.update_chart_display("trade"))
        # Handle option historical data (existing code)
        elif reqId in self.app.historical_data_requests:
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
            
            # Determine if this is a call or put based on contract_key
            # Format: SPX_6740_C_20251020 or SPX_6745_P_20251020
            is_call = '_C_' in contract_key
            is_put = '_P_' in contract_key
            
            # Update the appropriate chart and hide loading spinner
            if is_call and self.app.selected_call_contract:
                self.app.log_message("Updating call chart with new data", "INFO")
                if self.app.root:
                    self.app.root.after(100, self.app.update_call_chart)
                    # Always hide loading spinner when data arrives
                    self.app.root.after(200, self.app.hide_call_loading)
            elif is_put and self.app.selected_put_contract:
                self.app.log_message("Updating put chart with new data", "INFO")
                if self.app.root:
                    self.app.root.after(100, self.app.update_put_chart)
                    # Always hide loading spinner when data arrives
                    self.app.root.after(200, self.app.hide_put_loading)
        else:
            self.app.log_message(f"Historical data end for unknown reqId: {reqId}", "WARNING")
    
    def historicalDataUpdate(self, reqId: int, bar):
        """Called when streaming historical data updates (real-time bars)"""
        if reqId == self.app.spx_1min_req_id:
            # Parse the date string to datetime
            bar_time = datetime.strptime(bar.date, '%Y%m%d  %H:%M:%S')
            self.app.spx_1min_bars.append({
                'time': bar_time,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close
            })
            # Recalculate indicators with new bar
            self.app.calculate_indicators()
        # Handle Confirmation chart real-time updates (reqId 999995)
        elif reqId == 999995:
            # Update or append the latest bar for Confirmation chart
            if self.app.confirm_bar_data and self.app.confirm_bar_data[-1]['time'] == bar.date:
                # Update the last bar (same timestamp)
                self.app.confirm_bar_data[-1] = {
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                }
            else:
                # New bar
                self.app.confirm_bar_data.append({
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })
            # Update chart display
            if hasattr(self.app, 'update_chart_display') and self.app.root:
                self.app.root.after(100, lambda: self.app.update_chart_display("confirm"))
        # Handle Trade chart real-time updates (reqId 999994)
        elif reqId == 999994:
            # Update or append the latest bar for Trade chart
            if self.app.trade_bar_data and self.app.trade_bar_data[-1]['time'] == bar.date:
                # Update the last bar (same timestamp)
                self.app.trade_bar_data[-1] = {
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                }
            else:
                # New bar
                self.app.trade_bar_data.append({
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })
            # Update chart display
            if hasattr(self.app, 'update_chart_display') and self.app.root:
                self.app.root.after(100, lambda: self.app.update_chart_display("trade"))


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
        self.data_server_ok = False  # CRITICAL: Must receive 2104/2106 before placing orders
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
        self.managed_accounts = []  # List of managed accounts from TWS
        self.account = ""  # Current account for order placement
        
        # Strategy parameters
        self.atr_period = 14
        self.chandelier_multiplier = 3.0
        self.strategy_enabled = False  # Strategy automation OFF by default
        
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
        self.strike_to_row = {}  # strike -> sheet row index mapping for tksheet
        self.historical_data = {}
        self.historical_data_requests = {}  # reqId -> contract_key
        self.positions = {}
        self.order_status = {}
        self.pending_orders = {}  # orderId -> (contract_key, action, quantity)
        
        # ========================================================================
        # MANUAL TRADING MODE - Order Management System
        # ========================================================================
        # Tracks manual orders with intelligent mid-price chasing until filled
        # - Orders placed at mid-price with proper SPX rounding ($3+ = $0.10, <$3 = $0.05)
        # - Auto-adjusts limit price as market moves to ensure fills
        # - Monitors all open orders and updates UI in real-time
        self.manual_orders = {}  # orderId -> {contract, action, quantity, initial_mid, last_mid, attempts, timestamp}
        self.manual_order_update_interval = 1000  # Check/update orders every 1 second
        self.manual_order_max_price_deviation = 0.25  # Max $0.25 deviation before re-pricing
        
        # SPX underlying price tracking
        self.spx_price = 0.0
        self.spx_req_id = None
        
        # Expiration management
        self.expiry_offset = 0  # 0 = today (0DTE), 1 = next expiry, etc.
        self.current_expiry = self.calculate_expiry_date(self.expiry_offset)
        # Note: GUI doesn't exist yet during __init__, so we can't log to it here
        # Expiration will be logged when GUI is ready
        
        # Option chain
        self.spx_contracts = []  # List of all option contracts
        
        # Trading state
        self.last_trade_hour = -1
        self.active_straddles = []  # List of active straddle positions
        
        # ========================================================================
        # STRADDLE STRATEGY (Auto Straddle Entry)
        # ========================================================================
        self.straddle_enabled = False  # Separate on/off switch for straddle strategy
        self.straddle_frequency_minutes = 60  # How often to enter straddles (default: every 60 minutes)
        self.last_straddle_time = None  # Timestamp of last straddle entry
        
        # Supertrend data for each position
        self.supertrend_data = {}  # contract_key -> supertrend values
        
        # ========================================================================
        # Z-SCORE STRATEGY (Gamma-Snap HFS v3.0)
        # ========================================================================
        self.strategy_enabled = False
        self.vix_price = 0.0
        self.vix_req_id = 999998  # Request ID for VIX data
        self.vix_threshold = 30.0  # Pause strategy if VIX > this
        
        # Z-Score Parameters
        self.z_score_period = 20  # Rolling period for mean/std calculation
        self.z_score_threshold = 1.5  # Entry threshold (crosses above/below ±1.5)
        self.time_stop_minutes = 30  # Max time in trade before forced exit
        self.trade_qty = 1  # Number of contracts per trade
        
        # Strategy Data
        self.spx_1min_bars = deque(maxlen=390)  # Store SPX 1-min bars (full trading day)
        self.spx_1min_req_id = 999997  # Request ID for SPX 1-min historical data
        self.indicators = {'z_score': 0.0, 'ema9': 0.0}  # Current indicator values
        self.active_trade_info = {}  # Current active trade details
        self.trade_history = []  # Completed trades
        
        # Chart data for lightweight-charts
        self.chart_bar_data = []
        self.chart_hist_req_id = 999996
        self.selected_chart_contract = None
        
        # Track active chart subscriptions
        self.confirm_chart_active = False
        self.trade_chart_active = False
        
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
        
        # IBKR TWS Exact Color Scheme
        # Main theme: Pure black and very dark grays to match TWS option chain
        style.configure('.', background='#000000', foreground='#c8c8c8')
        style.configure('TFrame', background='#000000')
        style.configure('TLabel', background='#000000', foreground='#c8c8c8')
        style.configure('TButton', 
                       background='#1a1a1a',
                       foreground='#d0d0d0',
                       bordercolor='#3a3a3a', 
                       focuscolor='#505050')
        style.map('TButton',
                 background=[('active', '#2a2a2a'), ('pressed', '#0a0a0a')])
        
        # Entry and Combobox styling
        style.configure('TEntry', 
                       fieldbackground='#0a0a0a',
                       foreground='#c8c8c8',
                       bordercolor='#3a3a3a')
        style.configure('TCombobox',
                       fieldbackground='#0a0a0a',
                       foreground='#c8c8c8',
                       bordercolor='#3a3a3a',
                       arrowcolor='#808080')
        
        # Treeview: Match IBKR's option chain grid exactly
        # - Very dark background (#000000 to #050505)
        # - Headers: Darker gray with white text
        # - Grid lines: Subtle dark gray
        # - Selection: Subtle blue highlight
        style.configure('Treeview', 
                       background='#000000',           # Pure black base
                       foreground='#c8c8c8',          # Light gray text
                       fieldbackground='#000000',     # Pure black field
                       bordercolor='#1a1a1a',         # Very dark gray borders
                       borderwidth=1,
                       rowheight=25)                   # Comfortable row height
        
        style.configure('Treeview.Heading', 
                       background='#0a0a0a',          # Very dark gray header
                       foreground='#d0d0d0',          # White-ish header text
                       bordercolor='#1a1a1a',         # Dark border
                       relief='flat')
        
        # Selection and focus colors matching IBKR
        style.map('Treeview',
                 background=[('selected', '#1a2a3a')],  # Subtle blue selection
                 foreground=[('selected', '#ffffff')])   # White text when selected
        
        # Create app-wide scrollable container
        # This allows the entire app to be scrollable if window is too small
        main_canvas = tk.Canvas(self.root, bg='#000000', highlightthickness=0)
        main_vsb = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        main_hsb = ttk.Scrollbar(self.root, orient="horizontal", command=main_canvas.xview)
        
        main_container = ttk.Frame(main_canvas)
        
        # Configure canvas scrolling
        main_canvas.configure(yscrollcommand=main_vsb.set, xscrollcommand=main_hsb.set)
        main_canvas_window = main_canvas.create_window((0, 0), window=main_container, anchor="nw")
        
        # Debounced resize handling for smooth, responsive UI during window resizing
        # This prevents sluggishness by batching resize operations
        self.resize_debounce_id = None
        self.last_canvas_width = 0
        
        def configure_scroll_region_immediate():
            """Immediate scroll region update (called after debounce delay)"""
            try:
                main_canvas.configure(scrollregion=main_canvas.bbox("all"))
                canvas_width = main_canvas.winfo_width()
                if canvas_width > 1 and canvas_width != self.last_canvas_width:
                    main_canvas.itemconfig(main_canvas_window, width=canvas_width)
                    self.last_canvas_width = canvas_width
            except:
                pass  # Ignore errors during resize
        
        def configure_scroll_region_debounced(event=None):
            """Debounced scroll region update - prevents resize sluggishness"""
            if not self.root:
                return
            
            # Cancel pending resize operation
            if self.resize_debounce_id:
                self.root.after_cancel(self.resize_debounce_id)
            
            # Schedule new resize operation after 50ms delay
            # This batches multiple rapid resize events into a single update
            self.resize_debounce_id = self.root.after(50, configure_scroll_region_immediate)
        
        # Bind debounced resize handler
        main_container.bind("<Configure>", configure_scroll_region_debounced)
        main_canvas.bind("<Configure>", configure_scroll_region_debounced)
        
        # Pack scrollbars and canvas
        main_vsb.pack(side=RIGHT, fill=Y)
        main_hsb.pack(side=BOTTOM, fill=X)
        main_canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        
        # Enable mousewheel scrolling with optimized event handling
        def on_mousewheel(event):
            # Only scroll if canvas is actually scrollable
            if main_canvas.yview() != (0.0, 1.0):
                main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"  # Prevent event propagation for better performance
        
        main_canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=BOTH, expand=YES, padx=5, pady=(5, 0))
        
        # Tab 1: Trading Dashboard
        self.create_trading_tab()
        
        # Tab 2: Settings
        self.create_settings_tab()
        
        # Tab 3: SPX Chart - NOW EMBEDDED IN TRADING TAB (chart moved to main trading tab)
        # self.create_chart_tab()  # Disabled - chart now appears below option charts in Trading tab
        
        # Status bar at bottom (inside main_container so it's part of scrollable area)
        self.create_status_bar(main_container)
        
        # Start GUI update loop
        self.root.after(100, self.process_gui_queue)
        
        # Start time checker for hourly trades
        self.root.after(1000, self.check_trade_time)
        
        # Start Z-Score strategy loop (runs every 5 seconds)
        self.root.after(5000, self.run_gamma_snap_strategy)
        
        # Auto-connect to IBKR on startup (after GUI is ready)
        if self.auto_connect:
            self.log_message("Auto-connect enabled - connecting to IBKR in 2 seconds...", "INFO")
            self.root.after(2000, self.connect_to_ib)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_trading_tab(self):
        """
        Create the main trading dashboard tab with IBKR TWS-styled option chain.
        
        Color Scheme Implementation (Exact Match to IBKR TWS):
        ======================================================
        
        BACKGROUND COLORS:
        - Base background: Pure black (#000000)
        - ITM Calls: Very subtle dark green gradient (#001a00 shallow, #002a00 deep)
        - ITM Puts: Very subtle dark red gradient (#1a0000 shallow, #2a0000 deep)
        - ATM options: Very dark gray (#0a0a0a)
        - OTM options: Pure black (#000000)
        
        TEXT COLORS:
        - Positive values: Bright green (#00ff00) - gains, positive deltas
        - Negative values: Bright red (#ff0000) - losses, negative thetas
        - Neutral/ITM text: Light gray (#b0b0b0)
        - OTM text: Medium gray (#808080) - dimmer for less relevance
        - Headers: Off-white (#d0d0d0 to #e0e0e0)
        
        DESIGN PRINCIPLES:
        - Darker = Less relevant (OTM options fade to black)
        - Color saturation increases with moneyness depth
        - Strike column uses bold font and centered alignment
        - Grid lines are very subtle (#1a1a1a) to maintain focus on data
        - Selection highlight is subtle blue (#1a2a3a) to avoid distraction
        
        This implementation matches IBKR TWS Professional workstation styling
        for maximum familiarity and professional appearance.
        """
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
            width=25, 
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
        
        # Option Chain tksheet - IBKR TWS Professional Style
        chain_frame = ttk.Frame(tab)
        chain_frame.pack(fill=BOTH, expand=False, padx=5, pady=5)
        
        # IBKR TWS Color Scheme from Screenshot Analysis
        # Based on actual IB TWS interface with blue transparency for ITM options
        TWS_COLORS = {
            'bg': '#000000',              # Pure black background
            'fg': '#ffffff',              # White text (brighter than before)
            'header_bg': '#1a3a5a',       # Blue-gray header (like IB)
            'header_fg': '#ffffff',       # White header text
            'grid_line': '#2a2a2a',       # Subtle grid lines
            'selected': '#3a5a7a',        # Blue selection highlight
            
            # ITM backgrounds - Blue transparency like IB TWS
            'call_itm_deep': '#1a2a4a',   # Deep blue for deep ITM calls
            'call_itm': '#0f1a2a',        # Lighter blue for ITM calls
            'put_itm_deep': '#1a2a4a',    # Deep blue for deep ITM puts (same as calls in IB)
            'put_itm': '#0f1a2a',         # Lighter blue for ITM puts
            
            'otm_fg': '#808080',          # OTM dimmed text
            'strike_bg': '#2a4a6a',       # Blue background for strike column (like IB)
            'strike_fg': '#ffffff',       # White text for strike
            
            # Value colors
            'positive': '#00ff00',        # Bright green for positive values
            'negative': '#ff0000',        # Bright red for negative values
            'neutral': '#c0c0c0',         # Light gray for neutral
            
            # CHANGE % backgrounds (like IB TWS)
            'positive_bg': '#003300',     # Dark green background for positive change
            'negative_bg': '#330000',     # Dark red background for negative change
            
            # Special column backgrounds (like IB's colored columns)
            'delta_bg': '#1a1a2a',        # Slight blue tint for delta columns
            'volume_bg': '#1a1a1a'        # Slight gray for volume
        }
        
        # Column headers matching IBKR layout with CHANGE % column
        # CALLS: Imp Vol, Delta, Theta, Vega, Gamma, Volume, CHANGE %, Last, Ask, Bid (reversed - bid/ask closest to strike)
        # STRIKE (center)
        # PUTS: Bid, Ask, Last, CHANGE %, Volume, Gamma, Vega, Theta, Delta, Imp Vol (reversed - bid/ask closest to strike)
        headers = [
            # Call side (left) - 10 columns (REVERSED)
            "Imp Vol", "Delta", "Theta", "Vega", "Gamma", "Volume", "CHANGE %", "Last", "Ask", "Bid",
            # Strike (center) - 1 column
            "● STRIKE ●",
            # Put side (right) - 10 columns (REVERSED)
            "Bid", "Ask", "Last", "CHANGE %", "Volume", "Gamma", "Vega", "Theta", "Delta", "Imp Vol"
        ]
        
        # Create tksheet with professional configuration
        self.option_sheet = Sheet(
            chain_frame,
            headers=headers,
            height=330,  # ~12 rows visible (similar to old tree height)
            width=1400,  # Wide enough for all columns
            theme="dark",
            # Disable editing (read-only display)
            edit_cell_validation=False,
            # Enable selections for click detection
            enable_bindings=("single_select", "row_select"),
            show_row_index=False  # Hide row index column
        )
        
        # Configure TWS color scheme
        self.option_sheet.set_options(
            font=("Arial", 9, "normal"),
            header_font=("Arial", 9, "bold"),
            table_bg=TWS_COLORS['bg'],
            table_fg=TWS_COLORS['fg'],
            table_grid_fg=TWS_COLORS['grid_line'],
            table_selected_cells_bg=TWS_COLORS['selected'],
            table_selected_cells_fg="#ffffff",
            header_bg=TWS_COLORS['header_bg'],
            header_fg=TWS_COLORS['header_fg'],
            header_grid_fg=TWS_COLORS['grid_line']
        )
        
        # Set column widths and alignment
        col_width = 70
        strike_width = 100
        
        for i, header in enumerate(headers):
            if header == "● STRIKE ●":
                self.option_sheet.column_width(column=i, width=strike_width)
                # Strike column - center aligned
                self.option_sheet.align_columns(columns=i, align="center")
            else:
                self.option_sheet.column_width(column=i, width=col_width)
                # All other columns - center aligned
                self.option_sheet.align_columns(columns=i, align="center")
        
        # Pack sheet
        self.option_sheet.pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Bind click event for option selection
        self.option_sheet.bind("<ButtonRelease-1>", self.on_option_sheet_click)
        
        # Store TWS colors for later use in cell formatting
        self.tws_colors = TWS_COLORS
        
        # Store column indices for easy reference (updated with CHANGE % and Imp Vol symmetry)
        self.sheet_cols = {
            'c_bid': 0, 'c_ask': 1, 'c_last': 2, 'c_change': 3, 'c_vol': 4,
            'c_gamma': 5, 'c_vega': 6, 'c_theta': 7, 'c_delta': 8, 'c_iv': 9,
            'strike': 10,
            'p_iv': 11, 'p_delta': 12, 'p_theta': 13, 'p_vega': 14, 'p_gamma': 15,
            'p_vol': 16, 'p_change': 17, 'p_last': 18, 'p_ask': 19, 'p_bid': 20
        }
        
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
        
        # Create tksheet for positions (Excel-like grid)
        pos_frame = ttk.Frame(pos_container, height=180)
        pos_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        self.position_sheet = Sheet(
            pos_frame,
            headers=["Contract", "Qty", "Entry", "Mid", "PnL", "PnL%", "EntryTime", "TimeSpan", "Action"],
            height=180,
            theme="dark",
            show_row_index=False,
            show_top_left=False,
            empty_horizontal=0,
            empty_vertical=0,
            header_font=("Arial", 10, "bold"),
            font=("Arial", 10, "normal"),
            header_bg="#1a1a1a",
            header_fg="#ffffff",
            table_bg="#000000",
            table_fg="#ffffff",
            table_selected_cells_bg="#1a2a3a",
            table_selected_cells_fg="#ffffff",
            frame_bg="#000000",
            table_grid_fg="#1a1a1a",
            header_border_fg="#1a1a1a",
        )
        self.position_sheet.enable_bindings()
        self.position_sheet.pack(fill=BOTH, expand=YES)
        
        # Set column widths using column_width method
        # Contract, Qty, Entry, Mid, PnL, PnL%, EntryTime, TimeSpan, Action
        for col_idx, width in enumerate([210, 50, 80, 80, 100, 80, 100, 90, 70]):
            self.position_sheet.column_width(column=col_idx, width=width)
        
        # Set column alignments: left for Contract (0), center for all others
        self.position_sheet.align_columns(columns=[1, 2, 3, 4, 5, 6, 7, 8], align="center")
        self.position_sheet.align_columns(columns=[0], align="left")
        
        # Bind click event for Close button
        self.position_sheet.bind("<ButtonRelease-1>", self.on_position_sheet_click)
        
        # Orders section (right side)
        order_container = ttk.Frame(pos_order_frame)
        order_container.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        order_label = ttk.Label(order_container, text="Active Orders", 
                               font=("Arial", 12, "bold"))
        order_label.pack(fill=X, padx=5, pady=(5, 0))
        
        order_frame = ttk.Frame(order_container)
        order_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # tksheet for orders (dark theme, Excel-like)
        self.order_sheet = Sheet(
            order_frame,
            theme="dark",
            headers=["Order ID", "Contract", "Action", "Qty", "Price", "Status", "Cancel"],
            height=180,
            column_width=100,
            show_top_left=False,
            show_row_index=False,
            header_bg="#1a1a1a",
            header_fg="#ffffff",
            header_font=("Arial", 10, "bold"),
            table_bg="#000000",
            table_fg="#ffffff",
            table_font=("Arial", 10, "normal"),
            table_selected_cells_bg="#333333",
            table_selected_cells_fg="#ffffff"
        )
        self.order_sheet.enable_bindings("all")
        self.order_sheet.pack(fill=BOTH, expand=YES)
        
        # Set column widths
        self.order_sheet.column_width(column=0, width=80)   # Order ID
        self.order_sheet.column_width(column=1, width=210)  # Contract (+50px)
        self.order_sheet.column_width(column=2, width=60)   # Action
        self.order_sheet.column_width(column=3, width=50)   # Qty
        self.order_sheet.column_width(column=4, width=80)   # Price
        self.order_sheet.column_width(column=5, width=100)  # Status
        self.order_sheet.column_width(column=6, width=80)   # Cancel
        
        # Set column alignments: left for Contract (1), center for all others
        self.order_sheet.align_columns(columns=[0, 2, 3, 4, 5, 6], align="center")
        self.order_sheet.align_columns(columns=[1], align="left")
        
        # Bind click event for Cancel button
        self.order_sheet.bind("<ButtonRelease-1>", self.on_order_sheet_click)
        
        # Row 2: Charts side-by-side (Calls on left, Puts on right)
        charts_frame = ttk.Frame(bottom_frame)
        charts_frame.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        
        # Call chart (left side)
        call_chart_container = ttk.Frame(charts_frame)
        call_chart_container.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 2))
        
        call_chart_frame = ttk.Frame(call_chart_container)
        call_chart_frame.pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Create figure and canvas FIRST
        self.call_fig = Figure(figsize=(5, 4), dpi=80, facecolor='#181818')
        # Extended chart area - more space at bottom now
        self.call_fig.subplots_adjust(left=0.026, right=0.95, top=0.98, bottom=0.05)
        self.call_ax = self.call_fig.add_subplot(111, facecolor='#202020')
        self.call_ax.tick_params(colors='#E0E0E0', labelsize=8)
        self.call_ax.spines['bottom'].set_color('#FF8C00')
        self.call_ax.spines['top'].set_color('#FF8C00')
        self.call_ax.spines['left'].set_color('#FF8C00')
        self.call_ax.spines['right'].set_color('#FF8C00')
        
        self.call_canvas = FigureCanvasTkAgg(self.call_fig, master=call_chart_frame)
        self.call_canvas.get_tk_widget().pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Custom toolbar frame with chart title and controls AT TOP
        call_toolbar_frame = ttk.Frame(call_chart_frame, style='Dark.TFrame')
        call_toolbar_frame.pack(side=tk.TOP, fill=tk.X, before=self.call_canvas.get_tk_widget())
        
        # Add navigation toolbar for zoom/pan
        call_toolbar = NavigationToolbar2Tk(self.call_canvas, call_toolbar_frame)
        call_toolbar.pack(side=tk.LEFT, fill=tk.X)
        
        # Chart title and settings in center/right of toolbar
        call_controls_frame = ttk.Frame(call_toolbar_frame)
        call_controls_frame.pack(side=tk.RIGHT, padx=5)
        
        ttk.Label(call_controls_frame, text="Call Chart", 
                 font=("Arial", 10, "bold")).pack(side=LEFT, padx=5)
        
        # Interval dropdown
        ttk.Label(call_controls_frame, text="Interval:").pack(side=LEFT, padx=(10, 2))
        self.call_timeframe_var = tk.StringVar(value="1 min")
        call_timeframe = ttk.Combobox(call_controls_frame, textvariable=self.call_timeframe_var,
                                      values=["1 min", "5 min", "15 min", "30 min", "1 hour"],
                                      width=8, state="readonly")
        call_timeframe.pack(side=LEFT, padx=2)
        call_timeframe.bind('<<ComboboxSelected>>', lambda e: self.on_call_settings_changed())
        
        # Days back selector
        ttk.Label(call_controls_frame, text="Days:").pack(side=LEFT, padx=(10, 2))
        self.call_days_var = tk.StringVar(value="1")
        call_days = ttk.Combobox(call_controls_frame, textvariable=self.call_days_var,
                                 values=["1", "2", "5", "10", "20"],
                                 width=5, state="readonly")
        call_days.pack(side=LEFT, padx=2)
        call_days.bind('<<ComboboxSelected>>', lambda e: self.on_call_settings_changed())
        
        # Add label for contract description (centered)
        self.call_contract_label = ttk.Label(call_toolbar_frame, text="", 
                                             font=("Arial", 9), foreground="#00BFFF")
        self.call_contract_label.pack(side=tk.LEFT, expand=True)
        
        # Add loading spinner overlay for call chart (initially hidden)
        self.call_loading_frame = tk.Frame(call_chart_frame, bg='#181818')
        self.call_loading_label = ttk.Label(self.call_loading_frame, 
                                            text="⟳ Loading chart data...",
                                            font=("Arial", 12),
                                            foreground="#FF8C00",
                                            background="#181818")
        self.call_loading_label.pack(expand=True)
        self.call_loading_timeout_id = None  # For timeout tracking
        
        # Put chart (right side)
        put_chart_container = ttk.Frame(charts_frame)
        put_chart_container.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        put_chart_frame = ttk.Frame(put_chart_container)
        put_chart_frame.pack(fill=BOTH, expand=YES, padx=2, pady=2)
        
        # Create figure and canvas FIRST
        self.put_fig = Figure(figsize=(5, 4), dpi=80, facecolor='#181818')
        # Extended chart area - more space at bottom now
        self.put_fig.subplots_adjust(left=0.026, right=0.95, top=0.98, bottom=0.05)
        self.put_ax = self.put_fig.add_subplot(111, facecolor='#202020')
        self.put_ax.tick_params(colors='#E0E0E0', labelsize=8)
        self.put_ax.spines['bottom'].set_color('#FF8C00')
        self.put_ax.spines['top'].set_color('#FF8C00')
        self.put_ax.spines['left'].set_color('#FF8C00')
        self.put_ax.spines['right'].set_color('#FF8C00')
        
        self.put_canvas = FigureCanvasTkAgg(self.put_fig, master=put_chart_frame)
        self.put_canvas.get_tk_widget().pack(fill=BOTH, expand=YES, padx=0, pady=0)
        
        # Custom toolbar frame with chart title and controls AT TOP
        put_toolbar_frame = ttk.Frame(put_chart_frame, style='Dark.TFrame')
        put_toolbar_frame.pack(side=tk.TOP, fill=tk.X, before=self.put_canvas.get_tk_widget())
        
        # Add navigation toolbar for zoom/pan
        put_toolbar = NavigationToolbar2Tk(self.put_canvas, put_toolbar_frame)
        put_toolbar.pack(side=tk.LEFT, fill=tk.X)
        
        # Chart title and settings in center/right of toolbar
        put_controls_frame = ttk.Frame(put_toolbar_frame)
        put_controls_frame.pack(side=tk.RIGHT, padx=5)
        
        ttk.Label(put_controls_frame, text="Put Chart", 
                 font=("Arial", 10, "bold")).pack(side=LEFT, padx=5)
        
        # Interval dropdown
        ttk.Label(put_controls_frame, text="Interval:").pack(side=LEFT, padx=(10, 2))
        self.put_timeframe_var = tk.StringVar(value="1 min")
        put_timeframe = ttk.Combobox(put_controls_frame, textvariable=self.put_timeframe_var,
                                     values=["1 min", "5 min", "15 min", "30 min", "1 hour"],
                                     width=8, state="readonly")
        put_timeframe.pack(side=LEFT, padx=2)
        put_timeframe.bind('<<ComboboxSelected>>', lambda e: self.on_put_settings_changed())
        
        # Days back selector
        ttk.Label(put_controls_frame, text="Days:").pack(side=LEFT, padx=(10, 2))
        self.put_days_var = tk.StringVar(value="5")
        put_days = ttk.Combobox(put_controls_frame, textvariable=self.put_days_var,
                                values=["1", "2", "5", "10", "20"],
                                width=5, state="readonly")
        put_days.pack(side=LEFT, padx=2)
        put_days.bind('<<ComboboxSelected>>', lambda e: self.on_put_settings_changed())
        
        # Add label for contract description (centered)
        self.put_contract_label = ttk.Label(put_toolbar_frame, text="", 
                                            font=("Arial", 9), foreground="#00BFFF")
        self.put_contract_label.pack(side=tk.LEFT, expand=True)
        
        # Add loading spinner overlay for put chart (initially hidden)
        self.put_loading_frame = tk.Frame(put_chart_frame, bg='#181818')
        self.put_loading_label = ttk.Label(self.put_loading_frame, 
                                           text="⟳ Loading chart data...",
                                           font=("Arial", 12),
                                           foreground="#FF8C00",
                                           background="#181818")
        self.put_loading_label.pack(expand=True)
        self.put_loading_timeout_id = None  # For timeout tracking
        
        # ========================================================================
        # SPX UNDERLYING CHARTS - Two Charts Side-by-Side
        # ========================================================================
        # Confirmation Chart (Left - 1 min) | Trade Chart (Right - 15 secs)
        # ========================================================================
        
        spx_charts_container = ttk.Frame(bottom_frame)
        spx_charts_container.pack(fill=BOTH, expand=False, padx=5, pady=(5, 5))
        
        # ====================
        # CONFIRMATION CHART (Left - Longer timeframe)
        # ====================
        confirm_chart_container = ttk.Frame(spx_charts_container)
        confirm_chart_container.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 2))
        
        confirm_chart_frame = ttk.Frame(confirm_chart_container, height=300)
        confirm_chart_frame.pack(fill=BOTH, expand=False, padx=0, pady=0)
        confirm_chart_frame.pack_propagate(False)
        
        # Create figure with 2 subplots for confirmation chart FIRST
        self.confirm_fig = Figure(figsize=(9, 4.5), dpi=80, facecolor='#000000')
        gs_confirm = self.confirm_fig.add_gridspec(2, 1, height_ratios=[7, 3], hspace=0.05)
        self.confirm_ax = self.confirm_fig.add_subplot(gs_confirm[0])
        self.confirm_zscore_ax = self.confirm_fig.add_subplot(gs_confirm[1], sharex=self.confirm_ax)
        
        # Style confirmation price chart
        self.confirm_ax.set_facecolor('#000000')
        self.confirm_ax.tick_params(colors='#808080', which='both', labelsize=8, labelbottom=False)
        for spine in ['bottom', 'top', 'left', 'right']:
            self.confirm_ax.spines[spine].set_color('#00BFFF')
        self.confirm_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        self.confirm_ax.set_ylabel('SPX', color='#808080', fontsize=9)
        
        # Style confirmation Z-Score
        self.confirm_zscore_ax.set_facecolor('#000000')
        self.confirm_zscore_ax.tick_params(colors='#808080', which='both', labelsize=8)
        for spine in ['bottom', 'top', 'left', 'right']:
            self.confirm_zscore_ax.spines[spine].set_color('#00BFFF')
        self.confirm_zscore_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        self.confirm_zscore_ax.set_ylabel('Z-Score', color='#808080', fontsize=8)
        self.confirm_zscore_ax.axhline(y=0, color='#808080', linestyle='--', linewidth=1, alpha=0.5)
        self.confirm_zscore_ax.axhline(y=1.5, color='#44ff44', linestyle='--', linewidth=1, alpha=0.7)
        self.confirm_zscore_ax.axhline(y=-1.5, color='#ff4444', linestyle='--', linewidth=1, alpha=0.7)
        self.confirm_zscore_ax.set_ylim(-3, 3)
        
        # Extended chart area - more space at bottom now
        self.confirm_fig.subplots_adjust(left=0.026, right=0.95, top=0.98, bottom=0.05, hspace=0.2)
        
        self.confirm_canvas = FigureCanvasTkAgg(self.confirm_fig, master=confirm_chart_frame)
        self.confirm_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
        
        # Custom toolbar frame with chart title and controls AT TOP
        confirm_toolbar_frame = ttk.Frame(confirm_chart_frame, style='Dark.TFrame')
        confirm_toolbar_frame.pack(side=tk.TOP, fill=tk.X, before=self.confirm_canvas.get_tk_widget())
        
        confirm_toolbar = NavigationToolbar2Tk(self.confirm_canvas, confirm_toolbar_frame)
        confirm_toolbar.update()
        confirm_toolbar.pack(side=tk.LEFT, fill=tk.X)
        
        # Chart title and settings in center/right of toolbar
        confirm_controls_frame = ttk.Frame(confirm_toolbar_frame)
        confirm_controls_frame.pack(side=tk.RIGHT, padx=5)
        
        ttk.Label(confirm_controls_frame, text="Confirmation Chart", 
                 font=("Arial", 10, "bold"), foreground="#00BFFF").pack(side=LEFT, padx=5)
        
        # Timeframe selector
        ttk.Label(confirm_controls_frame, text="Interval:").pack(side=tk.LEFT, padx=(10, 2))
        self.confirm_timeframe_var = tk.StringVar(value="1 min")
        confirm_timeframe = ttk.Combobox(confirm_controls_frame, textvariable=self.confirm_timeframe_var,
                                        values=["30 secs", "1 min", "2 mins", "3 mins", "5 mins"],
                                        width=8, state="readonly")
        confirm_timeframe.pack(side=LEFT, padx=2)
        
        # Period selector
        ttk.Label(confirm_controls_frame, text="Period:").pack(side=tk.LEFT, padx=(10, 2))
        self.confirm_period_var = tk.StringVar(value="1 D")
        confirm_period = ttk.Combobox(confirm_controls_frame, textvariable=self.confirm_period_var,
                                     values=["1 D", "2 D", "5 D"],
                                     width=5, state="readonly")
        confirm_period.pack(side=LEFT, padx=2)
        
        # ====================
        # TRADE CHART (Right - Shorter timeframe for trading)
        # ====================
        trade_chart_container = ttk.Frame(spx_charts_container)
        trade_chart_container.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        trade_chart_frame = ttk.Frame(trade_chart_container, height=300)
        trade_chart_frame.pack(fill=BOTH, expand=False, padx=0, pady=0)
        trade_chart_frame.pack_propagate(False)
        
        # Create figure with 2 subplots for trade chart FIRST
        self.trade_fig = Figure(figsize=(9, 4.5), dpi=80, facecolor='#000000')
        gs_trade = self.trade_fig.add_gridspec(2, 1, height_ratios=[7, 3], hspace=0.05)
        self.trade_ax = self.trade_fig.add_subplot(gs_trade[0])
        self.trade_zscore_ax = self.trade_fig.add_subplot(gs_trade[1], sharex=self.trade_ax)
        
        # Style trade price chart
        self.trade_ax.set_facecolor('#000000')
        self.trade_ax.tick_params(colors='#808080', which='both', labelsize=8, labelbottom=False)
        for spine in ['bottom', 'top', 'left', 'right']:
            self.trade_ax.spines[spine].set_color('#00FF00')
        self.trade_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        self.trade_ax.set_ylabel('SPX', color='#808080', fontsize=9)
        
        # Style trade Z-Score
        self.trade_zscore_ax.set_facecolor('#000000')
        self.trade_zscore_ax.tick_params(colors='#808080', which='both', labelsize=8)
        for spine in ['bottom', 'top', 'left', 'right']:
            self.trade_zscore_ax.spines[spine].set_color('#00FF00')
        self.trade_zscore_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        self.trade_zscore_ax.set_ylabel('Z-Score', color='#808080', fontsize=8)
        self.trade_zscore_ax.axhline(y=0, color='#808080', linestyle='--', linewidth=1, alpha=0.5)
        self.trade_zscore_ax.axhline(y=1.5, color='#44ff44', linestyle='--', linewidth=1, alpha=0.7)
        self.trade_zscore_ax.axhline(y=-1.5, color='#ff4444', linestyle='--', linewidth=1, alpha=0.7)
        self.trade_zscore_ax.set_ylim(-3, 3)
        
        # Extended chart area - more space at bottom now
        self.trade_fig.subplots_adjust(left=0.026, right=0.95, top=0.98, bottom=0.05, hspace=0.2)
        
        self.trade_canvas = FigureCanvasTkAgg(self.trade_fig, master=trade_chart_frame)
        self.trade_canvas.get_tk_widget().pack(fill=BOTH, expand=YES)
        
        # Custom toolbar frame with chart title and controls AT TOP
        trade_toolbar_frame = ttk.Frame(trade_chart_frame, style='Dark.TFrame')
        trade_toolbar_frame.pack(side=tk.TOP, fill=tk.X, before=self.trade_canvas.get_tk_widget())
        
        trade_toolbar = NavigationToolbar2Tk(self.trade_canvas, trade_toolbar_frame)
        trade_toolbar.pack(side=tk.LEFT, fill=tk.X)
        
        # Chart title and settings in center/right of toolbar
        trade_controls_frame = ttk.Frame(trade_toolbar_frame)
        trade_controls_frame.pack(side=tk.RIGHT, padx=5)
        
        ttk.Label(trade_controls_frame, text="Trade Chart (Executes Here)", 
                 font=("Arial", 10, "bold"), foreground="#00FF00").pack(side=LEFT, padx=5)
        
        # Timeframe selector  
        ttk.Label(trade_controls_frame, text="Interval:").pack(side=LEFT, padx=(10, 2))
        self.trade_timeframe_var = tk.StringVar(value="15 secs")
        trade_timeframe = ttk.Combobox(trade_controls_frame, textvariable=self.trade_timeframe_var,
                                      values=["1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min"],
                                      width=8, state="readonly")
        trade_timeframe.pack(side=LEFT, padx=2)
        
        # Period selector
        ttk.Label(trade_controls_frame, text="Period:").pack(side=LEFT, padx=(10, 2))
        self.trade_period_var = tk.StringVar(value="1 D")
        trade_period = ttk.Combobox(trade_controls_frame, textvariable=self.trade_period_var,
                                   values=["1 D", "2 D", "5 D"],
                                   width=5, state="readonly")
        trade_period.pack(side=LEFT, padx=2)
        
        # Initialize chart data containers
        self.confirm_bar_data = []
        self.trade_bar_data = []
        self.chart_trade_markers = []
        
        self.log_message("SPX dual-chart system created - Confirmation + Trade charts", "INFO")
        
        # ========================================================================
        # BOTTOM PANELS - 5-Column Horizontal Layout
        # ========================================================================
        # Five-panel layout across the bottom:
        # Column 1: Activity Log (expandable)
        # Column 2: Strategy Parameters
        # Column 3: Gamma-Snap Strategy
        # Column 4: [Reserved - Blank for future use]
        # Column 5: Manual Mode (Quick Entry controls)
        # ========================================================================
        
        bottom_panels_frame = ttk.Frame(bottom_frame)
        bottom_panels_frame.pack(fill=BOTH, expand=True, padx=5, pady=(10, 5))
        
        # ========================================================================
        # COLUMN 1: Activity Log
        # ========================================================================
        activity_log_container = ttk.Frame(bottom_panels_frame)
        activity_log_container.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 3))
        
        log_label = ttk.Label(activity_log_container, text="Activity Log", 
                             font=("Arial", 11, "bold"))
        log_label.pack(fill=X, pady=(0, 3))
        
        log_frame = ttk.Frame(activity_log_container)
        log_frame.pack(fill=BOTH, expand=True)
        
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical")
        log_vsb.pack(side=RIGHT, fill=Y)
        
        self.log_text = tk.Text(log_frame, height=12, bg='#202020',
                               fg='#E0E0E0', font=("Consolas", 8),
                               yscrollcommand=log_vsb.set, wrap=tk.WORD)
        log_vsb.config(command=self.log_text.yview)
        self.log_text.pack(fill=BOTH, expand=YES)
        
        # Configure tags for different log levels
        self.log_text.tag_config("ERROR", foreground="#FF4444")
        self.log_text.tag_config("WARNING", foreground="#FFA500")
        self.log_text.tag_config("SUCCESS", foreground="#44FF44")
        self.log_text.tag_config("INFO", foreground="#E0E0E0")
        
        # ========================================================================
        # COLUMN 2: Chain Settings
        # ========================================================================
        strategy_params_container = ttk.Frame(bottom_panels_frame, width=180)
        strategy_params_container.pack(side=LEFT, fill=BOTH, expand=False, padx=3)
        strategy_params_container.pack_propagate(False)  # Maintain fixed width
        
        ttk.Label(strategy_params_container, text="Chain Settings", 
                 font=("Arial", 11, "bold")).pack(fill=X, pady=(0, 3))
        
        strategy_section = ttk.LabelFrame(strategy_params_container, text="Parameters", padding=5)
        strategy_section.pack(fill=BOTH, expand=True)
        
        # Strikes Above
        ttk.Label(strategy_section, text="Strikes +:", 
                  font=("Arial", 8)).grid(row=0, column=0, sticky=W, pady=1, padx=2)
        self.strikes_above_entry = ttk.Entry(strategy_section, width=8, font=("Arial", 8))
        self.strikes_above_entry.insert(0, str(self.strikes_above))
        self.strikes_above_entry.grid(row=0, column=1, sticky=EW, padx=2, pady=1)
        self.strikes_above_entry.bind('<FocusOut>', self.auto_save_settings)
        self.strikes_above_entry.bind('<Return>', self.auto_save_settings)
        strategy_section.columnconfigure(1, weight=1)
        
        # Strikes Below
        ttk.Label(strategy_section, text="Strikes -:", 
                  font=("Arial", 8)).grid(row=1, column=0, sticky=W, pady=1, padx=2)
        self.strikes_below_entry = ttk.Entry(strategy_section, width=8, font=("Arial", 8))
        self.strikes_below_entry.insert(0, str(self.strikes_below))
        self.strikes_below_entry.grid(row=1, column=1, sticky=EW, padx=2, pady=1)
        self.strikes_below_entry.bind('<FocusOut>', self.auto_save_settings)
        self.strikes_below_entry.bind('<Return>', self.auto_save_settings)
        
        # Chain Refresh
        ttk.Label(strategy_section, text="Refresh (s):", 
                  font=("Arial", 8)).grid(row=2, column=0, sticky=W, pady=1, padx=2)
        self.chain_refresh_entry = ttk.Entry(strategy_section, width=8, font=("Arial", 8))
        self.chain_refresh_entry.insert(0, str(self.chain_refresh_interval))
        self.chain_refresh_entry.grid(row=2, column=1, sticky=EW, padx=2, pady=1)
        self.chain_refresh_entry.bind('<FocusOut>', self.auto_save_settings)
        self.chain_refresh_entry.bind('<Return>', self.auto_save_settings)
        
        # ========================================================================
        # COLUMN 3: Gamma-Snap Strategy (WIDER for Dual Settings)
        # ========================================================================
        gamma_strategy_container = ttk.Frame(bottom_panels_frame, width=400)
        gamma_strategy_container.pack(side=LEFT, fill=BOTH, expand=False, padx=3)
        gamma_strategy_container.pack_propagate(False)  # Maintain fixed width
        
        ttk.Label(gamma_strategy_container, text="Strategy Settings", 
                 font=("Arial", 11, "bold")).pack(fill=X, pady=(0, 3))
        
        # Create two-column layout for Confirmation vs Trade Chart settings
        settings_columns = ttk.Frame(gamma_strategy_container)
        settings_columns.pack(fill=BOTH, expand=True)
        
        # LEFT COLUMN: Confirmation Chart Settings
        confirm_settings = ttk.LabelFrame(settings_columns, text="Confirmation Settings", padding=5)
        confirm_settings.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 2))
        
        ttk.Label(confirm_settings, text="EMA Len:", 
                  font=("Arial", 8)).grid(row=0, column=0, sticky=W, pady=1, padx=2)
        self.confirm_ema_entry = ttk.Entry(confirm_settings, width=6, font=("Arial", 8))
        self.confirm_ema_entry.insert(0, "9")
        self.confirm_ema_entry.grid(row=0, column=1, sticky=EW, padx=2, pady=1)
        self.confirm_ema_entry.bind('<FocusOut>', self.auto_save_settings)
        self.confirm_ema_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(confirm_settings, text="Z Period:", 
                  font=("Arial", 8)).grid(row=1, column=0, sticky=W, pady=1, padx=2)
        self.confirm_z_period_entry = ttk.Entry(confirm_settings, width=6, font=("Arial", 8))
        self.confirm_z_period_entry.insert(0, "30")
        self.confirm_z_period_entry.grid(row=1, column=1, sticky=EW, padx=2, pady=1)
        self.confirm_z_period_entry.bind('<FocusOut>', self.auto_save_settings)
        self.confirm_z_period_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(confirm_settings, text="Z ±:", 
                  font=("Arial", 8)).grid(row=2, column=0, sticky=W, pady=1, padx=2)
        self.confirm_z_threshold_entry = ttk.Entry(confirm_settings, width=6, font=("Arial", 8))
        self.confirm_z_threshold_entry.insert(0, "1.5")
        self.confirm_z_threshold_entry.grid(row=2, column=1, sticky=EW, padx=2, pady=1)
        self.confirm_z_threshold_entry.bind('<FocusOut>', self.auto_save_settings)
        self.confirm_z_threshold_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Button(confirm_settings, text="Refresh", 
                  command=self.refresh_confirm_chart,
                  style="info.TButton", width=10).grid(row=3, column=0, columnspan=2, pady=5)
        
        confirm_settings.columnconfigure(1, weight=1)
        
        # RIGHT COLUMN: Trade Chart Settings
        trade_settings = ttk.LabelFrame(settings_columns, text="Trade Chart Settings", padding=5)
        trade_settings.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(2, 0))
        
        ttk.Label(trade_settings, text="EMA Len:", 
                  font=("Arial", 8)).grid(row=0, column=0, sticky=W, pady=1, padx=2)
        self.trade_ema_entry = ttk.Entry(trade_settings, width=6, font=("Arial", 8))
        self.trade_ema_entry.insert(0, "9")
        self.trade_ema_entry.grid(row=0, column=1, sticky=EW, padx=2, pady=1)
        self.trade_ema_entry.bind('<FocusOut>', self.auto_save_settings)
        self.trade_ema_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(trade_settings, text="Z Period:", 
                  font=("Arial", 8)).grid(row=1, column=0, sticky=W, pady=1, padx=2)
        self.trade_z_period_entry = ttk.Entry(trade_settings, width=6, font=("Arial", 8))
        self.trade_z_period_entry.insert(0, "30")
        self.trade_z_period_entry.grid(row=1, column=1, sticky=EW, padx=2, pady=1)
        self.trade_z_period_entry.bind('<FocusOut>', self.auto_save_settings)
        self.trade_z_period_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(trade_settings, text="Z ±:", 
                  font=("Arial", 8)).grid(row=2, column=0, sticky=W, pady=1, padx=2)
        self.trade_z_threshold_entry = ttk.Entry(trade_settings, width=6, font=("Arial", 8))
        self.trade_z_threshold_entry.insert(0, "1.5")
        self.trade_z_threshold_entry.grid(row=2, column=1, sticky=EW, padx=2, pady=1)
        self.trade_z_threshold_entry.bind('<FocusOut>', self.auto_save_settings)
        self.trade_z_threshold_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Button(trade_settings, text="Refresh", 
                  command=self.refresh_trade_chart,
                  style="info.TButton", width=10).grid(row=3, column=0, columnspan=2, pady=5)
        
        trade_settings.columnconfigure(1, weight=1)
        
        # ========================================================================
        # COLUMN 4: Master Settings (WIDER - 2 columns of settings)
        # ========================================================================
        master_container = ttk.Frame(bottom_panels_frame, width=300)  # Wider to fit 2 columns
        master_container.pack(side=LEFT, fill=BOTH, expand=False, padx=3)
        master_container.pack_propagate(False)  # Maintain fixed width
        
        ttk.Label(master_container, text="Master Settings", 
                 font=("Arial", 11, "bold")).pack(fill=X, pady=(0, 3))
        
        master_section = ttk.LabelFrame(master_container, text="Strategy Control", padding=5)
        master_section.pack(fill=BOTH, expand=True)
        
        # Use grid for everything in master_section - 4 columns layout
        # COLUMN 1 & 2: Left side | COLUMN 3 & 4: Right side
        
        # Row 0: Strategy Status (ON/OFF buttons at top) - spans all columns
        ttk.Label(master_section, text="Auto:", 
                  font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=W, padx=2, pady=2)
        
        button_frame = ttk.Frame(master_section)
        button_frame.grid(row=0, column=1, columnspan=3, sticky=EW, pady=2)
        
        self.strategy_on_btn = ttk.Button(
            button_frame, 
            text="ON", 
            command=lambda: self.set_strategy_enabled(True),
            width=4,
            style='success.TButton'
        )
        self.strategy_on_btn.pack(side=LEFT, padx=1)
        
        self.strategy_off_btn = ttk.Button(
            button_frame, 
            text="OFF", 
            command=lambda: self.set_strategy_enabled(False),
            width=4,
            style='danger.TButton'
        )
        self.strategy_off_btn.pack(side=LEFT, padx=1)
        
        self.strategy_status_label = ttk.Label(
            button_frame, 
            text="OFF", 
            font=("Arial", 8, "bold"),
            foreground="#808080"
        )
        self.strategy_status_label.pack(side=LEFT, padx=2)
        
        # === LEFT COLUMN (Columns 0-1) ===
        
        # Row 1: VIX Threshold
        ttk.Label(master_section, text="VIX Thresh:", 
                  font=("Arial", 8)).grid(row=1, column=0, sticky=W, pady=2, padx=2)
        self.vix_threshold_entry = ttk.Entry(master_section, width=6, font=("Arial", 8))
        self.vix_threshold_entry.insert(0, "20")
        self.vix_threshold_entry.grid(row=1, column=1, sticky=EW, padx=2, pady=2)
        self.vix_threshold_entry.bind('<FocusOut>', self.auto_save_settings)
        self.vix_threshold_entry.bind('<Return>', self.auto_save_settings)
        
        # Row 2: Time Stop
        ttk.Label(master_section, text="Time Stop:", 
                  font=("Arial", 8)).grid(row=2, column=0, sticky=W, pady=2, padx=2)
        self.time_stop_entry = ttk.Entry(master_section, width=6, font=("Arial", 8))
        self.time_stop_entry.insert(0, "60")
        self.time_stop_entry.grid(row=2, column=1, sticky=EW, padx=2, pady=2)
        self.time_stop_entry.bind('<FocusOut>', self.auto_save_settings)
        self.time_stop_entry.bind('<Return>', self.auto_save_settings)
        
        # Row 3: Target Delta
        ttk.Label(master_section, text="Target Δ:", 
                  font=("Arial", 8)).grid(row=3, column=0, sticky=W, pady=2, padx=2)
        self.target_delta_entry = ttk.Entry(master_section, width=6, font=("Arial", 8))
        self.target_delta_entry.insert(0, "30")
        self.target_delta_entry.grid(row=3, column=1, sticky=EW, padx=2, pady=2)
        self.target_delta_entry.bind('<FocusOut>', self.auto_save_settings)
        self.target_delta_entry.bind('<Return>', self.auto_save_settings)
        
        # === RIGHT COLUMN (Columns 2-3) ===
        
        # Row 1: Max Risk
        ttk.Label(master_section, text="Max Risk:", 
                  font=("Arial", 8)).grid(row=1, column=2, sticky=W, pady=2, padx=(10, 2))
        risk_entry_frame = ttk.Frame(master_section)
        risk_entry_frame.grid(row=1, column=3, sticky=EW, padx=2, pady=2)
        ttk.Label(risk_entry_frame, text="$", font=("Arial", 8)).pack(side=LEFT)
        self.max_risk_entry = ttk.Entry(risk_entry_frame, width=6, font=("Arial", 8))
        self.max_risk_entry.insert(0, "500")
        self.max_risk_entry.pack(side=LEFT, fill=X, expand=True)
        self.max_risk_entry.bind('<FocusOut>', self.auto_save_settings)
        self.max_risk_entry.bind('<Return>', self.auto_save_settings)
        
        # Row 2: Trade Quantity
        ttk.Label(master_section, text="Trade Qty:", 
                  font=("Arial", 8)).grid(row=2, column=2, sticky=W, pady=2, padx=(10, 2))
        self.trade_qty_entry = ttk.Entry(master_section, width=6, font=("Arial", 8))
        self.trade_qty_entry.insert(0, "1")
        self.trade_qty_entry.grid(row=2, column=3, sticky=EW, padx=2, pady=2)
        self.trade_qty_entry.bind('<FocusOut>', self.auto_save_settings)
        self.trade_qty_entry.bind('<Return>', self.auto_save_settings)
        
        # Row 3: Position Size Mode (Radio buttons)
        ttk.Label(master_section, text="Pos. Size:", 
                  font=("Arial", 8, "bold")).grid(row=3, column=2, sticky=W, pady=2, padx=(10, 2))
        
        self.position_size_mode = tk.StringVar(value="fixed")  # "fixed" or "calculated"
        
        radio_frame = ttk.Frame(master_section)
        radio_frame.grid(row=3, column=3, sticky=W, padx=2)
        
        ttk.Radiobutton(radio_frame, text="Fixed", variable=self.position_size_mode, 
                       value="fixed", command=self.on_position_mode_change).pack(anchor=W, pady=1)
        ttk.Radiobutton(radio_frame, text="By Risk", variable=self.position_size_mode, 
                       value="calculated", command=self.on_position_mode_change).pack(anchor=W, pady=1)
        
        # Configure column weights
        master_section.columnconfigure(1, weight=1)
        master_section.columnconfigure(3, weight=1)
        
        # Initialize button states
        self.update_strategy_button_states()
        
        # ========================================================================
        # COLUMN 5: Straddle Strategy
        # ========================================================================
        straddle_container = ttk.Frame(bottom_panels_frame, width=180)
        straddle_container.pack(side=LEFT, fill=BOTH, expand=False, padx=3)
        straddle_container.pack_propagate(False)  # Maintain fixed width
        
        ttk.Label(straddle_container, text="Straddle Strategy", 
                 font=("Arial", 11, "bold")).pack(fill=X, pady=(0, 3))
        
        straddle_section = ttk.LabelFrame(straddle_container, text="Auto Entry", padding=5)
        straddle_section.pack(fill=BOTH, expand=True)
        
        # Enable/Disable buttons
        ttk.Label(straddle_section, text="Straddle:", 
                  font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=W, padx=2, pady=2)
        
        straddle_button_frame = ttk.Frame(straddle_section)
        straddle_button_frame.grid(row=0, column=1, sticky=EW, pady=2)
        
        self.straddle_on_btn = ttk.Button(
            straddle_button_frame, 
            text="ON", 
            command=lambda: self.set_straddle_enabled(True),
            width=4,
            style='success.TButton'
        )
        self.straddle_on_btn.pack(side=LEFT, padx=1)
        
        self.straddle_off_btn = ttk.Button(
            straddle_button_frame, 
            text="OFF", 
            command=lambda: self.set_straddle_enabled(False),
            width=4,
            style='danger.TButton'
        )
        self.straddle_off_btn.pack(side=LEFT, padx=1)
        
        self.straddle_status_label = ttk.Label(
            straddle_button_frame, 
            text="OFF", 
            font=("Arial", 8, "bold"),
            foreground="#808080"
        )
        self.straddle_status_label.pack(side=LEFT, padx=2)
        
        # Frequency setting
        ttk.Label(straddle_section, text="Frequency:", 
                  font=("Arial", 8)).grid(row=1, column=0, sticky=W, pady=2, padx=2)
        
        freq_frame = ttk.Frame(straddle_section)
        freq_frame.grid(row=1, column=1, sticky=EW, padx=2, pady=2)
        
        self.straddle_frequency_entry = ttk.Entry(freq_frame, width=6, font=("Arial", 8))
        self.straddle_frequency_entry.insert(0, "60")
        self.straddle_frequency_entry.pack(side=LEFT, fill=X, expand=True)
        self.straddle_frequency_entry.bind('<FocusOut>', self.auto_save_settings)
        self.straddle_frequency_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(freq_frame, text=" min", font=("Arial", 8)).pack(side=LEFT)
        
        # Info text
        ttk.Label(straddle_section, text="Uses Master Settings\nfor Delta & Position Size", 
                  font=("Arial", 7), foreground="#888888", 
                  justify=LEFT).grid(row=2, column=0, columnspan=2, sticky=W, padx=2, pady=(5, 0))
        
        # Status display
        self.straddle_next_label = ttk.Label(
            straddle_section, 
            text="Next: --:--", 
            font=("Arial", 7),
            foreground="#00BFFF"
        )
        self.straddle_next_label.grid(row=3, column=0, columnspan=2, sticky=W, padx=2, pady=(2, 0))
        
        straddle_section.columnconfigure(1, weight=1)
        
        # Initialize button states
        self.update_straddle_button_states()
        
        # ========================================================================
        # COLUMN 6: Manual Mode
        # ========================================================================
        manual_mode_container = ttk.Frame(bottom_panels_frame, width=180)
        manual_mode_container.pack(side=LEFT, fill=BOTH, expand=False, padx=(3, 0))
        manual_mode_container.pack_propagate(False)  # Maintain fixed width
        
        # Header
        ttk.Label(manual_mode_container, text="Manual Mode", 
                 font=("Arial", 11, "bold")).pack(fill=X, pady=(0, 3))
        
        # Manual Trading Controls
        manual_section = ttk.LabelFrame(manual_mode_container, text="Quick Entry", padding=5)
        manual_section.pack(fill=BOTH, expand=True)
        
        # Buy Call button (Green)
        self.buy_button = ttk.Button(manual_section, text="BUY CALL", 
                                      command=self.manual_buy_call,
                                      style='success.TButton', width=12)
        self.buy_button.pack(fill=X, pady=2)
        
        # Buy Put button (Red)
        self.sell_button = ttk.Button(manual_section, text="BUY PUT", 
                                       command=self.manual_buy_put,
                                       style='danger.TButton', width=12)
        self.sell_button.pack(fill=X, pady=2)
        
        # Info label
        ttk.Label(manual_section, text="Settings in Master panel →", 
                  font=("Arial", 8), foreground="#888888").pack(anchor=W, pady=(8, 0), padx=2)
        
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
        self.host_entry.bind('<FocusOut>', self.auto_save_settings)
        self.host_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(conn_frame, text="Port:").grid(row=1, column=0, sticky=W, pady=5)
        self.port_entry = ttk.Entry(conn_frame, width=30)
        self.port_entry.insert(0, str(self.port))
        self.port_entry.grid(row=1, column=1, sticky=W, padx=10, pady=5)
        self.port_entry.bind('<FocusOut>', self.auto_save_settings)
        self.port_entry.bind('<Return>', self.auto_save_settings)
        
        ttk.Label(conn_frame, text="Client ID:").grid(row=2, column=0, sticky=W, pady=5)
        self.client_entry = ttk.Entry(conn_frame, width=30)
        self.client_entry.insert(0, str(self.client_id))
        self.client_entry.grid(row=2, column=1, sticky=W, padx=10, pady=5)
        self.client_entry.bind('<FocusOut>', self.auto_save_settings)
        self.client_entry.bind('<Return>', self.auto_save_settings)
        
        # Strategy Settings Section
        # NOTE: Strategy Parameters and Gamma-Snap Strategy sections (including Trade Quantity)
        # have been moved to the main Trading tab (Manual Mode panel) for easier access.
        # All strategy settings are now directly accessible without switching tabs.
        
        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=X, padx=20, pady=20)
        
        ttk.Button(button_frame, text="Save & Reconnect", 
                  command=self.save_and_reconnect,
                  style="success.TButton", width=20).pack(side=LEFT, padx=5)
        
        ttk.Label(button_frame, text="All settings auto-save on change",
                 font=("Arial", 9, "italic"),
                 foreground="#808080").pack(side=LEFT, padx=15)
        
        canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)
    
    def create_chart_tab(self):
        """Create SPX chart tab with candlesticks, 9-EMA, and trade markers"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="SPX Chart")
        
        # Chart controls at top
        controls_frame = ttk.Frame(tab)
        controls_frame.pack(fill=X, padx=10, pady=10)
        
        ttk.Label(controls_frame, text="Chart Period:", font=("Arial", 10, "bold")).pack(side=LEFT, padx=5)
        self.chart_period_var = tk.StringVar(value="1 D")
        chart_period_combo = ttk.Combobox(controls_frame, textvariable=self.chart_period_var,
                                         values=["1 D", "2 D", "5 D"], state="readonly", width=8)
        chart_period_combo.pack(side=LEFT, padx=5)
        chart_period_combo.bind('<<ComboboxSelected>>', lambda e: self.request_chart_data())
        
        ttk.Label(controls_frame, text="Timeframe:", font=("Arial", 10, "bold")).pack(side=LEFT, padx=15)
        self.chart_timeframe_var = tk.StringVar(value="1 min")
        chart_timeframe_combo = ttk.Combobox(controls_frame, textvariable=self.chart_timeframe_var,
                                            values=["1 min", "5 mins", "15 mins"], state="readonly", width=10)
        chart_timeframe_combo.pack(side=LEFT, padx=5)
        chart_timeframe_combo.bind('<<ComboboxSelected>>', lambda e: self.request_chart_data())
        
        ttk.Button(controls_frame, text="Refresh Chart", 
                  command=self.request_chart_data,
                  style="info.TButton", width=15).pack(side=LEFT, padx=15)
        
        self.chart_status_label = ttk.Label(controls_frame, text="Chart: Waiting for data...",
                                           font=("Arial", 9), foreground="#808080")
        self.chart_status_label.pack(side=LEFT, padx=10)
        
        # Matplotlib figure and canvas
        self.chart_figure = Figure(figsize=(12, 8), facecolor='#000000')
        self.chart_ax = self.chart_figure.add_subplot(111)
        self.chart_ax.set_facecolor('#000000')
        
        # Style the chart to match TWS
        self.chart_ax.tick_params(colors='#808080', which='both')
        self.chart_ax.spines['bottom'].set_color('#3a3a3a')
        self.chart_ax.spines['top'].set_color('#3a3a3a')
        self.chart_ax.spines['left'].set_color('#3a3a3a')
        self.chart_ax.spines['right'].set_color('#3a3a3a')
        self.chart_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5)
        
        self.chart_canvas = FigureCanvasTkAgg(self.chart_figure, master=tab)
        self.chart_canvas.get_tk_widget().pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Initialize chart variables
        self.chart_candlestick_data = []
        self.chart_trade_markers = []
        
        self.log_message("Chart tab created - ready for data", "INFO")
    
    def refresh_confirm_chart(self):
        """Refresh confirmation chart with current settings"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot refresh chart - not connected", "WARNING")
            return
        
        # Cancel existing subscription first to avoid duplicate ticker ID error
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
        
        # Create contract for underlying index
        spx_contract = Contract()
        spx_contract.symbol = UNDERLYING_SYMBOL
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Clear existing data
        self.confirm_bar_data.clear()
        
        # Get settings
        period = self.confirm_period_var.get()
        timeframe = self.confirm_timeframe_var.get()
        
        # Request historical data with streaming enabled
        try:
            self.reqHistoricalData(
                999995,  # Unique ID for confirmation chart
                spx_contract,
                "",
                period,
                timeframe,
                "TRADES",
                1,
                1,
                True,  # keepUpToDate=True for real-time streaming
                []
            )
            
            # Mark as active only after successful request
            self.confirm_chart_active = True
            self.log_message(f"✓ Confirmation chart refreshed: {period} {timeframe} (streaming)", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error requesting Confirmation chart: {str(e)}", "ERROR")
    
    def refresh_trade_chart(self):
        """Refresh trade chart with current settings"""
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot refresh chart - not connected", "WARNING")
            return
        
        # Cancel existing subscription first to avoid duplicate ticker ID error
        if self.trade_chart_active:
            try:
                self.log_message("Canceling existing Trade chart subscription...", "INFO")
                self.cancelHistoricalData(999994)
                self.trade_chart_active = False
                # Small delay to ensure cancellation is processed
                import time
                time.sleep(0.1)
            except Exception as e:
                self.log_message(f"Error canceling Trade chart: {str(e)}", "WARNING")
        
        # Create contract for underlying index
        spx_contract = Contract()
        spx_contract.symbol = UNDERLYING_SYMBOL
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Clear existing data
        self.trade_bar_data.clear()
        
        # Get settings
        period = self.trade_period_var.get()
        timeframe = self.trade_timeframe_var.get()
        
        # Request historical data with streaming enabled
        try:
            self.reqHistoricalData(
                999994,  # Unique ID for trade chart
                spx_contract,
                "",
                period,
                timeframe,
                "TRADES",
                1,
                1,
                True,  # keepUpToDate=True for real-time streaming
                []
            )
            
            # Mark as active only after successful request
            self.trade_chart_active = True
            self.log_message(f"✓ Trade chart refreshed: {period} {timeframe} (streaming)", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error requesting Trade chart: {str(e)}", "ERROR")
    
    def request_chart_data(self):
        """Request SPX historical data for BOTH charts (legacy function - calls both refresh functions)"""
        self.refresh_confirm_chart()
        self.refresh_trade_chart()
    
    def update_chart_display(self, chart_type="confirm"):
        """Update the matplotlib chart with candlestick data, indicators, and Z-Score
        
        Args:
            chart_type: 'confirm' or 'trade' to specify which chart to update
        """
        # Select the appropriate data and chart objects
        if chart_type == "confirm":
            bar_data = self.confirm_bar_data
            price_ax = self.confirm_ax
            zscore_ax = self.confirm_zscore_ax
            canvas = self.confirm_canvas
            ema_length = int(self.confirm_ema_entry.get() or "9")
            z_period = int(self.confirm_z_period_entry.get() or "30")
            z_threshold = float(self.confirm_z_threshold_entry.get() or "1.5")
            chart_name = "Confirmation"
            chart_title = f"SPX Confirmation Chart ({ema_length}-EMA, Z-Period={z_period})"
        else:  # trade
            bar_data = self.trade_bar_data
            price_ax = self.trade_ax
            zscore_ax = self.trade_zscore_ax
            canvas = self.trade_canvas
            ema_length = int(self.trade_ema_entry.get() or "9")
            z_period = int(self.trade_z_period_entry.get() or "30")
            z_threshold = float(self.trade_z_threshold_entry.get() or "1.5")
            chart_name = "Trade"
            chart_title = f"SPX Trade Chart ({ema_length}-EMA, Z-Period={z_period})"
        
        if not bar_data:
            self.log_message(f"No {chart_name} chart data to display", "WARNING")
            return
        
        # Convert bar data to DataFrame
        df = pd.DataFrame(bar_data)
        
        # Parse time strings to datetime
        if isinstance(df['time'].iloc[0], str):
            df['time'] = pd.to_datetime(df['time'], format='%Y%m%d  %H:%M:%S')
        
        # Calculate EMA with configurable length
        df['ema'] = df['close'].ewm(span=ema_length, adjust=False).mean()
        
        # Calculate Z-Score with configurable period
        sma = df['close'].rolling(window=z_period).mean()
        std = df['close'].rolling(window=z_period).std()
        df['z_score'] = (df['close'] - sma) / std
        df['bb_upper'] = sma + (std * 2)
        df['bb_lower'] = sma - (std * 2)
        
        # Clear previous charts
        price_ax.clear()
        zscore_ax.clear()
        
        # ========================================================================
        # PRICE CHART (Top Subplot)
        # ========================================================================
        
        # Plot candlesticks manually
        for i, (idx, row) in enumerate(df.iterrows()):
            color = '#26a69a' if row['close'] >= row['open'] else '#ef5350'  # Green up, red down
            
            # Draw the candle body
            body_height = abs(row['close'] - row['open'])
            body_bottom = min(row['open'], row['close'])
            
            price_ax.add_patch(Rectangle(
                (i, body_bottom), 0.8, body_height,
                facecolor=color, edgecolor=color, linewidth=0
            ))
            
            # Draw the wicks
            price_ax.plot([i + 0.4, i + 0.4], [row['low'], row['high']], 
                         color=color, linewidth=1)
        
        # Plot EMA (with dynamic label showing actual length)
        price_ax.plot(range(len(df)), df['ema'], color='#FF8C00', linewidth=2, 
                     label=f'{ema_length}-EMA', alpha=0.9)
        
        # Plot Bollinger Bands
        price_ax.plot(range(len(df)), df['bb_upper'], color='#2962FF', linewidth=1, 
                     label='BB Upper', alpha=0.5, linestyle='--')
        price_ax.plot(range(len(df)), df['bb_lower'], color='#2962FF', linewidth=1, 
                     label='BB Lower', alpha=0.5, linestyle='--')
        
        # Add trade markers (ONLY on Trade chart)
        if chart_type == "trade":
            for trade in self.trade_history:
                try:
                    if 'entry_time' in trade:
                        time_diffs = (df['time'] - trade['entry_time']).abs()
                        entry_idx = time_diffs.idxmin()
                        entry_loc = df.index.get_loc(entry_idx)
                        if isinstance(entry_loc, int):
                            entry_position = entry_loc
                            entry_price = trade.get('entry_price', 0)
                            if entry_price > 0:
                                price_ax.scatter(entry_position, entry_price, marker='v', s=200, 
                                               color='#2196F3', zorder=5)
                                price_ax.text(entry_position, entry_price, f" ${entry_price:.2f}", 
                                            color='#2196F3', fontsize=8, va='top')
                    
                    if 'exit_time' in trade and trade.get('exit_time'):
                        time_diffs = (df['time'] - trade['exit_time']).abs()
                        exit_idx = time_diffs.idxmin()
                        exit_loc = df.index.get_loc(exit_idx)
                        if isinstance(exit_loc, int):
                            exit_position = exit_loc
                            exit_price = trade.get('exit_price_final', 0)
                            if exit_price > 0:
                                pnl = trade.get('pnl', 0)
                                marker_color = '#00FF00' if pnl > 0 else '#FF0000'
                                price_ax.scatter(exit_position, exit_price, marker='^', s=200, 
                                               color=marker_color, zorder=5)
                                price_ax.text(exit_position, exit_price, f" ${exit_price:.2f}\n${pnl:.0f}", 
                                            color=marker_color, fontsize=8, va='bottom')
                except Exception as e:
                    continue
        
        # Price chart styling
        price_ax.set_facecolor('#000000')
        price_ax.tick_params(colors='#808080', which='both', labelsize=8, labelbottom=False)
        price_ax.spines['bottom'].set_color('#3a3a3a')
        price_ax.spines['top'].set_color('#3a3a3a')
        price_ax.spines['left'].set_color('#3a3a3a')
        price_ax.spines['right'].set_color('#3a3a3a')
        price_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        
        # Move Y-axis to the right
        price_ax.yaxis.tick_right()
        price_ax.yaxis.set_label_position("right")
        price_ax.set_ylabel('SPX Price', color='#808080', fontsize=9)
        price_ax.set_title(chart_title, color='#C0C0C0', fontsize=11, fontweight='bold', pad=5)
        
        # Add current price label on Y-axis (bold and highlighted)
        if not df.empty:
            current_price = df['close'].iloc[-1]
            price_ax.axhline(y=current_price, color='#00FF00', linestyle='--', linewidth=1, alpha=0.3)
            price_ax.text(len(df) + 0.5, current_price, f' ${current_price:.2f} ', 
                         fontsize=9, fontweight='bold', color='#00FF00',
                         bbox=dict(boxstyle='round,pad=0.3', facecolor='#000000', 
                                  edgecolor='#00FF00', linewidth=1.5),
                         verticalalignment='center', horizontalalignment='left')
        
        # Legend for price chart
        if df['ema'].notna().any():
            legend = price_ax.legend(loc='upper left', facecolor='#1a1a1a', 
                                    edgecolor='#3a3a3a', framealpha=0.9, fontsize=8)
            for text in legend.get_texts():
                text.set_color('#C0C0C0')
        
        # ========================================================================
        # Z-SCORE INDICATOR (Bottom Subplot)
        # ========================================================================
        
        # Plot Z-Score line
        z_score_array = df['z_score'].to_numpy()
        zscore_ax.plot(range(len(df)), z_score_array, color='#00BFFF', linewidth=2, 
                      label='Z-Score', alpha=0.9)
        
        # Fill areas for visual clarity
        zscore_ax.fill_between(range(len(df)), 0, z_score_array, 
                              where=(z_score_array > 0), color='#44ff44', alpha=0.2)  # type: ignore
        zscore_ax.fill_between(range(len(df)), 0, z_score_array, 
                              where=(z_score_array < 0), color='#ff4444', alpha=0.2)  # type: ignore
        
        # Entry signal lines (use configurable threshold)
        zscore_ax.axhline(y=0, color='#808080', linestyle='-', linewidth=1, alpha=0.5)
        zscore_ax.axhline(y=z_threshold, color='#44ff44', linestyle='--', linewidth=1.5, 
                         alpha=0.8, label=f'Buy Signal (+{z_threshold})')
        zscore_ax.axhline(y=-z_threshold, color='#ff4444', linestyle='--', linewidth=1.5, 
                         alpha=0.8, label=f'Sell Signal (-{z_threshold})')
        
        # Z-Score chart styling
        zscore_ax.set_facecolor('#000000')
        zscore_ax.tick_params(colors='#808080', which='both', labelsize=8)
        zscore_ax.spines['bottom'].set_color('#3a3a3a')
        zscore_ax.spines['top'].set_color('#3a3a3a')
        zscore_ax.spines['left'].set_color('#3a3a3a')
        zscore_ax.spines['right'].set_color('#3a3a3a')
        zscore_ax.grid(True, color='#1a1a1a', linestyle='-', linewidth=0.5, alpha=0.3)
        
        # Move Y-axis to the right
        zscore_ax.yaxis.tick_right()
        zscore_ax.yaxis.set_label_position("right")
        zscore_ax.set_ylabel('Z-Score', color='#808080', fontsize=9)
        zscore_ax.set_xlabel('Time', color='#808080', fontsize=9)
        zscore_ax.set_ylim(-3, 3)
        
        # Add current Z-Score label on Y-axis (bold and highlighted)
        if not df.empty and not df['z_score'].isna().iloc[-1]:
            current_zscore = df['z_score'].iloc[-1]
            zscore_color = '#44ff44' if current_zscore > 0 else '#ff4444' if current_zscore < 0 else '#808080'
            zscore_ax.text(len(df) + 0.5, current_zscore, f' {current_zscore:.2f} ', 
                          fontsize=9, fontweight='bold', color=zscore_color,
                          bbox=dict(boxstyle='round,pad=0.3', facecolor='#000000', 
                                   edgecolor=zscore_color, linewidth=1.5),
                          verticalalignment='center', horizontalalignment='left')
        
        # Legend for Z-Score
        z_legend = zscore_ax.legend(loc='upper left', facecolor='#1a1a1a', 
                                   edgecolor='#3a3a3a', framealpha=0.9, fontsize=8)
        for text in z_legend.get_texts():
            text.set_color('#C0C0C0')
        
        # Refresh canvas
        canvas.draw()
        
        # Chart updated successfully (logging removed to reduce spam)
    
    def create_status_bar(self, parent):
        """Create status bar at bottom of window (now inside scrollable container)"""
        status_frame = ttk.Frame(parent, relief=tk.SUNKEN)
        status_frame.pack(side=BOTTOM, fill=X, padx=5, pady=5)
        
        # Connection status
        self.status_label = ttk.Label(status_frame, text="Status: Disconnected",
                                     font=("Arial", 10))
        self.status_label.pack(side=LEFT, padx=10, pady=5)
        
        # Connect/Disconnect button
        self.connect_btn = ttk.Button(status_frame, text="Connect",
                                     command=self.toggle_connection,
                                     style="success.TButton", width=15)
        self.connect_btn.pack(side=LEFT, padx=5, pady=5)
        
        # SPX Price (larger, center-ish)
        self.spx_label = ttk.Label(status_frame, text="SPX: --",
                                  font=("Arial", 12, "bold"),
                                  foreground="#00BFFF")
        self.spx_label.pack(side=LEFT, padx=20, pady=5)
        
        # VIX Price
        self.vix_label = ttk.Label(status_frame, text="VIX: --",
                                  font=("Arial", 10),
                                  foreground="#FFA500")
        self.vix_label.pack(side=LEFT, padx=10, pady=5)
        
        # Z-Score Indicator
        self.z_score_label = ttk.Label(status_frame, text="Z-Score: --",
                                      font=("Arial", 10),
                                      foreground="#C0C0C0")
        self.z_score_label.pack(side=LEFT, padx=10, pady=5)
        
        # Strategy Status (use StringVar for dynamic updates)
        self.strategy_status_var = tk.StringVar(value="Strategy: OFF")
        self.strategy_status_display = ttk.Label(status_frame, 
                                                 textvariable=self.strategy_status_var,
                                                 font=("Arial", 10),
                                                 foreground="#808080")
        self.strategy_status_display.pack(side=LEFT, padx=10, pady=5)
        
        # Time
        self.time_label = ttk.Label(status_frame, text="",
                                   font=("Arial", 10))
        self.time_label.pack(side=RIGHT, padx=10, pady=5)
        
        # Total PnL
        self.pnl_label = ttk.Label(status_frame, text="Total PnL: $0.00",
                                  font=("Arial", 10, "bold"))
        self.pnl_label.pack(side=RIGHT, padx=10, pady=5)
        
        self.update_time()
    
    def update_time(self):
        """Update time display"""
        if not self.root:
            return
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self.update_time)
    
    def update_vix_display(self):
        """Update VIX display in status bar"""
        if not hasattr(self, 'vix_label'):
            return
        
        if self.vix_price > 0:
            # Color code: Green if low (<20), Yellow if medium (20-30), Red if high (>30)
            if self.vix_price < 20:
                color = "#00FF00"  # Green - low volatility
            elif self.vix_price < 30:
                color = "#FFA500"  # Orange - medium volatility
            else:
                color = "#FF0000"  # Red - high volatility (strategy paused)
            
            self.vix_label.config(
                text=f"VIX: {self.vix_price:.2f}",
                foreground=color
            )
        else:
            self.vix_label.config(text="VIX: --", foreground="#808080")
    
    def update_indicator_display(self):
        """Update Z-Score and other indicators in status bar"""
        if not hasattr(self, 'z_score_label'):
            return
        
        z_score = self.indicators.get('z_score', 0)
        
        # Color code Z-Score based on threshold
        if abs(z_score) > self.z_score_threshold:
            color = "#FF0000"  # Red - beyond threshold (signal zone)
        elif abs(z_score) > self.z_score_threshold * 0.5:
            color = "#FFA500"  # Orange - approaching threshold
        else:
            color = "#00FF00"  # Green - within normal range
        
        self.z_score_label.config(
            text=f"Z-Score: {z_score:.2f}",
            foreground=color
        )
    
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
            # Cancel position subscription before disconnecting
            self.cancelPositions()
            EClient.disconnect(self)
        except Exception as e:
            self.log_message(f"Error during disconnect: {str(e)}", "WARNING")
        
        self.connection_state = ConnectionState.DISCONNECTED
        self.data_server_ok = False  # Reset data server flag on disconnect
        self.client_id_iterator = 1  # Reset client ID iterator for next connection
        
        # Reset chart subscription flags
        self.confirm_chart_active = False
        self.trade_chart_active = False
        
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
        
        # Request position updates (sync with TWS)
        self.log_message("Requesting position updates...", "INFO")
        self.reqPositions()
        
        # Subscribe to SPX underlying price
        self.log_message("Subscribing to SPX underlying price...", "INFO")
        self.subscribe_spx_price()
        
        # Request option chain - this will automatically subscribe to market data
        self.log_message("Requesting SPX option chain for 0DTE...", "INFO")
        self.request_option_chain()
        
        # Request SPX chart data with indicators
        self.log_message("Requesting SPX chart data with indicators...", "INFO")
        self.request_chart_data()
        
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
            self.strikes_above = int(self.strikes_above_entry.get())
            self.strikes_below = int(self.strikes_below_entry.get())
            self.chain_refresh_interval = int(self.chain_refresh_entry.get())
            
            # Master Settings (strategy parameters)
            self.vix_threshold = float(self.vix_threshold_entry.get())
            self.time_stop_minutes = int(self.time_stop_entry.get())
            self.trade_qty = int(self.trade_qty_entry.get())
            
            settings = {
                'host': self.host,
                'port': self.port,
                'client_id': self.client_id,
                'strikes_above': self.strikes_above,
                'strikes_below': self.strikes_below,
                'chain_refresh_interval': self.chain_refresh_interval,
                'strategy_enabled': self.strategy_enabled,
                # Master Settings
                'vix_threshold': self.vix_threshold,
                'time_stop_minutes': self.time_stop_minutes,
                'trade_qty': self.trade_qty,
                # Straddle Strategy
                'straddle_enabled': self.straddle_enabled,
                'straddle_frequency_minutes': int(self.straddle_frequency_entry.get() or "60"),
                # Dual Chart Settings
                'confirm_ema': int(self.confirm_ema_entry.get() or "9"),
                'confirm_z_period': int(self.confirm_z_period_entry.get() or "30"),
                'confirm_z_threshold': float(self.confirm_z_threshold_entry.get() or "1.5"),
                'trade_ema': int(self.trade_ema_entry.get() or "9"),
                'trade_z_period': int(self.trade_z_period_entry.get() or "30"),
                'trade_z_threshold': float(self.trade_z_threshold_entry.get() or "1.5"),
                # Chart period/timeframe settings
                'call_days': self.call_days_var.get(),
                'call_timeframe': self.call_timeframe_var.get(),
                'put_days': self.put_days_var.get(),
                'put_timeframe': self.put_timeframe_var.get(),
                'confirm_period': self.confirm_period_var.get(),
                'confirm_timeframe': self.confirm_timeframe_var.get(),
                'trade_period': self.trade_period_var.get(),
                'trade_timeframe': self.trade_timeframe_var.get()
            }
            
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            
            self.log_message("Settings saved successfully", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error saving settings: {str(e)}", "ERROR")
    
    def auto_save_settings(self, event=None):
        """Auto-save settings when any field changes (silent save without log message)"""
        try:
            if not hasattr(self, 'host_entry'):
                return  # GUI not fully initialized yet
            
            # Read values from entries (with validation)
            try:
                self.host = self.host_entry.get()
                self.port = int(self.port_entry.get())
                self.client_id = int(self.client_entry.get())
                self.strikes_above = int(self.strikes_above_entry.get())
                self.strikes_below = int(self.strikes_below_entry.get())
                self.chain_refresh_interval = int(self.chain_refresh_entry.get())
                
                # Master Settings (strategy parameters)
                if hasattr(self, 'vix_threshold_entry'):
                    self.vix_threshold = float(self.vix_threshold_entry.get())
                    self.time_stop_minutes = int(self.time_stop_entry.get())
                    self.trade_qty = int(self.trade_qty_entry.get())
                    self.target_delta = float(self.target_delta_entry.get())
                    self.max_risk = float(self.max_risk_entry.get())
                    self.position_size_mode_value = self.position_size_mode.get()
            except (ValueError, AttributeError):
                # Skip save if validation fails (user still typing)
                return
            
            settings = {
                'host': self.host,
                'port': self.port,
                'client_id': self.client_id,
                'strikes_above': self.strikes_above,
                'strikes_below': self.strikes_below,
                'chain_refresh_interval': self.chain_refresh_interval,
                'strategy_enabled': self.strategy_enabled,
                # Master Settings
                'vix_threshold': getattr(self, 'vix_threshold', 30.0),
                'time_stop_minutes': getattr(self, 'time_stop_minutes', 60),
                'trade_qty': getattr(self, 'trade_qty', 1),
                'target_delta': getattr(self, 'target_delta', 30.0),
                'max_risk': getattr(self, 'max_risk', 500.0),
                'position_size_mode': getattr(self, 'position_size_mode_value', 'fixed'),
                # Straddle Strategy
                'straddle_enabled': getattr(self, 'straddle_enabled', False),
                'straddle_frequency_minutes': int(self.straddle_frequency_entry.get() or "60") if hasattr(self, 'straddle_frequency_entry') else 60,
                # Dual Chart Settings
                'confirm_ema': int(self.confirm_ema_entry.get() or "9"),
                'confirm_z_period': int(self.confirm_z_period_entry.get() or "30"),
                'confirm_z_threshold': float(self.confirm_z_threshold_entry.get() or "1.5"),
                'trade_ema': int(self.trade_ema_entry.get() or "9"),
                'trade_z_period': int(self.trade_z_period_entry.get() or "30"),
                'trade_z_threshold': float(self.trade_z_threshold_entry.get() or "1.5"),
                # Chart settings
                'call_days': self.call_days_var.get() if hasattr(self, 'call_days_var') else '1',
                'call_timeframe': self.call_timeframe_var.get() if hasattr(self, 'call_timeframe_var') else '1 min',
                'put_days': self.put_days_var.get() if hasattr(self, 'put_days_var') else '5',
                'put_timeframe': self.put_timeframe_var.get() if hasattr(self, 'put_timeframe_var') else '1 min',
                'confirm_period': self.confirm_period_var.get() if hasattr(self, 'confirm_period_var') else '1 D',
                'confirm_timeframe': self.confirm_timeframe_var.get() if hasattr(self, 'confirm_timeframe_var') else '1 min',
                'trade_period': self.trade_period_var.get() if hasattr(self, 'trade_period_var') else '1 D',
                'trade_timeframe': self.trade_timeframe_var.get() if hasattr(self, 'trade_timeframe_var') else '15 secs'
            }
            
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            
            # Silent save - no log message to avoid spam
        except Exception as e:
            # Silent fail for auto-save
            pass
    
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
                self.strategy_enabled = settings.get('strategy_enabled', False)
                
                # Z-Score Strategy Parameters
                self.vix_threshold = settings.get('vix_threshold', 30.0)
                self.z_score_period = settings.get('z_score_period', 20)
                self.z_score_threshold = settings.get('z_score_threshold', 1.5)
                self.time_stop_minutes = settings.get('time_stop_minutes', 30)
                self.trade_qty = settings.get('trade_qty', 1)
                self.target_delta = settings.get('target_delta', 30.0)
                self.max_risk = settings.get('max_risk', 500.0)
                
                # Position size mode
                if hasattr(self, 'position_size_mode'):
                    self.position_size_mode.set(settings.get('position_size_mode', 'fixed'))
                
                # Straddle Strategy Parameters
                self.straddle_enabled = settings.get('straddle_enabled', False)
                self.straddle_frequency_minutes = settings.get('straddle_frequency_minutes', 60)
                
                # Restore chart settings if StringVars exist
                if hasattr(self, 'call_days_var'):
                    self.call_days_var.set(settings.get('call_days', '1'))
                if hasattr(self, 'call_timeframe_var'):
                    self.call_timeframe_var.set(settings.get('call_timeframe', '1 min'))
                if hasattr(self, 'put_days_var'):
                    self.put_days_var.set(settings.get('put_days', '5'))
                if hasattr(self, 'put_timeframe_var'):
                    self.put_timeframe_var.set(settings.get('put_timeframe', '1 min'))
                
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
                
                # Restore period/timeframe variables
                if hasattr(self, 'confirm_period_var'):
                    self.confirm_period_var.set(settings.get('confirm_period', '1 D'))
                if hasattr(self, 'confirm_timeframe_var'):
                    self.confirm_timeframe_var.set(settings.get('confirm_timeframe', '1 min'))
                if hasattr(self, 'trade_period_var'):
                    self.trade_period_var.set(settings.get('trade_period', '1 D'))
                if hasattr(self, 'trade_timeframe_var'):
                    self.trade_timeframe_var.set(settings.get('trade_timeframe', '15 secs'))
                
                self.log_message("✓ Settings loaded successfully", "SUCCESS")
        except Exception as e:
            self.log_message(f"Error loading settings: {str(e)}", "ERROR")
    
    def update_strategy_button_states(self):
        """Update the visual state of strategy ON/OFF buttons"""
        if self.strategy_enabled:
            # ON is active (green background)
            self.strategy_on_btn.config(style="success.TButton")
            self.strategy_off_btn.config(style="TButton")
            self.strategy_status_label.config(
                text="ACTIVE",
                foreground="#00FF00"
            )
        else:
            # OFF is active (red background)
            self.strategy_on_btn.config(style="TButton")
            self.strategy_off_btn.config(style="danger.TButton")
            self.strategy_status_label.config(
                text="INACTIVE",
                foreground="#FF0000"
            )
    
    def set_strategy_enabled(self, enabled: bool):
        """Enable or disable the automated Z-Score strategy"""
        self.strategy_enabled = enabled
        self.update_strategy_button_states()
        
        if enabled:
            self.log_message("=" * 60, "INFO")
            self.log_message("✓ GAMMA-TRAP Z-SCORE STRATEGY ENABLED", "SUCCESS")
            self.log_message("=" * 60, "INFO")
            self.log_message("Strategy Parameters:", "INFO")
            self.log_message(f"  VIX Threshold: {self.vix_threshold}", "INFO")
            self.log_message(f"  Z-Score Period: {self.z_score_period} bars", "INFO")
            self.log_message(f"  Z-Score Threshold: ±{self.z_score_threshold}", "INFO")
            self.log_message(f"  Time Stop: {self.time_stop_minutes} minutes", "INFO")
            
            self.log_message("Uses Master Settings:", "INFO")
            self.log_message(f"  Target Delta: {self.target_delta_entry.get()}", "INFO")
            
            mode = self.position_size_mode.get()
            if mode == "fixed":
                self.log_message(f"  Position Size: {self.trade_qty_entry.get()} contracts (Fixed)", "INFO")
            else:
                self.log_message(f"  Position Size: Calculated (Max Risk: ${self.max_risk_entry.get()})", "INFO")
            self.log_message("=" * 60, "INFO")
        else:
            self.log_message("=" * 60, "INFO")
            self.log_message("✗ GAMMA-TRAP Z-SCORE STRATEGY DISABLED", "WARNING")
            # If there's an active trade, log warning but don't exit
            if self.active_trade_info:
                self.log_message(
                    "⚠ Warning: Active trade will continue to be monitored for exit conditions",
                    "WARNING"
                )
            self.log_message("=" * 60, "INFO")
        
        # Auto-save settings
        self.auto_save_settings()
    
    def on_position_mode_change(self):
        """Handle position size mode radio button change"""
        mode = self.position_size_mode.get()
        if mode == "fixed":
            self.trade_qty_entry.config(state="normal")
            self.log_message("Position sizing: Fixed quantity mode", "INFO")
        else:  # calculated
            self.trade_qty_entry.config(state="disabled")
            self.log_message("Position sizing: Calculate by max risk mode", "INFO")
        self.auto_save_settings()
    
    def is_market_open(self) -> bool:
        """
        Check if SPX/XSP options market is open for trading.
        
        Regular Trading Hours: 8:30 AM - 3:15 PM ET, Monday-Friday
        (Extended hours 8:15 PM - 9:15 AM ET available but not used for automated strategies)
        
        Returns:
            bool: True if market is open for trading
        """
        try:
            from datetime import time
            import pytz
            
            # Get current time in Eastern Time
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)
            
            # Check if weekend
            if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
                return False
            
            # Check if in regular trading hours (8:30 AM - 3:15 PM ET)
            current_time = now_et.time()
            market_open = time(8, 30)   # 8:30 AM
            market_close = time(15, 15)  # 3:15 PM
            
            return market_open <= current_time <= market_close
            
        except ImportError:
            # If pytz not available, use simple check (assumes system time is ET or close enough)
            self.log_message("WARNING: pytz not installed - using local time for market hours check", "WARNING")
            now = datetime.now()
            
            # Check if weekend
            if now.weekday() >= 5:
                return False
            
            # Check hours (assuming local time is close to ET)
            current_time = now.time()
            market_open = time(8, 30)
            market_close = time(15, 15)
            
            return market_open <= current_time <= market_close
    
    def update_straddle_button_states(self):
        """Update the visual state of straddle strategy ON/OFF buttons"""
        if self.straddle_enabled:
            # ON is active (green background)
            self.straddle_on_btn.config(style="success.TButton")
            self.straddle_off_btn.config(style="TButton")
            self.straddle_status_label.config(
                text="ACTIVE",
                foreground="#00FF00"
            )
        else:
            # OFF is active (red background)
            self.straddle_on_btn.config(style="TButton")
            self.straddle_off_btn.config(style="danger.TButton")
            self.straddle_status_label.config(
                text="INACTIVE",
                foreground="#FF0000"
            )
    
    def set_straddle_enabled(self, enabled: bool):
        """Enable or disable the automated straddle strategy"""
        self.straddle_enabled = enabled
        self.update_straddle_button_states()
        
        if enabled:
            try:
                self.straddle_frequency_minutes = int(self.straddle_frequency_entry.get())
            except ValueError:
                self.straddle_frequency_minutes = 60
                self.straddle_frequency_entry.delete(0, tk.END)
                self.straddle_frequency_entry.insert(0, "60")
            
            self.log_message("=" * 60, "INFO")
            self.log_message("✓ STRADDLE STRATEGY ENABLED", "SUCCESS")
            self.log_message(f"  Frequency: Every {self.straddle_frequency_minutes} minutes", "INFO")
            self.log_message(f"  Uses Master Settings:", "INFO")
            self.log_message(f"    Target Delta: {self.target_delta_entry.get()}", "INFO")
            
            mode = self.position_size_mode.get()
            if mode == "fixed":
                self.log_message(f"    Position Size: {self.trade_qty_entry.get()} contracts (Fixed)", "INFO")
            else:
                self.log_message(f"    Position Size: Calculated (Max Risk: ${self.max_risk_entry.get()})", "INFO")
            self.log_message("=" * 60, "INFO")
            
            # Reset timer but DON'T enter immediately - wait for first interval
            self.last_straddle_time = datetime.now()  # Start timer from now
            self.log_message(f"⏰ Timer started - first entry in {self.straddle_frequency_minutes} minutes", "INFO")
        else:
            self.log_message("=" * 60, "INFO")
            self.log_message("✗ STRADDLE STRATEGY DISABLED", "WARNING")
            self.log_message("=" * 60, "INFO")
        
        # Auto-save settings
        self.auto_save_settings()
    
    # ========================================================================
    # SPX UNDERLYING PRICE
    # ========================================================================
    
    def subscribe_spx_price(self):
        """
        Subscribe to SPX underlying index price.
        This provides real-time price updates for the SPX index.
        """
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot subscribe to underlying price - not connected", "WARNING")
            return
        
        # Create underlying index contract
        spx_contract = Contract()
        spx_contract.symbol = UNDERLYING_SYMBOL
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Get unique request ID
        self.spx_req_id = self.next_req_id
        self.next_req_id += 1
        
        # Request market data for underlying
        self.reqMktData(self.spx_req_id, spx_contract, "", False, False, [])
        self.log_message(f"Subscribed to {UNDERLYING_SYMBOL} underlying price (reqId: {self.spx_req_id})", "INFO")
        
        # Subscribe to VIX for strategy filter
        self.subscribe_vix_price()
        
        # Request SPX 1-min historical data for Z-Score strategy
        self.request_spx_1min_history()
    
    def subscribe_vix_price(self):
        """Subscribe to VIX index for volatility monitoring"""
        if self.connection_state != ConnectionState.CONNECTED:
            return
        
        vix_contract = Contract()
        vix_contract.symbol = "VIX"
        vix_contract.secType = "IND"
        vix_contract.currency = "USD"
        vix_contract.exchange = "CBOE"
        
        self.reqMktData(self.vix_req_id, vix_contract, "", False, False, [])
        self.log_message(f"Subscribed to VIX (reqId: {self.vix_req_id})", "INFO")
    
    def request_spx_1min_history(self):
        """Request underlying 1-minute historical data for Z-Score calculation"""
        if self.connection_state != ConnectionState.CONNECTED:
            return
        
        spx_contract = Contract()
        spx_contract.symbol = UNDERLYING_SYMBOL
        spx_contract.secType = "IND"
        spx_contract.currency = "USD"
        spx_contract.exchange = "CBOE"
        
        # Request 1 day of 1-minute bars (390 bars in a trading day)
        self.reqHistoricalData(
            self.spx_1min_req_id,
            spx_contract,
            "",  # End date/time (empty = now)
            "1 D",  # Duration
            "1 min",  # Bar size
            "TRADES",  # What to show
            1,  # Use RTH (Regular Trading Hours)
            1,  # Format date as string
            True,  # Keep up to date (streaming)
            []  # Chart options
        )
        self.log_message(f"Requested {UNDERLYING_SYMBOL} 1-min history for Z-Score (reqId: {self.spx_1min_req_id})", "INFO")
    
    def update_spx_price_display(self):
        """Update the underlying price display in the GUI"""
        if self.spx_price > 0:
            self.spx_price_label.config(text=f"{UNDERLYING_SYMBOL}: {self.spx_price:.2f}")
            # Also update status bar if it exists
            if hasattr(self, 'spx_label'):
                self.spx_label.config(text=f"SPX: {self.spx_price:.2f}")
    
    # ========================================================================
    # OPTION CHAIN MANAGEMENT
    # ========================================================================
    
    def calculate_expiry_date(self, offset: int) -> str:
        """
        Calculate expiration date based on offset.
        offset = 0: Today (0DTE) - every weekday
        offset = 1: Next trading day expiration
        offset = 2: Day after next expiration, etc.
        
        SPX options now have DAILY expirations (Monday-Friday).
        """
        from datetime import timedelta
        
        current_date = datetime.now()
        target_date = current_date
        
        # SPX has daily expirations Monday-Friday
        # 0 = Monday, 1 = Tuesday, 2 = Wednesday, 3 = Thursday, 4 = Friday
        expiry_days = [0, 1, 2, 3, 4]
        
        days_checked = 0
        expirations_found = 0
        
        # Find the Nth expiration (where N = offset)
        # If offset=0 and today is an expiry day, return today
        while True:
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
    
    def get_contract_key(self, contract: Contract) -> str:
        """
        Generate standardized contract key for tracking positions and market data.
        
        Format: SYMBOL_STRIKE_RIGHT_YYYYMMDD
        - Strike: Integer format (no decimals for SPX, but keeps decimals for other symbols if present)
        - Expiry: Full expiration date (YYYYMMDD)
        
        Examples:
        - SPX_6740_C_20251020 (SPX Call at 6740, expiring Oct 20, 2025)
        - SPX_6745_P_20251020 (SPX Put at 6745, expiring Oct 20, 2025)
        - AAPL_150.5_C_20251120 (AAPL Call at 150.50, expiring Nov 20, 2025)
        """
        # Format strike: remove unnecessary decimals (.0 becomes empty)
        strike = contract.strike
        if strike == int(strike):
            strike_str = str(int(strike))  # Remove .0 for whole numbers
        else:
            strike_str = str(strike)  # Keep decimals for fractional strikes
        
        # Get YYYYMMDD from expiration (full 8-character date)
        expiry_yyyymmdd = contract.lastTradeDateOrContractMonth[:8] if contract.lastTradeDateOrContractMonth else "00000000"
        
        return f"{contract.symbol}_{strike_str}_{contract.right}_{expiry_yyyymmdd}"
    
    def create_option_contract(self, strike: float, right: str, symbol: Optional[str] = None, 
                              trading_class: Optional[str] = None) -> Contract:
        """
        Create an option contract with current expiration.
        
        Args:
            strike: Strike price
            right: "C" for call or "P" for put
            symbol: Underlying symbol (uses TRADING_SYMBOL if not specified)
            trading_class: Trading class (uses TRADING_CLASS if not specified)
        
        Returns:
            Contract object ready for IBKR API calls
        
        NOTE: For SPX/XSP options, tradingClass must match the symbol
        """
        # Use configured symbol if not specified
        if symbol is None:
            symbol = TRADING_SYMBOL
        if trading_class is None:
            trading_class = TRADING_CLASS
        
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "OPT"
        contract.currency = "USD"
        contract.exchange = "SMART"
        contract.tradingClass = trading_class
        contract.strike = strike
        contract.right = right  # "C" or "P"
        contract.lastTradeDateOrContractMonth = self.current_expiry
        contract.multiplier = "100"
        
        # DIAGNOSTIC: Log contract creation to verify expiration
        if not hasattr(self, '_contract_creation_logged'):
            self._contract_creation_logged = True
            self.log_message(f"Creating {symbol} contracts with expiration: {self.current_expiry}", "INFO")
        
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
            call_contract = self.create_option_contract(strike, "C")
            put_contract = self.create_option_contract(strike, "P")
            
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
                    call_contract = self.create_option_contract(strike, "C")
                    put_contract = self.create_option_contract(strike, "P")
                    
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
        Creates tksheet rows with calls on left and puts on right (IBKR style).
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
        self.strike_to_row.clear()
        
        # Clear sheet display
        if hasattr(self, 'option_sheet'):
            self.option_sheet.set_sheet_data([[]])
        
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
        
        # Prepare sheet data (2D list)
        sheet_data = []
        
        # Subscribe and create display rows
        for row_idx, strike in enumerate(sorted_strikes):
            strike_data = strikes_dict[strike]
            
            # Subscribe to call
            if strike_data['call']:
                req_id = self.next_req_id
                self.next_req_id += 1
                
                contract_key = self.get_contract_key(strike_data['call_contract'])
                self.market_data_map[req_id] = contract_key
                
                self.market_data[contract_key] = {
                    'contract': strike_data['call_contract'],
                    'right': 'C',
                    'strike': strike,
                    'bid': 0, 'ask': 0, 'last': 0, 'prev_close': 0, 'volume': 0,
                    'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0,
                    'row_index': row_idx  # Store row index instead of tree_item
                }
                
                self.subscribed_contracts.append(('C', strike, strike_data['call_contract']))
                # Request market data with MODEL_OPTION_COMPUTATION (tick type 13)
                # Empty string "" triggers automatic model-based greek calculations
                # These greeks work without Last price by using bid/ask mid-point
                self.reqMktData(req_id, strike_data['call_contract'], "", False, False, [])
            
            # Subscribe to put
            if strike_data['put']:
                req_id = self.next_req_id
                self.next_req_id += 1
                
                contract_key = self.get_contract_key(strike_data['put_contract'])
                self.market_data_map[req_id] = contract_key
                
                self.market_data[contract_key] = {
                    'contract': strike_data['put_contract'],
                    'right': 'P',
                    'strike': strike,
                    'bid': 0, 'ask': 0, 'last': 0, 'prev_close': 0, 'volume': 0,
                    'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0,
                    'row_index': row_idx  # Store row index instead of tree_item
                }
                
                self.subscribed_contracts.append(('P', strike, strike_data['put_contract']))
                # Request market data with MODEL_OPTION_COMPUTATION (tick type 13)
                # Empty string "" triggers automatic model-based greek calculations
                # These greeks work without Last price by using bid/ask mid-point
                self.reqMktData(req_id, strike_data['put_contract'], "", False, False, [])
            
            # Create sheet row with call on left, strike in center, put on right
            # Format: C_Bid, C_Ask, C_Last, C_CHANGE%, C_Vol, C_Gamma, C_Vega, C_Theta, C_Delta, C_IV, Strike, P_IV, P_Delta, P_Theta, P_Vega, P_Gamma, P_Vol, P_CHANGE%, P_Last, P_Ask, P_Bid
            row_data = [
                "0.00", "0.00", "0.00", "0.00%", "0", "0.00", "0.00", "0.00", "0.00", "0.00",  # Call data (10 columns)
                f"{strike:.2f}",  # Strike (1 column)
                "0.00", "0.00", "0.00", "0.00", "0.00", "0", "0.00%", "0.00", "0.00", "0.00"  # Put data (10 columns - added IV)
            ]
            
            sheet_data.append(row_data)
            
            # Map strike to row index
            self.strike_to_row[strike] = row_idx
        
        # Populate sheet with data
        if hasattr(self, 'option_sheet') and sheet_data:
            self.option_sheet.set_sheet_data(sheet_data)
        
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
        Update the option chain display with latest market data using tksheet.
        Updates cells with call data on left and put data on right (IBKR TWS style).
        Applies cell-level color coding for ITM/OTM and positive/negative values.
        """
        if not self.root or not hasattr(self, 'option_sheet'):
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
            
            # Helper function to get cell color based on value (for greeks/prices)
            def get_value_color(value):
                """Return text color based on positive/negative value"""
                try:
                    if value is None or value == 0:
                        return None  # Use default
                    num_val = float(value)
                    if num_val > 0:
                        return self.tws_colors['positive']  # Green
                    elif num_val < 0:
                        return self.tws_colors['negative']  # Red
                except (ValueError, TypeError):
                    pass
                return None  # Default
            
            # Helper function to get ITM/OTM background color
            def get_row_bg_color(strike):
                """Determine background color based on ITM/OTM status"""
                if self.spx_price <= 0:
                    return self.tws_colors['bg']  # Default black
                
                # ATM tolerance (within 0.5% of SPX price)
                atm_tolerance = self.spx_price * 0.005
                strike_distance = abs(strike - self.spx_price)
                
                if strike_distance <= atm_tolerance:
                    return self.tws_colors['strike_bg']  # ATM: slightly lighter
                elif strike < self.spx_price:
                    # Calls ITM when strike < spot
                    if (self.spx_price - strike) > (self.spx_price * 0.02):
                        return self.tws_colors['call_itm_deep']  # Deep ITM
                    else:
                        return self.tws_colors['call_itm']  # ITM
                else:
                    # Puts ITM when strike > spot
                    if (strike - self.spx_price) > (self.spx_price * 0.02):
                        return self.tws_colors['put_itm_deep']  # Deep ITM
                    else:
                        return self.tws_colors['put_itm']  # ITM
            
            # Batch update cells for performance
            cell_updates = []  # (row, col, value)
            cell_formats = []  # (row, col, fg_color, bg_color)
            
            # Process each strike row
            for strike, row_idx in self.strike_to_row.items():
                # Get call and put data for this strike
                # Contract keys now include expiration date: SPX_{strike}_{C/P}_{YYYYMMDD}
                # Find matching contracts by strike and right
                call_data = {}
                put_data = {}
                
                # Search for matching contracts in market_data
                strike_int = int(strike) if strike == int(strike) else strike
                for key, data in self.market_data.items():
                    if data.get('strike') == strike:
                        if data.get('right') == 'C':
                            call_data = data
                        elif data.get('right') == 'P':
                            put_data = data
                
                # Determine row background based on ITM/OTM status
                row_bg = get_row_bg_color(strike)
                
                # Calculate CHANGE % for call
                call_change_pct = 0.0
                call_change_str = "0.00%"
                if call_data.get('last', 0) > 0 and call_data.get('prev_close', 0) > 0:
                    call_change_pct = ((call_data['last'] - call_data['prev_close']) / call_data['prev_close']) * 100
                    call_change_str = f"{call_change_pct:+.2f}%"  # Show sign (+/-)
                
                # Calculate CHANGE % for put
                put_change_pct = 0.0
                put_change_str = "0.00%"
                if put_data.get('last', 0) > 0 and put_data.get('prev_close', 0) > 0:
                    put_change_pct = ((put_data['last'] - put_data['prev_close']) / put_data['prev_close']) * 100
                    put_change_str = f"{put_change_pct:+.2f}%"  # Show sign (+/-)
                
                # Self-compute greeks using Mid price if greeks are missing
                # Calculate time to expiry
                try:
                    expiry_str = self.current_expiry  # Format: YYYYMMDD
                    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
                    now = datetime.now()
                    # Calculate time to expiry in years
                    time_to_expiry = (expiry_date - now).total_seconds() / (365.25 * 24 * 3600)
                    time_to_expiry = max(0.0001, time_to_expiry)  # Minimum 1 hour to avoid division by zero
                except:
                    time_to_expiry = 0.00274  # Default to 1 day if parsing fails
                
                # Compute call greeks if missing and we have bid/ask
                if call_data and (not call_data.get('delta') or call_data.get('delta') == 0):
                    call_bid = call_data.get('bid', 0)
                    call_ask = call_data.get('ask', 0)
                    if call_bid > 0 and call_ask > 0 and self.spx_price > 0:
                        call_mid = (call_bid + call_ask) / 2.0
                        # Estimate IV from option price (simplified - use 20% if no better estimate)
                        estimated_iv = call_data.get('iv', 0.20)
                        if estimated_iv == 0:
                            estimated_iv = 0.20
                        
                        # Calculate greeks
                        greeks = calculate_greeks('C', self.spx_price, strike, time_to_expiry, estimated_iv)
                        call_data['delta'] = greeks['delta']
                        call_data['gamma'] = greeks['gamma']
                        call_data['theta'] = greeks['theta']
                        call_data['vega'] = greeks['vega']
                        if call_data.get('iv', 0) == 0:
                            call_data['iv'] = greeks['iv']
                
                # Compute put greeks if missing and we have bid/ask
                if put_data and (not put_data.get('delta') or put_data.get('delta') == 0):
                    put_bid = put_data.get('bid', 0)
                    put_ask = put_data.get('ask', 0)
                    if put_bid > 0 and put_ask > 0 and self.spx_price > 0:
                        put_mid = (put_bid + put_ask) / 2.0
                        # Estimate IV from option price (simplified - use 20% if no better estimate)
                        estimated_iv = put_data.get('iv', 0.20)
                        if estimated_iv == 0:
                            estimated_iv = 0.20
                        
                        # Calculate greeks
                        greeks = calculate_greeks('P', self.spx_price, strike, time_to_expiry, estimated_iv)
                        put_data['delta'] = greeks['delta']
                        put_data['gamma'] = greeks['gamma']
                        put_data['theta'] = greeks['theta']
                        put_data['vega'] = greeks['vega']
                        if put_data.get('iv', 0) == 0:
                            put_data['iv'] = greeks['iv']
                
                # Build row values
                # Call columns (0-9): Imp Vol, Delta, Theta, Vega, Gamma, Volume, CHANGE%, Last, Ask, Bid (REVERSED)
                call_values = [
                    safe_format(call_data.get('iv'), ".2f"),
                    safe_format(call_data.get('delta'), ".4f"),
                    safe_format(call_data.get('theta'), ".4f"),
                    safe_format(call_data.get('vega'), ".4f"),
                    safe_format(call_data.get('gamma'), ".4f"),
                    safe_format(call_data.get('volume'), "int"),
                    call_change_str,  # CHANGE % at index 6
                    safe_format(call_data.get('last'), ".2f"),
                    safe_format(call_data.get('ask'), ".2f"),
                    safe_format(call_data.get('bid'), ".2f")
                ]
                
                # Strike column (10)
                strike_value = f"{strike:.2f}"
                
                # Put columns (11-20): Bid, Ask, Last, CHANGE%, Volume, Gamma, Vega, Theta, Delta, IV (REVERSED)
                put_values = [
                    safe_format(put_data.get('bid'), ".2f"),
                    safe_format(put_data.get('ask'), ".2f"),
                    safe_format(put_data.get('last'), ".2f"),
                    put_change_str,  # CHANGE % at index 3 (column 14)
                    safe_format(put_data.get('volume'), "int"),
                    safe_format(put_data.get('gamma'), ".4f"),
                    safe_format(put_data.get('vega'), ".4f"),
                    safe_format(put_data.get('theta'), ".4f"),
                    safe_format(put_data.get('delta'), ".4f"),
                    safe_format(put_data.get('iv'), ".2f")
                ]
                
                # Update cells with values
                # Call columns mapping: 0=iv, 1=delta, 2=theta, 3=vega, 4=gamma, 5=volume, 6=change%, 7=last, 8=ask, 9=bid
                greek_keys_call = ['iv', 'delta', 'theta', 'vega', 'gamma', 'volume', 'change%', 'last', 'ask', 'bid']
                
                for col_idx, val in enumerate(call_values):
                    cell_updates.append((row_idx, col_idx, val))
                    
                    # CHANGE % column gets green/red background with WHITE text
                    if col_idx == 6:  # CHANGE % column (now at index 6)
                        if call_change_pct > 0:
                            cell_bg = self.tws_colors['positive_bg']  # Green background
                            fg_color = self.tws_colors['fg']  # WHITE text
                        elif call_change_pct < 0:
                            cell_bg = self.tws_colors['negative_bg']  # Red background
                            fg_color = self.tws_colors['fg']  # WHITE text
                        else:
                            cell_bg = self.tws_colors['bg']  # Black
                            fg_color = self.tws_colors['fg']  # White
                        cell_formats.append((row_idx, col_idx, fg_color, cell_bg))
                    # All other cells: pure black background with WHITE text (no coloring for greeks)
                    else:
                        cell_formats.append((row_idx, col_idx, self.tws_colors['fg'], self.tws_colors['bg']))
                
                # Strike column: Dynamic coloring based on ATM position
                # Strikes above SPX = current blue (#2a4a6a)
                # Strikes below SPX = darker blue (#1a2a3a)
                if strike >= self.spx_price:
                    strike_bg = self.tws_colors['strike_bg']  # Above ATM: current blue
                else:
                    strike_bg = '#1a2a3a'  # Below ATM: darker blue
                
                cell_updates.append((row_idx, 10, strike_value))
                cell_formats.append((row_idx, 10, self.tws_colors['strike_fg'], strike_bg))
                
                # Put columns mapping: 0=bid, 1=ask, 2=last, 3=change%, 4=volume, 5=gamma, 6=vega, 7=theta, 8=delta, 9=iv
                greek_keys_put = ['bid', 'ask', 'last', 'change%', 'volume', 'gamma', 'vega', 'theta', 'delta', 'iv']
                
                for col_offset, val in enumerate(put_values):
                    col_idx = 11 + col_offset
                    cell_updates.append((row_idx, col_idx, val))
                    
                    # CHANGE % column gets green/red background with WHITE text
                    if col_offset == 3:  # CHANGE % column (now at index 3, column 14)
                        if put_change_pct > 0:
                            cell_bg = self.tws_colors['positive_bg']  # Green background
                            fg_color = self.tws_colors['fg']  # WHITE text
                        elif put_change_pct < 0:
                            cell_bg = self.tws_colors['negative_bg']  # Red background
                            fg_color = self.tws_colors['fg']  # WHITE text
                        else:
                            cell_bg = self.tws_colors['bg']  # Black
                            fg_color = self.tws_colors['fg']  # White
                        cell_formats.append((row_idx, col_idx, fg_color, cell_bg))
                    # All other cells: pure black background with WHITE text (no coloring for greeks)
                    else:
                        cell_formats.append((row_idx, col_idx, self.tws_colors['fg'], self.tws_colors['bg']))
            
            # Apply all cell updates in batch
            for row, col, value in cell_updates:
                try:
                    self.option_sheet.set_cell_data(row, col, value, redraw=False)
                except:
                    pass  # Skip if row/col out of range
            
            # Apply all cell formatting in batch
            for row, col, fg, bg in cell_formats:
                try:
                    if fg:
                        self.option_sheet.highlight_cells(row, col, fg=fg, bg=bg, redraw=False)
                    elif bg:
                        self.option_sheet.highlight_cells(row, col, bg=bg, redraw=False)
                except:
                    pass  # Skip if row/col out of range
            
            # Redraw once after all updates
            self.option_sheet.redraw()
            
            # Schedule next update
            self.root.after(500, self.update_option_chain_display)
            
        except Exception as e:
            self.log_message(f"Error updating option chain display: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            # Continue updating even if there was an error
            self.root.after(500, self.update_option_chain_display)
    
    # ========================================================================
    # TRADING LOGIC
    # ========================================================================
    
    def check_trade_time(self):
        """
        Check if it's time to enter a new straddle based on configured frequency.
        Only executes during regular market hours (8:30 AM - 3:15 PM ET).
        """
        if not self.root:
            return
        
        # Only check if straddle strategy is enabled
        if self.straddle_enabled:
            now = datetime.now()
            
            # Check if market is open
            if not self.is_market_open():
                # Market closed - update status
                if hasattr(self, 'straddle_next_label'):
                    self.straddle_next_label.config(
                        text="Market Closed",
                        foreground="#FF0000"
                    )
                # Schedule next check
                self.root.after(1000, self.check_trade_time)
                return
            
            # Market is open - check if it's time to trade
            if self.last_straddle_time is None:
                # Should not happen (timer set in set_straddle_enabled)
                # But if it does, start timer now
                self.last_straddle_time = now
            else:
                # Check if enough time has elapsed
                elapsed_minutes = (now - self.last_straddle_time).total_seconds() / 60
                
                if elapsed_minutes >= self.straddle_frequency_minutes:
                    self.log_message(
                        f"Straddle timer triggered ({elapsed_minutes:.1f} min elapsed, "
                        f"frequency: {self.straddle_frequency_minutes} min)", 
                        "INFO"
                    )
                    self.enter_straddle()
                    self.last_straddle_time = now
                else:
                    # Update countdown display
                    remaining = self.straddle_frequency_minutes - elapsed_minutes
                    next_time = now + timedelta(minutes=remaining)
                    if hasattr(self, 'straddle_next_label'):
                        self.straddle_next_label.config(
                            text=f"Next: {next_time.strftime('%H:%M')}",
                            foreground="#00BFFF"
                        )
        
        # Schedule next check (every second for smooth countdown)
        self.root.after(1000, self.check_trade_time)
    
    def enter_straddle(self):
        """
        Enter a long straddle using the same logic as Manual Buy Call/Put buttons.
        Uses Master Settings for target delta and position sizing.
        
        This is the STRADDLE STRATEGY function - only runs when straddle_enabled = True.
        """
        # Check if straddle strategy is enabled
        if not self.straddle_enabled:
            self.log_message("Straddle strategy is disabled - skipping entry", "INFO")
            return
        
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("Cannot enter straddle: Not connected to IBKR", "WARNING")
            return
        
        if not self.data_server_ok:
            self.log_message("Cannot enter straddle: Data server not ready", "WARNING")
            return
        
        # Check if market is open
        if not self.is_market_open():
            self.log_message("Cannot enter straddle: Market is closed (Regular hours: 8:30 AM - 3:15 PM ET)", "WARNING")
            return
        
        self.log_message("=" * 60, "INFO")
        self.log_message("🔔 STRADDLE STRATEGY ENTRY TRIGGERED 🔔", "SUCCESS")
        self.log_message("=" * 60, "INFO")
        
        # This emulates clicking BUY CALL and BUY PUT buttons
        # Uses same Master Settings (target delta, position size mode, etc.)
        
        self.log_message("Entering CALL leg...", "INFO")
        self.manual_buy_call()
        
        # Small delay between legs to avoid overwhelming the system
        if self.root:
            self.root.after(500, lambda: self.log_message("Entering PUT leg...", "INFO"))
            self.root.after(1000, self.manual_buy_put)
        
        self.log_message("=" * 60, "INFO")
        self.log_message("=" * 60, "INFO")
    
    def place_order(self, contract_key: str, contract: Contract, action: str, 
                   quantity: int, limit_price: float, 
                   enable_chasing: bool = False, stop_price: float | None = None) -> int | None:
        """
        Universal order placement function - handles all order types
        
        Args:
            contract_key: Standardized contract identifier (e.g., "SPX_5800.0_C_20251020")
            contract: IBKR Contract object with all fields populated
            action: "BUY" or "SELL"
            quantity: Number of contracts
            limit_price: Limit price per contract
            enable_chasing: If True, enables mid-price chasing for manual orders
            stop_price: Optional stop price for stop-limit orders
        
        Returns:
            order_id: IBKR order ID for tracking
        
        Order Types:
            - Limit Order: stop_price=None, enable_chasing=False (automated straddles)
            - Stop-Limit Order: stop_price=value (exit orders with stops)
            - Manual Order with Chasing: enable_chasing=True (manual trading mode)
        """
        # CRITICAL: Check connection state AND data server readiness
        if self.connection_state != ConnectionState.CONNECTED:
            self.log_message("✗ Cannot place order: Not connected to IBKR", "ERROR")
            return None
        
        if not self.data_server_ok:
            self.log_message("✗ Cannot place order: Data server not ready (waiting for 2104/2106 message)", "ERROR")
            return None
        
        # Validate contract fields
        if not contract or not contract.symbol or not contract.secType:
            self.log_message(f"✗ ERROR: Invalid contract - missing symbol or secType", "ERROR")
            return None
        
        if not contract.lastTradeDateOrContractMonth:
            self.log_message(f"✗ ERROR: Invalid contract - missing expiration date", "ERROR")
            return None
        
        if not contract.strike or contract.strike <= 0:
            self.log_message(f"✗ ERROR: Invalid contract - missing or invalid strike", "ERROR")
            return None
        
        if not contract.right or contract.right not in ["C", "P"]:
            self.log_message(f"✗ ERROR: Invalid contract - missing or invalid right (C/P)", "ERROR")
            return None
        
        # Ensure required contract fields are set
        if not contract.exchange:
            contract.exchange = "SMART"
        if not contract.currency:
            contract.currency = "USD"
        if not contract.multiplier:
            contract.multiplier = "100"
        
        # CRITICAL: Set tradingClass for 0DTE options
        if not contract.tradingClass:
            contract.tradingClass = TRADING_CLASS
            self.log_message(f"Set tradingClass = {TRADING_CLASS} for {TRADING_SYMBOL} contract", "INFO")
        
        # DIAGNOSTIC: Validate contract has ALL required fields
        missing_fields = []
        if not contract.symbol: missing_fields.append("symbol")
        if not contract.secType: missing_fields.append("secType")
        if not contract.exchange: missing_fields.append("exchange")
        if not contract.currency: missing_fields.append("currency")
        if not contract.multiplier: missing_fields.append("multiplier")
        if not contract.lastTradeDateOrContractMonth: missing_fields.append("lastTradeDateOrContractMonth")
        if not contract.strike or contract.strike <= 0: missing_fields.append("strike")
        if not contract.right: missing_fields.append("right")
        
        if missing_fields:
            self.log_message(f"❌ CONTRACT VALIDATION FAILED! Missing fields: {', '.join(missing_fields)}", "ERROR")
            return None
        
        self.log_message(f"✓ Contract validation passed - all required fields present", "INFO")
        
        # Create a clean order object to avoid sending invalid default values
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = "LMT"  # Default to LMT
        order.lmtPrice = limit_price
        order.tif = "DAY"
        order.transmit = True
        
        # CRITICAL: Set problematic fields to proper values
        # These fields have invalid defaults that cause silent rejection
        order.eTradeOnly = False  # NOT for E*TRADE only
        order.firmQuoteOnly = False  # Allow regular market quotes
        order.auxPrice = UNSET_DOUBLE  # Clear auxPrice for LMT orders
        order.minQty = UNSET_INTEGER  # No minimum quantity requirement
        
        # Set account if available
        if self.account:
            order.account = self.account
        
        # Set order type based on parameters
        if stop_price is not None:
            order.orderType = "STP LMT"
            order.auxPrice = stop_price
            order_type_display = f"STP LMT (Stop: ${stop_price:.2f}, Limit: ${limit_price:.2f})"
        else:
            # Simple LMT order - don't set auxPrice at all (let IBKR use default)
            order.orderType = "LMT"
            order_type_display = f"LMT @ ${limit_price:.2f}"
        
        # Get order ID
        order_id = self.next_order_id
        self.next_order_id += 1
        
        # Log order details
        self.log_message(f"=== PLACING ORDER #{order_id} ===", "INFO")
        self.log_message(f"Contract: {contract.symbol} {contract.strike}{contract.right} {contract.lastTradeDateOrContractMonth}", "INFO")
        self.log_message(f"Order: {action} {quantity} {order_type_display}", "INFO")
        self.log_message(f"TradingClass: {contract.tradingClass if contract.tradingClass else 'None'}", "INFO")
        self.log_message(f"Exchange: {contract.exchange}", "INFO")
        self.log_message(f"Account: {order.account if order.account else 'None'}", "INFO")
        self.log_message(f"Mid-Price Chasing: {'ENABLED' if enable_chasing else 'DISABLED'}", "INFO")
        
        # ========================================================================
        # CRITICAL: Detailed object logging before placing order
        # ========================================================================
        self.log_message("-" * 20 + " CONTRACT DETAILS " + "-" * 20, "INFO")
        for key, value in vars(contract).items():
            if value:  # Only log populated fields
                self.log_message(f"  - {key}: {value}", "INFO")
        
        self.log_message("-" * 20 + " ORDER DETAILS " + "-" * 20, "INFO")
        for key, value in vars(order).items():
            # Log all fields, even if default, to be thorough
            self.log_message(f"  - {key}: {value}", "INFO")
        self.log_message("-" * 58, "INFO")
        # ========================================================================
        
        # Track order for callbacks
        self.pending_orders[order_id] = (contract_key, action, quantity)
        
        # If chasing enabled, track for price monitoring
        if enable_chasing:
            self.manual_orders[order_id] = {
                'contract_key': contract_key,
                'contract': contract,
                'action': action,
                'quantity': quantity,
                'initial_mid': limit_price,
                'last_mid': limit_price,
                'attempts': 1,
                'timestamp': datetime.now(),
                'order': order
            }
        
        # Place the order via IBKR API
        try:
            self.placeOrder(order_id, contract, order)
            self.log_message(f"✓ Order #{order_id} placed successfully", "SUCCESS")
                
        except Exception as e:
            self.log_message(f"✗ EXCEPTION during placeOrder(): {e}", "ERROR")
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
            # Clean up tracking
            if order_id in self.manual_orders:
                del self.manual_orders[order_id]
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
            return None
        
        # Add to order tree display
        self.add_order_to_tree(order_id, contract, action, quantity, limit_price, "Submitted")
        
        # Start monitoring if chasing enabled
        if enable_chasing and self.root:
            self.root.after(self.manual_order_update_interval, self.update_manual_orders)
        
        return order_id
    
    def update_position_on_fill(self, contract_key: str, action: str, 
                               quantity: int, fill_price: float):
        """Update position when order is filled"""
        if contract_key not in self.positions:
            # New position - fill_price is already per-option price
            data = self.market_data[contract_key]
            self.positions[contract_key] = {
                'contract': data['contract'],
                'position': quantity if action == "BUY" else -quantity,
                'avgCost': fill_price,  # Per-option price (not x100)
                'currentPrice': fill_price,
                'pnl': 0,
                'entryTime': datetime.now()
            }
            
            # Subscribe to market data for real-time updates
            if contract_key not in self.market_data:
                self.log_message(f"Subscribing to market data for new position: {contract_key}", "INFO")
                
                # Create market data entry and subscribe
                req_id = self.next_req_id
                self.next_req_id += 1
                
                # Ensure contract has required fields for market data subscription
                contract_obj = data['contract']
                if not contract_obj.exchange:
                    contract_obj.exchange = "SMART"
                if not contract_obj.tradingClass and contract_obj.symbol == "SPX":
                    contract_obj.tradingClass = "SPXW"
                
                self.market_data_map[req_id] = contract_key
                self.market_data[contract_key] = {
                    'contract': contract_obj,
                    'right': contract_obj.right,
                    'strike': contract_obj.strike,
                    'bid': 0, 'ask': 0, 'last': 0, 'volume': 0,
                    'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'iv': 0
                }
                
                self.reqMktData(req_id, contract_obj, "", False, False, [])
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
    
    def update_position_pnl(self, contract_key: str, current_price: float | None = None):
        """
        Update position PnL with current mid-price
        If current_price not provided, calculate from bid/ask
        """
        if contract_key in self.positions:
            pos = self.positions[contract_key]
            
            # Get current mid-price from market data
            if current_price is None and contract_key in self.market_data:
                data = self.market_data[contract_key]
                bid = data.get('bid', 0)
                ask = data.get('ask', 0)
                if bid > 0 and ask > 0:
                    current_price = (bid + ask) / 2
                    # DEBUG: Log mid-price calculation
                    # self.log_message(f"Mid price for {contract_key}: ${current_price:.2f} (bid: ${bid:.2f}, ask: ${ask:.2f})", "INFO")
                else:
                    current_price = data.get('last', pos['avgCost'])
                    # DEBUG: Log fallback to last price
                    # self.log_message(f"Using last price for {contract_key}: ${current_price:.2f} (no bid/ask)", "WARNING")
            elif current_price is None:
                # Market data not found - use last known price silently
                # (Don't spam warnings for positions with different expirations than loaded chain)
                current_price = pos.get('currentPrice', pos['avgCost'])
            
            if current_price:
                pos['currentPrice'] = current_price
                # P&L = (Current - Entry) × Quantity × Multiplier
                pos['pnl'] = (current_price - pos['avgCost']) * pos['position'] * 100
    
    # ========================================================================
    # Z-SCORE STRATEGY (Gamma-Snap HFS v3.0)
    # ========================================================================
    # Automated trading strategy based on SPX mean reversion
    # Entry: Z-Score crosses threshold (±1.5)
    # Exit: Price touches 9-EMA (profit target) or time stop (30 min)
    # ========================================================================
    
    def calculate_indicators(self):
        """Calculate Z-Score and 9-EMA from SPX 1-min bars"""
        if len(self.spx_1min_bars) < self.z_score_period:
            return
        
        # Convert to DataFrame for easier calculation
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
        
        # Update GUI display if method exists
        if hasattr(self, 'update_indicator_display'):
            self.update_indicator_display()
    
    def run_gamma_snap_strategy(self):
        """Main strategy loop - runs every 5 seconds"""
        # Schedule next run
        if self.root:
            self.root.after(5000, self.run_gamma_snap_strategy)
        
        # Check if strategy is enabled
        if not self.strategy_enabled:
            if hasattr(self, 'strategy_status_var'):
                self.strategy_status_var.set("Status: INACTIVE")
            return
        
        # Check trading hours (9:30 AM - 3:00 PM ET)
        now = datetime.now()
        if not (now.hour >= 9 and now.minute >= 30 and now.hour < 15):
            if hasattr(self, 'strategy_status_var'):
                self.strategy_status_var.set("Status: Outside Trading Hours")
            return
        
        # Check VIX filter
        if self.vix_price > self.vix_threshold:
            if hasattr(self, 'strategy_status_var'):
                self.strategy_status_var.set(f"Status: PAUSED (VIX High: {self.vix_price:.2f})")
            return
        
        # Need enough data for Z-Score calculation
        if len(self.spx_1min_bars) < self.z_score_period + 1:
            if hasattr(self, 'strategy_status_var'):
                self.strategy_status_var.set("Status: Waiting for Data...")
            return
        
        # If we're in a trade, check exit conditions
        if self.active_trade_info:
            self.check_trade_exit()
            return
        
        # Otherwise, scan for entry signals
        if hasattr(self, 'strategy_status_var'):
            self.strategy_status_var.set("Status: SCANNING...")
        
        # Get last two Z-Scores for crossover logic
        bar_data = [{'time': b['time'], 'close': b['close']} for b in self.spx_1min_bars]
        df = pd.DataFrame(bar_data).set_index('time')
        sma = df['close'].rolling(window=self.z_score_period).mean()
        std = df['close'].rolling(window=self.z_score_period).std()
        z_scores = (df['close'] - sma) / std
        
        if len(z_scores) < 2:
            return
        
        last_z_score = z_scores.iloc[-1]
        prev_z_score = z_scores.iloc[-2]
        
        # Long Entry: Z-Score crosses UP from below the threshold
        if (prev_z_score < -self.z_score_threshold and 
            last_z_score > -self.z_score_threshold):
            self.log_message(
                f"STRATEGY: LONG signal triggered (Z-Score: {last_z_score:.2f})",
                "SUCCESS"
            )
            self.enter_trade('LONG')
        
        # Short Entry: Z-Score crosses DOWN from above the threshold
        elif (prev_z_score > self.z_score_threshold and 
              last_z_score < self.z_score_threshold):
            self.log_message(
                f"STRATEGY: SHORT signal triggered (Z-Score: {last_z_score:.2f})",
                "SUCCESS"
            )
            self.enter_trade('SHORT')
    
    def enter_trade(self, direction: str):
        """
        Enter a trade based on strategy signal.
        Uses Master Settings for delta targeting and position sizing.
        """
        self.log_message("=" * 60, "INFO")
        self.log_message(f"🎯 GAMMA-TRAP STRATEGY ENTRY ({direction}) 🎯", "SUCCESS")
        self.log_message("=" * 60, "INFO")
        
        # Determine option type based on direction
        option_type = 'C' if direction == 'LONG' else 'P'
        
        # Get target delta from Master Settings
        try:
            target_delta = float(self.target_delta_entry.get())
            if target_delta <= 0 or target_delta > 100:
                raise ValueError("Target delta must be between 0 and 100")
        except (ValueError, AttributeError) as e:
            self.log_message(f"Invalid target delta, using default 30: {e}", "WARNING")
            target_delta = 30.0
        
        self.log_message(f"Strategy Signal: {direction} - Target Delta: {target_delta}", "INFO")
        
        # Find option by delta using shared function
        result = self.find_option_by_delta(option_type, target_delta)
        if not result:
            self.log_message(
                f"STRATEGY: Could not find suitable {option_type} option near {target_delta} delta",
                "WARNING"
            )
            return
        
        contract_key, contract, ask_price, actual_delta = result
        
        # Calculate quantity based on position sizing mode (from Master Settings)
        position_mode = self.position_size_mode.get()
        if position_mode == "fixed":
            # Use fixed quantity from Trade Qty field
            try:
                quantity = int(self.trade_qty_entry.get())
                if quantity <= 0:
                    raise ValueError("Quantity must be positive")
            except (ValueError, AttributeError) as e:
                self.log_message(f"Invalid trade quantity, using 1: {e}", "WARNING")
                quantity = 1
            self.log_message(f"Position sizing: Fixed quantity = {quantity} contracts", "INFO")
        else:  # calculated
            # Calculate quantity based on max risk / option price
            try:
                max_risk = float(self.max_risk_entry.get())
                if max_risk <= 0:
                    raise ValueError("Max risk must be positive")
            except (ValueError, AttributeError) as e:
                self.log_message(f"Invalid max risk, using default $500: {e}", "WARNING")
                max_risk = 500.0
            
            # Calculate: Max Risk / (Option Price * 100 multiplier)
            quantity = int(max_risk / ask_price)
            if quantity <= 0:
                quantity = 1  # Minimum 1 contract
            
            total_risk = quantity * ask_price
            self.log_message(f"Position sizing: Calculated by risk", "INFO")
            self.log_message(f"  Max Risk: ${max_risk:.2f}", "INFO")
            self.log_message(f"  Option Price: ${ask_price:.2f}", "INFO")
            self.log_message(f"  Quantity: {quantity} contracts", "INFO")
            self.log_message(f"  Actual Risk: ${total_risk:.2f}", "INFO")
        
        # Log contract details
        self.log_message(f"Contract found: {contract_key}", "INFO")
        self.log_message(f"Delta: {actual_delta:.1f} (Target: {target_delta})", "INFO")
        
        # Calculate mid-price for order
        limit_price = self.calculate_mid_price(contract_key)
        if not limit_price or limit_price <= 0:
            self.log_message("Cannot calculate mid price - using ask price", "WARNING")
            limit_price = ask_price
        
        # Place the order with mid-price chasing enabled
        order_id = self.place_order(
            contract_key,
            contract,
            "BUY",
            quantity,
            limit_price,
            enable_chasing=True  # Enable chasing for better fills
        )
        
        if order_id:
            self.active_trade_info = {
                'contract_key': contract_key,
                'direction': direction,
                'entry_time': datetime.now(),
                'order_id': order_id,
                'status': 'SUBMITTED',
                'profit_target_price': self.indicators['ema9'],
                'entry_price': None,
                'delta': actual_delta,
                'quantity': quantity  # Store quantity for exit
            }
            if hasattr(self, 'strategy_status_var'):
                self.strategy_status_var.set(f"Status: IN TRADE ({direction})")
            
            self.log_message(
                f"Gamma-Trap order #{order_id} submitted: {quantity} contracts @ ${limit_price:.2f}",
                "SUCCESS"
            )
        
        self.log_message("=" * 60, "INFO")
    
    def check_trade_exit(self):
        """Check exit conditions for active trade"""
        trade = self.active_trade_info
        
        # Wait for fill confirmation
        if not trade or trade.get('status') != 'FILLED':
            return
        
        # Get current SPX price
        current_price = self.spx_price
        if current_price == 0:
            return  # Wait for valid price
        
        # 1. Profit Target: Price touches the 9-EMA
        # Recalculate 9-EMA with most recent data
        self.calculate_indicators()
        profit_target = self.indicators['ema9']
        
        if ((trade['direction'] == 'LONG' and current_price >= profit_target) or
            (trade['direction'] == 'SHORT' and current_price <= profit_target)):
            self.log_message(
                f"STRATEGY: Profit target hit (SPX: ${current_price:.2f}, 9-EMA: ${profit_target:.2f})",
                "SUCCESS"
            )
            self.exit_trade("Profit Target")
            return
        
        # 2. Time Stop
        time_in_trade = (datetime.now() - trade['entry_time']).total_seconds() / 60
        if time_in_trade >= self.time_stop_minutes:
            self.log_message(
                f"STRATEGY: Time stop triggered ({time_in_trade:.1f} minutes)",
                "INFO"
            )
            self.exit_trade("Time Stop")
            return
    
    def exit_trade(self, reason: str):
        """Exit the active trade using stored quantity from entry"""
        trade = self.active_trade_info
        contract_key = trade['contract_key']
        
        # Get quantity from trade info (set during entry)
        quantity = trade.get('quantity', 1)  # Default to 1 if not found
        
        # Get market data
        option_data = self.market_data.get(contract_key)
        if not option_data:
            self.log_message(
                f"STRATEGY: Cannot exit, no market data for {contract_key}",
                "ERROR"
            )
            self.active_trade_info = {}
            return
        
        # Use mid-price with chasing (same logic as manual trading)
        limit_price = self.calculate_mid_price(contract_key)
        if limit_price <= 0:
            self.log_message(
                f"STRATEGY: Invalid mid-price, using $0.01",
                "WARNING"
            )
            limit_price = 0.01
        
        self.log_message(
            f"STRATEGY: Exiting {contract_key} ({quantity} contracts) due to: {reason} @ ${limit_price:.2f}",
            "INFO"
        )
        
        # Place exit order with mid-price chasing enabled
        order_id = self.place_order(
            contract_key,
            option_data['contract'],
            "SELL",
            quantity,  # Use stored quantity from entry
            limit_price,
            enable_chasing=True  # Enable chasing for better fills
        )
        
        if order_id:
            # Update trade info with exit details
            trade['exit_order_id'] = order_id
            trade['exit_reason'] = reason
            trade['exit_time'] = datetime.now()
            trade['exit_price'] = limit_price
            
            # Trade will be cleared when exit order fills (in orderStatus callback)
    
    # ========================================================================
    # MANUAL TRADING MODE - Implementation
    # ========================================================================
    # Intelligent order management system with mid-price chasing
    # Based on IBKR best practices for retail options trading
    # ========================================================================
    
    def round_to_spx_increment(self, price: float) -> float:
        """
        Round price to SPX options tick size:
        - Prices >= $3.00: Round to nearest $0.10
        - Prices < $3.00: Round to nearest $0.05
        
        Per CBOE SPX options rules and IBKR requirements
        """
        if price >= 3.00:
            # Round to nearest $0.10
            return round(price / 0.10) * 0.10
        else:
            # Round to nearest $0.05
            return round(price / 0.05) * 0.05
    
    def calculate_mid_price(self, contract_key: str) -> float:
        """
        Calculate mid-price from current bid/ask with proper rounding
        Returns 0 if no valid market data available
        """
        if contract_key not in self.market_data:
            return 0.0
        
        data = self.market_data[contract_key]
        bid = data.get('bid', 0)
        ask = data.get('ask', 0)
        
        if bid <= 0 or ask <= 0:
            return 0.0
        
        mid = (bid + ask) / 2.0
        return self.round_to_spx_increment(mid)
    
    def find_option_by_max_risk(self, option_type: str, max_risk_dollars: float) -> Optional[Tuple[str, Contract, float]]:
        """
        Find option closest to max risk without exceeding it
        
        Args:
            option_type: "C" for calls, "P" for puts
            max_risk_dollars: Maximum risk in dollars (e.g., 500 for $5.00 per contract)
        
        Returns:
            Tuple of (contract_key, contract, ask_price) or None if not found
        """
        try:
            # Convert max risk to per-contract price ($500 = $5.00)
            max_price = max_risk_dollars / 100.0
            
            best_option = None
            best_price = 0.0
            best_contract_key = None
            
            self.log_message(f"Scanning for {option_type} option with ask ≤ ${max_price:.2f}...", "INFO")
            
            for contract_key, data in self.market_data.items():
                # Safely check if this is the right option type
                if data.get('right') != option_type:
                    continue
                
                ask = data.get('ask', 0)
                
                # Must have valid ask price
                if ask <= 0 or ask > max_price:
                    continue
                
                # Find the option closest to max price (maximum value without exceeding)
                if ask > best_price:
                    best_price = ask
                    best_option = data.get('contract')
                    best_contract_key = contract_key
            
            if best_option and best_contract_key:
                self.log_message(
                    f"✓ Found {option_type} option: {best_contract_key} @ ${best_price:.2f} "
                    f"(Risk: ${best_price * 100:.2f})", 
                    "SUCCESS"
                )
                return (best_contract_key, best_option, best_price)
            else:
                self.log_message(
                    f"✗ No {option_type} options found with ask ≤ ${max_price:.2f}", 
                    "WARNING"
                )
                return None
        except Exception as e:
            self.log_message(f"Error in find_option_by_max_risk: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
            return None
    
    def find_option_by_delta(self, option_type: str, target_delta: float):
        """
        Find option contract closest to target delta
        
        Args:
            option_type: "C" for call or "P" for put
            target_delta: Target delta value (0-100, e.g., 30 for 30 delta)
        
        Returns:
            tuple: (contract_key, contract, ask_price, actual_delta) or None
        """
        try:
            if not self.market_data:
                self.log_message("No market data available", "WARNING")
                return None
            
            # Convert target delta to decimal (30 -> 0.30)
            target_delta_decimal = abs(target_delta / 100.0)
            
            best_delta_diff = float('inf')
            best_option = None
            best_contract_key = None
            best_price = 0
            best_delta = 0
            
            # Scan all options in market_data
            for contract_key, data in self.market_data.items():
                # Skip if wrong option type
                if option_type not in contract_key:
                    continue
                
                # Must have valid greeks
                delta = data.get('delta')
                if delta is None or delta == 0:
                    continue
                
                # For puts, delta is negative - use absolute value
                abs_delta = abs(delta)
                
                # Find closest to target delta
                delta_diff = abs(abs_delta - target_delta_decimal)
                
                if delta_diff < best_delta_diff:
                    ask = data.get('ask', 0)
                    if ask > 0:  # Must have valid ask price
                        best_delta_diff = delta_diff
                        best_option = data.get('contract')
                        best_contract_key = contract_key
                        best_price = ask
                        best_delta = abs_delta * 100  # Convert back to 0-100 scale
            
            if best_option and best_contract_key:
                self.log_message(
                    f"✓ Found {option_type} option: {best_contract_key} @ ${best_price:.2f} "
                    f"(Delta: {best_delta:.1f}, Target: {target_delta:.1f})", 
                    "SUCCESS"
                )
                return (best_contract_key, best_option, best_price, best_delta)
            else:
                self.log_message(
                    f"✗ No {option_type} options found with valid delta near {target_delta}", 
                    "WARNING"
                )
                return None
        except Exception as e:
            self.log_message(f"Error in find_option_by_delta: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
            return None
    
    def manual_buy_call(self):
        """
        Manual trading: Buy call option
        Finds contract by target delta and calculates position size based on mode
        """
        self.log_message("=" * 60, "INFO")
        self.log_message("🔔 BUY CALL BUTTON CLICKED 🔔", "SUCCESS")
        self.log_message("=" * 60, "INFO")
        
        try:
            if self.connection_state != ConnectionState.CONNECTED:
                self.log_message("❌ Cannot place order: Not connected to IBKR", "ERROR")
                messagebox.showerror("Not Connected", "Please connect to IBKR before trading")
                return
            
            if not self.data_server_ok:
                self.log_message("❌ Cannot place order: Data server not ready", "ERROR")
                messagebox.showerror("Not Ready", "Data server not ready. Please wait for confirmation message.")
                return
            
            # Get target delta
            try:
                target_delta = float(self.target_delta_entry.get())
                if target_delta <= 0 or target_delta > 100:
                    raise ValueError("Target delta must be between 0 and 100")
            except ValueError as e:
                self.log_message(f"Invalid target delta: {e}", "ERROR")
                messagebox.showerror("Invalid Input", "Please enter a valid target delta (0-100)")
                return
            
            self.log_message(f"MANUAL BUY CALL INITIATED - Target Delta: {target_delta}", "SUCCESS")
            
            # Find option by delta
            result = self.find_option_by_delta("C", target_delta)
            if not result:
                self.log_message("No suitable call options found", "WARNING")
                messagebox.showwarning("No Options Found", 
                                        f"No call options found near {target_delta} delta")
                return
            
            contract_key, contract, ask_price, actual_delta = result
            
            # Calculate quantity based on mode
            position_mode = self.position_size_mode.get()
            if position_mode == "fixed":
                # Use fixed quantity from Trade Qty field
                try:
                    quantity = int(self.trade_qty_entry.get())
                    if quantity <= 0:
                        raise ValueError("Quantity must be positive")
                except ValueError as e:
                    self.log_message(f"Invalid trade quantity: {e}", "ERROR")
                    messagebox.showerror("Invalid Input", "Please enter a valid trade quantity")
                    return
                self.log_message(f"Position sizing: Fixed quantity = {quantity} contracts", "INFO")
            else:  # calculated
                # Calculate quantity based on max risk / option price
                try:
                    max_risk = float(self.max_risk_entry.get())
                    if max_risk <= 0:
                        raise ValueError("Max risk must be positive")
                except ValueError as e:
                    self.log_message(f"Invalid max risk: {e}", "ERROR")
                    messagebox.showerror("Invalid Input", "Please enter a valid max risk amount")
                    return
                
                # Calculate: Max Risk / (Option Price * 100 multiplier)
                quantity = int(max_risk / ask_price)
                if quantity <= 0:
                    quantity = 1  # Minimum 1 contract
                
                total_risk = quantity * ask_price
                self.log_message(f"Position sizing: Calculated by risk", "INFO")
                self.log_message(f"  Max Risk: ${max_risk:.2f}", "INFO")
                self.log_message(f"  Option Price: ${ask_price:.2f}", "INFO")
                self.log_message(f"  Quantity: {quantity} contracts", "INFO")
                self.log_message(f"  Actual Risk: ${total_risk:.2f}", "INFO")
            
            # DIAGNOSTIC: Log the contract details
            self.log_message(f"Contract found: {contract_key}", "INFO")
            self.log_message(f"Contract expiration: {contract.lastTradeDateOrContractMonth}", "INFO")
            self.log_message(f"Delta: {actual_delta:.1f} (Target: {target_delta})", "INFO")
            
            # Calculate mid price for order
            mid_price = self.calculate_mid_price(contract_key)
            if mid_price == 0:
                self.log_message("Cannot calculate mid price - using ask price", "WARNING")
                mid_price = ask_price
            
            # Place order with mid-price chasing enabled
            order_id = self.place_order(
                contract_key=contract_key,
                contract=contract,
                action="BUY",
                quantity=quantity,
                limit_price=mid_price,
                enable_chasing=True  # Manual orders chase the mid-price
            )
            
            if order_id:
                self.log_message(f"Manual CALL order #{order_id} submitted: {quantity} contracts @ ${mid_price:.2f}", "SUCCESS")
            self.log_message("=" * 60, "INFO")
            
        except Exception as e:
            self.log_message(f"Error in manual_buy_call: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
            messagebox.showerror("Error", f"Failed to place call order: {e}")
    
    def manual_buy_put(self):
        """
        Manual trading: Buy put option
        Finds contract by target delta and calculates position size based on mode
        """
        self.log_message("=" * 60, "INFO")
        self.log_message("🔔 BUY PUT BUTTON CLICKED 🔔", "SUCCESS")
        self.log_message("=" * 60, "INFO")
        
        try:
            if self.connection_state != ConnectionState.CONNECTED:
                self.log_message("❌ Cannot place order: Not connected to IBKR", "ERROR")
                messagebox.showerror("Not Connected", "Please connect to IBKR before trading")
                return
            
            if not self.data_server_ok:
                self.log_message("❌ Cannot place order: Data server not ready", "ERROR")
                messagebox.showerror("Not Ready", "Data server not ready. Please wait for confirmation message.")
                return
            
            # Get target delta
            try:
                target_delta = float(self.target_delta_entry.get())
                if target_delta <= 0 or target_delta > 100:
                    raise ValueError("Target delta must be between 0 and 100")
            except ValueError as e:
                self.log_message(f"Invalid target delta: {e}", "ERROR")
                messagebox.showerror("Invalid Input", "Please enter a valid target delta (0-100)")
                return
            
            self.log_message(f"MANUAL BUY PUT INITIATED - Target Delta: {target_delta}", "SUCCESS")
            
            # Find option by delta
            result = self.find_option_by_delta("P", target_delta)
            if not result:
                self.log_message("No suitable put options found", "WARNING")
                messagebox.showwarning("No Options Found", 
                                        f"No put options found near {target_delta} delta")
                return
            
            contract_key, contract, ask_price, actual_delta = result
            
            # Calculate quantity based on mode
            position_mode = self.position_size_mode.get()
            if position_mode == "fixed":
                # Use fixed quantity from Trade Qty field
                try:
                    quantity = int(self.trade_qty_entry.get())
                    if quantity <= 0:
                        raise ValueError("Quantity must be positive")
                except ValueError as e:
                    self.log_message(f"Invalid trade quantity: {e}", "ERROR")
                    messagebox.showerror("Invalid Input", "Please enter a valid trade quantity")
                    return
                self.log_message(f"Position sizing: Fixed quantity = {quantity} contracts", "INFO")
            else:  # calculated
                # Calculate quantity based on max risk / option price
                try:
                    max_risk = float(self.max_risk_entry.get())
                    if max_risk <= 0:
                        raise ValueError("Max risk must be positive")
                except ValueError as e:
                    self.log_message(f"Invalid max risk: {e}", "ERROR")
                    messagebox.showerror("Invalid Input", "Please enter a valid max risk amount")
                    return
                
                # Calculate: Max Risk / (Option Price * 100 multiplier)
                quantity = int(max_risk / ask_price)
                if quantity <= 0:
                    quantity = 1  # Minimum 1 contract
                
                total_risk = quantity * ask_price
                self.log_message(f"Position sizing: Calculated by risk", "INFO")
                self.log_message(f"  Max Risk: ${max_risk:.2f}", "INFO")
                self.log_message(f"  Option Price: ${ask_price:.2f}", "INFO")
                self.log_message(f"  Quantity: {quantity} contracts", "INFO")
                self.log_message(f"  Actual Risk: ${total_risk:.2f}", "INFO")
            
            # DIAGNOSTIC: Log the contract details
            self.log_message(f"Contract found: {contract_key}", "INFO")
            self.log_message(f"Contract expiration: {contract.lastTradeDateOrContractMonth}", "INFO")
            self.log_message(f"Delta: {actual_delta:.1f} (Target: {target_delta})", "INFO")
            
            # Calculate mid price for order
            mid_price = self.calculate_mid_price(contract_key)
            if mid_price == 0:
                self.log_message("Cannot calculate mid price - using ask price", "WARNING")
                mid_price = ask_price
            
            # Place order with mid-price chasing enabled
            order_id = self.place_order(
                contract_key=contract_key,
                contract=contract,
                action="BUY",
                quantity=quantity,
                limit_price=mid_price,
                enable_chasing=True  # Manual orders chase the mid-price
            )
            
            if order_id:
                self.log_message(f"Manual PUT order #{order_id} submitted: {quantity} contracts @ ${mid_price:.2f}", "SUCCESS")
            self.log_message("=" * 60, "INFO")
            
        except Exception as e:
            self.log_message(f"Error in manual_buy_put: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
            messagebox.showerror("Error", f"Failed to place put order: {e}")
    
    def update_manual_orders(self):
        """
        Monitor all manual orders with aggressive chasing strategy
        
        Runs every 1 second to check if:
        1. Order is still open (not filled/cancelled)
        2. Mid-price has moved significantly
        3. After 10+ seconds, start giving in on price to force fills
        
        AGGRESSIVE CHASING STRATEGY:
        - First 10 seconds: Chase exact mid-price
        - After 10 seconds: Give in by $0.05 (if option < $3) or $0.10 (if option >= $3)
        - Every additional 10 seconds: Give in another increment
        - This forces stale orders to fill faster
        """
        if not self.manual_orders:
            return  # No orders to monitor
        
        orders_to_remove = []
        current_time = datetime.now()
        
        for order_id, order_info in self.manual_orders.items():
            # Check if order is still pending
            if order_id not in self.pending_orders:
                # Order was filled or cancelled - stop monitoring
                orders_to_remove.append(order_id)
                continue
            
            contract_key = order_info['contract_key']
            current_mid = self.calculate_mid_price(contract_key)
            
            if current_mid == 0:
                continue  # No valid market data
            
            # Calculate time since order placed
            time_elapsed = (current_time - order_info['timestamp']).total_seconds()
            
            # Determine price increment based on option price
            if current_mid < 3.00:
                increment = 0.05  # $0.05 for cheaper options
            else:
                increment = 0.10  # $0.10 for more expensive options
            
            # Calculate how much to give in based on elapsed time
            # First 10 seconds: 0 concession (chase exact mid)
            # After 10 seconds: 1 increment concession
            # After 20 seconds: 2 increment concession, etc.
            concession_count = int(time_elapsed // 10) - 1  # -1 because first 10 secs = 0 concession
            concession_count = max(0, concession_count)  # Never negative
            
            # Calculate target price based on action
            if order_info['action'] == "BUY":
                # For BUY orders, we're willing to pay MORE to get filled
                target_price = current_mid + (concession_count * increment)
            else:  # SELL
                # For SELL orders, we're willing to accept LESS to get filled
                target_price = current_mid - (concession_count * increment)
                target_price = max(0.05, target_price)  # Never go below $0.05
            
            last_price = order_info['last_mid']
            
            # Check if we need to update price
            price_diff = abs(target_price - last_price)
            should_update = False
            update_reason = ""
            
            # Always update if mid moved significantly (at least one tick)
            if abs(current_mid - last_price) >= 0.05:
                should_update = True
                update_reason = f"Mid moved ${last_price:.2f} → ${current_mid:.2f}"
            
            # Also update when we cross a 10-second threshold (new concession)
            elif concession_count > 0 and price_diff >= increment * 0.5:
                should_update = True
                if concession_count == 1:
                    update_reason = f"10s elapsed - giving in ${increment:.2f}"
                else:
                    update_reason = f"{int(time_elapsed)}s elapsed - giving in ${concession_count * increment:.2f} total"
            
            if should_update:
                # Log the update with reasoning
                self.log_message(
                    f"Order #{order_id}: {update_reason}, updating ${last_price:.2f} → ${target_price:.2f}",
                    "WARNING" if concession_count > 0 else "INFO"
                )
                
                # Modify existing order with new price
                modified_order = Order()
                modified_order.action = order_info['action']
                modified_order.totalQuantity = order_info['quantity']
                modified_order.orderType = "LMT"
                modified_order.lmtPrice = target_price
                modified_order.tif = "DAY"
                modified_order.transmit = True
                
                # Use same order ID to modify the existing order
                self.placeOrder(order_id, order_info['contract'], modified_order)
                
                # Update tracking
                order_info['last_mid'] = target_price
                order_info['attempts'] += 1
                
                # Update price in display
                status_text = "Chasing Mid" if concession_count == 0 else f"Giving In x{concession_count}"
                self.update_order_in_tree(order_id, status_text, target_price)
                
                self.log_message(
                    f"Order #{order_id} price updated to ${target_price:.2f} (attempt #{order_info['attempts']}, {int(time_elapsed)}s elapsed)",
                    "SUCCESS"
                )
        
        # Remove filled/cancelled orders from monitoring
        for order_id in orders_to_remove:
            if order_id in self.manual_orders:
                del self.manual_orders[order_id]
        
        # Continue monitoring if orders remain
        if self.manual_orders and self.root:
            self.root.after(self.manual_order_update_interval, self.update_manual_orders)
    
    def on_position_sheet_click(self, event):
        """
        Handle click on position sheet to close positions
        
        When user clicks "X Close" button in Action column, immediately closes
        the position using same mid-price chasing logic as entries
        """
        try:
            # Get selected cell
            selected = self.position_sheet.get_currently_selected()
            if not selected:
                return
            
            row, col = selected.row, selected.column
            
            # Check if clicked on Action column (index 8 - updated from 6 after adding EntryTime/TimeSpan)
            if col != 8:
                return
            
            # Get all data from the row
            row_data = self.position_sheet.get_row_data(row)
            if not row_data or len(row_data) < 7:
                return
            
            contract_display = row_data[0]  # e.g., "SPX_5800.0_C"
            
            # Find matching position
            matching_key = None
            for key in self.positions.keys():
                if key in contract_display or contract_display in key:
                    matching_key = key
                    break
            
            if not matching_key:
                self.log_message(f"Position not found for {contract_display}", "ERROR")
                return
            
            pos = self.positions[matching_key]
            
            # PROTECTION: Check if position is zero (nothing to close)
            if pos['position'] == 0:
                self.log_message(f"⚠️ WARNING: Position for {matching_key} is zero - nothing to close!", "WARNING")
                messagebox.showwarning(
                    "Invalid Position",
                    f"Position quantity is zero.\n"
                    "There is no position to close!\n\n"
                    "This may indicate the position was already closed or there's a tracking issue."
                )
                return
            
            # PROTECTION: Check for pending exit orders for this contract
            # Check for either SELL orders (closing long) or BUY orders (closing short)
            pending_exit_orders = []
            for order_id, order_info in self.manual_orders.items():
                if order_info['contract_key'] == matching_key:
                    # Check if this is an exit order (opposite direction of position)
                    is_exit_order = (pos['position'] > 0 and order_info['action'] == "SELL") or \
                                   (pos['position'] < 0 and order_info['action'] == "BUY")
                    if is_exit_order:
                        pending_exit_orders.append(order_id)
            
            if pending_exit_orders:
                action_type = "SELL" if pos['position'] > 0 else "BUY"
                self.log_message(f"⚠️ WARNING: Already have {len(pending_exit_orders)} pending {action_type} order(s) for {matching_key}!", "WARNING")
                messagebox.showwarning(
                    "Pending Exit Order",
                    f"There are already {len(pending_exit_orders)} pending {action_type} order(s) for this position!\n\n"
                    f"Order IDs: {', '.join(map(str, pending_exit_orders))}\n\n"
                    "Please wait for the existing order to fill or cancel it first."
                )
                return
            
            # Confirm close
            confirm = messagebox.askyesno(
                "Close Position",
                f"Close position: {contract_display}\n"
                f"Quantity: {pos['position']}\n"
                f"Current P&L: ${pos['pnl']:.2f}\n\n"
                f"Place exit order at mid-price?"
            )
            
            if not confirm:
                return
            
            self.log_message("=" * 60, "INFO")
            self.log_message(f"MANUAL CLOSE POSITION: {matching_key}", "SUCCESS")
            
            # Calculate mid price for exit
            mid_price = self.calculate_mid_price(matching_key)
            if mid_price == 0:
                # Fallback to last price
                mid_price = pos['currentPrice']
                self.log_message(f"Using last price ${mid_price:.2f} for exit", "WARNING")
            
            # CRITICAL FIX: Determine action based on position direction
            # If LONG (positive) → SELL to close
            # If SHORT (negative) → BUY to close (should never happen for options!)
            position_qty = pos['position']
            quantity = int(abs(position_qty))  # Ensure integer quantity
            
            if position_qty > 0:
                action = "SELL"  # Close long position
            elif position_qty < 0:
                action = "BUY"   # Close short position (SHOULD NEVER HAPPEN WITH OPTIONS!)
                self.log_message("⚠️ WARNING: Closing SHORT position - this should not happen with long-only options!", "WARNING")
            else:
                self.log_message("❌ ERROR: Position quantity is zero, nothing to close", "ERROR")
                return
            
            # Ensure contract has all required fields for order placement
            exit_contract = pos['contract']
            if not exit_contract.exchange:
                exit_contract.exchange = "SMART"
            if not exit_contract.tradingClass:
                exit_contract.tradingClass = TRADING_CLASS
            if not exit_contract.currency:
                exit_contract.currency = "USD"
            
            self.log_message(f"Exit order: {action} {quantity} @ ${mid_price:.2f}", "INFO")
            self.log_message(f"Contract: {exit_contract.symbol} {exit_contract.strike} {exit_contract.right} {exit_contract.lastTradeDateOrContractMonth}", "INFO")
            
            # Place sell order with mid-price chasing
            order_id = self.place_order(
                contract_key=matching_key,
                contract=exit_contract,
                action=action,
                quantity=quantity,
                limit_price=mid_price,
                enable_chasing=True  # Exit orders also chase the mid-price
            )
            
            if order_id:
                self.log_message(f"Exit order #{order_id} submitted with mid-price chasing", "SUCCESS")
            self.log_message("=" * 60, "INFO")
            
        except Exception as e:
            self.log_message(f"Error in on_position_sheet_click: {e}", "ERROR")
    
    def on_order_sheet_click(self, event):
        """
        Handle click on order sheet to cancel orders
        
        When user clicks "Cancel" button, cancels the order and removes from display
        """
        try:
            # Get selected cell
            selected = self.order_sheet.get_currently_selected()
            if not selected:
                return
            
            row, col = selected.row, selected.column
            
            # Check if clicked on Cancel column (index 6)
            if col != 6:
                return
            
            # Get order ID from first column
            row_data = self.order_sheet.get_row_data(row)
            if not row_data or len(row_data) < 1:
                return
            
            order_id = int(row_data[0])
            contract_display = row_data[1] if len(row_data) > 1 else "Unknown"
            
            # Confirm cancellation
            confirm = messagebox.askyesno(
                "Cancel Order",
                f"Cancel order #{order_id}?\n"
                f"Contract: {contract_display}"
            )
            
            if not confirm:
                return
            
            self.log_message(f"Canceling order #{order_id}...", "INFO")
            
            # Cancel the order
            self.cancelOrder(order_id)
            
            # Remove from manual orders tracking (stops price chasing)
            if order_id in self.manual_orders:
                del self.manual_orders[order_id]
            
            # Remove from pending orders
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
            
            # Remove from display
            self.update_order_in_tree(order_id, "Cancelled")
            
            self.log_message(f"Order #{order_id} cancelled", "SUCCESS")
            
        except Exception as e:
            self.log_message(f"Error closing position: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
    
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
                
                # Place exit order using unified function
                self.place_order(
                    contract_key=contract_key,
                    contract=contract,
                    action="SELL",
                    quantity=quantity,
                    limit_price=current_bid,
                    enable_chasing=False  # Supertrend exits don't chase
                )
    
    def update_chart(self, contract_key: str):
        """Update the matplotlib chart with supertrend - DEPRECATED, kept for compatibility"""
        # This method is no longer used - charts are now updated via update_call_chart and update_put_chart
        pass
    
    def on_option_sheet_click(self, event):
        """Handle click on option chain tksheet to update charts"""
        try:
            # Use tksheet's identify method to get row and column from click coordinates
            region = self.option_sheet.identify_region(event)
            
            # region returns a string like 'table', 'header', 'index', 'top left', or None
            if region != "table":
                self.log_message(f"Clicked in {region} area, not a data cell", "INFO")
                return
            
            # Get the row and column that was clicked
            # Use identify_row and identify_column methods
            row_idx = self.option_sheet.identify_row(event, exclude_index=True)
            col_idx = self.option_sheet.identify_column(event, exclude_header=True)
            
            if row_idx is None or col_idx is None:
                self.log_message("Could not identify clicked cell", "WARNING")
                return
            
            # Get strike from the selected row
            # Find strike by row index from strike_to_row mapping
            strike = None
            for s, r_idx in self.strike_to_row.items():
                if r_idx == row_idx:
                    strike = s
                    break
            
            if strike is None:
                self.log_message(f"Could not determine strike for row {row_idx}", "WARNING")
                return
            
            self.log_message(f"Clicked: row={row_idx}, column={col_idx}, strike={strike}", "INFO")
            
            # Determine if user clicked on call or put side
            # Columns 0-8 are calls, 9 is strike, 10-17 are puts
            if col_idx < 9:
                # Clicked on call side - find contract by strike and right using get_contract_key
                contract_key = None
                for key, data in self.market_data.items():
                    if data.get('strike') == float(strike) and data.get('right') == 'C':
                        contract_key = key
                        break
                
                self.log_message(f"Looking for call contract at strike {strike}, found: {contract_key}", "INFO")
                
                if contract_key and contract_key in self.market_data:
                    # Create fresh contract with current expiration for chart data
                    self.selected_call_contract = self.create_option_contract(float(strike), "C")
                    self.log_message(f"✓ Selected CALL: Strike {strike} (Expiry: {self.current_expiry}) - Requesting chart data...", "SUCCESS")
                    self.update_call_chart()
                else:
                    self.log_message(f"Call contract at strike {strike} not found in market_data", "WARNING")
                    self.log_message(f"Available contracts: {list(self.market_data.keys())[:5]}...", "DEBUG")
                    
            elif col_idx > 9:
                # Clicked on put side - find contract by strike and right using get_contract_key
                contract_key = None
                for key, data in self.market_data.items():
                    if data.get('strike') == float(strike) and data.get('right') == 'P':
                        contract_key = key
                        break
                
                self.log_message(f"Looking for put contract at strike {strike}, found: {contract_key}", "INFO")
                
                if contract_key and contract_key in self.market_data:
                    # Create fresh contract with current expiration for chart data
                    self.selected_put_contract = self.create_option_contract(float(strike), "P")
                    self.log_message(f"✓ Selected PUT: Strike {strike} (Expiry: {self.current_expiry}) - Requesting chart data...", "SUCCESS")
                    self.update_put_chart()
                else:
                    self.log_message(f"Put contract at strike {strike} not found in market_data", "WARNING")
                    self.log_message(f"Available contracts: {list(self.market_data.keys())[:5]}...", "DEBUG")
            else:
                self.log_message("Clicked on strike column - please click on call or put columns", "INFO")
                    
        except Exception as e:
            self.log_message(f"Error handling option chain click: {e}", "ERROR")
            import traceback
            self.log_message(f"Traceback: {traceback.format_exc()}", "ERROR")
    
    def on_option_chain_click(self, event):
        """DEPRECATED: Old Treeview click handler - replaced by on_option_sheet_click"""
        # Kept for backwards compatibility, redirects to sheet handler
        self.on_option_sheet_click(event)
    
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
            contract_key = self.get_contract_key(self.selected_call_contract)
            # Clear historical data to force re-request with new settings
            if contract_key in self.historical_data:
                del self.historical_data[contract_key]
        self.update_call_chart()
        # Auto-save chart settings
        self.save_settings()
    
    def on_put_settings_changed(self):
        """Handle put chart settings change - clear data and refresh"""
        if self.selected_put_contract:
            contract_key = self.get_contract_key(self.selected_put_contract)
            # Clear historical data to force re-request with new settings
            if contract_key in self.historical_data:
                del self.historical_data[contract_key]
        self.update_put_chart()
        # Auto-save chart settings
        self.save_settings()
    
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
        
        contract_key = self.get_contract_key(self.selected_call_contract)
        
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
        
        contract_key = self.get_contract_key(self.selected_put_contract)
        
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
            # Update toolbar label instead of chart title
            if chart_type == "Call":
                self.call_contract_label.config(text=f"Strike {strike}")
            elif chart_type == "Put":
                self.put_contract_label.config(text=f"Strike {strike}")
            
            ax.set_xlabel('Time', color='#E0E0E0', fontsize=8)
            ax.grid(True, alpha=0.2, color='#444444', linewidth=0.5, linestyle='-')
            
            # Move Y-axis to the right
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")
            ax.set_ylabel('Price', color='#E0E0E0', fontsize=8)
            
            # Add current price label on Y-axis (bold and highlighted)
            current_price = float(closes[-1])  # Last close price
            ax.text(n_bars + 0.5, current_price, f' ${current_price:.2f} ', 
                   fontsize=9, fontweight='bold', color='#FF8C00',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='#000000', 
                            edgecolor='#FF8C00', linewidth=1.5),
                   verticalalignment='center', horizontalalignment='left')
            
            # Add horizontal line at current price
            ax.axhline(y=current_price, color='#FF8C00', linestyle='--', linewidth=1, alpha=0.3)
            
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
                         quantity: int, price: float, status: str):
        """Add order to the order sheet (tksheet)"""
        try:
            contract_key = self.get_contract_key(contract)
            
            # Get current data
            current_data = self.order_sheet.get_sheet_data()
            
            # Add new row with price and Cancel button
            new_row = [str(order_id), contract_key, action, str(quantity), f"${price:.2f}", status, "Cancel"]
            current_data.append(new_row)
            
            # Update sheet (unavoidable when adding rows)
            self.order_sheet.set_sheet_data(current_data)
            
            # Re-apply column widths (only when row count changes)
            for col_idx, width in enumerate([80, 210, 60, 50, 80, 100, 80]):
                self.order_sheet.column_width(column=col_idx, width=width)
            
            # Apply yellow background to Cancel button (column 6)
            row_idx = len(current_data) - 1
            self.order_sheet.highlight_cells(row=row_idx, column=6, fg="#000000", bg="#FFFF00")
            
        except Exception as e:
            self.log_message(f"Error adding order to sheet: {e}", "ERROR")
    
    def update_order_in_tree(self, order_id: int, status: str, price: Optional[float] = None):
        """Update order status and optionally price in sheet (tksheet)"""
        try:
            # Get all rows
            data = self.order_sheet.get_sheet_data()
            
            # Find and update the row
            for i, row in enumerate(data):
                if row and len(row) > 0 and str(row[0]) == str(order_id):
                    # Only remove order when actually filled or cancelled
                    # "PreSubmitted" and "Submitted" mean order is working, NOT filled!
                    # "Inactive" means rejected (exchange closed, invalid order, etc.)
                    if status in ["Filled", "Cancelled", "Inactive"]:
                        data.pop(i)
                        # Update sheet (row count changed)
                        self.order_sheet.set_sheet_data(data)
                        # Re-apply column widths (only when row count changes)
                        for col_idx, width in enumerate([80, 210, 60, 50, 80, 100, 80]):
                            self.order_sheet.column_width(column=col_idx, width=width)
                    else:
                        # Update cells individually (preserves column widths)
                        if price is not None:
                            self.order_sheet.set_cell_data(i, 4, f"${price:.2f}")
                        self.order_sheet.set_cell_data(i, 5, status)
                    break
                    
        except Exception as e:
            self.log_message(f"Error updating order in sheet: {e}", "ERROR")
    
    def update_positions_display(self):
        """Update the positions tksheet grid"""
        if not self.root:
            return
        
        # Build data rows
        rows = []
        total_pnl = 0
        
        for contract_key, pos in self.positions.items():
            # Update P&L with current mid-price from market data
            self.update_position_pnl(contract_key)
            
            pnl = pos['pnl']
            pnl_pct = (pos['currentPrice'] / pos['avgCost'] - 1) * 100 if pos['avgCost'] > 0 else 0
            
            # Calculate time in position
            entry_time = pos.get('entryTime', datetime.now())
            time_span = datetime.now() - entry_time
            
            # Format time span as HH:MM:SS
            hours, remainder = divmod(int(time_span.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            time_span_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Format entry time as HH:MM:SS
            entry_time_str = entry_time.strftime("%H:%M:%S")
            
            # Format row data
            row = [
                contract_key,
                f"{pos['position']:.0f}",
                f"${pos['avgCost']:.2f}",
                f"${pos['currentPrice']:.2f}",
                f"${pnl:.2f}",
                f"{pnl_pct:.2f}%",
                entry_time_str,
                time_span_str,
                "Close"
            ]
            rows.append(row)
            total_pnl += pnl
        
        # Get current sheet size
        current_data = self.position_sheet.get_sheet_data()
        current_row_count = len(current_data)
        new_row_count = len(rows)
        
        # Handle row count changes (positions added/removed)
        if current_row_count != new_row_count:
            # Row count changed - need to use set_sheet_data (but this is rare)
            # This only happens when positions are opened or closed
            self.position_sheet.set_sheet_data(rows)
            
            # Re-apply column widths after set_sheet_data (unavoidable when row count changes)
            for col_idx, width in enumerate([230, 50, 80, 80, 100, 80, 100, 90, 70]):
                self.position_sheet.column_width(column=col_idx, width=width)
            
            # Color-code rows
            for row_idx, (contract_key, pos) in enumerate(self.positions.items()):
                pnl = pos['pnl']
                
                # Determine row color
                if pnl > 0:
                    fg_color = "#00FF00"  # Green for profit
                elif pnl < 0:
                    fg_color = "#FF0000"  # Red for loss
                else:
                    fg_color = "#FFFFFF"  # White for zero
                
                # Apply color to PnL columns (indices 4 and 5)
                self.position_sheet.highlight_cells(row=row_idx, column=4, fg=fg_color, bg="#000000")
                self.position_sheet.highlight_cells(row=row_idx, column=5, fg=fg_color, bg="#000000")
                
                # Style Close button: Red background, white text (index 8)
                self.position_sheet.highlight_cells(row=row_idx, column=8, fg="#FFFFFF", bg="#CC0000")
        else:
            # Same number of rows - update cells individually (preserves column widths)
            for row_idx, row in enumerate(rows):
                for col_idx, value in enumerate(row):
                    # Update each cell individually
                    self.position_sheet.set_cell_data(row_idx, col_idx, value)
            
            # Update cell colors for PnL columns
            for row_idx, (contract_key, pos) in enumerate(self.positions.items()):
                pnl = pos['pnl']
                
                # Determine row color
                if pnl > 0:
                    fg_color = "#00FF00"  # Green for profit
                elif pnl < 0:
                    fg_color = "#FF0000"  # Red for loss
                else:
                    fg_color = "#FFFFFF"  # White for zero
                
                # Apply color to PnL columns (indices 4 and 5)
                self.position_sheet.highlight_cells(row=row_idx, column=4, fg=fg_color, bg="#000000")
                self.position_sheet.highlight_cells(row=row_idx, column=5, fg=fg_color, bg="#000000")
                
                # Style Close button: Red background, white text (index 8)
                self.position_sheet.highlight_cells(row=row_idx, column=8, fg="#FFFFFF", bg="#CC0000")
        
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
        Log a message to GUI, console, AND file.
        
        Args:
            message: The message to log
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # GUI log entry (can include emojis) - only if GUI exists
        if hasattr(self, 'log_text') and self.log_text:
            log_entry = f"[{timestamp}] {message}\n"
            self.log_text.insert(tk.END, log_entry, level)
            self.log_text.see(tk.END)
        
        # Console log (no emojis, plain text)
        console_message = f"[{timestamp}] [{level}] {message}"
        print(console_message)
        
        # FILE LOG - Write to daily log file
        # Map our custom levels to standard logging levels
        if level == "ERROR":
            file_logger.error(message)
        elif level == "WARNING":
            file_logger.warning(message)
        elif level == "SUCCESS":
            file_logger.info(f"✓ {message}")
        else:  # INFO or any other level
            file_logger.info(message)
        
        # Keep log size manageable - only if GUI exists
        if hasattr(self, 'log_text') and self.log_text:
            if int(self.log_text.index('end-1c').split('.')[0]) > 1000:
                self.log_text.delete('1.0', '500.0')
    
    # ========================================================================
    # MAIN LOOP
    # ========================================================================
    
    def cleanup_all_connections(self):
        """Comprehensive cleanup of all IBKR connections, subscriptions, and threads"""
        self.log_message("Starting comprehensive cleanup...", "INFO")
        
        try:
            # Cancel all market data subscriptions using market_data_map (reqId -> contract_key)
            if hasattr(self, 'market_data_map') and self.market_data_map:
                self.log_message(f"Cancelling {len(self.market_data_map)} market data subscriptions...", "INFO")
                for req_id in list(self.market_data_map.keys()):
                    try:
                        self.cancelMktData(req_id)
                    except Exception as e:
                        pass  # Ignore errors during cleanup
                self.market_data_map.clear()
                self.subscribed_contracts.clear()
            
            # Cancel all historical data requests
            if hasattr(self, 'historical_data_requests') and self.historical_data_requests:
                self.log_message(f"Cancelling {len(self.historical_data_requests)} historical data requests...", "INFO")
                for req_id in list(self.historical_data_requests.keys()):
                    try:
                        self.cancelHistoricalData(req_id)
                    except Exception as e:
                        pass  # Ignore errors during cleanup
                self.historical_data_requests.clear()
            
            # Cancel position subscription
            try:
                self.log_message("Cancelling position subscription...", "INFO")
                self.cancelPositions()
            except Exception as e:
                pass  # Ignore errors during cleanup
            
            # Cancel any pending orders
            if hasattr(self, 'pending_orders') and self.pending_orders:
                self.log_message(f"Cancelling {len(self.pending_orders)} pending orders...", "INFO")
                for order_id in list(self.pending_orders.keys()):
                    try:
                        self.cancelOrder(order_id)
                    except Exception as e:
                        pass  # Ignore errors during cleanup
                self.pending_orders.clear()
            
            # Disconnect from IBKR
            try:
                self.log_message("Disconnecting from IBKR...", "INFO")
                EClient.disconnect(self)
            except Exception as e:
                pass  # Ignore errors during cleanup
            
            # Stop the API thread
            self.running = False
            if hasattr(self, 'api_thread') and self.api_thread and self.api_thread.is_alive():
                self.log_message("Waiting for API thread to terminate...", "INFO")
                self.api_thread.join(timeout=2.0)
                if self.api_thread.is_alive():
                    self.log_message("API thread did not terminate cleanly (timeout)", "WARNING")
                else:
                    self.log_message("API thread terminated successfully", "SUCCESS")
            
            self.connection_state = ConnectionState.DISCONNECTED
            self.log_message("Cleanup completed successfully", "SUCCESS")
            
        except Exception as e:
            self.log_message(f"Error during cleanup: {str(e)}", "ERROR")
    
    def on_closing(self):
        """Handle window closing - properly cleanup and exit"""
        if not self.root:
            return
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            # Comprehensive cleanup of all IBKR connections
            if self.connection_state == ConnectionState.CONNECTED:
                self.cleanup_all_connections()
            else:
                # Still stop the API thread even if not connected
                self.running = False
                if hasattr(self, 'api_thread') and self.api_thread and self.api_thread.is_alive():
                    self.api_thread.join(timeout=1.0)
            
            # Destroy the GUI window
            self.root.destroy()
            
            # Force exit the Python process
            import sys
            sys.exit(0)
    
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
        
        # Normal exit after GUI closes
        print("[SHUTDOWN] Application closed normally")
        import sys
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Application interrupted by user (Ctrl+C)")
        import sys
        sys.exit(0)
        
    except Exception as e:
        print(f"[FATAL ERROR] Application crashed: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
        import sys
        sys.exit(1)
