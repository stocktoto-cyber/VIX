import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式 (UI 終極修復：強制黑字 + 可見度優化) ---
st.markdown("""
    <style>
    /* === 1. 全域背景設定 (柔和灰) === */
    .stApp {
        background-color: #F0F0F3 !important;
    }
    
    /* === 2. 一般文字顏色 === */
    h1, h2, h3, h4, h5, h6, p, span, div, label, li, .stMarkdown {
        color: #333333 !important;
    }

    /* === 3. 側邊欄設定 === */
    section[data-testid="stSidebar"] {
        background-color: #EAEAED !important;
    }
    section[data-testid="stSidebar"] * {
        color: #333333 !important;
    }

    /* === 4. 指標卡片 (Metric Card) 樣式 === */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important; /* 純白背景 */
        border: 1px solid #E0E0E0 !important;
        padding: 15px !important;
        border-radius: 15px !important;
        box-shadow: 4px 4px 10px rgba(0,0,0,0.05) !important;
    }
    
    /* 【關鍵修復】暴力強制卡片內所有層級的文字顏色 */
    div[data-testid="stMetric"] * {
        color: #000000 !important; /* 預設全黑 */
    }
    
    /* 標題 (Label) 稍微淺一點區分 */
    div[data-testid="stMetricLabel"] p {
        color: #555555 !important; 
        font-weight: bold !important;
    }
    
    /* 數值 (Value) 純黑加粗 */
    div[data-testid="stMetricValue"] div {
        color: #000000 !important;
        font-weight: 900 !important;
    }

    /* 讓漲跌箭頭維持紅綠色 (不要被變黑) */
    div[data-testid="stMetricDelta"] svg { fill: auto !important; }
    div[data-testid="stMetricDelta"] > div { color: auto !important; }

    /* === 5. 按鈕 (Button) === */
    div[data-testid="stButton"] button {
        background: linear-gradient(145deg, #FFB74D, #FF9800) !important;
        border: none !important;
        border-radius: 30px !important;
        box-shadow: 3px 3px 6px #d1d1d1 !important;
    }
    /* 按鈕內的文字強制白色 */
    div[data-testid="stButton"] button p {
        color: white !important;
    }

    /* === 6. 輸入框與日期選單 === */
    div[data-testid="stTextInput"] input, div[data-testid="stDateInput"] input {
        background-color: #FFFFFF !important;
        color: #000000 !important;
        border: 1px solid #CCCCCC !important;
        border-radius: 10px !important;
    }
    
    /* === 7. 表格樣式優化 === */
    div[data-testid="stDataFrame"] {
        background-color: #FFFFFF !important;
        color: #000000 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心類別 ---
class MarketPanicDetector:
    def __init__(self, ticker='00675L.TW'):
        self.ticker = ticker.upper()
        self.stock_data = None
        self.vix_data = None
        self.fng_score = None
        self.volume_threshold = 7000 * 1000 # 7000張

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
        cols_to_numeric = ['Close', 'High', 'Low', 'Open', 'Volume']
        for col in cols_to_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['MA20'] + (df['STD'] * 2)
        df['Lower'] = df['MA20'] - (df['STD'] * 2)
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        return df

    def run_backtest(self, start_date, end_date):
        msg_box = st.empty()
        
        # 【重要修正】自動多抓 60 天資料，確保計算指標時有足夠的歷史數據
        buffer_days = 60
        fetch_start = start_date - timedelta(days=buffer_days)
        
        msg_box.info(f"📥 正在下載數據 (含前置運算資料: {fetch_start} ~ {end_date})...")
        
        try:
            # 1. 下載台股
            stock_df = yf.download(self.ticker, start=fetch_start, end=end_date, progress=False, threads=False)
            if stock_df.empty:
                msg_box.error(f"❌ 無法下載 {self.ticker} 的股價資料。")
                return None, None
            
            # 處理 MultiIndex
            if isinstance(stock_df.columns, pd.MultiIndex):
                stock_df.columns = stock_df.columns.get_level_values(0)
            if stock_df.index.tz is not None:
                stock_df.index = stock_df.index.tz_localize(None)

            # 2. 下載 VIX
            vix_df = yf.download("^VIX", start=fetch_start, end=end_date, progress=False, threads=False)
            vix_series = pd.Series(0, index=stock_df.index)
            
            if not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                if vix_df.index.tz is not None:
                    vix_df.index = vix_df.index.tz_localize(None)
                vix_series = vix_df['Close']

            # 3. 合併資料
            aligned_vix = vix_series.reindex(stock_df.index, method='ffill')
            df = stock_df.copy()
            df['VIX'] = aligned_vix.fillna(0)

            msg_box.info("🔄 正在計算策略...")
            
            # 先計算指標 (這時候包含前60天的資料，所以指標會準)
            df = self.calculate_technicals(df)
            
            # 【重要修正】計算完後，再切分出使用者真正想看的區間
            # 將 start_date 轉為 datetime 格式進行比較
            start_datetime = pd.to_datetime(start_date)
            df = df[df.index >= start_datetime]
            
            # 移除計算後仍有空值的資料 (通常這時候已經都有值了)
            df = df.dropna()

            trades = []
            positions = []
            
            # --- 診斷統計 ---
            df['Check_Price'] = df['Close'] < df['Lower']
            df['Check_Vol'] = df['Volume'] > self.volume_threshold
            df['Check_VIX'] = df
