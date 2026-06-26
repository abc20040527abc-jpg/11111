# 上架網站

這個網站需要 Python 後端即時抓 BingX K 線，所以請用支援 Web Service 的平台，例如 Render、Railway、Fly.io 或自己的 VPS。不要只用純靜態網站平台，否則 `/api/scan` 不會運作。

## Render 上架步驟

1. 把 `crypto_ai_trader` 資料夾上傳到 GitHub repository。
2. 登入 Render，建立 `New > Web Service`。
3. 連接你的 GitHub repository。
4. 設定：
   - Runtime: `Python`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python local_app.py`
   - Health Check Path: `/api/status`
5. 建立服務後，Render 會給你一個 `https://你的服務名.onrender.com` 網址。

本專案已經附上 `render.yaml`，Render 也可以用 Blueprint 方式部署。

## 環境變數

目前預設只掃描訊號，不會實盤下單。若你要接金十 API，可在平台環境變數加入：

```text
JIN10_API_URL=你的金十資料接口
JIN10_API_TOKEN=你的token
```

不建議一開始把 BingX 下單金鑰放到公開網站。若未來要做登入權限和實盤下單，再加入：

```text
BINGX_API_KEY=你的key
BINGX_API_SECRET=你的secret
```

## 注意

- 免費雲端服務可能會休眠，第一次開啟會比較慢。
- `signals.csv` 在雲端通常是暫存檔，重新部署後可能消失。
- 若網站公開給其他人使用，建議加登入密碼與掃描頻率限制，避免 API 被大量請求。
