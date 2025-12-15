import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式 (UI 修復版) ---
st.markdown("""
    <style>
    .stApp { background-color: #F0F0F3 !important; }
    h1, h2, h3, h4, h5, h6, p, span, div, label, .stMarkdown { color: #333333 !important; }
    section[data-testid="stSidebar"] { background-color: #EAEAED !important; }
    section[data-testid="stSidebar"] * { color: #333333 !important; }

    /* 卡片樣式 */
    div[data-testid="stMetric"] {
        background-color: #F0F0F3 !important;
        border: 1px solid #ffffff !important;
        padding: 15px !important;
        border-radius: 20px !important;
        box-shadow: 6px 6px 12px #c5c5c5, -6px -6px 12px #ffffff !important;
    }
    div[data-testid="stMetric"] label { color: #666666 !important; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #000000 !important; }
    div[data-testid="stMetricValue"] * { color: #000000 !important; }
    div[data-testid="stMetricDelta"] svg { fill: auto !important; }
    div[data-testid="stMetricDelta"] > div { color: auto !important; }

    /* 按鈕樣式 */
    div[data-testid="stButton"] button {
        background: linear-gradient(145deg, #FFB74D, #FF9800) !important;
        color: white !important;
        border-radius: 30px !important;
        border: none !important;
        box-shadow: 5px 5px 10px #d1d1d1, -5px -5px 10px #ffffff !important;
    }
    div[data-testid="stButton"] button * { color: white !important; }

    /* 輸入框樣式 */
    div[data-testid="stTextInput"] input, div[data-testid="stDateInput"] input {
        background-color: #E8E8EB !important;
        color: #000000 !important;
        border-radius: 10px !important;
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
        msg_box = st.empty() # 佔位符，用於動態更新訊息
        msg_box.info(f"📥 正在分開下載數據 ({start_date} ~ {end_date})...")
        
        try:
            # 1. 下載台股
            stock_df = yf.download(self.ticker, start=start_date, end=end_date, progress=False, threads=False)
            if stock_df.empty:
                msg_box.error(f"❌ 無法下載 {self.ticker} 的股價資料。")
                return None, None
            
            # 處理 MultiIndex 並強制移除時區 (關鍵修正)
            if isinstance(stock_df.columns, pd.MultiIndex):
                stock_df.columns = stock_df.columns.get_level_values(0)
            if stock_df.index.tz is not None:
                stock_df.index = stock_df.index.tz_localize(None)

            # 2. 下載 VIX
            vix_df = yf.download("^VIX", start=start_date, end=end_date, progress=False, threads=False)
            vix_series = pd.Series(0, index=stock_df.index)
            
            if not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                # 強制移除時區 (關鍵修正)
                if vix_df.index.tz is not None:
                    vix_df.index = vix_df.index.tz_localize(None)
                vix_series = vix_df['Close']

            # 3. 合併資料
            aligned_vix = vix_series.reindex(stock_df.index, method='ffill')
            df = stock_df.copy()
            df['VIX'] = aligned_vix.fillna(0)

            msg_box.info("🔄 正在計算技術指標與策略模擬...")
            df = self.calculate_technicals(df)
            df = df.dropna() # 去除計算指標後的空值

            trades = []
            positions = []
            
            # 診斷用：找出最接近條件的日子
            df['Vol_Check'] = df['Volume'] > self.volume_threshold
            df['VIX_Check'] = df['VIX'] > 20
            df['Price_Check'] = df['Close'] < df['Lower']
            # 計算每個人符合幾個條件
            df['Signal_Score'] = df['Vol_Check'].astype(int) + df['VIX_Check'].astype(int) + df['Price_Check'].astype(int)

            for i in range(len(df)):
                today = df.iloc[i]
                date = df.index[i]
                
                # 買入條件
                is_buy_signal = today['Price_Check'] and today['Vol_Check'] and today['VIX_Check']
                
                # 賣出條件
                is_sell_signal = (today['Close'] > today['Upper']) and \
                                 (today['Volume'] > self.volume_threshold) and \
                                 (today['VIX'] < 20)

                if is_buy_signal:
                    positions.append({
                        "entry_date": date,
                        "entry_price": today['Close'],
                        "entry_vix": today['VIX']
                    })
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

            msg_box.empty() # 清除訊息
            
            # 回傳交易紀錄 與 診斷用 DataFrame
            return pd.DataFrame(trades), df
            
        except Exception as e:
            msg_box.error(f"❌ 回測發生錯誤: {e}")
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
        trades_df, diagnostic_df = detector.run_backtest(start_date, end_date)
        
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
                
                if diagnostic_df is not None and not diagnostic_df.empty:
                    st.markdown("### 🕵️‍♂️ 策略診斷：最接近買入條件的 3 天")
                    
                    # 找出分數最高（符合最多條件）的前 3 天
                    top_candidates = diagnostic_df.nlargest(3, 'Signal_Score')
                    
                    for date, row in top_candidates.iterrows():
                        date_str = date.strftime('%Y-%m-%d')
                        st.markdown(f"**📅 日期：{date_str}**")
                        
                        c1, c2, c3 = st.columns(3)
                        
                        # 顯示條件狀態
                        val_vol = int(row['Volume']/1000)
                        val_vix = row['VIX']
                        is_vol_ok = row['Vol_Check']
                        is_vix_ok = row['VIX_Check']
                        is_price_ok = row['Price_Check']
                        
                        c1.metric("1. 價格跌破下軌", f"{'✅ 是' if is_price_ok else '❌ 否'}", 
                                  delta=f"收 {row['Close']:.2f} / 下 {row['Lower']:.2f}")
                        
                        c2.metric("2. 爆量 > 7000張", f"{'✅ 是' if is_vol_ok else '❌ 否'}",
                                  delta=f"{val_vol:,} 張")
                        
                        c3.metric("3. VIX > 20", f"{'✅ 是' if is_vix_ok else '❌ 否'}",
                                  delta=f"{val_vix:.2f}")
                        
                        st.divider()
                    
                    st.info("💡 如果看到很多「❌」，代表該條件太嚴苛。建議可嘗試放寬「成交量」或「VIX」門檻。")
