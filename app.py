<<<<<<< HEAD
# -*- coding: utf-8 -*-

import os
import json
import logging
from dotenv import load_dotenv # 建議使用 python-dotenv 管理環境變數

from flask import Flask, request, abort

from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
    # --- 匯入 Flex Message 會用到的元件 ---
    FlexBubble, FlexBox, FlexText, FlexButton, FlexSeparator, FlexImage,
    # --- 匯入 URIAction 和 MessageAction ---
    URIAction, MessageAction, # MessageAction 用於按鈕觸發文字訊息
    # --- 匯入 TemplateMessage 和 ButtonsTemplate ---
    TemplateMessage, ButtonsTemplate
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent # 處理加入好友事件
)

# --- 載入環境變數 ---
# 建議將您的金鑰和設定存在 .env 檔案或 Render 的環境變數中
load_dotenv()

# Line Bot 金鑰
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET') # 請確保已在 Render 加入此變數

# Google API 相關金鑰 (從 Render 環境變數讀取)
# 請確保這些 Key 與您在 Render 設定的名稱完全一致
google_calendar_id = os.getenv('GOOGLE_CALENDAR_ID', None)
# google_client_id = os.getenv('GOOGLE_CLIENT_ID', None) # GOOGLE_CLIENT_ID 和 SECRET 通常包含在 credentials.json 中，或者用於不同的 OAuth 流程
# google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET', None)
google_credentials_json_path = os.getenv('GOOGLE_CREDENTIALS_JSON', None) # 通常會是 JSON 檔案的路徑或內容字串

# 管理員/老師的 Line User ID (用於發送通知等)
teacher_user_id = os.getenv('TEACHER_USER_ID', None)

# --- 基本設定 ---
app = Flask(__name__)

# Line Bot API 設定
configuration = Configuration(access_token=channel_access_token)
# 檢查 channel_secret 是否成功載入，若無則無法啟動 handler
if not channel_secret:
    logging.error("LINE_CHANNEL_SECRET not found in environment variables.")
    # 這裡可以選擇退出程式或拋出錯誤，取決於您的錯誤處理策略
    # exit() # 或 raise ValueError("Missing LINE_CHANNEL_SECRET")
    handler = None # 或者將 handler 設為 None，並在後面檢查
else:
    handler = WebhookHandler(channel_secret)

# --- 服務與資訊內容 (方便管理) ---

# 主要服務項目
main_services_list = [
    "命理諮詢（數字易經、八字、問事）",
    "風水勘察與調理",
    "補財庫、煙供、生基、安斗等客製化法會儀軌",
    "點燈祈福、開運蠟燭",
    "命理課程與法術課程"
]

# 其他服務/連結
ig_link = "https://www.instagram.com/magic_momo9/"
other_services_keywords = {
    "開運產品": "關於開運生基煙供產品，（此處可放產品介紹或連結）。\n詳情請洽詢...",
    "運勢文": "查看每週運勢文，（此處可放最新運勢文摘要或連結）。\n請關注我們的社群平台獲取最新資訊。",
    "最新消息": "（此處可放置最新公告、活動資訊等）。",
    "課程介紹": "我們提供命理與法術相關課程，（此處可放課程詳細介紹、開課時間、報名方式等）。\n詳情請洽詢...",
    "IG": f"追蹤我們的 Instagram：{ig_link}", # 使用變數
    "抖音": "追蹤我們的抖音：[您的抖音連結]" # 請替換成您的抖音連結
}

# 法事價格
ritual_prices_info = {
    "冤親債主/補桃花/補財庫": {"single": 680, "combo": 1800},
    "祖先": {"single": 1800}
}

# 匯款資訊
payment_details = {
    "bank_code": "822",
    "bank_name": "中國信託",
    "account_number": "510540490990"
}

# 命理問事須知/如何預約
how_to_book_instructions = """【如何預約/命理問事須知】
請提供以下資訊：
1.  **國曆生日** (年/月/日)
2.  **出生時間** (24小時制，例如 晚上11:30 請輸入 2330 或 23:30，早上7點請輸入 0700 或 07:00)。
    * 請直接告知出生時間數字，**無需自行換算時區或加減時間**。
    * 時辰參考：
        2300-0059 子 | 0100-0259 丑
        0300-0459 寅 | 0500-0659 卯
        0700-0859 辰 | 0900-1059 巳
        1100-1259 午 | 1300-1459 未
        1500-1659 申 | 1700-1859 酉
        1900-2059 戌 | 2100-2259 亥

請將上述資訊，連同您想問的問題，一併發送給我們。

【預約方式】
（請在此處填寫您的主要預約方式，例如：請直接私訊留下您的問題與資料，我們會盡快回覆。）
"""

# --- 按鈕產生函式 ---
def create_return_to_menu_button():
    """產生返回主選單的 MessageAction 按鈕"""
    return MessageAction(label='返回主選單', text='服務項目')

# --- Flex Message 產生函式 ---

