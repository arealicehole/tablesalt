# Cost Basis Tracker

**Simple, private, local-first tracker for your token purchases, swaps, sells, and other assets (precious metals, etc.).**

It automatically handles the annoying math: when you buy ADA to then swap for IAG (or any multi-hop trade), the cost basis follows the tokens so you always know your **true USD cost per token** for whatever you're holding.

## Why this exists
You told me exactly what you needed:
- Track buys/sells/swaps across assets
- "I spent $X on ADA → swapped Y ADA for Z IAG" → app figures out effective cost per IAG
- Aggregate view of all bags + total capital deployed
- Simple enough to start today, powerful enough to evolve with your portfolio (crypto + metals + whatever)

This is **v1** — solid foundation. We can add CSV import from explorers/CEX, price APIs, charts, tax reports (realized + holdings), multi-wallet tags, staking rewards handling, mobile APK (via Flet/Flutter), etc. as you need it.

## Quick Start (Desktop / Laptop)

1. **Install Python 3.10+** (if you don't have it)

2. **Download the files** (app.py + requirements.txt + this README) into a folder, e.g. `~/cost-basis-tracker/`

3. Open terminal in that folder and run:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

4. Your browser will open automatically at `http://localhost:8501`

5. **Start using it!** Add your historical transactions in the "Add Transaction" tab (backdate them with the date picker). The Dashboard updates live with correct cost basis.

**Data location**: A file called `cost_basis_tracker.db` is created in the same folder. **Back it up regularly** (copy the whole folder or just the .db file). It's your entire history.

## Using on Android / Phone

**Recommended (easiest):**
- Run the app on your computer/laptop (leave it running or start when needed)
- Access from phone browser on same WiFi: `http://YOUR-COMPUTER-IP:8501`
- Or use a free tunnel like **ngrok** (`ngrok http 8501`) or **Tailscale** / **Cloudflare Tunnel** for secure remote access from anywhere.

**"App-like" feel on Android**:
- Open in Chrome → Menu → "Add to home screen"
- It will feel like a native app (fullscreen, icon). Works offline after first load for the UI (data is local to the server though).

**Future native APK**: We can convert this to a proper Android/iOS app using [Flet](https://flet.dev) (Python → Flutter) or Flutter directly. Let me know when you're ready and we'll do it.

## How the Cost Basis Math Works

This uses **average cost basis with cost transfer on swaps** (perfect for what you described).

**Your exact example**:
1. Buy 100 ADA for $100 USD → ADA now has `qty=100`, `cost_basis=$100` → avg cost $1.00/ADA
2. Swap 100 ADA → 50 IAG (with $0.50 fee)
   - Cost transferred from ADA to IAG: $100
   - Fee added to IAG cost basis
   - **IAG now shows avg cost ≈ $2.01 / IAG**
   - ADA holdings → 0

The Dashboard always shows:
- Per-asset: Quantity, Avg Cost per unit, Total Cost Basis, Est. Value (using *your* prices), Unrealized P/L
- Portfolio totals + Realized P/L from all sells to date

**Deposits / Airdrops / Staking rewards**: Currently added with $0 cost basis (common for "free" receives). You can note the FMV in the notes field for your own records/taxes. We can enhance later to support assigned cost basis on deposits.

**Precious metals**: Just treat GOLD/SILVER as assets with unit "oz". Enter current spot price in the Prices tab.

## Tips for Best Results
- Be as accurate as possible with amounts, dates, and fees.
- For CEX buys then withdraw to self-custody: record as one Buy (the total USD out + any withdrawal fee).
- For complex DeFi (multiple swaps in one tx, or fees paid in the token): approximate or split into multiple entries. Future versions can support more granular "internal tx" logging.
- Update prices in the **Prices** tab regularly for meaningful P/L numbers (or leave at 0 if you only care about cost basis tracking).
- The transaction history is **immutable log** — deletes are possible but use sparingly (it changes all downstream calculations).

## What's Next? (Evolving with you)
Tell me what you want to add first:
- CSV bulk import (from Cardano explorer, CEX exports, Koinly, etc.)
- Automatic price fetch (CoinGecko, etc. for ADA/IAG/BTC — metals too)
- Charts (cost basis vs time, allocation pie, P/L over time)
- Tax-ready reports (long/short term gains, cost basis per lot if we switch to FIFO later)
- Wallet connect / on-chain sync (read-only)
- Multiple portfolios or tags (e.g. "DeFi bags", "Metals stack", "Kids college fund")
- Mobile native app (APK + iOS)
- Integration with your restaurant business? (separate P&L tracker?)

This is **your** tool. It starts simple exactly as you asked and grows as your needs (and bags) grow.

## Support / Feedback
If anything breaks or the math doesn't feel right on your real data, paste the transaction details (or export the .db) and I'll debug/fix immediately. We're building this together.

Enjoy tracking your bags without the spreadsheet pain! 🚀
