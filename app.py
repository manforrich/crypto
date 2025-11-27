import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go

# --- 頁面設定 ---
st.set_page_config(page_title="加密貨幣策略競技場", layout="wide")
st.title("⚔️ MA 策略競技場：A/B 測試系統")
st.markdown("設定兩組不同的均線策略，直接回測比較哪一組在過去表現更好。")

# --- 1. 側邊欄：數據來源 ---
st.sidebar.header("1. 數據設定")
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)
limit = st.sidebar.slider("回測 K 棒數量", 200, 1000, 365)
initial_capital = st.sidebar.number_input("初始本金 (USDT)", value=10000)

st.sidebar.markdown("---")

# --- 2. 側邊欄：策略 A 設定 ---
st.sidebar.subheader("🔵 策略 A 設定")
ma_type_a = st.sidebar.selectbox("均線種類 A", ["SMA (簡單)", "EMA (指數)"], key='type_a')
short_a = st.sidebar.number_input("短週期 A", min_value=1, value=5, key='short_a')
long_a = st.sidebar.number_input("長週期 A", min_value=1, value=20, key='long_a')

st.sidebar.markdown("---")

# --- 3. 側邊欄：策略 B 設定 ---
st.sidebar.subheader("🟠 策略 B 設定")
ma_type_b = st.sidebar.selectbox("均線種類 B", ["SMA (簡單)", "EMA (指數)"], key='type_b', index=0)
short_b = st.sidebar.number_input("短週期 B", min_value=1, value=10, key='short_b')
long_b = st.sidebar.number_input("長週期 B", min_value=1, value=60, key='long_b')

# --- 函數：獲取數據 (抗封鎖) ---
@st.cache_data(ttl=600) # 加入快取，避免切換策略時一直重抓
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

# --- 函數：計算均線 ---
def calculate_ma(series, window, ma_type):
    if "EMA" in ma_type:
        return series.ewm(span=window, adjust=False).mean()
    return series.rolling(window).mean()

# --- 函數：執行單一策略回測 ---
def run_strategy(df_input, short_w, long_w, ma_type, capital):
    df = df_input.copy() # 複製一份以免影響原始資料
    
    # 計算指標
    col_short = f'MA_{short_w}'
    col_long = f'MA_{long_w}'
    df[col_short] = calculate_ma(df['close'], short_w, ma_type)
    df[col_long] = calculate_ma(df['close'], long_w, ma_type)
    
    # 產生訊號
    df['Signal'] = 0
    # 黃金交叉
    df.loc[(df[col_short] > df[col_long]) & (df[col_short].shift(1) <= df[col_long].shift(1)), 'Signal'] = 1
    # 死亡交叉
    df.loc[(df[col_short] < df[col_long]) & (df[col_short].shift(1) >= df[col_long].shift(1)), 'Signal'] = -1
    
    # 模擬交易
    balance = capital
    position = 0
    equity = []
    trades = 0
    
    for i, row in df.iterrows():
        price = row['close']
        # 買入
        if row['Signal'] == 1 and position == 0:
            position = balance / price
            balance = 0
            trades += 1
        # 賣出
        elif row['Signal'] == -1 and position > 0:
            balance = position * price
            position = 0
            trades += 1
            
        current_equity = balance + (position * price)
        equity.append(current_equity)
        
    df['Equity'] = equity
    final_equity = equity[-1]
    roi = ((final_equity - capital) / capital) * 100
    
    return final_equity, roi, trades, df['Equity']

# --- 主程式執行 ---
st.write(f"正在分析 **{selected_symbol}**...")
raw_data, source = get_data(selected_symbol, timeframe, limit)