def create_main_services_flex():
    """產生主要服務項目的 Flex Message (更新按鈕)"""
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[
                FlexText(text='宇宙玄天院 主要服務項目', weight='bold', size='xl', color='#5A3D1E', align='center')
            ]
        ),
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='我們提供以下服務，助您開啟靈性覺醒：', wrap=True, size='sm', color='#333333'),
                FlexSeparator(margin='md'),
                *[FlexText(text=f'• {service}', wrap=True, size='sm', margin='sm') for service in main_services_list],
                FlexSeparator(margin='lg'),
                FlexText(text='點擊下方按鈕或輸入關鍵字了解更多：', size='xs', color='#888888', wrap=True)
            ]
        ),
        footer=FlexBox(
            layout='vertical',
            spacing='sm',
            contents=[
                FlexButton(
                    action=MessageAction(label='如何預約', text='如何預約'),
                    style='primary',
                    color='#8C6F4E',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='開運 生基 煙供產品', text='開運產品'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=URIAction(label='追蹤我們的 IG', uri=ig_link),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='法事項目與費用', text='法事項目'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='主要服務項目', contents=bubble)

def create_ritual_prices_flex():
    """產生法事項目與費用的 Flex Message (加入返回主選單按鈕)"""
    contents = [
        FlexText(text='法事項目與費用', weight='bold', size='xl', color='#5A3D1E', align='center', margin='md')
    ]
    for item, prices in ritual_prices_info.items():
        price_texts = []
        if "single" in prices:
            price_texts.append(f"NT$ {prices['single']} / 份")
        if "combo" in prices:
             price_texts.append(f"(三合一/一條龍: 三份 NT$ {prices['combo']})")

        contents.extend([
            FlexSeparator(margin='lg'),
            FlexText(text=item, weight='bold', size='md', margin='md'),
            FlexText(text=" ".join(price_texts), size='sm', color='#555555', wrap=True)
        ])

    if "冤親債主/補桃花/補財庫" in ritual_prices_info and "combo" in ritual_prices_info["冤親債主/補桃花/補財庫"]:
         contents.append(FlexSeparator(margin='lg'))
         contents.append(FlexText(text='⚜️ 三合一/一條龍包含：冤親債主、補桃花、補財庫。', size='sm', color='#888888', wrap=True, margin='md'))

    contents.append(FlexSeparator(margin='xl'))
    # *** 加入按鈕到 Footer ***
    footer_buttons = [
        FlexButton(
            action={'type': 'message', 'label': '了解匯款資訊', 'text': '匯款資訊'},
            style='primary',
            color='#8C6F4E',
            height='sm',
            margin='md'
        ),
        FlexSeparator(margin='md'), # 分隔線
        FlexButton(
            action=create_return_to_menu_button().as_dict(), # 使用輔助函式產生返回按鈕的 action
            style='link', # 使用 link 樣式
            height='sm',
            color='#555555' # 深灰色文字
        )
    ]

    bubble = FlexBubble(
        body=FlexBox(
            layout='vertical',
            contents=contents
        ),
        footer=FlexBox( # 新增 Footer
             layout='vertical',
             spacing='sm',
             contents=footer_buttons
        ),
         styles={'body': {'backgroundColor': '#F9F9F9'}, 'footer': {'separator': True}} # 淺灰色背景
    )
    return FlexMessage(alt_text='法事項目與費用', contents=bubble)

# --- Template Message 產生函式 ---
def create_text_with_menu_button(text_content, alt_text="訊息"):
    """產生包含文字內容和返回主選單按鈕的 TemplateMessage"""
    buttons_template = ButtonsTemplate(
        text=text_content[:160], # ButtonsTemplate 的 text 限制為 160 字元
        actions=[
            create_return_to_menu_button()
        ]
        # 可以加入 title, thumbnail_image_url 等參數
    )
    return TemplateMessage(
        alt_text=alt_text, # 在通知或無法顯示 Template 時的替代文字
        template=buttons_template
    )

# --- 輔助函式：發送通知給管理員 ---
def notify_teacher(message_text):
    """發送 Push Message 給指定的老師/管理員"""
    if not teacher_user_id:
        logging.warning("TEACHER_USER_ID not set. Cannot send notification.")
        return
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send notification.")
        return

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=teacher_user_id,
                    messages=[TextMessage(text=message_text)] # 只發送傳入的文字
                )
            )
            logging.info(f"Notification sent to teacher: {teacher_user_id}")
    except Exception as e:
        logging.error(f"Error sending notification to teacher: {e}")


# --- Webhook 主要處理函式 ---
@app.route("/callback", methods=['POST'])
def callback():
    # 檢查 handler 是否成功初始化
    if ler is None:
        logging.error("Webhook ler is not initialized. Check LINE_CHANNEL_SECRET.")
        abort(500) # 內部伺服器錯誤

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # le webhook body
    try:
        ler.le(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)
    except Exception as e:
        print(f"Error ling webhook: {e}")
        logging.exception("Error ling webhook:") # 記錄詳細錯誤堆疊
        abort(500)

    return 'OK'

# --- 處理訊息事件 ---
@handler.add(MessageEvent, message=TextMessageContent)
def le_message(event):
    """處理文字訊息"""
    user_message = event.message.text.strip() # 去除前後空白
    user_id = event.source.user_id # 取得使用者 ID (保留，可能未來其他地方會用到)
    reply_content = None

    # 檢查 Line Bot API 設定是否有效
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot reply.")
        return # 無法回覆

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # --- 根據關鍵字回覆 ---
        if user_message in ["服務", "服務項目", "功能", "選單", "menu"]:
            reply_content = create_main_services_flex() # 主選單，不加返回按鈕
        elif user_message in ["預約", "預約諮詢", "問事", "命理問事", "算命", "如何預約"]:
            # *** 使用 Template Message 回覆 ***
            reply_content = create_text_with_menu_button(how_to_book_instructions, alt_text="如何預約/問事須知")
            notify_teacher("有使用者查詢了如何預約/問事須知。")
        elif user_message in ["法事", "法事項目", "價錢", "價格", "費用"]:
            reply_content = create_ritual_prices_flex() # Flex Message 已加入返回按鈕
        elif user_message in ["匯款", "匯款資訊", "帳號"]:
            # *** 使用 Template Message 回覆 ***
            payment_text = f"""【匯款資訊】
🌟 匯款帳號：
銀行代碼：{payment_details['bank_code']}
銀行名稱：{payment_details['bank_name']}
帳號：{payment_details['account_number']}

（匯款後請告知末五碼以便核對）"""
            reply_content = create_text_with_menu_button(payment_text, alt_text="匯款資訊")
        elif user_message in other_services_keywords or user_message == "開運產品":
             # 處理 "開運產品" 和字典中的其他關鍵字
             keyword_to_lookup = user_message if user_message in other_services_keywords else "開運產品"
             text_to_reply = other_services_keywords[keyword_to_lookup]
             # *** 使用 Template Message 回覆 ***
             reply_content = create_text_with_menu_button(text_to_reply, alt_text=keyword_to_lookup) # 使用關鍵字當 alt_text
        elif "你好" in user_message or "hi" in user_message.lower() or "hello" in user_message.lower():
             # *** 使用 Template Message 回覆 ***
             hello_text = "您好！很高興為您服務。\n請問需要什麼協助？\n您可以輸入「服務項目」查看我們的服務選單。"
             reply_content = create_text_with_menu_button(hello_text, alt_text="問候")

        # --- 處理 Google Calendar 相關邏輯 (範例，需要您實作) ---
        elif user_message == "查詢可預約時間":
            if google_calendar_id and google_credentials_json_path:
                try:
                    # ... (省略 Google Calendar API 呼叫邏輯) ...
                    calendar_response_text = "查詢可預約時間功能開發中..." # 暫時回覆
                    # *** 使用 Template Message 回覆 ***
                    reply_content = create_text_with_menu_button(calendar_response_text, alt_text="查詢可預約時間")
                    notify_teacher("有使用者正在查詢可預約時間。")
                except Exception as e:
                    logging.error(f"Error accessing Google Calendar: {e}")
                    error_text = "查詢可預約時間失敗，請稍後再試。"
                    # *** 使用 Template Message 回覆 ***
                    reply_content = create_text_with_menu_button(error_text, alt_text="查詢錯誤")
            else:
                error_text = "Google Calendar 設定不完整，無法查詢預約時間。"
                # *** 使用 Template Message 回覆 ***
                reply_content = create_text_with_menu_button(error_text, alt_text="設定錯誤")

        else:
            # --- 預設回覆 (如果需要，也可以加上返回按鈕) ---
            # default_text = "收到您的訊息！\n如果您需要服務，可以輸入「服務項目」查看選單，或直接說明您的需求喔。"
            # reply_content = create_text_with_menu_button(default_text, alt_text="收到訊息")

            # --- 將未知訊息轉發給老師 (範例) ---
            # notify_teacher(f"收到無法自動處理的訊息：\n\n{user_message}")
            pass # 目前設定為不回覆未知訊息

        # --- 發送回覆 ---
        if reply_content:
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[reply_content] # 發送單一訊息物件 (Flex 或 Template)
                    )
                )
            except Exception as e:
                 logging.error(f"Error sending reply message: {e}")


