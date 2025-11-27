import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go

# --- 頁面設定 ---
st.set_page_config(page_title="Binance 策略回測 (K棒版)", layout="wide")
st.title("📊 Binance 策略回測系統 (自訂 K 棒數)")

# --- 1. 側邊欄：數據來源 ---
st.sidebar.header("1. 數據設定")
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)

# --- 修改點：改回直接輸入 K 棒數量 ---
# Binance API 單次上限通常為 1000，所以 max 設為 1000
limit = st.sidebar.slider("回測 K 棒數量", min_value=100, max_value=1000, value=500)

initial_capital = st.sidebar.number_input("初始本金 (USDT)", value=10000)

st.sidebar.markdown("---")

# --- 2. 策略設定 ---
st.sidebar.subheader("🔵 策略 A 設定")
ma_type_a = st.sidebar.selectbox("種類 A", ["SMA", "EMA"], key='type_a')
short_a = st.sidebar.number_input("短週期 A", value=5, key='short_a')
long_a = st.sidebar.number_input("長週期 A", value=20, key='long_a')

st.sidebar.markdown("---")
st.sidebar.subheader("🟠 策略 B 設定")
ma_type_b = st.sidebar.selectbox("種類 B", ["SMA", "EMA"], key='type_b', index=0)
short_b = st.sidebar.number_input("短週期 B", value=10, key='short_b')
long_b = st.sidebar.number_input("長週期 B", value=60, key='long_b')

# --- 函數區 ---
@st.cache_data(ttl=600)
def get_data(symbol, timeframe, limit):
    # 定義交易所清單 (抗封鎖機制)
    exchanges = [('Binance', ccxt.binance()), ('Binance US', ccxt.binanceus()), ('Kraken', ccxt.kraken())]
    for name, exchange in exchanges:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df, name
        except: continue
    return None, None

def calculate_ma(series, window, ma_type):
    if ma_type == "EMA": return series.ewm(span=window, adjust=False).mean()
    return series.rolling(window).mean()

def calculate_mdd(equity_series):
    running_max = equity_series.cummax()
    drawdown = (equity_series - running_max) / running_max
    return drawdown.min() * 100 

def run_strategy(df_input, short_w, long_w, ma_type, capital):
    df = df_input.copy()
    col_s, col_l = f'MA_{short_w}', f'MA_{long_w}'
    df[col_s] = calculate_ma(df['close'], short_w, ma_type)
    df[col_l] = calculate_ma(df['close'], long_w, ma_type)
    
    # 產生訊號
    df['Signal'] = 0
    df.loc[(df[col_s] > df[col_l]) & (df[col_s].shift(1) <= df[col_l].shift(1)), 'Signal'] = 1
    df.loc[(df[col_s] < df[col_l]) & (df[col_s].shift(1) >= df[col_l].shift(1)), 'Signal'] = -1
    
    balance = capital
    position = 0
    equity = []
    trades = 0
    
    # 詳細交易紀錄
    trade_log = [] 
    current_entry_price = 0
    current_entry_time = None
    buy_signals = []
    sell_signals = []
    
    for i, row in df.iterrows():
        price = row['close']
        time = row['timestamp']
        
        # 買入
        if row['Signal'] == 1 and position == 0:
            position = balance / price
            balance = 0
            trades += 1
            current_entry_price = price
            current_entry_time = time
            buy_signals.append((time, price))
            
        # 賣出
        elif row['Signal'] == -1 and position > 0:
            balance = position * price
            position = 0
            trades += 1
            sell_signals.append((time, price))
            
            pnl = (price - current_entry_price) / current_entry_price * 100
            trade_log.append({
                "買入時間": current_entry_time,
                "買入價格": current_entry_price,
                "賣出時間": time,
                "賣出價格": price,
                "單筆獲利 (%)": pnl
            })
            
        equity.append(balance + (position * price))
        
    df['Equity'] = equity
    final_equity = equity[-1]
    roi = ((final_equity - capital) / capital) * 100
    mdd = calculate_mdd(pd.Series(equity))
    
    return {
        "final_equity": final_equity,
        "roi": roi,
        "trades": trades,
        "mdd": mdd,
        "df": df,
        "buys": buy_signals,
        "sells": sell_signals,
        "trade_log": pd.DataFrame(trade_log)
    }

