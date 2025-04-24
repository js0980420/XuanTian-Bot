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
    DatetimePickerAction # Keep for birth info collection
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
BOT_VERSION = "v1.10.0" # Increment version for date-less booking
print(f"運行版本：{BOT_VERSION}")

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

# --- 基本設定 ---
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '') # Keep for potential future use
google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '') # Keep for potential future use
teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 環境變數檢查與日誌 ---
print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN: {'已設置' if channel_access_token else '未設置'}")
print(f"DEBUG: LINE_CHANNEL_SECRET: {'已設置' if channel_secret else '未設置'}")
# print(f"DEBUG: GOOGLE_CALENDAR_ID: {'已設置' if calendar_id else '未設置'}") # Calendar check removed from booking
# print(f"DEBUG: GOOGLE_CREDENTIALS_JSON: {'已設置' if google_credentials_json else '未設置'}") # Calendar check removed from booking
print(f"DEBUG: TEACHER_USER_ID: {teacher_user_id if teacher_user_id else '未設置'}")

if not channel_access_token or not channel_secret: app.logger.critical("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
# if not calendar_id: app.logger.warning("警告：未設定 GOOGLE_CALENDAR_ID 環境變數") # No longer strictly needed for booking
# if not google_credentials_json: app.logger.warning("警告：未設定 GOOGLE_CREDENTIALS_JSON 環境變數") # No longer strictly needed for booking
if not teacher_user_id: app.logger.warning("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

# 初始化 LINE Bot API
try:
    configuration = Configuration(access_token=channel_access_token)
    handler = WebhookHandler(channel_secret)
    print("DEBUG: LINE Bot SDK configuration and handler initialized.")
except Exception as init_err: app.logger.critical(f"Failed to initialize LINE Bot SDK: {init_err}")

# Google Calendar API 設定 (保留，以防未來需要)
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版) ---
# !!! 警告：此簡易狀態管理在 Render 等環境下可能因服務重啟或多實例而遺失狀態 !!!
user_states = {} # {user_id: {"state": "awaiting_topic_and_question", "data": {...}}}

# --- Google Calendar 輔助函數 (保留，但不再用於預約檢查) ---
# def get_google_calendar_service(): ...
# def get_calendar_events_for_date(target_date): ...

# --- 輔助函數：獲取服務說明文字 ---
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
        app.logger.warning(f"get_info_text 收到未定義的主題: {topic}")
        return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

# --- 計算時辰輔助函數 ---
def get_shichen(hour):
    # ... (程式碼同上) ...
    if not isinstance(hour, int) or hour < 0 or hour > 23: app.logger.warning(f"Invalid hour input for get_shichen: {hour}"); return "未知"
    app.logger.info(f"Calculating Shichen for input hour: {hour}")
    if hour >= 23 or hour < 1: return "子"
    if 1 <= hour < 3: return "丑"
    if 3 <= hour < 5: return "寅"
    if 5 <= hour < 7: return "卯"
    if 7 <= hour < 9: return "辰"
    if 9 <= hour < 11: return "巳"
    if 11 <= hour < 13: return "午"
    if 13 <= hour < 15: return "未"
    if 15 <= hour < 17: return "申"
    if 17 <= hour < 19: return "酉"
    if 19 <= hour < 21: return "戌"
    if 21 <= hour < 23: return "亥"
    app.logger.error(f"Logic error in get_shichen for hour: {hour}"); return "未知"

# --- 輔助函數：建立主選單 Flex Message ---
def create_main_menu_message():
    # ... (程式碼同上) ...
    buttons = []
    services = {"預約：問事/命理": {"action": "select_service", "service": "問事/命理"},"預約：法事": {"action": "select_service", "service": "法事"},"預約：收驚": {"action": "select_service", "service": "收驚"},"預約：卜卦": {"action": "select_service", "service": "卜卦"},"了解：開運物": {"action": "show_info", "topic": "開運物"},"了解：生基品": {"action": "show_info", "topic": "生基品"}}
    button_style = {'primary': '#A67B5B', 'secondary': '#BDBDBD'}
    for label, data in services.items():
        style_key = 'primary' if data['action'] == 'select_service' else 'secondary'
        postback_data_str = json.dumps(data)
        if len(postback_data_str.encode('utf-8')) <= 300:
            buttons.append(FlexButton(action=PostbackAction(label=label, data=postback_data_str, display_text=label), style=style_key, color=button_style[style_key], margin='sm', height='sm'))
        else: app.logger.warning(f"主選單按鈕 Postback data 過長 ({len(postback_data_str.encode('utf-8'))} bytes): {postback_data_str}")
    bubble = FlexBubble(header=FlexBox(layout='vertical', padding_all='md', contents=[FlexText(text='請問需要什麼服務？', weight='bold', size='lg', align='center', color='#B28E49')]), body=FlexBox(layout='vertical', spacing='sm', contents=buttons))
    return FlexMessage(alt_text='請選擇服務', contents=bubble)

# --- 輔助函數：發送訊息 (處理 Push/Reply) ---
def send_message(recipient_id, message, reply_token=None):
    # ... (程式碼同上) ...
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        message_list = [message] if not isinstance(message, list) else message
        cleaned_messages = message_list
        if reply_token:
            try:
                app.logger.info(f"Attempting Reply to {recipient_id[:10]}... (Token: {reply_token[:10]}...)")
                line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=cleaned_messages))
                app.logger.info(f"Reply successful for {recipient_id[:10]}...")
                return True
            except Exception as e_reply: app.logger.warning(f"Reply failed for {recipient_id[:10]}... (Token: {reply_token[:10]}...): {e_reply}. Attempting Push.")
        try:
            app.logger.info(f"Attempting Push to {recipient_id[:10]}...")
            line_bot_api.push_message(PushMessageRequest(to=recipient_id, messages=cleaned_messages))
            app.logger.info(f"Push successful for {recipient_id[:10]}...")
            return True
        except Exception as e_push: app.logger.error(f"Push failed for {recipient_id[:10]}...: {e_push}"); return False

