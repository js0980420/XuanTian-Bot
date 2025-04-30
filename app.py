# -*- coding: utf-8 -*-

import os
import json
import logging
from dotenv import load_dotenv # 建議使用 python-dotenv 管理環境變數
import time
import traceback
from datetime import datetime

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
    TemplateMessage, ButtonsTemplate,
    PostbackAction
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent, # 處理加入好友事件
    PostbackEvent # 處理 Postback 事件
)

# --- 新增 APScheduler --- 
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
# ----------------------

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
    "最新消息": "老師已從廣州買玉結束順利返台，可於下個月正常安排法事。",
    "課程介紹": "我們提供命理與法術相關課程，（此處可放課程詳細介紹、開課時間、報名方式等）。\n詳情請洽詢...",
    "探索自我": "透過『順流致富』測驗，了解您的天賦與命格，開啟豐盛人生！\n[請在此處放入測驗連結]",
    "IG": f"追蹤我們的 Instagram：{ig_link}", # 使用變數
    "抖音": "https://www.tiktok.com/@userm1m3m4m9?_t=ZS-8vwra2PWsxU&_r=1" # 老師的抖音連結
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

# --- 問事/命理諮詢須知（與圖片完全一致） ---
CONSULTATION_INFO_TEXT = '''【問事/命理諮詢須知】

問事費用：NT$600 (不限制時間與問題，但一定要詳細！)

請準備以下資訊，並直接在此聊天室中一次提供：
1. ✅姓名
2. ✅國曆生日 (年/月/日，請提供身分證上的出生年月日)
3. ✅出生時間 (請提供幾點幾分，例如 14:30 或 23:15，若不確定請告知大概時段如「晚上」或「接近中午」)
4. ✅想詢問的問題 (請盡量詳細描述人、事、時、地、物，越詳細越好)
5. ✅照片需求：
   🔵問感情：請提供雙方姓名、生日、合照。
   🔵問其他事情：請提供個人清晰的雙手照片。

✅匯款資訊：
🌟銀行：822 中國信託
🌟帳號：510540490990

感恩😊 老師收到您的完整資料與匯款後，會以文字+語音訊息回覆您。
資料留完後請耐心等待，老師通常三天內會完成回覆，感恩🙏''' # 移除最後的詢問句

# --- 按鈕產生函式 ---
def create_return_to_menu_button():
    """產生返回主選單的 MessageAction 按鈕，改為跳到如何預約"""
    return MessageAction(label='返回主選單', text='如何預約')

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
                    action=MessageAction(label='IG', text='IG'),
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

