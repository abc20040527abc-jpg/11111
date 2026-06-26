# Crypto AI Trader - BingX SMC Scanner

這是一個 BingX 合約掃描器，會掃描 BingX USDT 合約，找出符合以下任一開單邏輯的標的：

- SMC 任一條件：BOS、流動性掃損、FVG。
- EMA200 + 布林帶：EMA200 作為方向濾網，布林帶作為觸發。站上 EMA200 且下軌反彈/上軌突破偏多；跌破 EMA200 且上軌受阻/下軌跌破偏空。
- 金十數據：用事件面文字粗略判斷 `RISK_ON`、`RISK_OFF`、`NEUTRAL`，作為方向提醒。

預設只顯示訊號，不會自動下單。

## 網站版

直接雙擊：

```text
一鍵打開網站.bat
```

網站會開在：

```text
http://127.0.0.1:8788
```

在網站裡可以設定週期、掃描數量、指定幣種，按「開始掃描」後會顯示多空方向、進場、止損、1R、1.5R、風險百分比與 TradingView 連結。掃描結果仍會同步輸出到 `signals.csv`。

## 快速開始

```powershell
cd C:\Users\test\Documents\Codex\2026-06-26\smc-codex-1-smc-2-1\outputs\crypto_ai_trader
.\run.ps1 --max-symbols 30
```

掃描單一幣種：

```powershell
.\run.ps1 --symbol BTC-USDT
```

輸出結果會包含：

- `entry`：用最新收盤價作為參考進場價。
- `stop`：多單放前低，空單放前高。
- `tp1R`：1R 止盈。
- `tp1.5R`：1.5R 止盈。
- `TradingView`：BingX 圖表參考連結。
- `signals.csv`：掃描結果表格。

## 金十數據接入

如果你沒有金十 API，直接編輯 `jin10_events.json`，把金十快訊貼進去即可：

```json
[
  {"title": "美聯儲官員釋放鴿派訊號", "content": "市場預期降息提前，風險資產走強。"}
]
```

如果你有金十 API，可用環境變數接入：

```powershell
$env:JIN10_API_URL="https://你的金十資料接口"
$env:JIN10_API_TOKEN="你的token"
.\run.ps1
```

程式會讀取 API 回傳中的 `title`、`content`、`summary`、`text` 欄位。

## BingX 真實下單

預設是乾跑模式。真實下單前請先確認策略、倉位、槓桿、交易權限與 API IP 白名單。

設定 API：

```powershell
$env:BINGX_API_KEY="你的key"
$env:BINGX_API_SECRET="你的secret"
```

送出市價單：

```powershell
.\run.ps1 --symbol BTC-USDT --place-orders --quantity 0.001 --order-limit 1
```

注意：目前程式只送出進場市價單，止損/止盈仍建議先手動掛單或在確認 BingX 條件單參數後再擴充自動 TP/SL。這是為了避免 API 參數誤用造成不必要的實盤風險。

## 策略提醒

這套邏輯是訊號掃描器，不是保證獲利模型。建議先用小範圍掃描和模擬盤驗證：

```powershell
.\run.ps1 --max-symbols 10 --interval 15m
.\run.ps1 --max-symbols 50 --interval 1h
.\run.ps1 --max-symbols 50 --interval 4h
```

常見調整方向：

- 想提高訊號數量：降低週期，例如 `15m`。
- 想提高訊號品質：只看 `score >= 2` 的結果。
- 想避開事件風險：金十偏 `RISK_OFF` 時少做多，偏 `RISK_ON` 時少做空。
