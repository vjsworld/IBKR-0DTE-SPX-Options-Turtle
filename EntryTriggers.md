Research Brief: Advanced Entry Triggers for HFT Mean-Reversion

Your current model (Gamma-Snap v2.0) is a confluence-based filter. It works by combining several "dumb" indicators (BBands, RSI, EMA) to create one "smart" signal. This is a proven and robust method.

"Better" models aim to achieve a higher win rate, a more precise entry, and a better understanding of why the reversion is happening. They do this by replacing the indicators with a single, more powerful statistical or order-flow-based model.

Here are the three primary categories of "better" models used for this type of trading.

Category 1: Statistical & Econometric Models (The "Quant" Upgrade)

These models replace the visual Bollinger Band with a more rigorous statistical measure of "extreme."

Model 1: The Z-Score (Statistical Arbitrage)

This is the most direct and powerful upgrade to your current model.

Core Concept: Instead of asking, "Did the price touch the 2-standard-deviation Bollinger Band?" it asks, "How many standard deviations is the current price from its recent moving average?" This normalized value is the Z-Score.

Formula: Z-Score = (Price - Moving_Average) / Standard_Deviation

How It's Better:

It's a "purer" signal. A Bollinger Band (20, 2) is just a Z-Score = 2.0.

It's normalized. A Z-Score of -2.5 means the same thing statistically, whether the market is volatile or quiet. This is not true for RSI, which can get "stuck" in oversold territory.

How to Integrate (High-Consistency Trigger):

Old Trigger: Price < BB_Lower AND RSI < 25

New Trigger: Z-Score(period=20) < -2.5 (or -3.0 for ultra-high-quality signals).

This single statistical value (Z-Score < -2.5) replaces both the Bollinger Band and the RSI, simplifying your logic and improving its statistical reliability.

Model 2: Ornstein-Uhlenbeck (OU) Process

This is the formal, academic model for any mean-reverting asset.

Core Concept: This is a stochastic differential equation that describes the motion of a particle "tethered" by a spring. The "spring" constantly pulls the price back to the mean. The model estimates three key parameters:

θ (theta): The speed of reversion (how fast it snaps back).

μ (mu): The mean it reverts to (your 9-EMA).

σ (sigma): The volatility of the asset (your Bollinger Band width).

How It's Better: Instead of a static "5-minute time stop," you could use the model's θ (speed) parameter to calculate the expected holding time for the trade before you even enter.

How to Integrate (Advanced): This is mathematically complex and requires a "rolling regression" to constantly re-fit the parameters. It's likely overkill for a 1-minute chart but is the "purest" model of this behavior.

Category 2: Market Microstructure & Order Flow (The "HFT" Upgrade)

This category of models ignores charts and indicators entirely. It gets data from the order book (Level 2 data) to see what other traders are doing, not what the price did. This is what most "true" HFT firms use.

Model 1: Order Book Imbalance (OBI)

Core Concept: This model analyzes the "depth" of the order book. It calculates the ratio of buy orders vs. sell orders at the first few price levels.

Example: If the SPX is at 5304, the model sees:

Bids (Buy Orders): 5303.75 (100 contracts), 5303.50 (150 contracts)

Asks (Sell Orders): 5304.00 (50 contracts), 5304.25 (25 contracts)

Signal: The model sees a (100+150) / (50+25) = 3.33 imbalance. There is 3.3x more buy-side liquidity (a "buy wall").

How It's Better: This is predictive. A large buy wall acts like a "floor" that the price will bounce off of. Your current model reacts to the price after it has already hit the floor. This model sees the floor before the price hits it.

How to Integrate:

New Trigger: (Total Bids / Total Asks) > 3.0

Challenge: This requires a Level 2 (Market Depth) data subscription from IBKR, which is a different feed (reqMktDepth) and far more data-intensive.

Model 2: Trade Flow Delta (Tape Reading)

Core Concept: This model analyzes the "Time & Sales" (the tape). It tracks whether trades are executing at the bid price (a "sell") or the ask price (a "buy").

Signal: It calculates the Cumulative Delta (Delta): (Volume at Ask) - (Volume at Bid).

A rising Delta means buyers are aggressively hitting the "ask" (bullish).

A falling Delta means sellers are aggressively hitting the "bid" (bearish).

How It's Better (The "Exhaustion" Trigger): This is the ultimate confirmation. Your Gamma-Snap strategy wants to buy a "snap-back." The best time to do this is when:

Price makes a new 1-minute low.

But the Delta on that new low is positive (i.e., buyers stepped in at the low).

How to Integrate:

Old Trigger: Price < BB_Lower AND RSI < 25

New Trigger: Price < BB_Lower AND Price_Delta(last 10 seconds) > 0 (This is called "absorption" or a "divergence").

Category 3: Machine Learning (ML) Models (The "AI" Upgrade)

These models use historical data to learn the optimal entry trigger, rather than you defining it.

Model 1: Classification (Random Forest / GBM)

This is the most practical ML approach and a direct replacement for your RSI/BB confluence.

Core Concept: You build a dataset from your 1-minute SPX bars. You then train a model (like a Random Forest or Gradient Boosting Machine) to predict a simple "Yes/No" outcome.

Feature Engineering (The X values): For each 1-minute bar, you would calculate:

Price_minus_EMA9 (your core reversion signal)

RSI(14)

BB_Upper, BB_Lower

VIX_Price

Time_of_Day (e.g., 10:30 AM = 10.5)

Day_of_Week (0-4)

Target (The Y value):

1 (Yes): If the price did touch the 9-EMA within the next 5 bars (a successful "snap").

0 (No): If the price did not touch the 9-EMA.

How It's Better: After training, you can feed the model live data (the features for the current bar). It will output a probability.

How to Integrate:

Old Trigger: Price < BB_Lower AND RSI < 25

New Trigger: The ML model's output P(Snap-Back) > 0.85 (i.e., "The model is 85% confident this is a winning trade").

Challenge: This requires a separate Python environment with scikit-learn or xgboost, a large historical dataset to train on, and a way to save and load the trained model into your trading app.

Recommendation & Next Steps

Your current model is good. The most logical and powerful upgrade that does not require a completely new data feed (like order flow) is the Z-Score model.

It is the same core strategy (mean-reversion) but replaces your visual indicators with a single, statistically normalized trigger. This should increase the quality and consistency of your signals.

My recommendation is to first try replacing your RSI/BB trigger with the Z-Score trigger.

We can modify your calculate_indicators function to compute a rolling 20-period Z-Score and then change the run_gamma_snap_strategy function to use it as the primary entry signal.