def create_ritual_prices_flex():
    """產生法事項目與費用的 Flex Message (加入返回主選單按鈕)"""
    contents = [
        FlexText(text='法事項目與費用', weight='bold', size='xl', color='#5A3D1E', align='center', margin='md'),
        FlexText(text='\n【法事項目分類說明】\n官司、考運、身體、小人 → 冤親\n財運、事業、防破財 → 補財庫\n感情、貴人、客戶、桃花 → 補桃花\n\n如有特別因素請私訊老師👋', size='sm', color='#888888', wrap=True, margin='md')
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

    # *** 直接顯示匯款資訊 ***
    contents.append(FlexText(text='【匯款資訊】', weight='bold', size='md', margin='lg'))
    contents.append(FlexText(
        text=f"🌟銀行：{payment_details['bank_code']} {payment_details['bank_name']}\n🌟帳號：{payment_details['account_number']}",
        size='sm', color='#555555', wrap=True, margin='sm'
    ))
    contents.append(FlexText(text='（匯款後請告知末五碼以便核對）', size='xs', color='#888888', margin='sm'))

    # *** 加入按鈕到 Footer ***
    footer_buttons = [
        FlexButton(
            action=PostbackAction(
                label="預約法事",
                data=json.dumps({"action": "show_ritual_selection"}, ensure_ascii=False)
            ),
            style="primary",
            color="#8C6F4E",
            height="sm"
        ),
        FlexButton(
            action=create_return_to_menu_button(),
            style='link',
            height='sm',
            color='#555555'
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

def create_how_to_book_flex():
    """產生如何預約的 Flex Message 選單（簡短版，含多功能按鈕，分段排版）"""
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[
                FlexText(text='如何預約 / 資訊查詢', weight='bold', size='xl', color='#5A3D1E', align='center')
            ]
        ),
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(
                    text='【如何預約】\n感謝您的信任與支持！🙏\n請直接點選下方服務按鈕，依照指示操作即可完成預約。\n\n✅ 問事通常三天內會回覆，感恩您的耐心等候。\n\n✅ 每週五會發送【改運小妙招】給您，敬請期待！\n\n如有疑問，歡迎隨時詢問，我們很樂意為您服務！🌟',
                    wrap=True, size='sm', color='#333333'
                )
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
                    style='primary',
                    color='#8C6F4E',
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
                    action=MessageAction(label='風水', text='風水'),
                    style='secondary',
                    color='#EFEBE4',
                    height='sm'
                ),
                 FlexSeparator(margin='md'),
                # 新增按鈕
                FlexButton(
                    action=MessageAction(label='最新消息', text='最新消息'),
                    style='link',
                    height='sm',
                    color='#555555'
                ),
                FlexButton(
                    # 這裡暫時使用 MessageAction，未來可改為 URIAction 跳轉測驗網址
                    action=MessageAction(label='探索自我(順流致富)', text='探索自我'),
                    style='link',
                    height='sm',
                    color='#555555'
                ),
                FlexSeparator(margin='md'),
                FlexButton(
                    action=create_return_to_menu_button(),
                    style='link',
                    height='sm',
                    color='#555555'
                ),
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'body': {'paddingAll': 'lg'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='如何預約/資訊查詢', contents=bubble)

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
def le_message(event):
    """處理文字訊息"""
    user_message = event.message.text.strip() # 去除前後空白
    user_id = event.source.user_id # 取得使用者 ID (保留，可能未來其他地方會用到)

    # 檢查 Line Bot API 設定是否有效
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot reply.")
        return # 無法回覆

    msg = user_message.replace(' ', '').replace('　', '').lower()

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        reply_content = []

        if "法事" in msg:
            reply_content.append(create_ritual_selection_message(user_id))
        if "問事" in msg or "命理" in msg:
            reply_content.append(TextMessage(text=CONSULTATION_INFO_TEXT))
            reply_content.append(create_text_with_menu_button(
                "🙏 感恩您的提問！老師通常三天內會回覆您，如還有其他需求，歡迎點選下方『返回主選單』繼續提問或預約其他服務 😊",
                alt_text="服務結束提醒"
            ))
        if "預約" in msg or "如何預約" in msg or "命理問事" in msg or "算命" in msg:
            reply_content.append(create_how_to_book_flex())
        if "收驚" in msg:
            reply_content.append(TextMessage(text="【收驚服務說明】\n收驚適合：驚嚇、睡不好、精神不安等狀況。\n請詳細說明您的狀況與需求，老師會依情況協助。\n\n老師通常三天內會回覆您，感恩您的耐心等候。"))
            reply_content.append(create_text_with_menu_button(
                "🙏 感恩您的提問！如還有其他需求，歡迎點選下方『返回主選單』繼續提問或預約其他服務 😊",
                alt_text="服務結束提醒"
            ))
        if "卜卦" in msg:
            reply_content.append(TextMessage(text="【卜卦服務說明】\n卜卦適合：人生抉擇、疑難雜症、重要決定等。\n請詳細說明您的問題與背景，老師會依情況協助。\n\n老師通常三天內會回覆您，感恩您的耐心等候。"))
            reply_content.append(create_text_with_menu_button(
                "🙏 感恩您的提問！如還有其他需求，歡迎點選下方『返回主選單』繼續提問或預約其他服務 😊",
                alt_text="服務結束提醒"
            ))
        if "風水" in msg:
            reply_content.append(TextMessage(text="【風水服務說明】\n風水適合：居家、辦公室、店面等空間調理。\n請詳細說明您的需求與空間狀況，老師會依情況協助。\n\n老師通常三天內會回覆您，感恩您的耐心等候。"))
            reply_content.append(create_text_with_menu_button(
                "🙏 感恩您的提問！如還有其他需求，歡迎點選下方『返回主選單』繼續提問或預約其他服務 😊",
                alt_text="服務結束提醒"
            ))
        if "匯款" in msg or "匯款資訊" in msg or "帳號" in msg:
            payment_text = f"""【匯款資訊】\n🌟 匯款帳號：\n銀行代碼：{payment_details['bank_code']}\n銀行名稱：{payment_details['bank_name']}\n帳號：{payment_details['account_number']}\n\n（匯款後請告知末五碼以便核對）"""
            reply_content.append(create_text_with_menu_button(payment_text, alt_text="匯款資訊"))
        if "最新消息" in msg:
            reply_content.append(create_text_with_menu_button(other_services_keywords["最新消息"], alt_text="最新消息"))
        if "探索自我" in msg or "順流致富" in msg:
            explore_text = other_services_keywords["探索自我"].replace("[請在此處放入測驗連結]", "(測驗連結待提供)")
            reply_content.append(create_text_with_menu_button(explore_text, alt_text="探索自我"))
        if "開運產品" in msg or "開運物" in msg:
            text_to_reply = other_services_keywords["開運產品"]
            reply_content.append(create_text_with_menu_button(text_to_reply, alt_text="開運產品"))
        if "課程" in msg:
            reply_content.append(create_text_with_menu_button(other_services_keywords["課程介紹"], alt_text="課程介紹"))
        if "ig" in msg:
            reply_content.append(create_text_with_menu_button(other_services_keywords["IG"], alt_text="IG"))
        if "抖音" in msg:
            reply_content.append(create_text_with_menu_button(other_services_keywords["抖音"], alt_text="抖音"))
        if "運勢文" in msg:
            reply_content.append(create_text_with_menu_button(other_services_keywords["運勢文"], alt_text="運勢文"))
        if "查詢可預約時間" in msg:
            if google_calendar_id and google_credentials_json_path:
                try:
                    calendar_response_text = "查詢可預約時間功能開發中..."
                    reply_content.append(create_text_with_menu_button(calendar_response_text, alt_text="查詢可預約時間"))
                except Exception as e:
                    logging.error(f"Error accessing Google Calendar: {e}")
                    error_text = "查詢可預約時間失敗，請稍後再試。"
                    reply_content.append(create_text_with_menu_button(error_text, alt_text="查詢錯誤"))
            else:
                error_text = "Google Calendar 設定不完整，無法查詢預約時間。"
                reply_content.append(create_text_with_menu_button(error_text, alt_text="設定錯誤"))

        # 如果沒有任何關鍵字被觸發，回覆預設訊息
        if not reply_content:
            reply_content = [TextMessage(text="老師三天內會親自回覆您，還有什麼需要幫忙的地方嗎？"), create_how_to_book_flex()]

        # --- 發送回覆 ---
        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_content
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
            logging.info(f"處理 postback 事件: 用戶 {user_id}, 動作 {action}")
        except (json.JSONDecodeError, TypeError):
            # 非 JSON 格式或為老式格式 (如生日選擇器)
            postback_data = event.postback.data
            action = None
            logging.info(f"處理非 JSON 格式 postback: {postback_data}")
        
        # --- 處理生日選擇 ---
        if postback_data == "action=select_birthday":
            # ... 現有代碼 ...
            pass
        
        # --- 處理：選擇法事項目 ---
        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            logging.info(f"用戶 {user_id} 選擇法事項目: {selected_ritual}")
            
            if selected_ritual:
                # 確保用戶狀態初始化
                if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals":
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
                    logging.info(f"初始化用戶狀態: {user_states[user_id]}")
                
                # 切換選擇狀態：如果已選擇則移除，如果未選擇則添加
                current_selection = user_states[user_id]["data"]["selected_rituals"]
                if selected_ritual in current_selection:
                    current_selection.remove(selected_ritual)
                    logging.info(f"從選擇中移除: {selected_ritual}")
                else:
                    current_selection.append(selected_ritual)
                    logging.info(f"添加到選擇: {selected_ritual}")
                
                # 立即發送更新後的法事選擇界面
                updated_menu = create_ritual_selection_message(user_id)
                
                # 使用事件的回覆 token 直接回覆更新的選單
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[updated_menu]
                        )
                    )
                    logging.info(f"已發送更新後的法事選擇介面給用戶 {user_id}")
                    return  # 直接返回，避免後續的回覆處理
                except Exception as e:
                    logging.error(f"回覆法事選擇介面時出錯: {e}")
            else:
                logging.warning(f"Postback 'select_ritual_item' 缺少法事項目，用戶 {user_id}")
                reply_content = TextMessage(text="發生錯誤，無法識別您選擇的法事項目。")
        
        # --- 處理完成法事選擇 ---
        elif action == 'confirm_rituals':
            if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                selected_rituals = user_states[user_id].get("data", {}).get("selected_rituals", [])
                logging.info(f"用戶 {user_id} 確認法事選擇: {selected_rituals}")
                
                if not selected_rituals:
                    # 提示用戶尚未選擇
                    alert_text = TextMessage(text="您尚未選擇任何法事項目，請選擇後再點擊完成。")
                    selection_menu = create_ritual_selection_message(user_id)
                    
                    try:
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[alert_text, selection_menu]
                            )
                        )
                        return  # 直接返回，避免後續的回覆處理
                    except Exception as e:
                        logging.error(f"回覆提示消息時出錯: {e}")
                else:
                    # 計算總價並處理預約
                    total_price, final_item_list = calculate_total_price(selected_rituals)
                    
                    # 生成詳細的確認訊息
                    confirmation_text = f"您已選擇以下法事項目：\n"
                    for item in final_item_list:
                        price = SERVICE_FEES.get(item, "洽詢")
                        confirmation_text += f"• {item} - NT${price}\n"
                    confirmation_text += f"\n總費用：NT${total_price}\n"
                    confirmation_text += "\n法事將於下個月由老師擇日統一進行。\n"
                    confirmation_text += "請完成匯款後告知末五碼，以便老師為您安排。\n"
                    confirmation_text += f"\n🌟銀行代碼：{payment_details['bank_code']}  {payment_details['bank_name']}\n"
                    confirmation_text += f"🌟帳號：{payment_details['account_number']}\n"
                    confirmation_text += "\n🙏 感恩您的信任！如還有其他需求，歡迎點選下方『返回主選單』繼續提問或預約其他服務 😊"
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[
                                create_text_with_menu_button(confirmation_text, alt_text="法事預約完成")
                            ]
                        )
                    )
                    if user_id in user_states:
                        del user_states[user_id]
                    return
            else:
                reply_content = TextMessage(text="請先選擇法事項目。")
                
        # --- 處理其他 action ---
        elif action == 'show_ritual_selection':
            ritual_menu = create_ritual_selection_message(user_id)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[ritual_menu]
                )
            )
            return

