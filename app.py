import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go

# --- 頁面設定 ---
st.set_page_config(page_title="策略回測 (天數版)", layout="wide")
st.title("📊 策略回測系統：自訂回測天數")

# --- 1. 側邊欄：數據來源 ---
st.sidebar.header("1. 數據設定")
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

# --- 修改重點：將 K 棒數量改為天數 ---
timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)
backtest_days = st.sidebar.slider("回測天數 (Days)", min_value=7, max_value=365, value=30)
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

# 輔助函數：將天數轉換為 K 棒數量
def calculate_limit_from_days(timeframe, days):
    # 定義每個週期包含多少分鐘
    tf_minutes = {
        "15m": 15,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
        "1w": 10080
    }
    minutes_per_candle = tf_minutes.get(timeframe, 1440)
    total_minutes = days * 24 * 60
    
    # 計算需要多少根 K 棒
    required_limit = int(total_minutes / minutes_per_candle)
    
    # API 安全限制 (Binance 公開 API 通常上限為 1000)
    max_api_limit = 1000
    
    if required_limit > max_api_limit:
        return max_api_limit, True # 回傳 True 代表被截斷了
    return required_limit, False

@st.cache_data(ttl=600)
def get_data(symbol, timeframe, limit):
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
    
    df['Signal'] = 0
    df.loc[(df[col_s] > df[col_l]) & (df[col_s].shift(1) <= df[col_l].shift(1)), 'Signal'] = 1
    df.loc[(df[col_s] < df[col_l]) & (df[col_s].shift(1) >= df[col_l].shift(1)), 'Signal'] = -1
    
    balance = capital
    position = 0
    equity = []
    trades = 0
    trade_log = [] 
    current_entry_price = 0
    current_entry_time = None
    buy_signals = []
    sell_signals = []
    
    for i, row in df.iterrows():
        price = row['close']
        time = row['timestamp']
        if row['Signal'] == 1 and position == 0:
            position = balance / price
            balance = 0
            trades += 1
            current_entry_price = price
            current_entry_time = time
            buy_signals.append((time, price))
        elif row['Signal'] == -1 and position > 0:
            balance = position * price
            position = 0
            trades += 1
            sell_signals.append((time, price))
            pnl = (price - current_entry_price) / current_entry_price * 100
            trade_log.append({"買入時間": current_entry_time, "買入價格": current_entry_price, "賣出時間": time, "賣出價格": price, "單筆獲利 (%)": pnl})
            
        equity.append(balance + (position * price))
        
    df['Equity'] = equity
    final_equity = equity[-1]
    roi = ((final_equity - capital) / capital) * 100
    mdd = calculate_mdd(pd.Series(equity))
    df_log = pd.DataFrame(trade_log)
    
    return {"final_equity": final_equity, "roi": roi, "trades": trades, "mdd": mdd, "df": df, "buys": buy_signals, "sells": sell_signals, "trade_log": df_log}

# --- 主程式 ---

# 1. 計算限制
limit, is_capped = calculate_limit_from_days(timeframe, backtest_days)

st.write(f"正在分析 **{selected_symbol}**...")
if is_capped:
    st.warning(f"⚠️ 注意：由於交易所 API 限制單次最多 1000 根，**{timeframe}** 週期無法讀取完整的 **{backtest_days}** 天。目前已自動載入最近的 **1000** 根 K 棒。")
else:
    st.info(f"✅ 已成功載入 **{backtest_days}** 天的 **{timeframe}** 數據 ({limit} 根 K 棒)。")

raw_data, source = get_data(selected_symbol, timeframe, limit)

if raw_data is not None:
    # 執行回測邏輯 (與之前相同)
    bh_equity = initial_capital * (raw_data['close'] / raw_data['close'].iloc[0])
    bh_roi = ((bh_equity.iloc[-1] - initial_capital) / initial_capital) * 100
    bh_mdd = calculate_mdd(bh_equity)

    res_a = run_strategy(raw_data, short_a, long_a, ma_type_a, initial_capital)
    res_b = run_strategy(raw_data, short_b, long_b, ma_type_b, initial_capital)
    
    # 顯示日期範圍
    start_date = raw_data['timestamp'].iloc[0].strftime('%Y-%m-%d')
    end_date = raw_data['timestamp'].iloc[-1].strftime('%Y-%m-%d')
    st.caption(f"📅 實際回測區間：{start_date} 至 {end_date} (數據來源: {source})")

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

    # --- 詳細分析 ---
    st.markdown("---")
    st.subheader("🔎 詳細進出場分析")
    view_option = st.radio("選擇要查看的策略詳情：", ("策略 A", "策略 B"), horizontal=True)
    target_res = res_a if view_option == "策略 A" else res_b
    target_short = short_a if view_option == "策略 A" else short_b
    target_long = long_a if view_option == "策略 A" else long_b
    
    tab1, tab2 = st.tabs(["📈 K 線圖與買賣點", "📋 交易明細表"])

    with tab1:
        fig_k = go.Figure()
        fig_k.add_trace(go.Candlestick(x=target_res['df']['timestamp'], open=target_res['df']['open'], high=target_res['df']['high'], low=target_res['df']['low'], close=target_res['df']['close'], name='價格'))
        fig_k.add_trace(go.Scatter(x=target_res['df']['timestamp'], y=target_res['df'][f'MA_{target_short}'], line=dict(color='orange', width=1), name=f'MA {target_short}'))
        fig_k.add_trace(go.Scatter(x=target_res['df']['timestamp'], y=target_res['df'][f'MA_{target_long}'], line=dict(color='blue', width=1), name=f'MA {target_long}'))
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
            styled_df = target_res['trade_log'].style.format({"買入價格": "${:.2f}", "賣出價格": "${:.2f}", "單筆獲利 (%)": "{:.2f}%"}).applymap(lambda v: 'color: green' if v > 0 else 'color: red', subset=['單筆獲利 (%)'])
            st.dataframe(styled_df, use_container_width=True)
        else:
            st.warning("無交易紀錄")

else:
    st.error("無法取得數據，請稍後再試。")
