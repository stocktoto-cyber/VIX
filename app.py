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

    # --- 功能 B: 回測邏輯 (加入 VIX 濾網) ---
    def run_backtest(self, start_date, end_date):
        st.info(f"正在下載股價與 VIX 歷史數據 ({start_date} ~ {end_date})...")
        
        # 1. 同時抓取 個股 與 VIX 歷史資料
        try:
            # 下載多檔股票數據
            data = yf.download([self.ticker, "^VIX"], start=start_date, end=end_date, progress=False)
            
            if data.empty:
                st.error("此區間無資料")
                return None
            
            # 整理數據 (yfinance 下載多檔時會變 MultiIndex)
            if isinstance(data.columns, pd.MultiIndex):
                # 提取個股 Close 和 Volume
                df = pd.DataFrame()
                df['Close'] = data['Close'][self.ticker]
                df['Open'] = data['Open'][self.ticker]
                df['High'] = data['High'][self.ticker]
                df['Low'] = data['Low'][self.ticker]
                df['Volume'] = data['Volume'][self.ticker]
                
                # 提取 VIX Close
                df['VIX'] = data['Close']['^VIX']
            else:
                # 萬一只有單檔 (防呆)
                st.error("數據下載異常，請稍後再試。")
                return None

            # 補值 (VIX 資料有時會缺漏)
            df['VIX'] = df['VIX'].fillna(method='ffill')

            # 計算指標
            df = self.calculate_technicals(df)
            
            # 2. 模擬交易
            trades = []
            position = None 
            
            for i in range(20, len(df)):
                today = df.iloc[i]
                date = df.index[i]
                
                # ---------------------------------------------------
                # 策略條件設定
                # ---------------------------------------------------
                
                # [買入條件]
                # 1. 收盤 < 布林下軌
                # 2. 成交量 > 7,000 張 (7,000,000 股)
                # 3. VIX > 20 (市場恐慌)
                # (註: F&G 因無歷史數據，此處以 VIX 為主)
                is_buy_signal = (today['Close'] < today['Lower']) and \
                                (today['Volume'] > 7000000) and \
                                (today['VIX'] > 20)
                
                # [賣出條件]
                # 1. 收盤 > 布林上軌
                # 2. 成交量 > 7,000 張
                # 3. VIX < 20 (市場回穩)
                is_sell_signal = (today['Close'] > today['Upper']) and \
                                 (today['Volume'] > 7000000) and \
                                 (today['VIX'] < 20)

                # 執行交易
                if position is None and is_buy_signal:
                    position = {
                        "entry_date": date,
                        "entry_price": today['Close'],
                        "entry_vix": today['VIX']
                    }
                elif position is not None and is_sell_signal:
                    roi = (today['Close'] - position['entry_price']) / position['entry_price']
                    trades.append({
                        "entry_date": position['entry_date'],
                        "exit_date": date,
                        "entry_price": position['entry_price'],
                        "exit_price": today['Close'],
                        "entry_vix": f"{position['entry_vix']:.1f}",
                        "exit_vix": f"{today['VIX']:.1f}",
                        "volume_at_exit": int(today['Volume']/1000),
                        "return": roi,
                        "holding_days": (date - position['entry_date']).days
                    })
                    position = None

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
        
        # 單位換算
        vol_today_sheets = int(today['Volume'] / 1000)
        
        # ---------------------------------------------------
        # 即時診斷條件 (包含 Fear & Greed)
        # ---------------------------------------------------
        
        # 買入訊號檢核
        buy_cond_price = today['Close'] < today['Lower']
        buy_cond_vol = today['Volume'] > 7000000
        buy_cond_vix = self.vix_data > 20
        buy_cond_fng = self.fng_score < 25 if self.fng_score else False
        
        buy_score = sum([buy_cond_price, buy_cond_vol, buy_cond_vix, buy_cond_fng])

        # 賣出訊號檢核 (僅供參考)
        sell_cond_price = today['Close'] > today['Upper']
        sell_cond_vol = today['Volume'] > 7000000
        sell_cond_vix = self.vix_data < 20
        sell_cond_fng = self.fng_score > 25 if self.fng_score else False

        # UI 顯示
        st.markdown(f"<h2 style='color:#333333;'>📊 即時恐慌診斷 | {self.ticker}</h2>", unsafe_allow_html=True)
        st.caption(f"📅 資料日期: {date_str}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("收盤價", f"{today['Close']:.2f}")
        col2.metric("今日成交量", f"{vol_today_sheets:,} 張")
        col3.metric("符合買入條件", f"{buy_score} / 4")
        
        st.markdown("---")
        
        # 詳細條件燈號
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🟢 買入條件檢核")
            st.write(f"1. 布林下緣: {'✅ 符合' if buy_cond_price else '❌ 未跌破'}")
            st.write(f"2. 爆量 (>7000張): {'✅ 符合' if buy_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX > 20: {'✅ 符合' if buy_cond_vix else '❌ 未達標'} ({self.vix_data:.2f})")
            st.write(f"4. F&G < 25: {'✅ 符合' if buy_cond_fng else '❌ 未達標'} ({self.fng_score})")

        with c2:
            st.subheader("🔴 賣出條件檢核")
            st.write(f"1. 布林上緣: {'✅ 符合' if sell_cond_price else '❌ 未突破'}")
            st.write(f"2. 爆量 (>7000張): {'✅ 符合' if sell_cond_vol else '❌ 未達標'}")
            st.write(f"3. VIX < 20: {'✅ 符合' if sell_cond_vix else '❌ 未達標'}")
            st.write(f"4. F&G > 25: {'✅ 符合' if sell_cond_fng else '❌ 極度恐慌中'}")

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
        with st.spinner('下載股價與 VIX 數據並回測中...'):
            trades_df = detector.run_backtest(start_date, end_date)
            
            if trades_df is not None and not trades_df.empty:
                total_trades = len(trades_df)
                win_trades = len(trades_df[trades_df['return'] > 0])
                win_rate = (win_trades / total_trades) * 100
                avg_return = trades_df['return'].mean() * 100
                total_return = ((trades_df['return'] + 1).prod() - 1) * 100 
                
                st.markdown(f"<h3 style='color:#333333;'>📈 回測報告 ({start_date} ~ {end_date})</h3>", unsafe_allow_html=True)
                st.warning("⚠️ 注意：由於無法取得「CNN 貪婪恐慌指數」的歷史數據，回測僅使用 VIX 作為情緒濾網。")
                st.info("""
                💡 **策略邏輯**：
                * **買入**：跌破布林下緣 + 爆量(>7000張) + **VIX > 20** (恐慌)
                * **賣出**：突破布林上緣 + 爆量(>7000張) + **VIX < 20** (平穩)
                """)

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
                
                display_df.columns = ["進場日期", "出場日期", "進場價", "出場價", "進場VIX", "出場VIX", "出場量", "報酬率", "持有天數"]
                
                st.dataframe(display_df, use_container_width=True)
                
            elif trades_df is not None:
                st.warning("⚠️ 在此區間內未發現符合策略的交易訊號。")
                st.markdown("可能原因：條件非常嚴格 (需同時滿足價格極端、爆大量且VIX配合)。")