# --- 處理加入好友事件 ---
@handler.add(FollowEvent)
def handle_follow(event):
    """當使用者加入好友時發送歡迎訊息與按鈕選單"""
    user_id = event.source.user_id
    logging.info(f"User {user_id} followed the bot.")
    notify_teacher(f"有新使用者加入好友：{user_id}")

    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send follow message.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        welcome_text = """歡迎加入【宇宙玄天院】！

宇宙玄天院｜開啟靈性覺醒的殿堂

本院奉玄天上帝為主神，由雲真居士領導修持道脈，融合儒、釋、道三教之理與現代身心靈智慧，致力於指引眾生走上自性覺醒與命運轉化之路。

主要服務項目包含：
• 命理諮詢（數字易經、八字、問事）
• 風水勘察與調理
• 補財庫、煙供、生基、安斗、等客製化法會儀軌
• 點燈祈福、開運蠟燭
• 命理課程與法術課程

本院深信：每一個靈魂都能連結宇宙本源，找到生命的方向與力量。讓我們陪伴您走向富足、自主與心靈的圓滿之路。

您可以點擊下方按鈕查看詳細服務項目與資訊："""
        welcome_message = TextMessage(text=welcome_text)
        services_flex = create_main_services_flex()

        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[welcome_message, services_flex]
                )
            )
            logging.info(f"Successfully sent welcome message to user {user_id}")
        except Exception as e:
            logging.error(f"Error sending follow message to user {user_id}: {e}")
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="歡迎加入宇宙玄天院！請輸入「服務項目」查看選單。")]
                )
            )

# --- 主程式入口 ---
if __name__ == "__main__":
    # 設定 Log 等級
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # 檢查必要的環境變數
    if not channel_access_token or not channel_secret:
        logging.error("Missing required LINE environment variables (TOKEN or SECRET). Exiting.")
        exit()
    if not teacher_user_id:
        logging.warning("TEACHER_USER_ID is not set. Notifications to teacher will not work.")
    # ... (其他檢查) ...

    port = int(os.environ.get('PORT', 5000))
    logging.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
=======
# -*- coding: utf-8 -*-

import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    PushMessageRequest, TextMessage, FlexMessage, FlexContainer,
    FlexBubble, FlexBox, FlexText, FlexButton, FlexSeparator, FlexImage,
    URIAction, MessageAction, DatetimePickerAction, TemplateMessage, ButtonsTemplate,
    QuickReply, QuickReplyItem, PostbackAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, PostbackEvent

# --- 載入環境變數 ---
load_dotenv()

# Line Bot 金鑰
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

# 管理員/老師的 Line User ID
teacher_user_id = os.getenv('TEACHER_USER_ID', None)

# --- 基本設定 ---
app = Flask(__name__)
configuration = Configuration(access_token=channel_access_token)

if not channel_secret:
    logging.error("LINE_CHANNEL_SECRET not found in environment variables.")
    handler = None
else:
    handler = WebhookHandler(channel_secret)

# --- 服務與資訊內容 ---
main_services_list = [
    "命理諮詢（數字易經、八字、問事）",
    "風水勘察與調理",
    "補財庫、煙供、生基、安斗等客製化法會儀軌",
    "點燈祈福、開運蠟燭",
    "命理課程與法術課程"
]

ig_link = "https://www.instagram.com/magic_momo9/"
other_services_keywords = {
    "開運物": "關於開運生基煙供產品，（此處可放產品介紹或連結）。\n詳情請洽詢...",
    "運勢文": "查看每週運勢文，（此處可放最新運勢文摘要或連結）。\n請關注我們的社群平台獲取最新資訊。",
    "最新消息": "（此處可放置最新公告、活動資訊等）。",
    "課程": "我們提供命理與法術相關課程，（此處可放課程詳細介紹、開課時間、報名方式等）。\n詳情請洽詢...",
    "IG": f"追蹤我們的 Instagram：{ig_link}",
    "抖音": "追蹤我們的抖音：[您的抖音連結]",
    "煙供品": "煙供品介紹：（此處可放煙供品介紹或連結）。\n詳情請洽詢...",
    "生基品": "生基品介紹：（此處可放生基品介紹或連結）。\n詳情請洽詢..."
}