# --- 處理加入好友事件 ---
@handler.add(FollowEvent)
def handle_follow(event):
    """當使用者加入好友時發送歡迎訊息與按鈕選單"""
    user_id = event.source.user_id
    followed_users.add(user_id) # 將新用戶 ID 加入集合
    logging.info(f"User {user_id} followed the bot. Current followed users: {len(followed_users)}")

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

# --- 狀態管理 ---
# 儲存所有加入好友的使用者 ID（模擬資料庫 - 注意：服務重啟會遺失）
followed_users = set()

# 儲存使用者的生日（臨時儲存，等待時辰選擇）
user_birthday_data = {}

# 統一使用 user_states 進行狀態管理 (替代 user_ritual_selections)
user_states = {}

# --- 每周運勢文群發 --- 
def send_weekly_fortune():
    """向所有已加入好友的用戶推播每周運勢文"""
    # !!! 注意：這裡的 fortune_text 需要您定期手動更新，或從外部來源讀取 !!!
    fortune_text = "【本週改運小妙招】\n(此處放置本週運勢/改運妙招內容...)\n\n祝您有美好的一週！"
    
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot send weekly fortune.")
        return
    
    logging.info(f"準備發送每周運勢文給 {len(followed_users)} 位用戶...")
    successful_sends = 0
    failed_sends = 0
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        # 複製一份 set 來迭代，避免在迭代過程中修改 set 導致錯誤
        current_followed_users = followed_users.copy() 
        for user_id in current_followed_users:
            try:
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=fortune_text)]
                    )
                )
                logging.info(f"已發送每周運勢文給用戶: {user_id}")
                successful_sends += 1
                time.sleep(0.1) # 稍微延遲，避免觸發速率限制
            except Exception as e:
                logging.error(f"發送每周運勢文給 {user_id} 時出錯: {e}")
                failed_sends += 1
                # 可以考慮在這裡處理錯誤，例如將失敗的 user_id 記錄下來
                # 或從 followed_users 中移除無效的 user_id (需要更謹慎的錯誤判斷)
                
    logging.info(f"每周運勢文發送完成。成功: {successful_sends}, 失敗: {failed_sends}")

