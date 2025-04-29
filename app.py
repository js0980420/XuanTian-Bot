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
from linebot.v3.exceptions import InvalidSignatureError # Import InvalidSignatureError
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
    MessageAction,  # Keep for main menu and return button
    URIAction,      # For IG link
    PostbackAction, # For ritual selection and date picker
    DatetimePickerAction, # Keep for birth info collection
    TemplateMessage,
    ButtonsTemplate,
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
BOT_VERSION = "v1.14.0" # Increment version for reverting main menu
print(f"運行版本：{BOT_VERSION}")

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

# --- 基本設定 ---
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
#teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 服務費用設定 ---
SERVICE_FEES = {
    "冤親債主 (個人)": 680, "補桃花 (個人)": 680, "補財庫 (個人)": 680,
    "三合一 (個人)": 1800,
    "冤親債主 (祖先)": 1800, "補桃花 (祖先)": 1800, "補財庫 (祖先)": 1800,
    "三合一 (祖先)": 5400,
    "問事/命理": "請私訊老師洽詢", "收驚": "請私訊老師洽詢", "卜卦": "請私訊老師洽詢",
}
# 定義三合一組合內容
PERSONAL_BUNDLE_ITEMS = {"冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)"}
ANCESTOR_BUNDLE_ITEMS = {"冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)"}
PERSONAL_BUNDLE_NAME = "三合一 (個人)"
ANCESTOR_BUNDLE_NAME = "三合一 (祖先)"

# --- 匯款資訊 ---
BANK_INFO = "🌟 匯款帳號：\n銀行：822 中國信託\n帳號：510540490990"

# --- 主要服務列表 (用於 Flex Message 顯示) ---
main_services_list = [
    "命理諮詢（數字易經、八字、問事）",
    "風水勘察與調理",
    "補財庫、煙供、生基、安斗等客製化法會儀軌",
    "點燈祈福、開運蠟燭",
    "命理課程與法術課程"
]

# --- 其他服務/連結 ---
ig_link = "https://www.instagram.com/magic_momo9/" # 請確認連結正確
other_services_keywords = {
    "開運物": "關於開運物，詳細資訊待更新，請稍後關注。",
    "課程": "關於命理與法術課程，詳細資訊待更新，請稍後關注。",
    "IG": f"追蹤我們的 Instagram：{ig_link}"
    # 可以加入更多關鍵字對應的文字
}

# --- 如何預約說明 ---
how_to_book_instructions = """【如何預約】
您可以透過點擊主選單上的按鈕來啟動預約流程：
- **問事**：將引導您輸入生日時辰與問題。
- **法事**：將讓您選擇具體的法事項目。
- **收驚 / 卜卦**：將直接記錄您的請求，老師會與您聯繫。
- **其他服務**：請直接私訊老師洽詢。

對於「問事/命理」諮詢，老師通常會在收到您的完整問題後的三天內回覆，感謝您的耐心等候！"""


