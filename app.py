import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go
from datetime import datetime

# --- 網頁設定 ---
st.set_page_config(page_title="Binance 加密貨幣追蹤", layout="wide")
st.title("🔶 Binance 加密貨幣即時儀表板")

# --- 初始化 Binance ---
# 使用 ccxt 連接 Binance 公開 API (不需要 API Key 即可獲取價格)
exchange = ccxt.karken()

# --- 側邊欄設定 ---
st.sidebar.header("設定選項")

# 1. 自定義輸入或選擇交易對
# Binance 的符號格式通常是 'BTC/USDT', 'ETH/USDT' 等
common_pairs = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("選擇交易對 (或自行輸入)", common_pairs)

# 讓使用者可以手動輸入其他冷門幣種，例如 'PEPE/USDT'
custom_symbol = st.sidebar.text_input("或是輸入其他交易對 (例如 PEPE/USDT)", "").upper()
if custom_symbol:
    selected_symbol = custom_symbol

# 2. 選擇時間週期 (Timeframe)
# ccxt 支援的週期格式
timeframe_options = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
selected_timeframe = st.sidebar.selectbox("選擇 K 線週期", timeframe_options, index=5) # 預設 1d

# 3. 限制資料筆數 (避免讀取太久)
limit = st.sidebar.slider("載入 K 棒數量", min_value=50, max_value=1000, value=200)

# --- 獲取 Binance 資料函數 ---
def fetch_binance_data(symbol, timeframe, limit):
    try:
        # fetch_ohlcv 獲取 K 線數據: [時間戳, 開盤, 最高, 最低, 收盤, 成交量]
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # 轉換為 DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 處理時間戳 (Binance 給的是毫秒)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df
    except Exception as e:
        return None

# --- 執行資料抓取 ---
st.write(f"正在從 Binance 獲取 **{selected_symbol}** 的 **{selected_timeframe}** 數據...")
data = fetch_binance_data(selected_symbol, selected_timeframe, limit)

if data is not None and not data.empty:
    # --- 顯示即時價格資訊 ---
    latest_close = data['close'].iloc[-1]
    prev_close = data['close'].iloc[-2]
    
    change = latest_close - prev_close
    pct_change = (change / prev_close) * 100
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label=f"{selected_symbol} 最新價格",
            value=f"{latest_close:.4f}", # 顯示到小數點後4位，適合加密貨幣
            delta=f"{change:.4f} ({pct_change:.2f}%)"
        )
    with col2:
        # 計算最高價和最低價 (在選定範圍內)
        highest = data['high'].max()
        st.metric(label="期間最高價", value=f"{highest:.4f}")
    with col3:
        lowest = data['low'].min()
        st.metric(label="期間最低價", value=f"{lowest:.4f}")

    # --- 繪製專業 K 線圖 (Candlestick) ---
    st.subheader(f"📈 {selected_symbol} K 線圖")
    
    fig = go.Figure(data=[go.Candlestick(
        x=data['timestamp'],
        open=data['open'],
        high=data['high'],
        low=data['low'],
        close=data['close'],
        name=selected_symbol
    )])

    # 設定圖表樣式
    fig.update_layout(
        title=f'{selected_symbol} - {selected_timeframe}',
        xaxis_title='時間',
        yaxis_title='價格 (USDT)',
        template='plotly_dark',
        height=600,
        xaxis_rangeslider_visible=False # 隱藏下方的範圍滑桿，讓畫面更清爽
    )

    st.plotly_chart(fig, use_container_width=True)

    # --- 顯示成交量圖 (可選) ---
    with st.expander("查看成交量分析"):
        st.bar_chart(data.set_index('timestamp')['volume'])

else:
    st.error(f"無法獲取數據。請檢查交易對名稱是否正確 (例如 BTC/USDT)，或是 Binance API 暫時無法連線。")
    st.info("提示：如果您輸入的是比較冷門的幣種，請確認它有在 Binance 上架。")
