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
# from googleapiclient.discovery import build # No longer needed for booking checks
import pytz

# --- 加入版本標記 ---
BOT_VERSION = "v1.12.0" # Increment version for multi-select ritual booking
print(f"運行版本：{BOT_VERSION}")

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

# --- 基本設定 ---
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
# calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '') # Keep for potential future use
# google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '') # Keep for potential future use
teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 服務費用設定 (更新版) ---
SERVICE_FEES = {
    "冤親債主 (個人)": 680,
    "補桃花 (個人)": 680,
    "補財庫 (個人)": 680,
    "三合一 (個人)": 1800, # 冤親+桃花+財庫 (個人)
    "冤親債主 (祖先)": 1800,
    "補桃花 (祖先)": 1800,
    "補財庫 (祖先)": 1800,
    "三合一 (祖先)": 5400, # 假設 1800 * 3，如果價格不同請修改此處
    "問事/命理": "請私訊老師洽詢",
    "收驚": "請私訊老師洽詢",
    "卜卦": "請私訊老師洽詢",
}
# 定義三合一組合內容，用於計算優惠
PERSONAL_BUNDLE_ITEMS = {"冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)"}
ANCESTOR_BUNDLE_ITEMS = {"冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)"}
PERSONAL_BUNDLE_NAME = "三合一 (個人)"
ANCESTOR_BUNDLE_NAME = "三合一 (祖先)"


# --- 匯款資訊 ---
BANK_INFO = "🌟 匯款帳號：\n銀行：822 中國信託\n帳號：510540490990"

# --- 環境變數檢查與日誌 ---
print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN: {'已設置' if channel_access_token else '未設置'}")
print(f"DEBUG: LINE_CHANNEL_SECRET: {'已設置' if channel_secret else '未設置'}")
print(f"DEBUG: TEACHER_USER_ID: {teacher_user_id if teacher_user_id else '未設置'}")

if not channel_access_token or not channel_secret: app.logger.critical("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
if not teacher_user_id: app.logger.warning("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

# 初始化 LINE Bot API
try:
    configuration = Configuration(access_token=channel_access_token)
    handler = WebhookHandler(channel_secret)
    print("DEBUG: LINE Bot SDK configuration and handler initialized.")
except Exception as init_err: app.logger.critical(f"Failed to initialize LINE Bot SDK: {init_err}")

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版) ---
# !!! 警告：此簡易狀態管理在 Render 等環境下可能因服務重啟或多實例而遺失狀態 !!!
user_states = {} # {user_id: {"state": "...", "data": {...}}}

# --- Google Calendar 輔助函數 (保留) ---
# def get_google_calendar_service(): ...
# def get_calendar_events_for_date(target_date): ...

# --- 輔助函數：獲取服務說明文字 ---
def get_info_text(topic):
    # ... (程式碼同上) ...
    current_year = datetime.date.today().year
    if topic == '開運物': return ("【開運物品】\n提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n如有特定需求或想預購，歡迎私訊老師。")
    elif topic == '生基品': return ("【生基用品】\n生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n老師提供相關諮詢與必需品代尋服務。\n如有興趣或需求，歡迎私訊老師洽詢。")
    else: app.logger.warning(f"get_info_text 收到未定義的主題: {topic}"); return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

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
# *** 修改：此函數現在處理非數字價格的服務，或法事總結 ***
def handle_booking_request(user_id, service_name_or_list, total_price=None, reply_token=None):
    """處理預約請求，包括單項非數字價格服務和多項法事總結"""
    app.logger.info(f"Handling booking request for {user_id}")

    is_ritual_summary = isinstance(service_name_or_list, list)
    service_display = ""
    price_display = ""
    log_service = "" # For logging purposes

    if is_ritual_summary:
        service_display = "\n".join([f"- {item}" for item in service_name_or_list]) if service_name_or_list else "未選擇項目"
        price_display = f"NT${total_price}" if total_price is not None else "計算錯誤"
        log_service = f"法事組合 ({len(service_name_or_list)}項)"
    else: # 單項服務 (問事/收驚/卜卦)
        service_display = service_name_or_list
        price_display = SERVICE_FEES.get(service_name_or_list, "價格請洽老師")
        log_service = service_name_or_list

    notification_base_text = (
        f"【服務請求】\n"
        f"--------------------\n"
        f"用戶ID: {user_id}\n"
        f"服務項目:\n{service_display}\n"
        f"費用: {price_display}\n"
        f"--------------------"
    )

    # --- 通知老師 ---
    if teacher_user_id:
        try:
            push_notification_text = notification_base_text + "\n請老師確認並處理後續事宜。"
            send_message(teacher_user_id, TextMessage(text=push_notification_text))
            app.logger.info(f"服務請求通知已嘗試發送給老師 ({log_service})。")
        except Exception as e:
            app.logger.error(f"錯誤：發送服務請求通知給老師失敗 ({log_service}): {e}")
            app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
    else:
        app.logger.warning(f"警告：未設定老師的 User ID，服務請求通知僅記錄在日誌中 ({log_service})。")
        app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")

    # --- 回覆客戶 ---
    if is_ritual_summary: # 法事總結回覆
        if not service_name_or_list: # 防呆：如果列表是空的
             reply_text_to_user = "您尚未選擇任何法事項目。請重新操作。"
        else:
            reply_text_to_user = f"您已選擇以下法事項目：\n{service_display}\n\n"
            reply_text_to_user += f"總費用：{price_display}\n\n"
            reply_text_to_user += "法事將於下個月由老師擇日統一進行。\n"
            reply_text_to_user += "請您完成匯款後告知末五碼，以便老師為您安排：\n"
            reply_text_to_user += f"{BANK_INFO}\n\n"
            reply_text_to_user += "感謝您的預約！"
    else: # 非法事服務回覆
        reply_text_to_user = f"收到您的「{service_display}」服務請求！\n\n"
        reply_text_to_user += f"費用：{price_display}\n\n"
        reply_text_to_user += "此請求已發送給老師，將由老師為您處理後續確認與報價事宜，感謝您的耐心等候！"

    send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)
    main_menu_message = create_main_menu_message()
    send_message(user_id, main_menu_message) # 顯示主選單

