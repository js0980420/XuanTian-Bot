# app.py
import os
import json
import datetime
import re # Import regular expressions for validation
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
    DatetimePickerAction,
    QuickReply,
    QuickReplyButton
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
if not teacher_user_id:
    print("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

# 初始化 LINE Bot API
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版，僅用於暫存生日時間) ---
# !!! 警告：此簡易狀態管理在 Render 等環境下可能因服務重啟或多實例而遺失狀態 !!!
user_states = {} # {user_id: {"state": "awaiting_topic_after_picker", "data": {"birth_info_str": "..."}}}

# --- Google Calendar 輔助函數 (與之前相同) ---
def get_google_calendar_service():
    # ... (程式碼同上) ...
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
    # ... (程式碼同上) ...
    service = get_google_calendar_service()
    if not service:
        return None
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
        return None

# --- 輔助函數：獲取服務說明文字 (與之前相同) ---
def get_info_text(topic):
    # ... (程式碼同上) ...
    current_year = datetime.date.today().year
    if topic == '開運物':
        guangzhou_shopping_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n🔹 如有特定需求或想預購，歡迎私訊老師。\n🔹 商品預計於老師回台後 ({current_year}/4/22之後) 陸續整理並寄出，感謝您的耐心等待！"
        return ("【開運物品】\n提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n" + guangzhou_shopping_reminder)
    elif topic == '生基品':
         guangzhou_shengji_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州尋找適合的玉器等生基相關用品。\n🔹 如有興趣或需求，歡迎私訊老師洽詢。\n🔹 相關用品預計於老師回台後 ({current_year}/4/22之後) 整理寄出。"
         return ("【生基用品】\n生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n老師提供相關諮詢與必需品代尋服務。\n\n" + guangzhou_shengji_reminder)
    elif topic == '法事':
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
            "❓ 如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。"
        )
    else:
        return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
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
    # ... (程式碼同上, 發送按鈕式歡迎訊息) ...
    user_id = event.source.user_id
    print(f"User {user_id} added the bot.")
    current_year = datetime.date.today().year
    guangzhou_reminder_text = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停。'
    buttons = []
    bookable_services = ["問事/命理", "法事", "收驚", "卜卦"]
    for service in bookable_services:
        postback_data = json.dumps({"action": "select_service", "service": service})
        if len(postback_data) <= 300:
            buttons.append(FlexButton(
                action=PostbackAction(label=f"預約：{service}", data=postback_data, display_text=f"我想預約：{service}"),
                style='primary', color='#A67B5B', margin='sm', height='sm'
            ))
        else:
            print(f"警告：預約按鈕 Postback data 過長 ({len(postback_data)}): {postback_data}")
    info_topics = ["開運物", "生基品"]
    for topic in info_topics:
        postback_data = json.dumps({"action": "show_info", "topic": topic})
        if len(postback_data) <= 300:
             buttons.append(FlexButton(
                action=PostbackAction(label=f"了解：{topic}", data=postback_data, display_text=f"我想了解：{topic}"),
                style='secondary', margin='sm', height='sm'
            ))
        else:
             print(f"警告：資訊按鈕 Postback data 過長 ({len(postback_data)}): {postback_data}")
    bubble = FlexBubble(
        header=FlexBox(layout='vertical', padding_all='lg', contents=[
             FlexText(text='宇宙玄天院 歡迎您！', weight='bold', size='xl', align='center', color='#B28E49'),
             FlexText(text='點擊下方按鈕選擇服務或了解詳情：', wrap=True, size='sm', color='#555555', align='center', margin='md'),
        ]),
        body=FlexBox(layout='vertical', spacing='sm', contents=buttons),
        footer=FlexBox(layout='vertical', contents=[
            FlexSeparator(margin='md'),
            FlexText(text=guangzhou_reminder_text, wrap=True, size='xs', color='#E53E3E', margin='md', align='center')
        ])
    )
    welcome_message = FlexMessage(alt_text='歡迎加入宇宙玄天院 - 請選擇服務', contents=bubble)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[welcome_message]))
        except Exception as e:
            print(f"發送歡迎訊息失敗: {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    text_lower = text.lower()
    reply_message = None
    current_year = datetime.date.today().year
    now = datetime.datetime.now(TW_TIMEZONE)

    # --- 檢查是否在命理問事流程中 (現在只處理等待主題的狀態) ---
    if user_id in user_states:
        state_info = user_states[user_id]
        current_state = state_info["state"]

        if text_lower == '取消':
            if user_id in user_states: del user_states[user_id] # 清除狀態
            reply_message = TextMessage(text="好的，已取消本次命理資訊輸入。")

        elif current_state == "awaiting_topic_after_picker":
            topic = text # 假設用戶會點擊 Quick Reply 或輸入文字
            birth_info_str = state_info["data"].get("birth_info_str", "未提供") # 從狀態取出之前存的生日時間字串

            # 格式化生日時間 (可能包含 T)
            try:
                dt_obj = datetime.datetime.fromisoformat(birth_info_str)
                formatted_birth_info = dt_obj.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')
            except ValueError:
                 formatted_birth_info = birth_info_str # 如果格式不對，直接顯示原始字串

            # --- 記錄資訊並通知老師 (或印出日誌) ---
            notification_base_text = (
                f"【命理問事請求】\n"
                f"--------------------\n"
                f"用戶ID: {user_id}\n"
                f"提供生日: {formatted_birth_info}\n" # 使用格式化後的時間
                f"問題主題: {topic}\n"
                f"--------------------"
            )
            print(f"準備處理命理問事請求: {notification_base_text}")

            if teacher_user_id:
                try:
                    push_notification_text = notification_base_text + "\n請老師抽空親自回覆"
                    with ApiClient(configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.push_message(PushMessageRequest(
                            to=teacher_user_id, messages=[TextMessage(text=push_notification_text)]
                        ))
                    print("命理問事通知已發送給老師。")
                except Exception as e:
                    print(f"錯誤：發送命理問事通知給老師失敗: {e}")
                    print("備份通知到日誌：")
                    print(notification_base_text + "\n（發送失敗，請查看日誌）")
            else:
                print("警告：未設定老師的 User ID，命理問事通知僅記錄在日誌中。")
                print(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

            reply_message = TextMessage(text=f"收到您的資訊！\n生日時辰：{formatted_birth_info}\n問題主題：{topic}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！")
            if user_id in user_states: del user_states[user_id] # 清除狀態
        else:
             # 如果狀態不是等待主題，可能是之前的狀態未清除或異常，提示用戶取消
             reply_message = TextMessage(text="您目前似乎在進行某個流程，若要重新開始，請先輸入「取消」。")


    # --- 如果不在對話流程中，處理一般關鍵字 ---
    else:
        # --- 觸發命理問事流程 ---
        if '命理' in text_lower or '問事' in text_lower:
            print(f"用戶 {user_id} 觸發命理問事流程")
            # 準備 DateTime Picker
            picker_data = json.dumps({"action": "collect_birth_info"})
            if len(picker_data) > 300:
                 print(f"警告：命理問事 Datetime Picker data 過長 ({len(picker_data)}): {picker_data}")
                 reply_message = TextMessage(text="系統錯誤，無法啟動生日輸入，請稍後再試。")
            else:
                # 設定選擇範圍，例如 1920 年至今
                min_date = "1920-01-01T00:00"
                max_date = now.strftime('%Y-%m-%dT%H:%M')

                bubble = FlexBubble(
                    body=FlexBox(layout='vertical', spacing='md', contents=[
                        FlexText(text='進行命理分析需要您的出生年月日時。', wrap=True, size='md'),
                        FlexText(text='若不確定準確時辰，可先選擇大概時間（如中午12點），稍後與老師確認。', wrap=True, size='sm', color='#666666', margin='sm'),
                        FlexButton(
                            action=DatetimePickerAction(
                                label='📅 點此選擇生日時辰',
                                data=picker_data,
                                mode='datetime',
                                min=min_date, # 限制最早日期
                                max=max_date  # 限制最晚日期 (今天)
                            ),
                            style='primary', color='#A67B5B', margin='lg'
                        )
                    ])
                )
                reply_message = FlexMessage(alt_text='請選擇您的出生年月日時', contents=bubble)

        # --- 處理「預約」關鍵字 ---
        elif text_lower == '預約':
            # (預約流程的程式碼與上次相同)
            service_buttons = []
            bookable_services = ["問事/命理", "法事", "收驚", "卜卦"]
            for service in bookable_services:
                postback_data = json.dumps({"action": "select_service", "service": service})
                if len(postback_data) <= 300:
                    service_buttons.append(
                        FlexButton(
                            action=PostbackAction(label=f"預約：{service}", data=postback_data, display_text=f"我想預約：{service}"),
                            style='primary', color='#A67B5B', margin='sm'
                        )
                    )
                else:
                    print(f"警告：Postback data 過長 ({len(postback_data)}): {postback_data}")
            bubble = FlexBubble(
                header=FlexBox(layout='vertical', contents=[
                    FlexText(text='請選擇您想預約的服務', weight='bold', size='lg', align='center', color='#B28E49')
                ]),
                body=FlexBox(layout='vertical', spacing='md', contents=service_buttons)
            )
            reply_message = FlexMessage(alt_text='請選擇預約服務', contents=bubble)

        # --- 處理其他資訊關鍵字 ---
        elif '法事' in text_lower:
            info_text = get_info_text('法事')
            reply_message = TextMessage(text=info_text)
        elif '開運物' in text_lower:
            reply_message = TextMessage(text=get_info_text('開運物'))
        elif '生基品' in text_lower:
            reply_message = TextMessage(text=get_info_text('生基品'))
        elif '收驚' in text_lower:
            guangzhou_shoujing_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可提供遠距離線上收驚服務，效果一樣。\n\n"
            reply_text = ("【收驚服務】\n適用於受到驚嚇、心神不寧、睡眠品質不佳等狀況。\n\n" + guangzhou_shoujing_reminder + "如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。")
            reply_message = TextMessage(text=reply_text)
        elif '卜卦' in text_lower:
            guangzhou_bugua_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可透過線上方式進行卜卦。\n\n"
            reply_text = ("【卜卦問事】\n針對特定問題提供指引，例如決策、尋物、運勢吉凶等。\n\n" + guangzhou_bugua_reminder + "如需預約，請點選歡迎訊息中的按鈕或輸入「預約」。")
            reply_message = TextMessage(text=reply_text)

        # --- 預設回覆 ---
        else:
            default_guangzhou_reminder = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停。'
            default_bubble = FlexBubble(
                body=FlexBox(
                    layout='vertical', spacing='md',
                    contents=[
                        FlexText(text='宇宙玄天院 小幫手', weight='bold', size='lg', align='center', color='#B28E49'),
                        FlexText(text='您好！請問需要什麼服務？', wrap=True, size='md', margin='md'),
                        FlexText(text='您可以點擊歡迎訊息中的按鈕，或輸入以下關鍵字：', wrap=True, size='sm', color='#555555', margin='lg'),
                        FlexText(text='🔹 預約'), FlexText(text='🔹 問事 / 命理'), FlexText(text='🔹 法事'),
                        FlexText(text='🔹 開運物'), FlexText(text='🔹 生基品'), FlexText(text='🔹 收驚'), FlexText(text='🔹 卜卦'),
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
                # 處理 QuickReply 的發送
                if isinstance(reply_message, TextMessage) and hasattr(reply_message, 'quick_reply') and reply_message.quick_reply:
                     line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[reply_message]
                        )
                    )
                else:
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
    """處理 Postback 事件 (預約流程 + 生日收集)"""
    reply_message = None
    user_id = event.source.user_id
    postback_data_str = event.postback.data
    print(f"收到 Postback: User={user_id}, Data='{postback_data_str}'")

    try:
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')

        # --- 處理：選擇服務 (預約流程) ---
        if action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                print(f"用戶 {user_id} 選擇了預約服務: {selected_service}")
                picker_data = json.dumps({"action": "select_datetime", "service": selected_service}) # 預約用的日期選擇
                if len(picker_data) > 300:
                     print(f"警告：預約 Datetime Picker data 過長 ({len(picker_data)}): {picker_data}")
                     reply_message = TextMessage(text="系統錯誤：選項資料過長，請稍後再試。")
                else:
                    min_datetime_str = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT00:00')
                    bubble = FlexBubble(
                        body=FlexBox(layout='vertical', contents=[
                            FlexText(text=f'您選擇了預約：{selected_service}', weight='bold', align='center', margin='md'),
                            FlexText(text='請選擇您希望預約的日期與時間', align='center', margin='md', size='sm'),
                            FlexButton(
                                action=DatetimePickerAction(
                                    label='📅 選擇日期時間', data=picker_data, mode='datetime', min=min_datetime_str
                                ),
                                style='primary', color='#A67B5B', margin='lg'
                            )
                        ])
                    )
                    reply_message = FlexMessage(alt_text='請選擇預約日期時間', contents=bubble)
            else:
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的服務。")

        # --- 處理：選擇預約日期時間後 ---
        elif action == 'select_datetime':
            selected_service = postback_data.get('service')
            selected_datetime_str = event.postback.params.get('datetime')
            if selected_service and selected_datetime_str:
                # (預約的後續處理、檢查、通知 - 與上次相同)
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
                        notification_base_text = (f"【預約請求】\n--------------------\n用戶ID: {user_id}\n服務項目: {selected_service}\n預約時間: {formatted_dt}\n--------------------")
                        print(f"準備處理預約請求: {notification_base_text}")
                        if teacher_user_id:
                            try:
                                push_notification_text = notification_base_text + "\n請老師盡快確認並回覆客戶"
                                with ApiClient(configuration) as api_client:
                                    line_bot_api = MessagingApi(api_client)
                                    line_bot_api.push_message(PushMessageRequest(to=teacher_user_id, messages=[TextMessage(text=push_notification_text)]))
                                print("預約通知已發送給老師。")
                            except Exception as e:
                                print(f"錯誤：發送預約通知給老師失敗: {e}")
                                print("備份通知到日誌：")
                                print(notification_base_text + "\n（發送失敗，請查看日誌）")
                        else:
                            print("警告：未設定老師的 User ID，預約通知僅記錄在日誌中。")
                            print(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
                        reply_text_to_user = (f"收到您的預約請求：\n服務：{selected_service}\n時間：{formatted_dt}\n\n此預約請求已發送給老師，將由老師為您處理後續確認事宜，感謝您的耐心等候！")
                        reply_message = TextMessage(text=reply_text_to_user)
                except ValueError:
                    print(f"錯誤：解析日期時間失敗: {selected_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                except Exception as e:
                    print(f"處理 select_datetime 時發生未知錯誤: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
            else:
                reply_message = TextMessage(text="發生錯誤，缺少預約服務或時間資訊。")

        # --- 處理：收集生日日期時間後 ---
        elif action == 'collect_birth_info':
            birth_datetime_str = event.postback.params.get('datetime')
            if birth_datetime_str:
                print(f"用戶 {user_id} 提供了生日時間: {birth_datetime_str}")
                # 暫存生日資訊，並設定狀態為等待主題
                user_states[user_id] = {
                    "state": "awaiting_topic_after_picker",
                    "data": {"birth_info_str": birth_datetime_str}
                }
                # 準備 Quick Reply 按鈕詢問主題
                quick_reply_items = [
                    QuickReplyButton(action=MessageAction(label="感情", text="感情")),
                    QuickReplyButton(action=MessageAction(label="事業", text="事業")),
                    QuickReplyButton(action=MessageAction(label="健康", text="健康")),
                    QuickReplyButton(action=MessageAction(label="財運", text="財運")),
                    QuickReplyButton(action=MessageAction(label="其他", text="其他")),
                    QuickReplyButton(action=MessageAction(label="取消", text="取消")),
                ]
                reply_message = TextMessage(
                    text=f"感謝您提供生日時辰。\n請問您主要想詢問關於哪方面的問題？",
                    quick_reply=QuickReply(items=quick_reply_items)
                )
            else:
                 reply_message = TextMessage(text="無法獲取您選擇的生日時間，請重試。")


        # --- 處理 show_info Action ---
        elif action == 'show_info':
            topic = postback_data.get('topic')
            if topic:
                 print(f"用戶 {user_id} 查詢資訊: {topic}")
                 info_text = get_info_text(topic)
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
    # PostbackEvent 沒有 reply_token，必須用 Push API 回覆
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
