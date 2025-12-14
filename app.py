import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import datetime

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式修正 (iOS 風格化) ---
st.markdown("""
    <style>
    /* === 全域設定：模擬 iOS 背景 === */
    .stApp {
        background-color: #F2F2F7 !important; /* iOS 系統淺灰背景 */
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    }

    /* === 指標卡片 (Metric Card) === */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important; /* 純白卡片 */
        border: none !important; /* 去除邊框 */
        padding: 20px !important;
        border-radius: 20px !important; /* 大圓角 */
        box-shadow: 0 4px 12px rgba(0,0,0,0.05) !important; /* 柔和的 iOS 陰影 */
    }

    /* 標題 (Label) - iOS 副標題灰 */
    div[data-testid="stMetricLabel"] * {
        color: #8E8E93 !important; /* iOS System Gray */
        font-size: 14px !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #8E8E93 !important;
    }

    /* 數值 (Value) - iOS 標題黑 */
    div[data-testid="stMetricValue"] * {
        color: #1C1C1E !important; /* iOS System Black */
        font-size: 28px !important; /* 加大數字 */
        font-weight: 700 !important; /* San Francisco Bold */
    }
    div[data-testid="stMetricValue"] {
        color: #1C1C1E !important;
    }

    /* === 按鈕 (Button) === */
    div[data-testid="stButton"] button {
        background-color: #007AFF !important; /* iOS System Blue */
        color: white !important;
        border-radius: 12px !important; /* 按鈕圓角 */
        border: none !important;
        padding: 10px 20px !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 5px rgba(0,122,255,0.3) !important;
        transition: all 0.2s ease;
        width: 100%; /* 讓按鈕填滿寬度 */
    }
    div[data-testid="stButton"] button:hover {
        background-color: #0062CC !important; /* 按下變深 */
        transform: scale(0.98); /* 按下微縮效果 */
    }

    /* === 輸入框 (Text Input) === */
    div[data-testid="stTextInput"] input {
        border-radius: 12px !important;
        background-color: #E5E5EA !important; /* iOS 輸入框背景灰 */
        color: #000000 !important;
        border: none !important;
        padding: 10px 15px !important;
    }
    div[data-testid="stTextInput"] label {
        color: #1C1C1E !important;
        font-weight: 600 !important;
    }

    /* === 狀態提示框 (Alerts) === */
    /* 成功 (Green) */
    div[data-testid="stNotification"][class*="success"] {
        background-color: #E8F5E9 !important; /* 淺綠底 */
        color: #34C759 !important; /* iOS System Green */
        border-radius: 16px !important;
        border: none !important;
    }
    .stAlert {
        border-radius: 16px !important;
        padding: 15px !important;
    }
    
    /* 錯誤/危險 (Red) */
    div[data-testid="stNotification"][class*="error"] {
        background-color: #FFEBEE !important;
        color: #FF3B30 !important; /* iOS System Red */
    }

    /* 修正 Streamlit 箭頭顏色 */
    div[data-testid="stMetricDelta"] svg {
        fill: auto !important;
    }

    /* 隱藏側邊欄預設背景，改為半透明磨砂感 (盡力模擬) */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E5E5EA;
    }
    </style>
    """, unsafe_allow_html=True)

