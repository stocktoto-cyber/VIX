import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="恐慌指標檢測器 (黑底版)", page_icon="🚨", layout="wide")

# --- 2. CSS 樣式 (黑底白字風格) ---
st.markdown("""
    <style>
    /* 全域設定 */
    .stApp { background-color: #0E1117 !important; color: #FFFFFF !important; }
    h1, h2, h3, h4, h5, h6, p, span, div, label, li, .stMarkdown { color: #FAFAFA !important; }
    
    /* 側邊欄 */
    section[data-testid="stSidebar"] { background-color: #262730 !important; }
    section[data-testid="stSidebar"] * { color: #FFFFFF !important; }

    /* 指標卡片 */
    div[data-testid="stMetric"] {
        background-color: #1E1E1E !important;
        border: 1px solid #444444 !important;
        padding: 15px !important;
        border-radius: 10px !important;
        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.5) !important;
    }
    div[data-testid="stMetricLabel"] p { color: #AAAAAA !important; font-weight: bold !important; }
    div[data-testid="stMetricValue"] div { color: #FFFFFF !important; font-weight: 900 !important; }
    div[data-testid="stMetricDelta"] svg { fill: auto !important; }
    div[data-testid="stMetricDelta"] > div { color: auto !important; }

    /* 按鈕 */
    div[data-testid="stButton"] button {
        background-color: #FF9800 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
    }
    div[data-testid="stButton"] button p { color: white !important; }

    /* 輸入框 & 下拉選單 */
    div[data-testid="stTextInput"] input, div[data-testid="stDateInput"] input, div[data-testid="stNumberInput"] input {
        background-color: #333333 !important;
        color: #FFFFFF !important;
        border: 1px solid #555555 !important;
    }
    div[data-testid="stSelectbox"] > div > div {
        background-color: #333333 !important;
        color: #FFFFFF !important;
    }
    
    /* 表格 */
    div[data-testid="stDataFrame"] { background-color: #1E1E1E !important; }
    
    /* 狀態提示框 */
    div[data-testid="stNotification"] {
        background-color: #333333 !important;
        color: #FFFFFF !important;
        border: 1px solid #555555 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心類別 ---
class MarketPanicDetector:
    def __init__(self, ticker_input='00675L', vol_multiplier=2.0, manual_fng=50):
        # --- 智慧代碼判斷邏輯 ---
        ticker_input = str(ticker_input).strip().upper()
        
        has_digit = any(char.isdigit() for char in ticker_input)
        
        if has_digit:
            # 台股模式
            self.is_tw_stock = True
            self.unit_label = "張"
            self.unit_divisor = 1000
            
            if not (ticker_input.endswith('.TW') or ticker_input.endswith('.TWO')):
                self.ticker = f"{ticker_input}.TW"
            else:
                self.ticker = ticker_input
        else:
            # 美股模式
            self.is_tw_stock = False
            self.unit_label = "股"
            self.unit_divisor = 1
            self.ticker = ticker_input

        self.vol_multiplier = vol_multiplier
        self.manual_fng = manual_fng
        self.stock_data = None
        self.vix_data = None
        self.fng_score = None

    def fetch_live_data(self):
        try:
            stock = yf.Ticker(self.ticker)
            self.stock_data = stock.history(period="6mo")
            
            # 自動修正 .TW -> .TWO
            if self.stock_data.empty and self.is_tw_stock and self.ticker.endswith('.TW'):
                alt_ticker = self.ticker.replace('.TW', '.TWO')
                stock = yf.Ticker(alt_ticker)
                temp_data = stock.history(period="6mo")
                
                if not temp_data.empty:
                    self.ticker = alt_ticker
                    self.stock_data = temp_data
            
            if self.stock_data.empty:
                st.error(f"❌ 查無【{self.ticker}】資料。請確認代碼是否正確 (例如是否已下市)。")
                return False

            vix = yf.Ticker("^VIX")
            vix_df = vix.history(period="5d")
            self.vix_data = vix_df['Close'].iloc[-1] if not vix_df.empty else 0
            return True
        except Exception as e:
            st.error(f"❌ 數據抓取失敗: {e}")
            return False

    def fetch_fear_and_greed(self):
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.cnn.com/"
        }
        try:
            response = requests.get(url, headers=headers, timeout=3)
            if response.status_code == 200:
                data = response.json()
                self.fng_score = round(data['fear_and_greed']['score'])
            else:
                self.fng_score = None
        except:
            self.fng_score = None

    def calculate_technicals(self, df):
        if df is None or df.empty: return df
        
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

    def run_backtest(self, start_date, end_date):
        msg_box = st.empty()
        buffer_days = 60
        fetch_start = start_date - timedelta(days=buffer_days)
        
        msg_box.info(f"📥 正在下載數據 ({self.ticker})...")
        
        try:
            stock_df = yf.download(self.ticker, start=fetch_start, end=end_date, progress=False, threads=False)
            
            if stock_df.empty:
                msg_box.error(f"❌ 無法下載 {self.ticker} 資料。")
                return None, None
            
            if isinstance(stock_df.columns, pd.MultiIndex):
                stock_df.columns = stock_df.columns.get_level_values(0)
            if stock_df.index.tz is not None:
                stock_df.index = stock_df.index.tz_localize(None)

            vix_df = yf.download("^VIX", start=fetch_start, end=end_date, progress=False, threads=False)
            vix_series = pd.Series(0, index=stock_df.index)
            
            if not vix_df.empty:
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_df.columns = vix_df.columns.get_level_values(0)
                if vix_df.index.tz is not None:
                    vix_df.index = vix_df.index.tz_localize(None)
                vix_series = vix_df['Close']

            aligned_vix = vix_series.reindex(stock_df.index, method='ffill')
            df = stock_df.copy()
            df['VIX'] = aligned_vix.fillna(0)

            msg_box.info("🔄 正在計算策略...")
            df = self.calculate_technicals(df)
            
            start_datetime = pd.to_datetime(start_date)
            df = df[df.index >= start_datetime]
            df = df.dropna()
            
            if df.empty:
                 msg_box.warning("⚠️ 此區間無交易資料。")
                 return None, None

            trades = []
            positions = []
            
            df['Check_Vol'] = df['Volume'] > (df['Vol_MA20'] * self.vol_multiplier)
            df['Check_Price'] = df['Close'] < df['Lower']
            df['Check_VIX'] = df['VIX'] > 20
            df['Signal_Buy'] = df['Check_Price'] & df['Check_Vol'] & df['Check_VIX']

            for i in range(len(df)):
                today = df.iloc[i]
                date = df.index[i]
                
                is_buy = today['Signal_Buy']
                is_sell = (today['Close'] > today['Upper']) and \
                          today['Check_Vol'] and \
                          (today['VIX'] < 20)

                if is_buy:
                    positions.append({
                        "entry_date": date,
                        "entry_price": today['Close'],
                        "entry_vix": today['VIX'],
                        "entry_vol": today['Volume']
                    })
                elif is_sell and len(positions) > 0:
                    for pos in positions:
                        roi = (today['Close'] - pos['entry_price']) / pos['entry_price']
                        trades.append({
                            "entry_date": pos['entry_date'],
                            "exit_date": date,
                            "entry_price": pos['entry_price'],
                            "exit_price": today['Close'],
                            "entry_vix": f"{pos['entry_vix']:.1f}",
                            "exit_vix": f"{today['VIX']:.1f}",
                            "volume_at_entry": int(pos['entry_vol'] / self.unit_divisor),
                            "volume_at_exit": int(today['Volume'] / self.unit_divisor),
                            "return": roi,
                            "holding_days": (date - pos['entry_date']).days
                        })
                    positions = []

            msg_box.empty()
            
            last_vol_ma = df['Vol_MA20'].iloc[-1] if not df.empty else 0
            
            stats = {
                "total_days": len(df),
                "count_price": df['Check_Price'].sum(),
                "count_vol": df['Check_Vol'].sum(),
                "count_vix": df['Check_VIX'].sum(),
                "count_all": df['Signal_Buy'].sum(),
                "last_vol_ma": last_vol_ma,
                "max_vix": df['VIX'].max() if not df.empty else 0
            }
            return pd.DataFrame(trades), stats
            
        except Exception as e:
            msg_box.error(f"❌ 回測錯誤: {e}")
            return None, None

    def show_live_analysis(self):
        if self.stock_data is None or self.stock_data.empty: return
        
        df = self.calculate_technicals(self.stock_data.copy())
        if df.empty: return

        today = df.iloc[-1]
        date_str = today.name.strftime('%Y-%m-%d')
        
        vol_today_display = int(today['Volume'] / self.unit_divisor)
        vol_ma_display = int(today['Vol_MA20'] / self.unit_divisor) if pd.notna(today['Vol_MA20']) else 0
        
        target_vol = today['Vol_MA20'] * self.vol_multiplier
        target_vol_display = int(target_vol / self.unit_divisor) if pd.notna(target_vol) else 0

        final_fng = self.fng_score if self.fng_score is not None else self.manual_fng
        source_label = "CNN即時" if self.fng_score is not None else "手動輸入"

        buy_cond_price = today['Close'] < today['Lower']
        buy_cond_vol = today['Volume'] > target_vol
        buy_cond_vix = self.vix_data > 20
        buy_cond_fng = final_fng < 25
        
        sell_cond_price = today['Close'] > today['Upper']
        sell_cond_vol = today['Volume'] > target_vol
        sell_cond_vix = self.vix_data < 20
        sell_cond_fng = final_fng > 75

        buy_score = sum([buy_cond_price, buy_cond_vol, buy_cond_vix, buy_cond_fng])
        sell_score = sum([sell_cond_price, sell_cond_vol, sell_cond_vix, sell_cond_fng])

        st.markdown(f"## 📊 即時恐慌診斷 | {self.ticker}")
        st.caption(f"📅 資料日期: {date_str} | 💥 爆量定義：> {self.vol_multiplier} 倍均量 ({target_vol_display:,} {self.unit_label})")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("收盤價", f"{today['Close']:.2f}")
        col2.metric("今日成交量", f"{vol_today_display:,} {self.unit_label}", delta=f"均量 {vol_ma_display:,}")
        
        fng_display = f"{final_fng}" if final_fng is not None else "N/A"
        col3.metric(f"恐懼與貪婪指數 ({source_label})", fng_display, delta="<25恐慌 / >75極貪婪")
        
        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"🟢 買入訊號 ({buy_score}/4)")
            if buy_score == 4: st.success("🚀 強力買入訊號觸發！")
            st.write(f"1. 布林下緣: {'✅ 符合' if buy_cond_price else '❌ 未跌破'}")
            st.write(f"2. 爆量 (>{self.vol_multiplier}倍): {'✅ 符合' if buy_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX > 20: {'✅ 符合' if buy_cond_vix else '❌ 未達標'} ({self.vix_data:.2f})")
            st.write(f"4. 恐懼與貪婪指數 < 25: {'✅ 符合' if buy_cond_fng else '❌ 未達標'}")

        with c2:
            st.subheader(f"🔴 賣出訊號 ({sell_score}/4)")
            if sell_score == 4: st.error("📉 強力賣出訊號觸發！")
            st.write(f"1. 布林上緣: {'✅ 符合' if sell_cond_price else '❌ 未突破'}")
            st.write(f"2. 爆量 (>{self.vol_multiplier}倍): {'✅ 符合' if sell_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX < 20: {'✅ 符合' if sell_cond_vix else '❌ 未達標'}")
            st.write(f"4. 恐懼與貪婪指數 > 75: {'✅ 符合' if sell_cond_fng else '❌ 未達標'}")

# --- 4. 主程式邏輯 ---

with st.sidebar:
    st.markdown("### ⚙️ 設定面板")
    ticker_input = st.text_input("股票代碼 (台股免加 .TW, 美股直接輸入)", value="00675L")
    
    st.markdown("---")
    st.markdown("### 💥 爆量定義")
    vol_multiplier = st.slider("成交量需大於均量的幾倍?", 1.0, 5.0, 2.0, 0.1)
    
    st.markdown("---")
    st.markdown("### 😨 恐懼與貪婪指數 (手動備援)")
    st.info("若自動抓取顯示 None，請手動輸入目前指數。")
    manual_fng_input = st.number_input("手動輸入數值", min_value=0, max_value=100, value=50)
    
    st.markdown("---")
    st.markdown("### 📅 回測設定")
    
    # === 日期快速區間選擇 ===
    date_ranges = {
        "自訂日期": (None, None),
        "近 1 年": (datetime.now() - timedelta(days=365), datetime.now()),
        "近 3 年": (datetime.now() - timedelta(days=365*3), datetime.now()),
        "近 5 年": (datetime.now() - timedelta(days=365*5), datetime.now()),
        "2024 (AI爆發)": (datetime(2024, 1, 1), datetime(2024, 12, 31)),
        "2023 (盤整復甦)": (datetime(2023, 1, 1), datetime(2023, 12, 31)),
        "2022 (升息/空頭)": (datetime(2022, 1, 1), datetime(2022, 12, 31)),
        "2021 (航運/大牛)": (datetime(2021, 1, 1), datetime(2021, 12, 31)),
        "2020 (疫情V轉)": (datetime(2020, 1, 1), datetime(2020, 12, 31)),
        "2019 (預防性降息)": (datetime(2019, 1, 1), datetime(2019, 12, 31)),
        "2018 (美中貿易戰)": (datetime(2018, 1, 1), datetime(2018, 12, 31)),
        "2008 (金融海嘯)": (datetime(2008, 1, 1), datetime(2008, 12, 31)),
    }

    # Callback 函數
    def update_dates():
        selected = st.session_state.preset_selection
        if selected != "自訂日期":
            start, end = date_ranges[selected]
            if end > datetime.now(): end = datetime.now()
            st.session_state.start_input = start
            st.session_state.end_input = end

    st.selectbox("快速區間", options=list(date_ranges.keys()), key="preset_selection", on_change=update_dates)

    if 'start_input' not in st.session_state:
        st.session_state.start_input = datetime.now() - timedelta(days=365*2)
    if 'end_input' not in st.session_state:
        st.session_state.end_input = datetime.now()

    start_date = st.date_input("開始日期", key="start_input")
    end_date = st.date_input("結束日期", key="end_input")
    
    run_btn = st.button("🚀 開始執行", type="primary")

if run_btn:
    detector = MarketPanicDetector(ticker_input, vol_multiplier, manual_fng_input)
    
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
                
                # 增加備註
                st.caption("ℹ️ 註：回測表中的恐慌指數使用 VIX 歷史數據呈現，因 F&G 指數無公開歷史資料。")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("總交易筆數", f"{total_trades} 筆")
                m2.metric("勝率", f"{win_rate:.1f}%")
                m3.metric("平均報酬", f"{avg_return:.2f}%")
                m4.metric("總報酬", f"{total_return:.2f}%")
                
                display_df = trades_df.copy()
                display_df['return'] = display_df['return'].apply(lambda x: f"{x*100:.2f}%")
                
                vol_unit_name = detector.unit_label
                
                # 修改欄位名稱
                display_df.columns = [
                    "進場日期", "出場日期", "進場價格", "出場價格", 
                    "進場恐慌指數 (VIX)", "出場恐慌指數 (VIX)", 
                    f"進場成交量 ({vol_unit_name})", 
                    f"出場成交量 ({vol_unit_name})", 
                    "報酬率", "持有天數"
                ]
                
                st.dataframe(display_df)
            else:
                st.warning("⚠️ 此區間內「無符合條件」的交易訊號。")
                
                if stats:
                    st.markdown("### 🕵️‍♂️ 為什麼沒買到？(條件診斷)")
                    st.write(f"統計期間：{stats['total_days']} 個交易日")
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("符合「跌破下軌」天數", f"{stats['count_price']} 天")
                    
                    last_vol_str = int(stats['last_vol_ma'] / detector.unit_divisor)
                    c2.metric(f"符合「>{vol_multiplier}倍爆量」天數", f"{stats['count_vol']} 天", 
                              help=f"近期均量約: {last_vol_str:,} {detector.unit_label}")
                    
                    display_max_vix = stats['max_vix'] if pd.notna(stats['max_vix']) else 0
                    c3.metric("符合「VIX>20」天數", f"{stats['count_vix']} 天", help=f"期間最高VIX: {display_max_vix:.2f}")
                    
                    c4.metric("🔥 三者同時符合", f"{stats['count_all']} 天")