# --- 主程式 ---
st.write(f"正在分析 **{selected_symbol}** (最近 {limit} 根 K 棒)...")
raw_data, source = get_data(selected_symbol, timeframe, limit)

if raw_data is not None:
    # 1. 基準 Buy & Hold
    bh_equity = initial_capital * (raw_data['close'] / raw_data['close'].iloc[0])
    bh_roi = ((bh_equity.iloc[-1] - initial_capital) / initial_capital) * 100
    bh_mdd = calculate_mdd(bh_equity)
    
    # 顯示日期區間
    start_date = raw_data['timestamp'].iloc[0].strftime('%Y-%m-%d')
    end_date = raw_data['timestamp'].iloc[-1].strftime('%Y-%m-%d')
    st.success(f"✅ 成功載入數據 | 來源: {source} | 區間: {start_date} ~ {end_date}")

    # 2. 執行策略
    res_a = run_strategy(raw_data, short_a, long_a, ma_type_a, initial_capital)
    res_b = run_strategy(raw_data, short_b, long_b, ma_type_b, initial_capital)
    
    # --- 績效看板 ---
    st.subheader("🏆 策略績效總覽")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"🔵 策略 A")
        st.metric("ROI", f"{res_a['roi']:.2f}%", f"{res_a['roi']-bh_roi:.2f}% vs B&H")
        st.metric("MDD", f"{res_a['mdd']:.2f}%", delta_color="inverse")
    with col2:
        st.info(f"🟠 策略 B")
        st.metric("ROI", f"{res_b['roi']:.2f}%", f"{res_b['roi']-bh_roi:.2f}% vs B&H")
        st.metric("MDD", f"{res_b['mdd']:.2f}%", delta_color="inverse")
    with col3:
        st.write("### 🏳️ Buy & Hold")
        st.metric("ROI", f"{bh_roi:.2f}%")
        st.metric("MDD", f"{bh_mdd:.2f}%")

    # --- 下方：詳細分析 (Tabs + Radio) ---
    st.markdown("---")
    st.subheader("🔎 詳細進出場分析")
    
    view_option = st.radio("選擇要查看的策略詳情：", ("策略 A", "策略 B"), horizontal=True)
    target_res = res_a if view_option == "策略 A" else res_b
    target_short = short_a if view_option == "策略 A" else short_b
    target_long = long_a if view_option == "策略 A" else long_b
    target_df = target_res['df']
    
    tab1, tab2 = st.tabs(["📈 K 線圖與買賣點", "📋 交易明細表"])

    with tab1:
        fig_k = go.Figure()
        fig_k.add_trace(go.Candlestick(x=target_df['timestamp'], open=target_df['open'], high=target_df['high'], low=target_df['low'], close=target_df['close'], name='價格'))
        fig_k.add_trace(go.Scatter(x=target_df['timestamp'], y=target_df[f'MA_{target_short}'], line=dict(color='orange', width=1), name=f'MA {target_short}'))
        fig_k.add_trace(go.Scatter(x=target_df['timestamp'], y=target_df[f'MA_{target_long}'], line=dict(color='blue', width=1), name=f'MA {target_long}'))
        
        if target_res['buys']:
            bx, by = zip(*target_res['buys'])
            fig_k.add_trace(go.Scatter(x=bx, y=by, mode='markers', name='買進', marker=dict(symbol='triangle-up', size=15, color='#00CC96')))
        if target_res['sells']:
            sx, sy = zip(*target_res['sells'])
            fig_k.add_trace(go.Scatter(x=sx, y=sy, mode='markers', name='賣出', marker=dict(symbol='triangle-down', size=15, color='#EF553B')))
            
        fig_k.update_layout(template='plotly_dark', height=600, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig_k, use_container_width=True)

    with tab2:
        if not target_res['trade_log'].empty:
            st.markdown(f"### {view_option} 歷史交易紀錄")
            styled_df = target_res['trade_log'].style.format({
                "買入價格": "${:.2f}", 
                "賣出價格": "${:.2f}", 
                "單筆獲利 (%)": "{:.2f}%"
            }).applymap(lambda v: 'color: green' if v > 0 else 'color: red', subset=['單筆獲利 (%)'])
            st.dataframe(styled_df, use_container_width=True)
        else:
            st.warning("在此回測期間內，該策略沒有產生任何完整的買賣交易。")

else:
    st.error("無法取得數據，請稍後再試。")