if raw_data is not None:
    # 執行策略 A
    eq_a, roi_a, trades_a, curve_a = run_strategy(raw_data, short_a, long_a, ma_type_a, initial_capital)
    # 執行策略 B
    eq_b, roi_b, trades_b, curve_b = run_strategy(raw_data, short_b, long_b, ma_type_b, initial_capital)
    
    # --- 1. 績效對決看板 ---
    st.subheader("🏆 策略績效對決")
    
    col1, col2, col3 = st.columns(3)
    
    # 輔助函數：顯示比較顏色
    def get_color(val1, val2):
        if val1 > val2: return "normal" # 綠色/贏
        if val1 < val2: return "off"    # 灰色/輸
        return "off"

    with col1:
        st.info(f"🔵 **策略 A** ({ma_type_a} {short_a} vs {long_a})")
        st.metric("總報酬率 (ROI)", f"{roi_a:.2f}%")
        st.metric("最終資產", f"${eq_a:,.0f}")
        st.write(f"交易次數: {trades_a}")

    with col2:
        st.info(f"🟠 **策略 B** ({ma_type_b} {short_b} vs {long_b})")
        st.metric("總報酬率 (ROI)", f"{roi_b:.2f}%", delta_color="normal") 
        st.metric("最終資產", f"${eq_b:,.0f}")
        st.write(f"交易次數: {trades_b}")
        
    with col3:
        st.warning("📊 **勝負分析**")
        diff = eq_a - eq_b
        winner = "策略 A" if diff > 0 else "策略 B"
        st.metric("獲勝者", winner)
        st.metric("資產差距", f"${abs(diff):,.0f}")
        st.write("提示：交易次數過多可能會增加手續費成本(本模型暫未計入手續費)。")

    # --- 2. 資產曲線比較圖 (最重要) ---
    st.subheader("📈 資產累積曲線比較 (Equity Curve)")
    fig_eq = go.Figure()
    
    # 策略 A 曲線 (藍色)
    fig_eq.add_trace(go.Scatter(
        x=raw_data['timestamp'], y=curve_a, 
        mode='lines', name=f'策略 A ({short_a}/{long_a})',
        line=dict(color='#00BFFF', width=2)
    ))
    
    # 策略 B 曲線 (橘色)
    fig_eq.add_trace(go.Scatter(
        x=raw_data['timestamp'], y=curve_b, 
        mode='lines', name=f'策略 B ({short_b}/{long_b})',
        line=dict(color='#FFA500', width=2)
    ))
    
    # 本金基準線
    fig_eq.add_hline(y=initial_capital, line_dash="dash", line_color="white", annotation_text="本金")
    
    fig_eq.update_layout(template='plotly_dark', height=500, title="如果用 1萬 USDT 投資，誰賺比較多？")
    st.plotly_chart(fig_eq, use_container_width=True)

    # --- 3. K線圖檢視 (以策略 A 為主) ---
    with st.expander("查看 K 線圖與買賣點 (以策略 A 為範例)"):
        # 這裡為了畫面簡潔，只畫出策略 A 的進出點供參考
        # 重新計算一次策略 A 的詳細數據
        df_a = raw_data.copy()
        df_a['MA1'] = calculate_ma(df_a['close'], short_a, ma_type_a)
        df_a['MA2'] = calculate_ma(df_a['close'], long_a, ma_type_a)
        
        fig_k = go.Figure()
        fig_k.add_trace(go.Candlestick(x=df_a['timestamp'], open=df_a['open'], high=df_a['high'], low=df_a['low'], close=df_a['close'], name='價格'))
        fig_k.add_trace(go.Scatter(x=df_a['timestamp'], y=df_a['MA1'], line=dict(color='#00BFFF', width=1), name=f'MA {short_a}'))
        fig_k.add_trace(go.Scatter(x=df_a['timestamp'], y=df_a['MA2'], line=dict(color='white', width=1, dash='dot'), name=f'MA {long_a}'))
        
        fig_k.update_layout(template='plotly_dark', height=500, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig_k, use_container_width=True)

else:
    st.error("無法取得數據，請檢查網路或稍後再試。")