# --- 輔助函數：處理預約請求 (記錄/通知 + 回覆客戶) ---
def handle_booking_request(user_id, service_name, reply_token=None):
    """處理不需要選日期的預約請求"""
    app.logger.info(f"Processing booking request for {user_id}, service: {service_name}")
    notification_base_text = (
        f"【服務請求】\n" # 改為通用標題
        f"--------------------\n"
        f"用戶ID: {user_id}\n"
        f"服務項目: {service_name}\n"
        f"--------------------"
    )
    if teacher_user_id:
        try:
            push_notification_text = notification_base_text + "\n請老師盡快確認並回覆客戶"
            send_message(teacher_user_id, TextMessage(text=push_notification_text))
            app.logger.info(f"服務請求通知已嘗試發送給老師 ({service_name})。")
        except Exception as e:
            app.logger.error(f"錯誤：發送服務請求通知給老師失敗 ({service_name}): {e}")
            app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
    else:
        app.logger.warning(f"警告：未設定老師的 User ID，服務請求通知僅記錄在日誌中 ({service_name})。")
        app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

    reply_text_to_user = (
        f"收到您的「{service_name}」服務請求！\n\n"
        f"此請求已發送給老師，將由老師為您處理後續確認事宜，感謝您的耐心等候！"
    )
    # 先用 Reply 回覆，再用 Push 發主選單
    send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)
    main_menu_message = create_main_menu_message()
    send_message(user_id, main_menu_message)

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")
    try:
        if 'handler' not in globals(): app.logger.critical("Handler not initialized!"); abort(500)
        handler.handle(body, signature)
    except InvalidSignatureError: app.logger.error("Invalid signature."); abort(400)
    except Exception as e: app.logger.exception(f"Error handling request: {e}"); abort(500)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    app.logger.info(f"User {user_id} added the bot.")
    if user_id in user_states: del user_states[user_id]
    main_menu_message = create_main_menu_message()
    send_message(user_id, main_menu_message)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token
    app.logger.info(f"Received text message from {user_id}: '{text}'")
    current_state = user_states.get(user_id, {}).get("state")

    # --- 檢查是否在命理問事流程中 ---
    if current_state == "awaiting_topic_and_question":
        state_info = user_states[user_id]; user_data = state_info["data"]
        if text.lower() in ['返回', '取消']:
             app.logger.info(f"Clearing state for user {user_id} due to '{text}' input.")
             if user_id in user_states: del user_states[user_id]
             main_menu_message = create_main_menu_message()
             send_message(user_id, main_menu_message, reply_token)
        else:
            topic_and_question = text
            user_data["topic_and_question"] = topic_and_question
            app.logger.info(f"User {user_id} provided topic and question: '{topic_and_question}'")
            birth_info_str = user_data.get("birth_info_str", "未提供"); shichen = user_data.get("shichen", "未知")
            formatted_birth_info = user_data.get("formatted_birth_info", birth_info_str)
            notification_base_text = (f"【命理問事請求】\n--------------------\n用戶ID: {user_id}\n提供生日: {formatted_birth_info}\n對應時辰: {shichen}\n主題與問題: {topic_and_question}\n--------------------")
            app.logger.info(f"準備處理命理問事請求: {notification_base_text}")
            if teacher_user_id:
                try: push_notification_text = notification_base_text + "\n請老師抽空親自回覆"; send_message(teacher_user_id, TextMessage(text=push_notification_text)); app.logger.info("命理問事通知已嘗試發送給老師。")
                except Exception as e: app.logger.error(f"錯誤：發送命理問事通知給老師失敗: {e}"); app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
            else: app.logger.warning("警告：未設定老師的 User ID..."); app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
            reply_text_to_user = f"收到您的資訊！\n生日時辰：{formatted_birth_info} ({shichen}時)\n您想詢問：{topic_and_question[:50]}{'...' if len(topic_and_question)>50 else ''}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！"
            send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)
            main_menu_message = create_main_menu_message()
            send_message(user_id, main_menu_message)
            if user_id in user_states: app.logger.info(f"Clearing state for user {user_id} after consultation info submission."); del user_states[user_id]

    # --- 如果不在特定流程中，所有其他文字訊息一律回覆主選單 ---
    else:
        app.logger.info(f"User {user_id} sent text '{text}' outside of expected flow. Replying with main menu.")
        main_menu_message = create_main_menu_message()
        send_message(user_id, main_menu_message, reply_token)


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (預約流程 + 生日收集 + 資訊顯示 + 返回)"""
    reply_message = None
    follow_up_message = None
    user_id = event.source.user_id
    app.logger.info(f"Received Postback from {user_id}")
    try:
        postback_data_str = event.postback.data
        app.logger.info(f"Postback data string: '{postback_data_str}'")
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')
        app.logger.info(f"Postback action: '{action}'")

        # --- 統一建立返回按鈕 ---
        back_button_data = json.dumps({"action": "show_main_menu"})
        back_button = None
        if len(back_button_data.encode('utf-8')) <= 300:
             back_button = FlexButton(action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'), style='secondary', height='sm', margin='xl')
        else: app.logger.error("Back button data too long!")

        # --- 處理：返回主選單 ---
        if action == 'show_main_menu':
            if user_id in user_states: app.logger.info(f"Clearing state for user {user_id} due to 'show_main_menu'."); del user_states[user_id]
            reply_message = create_main_menu_message()

        # --- 處理：選擇服務 (預約或問事) ---
        elif action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                app.logger.info(f"User {user_id} selected service: {selected_service}")
                # *** 修改處：收驚和卜卦直接處理請求 ***
                if selected_service in ["收驚", "卜卦"]:
                     handle_booking_request(user_id, selected_service) # 直接發送請求
                     # 不需要設定 reply_message 或 follow_up_message，因為 handle_booking_request 會處理
                elif selected_service == "法事":
                    # 顯示法事項目選擇
                    ritual_buttons = []
                    ritual_items = ["冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)", "三合一 (個人)", "冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)", "三合一 (祖先)"]
                    for item in ritual_items:
                        ritual_postback_data = json.dumps({"action": "select_ritual_item", "ritual": item})
                        if len(ritual_postback_data.encode('utf-8')) <= 300: ritual_buttons.append(FlexButton(action=PostbackAction(label=item, data=ritual_postback_data, display_text=f"預約法事：{item}"), style='primary', color='#A67B5B', margin='sm', height='sm'))
                        else: app.logger.warning(f"法事項目按鈕 Postback data 過長: {ritual_postback_data}")
                    contents = [FlexText(text='請選擇您想預約的法事項目：', wrap=True, size='md')]
                    contents.extend(ritual_buttons)
                    if back_button: contents.append(back_button)
                    bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents))
                    reply_message = FlexMessage(alt_text='請選擇法事項目', contents=bubble)
                elif selected_service == "問事/命理":
                    # 顯示生日選擇器
                    picker_data = json.dumps({"action": "collect_birth_info"})
                    if len(picker_data.encode('utf-8')) > 300: app.logger.error(f"問事/命理 Picker data too long for user {user_id}"); reply_message = TextMessage(text="系統錯誤..."); follow_up_message = create_main_menu_message()
                    else:
                        min_date = "1920-01-01T00:00"; max_date = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT%H:%M')
                        contents = [FlexText(text='進行命理分析需要您的出生年月日時。', wrap=True, size='md'), FlexText(text='若不確定準確時辰...', wrap=True, size='sm', color='#666666', margin='sm'), FlexButton(action=DatetimePickerAction(label='📅 點此選擇生日時辰', data=picker_data, mode='datetime', min=min_date, max=max_date), style='primary', color='#A67B5B', margin='lg')]
                        if back_button: contents.append(back_button)
                        bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents))
                        reply_message = FlexMessage(alt_text='請選擇您的出生年月日時', contents=bubble)
            else: app.logger.warning(f"Postback 'select_service' missing service for user {user_id}"); reply_message = TextMessage(text="發生錯誤..."); follow_up_message = create_main_menu_message()

        # *** 修改處：處理選擇具體法事項目後 ***
        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            if selected_ritual:
                app.logger.info(f"User {user_id} selected ritual item: {selected_ritual}")
                # 檢查是否為 4 月
                current_month = datetime.date.today().month
                if current_month == 4:
                    app.logger.info(f"Ritual booking blocked for {user_id} (April)")
                    reply_message = TextMessage(text=f"抱歉，{datetime.date.today().year}年4月老師在大陸，期間無法進行法事，請下個月再預約，謝謝。")
                    follow_up_message = create_main_menu_message()
                else:
                    # 非 4 月，直接處理請求
                    handle_booking_request(user_id, selected_ritual) # 使用具體法事名稱
            else:
                app.logger.warning(f"Postback 'select_ritual_item' missing ritual for user {user_id}")
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的法事項目。")
                follow_up_message = create_main_menu_message()

        # --- 處理：選擇生日日期時間後 (問事流程) ---
        elif action == 'collect_birth_info':
            selected_datetime_str = event.postback.params.get('datetime')
            if selected_datetime_str:
                app.logger.info(f"User {user_id} submitted birth datetime: {selected_datetime_str}")
                try:
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str); hour = selected_dt.hour; shichen = get_shichen(hour); formatted_dt = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')
                    user_states[user_id] = {"state": "awaiting_topic_and_question", "data": {"birth_info_str": selected_datetime_str, "formatted_birth_info": formatted_dt, "shichen": shichen}}
                    app.logger.info(f"State set for user {user_id}: awaiting_topic_and_question")
                    reply_message = TextMessage(text=f"收到您的生日時辰：{formatted_dt} ({shichen}時)\n請接著**一次輸入**您想問的主題和具體問題/情況：\n（例如：事業 最近工作上遇到瓶頸，該如何突破？）\n（若想返回主選單請直接輸入「返回」或「取消」）")
                except ValueError: app.logger.error(f"Failed to parse birth datetime for user {user_id}: {selected_datetime_str}"); reply_message = TextMessage(text="日期時間格式有誤..."); follow_up_message = create_main_menu_message()
                except Exception as e: app.logger.exception(f"Error processing birth info for user {user_id}: {e}"); reply_message = TextMessage(text="處理生日資訊錯誤..."); follow_up_message = create_main_menu_message()
            else: app.logger.warning(f"Postback 'collect_birth_info' missing datetime for user {user_id}"); reply_message = TextMessage(text="未收到生日時間..."); follow_up_message = create_main_menu_message()

        # --- 處理：選擇預約日期時間後 (僅用於收驚/卜卦，法事已在 select_ritual_item 處理) ---
        elif action == 'select_datetime':
            selected_service = postback_data.get('service') # 應該只會是 收驚 或 卜卦
            selected_datetime_str = event.postback.params.get('datetime') # 雖然選了，但不用
            if selected_service and selected_datetime_str:
                 app.logger.info(f"User {user_id} selected datetime for service '{selected_service}' (datetime ignored)")
                 # 直接處理請求，忽略選擇的時間
                 handle_booking_request(user_id, selected_service)
            else:
                 app.logger.warning(f"Postback 'select_datetime' missing data for user {user_id}")
                 reply_message = TextMessage(text="缺少預約資訊...")
                 follow_up_message = create_main_menu_message()

        # --- 處理 show_info Action ---
        elif action == 'show_info':
            topic = postback_data.get('topic')
            if topic:
                 app.logger.info(f"User {user_id} requested info for topic: {topic}")
                 info_text = get_info_text(topic)
                 contents = [FlexText(text=info_text, wrap=True)]
                 if back_button: contents.append(back_button)
                 bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents))
                 reply_message = FlexMessage(alt_text=f"關於 {topic} 的說明", contents=bubble)
            else: app.logger.warning(f"Postback 'show_info' missing topic for user {user_id}"); reply_message = TextMessage(text="無法識別資訊..."); follow_up_message = create_main_menu_message()

        else: # 未知 action
            app.logger.warning(f"Received unknown Postback Action from {user_id}: {action}")
            reply_message = create_main_menu_message()

    except json.JSONDecodeError: app.logger.error(f"Failed to parse Postback data from {user_id}: {postback_data_str}"); reply_message = TextMessage(text="系統無法處理請求..."); follow_up_message = create_main_menu_message()
    except Exception as e: app.logger.exception(f"Error processing Postback from {user_id}: {e}"); reply_message = TextMessage(text="系統發生錯誤..."); follow_up_message = create_main_menu_message()

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
