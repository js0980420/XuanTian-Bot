# app.py
import os
import json
import datetime
from flask import Flask, request, abort # render_template removed as it wasn't used by bot logic
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest, # Added for FollowEvent
    TextMessage,
    FlexMessage, # Added for rich messages
    FlexBubble,
    FlexBox,
    FlexText,
    FlexButton,
    FlexSeparator, # Added for layout
    MessageAction,
    URIAction # Added for potential future links
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent # Added for new friend event
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz

app = Flask(__name__)

# --- 基本設定 ---
# LINE Bot API 設定
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
# Google Calendar API 設定
calendar_id = os.getenv('YOUR_CALENDAR_ID', '') # Use the same env var name as in the guide
google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '') # Env var to hold the JSON content directly

if not channel_access_token or not channel_secret:
    print("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
    # Consider exiting or raising an error in a real application
if not calendar_id:
    print("警告：未設定 YOUR_CALENDAR_ID 環境變數，無法查詢日曆")
if not google_credentials_json:
    print("警告：未設定 GOOGLE_CREDENTIALS_JSON 環境變數，無法連接 Google Calendar")

# 初始化 LINE Bot API
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- Google Calendar 輔助函數 ---

def get_google_calendar_service():
    """初始化並返回 Google Calendar API 的 service 物件"""
    if not google_credentials_json:
        print("錯誤：缺少 Google 憑證 JSON 環境變數")
        return None
    try:
        credentials_info = json.loads(google_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except json.JSONDecodeError:
        print("錯誤：Google 憑證 JSON 格式錯誤")
        return None
    except Exception as e:
        print(f"連接 Google Calendar API 時發生錯誤: {e}")
        return None

def check_ritual_availability_on_date(target_date):
    """
    檢查指定日期是否因特殊行程 (如廣州行) 而無法進行 '法事'。
    返回 True 表示 '可以' 進行法事，False 表示 '不可以'。
    """
    # 廣州行程期間 (4/11 - 4/22) 無法進行法事
    guangzhou_start = datetime.date(target_date.year, 4, 11)
    guangzhou_end = datetime.date(target_date.year, 4, 22)
    if guangzhou_start <= target_date <= guangzhou_end:
        return False # 在廣州期間，不能做法事

    # TODO: 未來可以加入從 Google Calendar 讀取特定 "全天忙碌" 或 "無法事" 事件的邏輯
    # service = get_google_calendar_service()
    # if service:
    #     # 查詢是否有標記為 '無法事' 的全天事件
    #     pass

    return True # 預設可以做法事 (如果不在已知衝突日期內)

def get_calendar_events_for_date(target_date):
    """獲取指定日期的 Google 日曆事件列表"""
    service = get_google_calendar_service()
    if not service:
        return None # 無法連接服務

    try:
        start_time = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=TW_TIMEZONE)
        end_time = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=TW_TIMEZONE)

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        print(f"查詢日曆事件時發生錯誤 ({target_date}): {e}")
        return None # 查詢失敗

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    """處理來自 LINE 的 Webhook 請求"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("簽名驗證失敗")
        abort(400)
    except Exception as e:
        print(f"處理訊息時發生錯誤: {e}")
        abort(500)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """處理加好友事件，發送歡迎訊息"""
    user_id = event.source.user_id
    print(f"User {user_id} added the bot.")

    # 建立歡迎訊息 (Flex Message)
    bubble = FlexBubble(
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='宇宙玄天院 歡迎您！', weight='bold', size='xl', align='center', color='#B28E49'),
                FlexText(text='感謝您加入好友！我是您的命理小幫手。', wrap=True, size='sm', color='#555555'),
                FlexSeparator(margin='lg'),
                FlexText(text='您可以透過輸入關鍵字查詢服務：', wrap=True, size='md', margin='lg'),
                FlexText(text='🔹 問事 / 命理', size='md', margin='sm'),
                FlexText(text='🔹 法事', size='md', margin='sm'),
                FlexText(text='🔹 開運物', size='md', margin='sm'),
                FlexText(text='🔹 生基品', size='md', margin='sm'),
                FlexText(text='🔹 收驚', size='md', margin='sm'),
                FlexText(text='🔹 卜卦', size='md', margin='sm'),
                FlexText(text='🔹 查詢 YYYY-MM-DD (查詢日期行程)', size='md', margin='sm'),
                FlexSeparator(margin='lg'),
                FlexText(text='匯款資訊', weight='bold', size='lg', margin='md', color='#B28E49'),
                FlexText(text='🌟 銀行：822 中國信託', size='md'),
                FlexText(text='🌟 帳號：510540490990', size='md'),
                FlexSeparator(margin='lg'),
                 FlexText(text='🗓️ 特別提醒：4/11 至 4/22 老師在廣州，部分服務（如法事）暫停，詳情請輸入關鍵字查詢。', wrap=True, size='xs', color='#E53E3E', margin='md')
            ]
        )
    )
    welcome_message = FlexMessage(alt_text='歡迎加入宇宙玄天院', contents=bubble)

    # 使用 Push API 發送訊息
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.push_message(PushMessageRequest(
                to=user_id,
                messages=[welcome_message]
            ))
        except Exception as e:
            print(f"發送歡迎訊息失敗: {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    text = event.message.text.strip().lower() # 轉換為小寫並去除頭尾空白，方便比對
    reply_message = None # 預設不回覆

    # 獲取今天的日期 (台灣時間)
    today = datetime.datetime.now(TW_TIMEZONE).date()

    # --- 處理日期查詢 ---
    if text.startswith('查詢') and len(text.split()) == 2:
        try:
            date_str = text.split()[1]
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()

            # 檢查是否在廣州且影響法事
            can_do_ritual = check_ritual_availability_on_date(target_date)

            events = get_calendar_events_for_date(target_date)

            if events is None:
                reply_text = "抱歉，目前無法連接 Google 日曆查詢行程，請稍後再試。"
            elif not events:
                reply_text = f"✅ {target_date.strftime('%Y-%m-%d')} 老師尚有空檔。"
                if not can_do_ritual:
                    reply_text += "\n⚠️ 但請注意：此日期無法進行『法事』項目。"
            else:
                busy_times = []
                for item in events:
                    summary = item.get('summary', '忙碌')
                    start_info = item['start'].get('dateTime', item['start'].get('date'))
                    end_info = item['end'].get('dateTime', item['end'].get('date'))
                    # 簡單格式化時間
                    try:
                        start_dt = datetime.datetime.fromisoformat(start_info).astimezone(TW_TIMEZONE)
                        time_str = start_dt.strftime('%H:%M')
                    except: # 如果是全天事件或格式錯誤
                        time_str = "全天"
                    busy_times.append(f"{time_str} ({summary})")

                reply_text = f"🗓️ {target_date.strftime('%Y-%m-%d')} 老師行程：\n" + "\n".join(f"- {t}" for t in busy_times)
                if not can_do_ritual:
                    reply_text += "\n\n⚠️ 請注意：此日期無法進行『法事』項目。"

            reply_message = TextMessage(text=reply_text)

        except (ValueError, IndexError):
            reply_message = TextMessage(text="日期格式錯誤，請輸入「查詢 YYYY-MM-DD」格式，例如：「查詢 2025-04-18」")
        except Exception as e:
            print(f"處理查詢時發生錯誤: {e}")
            reply_message = TextMessage(text="查詢時發生內部錯誤，請稍後再試。")

    # --- 處理關鍵字 ---
    elif '法事' in text:
        # 建立法事說明的 Flex Message
        ritual_bubble = FlexBubble(
            direction='ltr',
            header=FlexBox(
                layout='vertical',
                contents=[
                    FlexText(text='法事服務項目', weight='bold', size='xl', align='center', color='#B28E49')
                ]
            ),
            body=FlexBox(
                layout='vertical',
                spacing='md',
                contents=[
                    FlexText(text='旨在透過儀式調和能量，趨吉避凶。', size='sm', wrap=True, color='#555555'),
                    FlexSeparator(margin='lg'),
                    FlexText(text='主要項目', weight='bold', size='lg', margin='md'),
                    FlexText(text='🔹 冤親債主 (處理官司/考運/健康/小人)', wrap=True),
                    FlexText(text='🔹 補桃花 (助感情/貴人/客戶)', wrap=True),
                    FlexText(text='🔹 補財庫 (助財運/事業/防破財)', wrap=True),
                    FlexText(text='費用：單項 NT$680 / 三項合一 NT$1800', margin='sm', size='sm', weight='bold'),
                    FlexSeparator(margin='md'),
                    FlexText(text='🔹 祖先相關 (詳情請私訊)', wrap=True),
                    FlexText(text='費用：NT$1800 / 份', margin='sm', size='sm', weight='bold'),
                    FlexSeparator(margin='lg'),
                    FlexText(text='匯款資訊', weight='bold', size='lg', color='#B28E49'),
                    FlexText(text='🌟 銀行：822 中國信託'),
                    FlexText(text='🌟 帳號：510540490990'),
                    FlexSeparator(margin='lg'),
                    FlexText(text='⚠️ 特別提醒', weight='bold', color='#E53E3E'),
                    FlexText(text='❗️ 4/11 至 4/22 老師在廣州，期間無法進行任何法事項目，敬請見諒。', wrap=True, size='sm', color='#E53E3E'),
                    FlexText(text='❓ 如有特殊需求，請直接私訊老師。', size='xs', margin='md', color='#777777')
                ]
            ),
            footer=FlexBox(
                layout='vertical',
                spacing='sm',
                contents=[
                    FlexButton(
                        action=MessageAction(label='查詢可預約日期', text='查詢 '), # 提示用戶輸入日期
                        style='primary',
                        color='#B28E49',
                        height='sm'
                    )
                ]
            )
        )
        reply_message = FlexMessage(alt_text='法事服務項目說明', contents=ritual_bubble)

    elif '問事' in text or '命理' in text:
        reply_text = (
            "【問事/命理諮詢】\n"
            "服務內容包含八字命盤分析、流年運勢、事業財運、感情姻緣等。\n\n"
            "🗓️ 老師行程：\n"
            "🔹 4/11 - 4/22 期間老師在廣州，但仍可透過線上方式進行問事或命理諮詢，歡迎預約。\n\n"
            "請使用「查詢 YYYY-MM-DD」格式查詢老師是否有空，或直接私訊預約。"
        )
        reply_message = TextMessage(text=reply_text)

    elif '開運物' in text:
        reply_text = (
            "【開運物品】\n"
            "提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n"
            "🛍️ 最新消息：\n"
            "🔹 4/11 - 4/22 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n"
            "🔹 如有特定需求或想預購，歡迎私訊老師。\n"
            "🔹 商品預計於老師回台後 (4/22之後) 陸續整理並寄出，感謝您的耐心等待！"
        )
        reply_message = TextMessage(text=reply_text)

    elif '生基品' in text:
         reply_text = (
            "【生基用品】\n"
            "生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n"
            "老師提供相關諮詢與必需品代尋服務。\n\n"
            "🛍️ 最新消息：\n"
            "🔹 4/11 - 4/22 老師親赴廣州尋找適合的玉器等生基相關用品。\n"
            "🔹 如有興趣或需求，歡迎私訊老師洽詢。\n"
            "🔹 相關用品預計於老師回台後 (4/22之後) 整理寄出。"
        )
         reply_message = TextMessage(text=reply_text)

    elif '收驚' in text:
        reply_text = (
            "【收驚服務】\n"
            "適用於受到驚嚇、心神不寧、睡眠品質不佳等狀況。\n\n"
            "🗓️ 老師行程：\n"
            "🔹 4/11 - 4/22 期間老師在廣州，但仍可提供遠距離線上收驚服務，效果一樣，歡迎私訊預約。"
        )
        reply_message = TextMessage(text=reply_text)

    elif '卜卦' in text:
        reply_text = (
            "【卜卦問事】\n"
            "針對特定問題提供指引，例如決策、尋物、運勢吉凶等。\n\n"
            "🗓️ 老師行程：\n"
            "🔹 4/11 - 4/22 期間老師在廣州，但仍可透過線上方式進行卜卦，歡迎私訊提問。"
        )
        reply_message = TextMessage(text=reply_text)

    # --- 預設回覆 ---
    else:
        # 如果不是查詢格式，且不是已知關鍵字，發送預設提示
        if not text.startswith('查詢'):
             default_bubble = FlexBubble(
                body=FlexBox(
                    layout='vertical',
                    spacing='md',
                    contents=[
                        FlexText(text='宇宙玄天院 小幫手', weight='bold', size='lg', align='center', color='#B28E49'),
                        FlexText(text='您好！請問需要什麼服務？', wrap=True, size='md', margin='md'),
                        FlexText(text='請輸入以下關鍵字查詢：', wrap=True, size='sm', color='#555555', margin='lg'),
                        FlexText(text='🔹 問事 / 命理'),
                        FlexText(text='🔹 法事'),
                        FlexText(text='🔹 開運物'),
                        FlexText(text='🔹 生基品'),
                        FlexText(text='🔹 收驚'),
                        FlexText(text='🔹 卜卦'),
                        FlexText(text='🔹 查詢 YYYY-MM-DD'),
                        FlexSeparator(margin='lg'),
                        FlexText(text='🗓️ 特別提醒：4/11 至 4/22 老師在廣州，部分服務（如法事）暫停。', wrap=True, size='xs', color='#E53E3E', margin='md')
                    ]
                )
            )
             reply_message = FlexMessage(alt_text='歡迎使用服務', contents=default_bubble)


    # --- 發送回覆 ---
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[reply_message]
                    )
                )
            except Exception as e:
                print(f"回覆訊息失敗: {e}")

# --- 主程式入口 ---
if __name__ == "__main__":
    # 從環境變數取得 Port，預設為 8080 (Render 常用的預設值)
    port = int(os.getenv('PORT', 8080))
    # 啟動 Flask 應用程式，監聽所有 IP 地址
    # debug=False 在生產環境中更安全
    app.run(host='0.0.0.0', port=port, debug=False)
```

**主要變更說明：**

1.  **環境變數調整**：改用 `YOUR_CALENDAR_ID` 和 `GOOGLE_CREDENTIALS_JSON` 作為環境變數名稱，以符合 Render 設定習慣（`GOOGLE_CREDENTIALS_JSON` 預期直接包含 JSON 內容）。
2.  **新增 `FollowEvent` 處理**：當使用者加入好友時，會發送包含服務列表和匯款資訊的 Flex Message 歡迎訊息。
3.  **日期可用性檢查 (`check_ritual_availability_on_date`)**：新增此函數，專門檢查特定日期（目前硬編碼為 4/11-4/22）是否因廣州行程而無法進行「法事」。
4.  **查詢邏輯更新**：
    * `查詢` 指令現在會調用 `get_calendar_events_for_date` 獲取當日行程。
    * 同時會調用 `check_ritual_availability_on_date` 檢查該日是否能做法事，並在回覆中加入提醒。
    * 改善了日曆事件顯示格式。
5.  **關鍵字回覆更新**：
    * **法事**：改用 Flex Message 顯示詳細項目、費用、說明、匯款資訊和廣州行程提醒。
    * **問事/命理、開運物、生基品、收驚、卜卦**：更新了回覆內容，加入了 4/11-4/22 廣州行程的相關說明（哪些服務可用/不可用，商品採購等）。
    * **預設回覆**：也改用 Flex Message，提供更清晰的引導。
6.  **Flex Message 使用**：廣泛使用 Flex Message 來提供更豐富、更美觀的訊息格式。
7.  **程式碼結構與註解**：調整了部分函數和註解，使其更清晰。
8.  **啟動設定**：`debug=False` 更適合生產環境；Port 預設改為 8080。

**部署前請注意：**

1.  **環境變數**：確保在 Render 上設定了 `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `YOUR_CALENDAR_ID`, 以及 `GOOGLE_CREDENTIALS_JSON`（這個變數的值應該是您 Google Service Account 金鑰 JSON 檔案的**完整內容**，而不是檔案路徑）。
2.  **`requirements.txt`**：確認 `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`, `pytz`, `line-bot-sdk`, `Flask`, `gunicorn` 都已包含在內。
3.  **測試**：部署後請務必徹底測試所有關鍵字和查詢功能，特別是日期相關的邏輯和廣州行程的