# --- 設定圖文選單 ---
def setup_rich_menu():
    if not channel_access_token:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN not found. Cannot set up rich menu.")
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 定義圖文選單結構 (6個按鈕)
        rich_menu_to_create = {
            "size": {
                "width": 2500,
                "height": 1686 # 適合 6 個按鈕的高度
            },
            "selected": True, # 預設顯示
            "name": "XuanTian_RichMenu_v2", # 給選單一個新名字
            "chatBarText": "服務選單",
            "areas": [
                {
                    "bounds": {"x": 0, "y": 0, "width": 833, "height": 843}, # 左上
                    "action": {"type": "message", "text": "如何預約"} 
                },
                {
                    "bounds": {"x": 833, "y": 0, "width": 834, "height": 843}, # 中上
                    "action": {"type": "message", "text": "問事"}
                },
                {
                    "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843}, # 右上
                    "action": {"type": "message", "text": "法事"}
                },
                {
                    "bounds": {"x": 0, "y": 843, "width": 833, "height": 843}, # 左下
                    "action": {"type": "message", "text": "開運物"} # 或其他您想放的
                },
                {
                    "bounds": {"x": 833, "y": 843, "width": 834, "height": 843}, # 中下
                    "action": {"type": "message", "text": "課程"}
                },
                {
                    "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843}, # 右下
                    "action": {"type": "uri", "uri": ig_link} # 直接連結到 IG
                    # 或者可以做成 postback action 打開一個包含 IG 和 TikTok 連結的選單
                    # "action": {"type": "postback", "data": "{\"action\":\"show_social_media\"}", "displayText": "社群平台"}
                }
            ]
        }

        try:
            # 0. 檢查是否已存在同名選單，若有則刪除舊的 (可選)
            existing_menus = line_bot_api.get_rich_menu_list()
            for menu in existing_menus:
                if menu.name == rich_menu_to_create["name"]:
                    logging.info(f"Deleting existing rich menu: {menu.rich_menu_id}")
                    line_bot_api.delete_rich_menu(menu.rich_menu_id)
                    break # 假設名字唯一

            # 1. 建立圖文選單物件
            rich_menu_response = line_bot_api.create_rich_menu(rich_menu_object=rich_menu_to_create)
            rich_menu_id = rich_menu_response.rich_menu_id
            logging.info(f"Rich menu created with ID: {rich_menu_id}")

            # 2. 上傳圖文選單圖片 (!!! 重要：您需要提供圖片 !!!)
            # 方法一：從本地文件上傳 (需要您將圖片放到項目目錄)
            image_path = "rich_menu_6grid.jpg" # 假設您的圖片檔名
            if os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    line_bot_api.set_rich_menu_image(
                        rich_menu_id=rich_menu_id,
                        content_type='image/jpeg', # 或 'image/png'
                        body=f.read()
                    )
                logging.info(f"Uploaded rich menu image from {image_path}")
            else:
                logging.warning(f"Rich menu image file not found at {image_path}. Please upload manually or provide the correct path.")
                # 您需要手動到 Line Developer 後台為這個 rich_menu_id 上傳圖片
            
            # 方法二：從 URL 上傳 (如果您的圖片在網路上)
            # image_url = "YOUR_IMAGE_URL_HERE"
            # import requests
            # response = requests.get(image_url, stream=True)
            # if response.status_code == 200:
            #     line_bot_api.set_rich_menu_image(
            #         rich_menu_id=rich_menu_id,
            #         content_type=response.headers['Content-Type'],
            #         body=response.raw
            #     )
            #     logging.info(f"Uploaded rich menu image from URL: {image_url}")
            # else:
            #     logging.error(f"Failed to download rich menu image from URL: {image_url}")

            # 3. 設定為預設圖文選單
            line_bot_api.set_default_rich_menu(rich_menu_id=rich_menu_id)
            logging.info(f"Set rich menu {rich_menu_id} as default.")

        except Exception as e:
            logging.error(f"Error setting up rich menu: {e}")
            logging.error(traceback.format_exc())

