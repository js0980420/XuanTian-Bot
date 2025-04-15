# app.py
import os
import json
import datetime
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
    PostbackAction, # Added for button actions
    DatetimePickerAction # Added for date/time selection
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    PostbackEvent # Added to handle postback actions
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz

app = Flask(__name__)

# --- 基本設定 ---
# LINE Bot API 設定
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
channel_secret = os.getenv('LINE_CHANNEL_SECRET', '')
# Google Calendar API 設定
calendar_id = os.getenv('GOOGLE_CALENDAR_ID', '')
google_credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
# *** 新增：老師的 LINE User ID，用於接收預約通知 ***
teacher_user_id = os.getenv('TEACHER_USER_ID', '')

# --- 環境變數檢查 ---
# (與上次相同，檢查 channel_access_token, channel_secret, calendar_id, google_credentials_json, teacher_user_id)
if not channel_access_token or not channel_secret:
    print("錯誤：請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")
if not calendar_id:
    print("警告：未設定 GOOGLE_CALENDAR_ID 環境變數，無法查詢日曆")
if not google_credentials_json:
    print("警告：未設定 GOOGLE_CREDENTIALS_JSON 環境變數，無法連接 Google Calendar")
if not teacher_user_id:
    print("警告：未設定 TEACHER_USER_ID 環境變數，無法發送預約通知給老師")


# 初始化 LINE Bot API
configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# Google Calendar API 設定
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# 時區設定
TW_TIMEZONE = pytz.timezone('Asia/Taipei')

# --- Google Calendar 輔助函數 (與之前相同) ---
def get_google_calendar_service():
    """初始化並返回 Google Calendar API 的 service 物件"""
    if not google_credentials_json:
        print("錯誤：缺少 Google 憑證 JSON 環境變數")
        return None
    try:
        credentials_info = json.loads(google_credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except json.JSONDecodeError:
        print("錯誤：Google 憑證 JSON 格式錯誤")
        return None
    except Exception as e:
        print(f"連接 Google Calendar API 時發生錯誤: {e}")
        return None

# 此函數不再用於法事預約前的檢查，僅用於查詢範例或未來擴充
# def check_ritual_availability_on_date(target_date):
#     """
#     檢查指定日期是否因特殊行程 (如廣州行) 而無法進行 '法事'。
#     返回 True 表示 '可以' 進行法事，False 表示 '不可以'。
#     """
#     current_year = datetime.date.today().year
#     guangzhou_start = datetime.date(current_year, 4, 11)
#     guangzhou_end = datetime.date(current_year, 4, 22)
#     if guangzhou_start <= target_date <= guangzhou_end:
#         return False # 在廣州期間，不能做法事
#     return True

def get_calendar_events_for_date(target_date):
    """獲取指定日期的 Google 日曆事件列表"""
    service = get_google_calendar_service()
    if not service:
        return None # 無法連接服務

    try:
        start_time = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=TW_TIMEZONE)
        end_time = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=TW_TIMEZONE)

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        print(f"查詢日曆事件時發生錯誤 ({target_date}): {e}")
        return None # 查詢失敗

# --- LINE 事件處理函數 ---