class MarketPanicDetector:
    def __init__(self, ticker='00675L.TW'):
        self.ticker = ticker.upper()
        self.stock_data = None
        self.vix_data = None
        self.fng_score = None
        
        # 設定參數
        self.rsi_threshold = 25       
        self.vix_threshold = 20       
        self.fng_threshold = 25       
        self.vol_multiplier = 1.5     

    def fetch_data(self):
        """抓取數據"""
        try:
            # 抓取個股
            stock = yf.Ticker(self.ticker)
            self.stock_data = stock.history(period="6mo")
            
            # 抓取 VIX
            vix = yf.Ticker("^VIX")
            vix_df = vix.history(period="5d")
            if not vix_df.empty:
                self.vix_data = vix_df['Close'].iloc[-1]
            else:
                self.vix_data = 0
            
            return True
        except Exception as e:
            st.error(f"❌ 數據抓取失敗: {e}")
            return False

    def fetch_fear_and_greed(self):
        """爬取 CNN Fear & Greed Index"""
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.fng_score = round(data['fear_and_greed']['score'])
            else:
                self.fng_score = None
        except:
            self.fng_score = None

    def calculate_technicals(self):
        """計算技術指標"""
        if self.stock_data is None or self.stock_data.empty:
            return

        df = self.stock_data.copy()
        
        # 1. 布林通道
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['MA20'] + (df['STD'] * 2)
        df['Lower'] = df['MA20'] - (df['STD'] * 2)

        # 2. 成交量均線
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()

        # 3. RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        self.stock_data = df

    def analyze(self):
        """輸出結果至 Streamlit"""
        if self.stock_data is None or self.stock_data.empty:
            st.warning("查無資料，請確認股票代碼是否正確。")
            return

        today = self.stock_data.iloc[-1]
        date_str = today.name.strftime('%Y-%m-%d')
        
        # --- 單位換算 (股 -> 張) ---
        vol_today_sheets = int(today['Volume'] / 1000)
        vol_ma_sheets = int(today['Vol_MA20'] / 1000)
        
        # 條件判斷
        cond_lower_band = today['Close'] < today['Lower']
        cond_volume = today['Volume'] > (today['Vol_MA20'] * self.vol_multiplier)
        cond_rsi = today['RSI'] < self.rsi_threshold
        cond_vix = self.vix_data > self.vix_threshold if self.vix_data else False
        cond_fng = self.fng_score < self.fng_threshold if self.fng_score else False

        # --- 顯示報告 ---
        st.markdown(f"<h1 style='color:#000000;'>📊 恐慌指標檢測 | {self.ticker}</h1>", unsafe_allow_html=True)
        st.caption(f"📅 資料日期: {date_str}")
        st.markdown("---")

        # 1. 技術面
        st.subheader("1. 價格 vs 布林下緣")
        c1, c2, c3 = st.columns(3)
        c1.metric("收盤價", f"{today['Close']:.2f}")
        c2.metric("布林下軌", f"{today['Lower']:.2f}")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if cond_lower_band:
                st.error("🔴 跌破下軌 (符合)")
            else:
                st.success("🟢 未跌破")

        # 2. 籌碼面
        st.subheader("2. 成交量 (單位: 張)")
        c1, c2, c3 = st.columns(3)
        c1.metric("今日量", f"{vol_today_sheets:,}")
        c2.metric("20日均量", f"{vol_ma_sheets:,}")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if cond_volume:
                st.error("🔴 爆量恐慌 (符合)")
            else:
                st.success("🟢 量能正常")

        # 3. 動能面
        st.subheader("3. RSI 指標")
        c1, c2 = st.columns([2, 1])
        c1.metric("RSI (14)", f"{today['RSI']:.2f}")
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if cond_rsi:
                st.error("🔴 嚴重超賣 (符合)")
            else:
                st.success("🟢 尚未超賣")

        # 4. 市場恐慌程度
        st.subheader("4. 市場恐慌程度")
        c1, c2 = st.columns(2)
        
        with c1:
            st.markdown("**VIX 恐慌指數**") # 標題稍微調整以配合 iOS 風格
            st.metric("VIX", f"{self.vix_data:.2f}")
            if cond_vix:
                st.error("🔴 市場恐慌 (符合)")
            else:
                st.success("🟢 市場平穩")
                
        with c2:
            st.markdown("**Fear & Greed Index**")
            if self.fng_score:
                st.metric("F&G 指數", f"{self.fng_score}")
                if cond_fng:
                    st.error("🔴 極度恐慌 (符合)")
                else:
                    st.success("🟢 情緒尚可")
            else:
                st.warning("⚠️ 無法取得數據")

        # --- 總結 ---
        st.markdown("---")
        score = sum([cond_lower_band, cond_volume, cond_rsi, cond_vix, cond_fng])
        
        # 使用 markdown 製作 iOS 風格的大標題
        st.markdown(f"<h3 style='color:#1C1C1E; font-weight:700;'>🎯 恐慌訊號總分: {score} / 5</h3>", unsafe_allow_html=True)
        
        if score >= 4:
            st.error("🚨 訊號極強！市場極度非理性，可考慮分批進場搶反彈。")
        elif score >= 3:
            st.warning("⚠️ 訊號中等，建議觀察盤中是否有「下影線」再動作。")
        else:
            st.info("☕ 目前尚未出現明顯的過度恐慌訊號，建議觀望。")


# --- Streamlit 執行邏輯 ---
with st.sidebar:
    st.markdown("<h2 style='color:#1C1C1E;'>⚙️ 設定</h2>", unsafe_allow_html=True)
    st.write("輸入台股代號 (如 2330.TW, 00675L.TW)")
    
    ticker_input = st.text_input("股票代碼", value="00675L.TW")
    
    st.write("") # 空行
    run_btn = st.button("🚀 開始分析", type="primary")

if run_btn or ticker_input:
    detector = MarketPanicDetector(ticker_input)
    with st.spinner('⏳ 正在抓取資料與計算中...'):
        success = detector.fetch_data()
        if success:
            detector.fetch_fear_and_greed()
            detector.calculate_technicals()
            detector.analyze()
