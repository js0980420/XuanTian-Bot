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
                    action={'type': 'message', 'label': '如何預約', 'text': '如何預約'},
                    style='primary',
                    color='#8C6F4E', # 淺棕色
                    height='sm'
                ),
                FlexButton(
                    action={'type': 'message', 'label': '開運 生基 煙供產品', 'text': '開運產品'},
                    style='secondary',
                    color='#EFEBE4', # 米白色背景
                    height='sm'
                ),
                 FlexButton(
                    action=URIAction(label='追蹤我們的 IG', uri=ig_link), # 使用 URIAction 打開網頁
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                FlexButton(
                    action={'type': 'message', 'label': '法事項目與費用', 'text': '法事項目'},
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}} # 米白色背景
    )
    # 主選單本身不需要返回按鈕
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
    if handler is None:
        logging.error("Webhook handler is not initialized. Check LINE_CHANNEL_SECRET.")
        abort(500) # 內部伺服器錯誤

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)
    except Exception as e:
        print(f"Error handling webhook: {e}")
        logging.exception("Error handling webhook:") # 記錄詳細錯誤堆疊
        abort(500)

    return 'OK'

# --- 處理訊息事件 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
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
    print(f"User {user_id} followed the bot.") # 可以在後台紀錄
    notify_teacher("有新使用者加入好友。") # 通知老師有新好友

    # 檢查 Line Bot API 設定是否有效
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send follow message.")
        return # 無法發送

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        welcome_text = """歡迎加入【宇宙玄天院】！

宇宙玄天院｜開啟靈性覺醒的殿堂

本院奉玄天上帝為主神，由雲真居士領導修持道脈，融合儒、釋、道三教之理與現代身心靈智慧，致力於指引眾生走上自性覺醒與命運轉化之路。

主要服務項目包含：
•	命理諮詢（數字易經、八字、問事）
•	風水勘察與調理
•	補財庫、煙供、生基、安斗、等客製化法會儀軌
•	點燈祈福、開運蠟燭
•	命理課程與法術課程

本院深信：每一個靈魂都能連結宇宙本源，找到生命的方向與力量。讓我們陪伴您走向富足、自主與心靈的圓滿之路。

您可以點擊下方按鈕查看詳細服務項目與資訊："""
        welcome_message = TextMessage(text=welcome_text)

        services_flex = create_main_services_flex() # 主選單 Flex Message

        try:
            # 同時發送歡迎文字和 Flex Message 按鈕選單
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[welcome_message, services_flex] # 將文字和 Flex 一起發送
                )
            )
        except Exception as e:
            logging.error(f"Error sending follow message: {e}")


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

