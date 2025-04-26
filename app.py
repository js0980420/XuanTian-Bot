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
    QuickReply, QuickReplyItem
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

# 法事價格
ritual_prices_info = {
    "冤親債主/補桃花/補財庫": {"single": 680, "combo": 1800},
    "冤親債主": {"single": 680},
    "補桃花": {"single": 680},
    "補財庫": {"single": 680},
    "祖先": {"single": 1800}
}

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
    "法事": "請選擇您需要的法事項目，詳情可查看「法事項目與費用」。",
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

# 儲存所有加入好友的使用者 ID（模擬資料庫）
followed_users = set()

# 儲存使用者的生日（臨時儲存，等待時辰選擇）
user_birthday_data = {}

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

def create_ritual_prices_flex():
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
        contents.append(FlexText(text='特別說明：', size='sm', color='#888888', wrap=True, margin='md'))
        contents.append(FlexText(text='官司、考運、身體、小人 → 冤親債主', size='sm', color='#888888', wrap=True))
        contents.append(FlexText(text='財運、事業、防破財 → 補財庫', size='sm', color='#888888', wrap=True))
        contents.append(FlexText(text='感情、貴人、客戶、桃花 → 補桃花', size='sm', color='#888888', wrap=True))
        contents.append(FlexText(text='若有特殊需求，請私訊老師！', size='sm', color='#888888', wrap=True))

    contents.append(FlexSeparator(margin='xl'))
    footer_buttons = [
        FlexButton(
            action={'type': 'message', 'label': '了解匯款資訊', 'text': '匯款資訊'},
            style='primary',
            color='#8C6F4E',
            height='sm',
            margin='md'
        ),
        FlexSeparator(margin='md'),
        FlexButton(
            action=create_return_to_menu_button(),
            style='link',
            height='sm',
            color='#555555'
        )
    ]

    bubble = FlexBubble(
        body=FlexBox(layout='vertical', contents=contents),
        footer=FlexBox(layout='vertical', spacing='sm', contents=footer_buttons),
        styles={'body': {'backgroundColor': '#F9F9F9'}, 'footer': {'separator': True}}
    )
    return FlexMessage(alt_text='法事項目與費用', contents=bubble)

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
                PushMessageRequest
