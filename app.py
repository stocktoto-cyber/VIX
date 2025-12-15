import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式 (UI 強制修復版 - 黑字優化) ---
st.markdown("""
    <style>
    /* === 1. 全域背景設定 === */
    .stApp {
        background-color: #F0F0F3 !important; /* 柔和灰背景 */
    }
    
    /* === 2. 強制所有一般文字為深灰色 (對抗深色模式) === */
    h1, h2, h3, h4, h5, h6, p, span, div, label, .stMarkdown {
        color: #333333 !important;
    }

    /* === 3. 側邊欄設定 === */
    section[data-testid="stSidebar"] {
        background-color: #EAEAED !important;
        box-shadow: inset -5px 0 10px rgba(0,0,0,0.02) !important;
    }
    section[data-testid="stSidebar"] * {
        color: #333333 !important;
    }

    /* === 4. 關鍵修復：指標卡片 (Metric Card) === */
    div[data-testid="stMetric"] {
        background-color: #F0F0F3 !important;
        border: 1px solid #ffffff !important;
        padding: 15px !important;
        border-radius: 20px !important;
        box-shadow: 6px 6px 12px #c5c5c5, -6px -6px 12px #ffffff !important;
    }
    
    /* 鎖定卡片內 "所有" 層級的文字，強制變黑 */
    div[data-testid="stMetric"] label { color: #666666 !important; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #000000 !important; }
    div[data-testid="stMetricValue"] * {
        color: #000000 !important;
    }

    /* 讓漲跌箭頭維持紅綠色 */
    div[data-testid="stMetricDelta"] svg { fill: auto !important; }
    div[data-testid="stMetricDelta"] > div { color: auto !important; }

    /* === 5. 按鈕 (Button) === */
    div[data-testid="stButton"] button {
        background: linear-gradient(145deg, #FFB74D, #FF9800) !important;
        color: white !important;
        border-radius: 30px !important;
        border: none !important;
        box-shadow: 5px 5px 10px #d1d1d1, -5px -5px 10px #ffffff !important;
    }
    div[data-testid="stButton"] button * {
        color: white !important;
    }

    /* === 6. 輸入框與日期選單 === */
    div[data-testid="stTextInput"] input, div[data-testid="stDateInput"] input {
        background-color: #E8E8EB !important;
        color: #000000 !important;
        border-radius: 10px !important;
    }
    
    /* === 7. 分頁籤 (Tabs) === */
    .stTabs button[aria-selected="true"] {
        color: #FF9800 !important;
        border-bottom-color: #FF9800 !important;
    }
    .stTabs button {
        color: #555555 !important;
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
        
        # 策略參數
        self.rsi_threshold = 25       
        self.vix_threshold = 20       
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
        # 確保資料是數值型態 (避免 yfinance 有時回傳 object)
        cols_to_numeric = ['Close', 'High', 'Low', 'Open', 'Volume']
        for col in cols_to_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['STD'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['MA20'] + (df['STD'] * 2)
        df['Lower'] = df['MA20'] - (df['STD'] * 2)
        df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        return df

    # --- 功能 B: 回測邏輯 (分開下載 + 穩定合併) ---
    def run_backtest(self, start_date, end_date):
        st.info(f"📥 正在分開下載個股與 VIX 數據，請稍候...")
        
        try:
            # 1. 下載台股資料 (threads=False 防止卡死)
            stock_df = yf.download(self.ticker, start=start_date, end=end_date, progress=False, threads=False)
            
            if stock_df.empty:
                st.error(f"❌ 無法下載 {self.ticker} 的股價資料，請檢查代碼或日期。")
                return None, None
            
            # 處理 MultiIndex (yfinance 新版問題)
            if isinstance(stock_df.columns, pd.MultiIndex):
                try:
                    stock_df.columns = stock_df.columns.get_level_values(0)
                except:
                    pass # 如果失敗就保持原樣，通常 get_level_values(0) 能解決 Price 標籤問題

            # 2. 下載 VIX 資料
            vix_df = yf.download("^VIX", start=start_date, end=end_date, progress=False, threads=False)
            
            if not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                # 只取 Close
                vix_series = vix_df['Close']
            else:
                st.warning("⚠️ 無法下載 VIX 數據，將假設 VIX=0 (不啟用恐慌濾網)。")
                vix_series = pd.Series(0, index=stock_df.index)

            # 3. 合併資料 (關鍵步驟：將 VIX 對齊台股日期)
            # 使用 reindex 將美股日期對齊到台股日期，缺值用 ffill (前值填充)
            aligned_vix = vix_series.reindex(stock_df.index, method='ffill')
            
            # 建立主 DataFrame
            df = stock_df.copy()
            df['VIX'] = aligned_vix.fillna(0) # 如果還有空值(例如第一天)，補0

            # 計算指標
            df = self.calculate_technicals(df)
            
            # 移除前 20 天 (因為 MA20 為 NaN)
            df = df.dropna()

            trades = []
            positions = []
            
            # 診斷用數據
            max_volume = df['Volume'].max() / 1000 if not df.empty else 0
            max_vix = df['VIX'].max() if not df.empty else 0
            
            # 模擬交易
            for i in range(len(df)):
                today = df.iloc[i]
                date = df.index[i]
                
                # --- 買入條件 ---
                # 1. 跌破布林下軌
                # 2. 爆量 > 7000張
                # 3. VIX > 20
                is_buy_signal = (today['Close'] < today['Lower']) and \
                                (today['Volume'] > self.volume_threshold) and \
                                (today['VIX'] > 20)
                
                # --- 賣出條件 ---
                # 1. 突破布林上軌
                # 2. 爆量 > 7000張
                # 3. VIX < 20
                is_sell_signal = (today['Close'] > today['Upper']) and \
                                 (today['Volume'] > self.volume_threshold) and \
                                 (today['VIX'] < 20)

                # 持續買入 (金字塔建倉)
                if is_buy_signal:
                    positions.append({
                        "entry_date": date,
                        "entry_price": today['Close'],
                        "entry_vix": today['VIX']
                    })
                
                # 全數賣出
                elif is_sell_signal and len(positions) > 0:
                    for pos in positions:
                        roi = (today['Close'] - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            "entry_date": pos['entry_date'],
                            "exit_date": date,
                            "entry_price": pos['entry_price'],
                            "exit_price": today['Close'],
                            "entry_vix": f"{pos['entry_vix']:.1f}",
                            "exit_vix": f"{today['VIX']:.1f}",
                            "volume_at_exit": int(today['Volume']/1000),
                            "return": roi,
                            "holding_days": (date - pos['entry_date']).days
                        })
                    positions = []

            # 統計診斷資料
            stats = {
                "max_vol": max_volume,
                "max_vix": max_vix,
                "data_count": len(df)
            }
            return pd.DataFrame(trades), stats
            
        except Exception as e:
            st.error(f"❌ 回測發生錯誤: {e}")
            return None, None

    def show_live_analysis(self):
        if self.stock_data is None: return
        
        df = self.calculate_technicals(self.stock_data.copy())
        today = df.iloc[-1]
        date_str = today.name.strftime('%Y-%m-%d')
        vol_today_sheets = int(today['Volume'] / 1000)
        
        buy_cond_price = today['Close'] < today['Lower']
        buy_cond_vol = today['Volume'] > self.volume_threshold
        buy_cond_vix = self.vix_data > 20
        buy_cond_fng = self.fng_score < 25 if self.fng_score else False
        
        sell_cond_price = today['Close'] > today['Upper']
        sell_cond_vol = today['Volume'] > self.volume_threshold
        sell_cond_vix = self.vix_data < 20
        sell_cond_fng = self.fng_score > 25 if self.fng_score else False

        buy_score = sum([buy_cond_price, buy_cond_vol, buy_cond_vix, buy_cond_fng])
        sell_score = sum([sell_cond_price, sell_cond_vol, sell_cond_vix, sell_cond_fng])

        st.markdown(f"## 📊 即時恐慌診斷 | {self.ticker}")
        st.caption(f"📅 資料日期: {date_str}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("收盤價", f"{today['Close']:.2f}")
        col2.metric("今日成交量", f"{vol_today_sheets:,} 張")
        col3.metric("F&G 指數", f"{self.fng_score}", delta="<25為恐慌")
        
        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"🟢 買入訊號 ({buy_score}/4)")
            if buy_score == 4: st.success("🚀 強力買入訊號觸發！")
            st.write(f"1. 布林下緣: {'✅ 符合' if buy_cond_price else '❌ 未跌破'}")
            st.write(f"2. 爆量 (>7000張): {'✅ 符合' if buy_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX > 20: {'✅ 符合' if buy_cond_vix else '❌ 未達標'} ({self.vix_data:.2f})")
            st.write(f"4. F&G < 25: {'✅ 符合' if buy_cond_fng else '❌ 未達標'}")

        with c2:
            st.subheader(f"🔴 賣出訊號 ({sell_score}/4)")
            if sell_score == 4: st.error("📉 強力賣出訊號觸發！")
            st.write(f"1. 布林上緣: {'✅ 符合' if sell_cond_price else '❌ 未突破'}")
            st.write(f"2. 爆量 (>7000張): {'✅ 符合' if sell_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX < 20: {'✅ 符合' if sell_cond_vix else '❌ 未達標'}")
            st.write(f"4. F&G > 25: {'✅ 符合' if sell_cond_fng else '❌ 未達標'}")

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
    
    with tab1:
        with st.spinner('分析即時數據中...'):
            if detector.fetch_live_data():
                detector.fetch_fear_and_greed()
                detector.show_live_analysis()
    
    with tab2:
        trades_df, stats = detector.run_backtest(start_date, end_date)
        
        if trades_df is not None:
            if not trades_df.empty:
                total_trades = len(trades_df)
                win_trades = len(trades_df[trades_df['return'] > 0])
                win_rate = (win_trades / total_trades) * 100
                avg_return = trades_df['return'].mean() * 100
                total_return = ((trades_df['return'] + 1).prod() - 1) * 100 
                
                st.markdown(f"### 📈 回測報告 ({start_date} ~ {end_date})")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("總交易筆數", f"{total_trades} 筆")
                m2.metric("勝率", f"{win_rate:.1f}%")
                m3.metric("平均報酬", f"{avg_return:.2f}%")
                m4.metric("總報酬", f"{total_return:.2f}%")
                
                st.dataframe(trades_df)
            else:
                st.warning("⚠️ 此區間內「無符合條件」的交易訊號。")
                if stats:
                    st.markdown("### 🕵️‍♂️ 策略診斷報告 (原因分析)")
                    c1, c2 = st.columns(2)
                    c1.metric("期間最大成交量", f"{int(stats['max_vol']):,} 張")
                    if stats['max_vol'] < 7000:
                        c1.error("❌ 最大量未達 7,000 張")
                    
                    c2.metric("期間最高 VIX", f"{stats['max_vix']:.2f}")
                    if stats['max_vix'] < 20:
                        c2.error("❌ 恐慌指數未達 20")
                    
                    st.info("💡 建議：此策略條件較嚴苛，請嘗試拉長回測日期（例如 2 年）以包含更多市場波動。")