# --- 服務費用設定 (更新版) ---
SERVICE_FEES = {
    "冤親債主 (個人)": 680, "補桃花 (個人)": 680, "補財庫 (個人)": 680,
    "三合一 (個人)": 1800, # 冤親+桃花+財庫 (個人)
    "冤親債主 (祖先)": 1800, "補桃花 (祖先)": 1800, "補財庫 (祖先)": 1800,
    "三合一 (祖先)": 5400, # 假設 1800 * 3
    # 其他服務...
}
# 定義三合一組合內容，用於計算優惠
PERSONAL_BUNDLE_ITEMS = {"冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)"}
ANCESTOR_BUNDLE_ITEMS = {"冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)"}
PERSONAL_BUNDLE_NAME = "三合一 (個人)"
ANCESTOR_BUNDLE_NAME = "三合一 (祖先)"

payment_details = {
    "bank_code": "822",
    "bank_name": "中國信託",
    "account_number": "510540490990"
}

how_to_book_instructions = """【如何預約】
請選擇您需要的服務類型："""

# 預約子選單項目
booking_submenu = {
    "問事": "請按照以下步驟提供您的資訊：\n1. 選擇您的 **國曆生日**。\n2. 選擇您的 **出生時辰**。",
    "法事": "請選擇您需要的法事項目：",
    "收驚": "收驚服務：請提供您的姓名與出生日期，我們將為您安排收驚儀式。",
    "卜卦": "卜卦服務：請提供您想詢問的問題，我們將為您進行卜卦。",
    "開運物": other_services_keywords["開運物"],
    "煙供品": other_services_keywords["煙供品"],
    "生基品": other_services_keywords["生基品"],
    "課程": other_services_keywords["課程"]
}

# 時辰選項
time_periods = [
    {"label": "子 (23:00-00:59)", "value": "子時 (23:00-00:59)"},
    {"label": "丑 (01:00-02:59)", "value": "丑時 (01:00-02:59)"},
    {"label": "寅 (03:00-04:59)", "value": "寅時 (03:00-04:59)"},
    {"label": "卯 (05:00-06:59)", "value": "卯時 (05:00-06:59)"},
    {"label": "辰 (07:00-08:59)", "value": "辰時 (07:00-08:59)"},
    {"label": "巳 (09:00-10:59)", "value": "巳時 (09:00-10:59)"},
    {"label": "午 (11:00-12:59)", "value": "午時 (11:00-12:59)"},
    {"label": "未 (13:00-14:59)", "value": "未時 (13:00-14:59)"},
    {"label": "申 (15:00-16:59)", "value": "申時 (15:00-16:59)"},
    {"label": "酉 (17:00-18:59)", "value": "酉時 (17:00-18:59)"},
    {"label": "戌 (19:00-20:59)", "value": "戌時 (19:00-20:59)"},
    {"label": "亥 (21:00-22:59)", "value": "亥時 (21:00-22:59)"}
]

# --- 狀態管理 ---
# 儲存所有加入好友的使用者 ID（模擬資料庫）
followed_users = set()

# 儲存使用者的生日（臨時儲存，等待時辰選擇）
user_birthday_data = {}

# 統一使用 user_states 進行狀態管理 (替代 user_ritual_selections)
user_states = {}

# --- 按鈕產生函式 ---
def create_return_to_menu_button():
    return MessageAction(label='返回主選單', text='服務項目')

# --- Flex Message 產生函式 ---
def create_main_services_flex():
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[
                FlexText(text='宇宙玄天院 主要服務項目', weight='bold', size='xl', color='#5A3D1E', align='center')
            ]
        ),
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='我們提供以下服務，助您開啟靈性覺醒：', wrap=True, size='sm', color='#333333'),
                FlexSeparator(margin='md'),
                *[FlexText(text=f'• {service}', wrap=True, size='sm', margin='sm') for service in main_services_list],
                FlexSeparator(margin='lg'),
                FlexText(text='點擊下方按鈕或輸入關鍵字了解更多：', size='xs', color='#888888', wrap=True)
            ]
        ),
        footer=FlexBox(
            layout='vertical',
            spacing='sm',
            contents=[
                FlexButton(
                    action=MessageAction(label='如何預約', text='如何預約'),
                    style='primary',
                    color='#8C6F4E',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='開運物', text='開運物'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=URIAction(label='追蹤我們的 IG', uri=ig_link),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='課程', text='課程'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='主要服務項目', contents=bubble)

# --- 輔助函數：建立法事選擇 Flex Message ---
def create_ritual_selection_message(user_id):
    """建立法事項目選擇的 Flex Message"""
    logging.info(f"创建法事选择消息, 用户ID: {user_id}")
    
    buttons = []
    ritual_items = [
        "冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)", "三合一 (個人)",
        "冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)", "三合一 (祖先)"
    ]
    
    # 獲取用戶當前已選項目
    current_selection = []
    if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
        current_selection = user_states[user_id]["data"].get("selected_rituals", [])
    
    logging.info(f"当前选择: {current_selection}")
    
    # 建立項目按鈕
    for item in ritual_items:
        price = SERVICE_FEES.get(item, "洽詢")
        label_with_price = f"{item} (NT${price})" if isinstance(price, int) else f"{item} ({price})"
        is_selected = item in current_selection
        button_label = f"✅ {label_with_price}" if is_selected else label_with_price
        button_style = 'secondary' if is_selected else 'primary'

        ritual_postback_data = json.dumps({"action": "select_ritual_item", "ritual": item})
        if len(ritual_postback_data.encode('utf-8')) <= 300:
            buttons.append(FlexButton(
                action=PostbackAction(
                    label=button_label, 
                    data=ritual_postback_data, 
                    display_text=f"選擇法事：{item}"
                ), 
                style=button_style, 
                color='#A67B5B' if not is_selected else '#DDDDDD', 
                margin='sm', 
                height='sm'
            ))
        else:
            logging.warning(f"Postback data too large for ritual: {item}")

    # 建立完成選擇按鈕
    confirm_data = json.dumps({"action": "confirm_rituals"})
    if len(confirm_data.encode('utf-8')) <= 300:
        buttons.append(FlexButton(
            action=PostbackAction(
                label='完成選擇，計算總價', 
                data=confirm_data, 
                display_text='完成法事選擇'
            ), 
            style='primary', 
            color='#4CAF50', 
            margin='lg', 
            height='sm'
        ))
    else:
        logging.warning("Confirm button postback data too large")

    # 建立返回按鈕
    back_button_data = json.dumps({"action": "show_main_menu"})
    if len(back_button_data.encode('utf-8')) <= 300:
         buttons.append(FlexButton(
             action=PostbackAction(
                 label='返回主選單', 
                 data=back_button_data, 
                 display_text='返回'
             ), 
             style='secondary', 
             height='sm', 
             margin='md'
         ))
    else:
        logging.warning("Back button postback data too large")

    # 顯示已選項目
    selected_text = "您目前已選擇：\n" + "\n".join(f"- {r}" for r in current_selection) if current_selection else "請點擊下方按鈕選擇法事項目："

    # 创建消息容器
    contents = [
        FlexText(text=selected_text, wrap=True, size='sm', margin='md'),
        FlexSeparator(margin='lg')
    ]
    
    # 将所有按钮添加到内容中
    for button in buttons:
        contents.append(button)

    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical', 
            contents=[FlexText(text='預約法事', weight='bold', size='lg', align='center', color='#B28E49')]
        ),
        body=FlexBox(
            layout='vertical', 
            spacing='md', 
            contents=contents
        )
    )
    
    logging.info("法事选择消息创建完成")
    return FlexMessage(alt_text='請選擇法事項目', contents=bubble)