# --- 輔助函數：計算總價 (處理三合一) ---
def calculate_total_price(selected_items):
    """計算選擇的法事項目總價，處理三合一優惠"""
    total_price = 0
    # 使用 set 方便操作，但要保留原始順序或類型以便顯示
    current_selection_set = set(selected_items)
    final_items_to_display = [] # 最終顯示給用戶的項目列表

    # 優先處理組合優惠
    personal_bundle_applied = False
    if PERSONAL_BUNDLE_ITEMS.issubset(current_selection_set):
        app.logger.info("Applying personal bundle discount.")
        total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0)
        final_items_to_display.append(PERSONAL_BUNDLE_NAME)
        current_selection_set -= PERSONAL_BUNDLE_ITEMS # 從待計算集合中移除
        personal_bundle_applied = True

    ancestor_bundle_applied = False
    if ANCESTOR_BUNDLE_ITEMS.issubset(current_selection_set):
        app.logger.info("Applying ancestor bundle discount.")
        total_price += SERVICE_FEES.get(ANCESTOR_BUNDLE_NAME, 0)
        final_items_to_display.append(ANCESTOR_BUNDLE_NAME)
        current_selection_set -= ANCESTOR_BUNDLE_ITEMS # 從待計算集合中移除
        ancestor_bundle_applied = True

    # 檢查是否單獨選了三合一 (如果上面組合已處理，這裡就不會再加)
    if PERSONAL_BUNDLE_NAME in current_selection_set and not personal_bundle_applied:
        app.logger.info("Adding individual personal bundle price.")
        total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0)
        final_items_to_display.append(PERSONAL_BUNDLE_NAME)
        current_selection_set.discard(PERSONAL_BUNDLE_NAME)

    if ANCESTOR_BUNDLE_NAME in current_selection_set and not ancestor_bundle_applied:
        app.logger.info("Adding individual ancestor bundle price.")
        total_price += SERVICE_FEES.get(ANCESTOR_BUNDLE_NAME, 0)
        final_items_to_display.append(ANCESTOR_BUNDLE_NAME)
        current_selection_set.discard(ANCESTOR_BUNDLE_NAME)


    # 計算剩餘單項價格
    for item in current_selection_set:
        price = SERVICE_FEES.get(item)
        if isinstance(price, int):
            total_price += price
            final_items_to_display.append(item) # 加入單項到顯示列表
        else:
            app.logger.warning(f"Item '{item}' has non-integer price, skipping in total calculation.")

    app.logger.info(f"Calculated total price: {total_price} for display items: {final_items_to_display}")
    return total_price, final_items_to_display


