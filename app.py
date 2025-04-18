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
user_states = {} # {user_id: {"state": "awaiting_topic_after_picker", "data": {"birth_info_str": "...", "shichen": "..."}}}

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
    else:
        print(f"警告：get_info_text 收到未定義的主題: {topic}")
        return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

# --- 計算時辰輔助函數 (與之前相同) ---
def get_shichen(hour):
    # ... (程式碼同上) ...
    if hour < 0 or hour > 23: return "未知"
    shichen_map = {(23, 0): "子", (1, 2): "丑", (3, 4): "寅", (5, 6): "卯",(7, 8): "辰", (9, 10): "巳", (11, 12): "午", (13, 14): "未",(15, 16): "申", (17, 18): "酉", (19, 20): "戌", (21, 22): "亥"}
    if hour == 23 or hour == 0: return "子"
    for hours, name in shichen_map.items():
        if hours[0] <= hour <= hours[1]: return name
    return "未知"

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    # ... (程式碼同上) ...
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    # 使用 Flask 的 logger 記錄請求 body，方便調試
    app.logger.info(f"Request body: {body}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("簽名驗證失敗")
        app.logger.error("Invalid signature. Check your channel access token/secret.")
        abort(400)
    except Exception as e:
        print(f"處理訊息時發生錯誤: {e}")
        app.logger.exception(f"Error handling request: {e}") # 記錄詳細錯誤堆疊
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
             print(f"警告：按鈕 Postback data 過長 ({len(postback_data_str)}): {postback_data_str}")
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
            app.logger.error(f"Failed to send welcome message to {user_id}: {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    text_lower = text.lower()
    reply_message = None
    now = datetime.datetime.now(TW_TIMEZONE)
    reply_token = event.reply_token # 獲取 reply token

    # --- 檢查是否在命理問事流程中 (等待主題) ---
    if user_id in user_states:
        state_info = user_states[user_id]
        current_state = state_info["state"]

        if text_lower == '取消' or text_lower == '返回':
            if user_id in user_states: del user_states[user_id]
            reply_message = TextMessage(text="好的，已取消。請點擊歡迎訊息中的按鈕重新選擇服務。")

        elif current_state == "awaiting_topic_after_picker":
            topic = text
            birth_info_str = state_info["data"].get("birth_info_str", "未提供")
            shichen = state_info["data"].get("shichen", "未知")
            formatted_birth_info = state_info["data"].get("formatted_birth_info", birth_info_str)

            notification_base_text = (
                f"【命理問事請求】\n"
                f"--------------------\n"
                f"用戶ID: {user_id}\n"
                f"提供生日: {formatted_birth_info}\n"
                f"對應時辰: {shichen}\n"
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
                    app.logger.error(f"Failed to send consultation notification to teacher {teacher_user_id}: {e}")
                    print("備份通知到日誌：")
                    print(notification_base_text + "\n（發送失敗，請查看日誌）")
            else:
                print("警告：未設定老師的 User ID，命理問事通知僅記錄在日誌中。")
                print(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

            reply_message = TextMessage(text=f"收到您的資訊！\n生日時辰：{formatted_birth_info} ({shichen}時)\n問題主題：{topic}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！")
            if user_id in user_states: del user_states[user_id]
        else:
             if user_id in user_states: del user_states[user_id]
             reply_message = TextMessage(text="您目前似乎在進行某個流程，若要重新開始，請點擊歡迎訊息中的按鈕。")

    # --- 如果不在對話流程中，處理特定關鍵字 ---
    else:
        # --- 觸發命理問事流程 ---
        if '命理' in text_lower or '問事' in text_lower:
            # *** 加入您建議的偵錯和錯誤處理 ***
            print(f"DEBUG: Matched '命理' or '問事' for user {user_id}")
            if user_id not in user_states:
                print(f"DEBUG: User {user_id} not in state, proceeding to ask birth info.")
                picker_data_dict = {"action": "collect_birth_info"}
                print(f"DEBUG: Picker data dictionary: {picker_data_dict}")
                picker_data = json.dumps(picker_data_dict)
                print(f"DEBUG: Picker data JSON string: {picker_data} (Length: {len(picker_data)})")
                if len(picker_data) > 300:
                    print(f"ERROR: Picker data too long for user {user_id}.")
                    reply_message = TextMessage(text="系統錯誤，無法啟動生日輸入，請稍後再試。")
                else:
                    min_date = "1920-01-01T00:00"
                    max_date = now.strftime('%Y-%m-%dT%H:%M')
                    print(f"DEBUG: Creating Flex Bubble for Datetime Picker (min={min_date}, max={max_date})")
                    try: # <--- 加入 try
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
                                )
                            ])
                        )
                        reply_message = FlexMessage(alt_text='請選擇您的出生年月日時', contents=bubble)
                        print(f"DEBUG: Successfully created Flex Message for user {user_id}")
                    except Exception as e_flex: # <--- 加入 except
                        print(f"ERROR: Failed to create Flex Message bubble for user {user_id}: {e_flex}")
                        app.logger.error(f"FlexMessage creation failed for user {user_id}: {e_flex}") # Log error
                        reply_message = TextMessage(text="系統錯誤，無法顯示生日選擇器，請稍後再試。") # Fallback reply
            else:
                 print(f"DEBUG: User {user_id} is already in state: {user_states[user_id]['state']}")
                 reply_message = TextMessage(text="您正在輸入生日資訊，請繼續依照提示操作，或輸入「取消」重新開始。")

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

        # --- 移除其他關鍵字處理 ---
        # (相關的 elif 區塊已移除)

        # --- 預設回覆 (引導使用按鈕或指定關鍵字) ---
        else:
            print(f"DEBUG: Received unhandled text from user {user_id}: '{text}'") # 加入日誌
            # 修改預設回覆，更強調按鈕
            reply_message = TextMessage(text="請點擊歡迎訊息中的按鈕來選擇服務，或輸入「預約」、「命理」、「問事」來開始互動，謝謝。")


    # --- 發送回覆 ---
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                # 使用 Reply API 回覆
                print(f"準備 Reply 回覆給 {user_id} (Token: {reply_token[:10]}...)") # Log reply attempt
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=reply_token, # 使用獲取的 reply_token
                        messages=[reply_message]
                    )
                )
                print(f"Reply 回覆成功 for user {user_id}")
            except Exception as e:
                print(f"回覆訊息失敗 for user {user_id}: {e}")
                app.logger.error(f"Failed to reply message to {user_id}: {e}")


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (預約流程 + 生日收集 + 資訊顯示)"""
    reply_message = None
    user_id = event.source.user_id
    postback_data_str = event.postback.data
    print(f"收到 Postback: User={user_id}, Data='{postback_data_str}'")

    try:
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')

        # --- 處理：選擇服務 (預約流程) ---
        if action == 'select_service':
            # (與上次相同)
            selected_service = postback_data.get('service')
            if selected_service:
                print(f"用戶 {user_id} 選擇了預約服務: {selected_service}")
                picker_data = json.dumps({"action": "select_datetime", "service": selected_service})
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
            # (與上次相同)
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
                                app.logger.error(f"Failed to send booking notification to teacher {teacher_user_id}: {e}")
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
                    app.logger.exception(f"Error processing select_datetime postback: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
            else:
                reply_message = TextMessage(text="發生錯誤，缺少預約服務或時間資訊。")

        # --- 處理：收集生日日期時間後 ---
        elif action == 'collect_birth_info':
            birth_datetime_str = event.postback.params.get('datetime')
            if birth_datetime_str:
                print(f"用戶 {user_id} 提供了生日時間: {birth_datetime_str}")
                try:
                    selected_dt = datetime.datetime.fromisoformat(birth_datetime_str)
                    selected_hour = selected_dt.hour
                    shichen = get_shichen(selected_hour)
                    formatted_birth_info = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')
                    print(f"對應時辰: {shichen}")
                except ValueError:
                    print(f"錯誤：解析生日時間失敗: {birth_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                    # 如果解析失敗，立刻回覆錯誤並停止
                    if reply_message:
                         with ApiClient(configuration) as api_client:
                            line_bot_api = MessagingApi(api_client)
                            try:
                                line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[reply_message]))
                            except Exception as push_err:
                                print(f"Push 回覆解析錯誤訊息失敗: {push_err}")
                         return # 結束此 Postback 處理

                # 暫存生日資訊和時辰，並設定狀態為等待主題
                user_states[user_id] = {
                    "state": "awaiting_topic_after_picker",
                    "data": {
                        "birth_info_str": birth_datetime_str,
                        "formatted_birth_info": formatted_birth_info,
                        "shichen": shichen
                    }
                }
                # 準備 Quick Reply 按鈕詢問主題 (加入返回選項)
                quick_reply_items = [
                    QuickReplyButton(action=MessageAction(label="感情", text="感情")),
                    QuickReplyButton(action=MessageAction(label="事業", text="事業")),
                    QuickReplyButton(action=MessageAction(label="健康", text="健康")),
                    QuickReplyButton(action=MessageAction(label="財運", text="財運")),
                    QuickReplyButton(action=MessageAction(label="其他", text="其他")),
                    QuickReplyButton(action=MessageAction(label="返回", text="返回")), # 加入返回/取消
                ]
                reply_message = TextMessage(
                    text=f"感謝您提供生日時辰：\n{formatted_birth_info} ({shichen}時)\n\n請問您主要想詢問關於哪方面的問題？\n（點選下方按鈕或直接輸入）",
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
                 # 如果 get_info_text 返回有效內容才回覆
                 if info_text and not info_text.startswith("抱歉"):
                     reply_message = TextMessage(text=info_text)
                 else:
                     print(f"主題 '{topic}' 沒有對應的說明文字。")
            else:
                 reply_message = TextMessage(text="抱歉，無法識別您想了解的資訊。")

        else:
            print(f"未知的 Postback Action: {action}")

    except json.JSONDecodeError:
        print(f"錯誤：無法解析 Postback data: {postback_data_str}")
        reply_message = TextMessage(text="系統無法處理您的請求，請稍後再試。")
    except Exception as e:
        print(f"處理 Postback 時發生未知錯誤: {e}")
        app.logger.exception(f"Error processing postback: {e}") # Log full traceback
        reply_message = TextMessage(text="系統發生錯誤，請稍後再試。")

    # --- 發送 Postback 的回覆 ---
    # PostbackEvent 沒有 reply_token，必須用 Push API 回覆
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                print(f"準備 Push 回覆給 {user_id}")
                # 處理 QuickReply 的發送
                if isinstance(reply_message, TextMessage) and hasattr(reply_message, 'quick_reply') and reply_message.quick_reply:
                    line_bot_api.push_message(PushMessageRequest(
                        to=user_id, messages=[reply_message]
                    ))
                else:
                    line_bot_api.push_message(PushMessageRequest(
                        to=user_id, messages=[reply_message]
                    ))
                print(f"Push 回覆成功 for user {user_id}")
            except Exception as e:
                print(f"回覆 Postback 訊息失敗: {e}")
                app.logger.error(f"Failed to push reply for postback to {user_id}: {e}")


# --- 主程式入口 ---
if __name__ == "__main__":
    # 設定 Flask logger
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.logger.info('Flask logger configured.')

    port = int(os.getenv('PORT', 8080))
    # 使用 Gunicorn 時，app.run() 不會被執行，但保留它以便本地測試
    # 本地測試時取消下一行的註解:
    # app.run(host='0.0.0.0', port=port, debug=True)
    # 注意：在 Render 上 debug=True 不建議
