#!/usr/bin/env python3
"""
Cost Basis Tracker - Simple personal tracker for crypto, tokens, precious metals & more.
Tracks buys, swaps, sells with automatic cost basis transfer across trades.
Evolves with you: start simple, add features as needed.

Run with: streamlit run app.py
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, time
from collections import defaultdict
import os

DB_PATH = "cost_basis_tracker.db"

def get_connection():
    """Get SQLite connection. Safe for Streamlit reruns."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables and default assets."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Transactions log - immutable history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            txn_type TEXT NOT NULL,
            from_asset TEXT,
            from_amount REAL,
            to_asset TEXT,
            to_amount REAL,
            fee_usd REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Current prices for valuation (manual update for now)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT PRIMARY KEY,
            current_price_usd REAL DEFAULT 0,
            updated_at TEXT
        )
    """)
    
    # Asset metadata
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            asset_type TEXT DEFAULT 'crypto',
            unit TEXT DEFAULT 'units',
            notes TEXT
        )
    """)
    
    # Default assets
    defaults = [
        ("USD", "US Dollar (Fiat)", "fiat", "USD", "Special fiat asset - cost basis always par value"),
        ("ADA", "Cardano", "crypto", "ADA", "Native token for Cardano network"),
        ("IAG", "Iagon", "crypto", "IAG", "Decentralized storage on Cardano"),
        ("GOLD", "Physical Gold", "metal", "oz", "Precious metals - track in troy ounces"),
        ("SILVER", "Physical Silver", "metal", "oz", "Precious metals"),
        ("BTC", "Bitcoin", "crypto", "BTC", ""),
        ("ETH", "Ethereum", "crypto", "ETH", ""),
        ("USDC", "USD Coin", "crypto", "USDC", "Stablecoin - often ~$1"),
    ]
    
    for sym, name, atype, unit, notes in defaults:
        cur.execute("""
            INSERT OR IGNORE INTO assets (symbol, name, asset_type, unit, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (sym, name, atype, unit, notes))
        if sym != "USD":
            cur.execute("""
                INSERT OR IGNORE INTO prices (symbol, current_price_usd, updated_at)
                VALUES (?, 0, ?)
            """, (sym, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def get_known_assets(include_usd=False):
    """Get list of known asset symbols from assets table + any used in txns."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT symbol FROM assets ORDER BY symbol")
    assets = [row[0] for row in cur.fetchall()]
    
    # Also pull any assets that appear in transactions but not yet in assets table
    cur.execute("""
        SELECT DISTINCT from_asset FROM transactions 
        UNION 
        SELECT DISTINCT to_asset FROM transactions
    """)
    tx_assets = [row[0] for row in cur.fetchall() if row[0]]
    
    all_assets = sorted(set(assets + tx_assets))
    
    if not include_usd:
        all_assets = [a for a in all_assets if a != "USD"]
    
    conn.close()
    return all_assets

def add_new_asset_if_needed(symbol):
    """Auto-register new asset symbols when used in transactions."""
    if not symbol or symbol == "USD":
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO assets (symbol, name, asset_type, unit) VALUES (?, ?, 'crypto', 'units')", 
                (symbol, symbol))
    cur.execute("INSERT OR IGNORE INTO prices (symbol, current_price_usd) VALUES (?, 0)", (symbol,))
    conn.commit()
    conn.close()

