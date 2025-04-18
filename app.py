很抱歉，我無法直接修改您電腦上、GitHub 倉庫或 Render 上的檔案。我是一個 AI 助理，沒有權限存取您的檔案系統或遠端服務。
但是，我可以將您先前提供的 app.py 程式碼，根據我建議的修改方式，產生一份完整修改後的版本給您。您只需要將下面的整段程式碼複製起來，然後完全取代您現有的 app.py 檔案內容，儲存後再重新部署到 Render 即可。
# app.py (已修改 import 語句)
import os
import json
import datetime
import re # Import regular expressions for validation
import logging # Import logging
from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
# *** 修改後的 Import 區塊 ***
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
    FlexSeparator
    # 移除 QuickReply, QuickReplyButton, Actions - 改從 models 匯入
)
# 單獨從 models 匯入 QuickReply 和 Action 相關類別
from linebot.v3.messaging.models import (
    QuickReply,
    QuickReplyButton,
    MessageAction,
    URIAction,
    PostbackAction,
    DatetimePickerAction
)
# --- (Webhooks import 保持不變) ---
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    PostbackEvent,
    # 增加 InvalidSignatureError 的匯入 (如果之前沒加的話)
    InvalidSignatureError
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz

# --- 加入版本標記 ---
BOT_VERSION = "v1.5.1" # Increment version after fix attempt
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
if not channel_access_token: app.logger.critical("錯誤：缺少 LINE_CHANNEL_ACCESS_TOKEN"); # Consider aborting if critical
if not channel_secret: app.logger.critical("錯誤：缺少 LINE_CHANNEL_SECRET"); # Consider aborting if critical
if not calendar_id: app.logger.warning("警告：缺少 GOOGLE_CALENDAR_ID"); # Calendar features will fail
if not google_credentials_json: app.logger.warning("警告：缺少 GOOGLE_CREDENTIALS_JSON"); # Calendar features will fail
if not teacher_user_id: app.logger.warning("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN: {'已設置' if channel_access_token else '未設置'}")
print(f"DEBUG: LINE_CHANNEL_SECRET: {'已設置' if channel_secret else '未設置'}")
print(f"DEBUG: GOOGLE_CALENDAR_ID: {'已設置' if calendar_id else '未設置'}")
print(f"DEBUG: GOOGLE_CREDENTIALS_JSON: {'已設置' if google_credentials_json else '未設置'}")
print(f"DEBUG: TEACHER_USER_ID: {'已設置' if teacher_user_id else '未設置'}")


# 初始化 LINE Bot API
handler = None
configuration = None
if channel_access_token and channel_secret:
    try:
        configuration = Configuration(access_token=channel_access_token)
        handler = WebhookHandler(channel_secret)
        print("DEBUG: LINE Bot SDK configuration and handler initialized.")
    except Exception as init_err:
        app.logger.critical(f"Failed to initialize LINE Bot SDK: {init_err}")
        handler = None # Ensure handler is None if init fails
else:
    app.logger.critical("Cannot initialize LINE Bot SDK due to missing credentials.")


# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版) ---
# !!! 警告：此簡易狀態管理在 Render 等環境下可能因服務重啟或多實例而遺失狀態 !!!
user_states = {} # {user_id: {"state": "...", "data": {...}}}

# --- Google Calendar 輔助函數 ---
def get_google_calendar_service():
    if not google_credentials_json:
        app.logger.error("錯誤：缺少 Google 憑證 JSON 環境變數")
        return None
    try:
        credentials_info = json.loads(google_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        app.logger.info("Successfully connected to Google Calendar API.")
        return service
    except json.JSONDecodeError as json_err:
        app.logger.error(f"錯誤：Google 憑證 JSON 格式無效: {json_err}")
        return None
    except Exception as e:
        app.logger.error(f"連接 Google Calendar API 時發生錯誤: {e}")
        return None

def get_calendar_events_for_date(target_date):
    service = get_google_calendar_service()
    if not service:
        app.logger.error("無法獲取 Google Calendar 服務，無法查詢事件。")
        return None
    if not calendar_id:
        app.logger.error("未設定 Google Calendar ID，無法查詢事件。")
        return None

    try:
        # Ensure target_date is a date object
        if isinstance(target_date, datetime.datetime):
            target_date = target_date.date()
        elif not isinstance(target_date, datetime.date):
             app.logger.error(f"get_calendar_events_for_date 接收到無效的日期類型: {type(target_date)}")
             return None

        start_time = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=TW_TIMEZONE)
        end_time = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=TW_TIMEZONE)
        app.logger.info(f"Querying Calendar ID '{calendar_id}' for date {target_date.strftime('%Y-%m-%d')}")
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        app.logger.info(f"Found {len(events)} events for {target_date.strftime('%Y-%m-%d')}")
        return events
    except Exception as e:
        app.logger.error(f"查詢日曆事件時發生錯誤 ({target_date.strftime('%Y-%m-%d')}): {e}")
        return None