# --- 法事項目與價格對應表 ---
SERVICE_FEES = {
    "冤親債主（個人）": 680,
    "補桃花（個人）": 680,
    "補財庫（個人）": 680,
    "三合一（個人）": 1800,
    "祖先": 1800
}

# --- 法事選擇多選選單產生函式 ---
def create_ritual_selection_message(user_id):
    """產生法事多選選單（含已選項目打勾）"""
    selected = set(user_states.get(user_id, {}).get("data", {}).get("selected_rituals", []))
    all_items = ["冤親債主（個人）", "補桃花（個人）", "補財庫（個人）", "三合一（個人）", "祖先"]
    buttons = []
    for item in all_items:
        checked = "✅" if item in selected else ""
        label = f"{checked}{item} (NT${SERVICE_FEES.get(item,'洽詢')})"
        buttons.append(
            FlexButton(
                action=PostbackAction(
                    label=label,
                    data=json.dumps({"action": "select_ritual_item", "ritual": item}, ensure_ascii=False)
                ),
                style="primary" if item in selected else "secondary",
                color="#8C6F4E" if item in selected else "#EFEBE4",
                height="sm"
            )
        )
    # 完成選擇按鈕
    buttons.append(FlexButton(
        action=PostbackAction(
            label="完成選擇、計算價格",
            data=json.dumps({"action": "confirm_rituals"}, ensure_ascii=False)
        ),
        style="primary",
        color="#5A3D1E",
        height="sm"
    ))
    # 返回主選單
    buttons.append(FlexButton(
        action=create_return_to_menu_button(),
        style="link",
        height="sm",
        color="#555555"
    ))

    # 新增說明文字
    description = FlexText(
        text="【法事項目分類說明】\n官司、考運、身體、小人 → 冤親\n財運、事業、防破財 → 補財庫\n感情、貴人、客戶、桃花 → 補桃花\n\n如有特別因素請私訊老師👋\n\n請勾選您要預約的法事項目，可複選：",
        size="sm",
        color="#333333",
        wrap=True
    )

    bubble = FlexBubble(
        header=FlexBox(
            layout="vertical",
            contents=[FlexText(text="預約法事", weight="bold", size="xl", color="#5A3D1E", align="center")]
        ),
        body=FlexBox(
            layout="vertical",
            spacing="md",
            contents=[description] + buttons
        ),
        styles={"header": {"backgroundColor": "#EFEBE4"}, "body": {"paddingAll": "lg"}}
    )
    return FlexMessage(alt_text="預約法事", contents=bubble)