# --- 輔助函數：建立法事選擇 Flex Message ---
def create_ritual_selection_message(user_id):
    """建立法事項目選擇的 Flex Message"""
    buttons = []
    ritual_items = [
        "冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)", "三合一 (個人)",
        "冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)", "三合一 (祖先)"
    ]
    # 獲取用戶當前已選項目
    current_selection = user_states.get(user_id, {}).get("data", {}).get("selected_rituals", [])

    # 建立項目按鈕
    for item in ritual_items:
        price = SERVICE_FEES.get(item, "洽詢")
        label_with_price = f"{item} (NT${price})" if isinstance(price, int) else f"{item} ({price})"
        is_selected = item in current_selection
        # *** 修改處：按鈕標籤顯示是否已選 ***
        button_label = f"✅ {label_with_price}" if is_selected else label_with_price
        button_style = 'secondary' if is_selected else 'primary' # 已選用次要樣式

        ritual_postback_data = json.dumps({"action": "select_ritual_item", "ritual": item})
        if len(ritual_postback_data.encode('utf-8')) <= 300:
            buttons.append(FlexButton(action=PostbackAction(label=button_label, data=ritual_postback_data, display_text=f"選擇法事：{item}"), style=button_style, color='#A67B5B' if not is_selected else '#DDDDDD', margin='sm', height='sm'))
        else: app.logger.warning(f"法事項目按鈕 Postback data 過長: {ritual_postback_data}")

    # 建立完成選擇按鈕
    confirm_data = json.dumps({"action": "confirm_rituals"})
    if len(confirm_data.encode('utf-8')) <= 300:
        buttons.append(FlexButton(action=PostbackAction(label='完成選擇，計算總價', data=confirm_data, display_text='完成選擇'), style='primary', color='#4CAF50', margin='lg', height='sm'))

    # 建立返回按鈕
    back_button_data = json.dumps({"action": "show_main_menu"})
    if len(back_button_data.encode('utf-8')) <= 300:
         buttons.append(FlexButton(action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'), style='secondary', height='sm', margin='md'))
    else: app.logger.error("Back button data too long for ritual selection!")

    # 顯示已選項目
    selected_text = "您目前已選擇：\n" + "\n".join(f"- {r}" for r in current_selection) if current_selection else "請點擊下方按鈕選擇法事項目："

    bubble = FlexBubble(
        header=FlexBox(layout='vertical', contents=[FlexText(text='預約法事', weight='bold', size='lg', align='center', color='#B28E49')]),
        body=FlexBox(layout='vertical', spacing='md', contents=[
            FlexText(text=selected_text, wrap=True, size='sm', margin='md'),
            FlexSeparator(margin='lg'),
            *buttons # 將按鈕列表展開
        ])
    )
    return FlexMessage(alt_text='請選擇法事項目', contents=bubble)


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
    welcome_text = "宇宙玄天院 歡迎您！\n感謝您加入好友！我是您的命理小幫手。\n點擊下方按鈕選擇服務或了解詳情："
    main_menu_message = create_main_menu_message()
    send_message(user_id, [TextMessage(text=welcome_text), main_menu_message])

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
            price = SERVICE_FEES.get("問事/命理", "請私訊老師洽詢")
            notification_base_text = (f"【命理問事請求】\n--------------------\n用戶ID: {user_id}\n提供生日: {formatted_birth_info}\n對應時辰: {shichen}\n主題與問題: {topic_and_question}\n費用: {price}\n--------------------")
            app.logger.info(f"準備處理命理問事請求: {notification_base_text}")
            if teacher_user_id:
                try: push_notification_text = notification_base_text + "\n請老師抽空親自回覆"; send_message(teacher_user_id, TextMessage(text=push_notification_text)); app.logger.info("命理問事通知已嘗試發送給老師。")
                except Exception as e: app.logger.error(f"錯誤：發送命理問事通知給老師失敗: {e}"); app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
            else: app.logger.warning("警告：未設定老師的 User ID..."); app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
            reply_text_to_user = f"收到您的資訊！\n生日時辰：{formatted_birth_info} ({shichen}時)\n您想詢問：{topic_and_question[:50]}{'...' if len(topic_and_question)>50 else ''}\n費用：{price}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！"
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
                if selected_service in ["收驚", "卜卦"]:
                     handle_booking_request(user_id, selected_service)
                elif selected_service == "法事":
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
                    app.logger.info(f"State set for user {user_id}: selecting_rituals")
                    reply_message = create_ritual_selection_message(user_id)
                elif selected_service == "問事/命理":
                    picker_data = json.dumps({"action": "collect_birth_info"})
                    if len(picker_data.encode('utf-8')) > 300: app.logger.error(f"問事/命理 Picker data too long for user {user_id}"); reply_message = TextMessage(text="系統錯誤..."); follow_up_message = create_main_menu_message()
                    else:
                        min_date = "1920-01-01T00:00"; max_date = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%dT%H:%M')
                        contents = [FlexText(text='進行命理分析需要您的出生年月日時。', wrap=True, size='md'), FlexText(text='若不確定準確時辰...', wrap=True, size='sm', color='#666666', margin='sm'), FlexButton(action=DatetimePickerAction(label='📅 點此選擇生日時辰', data=picker_data, mode='datetime', min=min_date, max=max_date), style='primary', color='#A67B5B', margin='lg')]
                        if back_button: contents.append(back_button)
                        bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents))
                        reply_message = FlexMessage(alt_text='請選擇您的出生年月日時', contents=bubble)
            else: app.logger.warning(f"Postback 'select_service' missing service for user {user_id}"); reply_message = TextMessage(text="發生錯誤..."); follow_up_message = create_main_menu_message()

        # *** 修改處：處理選擇具體法事項目後 (加入購物車邏輯) ***
        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            if selected_ritual:
                app.logger.info(f"User {user_id} toggled ritual item: {selected_ritual}")
                if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals":
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": [selected_ritual]}}
                    app.logger.warning(f"User {user_id} was not in selecting_rituals state, resetting.")
                else:
                    current_selection = user_states[user_id]["data"]["selected_rituals"]
                    if selected_ritual in current_selection:
                         current_selection.remove(selected_ritual)
                         app.logger.info(f"Removed '{selected_ritual}' from selection for {user_id}")
                    else:
                         current_selection.append(selected_ritual)
                         app.logger.info(f"Added '{selected_ritual}' to selection for {user_id}")
                # 重新顯示選擇畫面
                reply_message = create_ritual_selection_message(user_id)
            else:
                app.logger.warning(f"Postback 'select_ritual_item' missing ritual for user {user_id}")
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的法事項目。")
                follow_up_message = create_main_menu_message()

        # *** 新增：處理完成法事選擇 ***
        elif action == 'confirm_rituals':
             if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                 selected_rituals = user_states[user_id].get("data", {}).get("selected_rituals", [])
                 app.logger.info(f"User {user_id} confirmed rituals: {selected_rituals}")
                 if not selected_rituals:
                     reply_message = TextMessage(text="您尚未選擇任何法事項目，請選擇後再點擊完成。")
                     selection_menu = create_ritual_selection_message(user_id)
                     messages_to_send = [reply_message, selection_menu]
                     send_message(user_id, messages_to_send)
                     reply_message = None # 清除 reply_message
                 else:
                     total_price, final_item_list = calculate_total_price(selected_rituals)
                     handle_booking_request(user_id, final_item_list, total_price) # 傳遞列表和總價
                     del user_states[user_id] # 清除狀態
             else:
                 app.logger.warning(f"User {user_id} clicked confirm_rituals but not in correct state.")
                 reply_message = create_main_menu_message()

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

        # --- 處理：選擇預約日期時間後 (此路徑理論上不再使用) ---
        elif action == 'select_datetime':
             selected_service = postback_data.get('service')
             app.logger.warning(f"Unexpected 'select_datetime' action for service: {selected_service}. Handling as direct booking.")
             if selected_service: handle_booking_request(user_id, selected_service)
             else: app.logger.error(f"Postback 'select_datetime' missing service for user {user_id}"); reply_message = TextMessage(text="發生錯誤..."); follow_up_message = create_main_menu_message()

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
    if reply_message:
        if isinstance(reply_message, list): messages_to_send.extend(reply_message)
        else: messages_to_send.append(reply_message)
    if follow_up_message: messages_to_send.append(follow_up_message)
    if messages_to_send: send_message(user_id, messages_to_send)


# --- 主程式入口 ---
if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.run(host='0.0.0.0', port=port, debug=False)