# --- 輔助函數：獲取服務說明文字 ---
def get_info_text(topic):
    current_year = datetime.date.today().year
    guangzhou_dates = f"{current_year}/4/11 - {current_year}/4/22" # 統一日期範圍
    return_date_info = f"{current_year}/4/22之後" # 統一回台日期

    if topic == '開運物':
        guangzhou_shopping_reminder = (
            f"🛍️ 最新消息：\n"
            f"🔹 {guangzhou_dates} 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n"
            f"🔹 如有特定需求或想預購，歡迎私訊老師。\n"
            f"🔹 商品預計於老師回台後 ({return_date_info}) 陸續整理並寄出，感謝您的耐心等待！"
        )
        return (
            "【開運物品】\n"
            "提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n" +
            guangzhou_shopping_reminder
        )
    elif topic == '生基品':
         guangzhou_shengji_reminder = (
            f"🛍️ 最新消息：\n"
            f"🔹 {guangzhou_dates} 老師親赴廣州尋找適合的玉器等生基相關用品。\n"
            f"🔹 如有興趣或需求，歡迎私訊老師洽詢。\n"
            f"🔹 相關用品預計於老師回台後 ({return_date_info}) 整理寄出。"
         )
         return (
            "【生基用品】\n"
            "生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n"
            "老師提供相關諮詢與必需品代尋服務。\n\n" +
            guangzhou_shengji_reminder
         )
    else:
        app.logger.warning(f"get_info_text 收到未定義的主題: {topic}")
        return f"抱歉，目前沒有關於「{topic}」的詳細說明。"


# --- 計算時辰輔助函數 ---
def get_shichen(hour):
    """根據小時(0-23)計算對應的中文時辰"""
    if not isinstance(hour, int) or hour < 0 or hour > 23:
        app.logger.warning(f"無效的小時輸入用於計算時辰: {hour}")
        return "未知"
    # 定義時辰對應的小時範圍 (包含起始，不含結束，特殊處理子時)
    shichen_map = {
        "子": (23, 1), "丑": (1, 3), "寅": (3, 5), "卯": (5, 7),
        "辰": (7, 9), "巳": (9, 11), "午": (11, 13), "未": (13, 15),
        "申": (15, 17), "酉": (17, 19), "戌": (19, 21), "亥": (21, 23)
    }
    for name, hours in shichen_map.items():
        start, end = hours
        if start == 23: # 子時跨日特殊處理
            if hour >= start or hour < end:
                app.logger.info(f"Hour {hour} maps to Shichen: {name}")
                return name
        elif start <= hour < end:
            app.logger.info(f"Hour {hour} maps to Shichen: {name}")
            return name
    app.logger.warning(f"Could not map hour {hour} to Shichen.")
    return "未知"

