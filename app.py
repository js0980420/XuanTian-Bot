# app.py
import os
import json
import datetime
from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexButton,
    FlexSeparator,
    MessageAction,
    URIAction,
    PostbackAction,
    DatetimePickerAction
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    PostbackEvent
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz

app = Flask(__name__)

# --- 基本設定 ---
# (與上次相同)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '')
google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 環境變數檢查 ---
# (與上次相同)
if not channel_access_token or not channel_secret:
    print("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
if not calendar_id:
    print("警告：未設定 GOOGLE_CALENDAR_ID 環境變數，無法查詢日曆")
if not google_credentials_json:
    print("警告：未設定 GOOGLE_CREDENTIALS_JSON 環境變數，無法連接 Google Calendar")
# if not teacher_user_id: # 暫時不用老師 ID
#     print("警告：未設定 TEACHER_USER_ID 環境變數，無法發送預約通知給老師")

# 初始化 LINE Bot API
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- Google Calendar 輔助函數 (與之前相同) ---
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

def get_calendar_events_for_date(target_date):
    """獲取指定日期的 Google 日曆事件列表"""
    service = get_google_calendar_service()
    if not service:
        return None # 無法連接服務
    try:
        start_time = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=TW_TIMEZONE)
        end_time = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=TW_TIMEZONE)
        events_result = service.events().list(
            calendarId=calendar_id, timeMin=start_time.isoformat(), timeMax=end_time.isoformat(),
            singleEvents=True, orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        print(f"查詢日曆事件時發生錯誤 ({target_date}): {e}")
        return None # 查詢失敗

# --- 輔助函數：獲取服務說明文字 ---
def get_info_text(topic):
    """根據主題返回說明文字"""
    current_year = datetime.date.today().year
    if topic == '開運物':
        guangzhou_shopping_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n🔹 如有特定需求或想預購，歡迎私訊老師。\n🔹 商品預計於老師回台後 ({current_year}/4/22之後) 陸續整理並寄出，感謝您的耐心等待！"
        return ("【開運物品】\n提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n" + guangzhou_shopping_reminder)
    elif topic == '生基品':
         guangzhou_shengji_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州尋找適合的玉器等生基相關用品。\n🔹 如有興趣或需求，歡迎私訊老師洽詢。\n🔹 相關用品預計於老師回台後 ({current_year}/4/22之後) 整理寄出。"
         return ("【生基用品】\n生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n老師提供相關諮詢與必需品代尋服務。\n\n" + guangzhou_shengji_reminder)
    elif topic == '法事': # 也可用於顯示法事資訊
        guangzhou_ritual_reminder = f'❗️ {current_year}/4/11 至 {current_year}/4/22 老師在廣州，期間無法進行任何法事項目，敬請見諒。'
        return (
            "【法事服務項目】\n旨在透過儀式調和能量，趨吉避凶。\n"
            "主要項目：\n"
            "🔹 冤親債主 (處理官司/考運/健康/小人)\n"
            "🔹 補桃花 (助感情/貴人/客戶)\n"
            "🔹 補財庫 (助財運/事業/防破財)\n"
            "費用：單項 NT$680 / 三項合一 NT$1800\n\n"
            "🔹 祖先相關 (詳情請私訊)\n"
            "費用：NT$1800 / 份\n\n"
            "⚠️ 特別提醒：\n" + guangzhou_ritual_reminder + "\n"
            "❓ 如需預約，請點選下方「預約：法事」按鈕。" # 修改提示
        )
    # 可以為其他服務也加入說明
    # elif topic == '問事/命理':
    #     ...
    else:
        return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"


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
    """處理加好友事件，發送包含按鈕的歡迎訊息"""
    user_id = event.source.user_id
    print(f"User {user_id} added the bot.")

    current_year = datetime.date.today().year
    guangzhou_reminder_text = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停。'

    # --- 建立按鈕 ---
    buttons = []
    # 預約類按鈕
    bookable_services = ["問事/命理", "法事", "收驚", "卜卦"]
    for service in bookable_services:
        postback_data = json.dumps({"action": "select_service", "service": service})
        if len(postback_data) <= 300: # 檢查長度
            buttons.append(FlexButton(
                action=PostbackAction(label=f"預約：{service}", data=postback_data, display_text=f"我想預約：{service}"),
                style='primary', color='#A67B5B', margin='sm', height='sm'
            ))
        else:
            print(f"警告：預約按鈕 Postback data 過長 ({len(postback_data)}): {postback_data}")

    # 資訊類按鈕
    info_topics = ["開運物", "生基品"]
    for topic in info_topics:
        postback_data = json.dumps({"action": "show_info", "topic": topic})
        if len(postback_data) <= 300: # 檢查長度
             buttons.append(FlexButton(
                action=PostbackAction(label=f"了解：{topic}", data=postback_data, display_text=f"我想了解：{topic}"),
                style='secondary', margin='sm', height='sm' # 使用次要樣式
            ))
        else:
             print(f"警告：資訊按鈕 Postback data 過長 ({len(postback_data)}): {postback_data}")

    # --- 建立 Flex Message ---
    bubble = FlexBubble(
        header=FlexBox(layout='vertical', padding_all='lg', contents=[
             FlexText(text='宇宙玄天院 歡迎您！', weight='bold', size='xl', align='center', color='#B28E49'),
             FlexText(text='點擊下方按鈕選擇服務或了解詳情：', wrap=True, size='sm', color='#555555', align='center', margin='md'),
        ]),
        body=FlexBox(
            layout='vertical',
            spacing='sm', # 調整按鈕間距
            contents=buttons # 將按鈕放入 body
        ),
        footer=FlexBox(layout='vertical', contents=[ # 將提醒文字放入 footer
            FlexSeparator(margin='md'),
            FlexText(text=guangzhou_reminder_text, wrap=True, size='xs', color='#E53E3E', margin='md', align='center')
        ])
    )
    welcome_message = FlexMessage(alt_text='歡迎加入宇宙玄天院 - 請選擇服務', contents=bubble)

    # 使用 Push API 發送歡迎訊息
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
    """處理使用者傳送的文字訊息 (主要用於非按鈕觸發的關鍵字)"""
    text = event.message.text.strip().lower()
    reply_message = None
    current_year = datetime.date.today().year

    # --- 處理「預約」關鍵字 (與上次相同，作為備用入口) ---
    if text == '預約':
        service_buttons = []
        bookable_services = ["問事/命理", "法事", "收驚", "卜卦"]
        for service in bookable_services:
            postback_data = json.dumps({"action": "select_service", "service": service})
            if len(postback_data) > 300:
                 print(f"警告：Postback data 過長 ({len(postback_data)}): {postback_data}")
                 continue
            service_buttons.append(
                FlexButton(
                    action=PostbackAction(label=service, data=postback_data, display_text=f"我想預約：{service}"),
                    style='primary', color='#A67B5B', margin='sm'
                )
            )
        bubble = FlexBubble(
            header=FlexBox(layout='vertical', contents=[
                FlexText(text='請選擇您想預約的服務', weight='bold', size='lg', align='center', color='#B28E49')
            ]),
            body=FlexBox(layout='vertical', spacing='md', contents=service_buttons)
        )
        reply_message = FlexMessage(alt_text='請選擇預約服務', contents=bubble)

    # --- 處理其他關鍵字 (法事、問事、開運物等，作為備用資訊查詢) ---
    elif '法事' in text:
        # 直接使用輔助函數獲取文字，並加上預約提示
        info_text = get_info_text('法事')
        reply_message = TextMessage(text=info_text)
    elif '問事' in text or '命理' in text:
        guangzhou_consult_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可透過線上方式進行問事或命理諮詢，歡迎預約。\n\n"
        reply_text = ("【問事/命理諮詢】\n服務內容包含八字命盤分析、流年運勢、事業財運、感情姻緣等。\n\n" + guangzhou_consult_reminder + "如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。")
        reply_message = TextMessage(text=reply_text)
    elif '開運物' in text:
        reply_message = TextMessage(text=get_info_text('開運物'))
    elif '生基品' in text:
        reply_message = TextMessage(text=get_info_text('生基品'))
    elif '收驚' in text:
        guangzhou_shoujing_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可提供遠距離線上收驚服務，效果一樣。\n\n"
        reply_text = ("【收驚服務】\n適用於受到驚嚇、心神不寧、睡眠品質不佳等狀況。\n\n" + guangzhou_shoujing_reminder + "如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。")
        reply_message = TextMessage(text=reply_text)
    elif '卜卦' in text:
        guangzhou_bugua_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可透過線上方式進行卜卦。\n\n"
        reply_text = ("【卜卦問事】\n針對特定問題提供指引，例如決策、尋物、運勢吉凶等。\n\n" + guangzhou_bugua_reminder + "如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。")
        reply_message = TextMessage(text=reply_text)

    # --- 預設回覆 (如果不是已知關鍵字) ---
    else:
        # 避免在用戶點擊按鈕後又觸發預設回覆
        if text != '預約' and not text.startswith('我想'):
             default_guangzhou_reminder = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停。'
             default_bubble = FlexBubble(
                body=FlexBox(
                    layout='vertical', spacing='md',
                    contents=[
                        FlexText(text='宇宙玄天院 小幫手', weight='bold', size='lg', align='center', color='#B28E49'),
                        FlexText(text='您好！請問需要什麼服務？', wrap=True, size='md', margin='md'),
                        FlexText(text='您可以點擊歡迎訊息中的按鈕，或輸入以下關鍵字：', wrap=True, size='sm', color='#555555', margin='lg'),
                        FlexText(text='🔹 預約'),
                        FlexText(text='🔹 問事 / 命理'),
                        FlexText(text='🔹 法事'),
                        FlexText(text='🔹 開運物'),
                        FlexText(text='🔹 生基品'),
                        FlexText(text='🔹 收驚'),
                        FlexText(text='🔹 卜卦'),
                        FlexSeparator(margin='lg'),
                        FlexText(text=default_guangzhou_reminder, wrap=True, size='xs', color='#E53E3E', margin='md')
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


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (來自 Flex Message 按鈕和 Datetime Picker)"""
    reply_message = None
    user_id = event.source.user_id
    postback_data_str = event.postback.data
    print(f"收到 Postback: User={user_id}, Data='{postback_data_str}'")

    try:
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')

        # --- 處理：選擇服務後，跳出日期時間選擇器 ---
        if action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                print(f"用戶 {user_id} 選擇了服務: {selected_service}")
                picker_data = json.dumps({"action": "select_datetime", "service": selected_service})
                if len(picker_data) > 300:
                     print(f"警告：Datetime Picker data 過長 ({len(picker_data)}): {picker_data}")
                     reply_message = TextMessage(text="系統錯誤：選項資料過長，請稍後再試。")
                else:
                    min_datetime_str = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT00:00')
                    bubble = FlexBubble(
                        body=FlexBox(layout='vertical', contents=[
                            FlexText(text=f'您選擇了：{selected_service}', weight='bold', align='center', margin='md'),
                            FlexText(text='請選擇您希望預約的日期與時間', align='center', margin='md', size='sm'),
                            FlexButton(
                                action=DatetimePickerAction(
                                    label='📅 選擇日期時間',
                                    data=picker_data,
                                    mode='datetime',
                                    min=min_datetime_str
                                ),
                                style='primary', color='#A67B5B', margin='lg'
                            )
                        ])
                    )
                    reply_message = FlexMessage(alt_text='請選擇預約日期時間', contents=bubble)
            else:
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的服務。")

        # --- 處理：選擇日期時間後，進行預約檢查與通知 ---
        elif action == 'select_datetime':
            selected_service = postback_data.get('service')
            selected_datetime_str = event.postback.params.get('datetime')

            if selected_service and selected_datetime_str:
                print(f"用戶 {user_id} 預約服務 '{selected_service}' 時間 '{selected_datetime_str}'")
                try:
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    selected_date = selected_dt.date()
                    formatted_dt = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')

                    proceed_booking = True
                    if selected_service == '法事':
                        print(f"檢查法事可用性：日期 {selected_date}")
                        events = get_calendar_events_for_date(selected_date)
                        if events is None:
                            print(f"錯誤：無法查詢 {selected_date} 的日曆事件，法事預約失敗")
                            reply_message = TextMessage(text=f"抱歉，目前無法確認老師 {selected_date.strftime('%Y-%m-%d')} 的行程，請稍後再試或直接私訊老師。")
                            proceed_booking = False
                        elif len(events) > 0:
                            print(f"法事預約衝突：{selected_date} 已有行程 ({len(events)} 個事件)")
                            reply_message = TextMessage(text=f"抱歉，老師在 {selected_date.strftime('%Y-%m-%d')} 已有行程安排，暫無法進行法事，請選擇其他日期，謝謝。")
                            proceed_booking = False

                    if proceed_booking:
                        notification_text = (
                            f"【預約請求記錄】\n"
                            f"--------------------\n"
                            f"用戶ID: {user_id}\n"
                            f"服務項目: {selected_service}\n"
                            f"預約時間: {formatted_dt}\n"
                            f"--------------------\n"
                            f"（此訊息已記錄在後台日誌，請手動處理）"
                        )
                        print(notification_text)
                        print("預約請求已記錄到日誌。")
                        reply_text_to_user = (
                            f"收到您的預約請求：\n"
                            f"服務：{selected_service}\n"
                            f"時間：{formatted_dt}\n\n"
                            f"此預約已記錄，將由老師為您處理後續確認事宜，感謝您的耐心等候！"
                        )
                        reply_message = TextMessage(text=reply_text_to_user)

                except ValueError:
                    print(f"錯誤：解析日期時間失敗: {selected_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                except Exception as e:
                    print(f"處理 select_datetime 時發生未知錯誤: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
            else:
                reply_message = TextMessage(text="發生錯誤，缺少預約服務或時間資訊。")

        # --- 新增：處理 show_info Action ---
        elif action == 'show_info':
            topic = postback_data.get('topic')
            if topic:
                 print(f"用戶 {user_id} 查詢資訊: {topic}")
                 info_text = get_info_text(topic) # 使用輔助函數獲取文字
                 reply_message = TextMessage(text=info_text)
            else:
                 reply_message = TextMessage(text="抱歉，無法識別您想了解的資訊。")

        else:
            print(f"未知的 Postback Action: {action}")

    except json.JSONDecodeError:
        print(f"錯誤：無法解析 Postback data: {postback_data_str}")
        reply_message = TextMessage(text="系統無法處理您的請求，請稍後再試。")
    except Exception as e:
        print(f"處理 Postback 時發生未知錯誤: {e}")
        reply_message = TextMessage(text="系統發生錯誤，請稍後再試。")

    # --- 發送 Postback 的回覆 ---
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                print(f"準備 Push 回覆給 {user_id}")
                line_bot_api.push_message(PushMessageRequest(
                    to=user_id,
                    messages=[reply_message]
                ))
            except Exception as e:
                print(f"回覆 Postback 訊息失敗: {e}")


# --- 主程式入口 ---
if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
