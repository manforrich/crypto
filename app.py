import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go
import time
from datetime import datetime, timedelta

# --- 頁面設定 ---
st.set_page_config(page_title="Binance 自訂日期回測", layout="wide")
st.title("📅 自訂日期範圍回測系統")

# --- 1. 側邊欄設定 ---
st.sidebar.header("1. 數據設定")
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)

# --- 修改重點：日期選擇器 ---
st.sidebar.markdown("### 選擇日期範圍")
# 預設為過去 365 天
default_start = datetime.now() - timedelta(days=365)
default_end = datetime.now()

col_d1, col_d2 = st.sidebar.columns(2)
start_date = col_d1.date_input("開始日期", default_start)
end_date = col_d2.date_input("結束日期", default_end)

initial_capital = st.sidebar.number_input("初始本金 (USDT)", value=10000)

st.sidebar.markdown("---")
# --- 策略設定 (保持不變) ---
st.sidebar.subheader("🔵 策略 A")
ma_type_a = st.sidebar.selectbox("種類 A", ["SMA", "EMA"], key='type_a')
short_a = st.sidebar.number_input("短 A", value=5, key='short_a')
long_a = st.sidebar.number_input("長 A", value=20, key='long_a')

st.sidebar.subheader("🟠 策略 B")
ma_type_b = st.sidebar.selectbox("種類 B", ["SMA", "EMA"], key='type_b', index=0)
short_b = st.sidebar.number_input("短 B", value=10, key='short_b')
long_b = st.sidebar.number_input("長 B", value=60, key='long_b')

# --- 核心函數：分批抓取數據 ---
@st.cache_data(ttl=3600) # 資料量大，快取設久一點 (1小時)
def get_data_by_date_range(symbol, timeframe, start_date, end_date):
    # 初始化交易所 (使用 ccxt)
    exchange = ccxt.binance()
    
    # 將日期轉換為 timestamp (毫秒)
    since = exchange.parse8601(f"{start_date}T00:00:00Z")
    end_timestamp = exchange.parse8601(f"{end_date}T23:59:59Z")
    
    all_ohlcv = []
    limit = 1000 # Binance 單次上限
    
    # 進度條
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        while since < end_timestamp:
            status_text.text(f"正在下載數據... 目前進度: {pd.to_datetime(since, unit='ms')}")
            
            # 抓取數據
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            
            if not ohlcv:
                break
            
            # 將這一批數據加入總表
            all_ohlcv += ohlcv
            
            # 更新下一次抓取的起始時間 (最後一筆數據的時間 + 1個時間單位的毫秒數，避免重複)
            # 簡單做法：直接取最後一筆的時間
            last_timestamp = ohlcv[-1][0]
            
            # 如果抓到的最新數據已經超過結束時間，就停止
            if last_timestamp >= end_timestamp:
                break
                
            # 更新 since，準備抓下一頁
            # 注意：必須比最後一筆大，否則會無窮迴圈。通常加 1ms 即可，exchange 會自動找下一根
            since = last_timestamp + 1 
            
            # 稍微暫停避免觸發 API Rate Limit (雖然 Binance 公開 API 限制很寬鬆)
            time.sleep(0.1)
            
            # 簡單計算進度 (視覺用)
            current_progress = min((since - exchange.parse8601(f"{start_date}T00:00:00Z")) / (end_timestamp - exchange.parse8601(f"{start_date}T00:00:00Z")), 1.0)
            progress_bar.progress(current_progress)

        progress_bar.progress(1.0)
        status_text.text("下載完成！")
        time.sleep(0.5)
        status_text.empty()
        progress_bar.empty()
        
        if not all_ohlcv:
            return None, "No Data"

        # 整理 DataFrame
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # 過濾掉超出範圍的數據 (因為最後一次抓取可能會多抓一點點)
        mask = (df['timestamp'] >= pd.to_datetime(start_date)) & (df['timestamp'] <= pd.to_datetime(end_date) + timedelta(days=1))
        df = df.loc[mask]
        
        return df, "Binance"
        
    except Exception as e:
        return None, str(e)

# --- 策略計算函數 (通用) ---
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
    return {"final_equity": final_equity, "roi": roi, "trades": trades, "mdd": mdd, "df": df, "buys": buy_signals, "sells": sell_signals, "trade_log": pd.DataFrame(trade_log)}

# --- 主程式執行 ---

# 檢查日期順序
if start_date > end_date:
    st.error("❌ 開始日期必須早於結束日期！")
else:
    st.write(f"正在從 Binance 下載 **{selected_symbol}** ({timeframe}) 數據...")
    st.caption(f"區間：{start_date} 至 {end_date}")
    
    raw_data, source = get_data_by_date_range(selected_symbol, timeframe, start_date, end_date)

    if raw_data is not None and not raw_data.empty:
        st.success(f"✅ 下載完成！共 {len(raw_data)} 根 K 棒。")
        
        # 1. 基準 Buy & Hold
        bh_equity = initial_capital * (raw_data['close'] / raw_data['close'].iloc[0])
        bh_roi = ((bh_equity.iloc[-1] - initial_capital) / initial_capital) * 100
        bh_mdd = calculate_mdd(bh_equity)

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
        st.error(f"無法獲取數據 (Error: {source})。可能原因：\n1. 該交易對在選定的日期範圍內沒有數據。\n2. 網路連線問題。")