def create_payment_info_message():
    payment_text = f"""【匯款資訊】
🌟 匯款帳號：
銀行代碼：{payment_details['bank_code']}
銀行名稱：{payment_details['bank_name']}
帳號：{payment_details['account_number']}

（匯款後請回覆「匯款完成」並告知末五碼以便核對）"""
    
    logging.info("创建匯款信息消息")
    return TextMessage(text=payment_text)

def create_booking_submenu_flex():
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[
                FlexText(text='預約服務選項', weight='bold', size='xl', color='#5A3D1E', align='center')
            ]
        ),
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='請選擇您需要的服務類型：', wrap=True, size='sm', color='#333333'),
                FlexSeparator(margin='md'),
            ]
        ),
        footer=FlexBox(
            layout='vertical',
            spacing='sm',
            contents=[
                FlexButton(
                    action=MessageAction(label='問事', text='問事'),
                    style='primary',
                    color='#8C6F4E',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='法事', text='法事'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='收驚', text='收驚'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='卜卦', text='卜卦'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='開運物', text='開運物'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='煙供品', text='煙供品'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='生基品', text='生基品'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=MessageAction(label='課程', text='課程'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action=create_return_to_menu_button(),
                    style='link',
                    height='sm',
                    color='#555555'
                ),
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='預約服務選項', contents=bubble)

# --- Template Message 產生函式 ---
def create_text_with_menu_button(text_content, alt_text="訊息"):
    buttons_template = ButtonsTemplate(
        text=text_content[:160],
        actions=[create_return_to_menu_button()]
    )
    return TemplateMessage(alt_text=alt_text, template=buttons_template)

# --- 輔助函式：發送通知給管理員 ---
def notify_teacher(message_text):
    if not teacher_user_id:
        logging.warning("TEACHER_USER_ID not set. Cannot send notification.")
        return
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send notification.")
        return

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=teacher_user_id,
                    messages=[TextMessage(text=message_text)]
                )
            )
            logging.info(f"Notification sent to teacher: {teacher_user_id}")
    except Exception as e:
        logging.error(f"Error sending notification to teacher: {e}")

# --- 每周運勢文群發 ---
def send_weekly_fortune():
    fortune_text = "【本週運勢文】\n（此處放置您的運勢文內容）。\n請關注我們的社群平台獲取更多資訊！"
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for user_id in followed_users:
            try:
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=fortune_text)]
                    )
                )
                logging.info(f"Sent weekly fortune to user: {user_id}")
            except Exception as e:
                logging.error(f"Error sending weekly fortune to {user_id}: {e}")

# --- 設定圖文選單 ---
def setup_rich_menu():
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot set up rich menu.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 定義圖文選單結構
        rich_menu = {
            "size": {
                "width": 2500,
                "height": 1686
            },
            "selected": True,
            "name": "宇宙玄天院 圖文選單",
            "chatBarText": "選單",
            "areas": [
                {
                    "bounds": {
                        "x": 0,
                        "y": 0,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "如何預約"
                    }
                },
                {
                    "bounds": {
                        "x": 833,
                        "y": 0,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "問事"
                    }
                },
                {
                    "bounds": {
                        "x": 1666,
                        "y": 0,
                        "width": 834,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "法事"
                    }
                },
                {
                    "bounds": {
                        "x": 0,
                        "y": 843,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "IG"
                    }
                },
                {
                    "bounds": {
                        "x": 833,
                        "y": 843,
                        "width": 833,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "開運物"
                    }
                },
                {
                    "bounds": {
                        "x": 1666,
                        "y": 843,
                        "width": 834,
                        "height": 843
                    },
                    "action": {
                        "type": "message",
                        "text": "課程"
                    }
                }
            ]
        }

        try:
            # 建立圖文選單
            rich_menu_response = line_bot_api.create_rich_menu(rich_menu)
            rich_menu_id = rich_menu_response['richMenuId']
            logging.info(f"Rich menu created: {rich_menu_id}")

            # 上傳圖片（替換為你的圖片 URL）
            rich_menu_image_url = "YOUR_RICH_MENU_IMAGE_URL"  # 替換為實際的圖片 URL
            with open("rich_menu_image.jpg", "rb") as image_file:
                line_bot_api.set_rich_menu_image(rich_menu_id, "image/jpeg", image_file)
            logging.info("Rich menu image uploaded.")

            # 綁定圖文選單到所有使用者
            line_bot_api.link_rich_menu_to_user("all", rich_menu_id)
            logging.info("Rich menu linked to all users.")

        except Exception as e:
            logging.error(f"Error setting up rich menu: {e}")

