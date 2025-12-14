import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import datetime

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式修正 (關鍵修復) ---
# 這段 CSS 會強制覆蓋 Streamlit 的預設設定，解決「白底白字」問題
st.markdown("""
    <style>
    /* 針對指標卡片 (Metric Card) 的外框設定 */
    div[data-testid="stMetric"] {
        background-color: #f0f2f6 !important; /* 強制淺灰背景 */
        border: 1px solid #d6d6d6;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1); /* 加一點陰影讓它更立體 */
    }

    /* 強制修改標題文字顏色 (例如：收盤價、RSI) */
    div[data-testid="stMetricLabel"] p {
        color: #555555 !important; /* 深灰色 */
        font-weight: bold;
    }
    
    /* 針對某些版本的 Streamlit Label 結構不同，多加一層保險 */
    div[data-testid="stMetricLabel"] {
        color: #555555 !important;
    }

    /* 強制修改數值文字顏色 (例如：138.00) */
    div[data-testid="stMetricValue"] div {
        color: #000000 !important; /* 純黑色 */
        font-weight: bold;
    }
    
    /* 針對數值結構多加一層保險 */
    div[data-testid="stMetricValue"] {
        color: #000000 !important;
    }

    /* 狀態提示框 (Success/Error) 的文字顏色調整 */
    .stAlert {
        font-weight: bold;
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
        st.title(f"📊 恐慌指標檢測報告 | {self.ticker}")
        st.caption(f"📅 資料日期: {date_str}")
        st.markdown("---")

        # 1. 技術面
        st.subheader("1. [技術面] 價格 vs 布林下緣")
        c1, c2, c3 = st.columns(3)
        c1.metric("收盤價", f"{today['Close']:.2f}")
        c2.metric("布林下軌", f"{today['Lower']:.2f}")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True) # 排版微調
            if cond_lower_band:
                st.error("🔴 跌破下軌 (符合)")
            else:
                st.success("🟢 未跌破")

        # 2. 籌碼面
        st.subheader("2. [籌碼面] 成交量 (單位: 張)")
        c1, c2, c3 = st.columns(3)
        c1.metric("今日量", f"{vol_today_sheets:,}")
        c2.metric("20日均量", f"{vol_ma_sheets:,}")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if cond_volume:
                st.error("🔴 爆量恐慌殺盤 (符合)")
            else:
                st.success("🟢 量能正常")

        # 3. 動能面
        st.subheader("3. [動能面] RSI 指標")
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
            st.info("VIX 恐慌指數") # 使用 info 框代替純文字
            st.metric("VIX 指數", f"{self.vix_data:.2f}")
            if cond_vix:
                st.error("🔴 市場恐慌 (符合)")
            else:
                st.success("🟢 市場平穩")
                
        with c2:
            st.info("Fear & Greed Index")
            if self.fng_score:
                st.metric("貪婪恐慌指數", f"{self.fng_score}")
                if cond_fng:
                    st.error("🔴 極度恐慌 (符合)")
                else:
                    st.success("🟢 情緒尚可")
            else:
                st.warning("⚠️ 無法取得數據")

        # --- 總結 ---
        st.markdown("---")
        score = sum([cond_lower_band, cond_volume, cond_rsi, cond_vix, cond_fng])
        
        st.subheader(f"🎯 恐慌訊號總分: {score} / 5")
        
        if score >= 4:
            st.error("🚨 訊號極強！市場極度非理性，可考慮分批進場搶反彈。")
        elif score >= 3:
            st.warning("⚠️ 訊號中等，建議觀察盤中是否有「下影線」再動作。")
        else:
            st.info("☕ 目前尚未出現明顯的過度恐慌訊號，建議觀望。")


# --- Streamlit 執行邏輯 ---
with st.sidebar:
    st.header("⚙️ 設定")
    st.write("輸入台股代號 (如 2330.TW, 00675L.TW)")
    
    # 輸入框
    ticker_input = st.text_input("股票代碼", value="00675L.TW")
    
    # 按鈕
    run_btn = st.button("🚀 開始分析", type="primary")

# 當頁面載入或按下按鈕時執行
if run_btn or ticker_input:
    # 建立物件
    detector = MarketPanicDetector(ticker_input)
    
    # 執行流程
    with st.spinner('⏳ 正在抓取資料與計算中...'):
        success = detector.fetch_data()
        if success:
            detector.fetch_fear_and_greed()
            detector.calculate_technicals()
            detector.analyze()
