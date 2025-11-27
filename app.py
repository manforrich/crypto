import streamlit as st
import pandas as pd
import requests
import plotly.graph_objs as go
from datetime import datetime

# --- 網頁設定 ---
st.set_page_config(page_title="Binance 加密貨幣儀表板", layout="wide")

st.title("🔶 Binance 加密貨幣即時追蹤")
st.markdown("數據來源：**Binance (幣安) 公開 API**")

# --- 側邊欄設定 ---
st.sidebar.header("設定選項")

# 1. 選擇加密貨幣 (Binance 的代號通常是 BTCUSDT 這種格式)
crypto_options = {
    "Bitcoin (BTC)": "BTCUSDT",
    "Ethereum (ETH)": "ETHUSDT",
    "Solana (SOL)": "SOLUSDT",
    "Dogecoin (DOGE)": "DOGEUSDT",
    "BNB (BNB)": "BNBUSDT",
    "Cardano (ADA)": "ADAUSDT"
}
selected_crypto = st.sidebar.selectbox("選擇交易對 (USDT)", list(crypto_options.keys()))
symbol = crypto_options[selected_crypto]

# 2. 選擇時間範圍與 K 線週期
# Binance API 需要指定 interval (K線週期) 和 limit (資料筆數)
time_range = st.sidebar.selectbox("選擇時間範圍", ["24小時 (5分K)", "7天 (1小時K)", "30天 (4小時K)", "1年 (日K)"])

# 設定對應的參數
if time_range == "24小時 (5分K)":
    interval = "5m"
    limit = 288  # 12 * 24
elif time_range == "7天 (1小時K)":
    interval = "1h"
    limit = 168  # 24 * 7
elif time_range == "30天 (4小時K)":
    interval = "4h"
    limit = 180  # 6 * 30
else:  # 1年
    interval = "1d"
    limit = 365

# --- 核心函數：從 Binance 抓取資料 ---
@st.cache_data(ttl=60) # 設定快取時間為 60 秒，避免太頻繁請求
def get_binance_data(symbol, interval, limit):
    # Binance 公開 API 網址
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status() # 檢查請求是否成功
        data = response.json()
        
        # Binance 回傳的資料是 list of lists，需要轉換成 DataFrame
        # 格式：[Open Time, Open, High, Low, Close, Volume, ...]
        df = pd.DataFrame(data, columns=[
            "Open Time", "Open", "High", "Low", "Close", "Volume",
            "Close Time", "Quote Asset Volume", "Number of Trades",
            "Taker Buy Base Asset Volume", "Taker Buy Quote Asset Volume", "Ignore"
        ])
        
        # 資料處理：轉換時間與數值格式
        df["Date"] = pd.to_datetime(df["Open Time"], unit="ms")
        df["Close"] = df["Close"].astype(float)
        df["Open"] = df["Open"].astype(float)
        df["High"] = df["High"].astype(float)
        df["Low"] = df["Low"].astype(float)
        df["Volume"] = df["Volume"].astype(float)
        
        return df
    except Exception as e:
        st.error(f"抓取 Binance 資料時發生錯誤: {e}")
        return pd.DataFrame()

# --- 執行抓取 ---
data_load_state = st.text('正在連線 Binance API...')
df = get_binance_data(symbol, interval, limit)
data_load_state.text('數據更新完成！')

# --- 顯示內容 ---
if not df.empty:
    # 取得最新價格資訊
    latest_close = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2]
    
    change = latest_close - prev_close
    pct_change = (change / prev_close) * 100
    
    # 根據漲跌改變顏色
    change_color = "normal" 

    # 顯示 Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label=f"{selected_crypto} 現價", 
            value=f"${latest_close:,.2f}", 
            delta=f"{change:,.2f} ({pct_change:.2f}%)"
        )
    with col2:
         # 顯示最高價與最低價
         high_24h = df['High'].max()
         low_24h = df['Low'].min()
         st.metric(label="區間最高", value=f"${high_24h:,.2f}")
    with col3:
         st.metric(label="區間最低", value=f"${low_24h:,.2f}")

    # --- 繪圖 (使用 Candlestick K線圖更專業) ---
    st.subheader(f"📊 {selected_crypto} K線走勢圖")
    
    fig = go.Figure(data=[go.Candlestick(
        x=df['Date'],
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        name=symbol
    )])

    fig.update_layout(
        title=f'{symbol} - {interval} 級別',
        xaxis_title='時間',
        yaxis_title='價格 (USDT)',
        template='plotly_dark',
        height=600,
        xaxis_rangeslider_visible=False # 隱藏下方的滑動條讓畫面更乾淨
    )

    st.plotly_chart(fig, use_container_width=True)

    # --- 顯示原始數據 ---
    with st.expander("查看詳細歷史數據"):
        # 只顯示需要的欄位，並將索引設為日期
        display_df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].sort_values('Date', ascending=False)
        st.dataframe(display_df, use_container_width=True)

else:
    st.warning("目前無法顯示數據，請檢查您的網路連線 (部分地區可能需要 VPN 連線至 Binance)。")
