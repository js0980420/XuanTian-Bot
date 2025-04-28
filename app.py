# -*- coding: utf-8 -*-

import os
import json
import logging
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    PushMessageRequest, TextMessage, FlexMessage, FlexContainer,
    FlexBubble, FlexBox, FlexText, FlexButton, FlexSeparator,
    URIAction, MessageAction, DatetimePickerAction, TemplateMessage, ButtonsTemplate,
    QuickReply, QuickReplyItem, PostbackAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, PostbackEvent

# 載入環境變數
load_dotenv()

# Line Bot 金鑰與老師ID
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')
teacher_user_id = os.getenv('TEACHER_USER_ID', None)

# Flask 與 Line Bot 設定
app = Flask(__name__)
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret) if channel_secret else None

# 主要服務與資訊
main_services_list = [
    "命理諮詢（數字易經、八字、問事）",
    "風水勘察與調理",
    "補財庫、煙供、生基、安斗等客製化法會儀軌",
    "點燈祈福、開運蠟燭",
    "命理課程與法術課程"
]

ig_link = "https://www.instagram.com/magic_momo9/"
other_services_keywords = {
    "開運物": "關於開運物，詳細資訊待更新，請稍後關注。",
    "課程": "關於命理與法術課程，詳細資訊待更新，請稍後關注。",
    "IG": f"追蹤我們的 Instagram：{ig_link}"
}

# 法事服務項目與價格
SERVICE_FEES = {
    "補財庫": 680,
    "煙供": 680,
    "生基": 680,
    "安斗": 1800
}
TRIPLE_COMBO_PRICE = 1800  # 三合一價格

# 匯款資訊
payment_details = {
    "bank_code": "822",
    "bank_name": "中國信託",
    "account_number": "510540490990"
}

# 如何預約說明
how_to_book_instructions = """【如何預約】
請選擇您需要的服務：
• 命理諮詢（線上通靈問事、八字、數字易經）
• 法事（補財庫、煙供、生基、安斗）
• 收驚
• 卜卦
• 風水勘察與調理
點擊對應按鈕進行預約！"""

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

# 狀態管理
user_states = {}
user_birthday_data = {}

# 按鈕與消息生成函數
def create_return_to_menu_button():
    return MessageAction(label='返回主選單', text='服務項目')

def create_main_services_flex():
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

def create_ritual_selection_message(user_id):
    if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals":
        user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
    
    selected_rituals = user_states[user_id]["data"]["selected_rituals"]
    buttons = []
    for ritual, price in SERVICE_FEES.items():
        is_selected = ritual in selected_rituals
        label = f"✅ {ritual} (NT${price})" if is_selected else f"{ritual} (NT${price})"
        buttons.append(FlexButton(
            action=PostbackAction(
                label=label,
                data=json.dumps({"action": "select_ritual_item", "ritual": ritual}),
                display_text=f"選擇：{ritual}"
            ),
            style='secondary' if is_selected else 'primary',
            color='#A67B5B' if not is_selected else '#DDDDDD',
            margin='sm',
            height='sm'
        ))
    
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[FlexText(text='法事選擇', weight='bold', size='lg', color='#B28E49', align='center')]
        ),
        body=FlexBox(
            layout='vertical',
            contents=[
                FlexText(text='請選擇法事項目：', size='sm', margin='md'),
                FlexSeparator(margin='md'),
                *buttons,
                FlexButton(
                    action=PostbackAction(label='完成選擇', data=json.dumps({"action": "confirm_rituals"})),
                    style='primary',
                    color='#8C6F4E',
                    margin='md',
                    height='sm'
                ),
                FlexButton(action=create_return_to_menu_button(), style='link', height='sm', color='#555555')
            ]
        )
    )
    return FlexMessage(alt_text='請選擇法事項目', contents=bubble)