# --- 環境變數檢查與日誌 ---
print(f"DEBUG: LINE_CHANNEL_ACCESS_TOKEN: {'已設置' if channel_access_token else '未設置'}")
print(f"DEBUG: LINE_CHANNEL_SECRET: {'已設置' if channel_secret else '未設置'}")
print(f"DEBUG: TEACHER_USER_ID: {teacher_user_id if teacher_user_id else '未設置'}")
if not channel_access_token or not channel_secret: app.logger.critical("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
if not teacher_user_id: app.logger.warning("警告：未設定 TEACHER_USER_ID 環境變數，預約/問事通知將僅記錄在日誌中。")

# 初始化 LINE Bot API
handler = None
try:
    configuration = Configuration(access_token=channel_access_token)
    if channel_secret:
        handler = WebhookHandler(channel_secret)
        print("DEBUG: LINE Bot SDK configuration and handler initialized.")
    else:
        app.logger.critical("錯誤：LINE_CHANNEL_SECRET 未設定，無法初始化 Webhook Handler。")
except Exception as init_err: app.logger.critical(f"Failed to initialize LINE Bot SDK: {init_err}")

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- 狀態管理 (簡易版) ---
user_states = {} # {user_id: {"state": "...", "data": {...}}}

# --- 輔助函數：獲取服務說明文字 ---
def get_info_text(topic):
    if topic == '開運物': return ("【開運物品】\n提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等...\n如有特定需求或想預購，歡迎私訊老師。")
    elif topic == '課程': return ("【課程介紹】\n我們提供命理與法術相關課程...\n詳情請洽詢...") # 範例文字
    else: app.logger.warning(f"get_info_text 收到未定義的主題: {topic}"); return "抱歉，目前沒有關於「"+topic+"」的詳細說明。"

# --- 計算時辰輔助函數 ---
def get_shichen(hour):
    if not isinstance(hour, int) or hour < 0 or hour > 23: app.logger.warning(f"Invalid hour input: {hour}"); return "未知"
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

# --- 輔助函數：建立主選單 Flex Message (新版按鈕) ---
def create_main_menu_message():
    """建立符合圖片樣式的主選單 Flex Message"""
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[FlexText(text='宇宙玄天院 主要服務項目', weight='bold', size='xl', color='#5A3D1E', align='center')]
        ),
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='我們提供以下服務，助您開啟靈性覺醒：', wrap=True, size='sm', color='#333333'),
                FlexSeparator(margin='md'),
                *[FlexText(text=f'• {service}', wrap=True, size='sm', margin='sm') for service in main_services_list]
            ]
        ),
        footer=FlexBox(
            layout='vertical',
            spacing='sm',
            contents=[
                FlexButton(action=MessageAction(label='如何預約', text='如何預約'), style='primary', color='#8C6F4E', height='sm'),
                FlexButton(action=MessageAction(label='問事', text='問事'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='法事', text='法事'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=URIAction(label='IG', uri=ig_link), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='開運物', text='開運物'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='課程', text='課程'), style='secondary', color='#EFEBE4', height='sm')
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='主要服務項目', contents=bubble)

# --- 輔助函數：發送訊息 (處理 Push/Reply) ---
def send_message(recipient_id, message, reply_token=None):
    # ... (程式碼同上) ...
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        message_list = [message] if not isinstance(message, list) else message
        cleaned_messages = message_list
        if reply_token:
            try: app.logger.info(f"Attempting Reply to {recipient_id[:10]}..."); line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=cleaned_messages)); app.logger.info(f"Reply successful for {recipient_id[:10]}..."); return True
            except Exception as e_reply: app.logger.warning(f"Reply failed for {recipient_id[:10]}...: {e_reply}. Attempting Push.")
        try: app.logger.info(f"Attempting Push to {recipient_id[:10]}..."); line_bot_api.push_message(PushMessageRequest(to=recipient_id, messages=cleaned_messages)); app.logger.info(f"Push successful for {recipient_id[:10]}..."); return True
        except Exception as e_push: app.logger.error(f"Push failed for {recipient_id[:10]}...: {e_push}"); return False

# --- 輔助函數：處理預約請求 (記錄/通知 + 回覆客戶) ---
def handle_booking_request(user_id, service_name_or_list, total_price=None, reply_token=None):
    # ... (程式碼同上) ...
    app.logger.info(f"Handling booking request for {user_id}")
    is_ritual_summary = isinstance(service_name_or_list, list); service_display = ""; price_display = ""; log_service = ""
    if is_ritual_summary: service_display = "\n".join([f"- {item}" for item in service_name_or_list]) if service_name_or_list else "未選擇項目"; price_display = f"NT${total_price}" if total_price is not None else "計算錯誤"; log_service = f"法事組合 ({len(service_name_or_list)}項)"
    else: service_display = service_name_or_list; price_display = SERVICE_FEES.get(service_name_or_list, "價格請洽老師"); log_service = service_name_or_list
    notification_base_text = (f"【服務請求】\n--------------------\n用戶ID: {user_id}\n服務項目:\n{service_display}\n費用: {price_display}\n--------------------")
    else: app.logger.warning(f"警告：未設定老師的 User ID..."); app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
    if is_ritual_summary:
        if not service_name_or_list: reply_text_to_user = "您尚未選擇任何法事項目。請重新操作。"
        else: reply_text_to_user = f"您已選擇以下法事項目：\n{service_display}\n\n總費用：{price_display}\n\n法事將於下個月由老師擇日統一進行。\n請您完成匯款後告知末五碼，以便老師為您安排：\n{BANK_INFO}\n\n感謝您的預約！"
    else: reply_text_to_user = f"收到您的「{service_display}」服務請求！\n\n費用：{price_display}\n\n此請求已發送給老師，將由老師為您處理後續確認與報價事宜，感謝您的耐心等候！"
    send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)
    main_menu_message = create_main_menu_message(); send_message(user_id, main_menu_message)

