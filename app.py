import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go

# --- 網頁基本設定 ---
st.set_page_config(page_title="加密貨幣追蹤 + MA線", layout="wide")
st.title("📈 加密貨幣趨勢儀表板 (含 MA 分析)")

# --- 側邊欄設定 ---
st.sidebar.header("1. 數據設定")
# 提供常見交易對
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT']
selected_symbol = st.sidebar.selectbox("選擇交易對", common_pairs)
custom_symbol = st.sidebar.text_input("或自定義 (如 BNB/USDT)", "").upper()
if custom_symbol:
    selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["1m", "5m", "15m", "1h", "4h", "1d", "1w"], index=5)
limit = st.sidebar.slider("K棒數量", 50, 500, 200)

st.sidebar.markdown("---")
st.sidebar.header("2. 技術指標設定 (MA)")
# 讓使用者設定兩條均線
ma_short_period = st.sidebar.number_input("短週期 MA (如 20)", min_value=1, value=20)
ma_long_period = st.sidebar.number_input("長週期 MA (如 60)", min_value=1, value=60)

# --- 核心函數：智慧型獲取數據 (抗封鎖版) ---
def get_crypto_data(symbol, timeframe, limit):
    # 定義嘗試順序：Binance -> Binance US -> Kraken
    exchanges_to_try = [
        ('Binance', ccxt.binance()),
        ('Binance US', ccxt.binanceus()),
        ('Kraken', ccxt.kraken())
    ]
    
    for name, exchange in exchanges_to_try:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df, name
        except (ccxt.BadSymbol, Exception):
            continue
            
    return None, None

# --- 主程式邏輯 ---
st.write(f"正在搜尋 **{selected_symbol}** 的數據...")
data, source_name = get_crypto_data(selected_symbol, timeframe, limit)

if data is not None:
    # --- 1. 計算移動平均線 (MA) ---
    # 使用 Pandas 的 rolling().mean() 快速計算
    data[f'MA_{ma_short_period}'] = data['close'].rolling(window=ma_short_period).mean()
    data[f'MA_{ma_long_period}'] = data['close'].rolling(window=ma_long_period).mean()

    # --- 2. 顯示頂部資訊 ---
    latest = data.iloc[-1]
    prev = data.iloc[-2]
    change = latest['close'] - prev['close']
    pct = (change / prev['close']) * 100
    
    st.success(f"✅ 數據來源: {source_name}")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(f"{selected_symbol} 價格", f"{latest['close']:.4f}", f"{pct:.2f}%")
    with col2:
        st.metric("成交量", f"{latest['volume']:.2f}")
    with col3:
        # 顯示最新 MA 數值
        ma_s_val = latest[f'MA_{ma_short_period}']
        st.metric(f"MA {ma_short_period}", f"{ma_s_val:.4f}" if not pd.isna(ma_s_val) else "計算中...")
    with col4:
        ma_l_val = latest[f'MA_{ma_long_period}']
        st.metric(f"MA {ma_long_period}", f"{ma_l_val:.4f}" if not pd.isna(ma_l_val) else "計算中...")

    # --- 3. 繪製圖表 (Candlestick + Line) ---
    fig = go.Figure()

    # K線圖 (主圖)
    fig.add_trace(go.Candlestick(
        x=data['timestamp'],
        open=data['open'], high=data['high'],
        low=data['low'], close=data['close'],
        name='K線'
    ))

    # MA 短週期線 (橘色)
    fig.add_trace(go.Scatter(
        x=data['timestamp'], 
        y=data[f'MA_{ma_short_period}'],
        mode='lines',
        name=f'MA {ma_short_period}',
        line=dict(color='#FFA500', width=1.5) # Orange
    ))

    # MA 長週期線 (藍色)
    fig.add_trace(go.Scatter(
        x=data['timestamp'], 
        y=data[f'MA_{ma_long_period}'],
        mode='lines',
        name=f'MA {ma_long_period}',
        line=dict(color='#00BFFF', width=1.5) # Deep Sky Blue
    ))

    # 圖表美化設定
    fig.update_layout(
        title=f'{selected_symbol} 價格走勢 ({timeframe})',
        yaxis_title='價格',
        template='plotly_dark',
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1) # 圖例放上面
    )
    
    # 移除下方的範圍滑桿(Range Slider)讓畫面更乾淨
    fig.update_layout(xaxis_rangeslider_visible=False)

    st.plotly_chart(fig, use_container_width=True)
    
    # 選項：顯示原始數據
    with st.expander("查看詳細數據表格"):
        st.dataframe(data.sort_index(ascending=False).head(100))

else:
    st.error("❌ 無法獲取數據，請嘗試更換交易對名稱 (例如使用 BTC/USD)。")
