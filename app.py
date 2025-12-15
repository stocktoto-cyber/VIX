import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式 (Soft UI / Neumorphism 暖白風格) ---
st.markdown("""
    <style>
    /* === 全域設定 === */
    .stApp {
        background-color: #F0F0F3 !important;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    }
    
    h1, h2, h3, h4, p, span, label, .stMarkdown {
        color: #444444 !important;
    }

    /* 側邊欄 */
    section[data-testid="stSidebar"] {
        background-color: #EAEAED !important;
        box-shadow: inset -5px 0 10px rgba(0,0,0,0.02) !important;
    }

    /* === 卡片 (Metric Card) === */
    div[data-testid="stMetric"] {
        background-color: #F0F0F3 !important;
        border: none !important;
        padding: 15px !important;
        border-radius: 20px !important;
        box-shadow: 8px 8px 16px #aeaec0, -8px -8px 16px #ffffff !important;
    }
    
    div[data-testid="stMetricLabel"] { color: #7D7D7D !important; font-weight: 600; }
    div[data-testid="stMetricValue"] { color: #333333 !important; font-weight: 700; }

    /* === 按鈕 (Button) - 橘色漸層 === */
    div[data-testid="stButton"] button {
        background: linear-gradient(145deg, #FFB74D, #FF9800) !important;
        color: white !important;
        border-radius: 30px !important;
        border: none !important;
        padding: 10px 25px !important;
        font-weight: 600 !important;
        box-shadow: 5px 5px 10px #d1d1d1, -5px -5px 10px #ffffff !important;
        transition: all 0.2s ease;
    }
    div[data-testid="stButton"] button:hover {
        transform: translateY(-2px);
        box-shadow: 6px 6px 12px #c1c1c1, -6px -6px 12px #ffffff !important;
    }

    /* === 輸入框與日期選單 === */
    div[data-testid="stTextInput"] input, div[data-testid="stDateInput"] input {
        background-color: #F0F0F3 !important;
        border-radius: 15px !important;
        border: none !important;
        color: #333333 !important;
        box-shadow: inset 5px 5px 10px #d1d1d1, inset -5px -5px 10px #ffffff !important;
    }

    /* === 狀態提示框 === */
    .stAlert {
        border-radius: 15px !important;
        box-shadow: 5px 5px 10px #dedede, -5px -5px 10px #ffffff !important;
        border: none !important;
    }
    
    /* 修正 Tab 樣式 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #F0F0F3;
        border-radius: 15px;
        box-shadow: 5px 5px 10px #d1d1d1, -5px -5px 10px #ffffff;
        color: #444444;
        font-weight: bold;
        border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FF9800 !important;
        color: white !important;
        box-shadow: inset 3px 3px 6px #d98200, inset -3px -3px 6px #ffd06b !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心類別：恐慌檢測與回測 ---
class MarketPanicDetector:
    def __init__(self, ticker='00675L.TW'):
        self.ticker = ticker.upper()
        self.stock_data = None
        self.vix_data = None
        self.fng_score = None
        
        # 策略參數
        self.rsi_threshold = 25       
        self.vix_threshold = 20       
        self.vol_multiplier = 1.5     

    # --- 功能 A: 即時數據抓取 ---
    def fetch_live_data(self):
        try:
            stock = yf.Ticker(self.ticker)
            self.stock_data = stock.history(period="6mo")
            vix = yf.Ticker("^VIX")
            vix_df = vix.history(period="5d")
            self.vix_data = vix_df['Close'].iloc[-1] if not vix_df.empty else 0
            return True
        except Exception as e:
            st.error(f"❌ 數據抓取失敗: {e}")
            return False

    def fetch_fear_and_greed(self):
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.fng_score = round(data['fear_and_greed']['score'])
            else:
                self.fng_score = None
        except:
            self.fng_score = None

    def calculate_technicals(self, df):
        # 布林通道
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['MA20'] + (df['STD'] * 2)
        df['Lower'] = df['MA20'] - (df['STD'] * 2)
        # 成交量
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        return df

    # --- 功能 B: 回測邏輯 (已修正賣出條件) ---
    def run_backtest(self, start_date, end_date):
        st.info(f"正在回測 {self.ticker}，區間: {start_date} ~ {end_date}")
        
        # 1. 抓取歷史資料
        try:
            df = yf.download(self.ticker, start=start_date, end=end_date, progress=False)
            if df.empty:
                st.error("此區間無股價資料")
                return None
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 計算指標
            df = self.calculate_technicals(df)
            
            # 2. 模擬交易
            trades = []
            position = None # 持倉狀態
            
            for i in range(20, len(df)):
                today = df.iloc[i]
                date = df.index[i]
                
                # --- 進場條件 (維持不變) ---
                # 1. RSI < 25 (嚴重超賣)
                # 2. 收盤價 < 布林下軌 (價格極端)
                is_panic = (today['RSI'] < self.rsi_threshold) and \
                           (today['Close'] < today['Lower'])
                
                # --- 出場條件 (已修改) ---
                # 1. 收盤價 > 布林上軌 (High/Close 突破皆可，這裡用收盤較保守)
                # 2. 成交量 > 10,000 張 (10,000,000 股)
                is_target_met = (today['Close'] > today['Upper']) and \
                                (today['Volume'] > 10000000)

                # 執行交易
                if position is None and is_panic:
                    position = {
                        "entry_date": date,
                        "entry_price": today['Close']
                    }
                elif position is not None and is_target_met:
                    # 獲利了結
                    roi = (today['Close'] - position['entry_price']) / position['entry_price']
                    trades.append({
                        "entry_date": position['entry_date'],
                        "exit_date": date,
                        "entry_price": position['entry_price'],
                        "exit_price": today['Close'],
                        "volume_at_exit": int(today['Volume']/1000), # 紀錄賣出時的量(張)
                        "return": roi,
                        "holding_days": (date - position['entry_date']).days
                    })
                    position = None # 清空持倉

            return pd.DataFrame(trades)
            
        except Exception as e:
            st.error(f"回測發生錯誤: {e}")
            return None

    # --- 顯示即時分析介面 ---
    def show_live_analysis(self):
        if self.stock_data is None: return
        
        df = self.calculate_technicals(self.stock_data.copy())
        today = df.iloc[-1]
        date_str = today.name.strftime('%Y-%m-%d')
        
        # 判斷邏輯
        cond_lower_band = today['Close'] < today['Lower']
        cond_volume = today['Volume'] > (today['Vol_MA20'] * self.vol_multiplier)
        cond_rsi = today['RSI'] < self.rsi_threshold
        cond_vix = self.vix_data > self.vix_threshold
        cond_fng = self.fng_score < 25 if self.fng_score else False
        
        score = sum([cond_lower_band, cond_volume, cond_rsi, cond_vix, cond_fng])

        st.markdown(f"<h2 style='color:#333333;'>📊 即時恐慌診斷 | {self.ticker}</h2>", unsafe_allow_html=True)
        st.caption(f"📅 資料日期: {date_str}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("收盤價", f"{today['Close']:.2f}")
        col2.metric("RSI (14)", f"{today['RSI']:.2f}")
        col3.metric("總分 (滿分5)", f"{score}", delta="越高越恐慌" if score > 3 else "觀察中")
        
        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            if score >= 4:
                st.error("🚨 訊號極強！市場非理性，可留意反彈機會。")
            elif score >= 3:
                st.warning("⚠️ 訊號中等，建議觀察是否有下影線。")
            else:
                st.info("☕ 目前尚未出現明顯恐慌訊號。")
        with c2:
            st.markdown(f"**詳細狀態**")
            st.text(f"布林下軌: {'跌破 🔴' if cond_lower_band else '安全 🟢'}")
            st.text(f"爆量程度: {'爆量 🔴' if cond_volume else '正常 🟢'}")
            st.text(f"VIX指數: {'恐慌 🔴' if cond_vix else '平穩 🟢'}")

# --- 4. 主程式邏輯 ---

with st.sidebar:
    st.markdown("### ⚙️ 設定面板")
    ticker_input = st.text_input("股票代碼", value="00675L.TW")
    
    st.markdown("---")
    st.markdown("### 📅 回測設定")
    start_date = st.date_input("開始日期", datetime.now() - timedelta(days=365*2))
    end_date = st.date_input("結束日期", datetime.now())
    
    run_btn = st.button("🚀 開始執行", type="primary")

if run_btn:
    detector = MarketPanicDetector(ticker_input)
    
    tab1, tab2 = st.tabs(["📊 即時診斷", "📈 歷史回測"])
    
    # === 分頁 1: 即時診斷 ===
    with tab1:
        with st.spinner('分析即時數據中...'):
            if detector.fetch_live_data():
                detector.fetch_fear_and_greed()
                detector.show_live_analysis()
    
    # === 分頁 2: 歷史回測 ===
    with tab2:
        with st.spinner('正在進行歷史回測模擬...'):
            trades_df = detector.run_backtest(start_date, end_date)
            
            if trades_df is not None and not trades_df.empty:
                total_trades = len(trades_df)
                win_trades = len(trades_df[trades_df['return'] > 0])
                win_rate = (win_trades / total_trades) * 100
                avg_return = trades_df['return'].mean() * 100
                total_return = ((trades_df['return'] + 1).prod() - 1) * 100 
                
                st.markdown(f"<h3 style='color:#333333;'>📈 回測報告 ({start_date} ~ {end_date})</h3>", unsafe_allow_html=True)
                st.info("💡 策略邏輯：\n1. 買入：RSI<25 且 跌破布林下軌。\n2. 賣出：突破布林上軌 且 當日成交量 > 10,000 張。")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("總交易次數", f"{total_trades} 次")
                m2.metric("勝率", f"{win_rate:.1f}%")
                m3.metric("平均單次報酬", f"{avg_return:.2f}%")
                m4.metric("總累積報酬", f"{total_return:.2f}%", delta=f"{total_return:.2f}%")
                
                st.markdown("---")
                
                st.subheader("📝 交易明細表")
                display_df = trades_df.copy()
                display_df['return'] = display_df['return'].apply(lambda x: f"{x*100:.2f}%")
                display_df['entry_date'] = display_df['entry_date'].dt.date
                display_df['exit_date'] = display_df['exit_date'].dt.date
                display_df['volume_at_exit'] = display_df['volume_at_exit'].apply(lambda x: f"{x:,} 張")
                
                display_df.columns = ["進場日期", "出場日期", "進場價", "出場價", "出場時成交量", "報酬率", "持有天數"]
                
                st.dataframe(display_df, use_container_width=True)
                
            elif trades_df is not None:
                st.warning("⚠️ 在此區間內未發現符合策略的交易訊號 (可能是條件太嚴格，例如成交量未達 1 萬張)。")