def compute_portfolio():
    """
    Process all transactions in chronological order and compute:
    - Current holdings with average cost basis (cost follows swaps)
    - Total realized P/L from sells
    Returns: holdings dict, realized_pnl, total_txns_count
    """
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM transactions ORDER BY timestamp ASC, id ASC", 
        conn
    )
    conn.close()
    
    if df.empty:
        return {}, 0.0, 0
    
    holdings = defaultdict(lambda: {"qty": 0.0, "cost_basis": 0.0})
    realized_pnl = 0.0
    
    for _, row in df.iterrows():
        txn_type = row["txn_type"]
        from_asset = row["from_asset"] if pd.notna(row["from_asset"]) else None
        to_asset = row["to_asset"] if pd.notna(row["to_asset"]) else None
        from_amt = float(row["from_amount"] or 0)
        to_amt = float(row["to_amount"] or 0)
        fee_usd = float(row["fee_usd"] or 0)
        
        if from_asset == "USD" and to_asset:
            # BUY: USD -> Asset. Cost basis added to received asset.
            if to_asset not in holdings:
                holdings[to_asset] = {"qty": 0.0, "cost_basis": 0.0}
            holdings[to_asset]["qty"] += to_amt
            holdings[to_asset]["cost_basis"] += from_amt + fee_usd
            
        elif to_asset == "USD" and from_asset:
            # SELL: Asset -> USD. Realize P/L, reduce cost basis of sold asset.
            if from_asset in holdings and holdings[from_asset]["qty"] > 1e-12:
                cb_per_unit = holdings[from_asset]["cost_basis"] / holdings[from_asset]["qty"]
                cost_removed = cb_per_unit * from_amt
                holdings[from_asset]["qty"] -= from_amt
                holdings[from_asset]["cost_basis"] -= cost_removed
                realized_pnl += (to_amt - cost_removed) - fee_usd
            # If qty insufficient, we still allow (data error or correction) but don't crash
            
        elif from_asset and to_asset and from_asset != "USD" and to_asset != "USD":
            # SWAP: AssetA -> AssetB. Transfer proportional cost basis to new asset.
            if from_asset in holdings and holdings[from_asset]["qty"] > 1e-12:
                cb_per_unit = holdings[from_asset]["cost_basis"] / holdings[from_asset]["qty"]
                cost_transferred = cb_per_unit * from_amt
                holdings[from_asset]["qty"] -= from_amt
                holdings[from_asset]["cost_basis"] -= cost_transferred
                
                if to_asset not in holdings:
                    holdings[to_asset] = {"qty": 0.0, "cost_basis": 0.0}
                holdings[to_asset]["qty"] += to_amt
                holdings[to_asset]["cost_basis"] += cost_transferred + fee_usd
                
        elif from_asset is None and to_asset:
            # DEPOSIT / airdrop / receive (cost basis = 0 by default for free receives)
            if to_asset not in holdings:
                holdings[to_asset] = {"qty": 0.0, "cost_basis": 0.0}
            holdings[to_asset]["qty"] += to_amt
            # Future: support assigned cost via extra column if needed. For now cost=0 + fee if any.
            holdings[to_asset]["cost_basis"] += fee_usd
    
    # Remove dust / zero holdings
    holdings = {k: v for k, v in holdings.items() if v["qty"] > 1e-9}
    
    return dict(holdings), realized_pnl, len(df)

def get_prices():
    """Load current prices into dict."""
    conn = get_connection()
    df = pd.read_sql_query("SELECT symbol, current_price_usd FROM prices", conn)
    conn.close()
    return dict(zip(df["symbol"], df["current_price_usd"]))

def format_currency(val):
    if pd.isna(val) or val is None:
        return "$0.00"
    return f"${val:,.2f}"

