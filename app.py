import streamlit as st
from tvDatafeed import TvDatafeed, Interval
import pandas as pd
import plotly.graph_objs as go

# --- 頁面設定 ---
st.set_page_config(page_title="TradingView 策略回測", layout="wide")
st.title("📈 TradingView 數據源 - 策略回測系統")
st.markdown("使用 **TradingView** 數據進行回測，支援加密貨幣、股票與外匯。")

# --- 1. 側邊欄：數據來源 ---
st.sidebar.header("1. TradingView 數據設定")

# 交易所與商品選擇
exchange = st.sidebar.selectbox("交易所 (Exchange)", ["BINANCE", "COINBASE", "KRAKEN", "NASDAQ", "TWSE"], index=0)
symbol_input = st.sidebar.text_input("商品代號 (Symbol)", "BTCUSDT").upper()
full_symbol = f"{exchange}:{symbol_input}"

# 時間週期對應 (TradingView 格式)
interval_map = {
    "15m": Interval.in_15_minute,
    "1h": Interval.in_1_hour,
    "4h": Interval.in_4_hour,
    "1d": Interval.in_daily,
    "1w": Interval.in_weekly
}
timeframe_label = st.sidebar.selectbox("K線週期", list(interval_map.keys()), index=3)
selected_interval = interval_map[timeframe_label]

backtest_days = st.sidebar.slider("回測 K 棒數量 (Bars)", 100, 2000, 365)
initial_capital = st.sidebar.number_input("初始本金 (USDT/USD)", value=10000)

st.sidebar.markdown("---")

# --- 2. 策略設定 (維持不變) ---
st.sidebar.subheader("🔵 策略 A")
ma_type_a = st.sidebar.selectbox("種類 A", ["SMA", "EMA"], key='type_a')
short_a = st.sidebar.number_input("短週期 A", value=5, key='short_a')
long_a = st.sidebar.number_input("長週期 A", value=20, key='long_a')

st.sidebar.subheader("🟠 策略 B")
ma_type_b = st.sidebar.selectbox("種類 B", ["SMA", "EMA"], key='type_b', index=0)
short_b = st.sidebar.number_input("短週期 B", value=10, key='short_b')
long_b = st.sidebar.number_input("長週期 B", value=60, key='long_b')

# --- 核心函數：TradingView 抓取 ---
@st.cache_data(ttl=600)
def get_tv_data(symbol, exchange, interval, n_bars):
    tv = TvDatafeed() # 使用訪客模式 (無需帳號密碼)
    
    try:
        # 抓取數據
        df = tv.get_hist(symbol=symbol, exchange=exchange, interval=interval, n_bars=n_bars)
        
        if df is None or df.empty:
            return None
            
        # 整理資料格式
        df = df.reset_index()
        # TvDatafeed 的欄位通常是 symbol 名稱開頭 (例如 BINANCE:BTCUSDT:close)
        # 我們需要重新命名為標準格式
        df.columns = [col.split(':')[-1] for col in df.columns] 
        
        # 確保有標準欄位
        rename_map = {
            'datetime': 'timestamp',
            'date': 'timestamp', # 有時候是 date
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }
        df = df.rename(columns=rename_map)
        
        # 確保 timestamp 是 datetime 格式
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df
    except Exception as e:
        st.error(f"TradingView 抓取失敗: {e}")
        return None

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

# --- 主程式 ---
st.write(f"正在從 TradingView 獲取 **{full_symbol}** 的數據...")

raw_data = get_tv_data(symbol_input, exchange, selected_interval, backtest_days)

if raw_data is not None and not raw_data.empty:
    st.success(f"✅ 成功載入 {len(raw_data)} 根 K 棒 (區間: {raw_data['timestamp'].iloc[0].date()} ~ {raw_data['timestamp'].iloc[-1].date()})")

    # 基準 Buy & Hold
    bh_equity = initial_capital * (raw_data['close'] / raw_data['close'].iloc[0])
    bh_roi = ((bh_equity.iloc[-1] - initial_capital) / initial_capital) * 100
    bh_mdd = calculate_mdd(bh_equity)

    # 執行策略
    res_a = run_strategy(raw_data, short_a, long_a, ma_type_a, initial_capital)
    res_b = run_strategy(raw_data, short_b, long_b, ma_type_b, initial_capital)
    
    # --- 績效看板 ---
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

    # --- 圖表與詳細分析 ---
    st.markdown("---")
    view_option = st.radio("選擇策略視角：", ("策略 A", "策略 B"), horizontal=True)
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
    st.error("無法從 TradingView 獲取數據。請檢查：\n1. 交易所名稱 (Exchange) 是否正確 (如 BINANCE, COINBASE)。\n2. 代號 (Symbol) 是否存在 (如 BTCUSDT)。")
