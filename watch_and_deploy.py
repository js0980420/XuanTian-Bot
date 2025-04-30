#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件監視和自動部署腳本
監視指定文件的變更，當檢測到變更時自動觸發部署流程
"""

import os
import sys
import time
import logging
from datetime import datetime
import traceback

# 先檢查所需依賴
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    # 使用修復版的auto_deploy
    import auto_deploy_fixed as auto_deploy
except ImportError as e:
    print(f"錯誤: 缺少必要依賴項 - {e}")
    print("正在嘗試安裝依賴...")
    import subprocess
    subprocess.call([sys.executable, "-m", "pip", "install", "watchdog"])
    print("請重新運行此腳本")
    sys.exit(1)

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'file_watch.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 需要監視的文件和目錄
WATCH_PATHS = [
    'app.py',  # 主應用程序文件
    # 可以添加其他需要監視的文件或目錄
]

# 部署防抖時間（秒），避免頻繁部署
DEBOUNCE_TIME = 5

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_deploy_time = 0
        self.pending_changes = False
        self.repo_path = os.path.dirname(os.path.abspath(__file__))
        
    def on_any_event(self, event):
        try:
            # 忽略目錄事件和.git目錄下的事件
            if event.is_directory or '.git' in event.src_path:
                return

            # 檢查是否是我們需要監視的文件
            relative_path = os.path.relpath(event.src_path, self.repo_path)
            watch_file = False
            
            for path in WATCH_PATHS:
                if path in relative_path:
                    watch_file = True
                    break
                    
            if not watch_file:
                return
                
            logger.info(f"檢測到文件變更: {relative_path}, 事件類型: {event.event_type}")
            self.pending_changes = True
            
            # 防抖：等待一段時間後再部署，避免頻繁部署
            current_time = time.time()
            if (current_time - self.last_deploy_time) > DEBOUNCE_TIME:
                self.deploy()
        except Exception as e:
            logger.error(f"處理文件變更時出錯: {e}")
            logger.error(traceback.format_exc())
    
    def deploy(self):
        """執行部署流程"""
        if not self.pending_changes:
            return
            
        try:
            logger.info("開始自動部署流程...")
            commit_message = f"自動部署: 文件變更 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            success = auto_deploy.deploy(self.repo_path, commit_message)
            if success:
                logger.info("✓ 自動部署成功!")
            else:
                logger.error("× 自動部署失敗，請查看日誌")
            
            self.pending_changes = False
            self.last_deploy_time = time.time()
        except Exception as e:
            logger.error(f"執行部署時出錯: {e}")
            logger.error(traceback.format_exc())
            self.pending_changes = False  # 重置狀態，避免卡住

def start_watching():
    """啟動文件監視"""
    try:
        repo_path = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"啟動文件監視，工作目錄: {repo_path}")
        logger.info(f"監視文件: {', '.join(WATCH_PATHS)}")
        
        event_handler = FileChangeHandler()
        observer = Observer()
        
        # 設置觀察者
        observer.schedule(event_handler, repo_path, recursive=True)
        observer.start()
        
        try:
            logger.info("文件監視已啟動，按 Ctrl+C 停止")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("監視已停止")
            observer.stop()
        
        observer.join()
    except Exception as e:
        logger.error(f"啟動監視服務時出錯: {e}")
        logger.error(traceback.format_exc())
        return False
    return True

if __name__ == "__main__":
    print("啟動文件監視和自動部署服務...")
    try:
        logger.info("啟動文件監視和自動部署服務")
        if not start_watching():
            sys.exit(1)
    except Exception as e:
        print(f"錯誤: {e}")
        traceback.print_exc()
        sys.exit(1) 