def main():
    st.set_page_config(
        page_title="Cost Basis Tracker",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    init_db()
    
    st.title("📊 Cost Basis Tracker")
    st.caption("Track buys • swaps • sells across tokens, DeFi & precious metals. Cost basis travels with your bags.")
    
    # Sidebar info
    with st.sidebar:
        st.markdown("### How it works")
        st.info(
            "Uses **average cost basis**. When you swap ADA → IAG, the USD you originally spent on ADA "
            "is automatically transferred to your IAG bag. You always see your true entry price per token, "
            "even after multiple hops and fees."
        )
        st.markdown("**Example:**")
        st.markdown("- Spend $100 → 100 ADA")
        st.markdown("- Swap 100 ADA → 50 IAG")
        st.markdown("- Your IAG cost basis = **$2.00 / IAG** (math done for you)")
        
        st.divider()
        st.markdown("**v1.0** — Simple & solid foundation. Ready to evolve (CSV import, charts, price APIs, tax export, APK, etc.)")
        st.markdown("Data lives in `cost_basis_tracker.db` next to this script. **Backup it!**")
    
    holdings, realized_pnl, txn_count = compute_portfolio()
    prices = get_prices()
    
    # ========== DASHBOARD TAB ==========
    tab_dash, tab_add, tab_history, tab_prices, tab_assets = st.tabs([
        "📈 Dashboard", "➕ Add Transaction", "📜 History", "💵 Prices", "🪙 Assets"
    ])
    
    with tab_dash:
        st.header("Portfolio Overview")
        
        if not holdings:
            st.warning("No holdings yet. Add your first transaction in the 'Add Transaction' tab!")
            st.stop()
        
        # Calculate metrics
        total_cost = sum(h["cost_basis"] for h in holdings.values())
        portfolio_value = 0.0
        for sym, h in holdings.items():
            price = prices.get(sym, 0.0)
            portfolio_value += h["qty"] * price
        unrealized_pnl = portfolio_value - total_cost
        
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Cost Basis", format_currency(total_cost), 
                    help="Net USD you've effectively paid for current holdings (after all swaps)")
        col2.metric("Est. Portfolio Value", format_currency(portfolio_value),
                    delta=format_currency(unrealized_pnl),
                    delta_color="normal" if unrealized_pnl >= 0 else "inverse",
                    help="Based on prices you set in the Prices tab")
        col3.metric("Unrealized P/L", format_currency(unrealized_pnl),
                    help="Current market value minus your cost basis")
        col4.metric("Realized P/L (Sells)", format_currency(realized_pnl),
                    help="Profits/losses locked in from sells to USD")
        
        st.divider()
        
        # Holdings table
        st.subheader("Current Holdings & Cost Basis")
        
        table_data = []
        for sym in sorted(holdings.keys()):
            h = holdings[sym]
            price = prices.get(sym, 0.0)
            value = h["qty"] * price
            pnl = value - h["cost_basis"]
            avg_cost = h["cost_basis"] / h["qty"] if h["qty"] > 0 else 0
            pct = (value / portfolio_value * 100) if portfolio_value > 0 else 0
            
            table_data.append({
                "Asset": sym,
                "Qty": round(h["qty"], 6),
                "Avg Cost / Unit": round(avg_cost, 6),
                "Total Cost Basis": round(h["cost_basis"], 2),
                "Current Price": round(price, 4),
                "Est. Value": round(value, 2),
                "Unrealized P/L": round(pnl, 2),
                "% Portfolio": f"{pct:.1f}%"
            })
        
        df_hold = pd.DataFrame(table_data)
        
        # Color code P/L
        def color_pnl(val):
            if isinstance(val, (int, float)):
                color = "green" if val >= 0 else "red"
                return f"color: {color}"
            return ""
        
        st.dataframe(
            df_hold.style.applymap(color_pnl, subset=["Unrealized P/L"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Avg Cost / Unit": st.column_config.NumberColumn(format="%.6f"),
                "Total Cost Basis": st.column_config.NumberColumn(format="$%.2f"),
                "Current Price": st.column_config.NumberColumn(format="%.4f"),
                "Est. Value": st.column_config.NumberColumn(format="$%.2f"),
                "Unrealized P/L": st.column_config.NumberColumn(format="$%.2f"),
            }
        )
        
        st.caption(f"Based on {txn_count} transactions • Cost basis uses average method with full transfer on swaps • Prices last set by you")
        
        with st.expander("📖 What does 'Total Cost Basis' really mean?"):
            st.markdown("""
            This is the **true net capital** you've deployed into your current bags.
            
            - Every time you buy with USD → that USD is added to the asset's cost basis.
            - Every time you **swap**, the cost basis travels with the tokens to the new asset.
            - Sells remove the proportional cost basis and calculate realized P/L.
            - Deposits (airdrops, rewards) currently add 0 cost (you can note FMV in notes if needed for taxes).
            
            This gives you accurate **per-token entry price** no matter how many hops you took (e.g. USD → ADA → IAG on Maya or Minswap).
            """)
    
    # ========== ADD TRANSACTION TAB ==========
    with tab_add:
        st.header("Add New Transaction")
        st.markdown("All math for cost basis is handled automatically when you view the Dashboard.")
        
        with st.form("add_txn", clear_on_submit=True):
            # Date & Type
            c1, c2 = st.columns([1, 2])
            with c1:
                txn_date = st.date_input("Date of transaction", value=date.today())
                txn_time = st.time_input("Time (local)", value=datetime.now().time())
            with c2:
                txn_type = st.selectbox(
                    "Type",
                    ["Buy with USD", "Sell for USD", "Swap between assets", "Deposit / Airdrop / Receive"],
                    help="Choose the nature of the transaction. Cost basis logic differs per type."
                )
            
            known = get_known_assets(include_usd=False)
            known_with_usd = get_known_assets(include_usd=True)
            
            from_asset = to_asset = None
            from_amt = to_amt = fee_usd = usd_val = 0.0
            notes = ""
            
            if txn_type == "Buy with USD":
                st.markdown("**Buy crypto / metal / asset with fiat USD**")
                to_asset = st.selectbox("Asset you received", options=known + ["(custom new asset)"], index=0)
                if to_asset == "(custom new asset)":
                    to_asset = st.text_input("New asset symbol (e.g. NEWTOKEN)", value="").upper().strip()
                
                to_amt = st.number_input("Amount received", min_value=0.0, step=0.000001, format="%.8f")
                usd_val = st.number_input("USD spent (total out of pocket, including gas/fees if paid in fiat)", min_value=0.0, step=0.01, value=0.0)
                fee_usd = st.number_input("Extra fees paid in USD (if any)", min_value=0.0, step=0.01, value=0.0)
                notes = st.text_area("Notes", placeholder="Exchange/wallet used, tx hash, reason, etc.")
                
                from_asset = "USD"
                from_amt = usd_val
            
            elif txn_type == "Sell for USD":
                st.markdown("**Sell asset for USD (realize P/L)**")
                from_asset = st.selectbox("Asset you sold", options=known)
                from_amt = st.number_input("Amount sold", min_value=0.0, step=0.000001, format="%.8f")
                usd_val = st.number_input("USD received (net proceeds)", min_value=0.0, step=0.01)
                fee_usd = st.number_input("Extra fees / gas paid in USD", min_value=0.0, step=0.01, value=0.0)
                notes = st.text_area("Notes", placeholder="Where sold, slippage, etc.")
                
                to_asset = "USD"
                to_amt = usd_val
            
            elif txn_type == "Swap between assets":
                st.markdown("**Swap / Trade one asset for another (cost basis transfers automatically)**")
                c_from, c_to = st.columns(2)
                with c_from:
                    from_asset = st.selectbox("From (sold / swapped out)", options=known)
                    from_amt = st.number_input("Amount sent out", min_value=0.0, step=0.000001, format="%.8f", key="swap_from")
                with c_to:
                    to_asset = st.selectbox("To (received)", options=known + ["(custom new asset)"], index=0)
                    if to_asset == "(custom new asset)":
                        to_asset = st.text_input("New asset symbol", value="").upper().strip()
                    to_amt = st.number_input("Amount received", min_value=0.0, step=0.000001, format="%.8f", key="swap_to")
                
                fee_usd = st.number_input("Fees paid in USD (or 0 if paid in asset - approximate by adjusting amounts)", min_value=0.0, step=0.01, value=0.0)
                notes = st.text_area("Notes", placeholder="DEX used (Minswap, etc.), pool, slippage %")
            
            elif txn_type == "Deposit / Airdrop / Receive":
                st.markdown("**Receive asset for free or off-chain (cost basis = 0 by default)**")
                to_asset = st.selectbox("Asset received", options=known + ["(custom new asset)"], index=0)
                if to_asset == "(custom new asset)":
                    to_asset = st.text_input("New asset symbol", value="").upper().strip()
                
                to_amt = st.number_input("Amount received", min_value=0.0, step=0.000001, format="%.8f")
                fee_usd = st.number_input("Fees paid in USD to receive (rare)", min_value=0.0, step=0.01, value=0.0)
                notes = st.text_area("Notes", placeholder="Airdrop, staking reward, gift, mined, P2P receive, etc. Add FMV at receive for tax notes if needed.")
                
                from_asset = None
                from_amt = 0.0
            
            submitted = st.form_submit_button("✅ Add Transaction", type="primary", use_container_width=True)
            
            if submitted:
                if not to_asset and txn_type != "Sell for USD":
                    st.error("Please specify the asset involved.")
                elif from_amt == 0 and to_amt == 0:
                    st.error("Amounts cannot both be zero.")
                else:
                    ts = datetime.combine(txn_date, txn_time).isoformat(sep=" ")
                    
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO transactions 
                        (timestamp, txn_type, from_asset, from_amount, to_asset, to_amount, fee_usd, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (ts, txn_type, from_asset, from_amt, to_asset, to_amt, fee_usd, notes.strip()))
                    conn.commit()
                    conn.close()
                    
                    # Auto register any new assets
                    add_new_asset_if_needed(from_asset)
                    add_new_asset_if_needed(to_asset)
                    
                    st.success(f"Transaction recorded: {txn_type} • {from_asset or ''} → {to_asset or ''}")
                    st.balloons()
                    st.rerun()
    
    # ========== HISTORY TAB ==========
    with tab_history:
        st.header("Transaction History")
        st.caption("Your immutable log. Cost basis calculations re-process everything from here on every Dashboard load.")
        
        conn = get_connection()
        hist_df = pd.read_sql_query(
            "SELECT id, timestamp, txn_type, from_asset, from_amount, to_asset, to_amount, fee_usd, notes FROM transactions ORDER BY timestamp DESC, id DESC",
            conn
        )
        conn.close()
        
        if hist_df.empty:
            st.info("No transactions yet.")
        else:
            # Nice display
            hist_df_display = hist_df.copy()
            hist_df_display["timestamp"] = pd.to_datetime(hist_df_display["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")
            
            st.dataframe(
                hist_df_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", width="small"),
                    "from_amount": st.column_config.NumberColumn(format="%.6f"),
                    "to_amount": st.column_config.NumberColumn(format="%.6f"),
                    "fee_usd": st.column_config.NumberColumn(format="$%.2f"),
                }
            )
            
            st.divider()
            st.subheader("Delete a transaction (use with caution - this changes history)")
            del_id = st.number_input("Enter Transaction ID to permanently delete", min_value=1, step=1)
            if st.button("🗑️ Delete Transaction", type="secondary"):
                if del_id:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM transactions WHERE id = ?", (del_id,))
                    conn.commit()
                    conn.close()
                    st.warning(f"Deleted transaction #{del_id}. Dashboard will recalculate.")
                    st.rerun()
    
    # ========== PRICES TAB ==========
    with tab_prices:
        st.header("Current Asset Prices (USD)")
        st.caption("These are used only for the Dashboard valuation and P/L estimates. Update anytime. No API yet — manual for full control & privacy.")
        
        conn = get_connection()
        price_df = pd.read_sql_query(
            "SELECT symbol, current_price_usd, updated_at FROM prices ORDER BY symbol", 
            conn
        )
        conn.close()
        
        if not price_df.empty:
            edited_prices = st.data_editor(
                price_df,
                column_config={
                    "symbol": st.column_config.TextColumn(disabled=True),
                    "current_price_usd": st.column_config.NumberColumn(
                        "Current Price (USD)", min_value=0.0, step=0.0001, format="%.4f"
                    ),
                    "updated_at": st.column_config.TextColumn("Last Updated", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
                key="prices_editor"
            )
            
            if st.button("💾 Save Price Changes", type="primary"):
                conn = get_connection()
                cur = conn.cursor()
                now = datetime.now().isoformat()
                for _, row in edited_prices.iterrows():
                    cur.execute(
                        "UPDATE prices SET current_price_usd = ?, updated_at = ? WHERE symbol = ?",
                        (float(row["current_price_usd"]), now, row["symbol"])
                    )
                conn.commit()
                conn.close()
                st.success("Prices saved! Dashboard will use the new values.")
                st.rerun()
        
        st.info("Tip: For precious metals, use current spot price per oz (or whatever unit you track). For illiquid tokens, use recent trade price or your own valuation.")
    
    # ========== ASSETS TAB ==========
    with tab_assets:
        st.header("Asset Registry")
        st.caption("Metadata for display and future features (icons, categories, etc.). New assets are auto-added when you use them in transactions.")
        
        conn = get_connection()
        asset_df = pd.read_sql_query(
            "SELECT symbol, name, asset_type, unit, notes FROM assets ORDER BY asset_type, symbol", 
            conn
        )
        conn.close()
        
        st.dataframe(asset_df, use_container_width=True, hide_index=True)
        
        st.divider()
        st.subheader("Add / Update Custom Asset")
        with st.form("add_asset"):
            new_sym = st.text_input("Symbol (e.g. MYCOIN)").upper().strip()
            new_name = st.text_input("Display Name (optional)")
            new_type = st.selectbox("Type", ["crypto", "metal", "stock", "other", "fiat"])
            new_unit = st.text_input("Unit label (e.g. tokens, oz, shares)", value="units")
            new_notes = st.text_area("Notes")
            
            if st.form_submit_button("Add / Update Asset"):
                if new_sym:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT OR REPLACE INTO assets (symbol, name, asset_type, unit, notes)
                        VALUES (?, ?, ?, ?, ?)
                    """, (new_sym, new_name or new_sym, new_type, new_unit, new_notes))
                    cur.execute("INSERT OR IGNORE INTO prices (symbol) VALUES (?)", (new_sym,))
                    conn.commit()
                    conn.close()
                    st.success(f"Asset {new_sym} registered.")
                    st.rerun()
    
    # Footer
    st.divider()
    st.caption("Made for evolving portfolios • Your data stays local in the .db file • v1.0 • Feedback welcome to improve!")

if __name__ == "__main__":
    main()