# --- 輔助函數：計算總價 (處理三合一) ---
def calculate_total_price(selected_items):
    # ... (程式碼同上) ...
    total_price = 0; current_selection_set = set(selected_items); final_items_to_display = []
    personal_bundle_applied = False
    if PERSONAL_BUNDLE_ITEMS.issubset(current_selection_set): app.logger.info("Applying personal bundle discount."); total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0); final_items_to_display.append(PERSONAL_BUNDLE_NAME); current_selection_set -= PERSONAL_BUNDLE_ITEMS; personal_bundle_applied = True
    ancestor_bundle_applied = False
    if ANCESTOR_BUNDLE_ITEMS.issubset(current_selection_set): app.logger.info("Applying ancestor bundle discount."); total_price += SERVICE_FEES.get(ANCESTOR_BUNDLE_NAME, 0); final_items_to_display.append(ANCESTOR_BUNDLE_NAME); current_selection_set -= ANCESTOR_BUNDLE_ITEMS; ancestor_bundle_applied = True
    if PERSONAL_BUNDLE_NAME in current_selection_set and not personal_bundle_applied: app.logger.info("Adding individual personal bundle price."); total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0); final_items_to_display.append(PERSONAL_BUNDLE_NAME); current_selection_set.discard(PERSONAL_BUNDLE_NAME)
    if ANCESTOR_BUNDLE_NAME in current_selection_set and not ancestor_bundle_applied: app.logger.info("Adding individual ancestor bundle price."); total_price += SERVICE_FEES.get(ANCESTOR_BUNDLE_NAME, 0); final_items_to_display.append(ANCESTOR_BUNDLE_NAME); current_selection_set.discard(ANCESTOR_BUNDLE_NAME)
    for item in current_selection_set:
        price = SERVICE_FEES.get(item)
        if isinstance(price, int): total_price += price; final_items_to_display.append(item)
        else: app.logger.warning(f"Item '{item}' has non-integer price, skipping.")
    app.logger.info(f"Calculated total price: {total_price} for display items: {final_items_to_display}")
    return total_price, final_items_to_display

