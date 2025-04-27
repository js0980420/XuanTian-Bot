# 命理師 LINE 官方帳號機器人

這是一個為命理師設計的 LINE 官方帳號機器人，能夠自動回覆客戶關於法事、命理和開運物品的訊息，並且可以透過 Google Calendar API 查詢命理師的行程安排。

## 主要功能

1. 自動回覆關於法事、命理和開運物品的訊息
2. 根據 Google Calendar 行程，自動回覆命理師的可用時間
3. 特殊處理（如 4 月命理師在大陸，無法進行法事的情況）
4. 提供簡單的網站首頁

## 技術架構

- Python Flask 後端
- LINE Messaging API
- Google Calendar API
- 部署於 Render

## 安裝與設定

### 前置需求

- Python 3.8+
- LINE 開發者帳號
- Google Cloud 帳號與設定

### 設定步驟

1. 複製專案到本地：

```bash
git clone https://github.com/yourusername/fortune-line-bot.git
cd fortune-line-bot
```

2. 安裝相依套件：

```bash
pip install -r requirements.txt
```

3. 設定環境變數：

編輯 `.env` 檔案並填入：

```
LINE_CHANNEL_ACCESS_TOKEN=你的LINE_CHANNEL_ACCESS_TOKEN
LINE_CHANNEL_SECRET=你的LINE_CHANNEL_SECRET
GOOGLE_CALENDAR_ID=你的GOOGLE_CALENDAR_ID
GOOGLE_CREDENTIALS={"type": "service_account", ...} # 你的Google服務帳號認證JSON
```

4. 啟動本地開發伺服器：

```bash
python app.py
```

## 部署到 Render

1. 在 Render 建立新的 Web Service
2. 連結到你的 GitHub 儲存庫
3. 設定以下內容：
   - **Environment**: Python 3.8 (或更新版本)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
4. 在 Render 環境變數設定中新增 `.env` 檔案中的所有環境變數
5. 部署應用程式

## LINE Bot 設定

1. 在 [LINE Developers Console](https://developers.line.biz/console/) 建立新的 Provider 和 Channel
2. 設定 Webhook URL 為 `https://您的Render域名/callback`
3. 開啟 Webhook
4. 複製 Channel access token 和 Channel secret 到環境變數

## Google Calendar API 設定

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 建立專案
2. 啟用 Google Calendar API
3. 建立服務帳號與金鑰
4. 將服務帳號 JSON 金鑰內容設定到環境變數 `GOOGLE_CREDENTIALS`
5. 在 Google Calendar 分享權限給服務帳號的電子郵件地址

## 使用指南

用戶可以透過以下關鍵字獲取資訊：

- 「命理」：獲取關於命理服務的資訊
- 「法事」：獲取關於法事服務的資訊
- 「開運」：獲取關於開運物品的資訊
- 「查詢 YYYY-MM-DD」：查詢特定日期的可預約狀態

## 授權

MIT

## 作者

您的姓名或組織 
