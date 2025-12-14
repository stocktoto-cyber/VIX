import yfinance as yf
import pandas as pd
import requests
import datetime

class MarketPanicDetector:
    def __init__(self, ticker='00675L.TW'):
        self.ticker = ticker
        self.stock_data = None
        self.vix_data = None
        self.fng_score = None
        
        # 設定參數
        self.rsi_threshold = 25       # RSI 超賣標準
        self.vix_threshold = 20       # VIX 恐慌標準
        self.fng_threshold = 25       # Fear & Greed 恐慌標準
        self.vol_multiplier = 1.5     # 爆量標準：大於 20MA 的幾倍

    def fetch_data(self):
        """抓取數據"""
        print(f"📥 正在抓取 {self.ticker} 與 VIX 數據...")
        try:
            stock = yf.Ticker(self.ticker)
            self.stock_data = stock.history(period="6mo")
            
            vix = yf.Ticker("^VIX")
            vix_df = vix.history(period="5d")
            if not vix_df.empty:
                self.vix_data = vix_df['Close'].iloc[-1]
            else:
                self.vix_data = 0
        except Exception as e:
            print(f"❌ 數據抓取失敗: {e}")

    def fetch_fear_and_greed(self):
        """爬取 CNN Fear & Greed Index"""
        print("📥 正在連線 CNN 抓取貪婪恐慌指數...")
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
        """輸出結果 (已修正為張數)"""
        if self.stock_data is None:
            return

        today = self.stock_data.iloc[-1]
        date_str = today.name.strftime('%Y-%m-%d')
        
        # --- 單位換算 (股 -> 張) ---
        # yfinance 台股 Volume 通常是股數，除以 1000 換算成張
        vol_today_sheets = int(today['Volume'] / 1000)
        vol_ma_sheets = int(today['Vol_MA20'] / 1000)
        
        # 條件判斷
        cond_lower_band = today['Close'] < today['Lower']
        cond_volume = today['Volume'] > (today['Vol_MA20'] * self.vol_multiplier)
        cond_rsi = today['RSI'] < self.rsi_threshold
        cond_vix = self.vix_data > self.vix_threshold if self.vix_data else False
        cond_fng = self.fng_score < self.fng_threshold if self.fng_score else False

        # --- 顯示報告 ---
        print("\n" + "="*40)
        print(f"📊 恐慌指標檢測報告 | 標的: {self.ticker}")
        print(f"📅 資料日期: {date_str}")
        print("="*40)

        print(f"1. [技術面] 價格 vs 布林下緣:")
        print(f"   收盤價 {today['Close']:.2f} | 下軌 {today['Lower']:.2f}")
        print(f"   判定: {'🔴 跌破下軌 (符合)' if cond_lower_band else '🟢 未跌破'}")
        
        print(f"\n2. [籌碼面] 成交量 (單位: 張):")
        print(f"   今日量: {vol_today_sheets:,} 張")
        print(f"   20日均量: {vol_ma_sheets:,} 張")
        print(f"   判定: {'🔴 爆量恐慌殺盤 (符合)' if cond_volume else '🟢 量能正常'}")

        print(f"\n3. [動能面] RSI 指標:")
        print(f"   數值 {today['RSI']:.2f}")
        print(f"   判定: {'🔴 嚴重超賣 (符合)' if cond_rsi else '🟢 尚未超賣'}")

        print(f"\n4. [避險面] VIX 恐慌指數:")
        print(f"   數值 {self.vix_data:.2f}")
        print(f"   判定: {'🔴 市場恐慌 (符合)' if cond_vix else '🟢 市場平穩'}")

        print(f"\n5. [情緒面] Fear & Greed Index:")
        if self.fng_score:
            print(f"   數值 {self.fng_score}")
            print(f"   判定: {'🔴 極度恐慌 (符合)' if cond_fng else '🟢 情緒尚可'}")
        else:
            print("   ⚠️ 無法取得數據")

        # --- 總結 ---
        print("-" * 40)
        score = sum([cond_lower_band, cond_volume, cond_rsi, cond_vix, cond_fng])
        print(f"🎯 恐慌訊號總分: {score} / 5")
        
        if score >= 4:
            print("🚨 訊號極強！市場極度非理性，00675L 可考慮分批進場搶反彈。")
        elif score >= 3:
            print("⚠️ 訊號中等，建議觀察盤中是否有「下影線」再動作。")
        else:
            print("☕ 目前尚未出現明顯的過度恐慌訊號，建議觀望。")
        print("="*40)

if __name__ == "__main__":
    bot = MarketPanicDetector('00675L.TW')
    bot.fetch_data()
    bot.fetch_fear_and_greed()
    bot.calculate_technicals()
    bot.analyze()
