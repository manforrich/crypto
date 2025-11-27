import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objs as go
import time
from datetime import datetime, timedelta

# --- 頁面設定 ---
st.set_page_config(page_title="Binance 自訂日期回測 (抗封鎖版)", layout="wide")
st.title("📅 自訂日期範圍回測系統 (抗封鎖修復版)")

# --- 1. 側邊欄設定 ---
st.sidebar.header("1. 數據設定")
# 為了增加相容性 (Kraken/BinanceUS 常使用 USD)，建議同時提供 USDT 和 USD
common_pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BTC/USD', 'ETH/USD', 'DOGE/USDT', 'XRP/USDT']
selected_symbol = st.sidebar.selectbox("交易對", common_pairs)
custom_symbol = st.sidebar.text_input("自定義 (如 BNB/USDT)", "").upper()
if custom_symbol: selected_symbol = custom_symbol

timeframe = st.sidebar.selectbox("K線週期", ["15m", "1h", "4h", "1d", "1w"], index=3)

st.sidebar.markdown("### 選擇日期範圍")
default_start = datetime.now() - timedelta(days=365)
default_end = datetime.now()
col_d1, col_d2 = st.sidebar.columns(2)
start_date = col_d1.date_input("開始日期", default_start)
end_date = col_d2.date_input("結束日期", default_end)

initial_capital = st.sidebar.number_input("初始本金 (USDT)", value=10000)

st.sidebar.markdown("---")
# --- 策略設定 ---
st.sidebar.subheader("🔵 策略 A")
ma_type_a = st.sidebar.selectbox("種類 A", ["SMA", "EMA"], key='type_a')
short_a = st.sidebar.number_input("短 A", value=5, key='short_a')
long_a = st.sidebar.number_input("長 A", value=20, key='long_a')

st.sidebar.subheader("🟠 策略 B")
ma_type_b = st.sidebar.selectbox("種類 B", ["SMA", "EMA"], key='type_b', index=0)
short_b = st.sidebar.number_input("短 B", value=10, key='short_b')
long_b = st.sidebar.number_input("長 B", value=60, key='long_b')

# --- 核心函數：分批抓取數據 (含抗封鎖重試機制) ---
@st.cache_data(ttl=3600)
def get_data_by_date_range(symbol, timeframe, start_date, end_date):
    # 定義要嘗試的交易所清單
    # Binance Global -> Binance US (美國IP可用) -> Kraken (美國IP可用)
    exchanges_list = [
        ('Binance', ccxt.binance()), 
        ('Binance US', ccxt.binanceus()), 
        ('Kraken', ccxt.kraken())
    ]

    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 迴圈嘗試不同的交易所
    for exchange_name, exchange in exchanges_list:
        try:
            # 測試連線與商品是否存在
            # 先試抓 1 根，確認沒問題再開始大量下載
            test_ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=1)
            if not test_ohlcv:
                # 可能是商品名稱不對 (例如 Kraken 用 BTC/USD 不用 USDT)
                continue 
            
            # --- 開始正式下載邏輯 ---
            status_text.text(f"正在從 {exchange_name} 下載數據...")
            
            since = exchange.parse8601(f"{start_date}T00:00:00Z")
            end_timestamp = exchange.parse8601(f"{end_date}T23:59:59Z")
            all_ohlcv = []
            limit = 1000 # 單次請求上限
            
            while since < end_timestamp:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                if not ohlcv:
                    break
                
                all_ohlcv += ohlcv
                last_timestamp = ohlcv[-1][0]
                
                if last_timestamp >= end_timestamp:
                    break
                
                since = last_timestamp + 1 
                
                # 計算進度
                total_duration = end_timestamp - exchange.parse8601(f"{start_date}T00:00:00Z")
                current_duration = last_timestamp - exchange.parse8601(f"{start_date}T00:00:00Z")
                progress_val = min(current_duration / total_duration, 1.0)
                progress_bar.progress(progress_val)
                
                # 稍微休息避免被交易所擋
                time.sleep(exchange.rateLimit / 1000 if exchange.rateLimit else 0.1)

            # 下載完成後的處理
            if not all_ohlcv:
                continue # 換下一家

            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # 過濾日期範圍
            mask = (df['timestamp'] >= pd.to_datetime(start_date)) & (df['timestamp'] <= pd.to_datetime(end_date) + timedelta(days=1))
            df = df.loc[mask]
            
            # 成功回傳！
            progress_bar.progress(1.0)
            status_text.empty()
            return df, exchange_name
            
        except ccxt.BadSymbol:
            # 找不到該幣種，換下一家
            continue
        except Exception as e:
            # 遇到 451 或其他網路錯誤，換下一家
            print(f"{exchange_name} Error: {e}")
            continue

    # 如果全部都失敗
    progress_bar.empty()
    return None, "All Exchanges Failed"

# --- 策略計算函數 ---
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

if start_date > end_date:
    st.error("❌ 開始日期必須早於結束日期！")
else:
    st.write(f"正在搜尋 **{selected_symbol}** 的數據 (自動切換節點)...")
    st.caption(f"目標區間：{start_date} 至 {end_date}")
    
    raw_data, source = get_data_by_date_range(selected_symbol, timeframe, start_date, end_date)

    if raw_data is not None and not raw_data.empty:
        st.success(f"✅ 成功從 **{source}** 下載數據！共 {len(raw_data)} 根 K 棒。")
        
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
        st.error(f"❌ 無法獲取數據。所有交易所 (Binance, Binance US, Kraken) 皆嘗試失敗。\n請檢查：\n1. 交易對名稱 (如 BTC/USDT 在 Kraken 上可能是 BTC/USD)。\n2. 該交易對是否過於冷門。")