# --- 輔助函數：建立主選單 Flex Message ---
def create_main_menu_message():
    """建立包含服務按鈕的主選單 Flex Message"""
    buttons = []
    # 服務項目與對應的 Postback data
    services = {
        "預約：問事/命理": {"action": "select_service", "service": "問事/命理"},
        "預約：法事": {"action": "select_service", "service": "法事"},
        "預約：收驚": {"action": "select_service", "service": "收驚"},
        "預約：卜卦": {"action": "select_service", "service": "卜卦"},
        "了解：開運物": {"action": "show_info", "topic": "開運物"},
        "了解：生基品": {"action": "show_info", "topic": "生基品"}
    }
    button_style = {'primary': '#A67B5B', 'secondary': '#BDBDBD'} # 定義按鈕顏色

    for label, data in services.items():
        try:
            postback_data_str = json.dumps(data, ensure_ascii=False) # ensure_ascii=False for Chinese chars
            postback_data_bytes = postback_data_str.encode('utf-8')
            if len(postback_data_bytes) <= 300:
                style_key = 'primary' if data['action'] == 'select_service' else 'secondary'
                buttons.append(FlexButton(
                    action=PostbackAction(label=label, data=postback_data_str, display_text=label),
                    style=style_key, color=button_style[style_key], margin='sm', height='sm'
                ))
            else:
                 app.logger.warning(f"主選單按鈕 Postback data 過長 ({len(postback_data_bytes)} bytes): {label} -> {postback_data_str}")
        except Exception as e:
            app.logger.error(f"建立主選單按鈕時出錯: {label}, error: {e}")

    # 檢查是否成功產生任何按鈕
    if not buttons:
        app.logger.error("無法產生任何主選單按鈕！")
        # 返回一個簡單的文字訊息作為備用
        return TextMessage(text="抱歉，目前無法顯示服務選單，請稍後再試或直接輸入您的問題。")

    # 建立 Flex Message 結構
    bubble = FlexBubble(
        header=FlexBox(layout='vertical', padding_all='md', contents=[
             FlexText(text='請問需要什麼服務？', weight='bold', size='lg', align='center', color='#B28E49'),
        ]),
        body=FlexBox(layout='vertical', spacing='sm', contents=buttons) # 按鈕放在 body
    )
    return FlexMessage(alt_text='請問需要什麼服務？(請選擇)', contents=bubble) # 修改 alt_text

