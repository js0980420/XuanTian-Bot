#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
自動部署腳本，完成以下步驟：
1. 提交代碼到本地git倉庫
2. 推送到GitHub遠程倉庫
3. 觸發Render自動部署（如果已配置）
"""

import os
import sys
import subprocess
import logging
from datetime import datetime

# 設置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 倉庫信息配置
# 請修改以下變量為您的實際值
GITHUB_REPO_URL = "https://github.com/js0980420/XuanTian-line-bot.git"  # 替換為您的GitHub倉庫URL
BRANCH_NAME = "main"  # 替換為您要推送的分支名稱
RENDER_DEPLOY_HOOK = "https://api.render.com/deploy/srv-cvurjkidbo4c73f6ln8g?key=QrrjwRCjC2w"  # 如果有Render的Deploy Hook URL，可以在這里設置

def run_command(command, cwd=None):
    """執行shell命令並返回結果"""
    logger.info(f"執行命令: {command}")
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            check=True, 
            text=True, 
            capture_output=True,
            cwd=cwd
        )
        if result.stdout:
            logger.info(result.stdout)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"命令執行失敗: {e}")
        if e.stderr:
            logger.error(e.stderr)
        return False, e.stderr

def check_git_installed():
    """檢查git是否已安裝"""
    success, _ = run_command("git --version")
    return success

def check_git_repo(repo_path):
    """檢查目錄是否為git倉庫"""
    return os.path.isdir(os.path.join(repo_path, ".git"))

def setup_git_repo(repo_path):
    """初始化git倉庫並設置遠程倉庫"""
    if not check_git_repo(repo_path):
        logger.info(f"在 {repo_path} 初始化git倉庫")
        run_command("git init", cwd=repo_path)
    
    # 檢查遠程倉庫是否已設置
    success, output = run_command("git remote -v", cwd=repo_path)
    if success and "origin" not in output:
        logger.info(f"設置遠程倉庫: {GITHUB_REPO_URL}")
        run_command(f"git remote add origin {GITHUB_REPO_URL}", cwd=repo_path)

def commit_changes(repo_path, commit_message=None):
    """提交所有更改到本地倉庫"""
    # 如果沒有提供commit消息，使用時間戳創建一個
    if not commit_message:
        commit_message = f"自動部署: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # 添加所有文件
    run_command("git add .", cwd=repo_path)
    
    # 創建提交
    success, _ = run_command(f'git commit -m "{commit_message}"', cwd=repo_path)
    return success

def push_to_github(repo_path):
    """推送更改到GitHub"""
    logger.info(f"推送更改到GitHub分支: {BRANCH_NAME}")
    success, output = run_command(f"git push -u origin {BRANCH_NAME}", cwd=repo_path)
    return success

def trigger_render_deploy():
    """觸發Render部署（如果配置了Deploy Hook）"""
    if RENDER_DEPLOY_HOOK:
        import requests
        logger.info("觸發Render部署")
        try:
            response = requests.get(RENDER_DEPLOY_HOOK)
            if response.status_code == 200:
                logger.info("Render部署已觸發")
                return True
            else:
                logger.error(f"觸發Render部署失敗: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"觸發Render部署時出錯: {e}")
            return False
    else:
        logger.info("沒有配置Render Deploy Hook，跳過觸發部署")
        logger.info("如果已在Render上配置了GitHub自動部署，代碼推送後會自動觸發部署")
        return True

def deploy(repo_path=None, commit_message=None):
    """
    執行完整的部署流程
    
    Args:
        repo_path: Git倉庫路徑，默認為當前目錄
        commit_message: 提交消息
    
    Returns:
        bool: 部署是否成功
    """
    # 默認使用當前目錄
    if not repo_path:
        repo_path = os.getcwd()
    
    logger.info(f"開始部署流程，倉庫路徑: {repo_path}")
    
    # 檢查git是否已安裝
    if not check_git_installed():
        logger.error("Git未安裝，無法繼續部署")
        return False
    
    # 設置git倉庫
    setup_git_repo(repo_path)
    
    # 提交更改
    if not commit_changes(repo_path, commit_message):
        logger.info("沒有新的更改需要提交，或提交失敗")
        return False
    
    # 推送到GitHub
    if not push_to_github(repo_path):
        logger.error("推送到GitHub失敗")
        return False
    
    # 觸發Render部署
    trigger_render_deploy()
    
    logger.info("部署流程完成")
    return True

if __name__ == "__main__":
    # 獲取命令行參數
    repo_path = os.getcwd()  # 默認為當前目錄
    commit_message = None
    
    # 解析命令行參數
    if len(sys.argv) > 1:
        if os.path.isdir(sys.argv[1]):
            repo_path = sys.argv[1]
        else:
            commit_message = sys.argv[1]
    
    if len(sys.argv) > 2:
        commit_message = sys.argv[2]
    
    # 執行部署
    success = deploy(repo_path, commit_message)
    
    if success:
        print("\n✅ 部署成功!")
    else:
        print("\n❌ 部署失敗，請查看日志。")
        sys.exit(1) 