def create_booking_submenu_flex():
    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical',
            contents=[FlexText(text='預約服務選項', weight='bold', size='xl', color='#5A3D1E', align='center')]
        ),
        body=FlexBox(
            layout='vertical',
            contents=[FlexText(text='請選擇服務類型：', wrap=True, size='sm', color='#333333'), FlexSeparator(margin='md')]
        ),
        footer=FlexBox(
            layout='vertical',
            spacing='sm',
            contents=[
                FlexButton(action=MessageAction(label='命理諮詢', text='命理諮詢'), style='primary', color='#8C6F4E', height='sm'),
                FlexButton(action=MessageAction(label='法事', text='法事'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='收驚', text='收驚'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='卜卦', text='卜卦'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=MessageAction(label='風水勘察與調理', text='風水勘察與調理'), style='secondary', color='#EFEBE4', height='sm'),
                FlexButton(action=create_return_to_menu_button(), style='link', height='sm', color='#555555')
            ]
        ),
        styles={'header': {'backgroundColor': '#EFEBE4'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='預約服務選項', contents=bubble)

def create_text_with_menu_button(text_content, alt_text="訊息"):
    buttons_template = ButtonsTemplate(text=text_content[:160], actions=[create_return_to_menu_button()])
    return TemplateMessage(alt_text=alt_text, template=buttons_template)

# 通知老師
def notify_teacher(message_text):
    if teacher_user_id and channel_access_token:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                line_bot_api.push_message(PushMessageRequest(to=teacher_user_id, messages=[TextMessage(text=message_text)]))
                logging.info(f"通知已發送給老師: {teacher_user_id}")
            except Exception as e:
                logging.error(f"通知老師失敗: {e}")

# 計算總價
def calculate_total_price(selected_rituals):
    if len(selected_rituals) == 3 and all(r in ["補財庫", "煙供", "生基"] for r in selected_rituals):
        return TRIPLE_COMBO_PRICE, ["三合一（補財庫、煙供、生基）"]
    total = sum(SERVICE_FEES.get(item, 0) for item in selected_rituals)
    return total, selected_rituals

# 處理預約請求
def handle_booking_request(user_id, service_name_or_list, total_price=None, reply_token=None):
    is_list = isinstance(service_name_or_list, list)
    service_display = "\n".join([f"- {item}" for item in service_name_or_list]) if is_list else service_name_or_list
    price_display = f"NT${total_price}" if total_price else "洽詢"
    
    notify_teacher(f"【預約請求】\n用戶ID: {user_id}\n服務: {service_display}\n費用: {price_display}")
    
    reply_text = f"您已預約：\n{service_display}\n費用：{price_display}\n老師將盡快聯繫您確認細節。"
    if is_list:
        reply_text += f"\n\n請完成匯款後告知末五碼：\n銀行代碼：{payment_details['bank_code']}\n銀行名稱：{payment_details['bank_name']}\n帳號：{payment_details['account_number']}"
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply_text), create_main_services_flex()]))

# Webhook 處理
@app.route("/callback", methods=['POST'])
def callback():
    if not handler:
        logging.error("Webhook handler 未初始化")
        abort(500)
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logging.error("簽名無效")
        abort(400)
    except Exception as e:
        logging.error(f"Webhook 處理錯誤: {e}")
        abort(500)
    return 'OK'

# 處理訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    reply_content = None

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if user_message in ["服務", "服務項目", "選單"]:
            reply_content = create_main_services_flex()
        elif user_message == "如何預約":
            reply_content = create_booking_submenu_flex()
        elif user_message == "問事" or user_message == "命理諮詢":
            reply_content = TemplateMessage(
                alt_text="請選擇生日",
                template=ButtonsTemplate(
                    text="請提供您的生日與時辰：",
                    actions=[DatetimePickerAction(label="選擇生日", data="action=select_birthday", mode="date", initial="1990-01-01", max="2025-12-31", min="1900-01-01")]
                )
            )
        elif user_message == "法事":
            reply_content = create_ritual_selection_message(user_id)
        elif user_message in ["IG", "開運物", "課程"]:
            reply_content = create_text_with_menu_button(other_services_keywords[user_message], alt_text=user_message)
        elif user_message in ["收驚", "卜卦", "風水勘察與調理"]:
            handle_booking_request(user_id, user_message, reply_token=event.reply_token)
            return
        elif user_message.startswith("問題: "):
            if user_id in user_birthday_data:
                birthday, time = user_birthday_data[user_id]
                question = user_message[4:]
                notify_teacher(f"【問事請求】\n用戶ID: {user_id}\n生日: {birthday}\n時辰: {time}\n問題: {question}")
                reply_content = TextMessage(text="您的問事資訊已提交，老師將盡快回覆！")
                del user_birthday_data[user_id]

        if reply_content:
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_content]))

# 處理 Postback
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    postback_data = json.loads(event.postback.data) if event.postback.data.startswith('{') else event.postback.data
    reply_content = None

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        if postback_data == "action=select_birthday":
            birthday = event.postback.params['date']
            user_birthday_data[user_id] = [birthday, None]
            quick_reply_items = [QuickReplyItem(action=MessageAction(label=p["label"], text=f"時辰: {p['value']}")) for p in time_periods]
            reply_content = TextMessage(text="請選擇您的出生時辰：", quick_reply=QuickReply(items=quick_reply_items))
        elif isinstance(postback_data, dict) and postback_data.get("action") == "select_ritual_item":
            ritual = postback_data["ritual"]
            if ritual in user_states.get(user_id, {}).get("data", {}).get("selected_rituals", []):
                user_states[user_id]["data"]["selected_rituals"].remove(ritual)
            else:
                user_states[user_id]["data"]["selected_rituals"].append(ritual)
            reply_content = create_ritual_selection_message(user_id)
        elif isinstance(postback_data, dict) and postback_data.get("action") == "confirm_rituals":
            selected_rituals = user_states[user_id]["data"]["selected_rituals"]
            total_price, final_items = calculate_total_price(selected_rituals)
            handle_booking_request(user_id, final_items, total_price, event.reply_token)
            del user_states[user_id]
            return

        if reply_content:
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_content]))

# 處理加入好友
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    notify_teacher(f"有新使用者加入好友：{user_id}")
    welcome_text = "歡迎加入宇宙玄天院！請輸入「服務項目」查看選單。"
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=welcome_text), create_main_services_flex()]))

# 主程式
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if not channel_access_token or not channel_secret:
        logging.error("缺少必要的 LINE 環境變數")
        exit()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