# --- 輔助函數：發送訊息 ---
def send_message(user_id, message, reply_token=None):
    """統一的訊息發送函數，支援回覆和推送"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            if reply_token:
                # 使用回覆 token 回覆訊息
                if isinstance(message, list):
                    line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=message))
                else:
                    line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[message]))
            else:
                # 直接推送訊息給指定用戶
                if isinstance(message, list):
                    for msg in message:
                        line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[msg]))
                else:
                    line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[message]))
            return True
        except Exception as e:
            logging.error(f"Error in send_message: {e}")
            return False

# --- 輔助函數：建立主選單訊息 ---
def create_main_menu_message():
    """建立主選單訊息"""
    return create_main_services_flex()

# --- 輔助函數：計算總價 (處理三合一) ---
def calculate_total_price(selected_items):
    """計算選擇的法事項目總價，處理三合一優惠"""
    total_price = 0
    current_selection_set = set(selected_items)
    final_items_to_display = [] # 最終顯示給用戶的項目列表

    # 優先處理組合優惠
    personal_bundle_applied = False
    if PERSONAL_BUNDLE_ITEMS.issubset(current_selection_set):
        logging.info("Applying personal bundle discount.")
        total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0)
        final_items_to_display.append(PERSONAL_BUNDLE_NAME)
        current_selection_set -= PERSONAL_BUNDLE_ITEMS # 從待計算集合中移除
        personal_bundle_applied = True

    ancestor_bundle_applied = False
    if ANCESTOR_BUNDLE_ITEMS.issubset(current_selection_set):
        logging.info("Applying ancestor bundle discount.")
        total_price += SERVICE_FEES.get(ANCESTOR_BUNDLE_NAME, 0)
        final_items_to_display.append(ANCESTOR_BUNDLE_NAME)
        current_selection_set -= ANCESTOR_BUNDLE_ITEMS # 從待計算集合中移除
        ancestor_bundle_applied = True

    # 檢查是否單獨選了三合一
    if PERSONAL_BUNDLE_NAME in current_selection_set and not personal_bundle_applied:
        logging.info("Adding individual personal bundle price.")
        total_price += SERVICE_FEES.get(PERSONAL_BUNDLE_NAME, 0)
        final_items_to_display.append(PERSONAL_BUNDLE_NAME)
        current_selection_set.discard(PERSONAL_BUNDLE_NAME)

    if ANCESTOR_BUNDLE_NAME in current_selection_set and not ancestor_bundle_applied:
        logging.info("Adding individual ancestor bundle price.")
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
            logging.warning(f"Price not found for item: {item}")
            final_items_to_display.append(f"{item} (價格未知)")

    logging.info(f"Calculated total price: {total_price} for display items: {final_items_to_display}")
    return total_price, final_items_to_display

# --- 輔助函數：處理預約請求 (記錄/通知 + 回覆客戶) ---
def handle_booking_request(user_id, service_name_or_list, total_price=None, reply_token=None):
    """處理預約請求，包括單項非數字價格服務和多項法事總結"""
    
    is_ritual_summary = isinstance(service_name_or_list, list)

    if is_ritual_summary: # 法事總結
        service_display = "\n".join([f"- {item}" for item in service_name_or_list]) if service_name_or_list else "未選擇項目"
        price_display = f"NT${total_price}" if total_price is not None else "計算錯誤"
        log_service = f"法事組合 ({len(service_name_or_list)}項)"
    else: # 單項服務
        service_display = service_name_or_list
        price_display = f"NT${SERVICE_FEES.get(service_name_or_list, '洽詢')}"
        log_service = service_name_or_list

    # --- 通知老師 (包含最終項目和總價) ---
    notification_base_text = (f"【服務請求】\n"
                              f"用戶ID: {user_id}\n" 
                              f"服務項目:\n{service_display}\n"
                              f"費用: {price_display}\n"
                              f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        notify_teacher(notification_base_text)
    except Exception as e:
        logging.error(f"Failed to notify teacher: {e}")

    # --- 回覆客戶 ---
    if is_ritual_summary: # 法事總結回覆
        if not service_name_or_list: 
            reply_text_to_user = "您尚未選擇任何法事項目。請重新操作。"
        else:
            # 這裡產生包含總價和匯款資訊的回覆
            reply_text_to_user = f"您已選擇以下法事項目：\n{service_display}\n\n"
            reply_text_to_user += f"總費用：{price_display}\n\n"
            reply_text_to_user += "法事將於下個月由老師擇日統一進行。\n"
            reply_text_to_user += "請您完成匯款後告知末五碼，以便老師為您安排：\n"
            reply_text_to_user += f"銀行代碼：{payment_details['bank_code']}\n"
            reply_text_to_user += f"銀行名稱：{payment_details['bank_name']}\n"
            reply_text_to_user += f"帳號：{payment_details['account_number']}\n\n"
            reply_text_to_user += "感謝您的預約！"
    else: # 單項服務回覆
        reply_text_to_user = f"感謝您預約「{service_display}」服務。\n"
        reply_text_to_user += f"費用：{price_display}\n\n"
        reply_text_to_user += "老師將盡快與您聯繫，確認服務細節。"

    # --- 發送回覆與主選單 ---
    send_message(user_id, TextMessage(text=reply_text_to_user), reply_token)
    main_menu_message = create_main_menu_message()
    send_message(user_id, main_menu_message)

# --- Webhook 主要處理函式 ---
@app.route("/callback", methods=['POST'])
def callback():
    if handler is None:
        logging.error("Webhook handler is not initialized. Check LINE_CHANNEL_SECRET.")
        abort(500)

    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("Invalid signature. Please check your channel access token/secret.")
        abort(400)
    except Exception as e:
        logging.error(f"Error handling webhook: {e}")
        abort(500)

    return 'OK'

# --- 處理訊息事件 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    reply_content = None

    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot reply.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 检查是否是法事相关关键词
        if user_message in ["法事", "預約法事", "法會", "解冤親", "補財庫", "補桃花"]:
            # 直接进入法事流程
            user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
            logging.info(f"用户 {user_id} 输入法事关键词：{user_message}，直接进入法事选择")
            reply_content = create_ritual_selection_message(user_id)
            notify_teacher("有使用者查詢了法事項目。")
            
        elif user_message in ["服務", "服務項目", "功能", "選單", "menu"]:
            reply_content = create_main_services_flex()
        elif user_message in ["如何預約", "預約", "預約諮詢", "命理問事", "算命"]:
            reply_content = create_booking_submenu_flex()
            notify_teacher("有使用者查詢了預約服務選項。")
        elif user_message in booking_submenu:
            # 如果選擇「問事」，顯示日期選擇器
            if user_message == "問事":
                reply_content = TemplateMessage(
                    alt_text="請選擇您的生日",
                    template=ButtonsTemplate(
                        text=booking_submenu[user_message],
                        actions=[
                            DatetimePickerAction(
                                label="選擇生日",
                                data="action=select_birthday",
                                mode="date",
                                initial="1990-01-01",
                                max="2025-12-31",
                                min="1900-01-01"
                            ),
                            create_return_to_menu_button()
                        ]
                    )
                )
            else:
                reply_content = create_text_with_menu_button(
                    booking_submenu[user_message],
                    alt_text=user_message
                )
            notify_teacher(f"有使用者查詢了 {user_message} 服務。")
        elif user_message.startswith("選擇法事: "):
            # 記錄使用者的法事選擇
            selected_ritual = user_message.replace("選擇法事: ", "")
            logging.info(f"用户通过消息选择法事: {selected_ritual}")
            
            # 確保使用者狀態初始化
            if user_id not in user_states:
                user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
                logging.info(f"初始化用户状态: {user_states[user_id]}")
            
            # 切换选择状态：如果已选择则移除，如果未选择则添加
            current_selection = user_states[user_id]["data"]["selected_rituals"]
            if selected_ritual in current_selection:
                current_selection.remove(selected_ritual)
                logging.info(f"从选择中移除: {selected_ritual}")
            else:
                current_selection.append(selected_ritual)
                logging.info(f"添加到选择: {selected_ritual}")
            
            # 只发送更新后的法事选择界面，不发送文本回复
            reply_content = create_ritual_selection_message(user_id)
            
        elif user_message == "完成法事選擇" or user_message == "完成選擇":
            logging.info(f"用户完成法事选择")
            if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                selected_rituals = user_states[user_id]["data"]["selected_rituals"]
                logging.info(f"用户已选择: {selected_rituals}")
                
                if not selected_rituals:
                    reply_content = TextMessage(text="您尚未選擇任何法事項目，請先選擇項目後再完成。")
                    logging.info("用户未选择任何项目")
                else:
                    # 计算总价并处理预约
                    total_price, final_item_list = calculate_total_price(selected_rituals)
                    handle_booking_request(user_id, final_item_list, total_price, event.reply_token)
                    
                    # 清除状态
                    if user_id in user_states:
                        del user_states[user_id]
                    
                    # 这里不设置reply_content，因为handle_booking_request会发送回复
                    return
            else:
                reply_content = TextMessage(text="您尚未開始選擇法事，請先輸入「法事」")
                logging.info("用户未处于法事选择状态")
        
        elif user_message == "確認法事費用":
            reply_content = create_payment_info_message()
        elif user_message in ["匯款", "匯款資訊", "帳號"]:
            reply_content = create_payment_info_message()
            logging.info("显示匯款信息")
        elif user_message in ["IG"]:
            text_to_reply = other_services_keywords["IG"]
            reply_content = create_text_with_menu_button(text_to_reply, alt_text="IG")
            notify_teacher("有使用者查詢了 Instagram 連結。")
        elif user_message in ["開運物", "課程"]:
            text_to_reply = other_services_keywords[user_message]
            reply_content = create_text_with_menu_button(text_to_reply, alt_text=user_message)
            notify_teacher(f"有使用者查詢了 {user_message}。")
        elif user_message in other_services_keywords:
            text_to_reply = other_services_keywords[user_message]
            reply_content = create_text_with_menu_button(text_to_reply, alt_text=user_message)
        elif "你好" in user_message or "hi" in user_message.lower() or "hello" in user_message.lower():
            hello_text = "您好！很高興為您服務。\n請問需要什麼協助？\n您可以輸入「服務項目」查看我們的服務選單。"
            reply_content = create_text_with_menu_button(hello_text, alt_text="問候")
            notify_teacher("有使用者查詢了問候。")
        elif user_message.startswith("時辰: "):
            # 使用者選擇了時辰
            selected_time = user_message.replace("時辰: ", "")
            birthday = user_birthday_data.get(user_id)

            if birthday:
                # 將生日和時辰傳送給老師
                message_to_teacher = f"使用者 {user_id} 提交了命理問事資訊：\n生日：{birthday}\n時辰：{selected_time}"
                notify_teacher(message_to_teacher)

                # 回覆使用者
                reply_content = create_text_with_menu_button(
                    "您的資訊已提交給老師，老師會盡快回覆您！",
                    alt_text="提交成功"
                )

                # 清除臨時儲存的生日資料
                user_birthday_data.pop(user_id, None)

        if reply_content:
            try:
                # 如果 reply_content 是列表（多個訊息），則逐一發送
                if isinstance(reply_content, list):
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=reply_content
                        )
                    )
                else:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[reply_content]
                        )
                    )
            except Exception as e:
                logging.error(f"Error sending reply message: {e}")

# --- 處理 Postback 事件（包含所有按鈕回調） ---
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    reply_content = None

    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot handle postback.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        try:
            # 嘗試解析 JSON 格式的 postback data
            postback_data = json.loads(event.postback.data)
            action = postback_data.get('action')
        except (json.JSONDecodeError, TypeError):
            # 非 JSON 格式或為老式格式 (如生日選擇器)
            postback_data = event.postback.data
            action = None
        
        # --- 處理生日選擇 ---
        if postback_data == "action=select_birthday":
            # 使用者選擇了生日，儲存生日並顯示時辰選擇
            birthday = event.postback.params['date']
            user_birthday_data[user_id] = birthday

            # 顯示時辰選擇的 Quick Reply
            quick_reply_items = [
                QuickReplyItem(
                    action=MessageAction(
                        label=period["label"],
                        text=f"時辰: {period['value']}"
                    )
                ) for period in time_periods
            ]
            quick_reply_items.append(
                QuickReplyItem(
                    action=create_return_to_menu_button()
                )
            )

            reply_content = TextMessage(
                text="請選擇您的出生時辰：\n2300-0059 子 | 0100-0259 丑\n0300-0459 寅 | 0500-0659 卯\n0700-0859 辰 | 0900-1059 巳\n1100-1259 午 | 1300-1459 未\n1500-1659 申 | 1700-1859 酉\n1900-2059 戌 | 2100-2259 亥",
                quick_reply=QuickReply(items=quick_reply_items)
            )
        
        # --- 處理：選擇服務 (預約或問事) ---
        elif action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service == "法事":
                # 初始化法事選擇狀態
                user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
                logging.info(f"State set for user {user_id}: selecting_rituals")
                reply_content = create_ritual_selection_message(user_id) # 顯示法事選擇畫面
            # ... (其他服務的處理)

        # *** 修改处：处理选择具体法事项目后 (加入/移除选择) ***
        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            if selected_ritual:
                app.logger.info(f"User {user_id} selected ritual item: {selected_ritual}")
                # 更新用户状态中的已选列表
                if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals":
                    # 如果状态不对，重新开始选择
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": [selected_ritual]}}
                    app.logger.warning(f"User {user_id} was not in selecting_rituals state, resetting.")
                else:
                    # 切换选择状态：如果已经选择了，就移除；如果未选择，就添加
                    current_selection = user_states[user_id]["data"]["selected_rituals"]
                    if selected_ritual in current_selection:
                        current_selection.remove(selected_ritual)
                        app.logger.info(f"Removed '{selected_ritual}' from selection for {user_id}")
                    else:
                        current_selection.append(selected_ritual)
                        app.logger.info(f"Added '{selected_ritual}' to selection for {user_id}")
                
                # 更新法事选择界面，但不发送简短回复
                selection_menu = create_ritual_selection_message(user_id)
                reply_message = selection_menu  # 只发送更新后的选择界面
            else:
                app.logger.warning(f"Postback 'select_ritual_item' missing ritual for user {user_id}")
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的法事項目。")
                follow_up_message = create_main_menu_message()

        # --- 處理完成法事選擇 ---
        elif action == 'confirm_rituals':
            if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                selected_rituals = user_states[user_id].get("data", {}).get("selected_rituals", [])
                logging.info(f"User {user_id} confirmed rituals: {selected_rituals}")
                if not selected_rituals:
                    # 提示用戶尚未選擇
                    alert_text = TextMessage(text="您尚未選擇任何法事項目，請選擇後再點擊完成。")
                    selection_menu = create_ritual_selection_message(user_id)
                    reply_content = [alert_text, selection_menu]
                else:
                    # 計算總價並處理預約
                    total_price, final_item_list = calculate_total_price(selected_rituals)
                    handle_booking_request(user_id, final_item_list, total_price)
                    # 清除狀態
                    if user_id in user_states:
                        del user_states[user_id]
        
        # --- 處理確認付款 ---
        elif action == 'confirm_payment':
            logging.info(f"用户 {user_id} 确认法事并准备付款")
            if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                selected_rituals = user_states[user_id]["data"]["selected_rituals"]
                
                if selected_rituals:
                    # 计算总价
                    total_price, final_item_list = calculate_total_price(selected_rituals)
                    logging.info(f"确认付款: 总价 {total_price}，项目 {final_item_list}")
                    
                    # 保存选择的项目和价格，用于后续匯款核对
                    user_states[user_id]["data"]["total_price"] = total_price
                    user_states[user_id]["data"]["final_items"] = final_item_list
                    user_states[user_id]["state"] = "waiting_payment"
                    
                    # 显示匯款信息
                    reply_content = create_payment_info_message()
                    logging.info("发送匯款信息")
                else:
                    reply_content = TextMessage(text="您尚未選擇任何法事項目，請重新操作。")
                    logging.warning("用户尝试确认空的法事选择")
            else:
                reply_content = TextMessage(text="無法找到您的法事選擇記錄，請重新操作。")
                logging.warning(f"用户 {user_id} 不在法事选择状态但尝试确认付款")
                
        # --- 處理其他 action ---
        elif action == 'show_main_menu':
            reply_content = create_main_services_flex()

        # --- 發送回覆 ---
        if reply_content:
            try:
                # 如果 reply_content 是列表（多個訊息），則逐一發送
                if isinstance(reply_content, list):
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=reply_content
                        )
                    )
                else:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[reply_content]
                        )
                    )
            except Exception as e:
                logging.error(f"Error sending reply message: {e}")

# --- 處理加入好友事件 ---
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    followed_users.add(user_id)
    logging.info(f"User {user_id} followed the bot.")
    notify_teacher(f"有新使用者加入好友：{user_id}")

    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send follow message.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        welcome_text = """歡迎加入【宇宙玄天院】！

