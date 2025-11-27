import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go

# --- 頁面設定 ---
st.set_page_config(page_title="策略 vs Buy & Hold (含 MDD)", layout="wide")
st.title("⚖️ 策略績效 vs Buy & Hold (含風險評估)")
st.markdown("比較「均線策略」與「買入持有」的報酬率 (ROI) 與 最大回撤 (MDD)。")

# --- 1. 側邊欄：數據設定 ---
st.sidebar.header("1. 數據設定")
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)
limit = st.sidebar.slider("回測 K 棒數量", 200, 1000, 365)
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

# 計算回撤的輔助函數
def calculate_mdd(equity_series):
    # 1. 計算累積最大資產 (High Water Mark)
    running_max = equity_series.cummax()
    # 2. 計算當前資產與最高點的落差比例
    drawdown = (equity_series - running_max) / running_max
    # 3. 取最小的值 (因為是負數，越小代表跌越多)
    mdd = drawdown.min() * 100 
    return mdd

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
    
    for i, row in df.iterrows():
        price = row['close']
        if row['Signal'] == 1 and position == 0:
            position = balance / price
            balance = 0
            trades += 1
        elif row['Signal'] == -1 and position > 0:
            balance = position * price
            position = 0
            trades += 1
        equity.append(balance + (position * price))
        
    df['Equity'] = equity
    final_equity = equity[-1]
    roi = ((final_equity - capital) / capital) * 100
    
    # 計算 MDD
    mdd = calculate_mdd(pd.Series(equity))
    
    return final_equity, roi, trades, df['Equity'], mdd

# --- 主程式 ---
st.write(f"正在分析 **{selected_symbol}**...")
raw_data, source = get_data(selected_symbol, timeframe, limit)

if raw_data is not None:
    # 1. 計算 Buy and Hold 數據
    start_price = raw_data['close'].iloc[0]
    # B&H 的資產曲線就是價格走勢的映射
    bh_equity_curve = initial_capital * (raw_data['close'] / start_price)
    bh_final_equity = bh_equity_curve.iloc[-1]
    bh_roi = ((bh_final_equity - initial_capital) / initial_capital) * 100
    bh_mdd = calculate_mdd(bh_equity_curve)

    # 2. 執行策略 A & B
    eq_a, roi_a, trades_a, curve_a, mdd_a = run_strategy(raw_data, short_a, long_a, ma_type_a, initial_capital)
    eq_b, roi_b, trades_b, curve_b, mdd_b = run_strategy(raw_data, short_b, long_b, ma_type_b, initial_capital)
    
    # --- 顯示績效 ---
    st.subheader("🏆 績效與風險分析")
    
    col1, col2, col3 = st.columns(3)
    
    # 顯示顏色設定 (MDD 越小(負越多)越危險，用紅色表示)
    
    with col1:
        st.info(f"🔵 **策略 A**")
        st.metric("ROI (報酬率)", f"{roi_a:.2f}%", delta=f"{roi_a - bh_roi:.2f}% vs B&H")
        st.metric("MDD (最大回撤)", f"{mdd_a:.2f}%", delta=f"{mdd_a - bh_mdd:.2f}% vs B&H", delta_color="inverse")
        st.write(f"交易次數: {trades_a}")
        
    with col2:
        st.info(f"🟠 **策略 B**")
        st.metric("ROI (報酬率)", f"{roi_b:.2f}%", delta=f"{roi_b - bh_roi:.2f}% vs B&H")
        st.metric("MDD (最大回撤)", f"{mdd_b:.2f}%", delta=f"{mdd_b - bh_mdd:.2f}% vs B&H", delta_color="inverse")
        st.write(f"交易次數: {trades_b}")

    with col3:
        st.markdown("### 🏳️ **Buy & Hold (基準)**")
        st.metric("ROI (報酬率)", f"{bh_roi:.2f}%")
        st.metric("MDD (最大回撤)", f"{bh_mdd:.2f}%", help="如果一直持有不動，資產最多曾縮水多少")
        
        # 簡單評語
        mdd_winner = "策略 A" if mdd_a > mdd_b else "策略 B" # MDD 數字比較大(接近0)比較好
        st.caption(f"🛡️ 風險控制王者: {mdd_winner}")

    # --- 資產曲線圖 ---
    st.subheader("📈 資產成長曲線")
    fig_eq = go.Figure()
    
    fig_eq.add_trace(go.Scatter(x=raw_data['timestamp'], y=curve_a, mode='lines', name=f'策略 A', line=dict(color='#00BFFF', width=2)))
    fig_eq.add_trace(go.Scatter(x=raw_data['timestamp'], y=curve_b, mode='lines', name=f'策略 B', line=dict(color='#FFA500', width=2)))
    fig_eq.add_trace(go.Scatter(x=raw_data['timestamp'], y=bh_equity_curve, mode='lines', name='Buy & Hold', line=dict(color='gray', width=2, dash='dash')))
    
    fig_eq.add_hline(y=initial_capital, line_color="white", line_width=1, annotation_text="本金")
    fig_eq.update_layout(template='plotly_dark', height=500, title="策略 vs B&H 資產走勢")
    st.plotly_chart(fig_eq, use_container_width=True)

    # --- 詳細數據 ---
    with st.expander("查看數據表格"):
        st.dataframe(pd.DataFrame({
            "日期": raw_data['timestamp'],
            "價格": raw_data['close'],
            "策略A資產": curve_a,
            "策略B資產": curve_b,
            "B&H資產": bh_equity_curve
        }).sort_values("日期", ascending=False))

else:
    st.error("無法取得數據，請稍後再試。")
