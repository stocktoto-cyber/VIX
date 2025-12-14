import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="精選持股追蹤",
    page_icon="📈",
    layout="wide" # 使用寬版面讓圖表更清楚
)

# 自定義 CSS 來優化指標顯示 (讓字體更大更清楚)
st.markdown("""
    <style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 設定寫死的股票清單 ---
# 字典格式：代號 -> 名稱
STOCKS = {
    "2330.TW": "台積電 (2330)",
    "0050.TW": "元大台灣50 (0050)",
    "00757.TW": "統一FANG+ (00757)",
    "00675L.TW": "富邦臺灣加權正2 (00675L)"
}

# --- 3. 側邊欄：控制區 ---
with st.sidebar:
    st.title("⚙️ 股票設定")
    
    # 下拉選單 (顯示名稱，回傳代號)
    selected_ticker = st.selectbox(
        "選擇股票",
        options=list(STOCKS.keys()),
        format_func=lambda x: STOCKS[x]
    )
    
    st.markdown("---")
    
    # 時間範圍選擇
    time_period = st.radio(
        "觀察週期",
        options=["1mo", "3mo", "6mo", "1y", "ytd"],
        index=2, # 預設 6個月
        format_func=lambda x: {
            "1mo": "近 1 月", "3mo": "近 3 月", 
            "6mo": "近 6 月", "1y": "近 1 年", "ytd": "今年以來"
        }[x]
    )
    
    st.info(f"目前檢視：**{STOCKS[selected_ticker]}**")

# --- 4. 資料獲取函數 (快取以加速) ---
@st.cache_data(ttl=300) # 每5分鐘更新一次
def get_stock_data(ticker, period):
    try:
        stock = yf.Ticker(ticker)
        # 抓取歷史資料
        df = stock.history(period=period)
        # 抓取即時資訊 (用於顯示最新價格)
        info = stock.info
        return df, info
    except Exception as e:
        st.error(f"資料讀取錯誤: {e}")
        return None, None

# --- 5. 主程式邏輯 ---

# 獲取資料
df, info = get_stock_data(selected_ticker, time_period)

if df is not None and not df.empty:
    # 取得最新一筆與前一筆資料計算漲跌
    latest_price = df['Close'].iloc[-1]
    prev_price = df['Close'].iloc[-2]
    change = latest_price - prev_price
    pct_change = (change / prev_price) * 100

    # === 區塊 A: 頭部資訊看板 ===
    st.title(f"{STOCKS[selected_ticker]} 走勢看板")
    
    # 使用 Columns 排版讓資訊橫向排列
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="目前股價",
            value=f"{latest_price:.2f}",
            delta=f"{change:.2f} ({pct_change:.2f}%)"
        )
    with col2:
        st.metric(label="開盤價", value=f"{df['Open'].iloc[-1]:.2f}")
    with col3:
        st.metric(label="最高價", value=f"{df['High'].iloc[-1]:.2f}")
    with col4:
        st.metric(label="最低價", value=f"{df['Low'].iloc[-1]:.2f}")

    # === 區塊 B: 圖表與數據 (使用 Tabs 分頁) ===
    tab1, tab2 = st.tabs(["📊 K線走勢圖", "📄 詳細歷史數據"])

    with tab1:
        # 繪製 Plotly 互動式 K 線圖
        fig = go.Figure(data=[go.Candlestick(
            x=df.index,
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name="股價"
        )])

        # 添加移動平均線 (簡單範例：20日均線)
        # 如果資料夠多才畫
        if len(df) > 20:
            ma20 = df['Close'].rolling(window=20).mean()
            fig.add_trace(go.Scatter(x=df.index, y=ma20, mode='lines', name='MA20 (月線)', line=dict(color='orange', width=1.5)))

        fig.update_layout(
            title=f"{STOCKS[selected_ticker]} - {time_period} K線圖",
            yaxis_title="價格 (TWD)",
            xaxis_rangeslider_visible=False, # 隱藏底部的滑桿讓畫面更清爽
            height=500,
            template="plotly_white",
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("歷史交易數據")
        # 把 Index (Date) 變成一個欄位並格式化
        display_df = df.sort_index(ascending=False).copy()
        display_df.index = display_df.index.strftime('%Y-%m-%d')
        st.dataframe(
            display_df[['Open', 'High', 'Low', 'Close', 'Volume']],
            use_container_width=True,
            height=400
        )

else:
    st.warning("無法取得資料，請檢查股票代碼或網路連線。")