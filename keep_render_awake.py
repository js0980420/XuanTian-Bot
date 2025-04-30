import requests
import time

RENDER_URL = "https://xuantian-line-bot.onrender.com"

while True:
    try:
        response = requests.get(RENDER_URL)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Ping! 狀態碼: {response.status_code}")
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Ping 失敗: {e}")
    time.sleep(720)  # 12分鐘 = 720秒 