import os
import json
import datetime
import time
import logging
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from linebot import LineBotApi
from linebot.models import TextSendMessage
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# LINE Bot API 設定
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# 接收通知的使用者 ID 列表（管理者）
ADMIN_USER_IDS = os.environ.get('ADMIN_USER_IDS', '').split(',')

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

def get_tomorrow_events():
    """獲取明天的所有事件"""
    service = get_google_calendar_service()
    if not service:
        logger.error("無法連接Google日曆")
        return None
    
    # 設定查詢時間範圍（明天）
    tomorrow = datetime.datetime.now(TW_TIMEZONE).date() + datetime.timedelta(days=1)
    start_time = datetime.datetime.combine(tomorrow, datetime.time.min).astimezone(TW_TIMEZONE)
    end_time = datetime.datetime.combine(tomorrow, datetime.time.max).astimezone(TW_TIMEZONE)
    
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
        return events
    except Exception as e:
        logger.error(f"獲取日曆事件時出錯：{str(e)}")
        return None

def get_monthly_events():
    """獲取本月固定行程"""
    service = get_google_calendar_service()
    if not service:
        logger.error("無法連接Google日曆")
        return None
    
    # 設定查詢時間範圍（本月）
    now = datetime.datetime.now(TW_TIMEZONE)
    first_day = datetime.datetime(now.year, now.month, 1).astimezone(TW_TIMEZONE)
    
    # 計算下個月的第一天
    if now.month == 12:
        next_month = datetime.datetime(now.year + 1, 1, 1).astimezone(TW_TIMEZONE)
    else:
        next_month = datetime.datetime(now.year, now.month + 1, 1).astimezone(TW_TIMEZONE)
    
    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=first_day.isoformat(),
            timeMax=next_month.isoformat(),
            singleEvents=False,  # 獲取重複事件
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        return events
    except Exception as e:
        logger.error(f"獲取月度事件時出錯：{str(e)}")
        return None

def send_daily_reminder():
    """發送明天行程提醒"""
    events = get_tomorrow_events()
    
    if not events:
        message = "明天沒有任何預約或行程安排。"
    else:
        message = "明天的行程安排：\n\n"
        for idx, event in enumerate(events, 1):
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', '未命名事件')
            
            # 將時間格式化
            try:
                if 'T' in start:  # 日期時間格式
                    start_dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.datetime.fromisoformat(end.replace('Z', '+00:00'))
                    start_fmt = start_dt.astimezone(TW_TIMEZONE).strftime('%H:%M')
                    end_fmt = end_dt.astimezone(TW_TIMEZONE).strftime('%H:%M')
                    time_str = f"{start_fmt}-{end_fmt}"
                else:  # 僅日期格式
                    time_str = "全天"
            except Exception:
                time_str = f"{start}-{end}"
                
            message += f"{idx}. {time_str} {summary}\n"
    
    # 發送訊息給管理者
    for user_id in ADMIN_USER_IDS:
        if user_id:
            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=message)
                )
                logger.info(f"已發送每日提醒給用戶 {user_id}")
            except Exception as e:
                logger.error(f"發送訊息給用戶 {user_id} 時出錯：{str(e)}")

def is_in_mainland_china(month):
    """檢查指定月份是否在大陸地區"""
    return month == 4

def send_monthly_status():
    """發送月度狀態更新"""
    now = datetime.datetime.now(TW_TIMEZONE)
    current_month = now.month
    
    # 檢查是否在大陸
    if is_in_mainland_china(current_month):
        message = f"{current_month}月命理師在大陸地區，無法進行法事，請知悉。"
        
        # 發送訊息給管理者
        for user_id in ADMIN_USER_IDS:
            if user_id:
                try:
                    line_bot_api.push_message(
                        user_id,
                        TextSendMessage(text=message)
                    )
                    logger.info(f"已發送月度狀態給用戶 {user_id}")
                except Exception as e:
                    logger.error(f"發送訊息給用戶 {user_id} 時出錯：{str(e)}")

def main_scheduler():
    """主排程函數，每天運行一次"""
    logger.info("開始運行排程")
    
    # 發送明天的行程提醒
    send_daily_reminder()
    
    # 如果是月初（1號），發送月度狀態
    now = datetime.datetime.now(TW_TIMEZONE)
    if now.day == 1:
        send_monthly_status()
    
    logger.info("排程完成")

if __name__ == "__main__":
    # 可以直接運行這個腳本進行測試
    main_scheduler()
    
    # 實際部署時，可以使用以下代碼每天自動執行
    # while True:
    #     main_scheduler()
    #     # 等待到明天同一時間
    #     now = datetime.datetime.now(TW_TIMEZONE)
    #     tomorrow = now.replace(day=now.day+1, hour=8, minute=0, second=0, microsecond=0)
    #     if tomorrow.day == 1:  # 處理月末情況
    #         tomorrow = tomorrow.replace(month=tomorrow.month+1, day=1)
    #         if tomorrow.month == 1:  # 處理年末情況
    #             tomorrow = tomorrow.replace(year=tomorrow.year+1)
    #     sleep_seconds = (tomorrow - now).total_seconds()
    #     logger.info(f"等待 {sleep_seconds} 秒後執行下一次排程")
    #     time.sleep(sleep_seconds) 