# --- 法事總價計算（含三合一自動合併）---
def calculate_total_price(selected_rituals):
    items = set(selected_rituals)
    # 三合一自動合併
    single_set = {"冤親債主（個人）", "補桃花（個人）", "補財庫（個人）"}
    if single_set.issubset(items):
        items -= single_set
        items.add("三合一（個人）")
    total = sum(SERVICE_FEES.get(item, 0) for item in items)
    return total, list(items)

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

    # --- 新增：嘗試設定圖文選單 --- 
    try:
        setup_rich_menu()
    except Exception as e:
        logging.error(f"Failed to setup rich menu during startup: {e}")
    # -----------------------------

    # --- 新增：設定每周五發送運勢文的排程 --- 
    scheduler = BackgroundScheduler(daemon=True) # daemon=True 允許主程序退出
    # 設定為每周五的上午 9:00 發送
    scheduler.add_job(send_weekly_fortune, CronTrigger(day_of_week='fri', hour=9, minute=0, timezone='Asia/Taipei'))
    scheduler.start()
    logging.info("APScheduler started for weekly fortune messages.")
    # ---------------------------------------

    port = int(os.environ.get('PORT', 5000))
    logging.info(f"Starting Flask server on port {port}")
    # 確保在生產環境中 debug=False
    app.run(host='0.0.0.0', port=port, debug=False)