# --- 輔助函數：發送訊息 (處理 Push/Reply) ---
def send_message(recipient_id, message, reply_token=None):
    """統一處理發送訊息，優先使用 Reply，失敗或無 Token 時嘗試 Push"""
    if not configuration:
        app.logger.error("LINE SDK 未初始化，無法發送訊息。")
        return False

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        # 確保 message 是列表
        message_list = [message] if not isinstance(message, list) else message

        # 檢查 message_list 是否為空或包含 None
        if not message_list or any(m is None for m in message_list):
             app.logger.error(f"嘗試發送空訊息或包含 None 的訊息列表給 {recipient_id[:10]}...")
             return False

        # Reply 優先
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
                # Reply 失敗，繼續嘗試 Push (不需要 return False)

        # Reply 失敗或無 Token 時，嘗試 Push
        try:
            app.logger.info(f"Attempting Push to {recipient_id[:10]}...")
            # Push API 不支援 QuickReply，需要清理
            cleaned_messages = []
            for msg in message_list:
                 if isinstance(msg, TextMessage) and hasattr(msg, 'quick_reply') and msg.quick_reply:
                     # 只保留文字部分，移除 QuickReply
                     cleaned_messages.append(TextMessage(text=msg.text))
                     app.logger.info("Removed QuickReply from message before Pushing.")
                 elif msg: # 確保訊息不是 None
                     cleaned_messages.append(msg)

            if not cleaned_messages:
                 app.logger.error(f"清理後無有效訊息可發送 (Push) 給 {recipient_id[:10]}...")
                 return False

            line_bot_api.push_message(
                PushMessageRequest(to=recipient_id, messages=cleaned_messages)
            )
            app.logger.info(f"Push successful for {recipient_id[:10]}...")
            return True
        except Exception as e_push:
            app.logger.error(f"Push failed for {recipient_id[:10]}...: {e_push}")
            return False

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    # 檢查 handler 是否已初始化
    if not handler:
        app.logger.critical("Webhook handler 未初始化，無法處理請求。")
        abort(500) # Internal Server Error

    signature = request.headers.get('X-Line-Signature', '') # Use .get for safety
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}") # Consider logging less in production if sensitive

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature received.")
        abort(400) # Bad Request
    except Exception as e:
        app.logger.exception(f"Error handling request: {e}") # Log full exception
        abort(500) # Internal Server Error

    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """處理加好友事件，發送主選單按鈕"""
    user_id = event.source.user_id
    reply_token = event.reply_token # FollowEvent has a reply token
    app.logger.info(f"User {user_id} added the bot.")

    # 清除該用戶可能存在的舊狀態
    if user_id in user_states:
        app.logger.info(f"Clearing existing state for new follow user {user_id}.")
        del user_states[user_id]

    main_menu_message = create_main_menu_message()
    # 嘗試使用 Reply Token 發送歡迎訊息+主選單
    send_message(user_id, main_menu_message, reply_token)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token
    app.logger.info(f"Received text message from {user_id}: '{text}'")

    current_state_info = user_states.get(user_id)
    current_state = current_state_info.get("state") if current_state_info else None
    user_data = current_state_info.get("data") if current_state_info else {}

    app.logger.info(f"User {user_id} current state: {current_state}") # Log current state

    # --- 檢查是否是取消指令 ---
    if text.lower() in ['返回', '取消', '主選單']:
        if user_id in user_states:
            app.logger.info(f"Clearing state for user {user_id} due to '{text}' input.")
            del user_states[user_id]
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message, reply_token)
        return # 處理完取消指令，結束

    # --- 根據狀態處理 ---

    # 狀態：等待選擇主題 (QuickReply 回應)
    if current_state == "awaiting_topic_selection":
        topic = text # QuickReply 回傳的是文字
        valid_topics = ["事業", "感情", "健康", "財運", "其他"] # 與 QuickReply 按鈕對應

        if topic in valid_topics:
            user_data["topic"] = topic
            user_states[user_id]["state"] = "awaiting_question_detail" # 更新狀態
            app.logger.info(f"User {user_id} selected topic: {topic}. Now awaiting question detail.")
            # 提示輸入問題，並告知可輸入 '返回'
            reply_message = TextMessage(text=f"好的，您選擇了「{topic}」。\n請簡述您想問的具體問題或情況：\n（若想返回主選單請直接輸入「返回」或「取消」）")
            send_message(user_id, reply_message, reply_token)
        else:
            # 輸入了無效的主題，重新提示 (維持在 awaiting_topic_selection 狀態)
            app.logger.warning(f"User {user_id} entered invalid topic '{topic}' while awaiting topic selection.")
            quick_reply_items = [QuickReplyButton(action=MessageAction(label=t, text=t)) for t in valid_topics]
            quick_reply_items.append(QuickReplyButton(action=MessageAction(label="取消", text="取消")))
            reply_message = TextMessage(
                text="請點擊下方按鈕選擇主要想詢問的問題主題，或輸入「取消」返回主選單：",
                quick_reply=QuickReply(items=quick_reply_items)
            )
            send_message(user_id, reply_message, reply_token)

    # 狀態：等待輸入問題詳情
    elif current_state == "awaiting_question_detail":
        question = text # 將用戶輸入的文字視為問題內容
        user_data["question"] = question
        app.logger.info(f"User {user_id} provided question detail: '{question[:100]}...'") # Log truncated question

        birth_info_str = user_data.get("birth_info_str", "未提供")
        shichen = user_data.get("shichen", "未知")
        formatted_birth_info = user_data.get("formatted_birth_info", birth_info_str) # Use formatted if available
        topic = user_data.get("topic", "未指定")

        # --- 記錄資訊並通知老師 ---
        notification_lines = [
            "【命理問事請求】",
            "--------------------",
            f"用戶ID: {user_id}", # Consider if user ID should be sent
            f"提供生日: {formatted_birth_info}",
            f"對應時辰: {shichen}",
            f"問題主題: {topic}",
            f"問題內容:\n{question}", # Full question
            "--------------------"
        ]
        notification_base_text = "\n".join(notification_lines)
        app.logger.info(f"準備處理命理問事請求:\n{notification_base_text}")

        if teacher_user_id:
            try:
                push_notification_text = notification_base_text + "\n請老師抽空親自回覆"
                # 使用 send_message 函數發送 (不帶 reply_token)
                success = send_message(teacher_user_id, TextMessage(text=push_notification_text))
                if success:
                    app.logger.info("命理問事通知已嘗試發送給老師。")
                else:
                     app.logger.error("錯誤：發送命理問事通知給老師失敗 (send_message returned False)。")
                     app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
            except Exception as e:
                app.logger.error(f"錯誤：發送命理問事通知給老師時發生異常: {e}")
                app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送異常，請查看日誌）")
        else:
            app.logger.warning("警告：未設定老師的 User ID，命理問事通知僅記錄在日誌中。")
            app.logger.info("日誌記錄通知：\n" + notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

        # --- 回覆客戶 ---
        reply_text_to_user = (
            f"收到您的資訊！\n"
            f"生日時辰：{formatted_birth_info} ({shichen}時)\n"
            f"問題主題：{topic}\n"
            # 顯示部分問題內容確認
            f"問題內容：{question[:50]}{'...' if len(question)>50 else ''}\n\n"
            f"老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！"
        )
        # 先用 Reply Token 回覆確認訊息
        send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)

        # 然後用 Push 發送主選單 (避免覆蓋 Reply)
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message)

        # 清除狀態
        if user_id in user_states:
            app.logger.info(f"Clearing state for user {user_id} after consultation info submission.")
            del user_states[user_id]

    # --- 如果不在特定流程中，且不是取消指令 ---
    else:
        app.logger.info(f"User {user_id} sent text '{text}' outside of expected flow or state. Replying with main menu.")
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message, reply_token)


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (預約流程 + 生日收集 + 資訊顯示 + 返回)"""
    user_id = event.source.user_id
    reply_token = event.reply_token
    app.logger.info(f"Received Postback from {user_id}")

    reply_message = None # 要回覆的主要訊息
    follow_up_message = None # 可能需要額外 Push 的訊息 (如主選單)

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

        # --- 處理：顯示資訊 (開運物/生基品) ---
        elif action == 'show_info':
             topic = postback_data.get('topic')
             if topic:
                 info_text = get_info_text(topic)
                 back_button_data = json.dumps({"action": "show_main_menu"})
                 back_button = FlexButton(
                     action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'),
                     style='secondary', height='sm', margin='xl'
                 )
                 bubble = FlexBubble(
                     header=FlexBox(layout='vertical', contents=[FlexText(text=f"【{topic}】說明", weight='bold', size='lg', align='center', color='#B28E49')]),
                     body=FlexBox(layout='vertical', spacing='md', contents=[
                         FlexText(text=info_text, wrap=True, size='sm'),
                         back_button
                     ])
                 )
                 reply_message = FlexMessage(alt_text=f'{topic} 相關說明', contents=bubble)
             else:
                 app.logger.warning(f"Postback 'show_info' missing topic for user {user_id}")
                 reply_message = TextMessage(text="發生錯誤，無法顯示相關說明。")
                 follow_up_message = create_main_menu_message()


        # --- 處理：選擇服務 (點擊主選單的預約按鈕) ---
        elif action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                app.logger.info(f"User {user_id} selected service: {selected_service}")

                # --- 準備 Flex Message 內容 ---
                contents = []
                alt_text = f'選擇 {selected_service}' # Default alt text

                # --- 返回主選單按鈕 (通用) ---
                back_button = None
                try:
                    back_button_data = json.dumps({"action": "show_main_menu"})
                    back_button_bytes = back_button_data.encode('utf-8')
                    if len(back_button_bytes) <= 300:
                         back_button = FlexButton(
                             action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'),
                             style='secondary', height='sm', margin='xl'
                         )
                    else:
                        app.logger.error("Back button postback data too long!")
                except Exception as e:
                     app.logger.error(f"Error creating back button: {e}")

                # --- 根據服務類型建立不同內容 ---
                if selected_service == "問事/命理":
                    try:
                        picker_data = json.dumps({"action": "collect_birth_info", "service": selected_service}) # Add service here too
                        picker_data_bytes = picker_data.encode('utf-8')
                        if len(picker_data_bytes) > 300:
                            app.logger.error(f"問事/命理 Picker data too long ({len(picker_data_bytes)} bytes) for user {user_id}")
                            raise ValueError("Picker data too long") # Trigger exception handling

                        min_date_str = "1920-01-01T00:00" # Allow older dates
                        # Max date should be now (or slightly in the past)
                        max_date_str = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT%H:%M')

                        contents.extend([
                            FlexText(text=f'您選擇了：{selected_service}', weight='bold', align='center'),
                            FlexSeparator(margin='md'),
                            FlexText(text='進行命理分析需要您的出生年月日時。', wrap=True, size='md', margin='md'),
                            FlexText(text='若不確定準確時辰，可先選擇大概時間（如中午12點），稍後可在問題詳述中說明。', wrap=True, size='sm', color='#666666', margin='sm'),
                            FlexButton(
                                action=DatetimePickerAction(
                                    label='📅 點此選擇生日時辰',
                                    data=picker_data,
                                    mode='datetime',
                                    min=min_date_str,
                                    max=max_date_str
                                ),
                                style='primary', color='#A67B5B', margin='lg', height='sm'
                            )
                        ])
                        alt_text='請選擇您的出生年月日時'
                    except Exception as e:
                        app.logger.error(f"Error creating datetime picker for '問事/命理': {e}")
                        reply_message = TextMessage(text="系統錯誤，無法啟動生日輸入，請稍後再試或返回主選單。")
                        follow_up_message = create_main_menu_message() # Provide menu as fallback

                else: # 法事, 收驚, 卜卦 - 進入預約時間選擇 (假設流程相似)
                    try:
                        picker_data = json.dumps({"action": "select_datetime", "service": selected_service})
                        picker_data_bytes = picker_data.encode('utf-8')
                        if len(picker_data_bytes) > 300:
                            app.logger.error(f"預約 Picker data too long ({len(picker_data_bytes)} bytes) for user {user_id}, service {selected_service}")
                            raise ValueError("Picker data too long")

                        # 預約通常選未來時間
                        min_datetime_str = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT%H:%M')

                        contents.extend([
                            FlexText(text=f'您選擇了預約：{selected_service}', weight='bold', align='center', margin='md'),
                            FlexSeparator(margin='md'),
                            FlexText(text='請選擇您希望預約的日期與時間：', align='center', margin='md', size='sm'),
                            FlexButton(
                                action=DatetimePickerAction(
                                    label='📅 選擇日期時間',
                                    data=picker_data,
                                    mode='datetime',
                                    min=min_datetime_str
                                ),
                                style='primary', color='#A67B5B', margin='lg', height='sm'
                            )
                        ])
                        alt_text=f'請選擇 {selected_service} 預約日期時間'
                    except Exception as e:
                        app.logger.error(f"Error creating datetime picker for '{selected_service}': {e}")
                        reply_message = TextMessage(text="系統錯誤，無法啟動時間選擇，請稍後再試或返回主選單。")
                        follow_up_message = create_main_menu_message()

                # --- 組合 Flex Message (如果尚未因錯誤而設定 reply_message) ---
                if not reply_message and contents:
                    if back_button:
                        contents.append(back_button) # 加入返回按鈕
                    bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents))
                    reply_message = FlexMessage(alt_text=alt_text, contents=bubble)
                elif not reply_message and not contents: # Should not happen if logic is correct
                     app.logger.error(f"No content generated for select_service: {selected_service}")
                     reply_message = TextMessage(text="處理您的請求時發生錯誤。")
                     follow_up_message = create_main_menu_message()

            else: # 沒有 selected_service
                app.logger.warning(f"Postback 'select_service' missing service data for user {user_id}. Data: {postback_data_str}")
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的服務。")
                follow_up_message = create_main_menu_message()

        # --- 處理：選擇生日日期時間後 (問事流程) ---
        elif action == 'collect_birth_info':
            selected_datetime_str = event.postback.params.get('datetime')
            service_type = postback_data.get('service', '問事/命理') # Get service type

            if selected_datetime_str:
                app.logger.info(f"User {user_id} submitted birth datetime: {selected_datetime_str} for service {service_type}")
                try:
                    # Parse datetime string (LINE returns 'YYYY-MM-DDThh:mm')
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    # Convert to Taiwan time for display and shichen calculation
                    selected_dt_tw = selected_dt.replace(tzinfo=pytz.utc).astimezone(TW_TIMEZONE) # Assume LINE sends UTC or naive, convert to TW
                    hour = selected_dt_tw.hour
                    shichen = get_shichen(hour)
                    formatted_dt_str = selected_dt_tw.strftime('%Y-%m-%d %H:%M') # Format for display

                    # 暫存資訊並設定下一步狀態: 等待選擇主題
                    user_states[user_id] = {
                        "state": "awaiting_topic_selection",
                        "data": {
                            "service": service_type,
                            "birth_info_str": selected_datetime_str, # Store original string if needed
                            "formatted_birth_info": formatted_dt_str, # Store formatted string
                            "shichen": shichen
                        }
                    }
                    app.logger.info(f"State set for user {user_id}: awaiting_topic_selection. Data: {user_states[user_id]['data']}")

                    # --- 使用 QuickReply 提示選擇問題主題 ---
                    valid_topics = ["事業", "感情", "健康", "財運", "其他"]
                    quick_reply_items = [QuickReplyButton(action=MessageAction(label=t, text=t)) for t in valid_topics]
                    # Optionally add a cancel button
                    quick_reply_items.append(QuickReplyButton(action=MessageAction(label="取消", text="取消")))

                    reply_message = TextMessage(
                        text=f"已記錄您的生日時辰：{formatted_dt_str} ({shichen}時)\n\n接下來，請選擇主要想詢問的問題主題：",
                        quick_reply=QuickReply(items=quick_reply_items)
                    )

                except ValueError as ve:
                    app.logger.error(f"Error parsing datetime string '{selected_datetime_str}' from LINE: {ve}")
                    reply_message = TextMessage(text="抱歉，無法解析您選擇的日期時間格式，請重試或返回主選單。")
                    follow_up_message = create_main_menu_message()
                except Exception as e:
                    app.logger.exception(f"Error processing birth info for user {user_id}: {e}")
                    reply_message = TextMessage(text="處理您的生日資訊時發生錯誤，請稍後再試。")
                    follow_up_message = create_main_menu_message()
            else:
                app.logger.warning(f"Postback 'collect_birth_info' missing datetime param for user {user_id}. Params: {event.postback.params}")
                reply_message = TextMessage(text="未收到您選擇的日期時間，請重試。")
                # No state change, user might retry picker

        # --- 處理：選擇預約日期時間後 (法事/收驚/卜卦流程) ---
        elif action == 'select_datetime':
            selected_datetime_str = event.postback.params.get('datetime')
            service_type = postback_data.get('service')

            if selected_datetime_str and service_type:
                app.logger.info(f"User {user_id} selected appointment datetime: {selected_datetime_str} for service: {service_type}")
                try:
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    selected_dt_tw = selected_dt.replace(tzinfo=pytz.utc).astimezone(TW_TIMEZONE) # Convert to TW time
                    formatted_dt_str = selected_dt_tw.strftime('%Y-%m-%d %H:%M')
                    selected_date = selected_dt_tw.date() # Extract date part

                    # --- 檢查老師行事曆 ---
                    available_slots_text = "老師當日行程：\n"
                    events = get_calendar_events_for_date(selected_date)
                    if events is None: # Error fetching calendar
                        available_slots_text += "無法查詢老師行程，請稍後再試或直接與老師聯繫。"
                        can_proceed = False # Assume cannot proceed if calendar fails
                    elif not events:
                        available_slots_text += "老師當日尚無安排，此時段可預約。"
                        can_proceed = True
                    else:
                        available_slots_text += "老師當日已有安排：\n"
                        for event in events:
                             start = event['start'].get('dateTime', event['start'].get('date'))
                             # Try parsing dateTime first, then date
                             try:
                                 start_dt = datetime.datetime.fromisoformat(start).astimezone(TW_TIMEZONE)
                                 event_time_str = start_dt.strftime('%H:%M')
                             except ValueError: # Handle date-only events or parse errors
                                 event_time_str = start # Use the date string
                             summary = event.get('summary', '私人行程')
                             available_slots_text += f"- {event_time_str} {summary}\n"
                        available_slots_text += "\n請確認您選擇的時間是否與老師行程衝突。"
                        # Simple check: assume conflict if any event exists. Refine if needed.
                        can_proceed = True # Allow user to confirm despite potential conflicts shown

                    # --- 通知老師 ---
                    notification_lines = [
                        f"【{service_type} 預約請求】",
                        "--------------------",
                        f"用戶ID: {user_id}",
                        f"預約項目: {service_type}",
                        f"希望時段: {formatted_dt_str}",
                        "--------------------",
                        available_slots_text # Include calendar info for teacher
                    ]
                    notification_text = "\n".join(notification_lines)
                    app.logger.info(f"準備處理預約請求:\n{notification_text}")

                    if teacher_user_id:
                        try:
                            push_text = notification_text + "\n請老師確認是否可接受此預約，並聯繫客戶。"
                            success = send_message(teacher_user_id, TextMessage(text=push_text))
                            if success: app.logger.info("預約請求通知已嘗試發送給老師。")
                            else: app.logger.error("錯誤：發送預約請求通知給老師失敗。")
                        except Exception as e:
                            app.logger.error(f"錯誤：發送預約通知給老師時發生異常: {e}")
                    else:
                        app.logger.warning("警告：未設定老師 User ID，預約請求通知僅記錄日誌。")
                        app.logger.info("日誌記錄預約請求：\n" + notification_text)

                    # --- 回覆客戶 ---
                    reply_text_to_user = (
                        f"收到您的 {service_type} 預約請求！\n"
                        f"您選擇的時段：{formatted_dt_str}\n\n"
                        f"{available_slots_text}\n" # Show teacher's schedule info
                        f"已將您的請求轉達給老師，老師確認後會與您聯繫後續事宜，謝謝！"
                    )
                    reply_message = TextMessage(text=reply_text_to_user)
                    # No state change needed here, flow ends until teacher contacts

                except ValueError as ve:
                    app.logger.error(f"Error parsing datetime string '{selected_datetime_str}' from LINE for appointment: {ve}")
                    reply_message = TextMessage(text="抱歉，無法解析您選擇的日期時間格式，請重試或返回主選單。")
                    follow_up_message = create_main_menu_message()
                except Exception as e:
                    app.logger.exception(f"Error processing appointment request for user {user_id}, service {service_type}: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
                    follow_up_message = create_main_menu_message()
            else:
                app.logger.warning(f"Postback 'select_datetime' missing params for user {user_id}. Params: {event.postback.params}, Data: {postback_data_str}")
                reply_message = TextMessage(text="未收到您選擇的日期時間或服務類型，請重試。")
                # No state change

        # --- 未知 Action ---
        else:
            app.logger.warning(f"Received unknown Postback action '{action}' from user {user_id}. Data: {postback_data_str}")
            reply_message = TextMessage(text="抱歉，無法處理您的請求。")
            follow_up_message = create_main_menu_message() # Send menu for safety

    except json.JSONDecodeError as json_err:
        app.logger.error(f"Failed to decode Postback JSON data from user {user_id}: '{postback_data_str}'. Error: {json_err}")
        reply_message = TextMessage(text="處理您的請求時發生內部錯誤 (資料格式錯誤)。")
        follow_up_message = create_main_menu_message()
    except Exception as e:
        app.logger.exception(f"Error handling Postback from user {user_id}. Data: {postback_data_str}. Error: {e}")
        reply_message = TextMessage(text="處理您的請求時發生未預期的錯誤。")
        follow_up_message = create_main_menu_message() # Send menu for safety

    # --- 發送回覆 ---
    if reply_message:
        send_message(user_id, reply_message, reply_token)
    # 如果有 follow_up_message，則在 reply 之後用 push 發送
    if follow_up_message:
        # 加一點延遲避免訊息太快？ (Optional)
        # import time; time.sleep(0.5)
        send_message(user_id, follow_up_message)


# --- 主程式入口 ---
if __name__ == "__main__":
    # 獲取 Render 分配的端口，如果沒有則預設為 5000 (本地測試用)
    port = int(os.environ.get('PORT', 5000))
    # 監聽所有網路介面，使 Render 可以訪問
    app.run(host='0.0.0.0', port=port, debug=False) # debug=False for production

請執行以下步驟：
 * 複製 上方區塊中的所有程式碼。
 * 開啟您本地的 app.py 檔案。
 * 刪除 app.py 中現有的所有內容。
 * 將您剛剛複製的程式碼 貼上 到 app.py 中。
 * 儲存 app.py 檔案。
 * 將這個修改後的 app.py 推送 (push) 到您的 GitHub 倉庫 (js0980420 / XuanTian-line-bot) 的 main 分支。
 * Render 應該會自動偵測到程式碼變更並觸發新的部署。您可以觀察 Render 儀表板上的部署日誌，確認這次是否成功啟動，以及 ImportError 是否消失。
希望這次修改能夠解決問題！
