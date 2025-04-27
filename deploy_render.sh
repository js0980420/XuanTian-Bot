#!/bin/bash

# Render 部署腳本
pip install -r requirements.txt
gunicorn app:app 