# --- 輔助函數：建立法事選擇 Flex Message ---
def create_ritual_selection_message(user_id):
    # ... (程式碼同上) ...
    buttons = []; ritual_items = ["冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)", "三合一 (個人)", "冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)", "三合一 (祖先)"]
    current_selection = user_states.get(user_id, {}).get("data", {}).get("selected_rituals", [])
    for item in ritual_items:
        price = SERVICE_FEES.get(item, "洽詢"); label_with_price = f"{item} (NT${price})" if isinstance(price, int) else f"{item} ({price})"
        is_selected = item in current_selection; button_label = f"✅ {label_with_price}" if is_selected else label_with_price; button_style = 'secondary' if is_selected else 'primary'
        ritual_postback_data = json.dumps({"action": "select_ritual_item", "ritual": item})
        if len(ritual_postback_data.encode('utf-8')) <= 300: buttons.append(FlexButton(action=PostbackAction(label=button_label, data=ritual_postback_data, display_text=f"選擇法事：{item}"), style=button_style, color='#A67B5B' if not is_selected else '#DDDDDD', margin='sm', height='sm'))
        else: app.logger.warning(f"法事項目按鈕 Postback data 過長: {ritual_postback_data}")
    confirm_data = json.dumps({"action": "confirm_rituals"})
    if len(confirm_data.encode('utf-8')) <= 300: buttons.append(FlexButton(action=PostbackAction(label='完成選擇，計算總價', data=confirm_data, display_text='完成選擇'), style='primary', color='#4CAF50', margin='lg', height='sm'))
    back_button_data = json.dumps({"action": "show_main_menu"})
    if len(back_button_data.encode('utf-8')) <= 300: buttons.append(FlexButton(action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'), style='secondary', height='sm', margin='md'))
    else: app.logger.error("Back button data too long for ritual selection!")
    selected_text = "您目前已選擇：\n" + "\n".join(f"- {r}" for r in current_selection) if current_selection else "請點擊下方按鈕選擇法事項目："
    bubble = FlexBubble(header=FlexBox(layout='vertical', contents=[FlexText(text='預約法事', weight='bold', size='lg', align='center', color='#B28E49')]), body=FlexBox(layout='vertical', spacing='md', contents=[FlexText(text=selected_text, wrap=True, size='sm', margin='md'), FlexSeparator(margin='lg'), *buttons]))
    return FlexMessage(alt_text='請選擇法事項目', contents=bubble)

# --- 輔助函數：建立返回主選單按鈕的 Action ---
def create_return_to_menu_action():
    """產生返回主選單的 MessageAction"""
    return MessageAction(label='返回主選單', text='服務項目') # 觸發文字 "服務項目"

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    if handler is None: app.logger.critical("Webhook handler is not initialized."); abort(500)
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")
    try: handler.handle(body, signature)
    except InvalidSignatureError: app.logger.error("Invalid signature."); abort(400)
    except Exception as e: app.logger.exception(f"Error handling request: {e}"); abort(500)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id; app.logger.info(f"User {user_id} added the bot.")
    if user_id in user_states: del user_states[user_id]
    welcome_text = "宇宙玄天院 歡迎您！\n感謝您加入好友！我是您的命理小幫手。\n點擊下方按鈕選擇服務或了解詳情："
    main_menu_message = create_main_menu_message()
    send_message(user_id, [TextMessage(text=welcome_text), main_menu_message])

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    user_id = event.source.user_id; text = event.message.text.strip(); reply_token = event.reply_token
    app.logger.info(f"Received text message from {user_id}: '{text}'")
    current_state = user_states.get(user_id, {}).get("state")
    text_lower = text.lower()
    reply_content = None # 初始化回覆內容

    # --- 檢查是否在命理問事流程中 ---
    if current_state == "awaiting_topic_and_question":
        state_info = user_states[user_id]; user_data = state_info["data"]
        if text_lower in ['返回', '取消', '服務項目']: # 加入 "服務項目" 作為取消關鍵字
             app.logger.info(f"Clearing state for user {user_id} due to '{text}' input.")
             if user_id in user_states: del user_states[user_id]
             reply_content = create_main_menu_message() # 直接回主選單
        else:
            topic_and_question = text; user_data["topic_and_question"] = topic_and_question
            app.logger.info(f"User {user_id} provided topic and question: '{topic_and_question}'")
            birth_info_str = user_data.get("birth_info_str", "未提供"); shichen = user_data.get("shichen", "未知")
            formatted_birth_info = user_data.get("formatted_birth_info", birth_info_str); price = SERVICE_FEES.get("問事/命理", "請私訊老師洽詢")
            notification_base_text = (f"【命理問事請求】\n--------------------\n用戶ID: {user_id}\n提供生日: {formatted_birth_info}\n對應時辰: {shichen}\n主題與問題: {topic_and_question}\n費用: {price}\n--------------------")
            app.logger.info(f"準備處理命理問事請求: {notification_base_text}")
            if teacher_user_id:
                try: push_notification_text = notification_base_text + "\n請老師抽空親自回覆"; send_message(teacher_user_id, TextMessage(text=push_notification_text)); app.logger.info("命理問事通知已嘗試發送給老師。")
                except Exception as e: app.logger.error(f"錯誤：發送命理問事通知給老師失敗: {e}"); app.logger.info("備份通知到日誌：\n" + notification_base_text + "\n（發送失敗，請查看日誌）")
            else: app.logger.warning("警告：未設定老師的 User ID..."); app.logger.info(notification_base_text + "\n（未設定老師ID，僅記錄日誌）")
            reply_text_to_user = f"收到您的資訊！\n生日時辰：{formatted_birth_info} ({shichen}時)\n您想詢問：{topic_and_question[:50]}{'...' if len(topic_and_question)>50 else ''}\n費用：{price}\n\n老師會在空閒時親自查看，並針對您的問題回覆您，請耐心等候，謝謝！"
            # *** 修改處：發送確認後，再發主選單 ***
            send_message(user_id, TextMessage(text=reply_text_to_user), reply_token) # 先用 Reply 回覆
            reply_token = None # 避免後續重複使用 Reply Token
            reply_content = create_main_menu_message() # 準備主選單
            if user_id in user_states: app.logger.info(f"Clearing state for user {user_id} after consultation info submission."); del user_states[user_id]
    elif text_lower == "如何預約":
    # *** 修改處：直接在此處建立預約子選單 Flex Message ***
        try:
            submenu_buttons = []
            submenu_items = {
                "問事": {"action": "select_service", "service": "問事/命理"}, # 觸發問事流程
                "法事": {"action": "select_service", "service": "法事"},   # 觸發法事流程
                "收驚": {"action": "book_simple_service", "service": "收驚"}, # 直接預約
                "卜卦": {"action": "book_simple_service", "service": "卜卦"}, # 直接預約
                "風水勘察與調理": {"action": "book_simple_service", "service": "風水勘察與調理"} # 直接預約 (假設)
            }
            submenu_button_style = {'primary': '#8C6F4E', 'secondary': '#EFEBE4'}

            for label, data in submenu_items.items():
                # 使用 PostbackAction 以便後續處理
                postback_data_str = json.dumps(data)
                if len(postback_data_str.encode('utf-8')) <= 300:
                     submenu_buttons.append(FlexButton(
                        action=PostbackAction(label=label, data=postback_data_str, display_text=label),
                        style='primary' if label == "問事" else 'secondary', # 問事用主要顏色
                        color=submenu_button_style['primary'] if label == "問事" else submenu_button_style['secondary'],
                        height='sm',
                        margin='sm'
                    ))
                else:
                    app.logger.warning(f"預約子選單按鈕 Postback data 過長: {postback_data_str}")

            # 加入返回主選單按鈕
            back_button_data = json.dumps({"action": "show_main_menu"})
            if len(back_button_data.encode('utf-8')) <= 300:
                 submenu_buttons.append(FlexButton(
                    action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'),
                    style='link',
                    height='sm',
                    color='#555555',
                    margin='lg' # 與上方按鈕間距拉大
                ))
            else:
                 app.logger.error("Back button data too long for booking submenu!")


            bubble = FlexBubble(
                header=FlexBox(
                    layout='vertical',
                    contents=[FlexText(text='預約服務選項', weight='bold', size='xl', color='#5A3D1E', align='center')]
                ),
                body=FlexBox(
                    layout='vertical',
                    spacing='md',
                    contents=[
                        FlexText(text='請選擇您需要的服務類型：', wrap=True, size='sm', color='#333333'),
                        FlexSeparator(margin='md')
                    ]
                ),
                footer=FlexBox( # 將按鈕放在 Footer
                    layout='vertical',
                    spacing='sm',
                    contents=submenu_buttons
                ),
                styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
            )
            reply_content = FlexMessage(alt_text='預約服務選項', contents=bubble)
            #notify_teacher("有使用者查詢了預約服務選項。") # 保留通知

        except Exception as e:
            app.logger.error(f"建立預約子選單時發生錯誤: {e}")
            reply_content = TextMessage(text="抱歉，顯示預約選項時發生錯誤，請稍後再試。")

    # ... (處理其他關鍵字，例如 "問事", "法事" 等，這些仍然需要保留，因為子選單按鈕會觸發這些文字) ...
    
    elif text_lower == "問事" or text_lower == "命理諮詢":
        app.logger.info(f"User {user_id} triggered consultation keyword.")
        # *** 修改處：直接準備包含所有須知的說明文字 ***
        consultation_info_text = """【問事/命理諮詢須知】

問事費用：NT$600 (不限制時間與問題，但一定要詳細！)

請準備以下資訊，並直接在此聊天室中一次提供：
1.  ✅姓名
2.  ✅國曆生日 (年/月/日，請提供身分證上的出生年月日)
3.  ✅出生時辰 (盡量提供即可，若不確定也沒關係)
4.  ✅想詢問的問題 (請盡量詳細描述人、事、時、地、物，越詳細越好)
5.  ✅照片需求：
    🔵問感情：請提供雙方姓名、生日、合照。
    🔵問其他事情：請提供個人清晰的雙手照片。

✅匯款資訊：
🌟 銀行：822 中國信託
🌟 帳號：510540490990

感恩😊 老師收到您的完整資料與匯款後，會以文字+語音訊息回覆您。資料留完後請耐心等待，通常三天內會完成回覆，感恩🙏"""
        
        reply_content = TextMessage(text=consultation_info_text)
        # (移除了附加 QuickReply 的部分)
    elif text_lower in ["法事", "預約法事", "法會", "解冤親", "補財庫", "補桃花"]:
        app.logger.info(f"User {user_id} triggered ritual keyword: '{text}'. Entering ritual selection.")
        user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
        reply_content = create_ritual_selection_message(user_id)
    elif text_lower in ["開運物", "課程"]:
        reply_content = TextMessage(text=get_info_text(text))
        # 附加主選單按鈕
        reply_content.quick_reply = QuickReply(items=[QuickReplyButton(action=create_return_to_menu_action())])
    elif text_lower == "ig":
         reply_content = TextMessage(text=other_services_keywords["IG"])
         # 附加主選單按鈕
         reply_content.quick_reply = QuickReply(items=[QuickReplyButton(action=create_return_to_menu_action())])
    # --- 其他所有文字訊息一律回覆主選單 ---
    else:
        app.logger.info(f"User {user_id} sent text '{text}' outside of expected flow. Replying with main menu.")
        reply_content = create_main_menu_message()

    # --- 發送回覆 ---
    if reply_content:
        send_message(user_id, reply_content, reply_token)


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (預約流程 + 生日收集 + 資訊顯示 + 返回)"""
    reply_message = None; follow_up_message = None; user_id = event.source.user_id
    app.logger.info(f"Received Postback from {user_id}")
    try:
        postback_data_str = event.postback.data; app.logger.info(f"Postback data string: '{postback_data_str}'")
        postback_data = json.loads(postback_data_str); action = postback_data.get('action'); app.logger.info(f"Postback action: '{action}'")
        back_button_data = json.dumps({"action": "show_main_menu"}); back_button = None
        if len(back_button_data.encode('utf-8')) <= 300: back_button = FlexButton(action=PostbackAction(label='返回主選單', data=back_button_data, display_text='返回'), style='secondary', height='sm', margin='xl')
        else: app.logger.error("Back button data too long!")
        if action == 'show_main_menu':
            if user_id in user_states: app.logger.info(f"Clearing state for user {user_id} due to 'show_main_menu'."); del user_states[user_id]
            reply_message = create_main_menu_message()
        elif action == 'select_service': # 由主選單按鈕觸發
            selected_service = postback_data.get('service')
            if selected_service:
                app.logger.info(f"User {user_id} selected service via Postback: {selected_service}")
                if selected_service in ["收驚", "卜卦"]: handle_booking_request(user_id, selected_service) # 直接處理
                elif selected_service == "法事":
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
                    app.logger.info(f"State set for user {user_id}: selecting_rituals")
                    reply_message = create_ritual_selection_message(user_id) # 顯示法事選擇
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

        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            if selected_ritual:
                app.logger.info(f"User {user_id} toggled ritual item: {selected_ritual}")
                if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals": user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": [selected_ritual]}}; app.logger.warning(f"User {user_id} was not in selecting_rituals state, resetting.")
                else:
                    current_selection = user_states[user_id]["data"]["selected_rituals"]
                    if selected_ritual in current_selection: current_selection.remove(selected_ritual); app.logger.info(f"Removed '{selected_ritual}' from selection for {user_id}")
                    else: current_selection.append(selected_ritual); app.logger.info(f"Added '{selected_ritual}' to selection for {user_id}")
                reply_message = create_ritual_selection_message(user_id) # 只發送更新後的選單
            else: app.logger.warning(f"Postback 'select_ritual_item' missing ritual for user {user_id}"); reply_message = TextMessage(text="發生錯誤..."); follow_up_message = create_main_menu_message()

        elif action == 'confirm_rituals':
             if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                 selected_rituals = user_states[user_id].get("data", {}).get("selected_rituals", [])
                 app.logger.info(f"User {user_id} confirmed rituals: {selected_rituals}")
                 if not selected_rituals:
                      reply_message = TextMessage(text="您尚未選擇任何法事項目，請選擇後再點擊完成選擇。")
                      # 這裡不發送 follow_up_message，讓用戶看到提示後可以繼續操作當前選單
                 else: total_price, final_item_list = calculate_total_price(selected_rituals); handle_booking_request(user_id, final_item_list, total_price); del user_states[user_id]; reply_message = None # handle_booking_request 會處理回覆
             else: app.logger.warning(f"User {user_id} clicked confirm_rituals but not in correct state."); reply_message = create_main_menu_message()
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
        elif action == 'select_datetime': # 理論上不再使用
             selected_service = postback_data.get('service'); app.logger.warning(f"Unexpected 'select_datetime' action for service: {selected_service}. Handling as direct booking.")
             if selected_service: handle_booking_request(user_id, selected_service)
             else: app.logger.error(f"Postback 'select_datetime' missing service for user {user_id}"); reply_message = TextMessage(text="發生錯誤..."); follow_up_message = create_main_menu_message()
        elif action == 'show_info':
            topic = postback_data.get('topic')
            if topic:
                 app.logger.info(f"User {user_id} requested info for topic: {topic}")
                 info_text = get_info_text(topic); contents = [FlexText(text=info_text, wrap=True)]
                 if back_button: contents.append(back_button)
                 bubble = FlexBubble(body=FlexBox(layout='vertical', spacing='md', contents=contents)); reply_message = FlexMessage(alt_text=f"關於 {topic} 的說明", contents=bubble)
            else: app.logger.warning(f"Postback 'show_info' missing topic for user {user_id}"); reply_message = TextMessage(text="無法識別資訊..."); follow_up_message = create_main_menu_message()
        else: app.logger.warning(f"Received unknown Postback Action from {user_id}: {action}"); reply_message = create_main_menu_message()
    except json.JSONDecodeError: app.logger.error(f"Failed to parse Postback data from {user_id}: {postback_data_str}"); reply_message = TextMessage(text="系統無法處理請求..."); follow_up_message = create_main_menu_message()
    except Exception as e: app.logger.exception(f"Error processing Postback from {user_id}: {e}"); reply_message = TextMessage(text="系統發生錯誤..."); follow_up_message = create_main_menu_message()
    messages_to_send = []
    if reply_message:
        if isinstance(reply_message, list): messages_to_send.extend(reply_message)
        else: messages_to_send.append(reply_message)
    if follow_up_message: messages_to_send.append(follow_up_message)
    if messages_to_send: send_message(user_id, messages_to_send) # Postback 一律用 Push

# --- 主程式入口 ---
if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.run(host='0.0.0.0', port=port, debug=False)
