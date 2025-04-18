# app.py
import os
import json
import datetime
import re # Import regular expressions for validation
import logging # Import logging
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

# --- 加入版本標記 ---
BOT_VERSION = "v1.4.0" # Increment version
print(f"運行版本：{BOT_VERSION}")

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

# --- 基本設定 ---
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '')
google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 環境變數檢查與日誌 ---
print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN: {'已設置' if channel_access_token else '未設置'}")
print(f"DEBUG: LINE_CHANNEL_SECRET: {'已設置' if channel_secret else '未設置'}")
print(f"DEBUG: GOOGLE_CALENDAR_ID: {'已設置' if calendar_id else '未設置'}")
print(f"DEBUG: GOOGLE_CREDENTIALS_JSON: {'已設置' if google_credentials_json else '未設置'}")
print(f"DEBUG: TEACHER_USER_ID: {teacher_user_id if teacher_user_id else '未設置'}")

if not channel_access_token or not channel_secret:
    app.logger.critical("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
if not calendar_id:
    app.logger.warning("警告：未設定 GOOGLE_CALENDAR_ID 環境變數，無法查詢日曆")
if not google_credentials_json:
    app.logger.warning("警告：未設定 GOOGLE_CREDENTIALS_JSON 環境變數，無法連接 Google Calendar")
if not teacher_user_id:
    app.logger.warning("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

# 初始化 LINE Bot API
try:
    configuration = Configuration(access_token=channel_access_token)
    handler = WebhookHandler(channel_secret)
    print("DEBUG: LINE Bot SDK configuration and handler initialized.")
except Exception as init_err:
    print(f"CRITICAL ERROR: Failed to initialize LINE Bot SDK: {init_err}")
    app.logger.critical(f"Failed to initialize LINE Bot SDK: {init_err}")

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版) ---
# !!! 警告：此簡易狀態管理在 Render 等環境下可能因服務重啟或多實例而遺失狀態 !!!
user_states = {} # {user_id: {"state": "awaiting_question", "data": {...}}}

# --- Google Calendar 輔助函數 ---
def get_google_calendar_service():
    if not google_credentials_json:
        app.logger.error("錯誤：缺少 Google 憑證 JSON 環境變數")
        return None
    try:
        credentials_info = json.loads(google_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except json.JSONDecodeError:
        app.logger.error("錯誤：Google 憑證 JSON 格式錯誤")
        return None
    except Exception as e:
        app.logger.error(f"連接 Google Calendar API 時發生錯誤: {e}")
        return None

def get_calendar_events_for_date(target_date):
    service = get_google_calendar_service()
    if not service:
        return None
    try:
        start_time = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=TW_TIMEZONE)
        end_time = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=TW_TIMEZONE)
        app.logger.info(f"Querying Calendar ID '{calendar_id}' for date {target_date}")
        events_result = service.events().list(
            calendarId=calendar_id, timeMin=start_time.isoformat(), timeMax=end_time.isoformat(),
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        app.logger.info(f"Found {len(events)} events for {target_date}")
        return events
    except Exception as e:
        app.logger.error(f"查詢日曆事件時發生錯誤 ({target_date}): {e}")
        return None

# --- 輔助函數：獲取服務說明文字 ---
def get_info_text(topic):
    current_year = datetime.date.today().year
    if topic == '開運物':
        guangzhou_shopping_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n🔹 如有特定需求或想預購，歡迎私訊老師。\n🔹 商品預計於老師回台後 ({current_year}/4/22之後) 陸續整理並寄出，感謝您的耐心等待！"
        return ("【開運物品】\n提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n" + guangzhou_shopping_reminder)
    elif topic == '生基品':
         guangzhou_shengji_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州尋找適合的玉器等生基相關用品。\n🔹 如有興趣或需求，歡迎私訊老師洽詢。\n🔹 相關用品預計於老師回台後 ({current_year}/4/22之後) 整理寄出。"
         return ("【生基用品】\n生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n老師提供相關諮詢與必需品代尋服務。\n\n" + guangzhou_shengji_reminder)
    else:
        app.logger.warning(f"get_info_text 收到未定義的主題: {topic}")
        return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

# --- 計算時辰輔助函數 ---
def get_shichen(hour):
    if not isinstance(hour, int) or hour < 0 or hour > 23: return "未知"
    shichen_map = {(23, 0): "子", (1, 2): "丑", (3, 4): "寅", (5, 6): "卯",(7, 8): "辰", (9, 10): "巳", (11, 12): "午", (13, 14): "未",(15, 16): "申", (17, 18): "酉", (19, 20): "戌", (21, 22): "亥"}
    if hour == 0: return "子"
    for hours, name in shichen_map.items():
        if hours == (23, 0) and hour == 23: return "子"
        if hours[0] <= hour <= hours[1]: return name
    return "未知"

# --- 輔助函數：建立主選單 Flex Message ---
def create_main_menu_message():
    """建立包含服務按鈕的主選單 Flex Message"""
    buttons = []
    services = {
        "預約：問事/命理": {"action": "select_service", "service": "問事/命理"},
        "預約：法事": {"action": "select_service", "service": "法事"},
        "預約：收驚": {"action": "select_service", "service": "收驚"},
        "預約：卜卦": {"action": "select_service", "service": "卜卦"},
        "了解：開運物": {"action": "show_info", "topic": "開運物"},
        "了解：生基品": {"action": "show_info", "topic": "生基品"}
    }
    button_style = {'primary': '#A67B5B', 'secondary': '#BDBDBD'}
    for label, data in services.items():
        style_key = 'primary' if data['action'] == 'select_service' else 'secondary'
        postback_data_str = json.dumps(data)
        if len(postback_data_str) <= 300:
            buttons.append(FlexButton(
                action=PostbackAction(label=label, data=postback_data_str, display_text=label),
                style=style_key, color=button_style[style_key], margin='sm', height='sm'
            ))
        else:
             app.logger.warning(f"主選單按鈕 Postback data 過長 ({len(postback_data_str)}): {postback_data_str}")

    bubble = FlexBubble(
        header=FlexBox(layout='vertical', padding_all='md', contents=[
             FlexText(text='請問需要什麼服務？', weight='bold', size='lg', align='center', color='#B28E49'),
        ]),
        body=FlexBox(layout='vertical', spacing='sm', contents=buttons)
    )
    return FlexMessage(alt_text='請選擇服務', contents=bubble)

# --- 輔助函數：發送訊息 (處理 Push/Reply) ---
def send_message(recipient_id, message, reply_token=None):
    """統一處理發送訊息，優先使用 Reply，失敗或無 Token 時嘗試 Push"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        message_list = [message] if not isinstance(message, list) else message

        if reply_token:
            try:
                app.logger.info(f"Attempting Reply to {recipient_id[:10]}... (Token: {reply_token[:10]}...)")
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=reply_token, messages=message_list)
                )
                app.logger.info(f"Reply successful for {recipient_id[:10]}...")
                return True
            except Exception as e_reply:
                app.logger.warning(f"Reply failed for {recipient_id[:10]}... (Token: {reply_token[:10]}...): {e_reply}. Attempting Push.")

        try:
            app.logger.info(f"Attempting Push to {recipient_id[:10]}...")
            cleaned_messages = []
            for msg in message_list:
                 if isinstance(msg, TextMessage) and hasattr(msg, 'quick_reply') and msg.quick_reply:
                     cleaned_messages.append(TextMessage(text=msg.text))
                 else:
                     cleaned_messages.append(msg)
            line_bot_api.push_message(PushMessageRequest(to=recipient_id, messages=cleaned_messages))
            app.logger.info(f"Push successful for {recipient_id[:10]}...")
            return True
        except Exception as e_push:
            app.logger.error(f"Push failed for {recipient_id[:10]}...: {e_push}")
            return False

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Check your channel access token/secret.")
        abort(400)
    except Exception as e:
        app.logger.exception(f"Error handling request: {e}")
        abort(500)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """處理加好友事件，發送主選單按鈕"""
    user_id = event.source.user_id
    app.logger.info(f"User {user_id} added the bot.")
    # 清除可能殘留的狀態
    if user_id in user_states:
        del user_states[user_id]
    main_menu_message = create_main_menu_message()
    send_message(user_id, main_menu_message)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token
    app.logger.info(f"Received text message from {user_id}: '{text}'")

    # --- 檢查是否在命理問事流程中 (等待問題) ---
    if user_id in user_states and user_states[user_id]["state"] == "awaiting_question":
        state_info = user_states[user_id]
        user_data = state_info["data"]
        question = text # 將用戶輸入的文字視為問題內容
        user_data["question"] = question
        app.logger.info(f"User {user_id} provided question: '{question}'")

        birth_info_str = user_data.get("birth_info_str", "未提供")
        shichen = user_data.get("shichen", "未知")
        formatted_birth_info = user_data.get("formatted_birth_info", birth_info_str)

        # --- 記錄資訊並通知老師 ---
        notification_base_text = (
            f"【命理問事請求】\n"
            f"--------------------\n"
            f"用戶ID: {user_id}\n"
            f"提供生日: {formatted_birth_info}\n"
            f"對應時辰: {shichen}\n"
            f"問題內容: {question}\n"
            f"--------------------"
        )
        app.logger.info(f"準備處理命理問事請求: {notification_base_text}")

        if teacher_user_id:
            try:
                push_notification_text = notification_base_text + "\n請老師抽空親自回覆"
                send_message(teacher_user_id, TextMessage(text=push_notification_text))
                app.logger.info("命理問事通知已嘗試發送給老師。")
            except Exception as e:
                app.logger.error(f"錯誤：發送命理問事通知給老師失敗: {e}")
                app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
        else:
            app.logger.warning("警告：未設定老師的 User ID，命理問事通知僅記錄在日誌中。")
            app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

        # --- 回覆客戶 ---
        reply_text_to_user = f"收到您的資訊！\n生日時辰：{formatted_birth_info} ({shichen}時)\n問題內容：{question}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！"
        # 發送確認訊息，然後顯示主選單
        send_message(user_id, TextMessage(text=reply_text_to_user), reply_token) # 先用 Reply Token 回覆確認
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message) # 再用 Push 發送主選單

        # 清除狀態
        if user_id in user_states:
            app.logger.info(f"Clearing state for user {user_id} after consultation info submission.")
            del user_states[user_id]

    # --- 如果不在特定流程中，所有其他文字訊息一律回覆主選單 ---
    else:
        app.logger.info(f"User {user_id} sent text '{text}' outside of expected flow. Replying with main menu.")
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message, reply_token)


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (預約流程 + 生日收集 + 資訊顯示 + 返回)"""
    reply_message = None
    follow_up_message = None # 用於在主要回覆後再發送主選單
    user_id = event.source.user_id
    # Postback event 沒有 reply_token，所有回覆都需用 Push
    app.logger.info(f"Received Postback from {user_id}")

    try:
        postback_data_str = event.postback.data
        app.logger.info(f"Postback data string: '{postback_data_str}'")
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')
        app.logger.info(f"Postback action: '{action}'")

        # --- 處理：返回主選單 ---
        if action == 'show_main_menu':
            if user_id in user_states:
                app.logger.info(f"Clearing state for user {user_id} due to 'show_main_menu'.")
                del user_states[user_id]
            reply_message = create_main_menu_message()

        # --- 處理：選擇服務 (預約或問事) ---
        elif action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                app.logger.info(f"User {user_id} selected service: {selected_service}")
                back_button_data = json.dumps({"action": "show_main_menu"})
                back_button = FlexButton(
                    action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'),
                    style='secondary', height='sm', margin='xl' #加大間距
                )
                if selected_service == "問事/命理":
                    picker_data = json.dumps({"action": "collect_birth_info"})
                    if len(picker_data) > 300:
                         app.logger.error(f"問事/命理 Picker data too long for user {user_id}")
                         reply_message = TextMessage(text="系統錯誤，無法啟動生日輸入，請稍後再試。")
                         follow_up_message = create_main_menu_message()
                    else:
                        min_date = "1920-01-01T00:00"
                        max_date = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT%H:%M')
                        bubble = FlexBubble(
                            body=FlexBox(layout='vertical', spacing='md', contents=[
                                FlexText(text='進行命理分析需要您的出生年月日時。', wrap=True, size='md'),
                                FlexText(text='若不確定準確時辰，可先選擇大概時間（如中午12點），稍後與老師確認。', wrap=True, size='sm', color='#666666', margin='sm'),
                                FlexButton(
                                    action=DatetimePickerAction(
                                        label='📅 點此選擇生日時辰', data=picker_data, mode='datetime',
                                        min=min_date, max=max_date
                                    ),
                                    style='primary', color='#A67B5B', margin='lg'
                                ),
                                back_button # 加入返回按鈕
                            ])
                        )
                        reply_message = FlexMessage(alt_text='請選擇您的出生年月日時', contents=bubble)
                else: # 法事, 收驚, 卜卦 - 進入預約時間選擇
                    picker_data = json.dumps({"action": "select_datetime", "service": selected_service})
                    if len(picker_data) > 300:
                        app.logger.error(f"預約 Picker data too long for user {user_id}, service {selected_service}")
                        reply_message = TextMessage(text="系統錯誤，無法啟動時間選擇，請稍後再試。")
                        follow_up_message = create_main_menu_message()
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
                                ),
                                back_button # 加入返回按鈕
                            ])
                        )
                        reply_message = FlexMessage(alt_text='請選擇預約日期時間', contents=bubble)
            else:
                app.logger.warning(f"Postback 'select_service' missing service for user {user_id}")
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的服務。")
                follow_up_message = create_main_menu_message()

        # --- 處理：選擇生日日期時間後 (問事流程) ---
        elif action == 'collect_birth_info':
            selected_datetime_str = event.postback.params.get('datetime')
            if selected_datetime_str:
                app.logger.info(f"User {user_id} submitted birth datetime: {selected_datetime_str}")
                try:
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    hour = selected_dt.hour
                    shichen = get_shichen(hour)
                    formatted_dt = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')
                    user_states[user_id] = {
                        "state": "awaiting_question",
                        "data": {
                            "birth_info_str": selected_datetime_str,
                            "formatted_birth_info": formatted_dt,
                            "shichen": shichen
                        }
                    }
                    app.logger.info(f"State set for user {user_id}: awaiting_question")
                    # 提示用戶輸入問題 (不加按鈕，提示可輸入 '返回')
                    reply_message = TextMessage(text=f"收到您的生日時辰：{formatted_dt} ({shichen}時)\n\n請接著輸入您想詢問的具體問題：\n（若要返回主選單請輸入「返回」）")

                except ValueError:
                    app.logger.error(f"Failed to parse birth datetime for user {user_id}: {selected_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                    follow_up_message = create_main_menu_message()
                except Exception as e:
                    app.logger.exception(f"Error processing birth info for user {user_id}: {e}")
                    reply_message = TextMessage(text="處理您的生日資訊時發生錯誤，請稍後再試。")
                    follow_up_message = create_main_menu_message()
            else:
                 app.logger.warning(f"Postback 'collect_birth_info' missing datetime for user {user_id}")
                 reply_message = TextMessage(text="發生錯誤，未收到您選擇的生日時間。")
                 follow_up_message = create_main_menu_message()

        # --- 處理：選擇預約日期時間後 (預約流程) ---
        elif action == 'select_datetime':
            selected_service = postback_data.get('service')
            selected_datetime_str = event.postback.params.get('datetime')
            if selected_service and selected_datetime_str:
                app.logger.info(f"User {user_id} booking service '{selected_service}' at '{selected_datetime_str}'")
                try:
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    selected_date = selected_dt.date()
                    formatted_dt = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')
                    proceed_booking = True
                    if selected_service == '法事':
                        app.logger.info(f"Checking ritual availability for {user_id} on {selected_date}")
                        events = get_calendar_events_for_date(selected_date)
                        if events is None:
                            app.logger.error(f"Failed to query calendar for {selected_date}, blocking ritual booking for {user_id}")
                            reply_message = TextMessage(text=f"抱歉，目前無法確認老師 {selected_date.strftime('%Y-%m-%d')} 的行程，請稍後再試或直接私訊老師。")
                            proceed_booking = False
                        elif len(events) > 0:
                            app.logger.info(f"Ritual booking conflict for {user_id} on {selected_date} ({len(events)} events)")
                            reply_message = TextMessage(text=f"抱歉，老師在 {selected_date.strftime('%Y-%m-%d')} 已有行程安排，暫無法進行法事，請選擇其他日期，謝謝。")
                            proceed_booking = False

                    if proceed_booking:
                        notification_base_text = (f"【預約請求】\n--------------------\n用戶ID: {user_id}\n服務項目: {selected_service}\n預約時間: {formatted_dt}\n--------------------")
                        app.logger.info(f"Processing booking request: {notification_base_text}")
                        if teacher_user_id:
                            try:
                                push_notification_text = notification_base_text + "\n請老師盡快確認並回覆客戶"
                                send_message(teacher_user_id, TextMessage(text=push_notification_text))
                                app.logger.info("預約通知已嘗試發送給老師。")
                            except Exception as e:
                                app.logger.error(f"錯誤：發送預約通知給老師失敗: {e}")
                                app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
                        else:
                            app.logger.warning("警告：未設定老師的 User ID，預約通知僅記錄在日誌中。")
                            app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
                        reply_text_to_user = (f"收到您的預約請求：\n服務：{selected_service}\n時間：{formatted_dt}\n\n此預約請求已發送給老師，將由老師為您處理後續確認事宜，感謝您的耐心等候！")
                        reply_message = TextMessage(text=reply_text_to_user)
                        follow_up_message = create_main_menu_message()
                    else:
                         follow_up_message = create_main_menu_message()
                except ValueError:
                    app.logger.error(f"Failed to parse booking datetime for user {user_id}: {selected_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                    follow_up_message = create_main_menu_message()
                except Exception as e:
                    app.logger.exception(f"Error processing booking datetime for user {user_id}: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
                    follow_up_message = create_main_menu_message()
            else:
                 app.logger.warning(f"Postback 'select_datetime' missing data for user {user_id}")
                 reply_message = TextMessage(text="發生錯誤，缺少預約服務或時間資訊。")
                 follow_up_message = create_main_menu_message()

        # --- 處理 show_info Action ---
        elif action == 'show_info':
            topic = postback_data.get('topic')
            if topic:
                 app.logger.info(f"User {user_id} requested info for topic: {topic}")
                 info_text = get_info_text(topic)
                 reply_message = TextMessage(text=info_text)
                 follow_up_message = create_main_menu_message()
            else:
                 app.logger.warning(f"Postback 'show_info' missing topic for user {user_id}")
                 reply_message = TextMessage(text="抱歉，無法識別您想了解的資訊。")
                 follow_up_message = create_main_menu_message()

        else:
            app.logger.warning(f"Received unknown Postback Action from {user_id}: {action}")
            reply_message = create_main_menu_message()

    except json.JSONDecodeError:
        app.logger.error(f"Failed to parse Postback data from {user_id}: {postback_data_str}")
        reply_message = TextMessage(text="系統無法處理您的請求，請稍後再試。")
        follow_up_message = create_main_menu_message()
    except Exception as e:
        app.logger.exception(f"Error processing Postback from {user_id}: {e}")
        reply_message = TextMessage(text="系統發生錯誤，請稍後再試。")
        follow_up_message = create_main_menu_message()

    # --- 發送 Postback 的回覆 (一律用 Push) ---
    messages_to_send = []
    if reply_message: messages_to_send.append(reply_message)
    if follow_up_message: messages_to_send.append(follow_up_message)
    if messages_to_send: send_message(user_id, messages_to_send)


# --- 主程式入口 ---
if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.run(host='0.0.0.0', port=port, debug=False)