@app.route("/callback", methods=['POST'])
def callback():
    """處理來自 LINE 的 Webhook 請求"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("簽名驗證失敗")
        abort(400)
    except Exception as e:
        print(f"處理訊息時發生錯誤: {e}")
        abort(500)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    """處理加好友事件，發送歡迎訊息 (移除匯款資訊和查詢格式)"""
    user_id = event.source.user_id
    print(f"User {user_id} added the bot.")

    current_year = datetime.date.today().year
    guangzhou_reminder_text = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停，詳情請輸入關鍵字查詢。'

    bubble = FlexBubble(
        body=FlexBox(
            layout='vertical',
            spacing='md',
            contents=[
                FlexText(text='宇宙玄天院 歡迎您！', weight='bold', size='xl', align='center', color='#B28E49'),
                FlexText(text='感謝您加入好友！我是您的命理小幫手。', wrap=True, size='sm', color='#555555'),
                FlexSeparator(margin='lg'),
                FlexText(text='您可以透過輸入關鍵字查詢服務：', wrap=True, size='md', margin='lg'),
                FlexText(text='🔹 預約 (預約老師服務)', size='md', margin='sm'), # 新增預約提示
                FlexText(text='🔹 問事 / 命理', size='md', margin='sm'),
                FlexText(text='🔹 法事', size='md', margin='sm'),
                FlexText(text='🔹 開運物', size='md', margin='sm'),
                FlexText(text='🔹 生基品', size='md', margin='sm'),
                FlexText(text='🔹 收驚', size='md', margin='sm'),
                FlexText(text='🔹 卜卦', size='md', margin='sm'),
                # 移除查詢格式提示
                FlexSeparator(margin='lg'),
                # 移除匯款資訊
                FlexText(text=guangzhou_reminder_text, wrap=True, size='xs', color='#E53E3E', margin='md')
            ]
        )
    )
    welcome_message = FlexMessage(alt_text='歡迎加入宇宙玄天院', contents=bubble)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.push_message(PushMessageRequest(
                to=user_id,
                messages=[welcome_message]
            ))
        except Exception as e:
            print(f"發送歡迎訊息失敗: {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理使用者傳送的文字訊息"""
    text = event.message.text.strip().lower()
    reply_message = None
    current_year = datetime.date.today().year

    # --- 處理「預約」關鍵字 ---
    if text == '預約':
        # 建立服務選擇的 Flex Message
        service_buttons = []
        bookable_services = ["問事/命理", "法事", "收驚", "卜卦"] # 可預約的服務列表
        for service in bookable_services:
            postback_data = json.dumps({"action": "select_service", "service": service})
            # 防止 data 過長 (LINE Postback data 限制 300 字元)
            if len(postback_data) > 300:
                 print(f"警告：Postback data 過長 ({len(postback_data)}): {postback_data}")
                 continue # 跳過此按鈕或進行縮減

            service_buttons.append(
                FlexButton(
                    action=PostbackAction(label=service, data=postback_data, display_text=f"我想預約：{service}"),
                    style='primary',
                    color='#A67B5B', # 調整顏色
                    margin='sm'
                )
            )

        bubble = FlexBubble(
            header=FlexBox(layout='vertical', contents=[
                FlexText(text='請選擇您想預約的服務', weight='bold', size='lg', align='center', color='#B28E49')
            ]),
            body=FlexBox(
                layout='vertical',
                spacing='md',
                contents=service_buttons
            )
            # 可以考慮加入 Footer 說明文字
        )
        reply_message = FlexMessage(alt_text='請選擇預約服務', contents=bubble)

    # --- 移除舊的「查詢」關鍵字處理 ---
    # elif text.startswith('查詢') and len(text.split()) == 2:
    #    ... (相關程式碼已移除) ...

    # --- 處理其他關鍵字 (法事說明移除匯款資訊) ---
    elif '法事' in text:
        guangzhou_ritual_reminder = f'❗️ {current_year}/4/11 至 {current_year}/4/22 老師在廣州，期間無法進行任何法事項目，敬請見諒。'
        ritual_bubble = FlexBubble(
            direction='ltr',
            header=FlexBox(
                layout='vertical',
                contents=[
                    FlexText(text='法事服務項目', weight='bold', size='xl', align='center', color='#B28E49')
                ]
            ),
            body=FlexBox(
                layout='vertical',
                spacing='md',
                contents=[
                    FlexText(text='旨在透過儀式調和能量，趨吉避凶。', size='sm', wrap=True, color='#555555'),
                    FlexSeparator(margin='lg'),
                    FlexText(text='主要項目', weight='bold', size='lg', margin='md'),
                    FlexText(text='🔹 冤親債主 (處理官司/考運/健康/小人)', wrap=True),
                    FlexText(text='🔹 補桃花 (助感情/貴人/客戶)', wrap=True),
                    FlexText(text='🔹 補財庫 (助財運/事業/防破財)', wrap=True),
                    FlexText(text='費用：單項 NT$680 / 三項合一 NT$1800', margin='sm', size='sm', weight='bold'),
                    FlexSeparator(margin='md'),
                    FlexText(text='🔹 祖先相關 (詳情請私訊)', wrap=True),
                    FlexText(text='費用：NT$1800 / 份', margin='sm', size='sm', weight='bold'),
                    FlexSeparator(margin='lg'),
                    # --- 移除匯款資訊 ---
                    # FlexText(text='匯款資訊', weight='bold', size='lg', color='#B28E49'),
                    # FlexText(text='🌟 銀行：822 中國信託'),
                    # FlexText(text='🌟 帳號：510540490990'),
                    # FlexSeparator(margin='lg'),
                    FlexText(text='⚠️ 特別提醒', weight='bold', color='#E53E3E'),
                    FlexText(text=guangzhou_ritual_reminder, wrap=True, size='sm', color='#E53E3E'),
                    FlexText(text='❓ 如有特殊需求或預約，請直接輸入「預約」關鍵字。', size='xs', margin='md', color='#777777', wrap=True) # 修改提示
                ]
            ),
            # Footer 可以移除或改為其他按鈕
            # footer=FlexBox(...)
        )
        reply_message = FlexMessage(alt_text='法事服務項目說明', contents=ritual_bubble)

    # --- 其他關鍵字處理 (問事/命理, 開運物, 生基品, 收驚, 卜卦) ---
    # (內容與上次相同，但移除查詢格式提示，並提醒使用「預約」)
    elif '問事' in text or '命理' in text:
        guangzhou_consult_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可透過線上方式進行問事或命理諮詢，歡迎預約。\n\n"
        reply_text = (
            "【問事/命理諮詢】\n"
            "服務內容包含八字命盤分析、流年運勢、事業財運、感情姻緣等。\n\n"
            + guangzhou_consult_reminder +
            "如需預約，請直接輸入「預約」關鍵字。"
        )
        reply_message = TextMessage(text=reply_text)

    elif '開運物' in text:
        guangzhou_shopping_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州採購加持玉器、水晶及各式開運飾品。\n🔹 如有特定需求或想預購，歡迎私訊老師。\n🔹 商品預計於老師回台後 ({current_year}/4/22之後) 陸續整理並寄出，感謝您的耐心等待！"
        reply_text = (
            "【開運物品】\n"
            "提供招財符咒、開運手鍊、化煞吊飾、五行調和香氛等，均由老師親自開光加持。\n\n"
            + guangzhou_shopping_reminder
        )
        reply_message = TextMessage(text=reply_text)

    elif '生基品' in text:
         guangzhou_shengji_reminder = f"🛍️ 最新消息：\n🔹 {current_year}/4/11 - {current_year}/4/22 老師親赴廣州尋找適合的玉器等生基相關用品。\n🔹 如有興趣或需求，歡迎私訊老師洽詢。\n🔹 相關用品預計於老師回台後 ({current_year}/4/22之後) 整理寄出。"
         reply_text = (
            "【生基用品】\n"
            "生基是一種藉由風水寶地磁場能量，輔助個人運勢的秘法。\n\n"
            "老師提供相關諮詢與必需品代尋服務。\n\n"
            + guangzhou_shengji_reminder
        )
         reply_message = TextMessage(text=reply_text)

    elif '收驚' in text:
        guangzhou_shoujing_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可提供遠距離線上收驚服務，效果一樣。\n\n"
        reply_text = (
            "【收驚服務】\n"
            "適用於受到驚嚇、心神不寧、睡眠品質不佳等狀況。\n\n"
            + guangzhou_shoujing_reminder +
            "如需預約，請直接輸入「預約」關鍵字。"
        )
        reply_message = TextMessage(text=reply_text)

    elif '卜卦' in text:
        guangzhou_bugua_reminder = f"🗓️ 老師行程：\n🔹 {current_year}/4/11 - {current_year}/4/22 期間老師在廣州，但仍可透過線上方式進行卜卦。\n\n"
        reply_text = (
            "【卜卦問事】\n"
            "針對特定問題提供指引，例如決策、尋物、運勢吉凶等。\n\n"
            + guangzhou_bugua_reminder +
             "如需預約，請直接輸入「預約」關鍵字。"
        )
        reply_message = TextMessage(text=reply_text)

    # --- 預設回覆 (如果不是已知關鍵字) ---
    else:
        if text != '預約': # 避免重複觸發
             default_guangzhou_reminder = f'🗓️ 特別提醒：{current_year}/4/11 至 {current_year}/4/22 老師在廣州，部分服務（如法事）暫停。'
             default_bubble = FlexBubble(
                body=FlexBox(
                    layout='vertical',
                    spacing='md',
                    contents=[
                        FlexText(text='宇宙玄天院 小幫手', weight='bold', size='lg', align='center', color='#B28E49'),
                        FlexText(text='您好！請問需要什麼服務？', wrap=True, size='md', margin='md'),
                        FlexText(text='請輸入以下關鍵字查詢：', wrap=True, size='sm', color='#555555', margin='lg'),
                        FlexText(text='🔹 預約 (預約老師服務)'), # 強調預約
                        FlexText(text='🔹 問事 / 命理'),
                        FlexText(text='🔹 法事'),
                        FlexText(text='🔹 開運物'),
                        FlexText(text='🔹 生基品'),
                        FlexText(text='🔹 收驚'),
                        FlexText(text='🔹 卜卦'),
                        FlexSeparator(margin='lg'),
                        FlexText(text=default_guangzhou_reminder, wrap=True, size='xs', color='#E53E3E', margin='md')
                    ]
                )
            )
             reply_message = FlexMessage(alt_text='歡迎使用服務', contents=default_bubble)

    # --- 發送回覆 ---
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[reply_message]
                    )
                )
            except Exception as e:
                print(f"回覆訊息失敗: {e}")