宇宙玄天院｜開啟靈性覺醒的殿堂

本院奉玄天上帝為主神，由雲真居士領導修持道脈，融合儒、釋、道三教之理與現代身心靈智慧，致力於指引眾生走GARAGE上自性覺醒與命運轉化之路。

主要服務項目包含：
• 命理諮詢（數字易經、八字、問事）
• 風水勘察與調理
• 補財庫、煙供、生基、安斗、等客製化法會儀軌
• 點燈祈福、開運蠟燭
• 命理課程與法術課程

本院深信：每一個靈魂都能連結宇宙本源，找到生命的方向與力量。讓我們陪伴您走向富足、自主與心靈的圓滿之路。

請點擊下方選單查看詳細服務項目與資訊！"""
        welcome_message = TextMessage(text=welcome_text)
        services_flex = create_main_services_flex()

        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[welcome_message, services_flex]
                )
            )
            logging.info(f"Successfully sent welcome message to user {user_id}")
        except Exception as e:
            logging.error(f"Error sending follow message to user {user_id}: {e}")
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="歡迎加入宇宙玄天院！請輸入「服務項目」查看選單。")]
                )
            )

# --- 主程式入口 ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if not channel_access_token or not channel_secret:
        logging.error("Missing required LINE environment variables (TOKEN or SECRET). Exiting.")
        exit()
    if not teacher_user_id:
        logging.warning("TEACHER_USER_ID is not set. Notifications to teacher will not work.")

    # 設定圖文選單
    setup_rich_menu()

    # 設定每周一發送運勢文的排程
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_weekly_fortune,
        CronTrigger(day_of_week='mon', hour=9, minute=0)  # 每周一上午9點
    )
    scheduler.start()

    port = int(os.environ.get('PORT', 5000))
    logging.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
>>>>>>> 6525685fb5b1dbcb3ace258657b3b1b09cd0f0f6
