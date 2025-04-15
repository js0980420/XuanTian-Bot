import os
import json
import datetime
from flask import Flask, request, abort, render_template
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, ButtonComponent, MessageAction
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz

app = Flask(__name__)

# LINE Bot API 設定
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
calendar_id = os.environ.get('GOOGLE_CALENDAR_ID', '')

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

def get_google_calendar_service():
    """獲取Google Calendar API服務"""
    json_str = os.environ.get('GOOGLE_CREDENTIALS', '')
    if not json_str:
        return None
    
    credentials_info = json.loads(json_str)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=credentials)
    return service

def check_availability(date):
    """檢查指定日期的可用性"""
    service = get_google_calendar_service()
    if not service:
        return "無法連接Google日曆，請稍後再試"
    
    # 設定查詢時間範圍
    start_time = datetime.datetime.combine(date, datetime.time.min).astimezone(TW_TIMEZONE)
    end_time = datetime.datetime.combine(date, datetime.time.max).astimezone(TW_TIMEZONE)
    
    start_time_str = start_time.isoformat()
    end_time_str = end_time.isoformat()
    
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time_str,
            timeMax=end_time_str,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"{date.strftime('%Y-%m-%d')} 命理師有空，可以預約"
        else:
            busy_times = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                busy_times.append(f"{start}~{end}")
            
            return f"{date.strftime('%Y-%m-%d')} 命理師已有預約：{'、'.join(busy_times)}"
    except Exception as e:
        return f"檢查日曆時出錯：{str(e)}"

def is_in_mainland_china(date):
    """檢查是否在大陸地區（4月）"""
    if date.month == 4:
        return True
    return False

def create_flex_message(title, text):
    """創建Flex訊息"""
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text=title, weight="bold", size="xl"),
                TextComponent(text=text, wrap=True, margin="md")
            ]
        )
    )
    return FlexSendMessage(alt_text=title, contents=bubble)

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook回調函數"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """處理文字訊息"""
    text = event.message.text
    reply_text = None
    
    # 檢查日期格式（例如：2023-05-15）
    if text.startswith('查詢 '):
        try:
            date_str = text.split(' ')[1]
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # 檢查是否在大陸
            if is_in_mainland_china(date):
                reply_text = f"{date_str} 命理師在大陸地區，無法進行法事，請選擇其他日期"
            else:
                reply_text = check_availability(date)
                
        except (ValueError, IndexError):
            reply_text = "日期格式不正確，請使用「查詢 YYYY-MM-DD」格式"
    
    # 關於法事的資訊
    elif '法事' in text:
        reply_text = (
            "本命理館提供各種法事服務：\n"
            "1. 祈福化煞儀式\n"
            "2. 財運開運法事\n"
            "3. 姻緣助力法事\n"
            "4. 事業升遷法事\n\n"
            "請注意：4月期間命理師在大陸，無法進行法事"
        )
    
    # 關於命理的資訊
    elif '命理' in text:
        reply_text = (
            "本命理館提供以下命理服務：\n"
            "1. 八字命盤分析\n"
            "2. 流年運勢解析\n"
            "3. 五行缺失調理\n"
            "4. 事業財運分析\n"
            "5. 姻緣分析\n\n"
            "歡迎使用「查詢 YYYY-MM-DD」格式查詢可預約時間"
        )
    
    # 關於開運物的資訊
    elif '開運' in text:
        reply_text = (
            "本命理館提供多種開運物品：\n"
            "1. 招財符咒\n"
            "2. 開運手鍊\n"
            "3. 化煞吊飾\n"
            "4. 五行調和香氛\n\n"
            "所有開運物品均由命理師親自開光加持"
        )
    
    # 預設回覆
    else:
        reply_text = (
            "您好，感謝聯繫本命理館。請輸入以下關鍵字了解更多：\n"
            "- 「命理」了解命理服務\n"
            "- 「法事」了解法事服務\n"
            "- 「開運」了解開運物品\n"
            "- 「查詢 YYYY-MM-DD」查詢預約時間"
        )
    
    # 發送訊息
    if reply_text:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

@app.route('/')
def home():
    """首頁"""
    return render_template('index.html')

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 