@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件 (來自 Flex Message 按鈕和 Datetime Picker)"""
    reply_message = None
    user_id = event.source.user_id
    postback_data_str = event.postback.data
    print(f"收到 Postback: User={user_id}, Data='{postback_data_str}'")

    try:
        postback_data = json.loads(postback_data_str)
        action = postback_data.get('action')

        # --- 處理：選擇服務後，跳出日期時間選擇器 ---
        if action == 'select_service':
            selected_service = postback_data.get('service')
            if selected_service:
                print(f"用戶 {user_id} 選擇了服務: {selected_service}")
                # 準備 Datetime Picker 的 Postback data
                picker_data = json.dumps({
                    "action": "select_datetime",
                    "service": selected_service
                })
                if len(picker_data) > 300:
                     print(f"警告：Datetime Picker data 過長 ({len(picker_data)}): {picker_data}")
                     reply_message = TextMessage(text="系統錯誤：選項資料過長，請稍後再試。")
                else:
                    # 設定日期選擇器的最小日期為今天
                    min_date = datetime.datetime.now(TW_TIMEZONE).strftime('%Y-%m-%d')

                    bubble = FlexBubble(
                        body=FlexBox(layout='vertical', contents=[
                            FlexText(text=f'您選擇了：{selected_service}', weight='bold', align='center', margin='md'),
                            FlexText(text='請選擇您希望預約的日期與時間', align='center', margin='md', size='sm'),
                            FlexButton(
                                action=DatetimePickerAction(
                                    label='📅 選擇日期時間',
                                    data=picker_data,
                                    mode='datetime', # 選擇日期+時間
                                    # initial='...', # 可選：初始顯示時間
                                    min=min_date # 限制最早只能選今天
                                    # max='...' # 可選：限制最晚日期
                                ),
                                style='primary',
                                color='#A67B5B',
                                margin='lg'
                            )
                        ])
                    )
                    reply_message = FlexMessage(alt_text='請選擇預約日期時間', contents=bubble)
            else:
                reply_message = TextMessage(text="發生錯誤，無法識別您選擇的服務。")

        # --- 處理：選擇日期時間後，進行預約檢查與通知 ---
        elif action == 'select_datetime':
            selected_service = postback_data.get('service')
            selected_datetime_str = event.postback.params.get('datetime')

            if selected_service and selected_datetime_str:
                print(f"用戶 {user_id} 預約服務 '{selected_service}' 時間 '{selected_datetime_str}'")
                try:
                    # 解析日期時間
                    selected_dt = datetime.datetime.fromisoformat(selected_datetime_str)
                    selected_date = selected_dt.date()
                    formatted_dt = selected_dt.astimezone(TW_TIMEZONE).strftime('%Y-%m-%d %H:%M')

                    # --- 可用性檢查 (僅針對法事) ---
                    proceed_booking = True
                    if selected_service == '法事':
                        print(f"檢查法事可用性：日期 {selected_date}")
                        events = get_calendar_events_for_date(selected_date)
                        if events is None:
                            # 日曆查詢失敗，可以選擇通知老師或提示用戶稍後再試
                            print(f"警告：無法查詢 {selected_date} 的日曆事件，暫時允許法事預約")
                            # reply_message = TextMessage(text="抱歉，暫時無法確認老師行程，請稍後再試或直接私訊老師。")
                            # proceed_booking = False
                        elif len(events) > 0:
                            print(f"法事預約衝突：{selected_date} 已有行程")
                            reply_message = TextMessage(text=f"抱歉，老師在 {selected_date.strftime('%Y-%m-%d')} 已有行程安排，暫無法進行法事，請選擇其他日期，謝謝。")
                            proceed_booking = False

                    # --- 若檢查通過或無需檢查 ---
                    if proceed_booking:
                        print(f"預約檢查通過，準備通知老師 (ID: {teacher_user_id})")
                        # 1. 發送通知給老師
                        if teacher_user_id:
                            notification_text = (
                                f"【新預約請求】\n"
                                f"--------------------\n"
                                f"用戶ID: {user_id}\n"
                                f"服務項目: {selected_service}\n"
                                f"預約時間: {formatted_dt}\n"
                                f"--------------------\n"
                                f"請盡快與用戶確認此預約！"
                            )
                            try:
                                with ApiClient(configuration) as api_client:
                                    line_bot_api = MessagingApi(api_client)
                                    line_bot_api.push_message(PushMessageRequest(
                                        to=teacher_user_id,
                                        messages=[TextMessage(text=notification_text)]
                                    ))
                                print("預約通知已發送給老師。")
                            except Exception as e:
                                print(f"錯誤：發送預約通知給老師失敗: {e}")
                                # 即使通知失敗，還是要回覆客戶
                        else:
                            print("錯誤：未設定老師的 User ID，無法發送預約通知！")
                            # 在此情況下，您需要有其他方式得知預約請求

                        # 2. 回覆客戶，告知請求已收到
                        reply_text_to_user = (
                            f"收到您的預約請求：\n"
                            f"服務：{selected_service}\n"
                            f"時間：{formatted_dt}\n\n"
                            f"此預約尚待老師確認，確認後會儘快與您聯繫，感謝您的耐心等候！"
                        )
                        reply_message = TextMessage(text=reply_text_to_user)

                except ValueError:
                    print(f"錯誤：解析日期時間失敗: {selected_datetime_str}")
                    reply_message = TextMessage(text="選擇的日期時間格式有誤，請重新操作。")
                except Exception as e:
                    print(f"處理 select_datetime 時發生未知錯誤: {e}")
                    reply_message = TextMessage(text="處理您的預約請求時發生錯誤，請稍後再試。")
            else:
                reply_message = TextMessage(text="發生錯誤，缺少預約服務或時間資訊。")

        # --- 可以加入其他 Postback Action 的處理 ---
        # elif action == '...':
        #    pass

        else:
            print(f"未知的 Postback Action: {action}")
            # 可以選擇不回覆或回覆通用錯誤訊息
            # reply_message = TextMessage(text="無法處理您的請求。")

    except json.JSONDecodeError:
        print(f"錯誤：無法解析 Postback data: {postback_data_str}")
        reply_message = TextMessage(text="系統無法處理您的請求，請稍後再試。")
    except Exception as e:
        print(f"處理 Postback 時發生未知錯誤: {e}")
        reply_message = TextMessage(text="系統發生錯誤，請稍後再試。")

    # --- 發送 Postback 的回覆 ---
    if reply_message:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                # Postback 沒有 reply_token，必須用 Push API 回覆
                # 但為了簡單起見，我們先嘗試用 Reply (如果 LINE 未來支援或在某些情境下可行)
                # 注意：標準作法是用 Push API 回覆 Postback event
                # line_bot_api.reply_message(...)
                # --- 使用 Push API 回覆 ---
                print(f"準備 Push 回覆給 {user_id}")
                line_bot_api.push_message(PushMessageRequest(
                    to=user_id,
                    messages=[reply_message]
                ))
            except Exception as e:
                print(f"回覆 Postback 訊息失敗: {e}")


# --- 主程式入口 ---
if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False) # 生產環境建議 debug=False
