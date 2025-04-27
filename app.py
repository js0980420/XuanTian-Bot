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
    buttons = []
    ritual_items = [
        "冤親債主 (個人)", "補桃花 (個人)", "補財庫 (個人)", "三合一 (個人)",
        "冤親債主 (祖先)", "補桃花 (祖先)", "補財庫 (祖先)", "三合一 (祖先)"
    ]
    # 獲取用戶當前已選項目
    current_selection = []
    if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
        current_selection = user_states[user_id]["data"].get("selected_rituals", [])

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

    bubble = FlexBubble(
        header=FlexBox(
            layout='vertical', 
            contents=[FlexText(text='預約法事', weight='bold', size='lg', align='center', color='#B28E49')]
        ),
        body=FlexBox(
            layout='vertical', 
            spacing='md', 
            contents=[
                FlexText(text=selected_text, wrap=True, size='sm', margin='md'),
                FlexSeparator(margin='lg'),
                *buttons # 將按鈕列表展開
            ]
        )
    )
    return FlexMessage(alt_text='請選擇法事項目', contents=bubble)

def create_payment_info_message():
    payment_text = f"""【匯款資訊】
🌟 匯款帳號：
銀行代碼：{payment_details['bank_code']}
銀行名稱：{payment_details['bank_name']}
帳號：{payment_details['account_number']}

（匯款後請點擊下方「匯款完成」按鈕並告知末五碼以便核對）"""
    return TemplateMessage(
        alt_text="匯款資訊",
        template=ButtonsTemplate(
            text=payment_text[:160],
            actions=[
                MessageAction(label='匯款完成', text='匯款完成'),
                create_return_to_menu_button()
            ]
        )
    )

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

        if user_message in ["服務", "服務項目", "功能", "選單", "menu"]:
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
        elif user_message in ["法事"]:
            # 初始化使用者的法事選擇
            user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
            reply_content = create_ritual_selection_message(user_id)
            notify_teacher("有使用者查詢了法事項目。")
        elif user_message.startswith("選擇法事: "):
            # 記錄使用者的法事選擇
            selected_ritual = user_message.replace("選擇法事: ", "")
            
            # 確保使用者狀態初始化
            if user_id not in user_states:
                user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": []}}
            
            # 模擬反白效果：如果已選擇則移除，否則添加
            current_selection = user_states[user_id]["data"]["selected_rituals"]
            if selected_ritual in current_selection:
                current_selection.remove(selected_ritual)
            else:
                current_selection.append(selected_ritual)
            
            reply_content = create_ritual_selection_message(user_id)
        elif user_message == "完成法事選擇":
            if user_id in user_states and user_states[user_id].get("state") == "selecting_rituals":
                selected_rituals = user_states[user_id]["data"]["selected_rituals"]
                total_price, final_item_list = calculate_total_price(selected_rituals)
                reply_content = create_text_with_menu_button(
                    f"您已選擇以下法事項目：\n{', '.join(final_item_list)}\n\n總費用：NT${total_price}",
                    alt_text="法事確認"
                )
        elif user_message == "確認法事費用":
            reply_content = create_payment_info_message()
        elif user_message == "匯款完成":
            if user_id in user_states and "selected_rituals" in user_states[user_id].get("data", {}):
                selections = user_states[user_id]["data"]["selected_rituals"]
                total_price, _ = calculate_total_price(selections)

                # 通知老師
                message_to_teacher = f"使用者 {user_id} 已完成匯款：\n選擇項目：{', '.join(selections)}\n總費用：NT$ {total_price}\n請等待使用者提供末五碼以核對。"
                notify_teacher(message_to_teacher)

                reply_content = create_text_with_menu_button(
                    "感謝您的匯款！請提供帳號末五碼以便核對。",
                    alt_text="匯款完成"
                )

                # 清除使用者的法事選擇
                if user_id in user_states:
                    del user_states[user_id]
            else:
                reply_content = create_text_with_menu_button(
                    "無法找到您的法事選擇記錄，請重新操作。",
                    alt_text="匯款完成"
                )
        elif user_message in ["匯款", "匯款資訊", "帳號"]:
            reply_content = create_payment_info_message()
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

        # --- 處理選擇具體法事項目 (加入/移除選擇) ---
        elif action == 'select_ritual_item':
            selected_ritual = postback_data.get('ritual')
            if selected_ritual:
                logging.info(f"User {user_id} toggled ritual item: {selected_ritual}")
                # 更新用戶狀態中的已選列表
                if user_id not in user_states or user_states[user_id].get("state") != "selecting_rituals":
                    # 理論上不該發生，但做個防呆
                    user_states[user_id] = {"state": "selecting_rituals", "data": {"selected_rituals": [selected_ritual]}}
                    logging.warning(f"User {user_id} was not in selecting_rituals state, resetting.")
                else:
                    current_selection = user_states[user_id]["data"]["selected_rituals"]
                    # 切換選擇狀態
                    if selected_ritual in current_selection:
                        current_selection.remove(selected_ritual)
                        logging.info(f"Removed '{selected_ritual}' from selection for {user_id}")
                    else:
                        current_selection.append(selected_ritual)
                        logging.info(f"Added '{selected_ritual}' to selection for {user_id}")
                # 重新顯示選擇畫面
                reply_content = create_ritual_selection_message(user_id)

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
