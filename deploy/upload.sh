#!/bin/bash
# ローカルからサーバーにコードをアップロードするスクリプト
# 使い方: bash deploy/upload.sh <サーバーのIPアドレス>
# 例:     bash deploy/upload.sh 132.145.xx.xx

SERVER_IP=$1
if [ -z "$SERVER_IP" ]; then
  echo "使い方: bash deploy/upload.sh <IPアドレス>"
  exit 1
fi

PROJECT_DIR="$HOME/auto-invest"
SSH_USER="ubuntu"   # Oracle Cloud Ubuntu のデフォルトユーザー

echo "=== $SERVER_IP にアップロード中... ==="

# dataディレクトリとdeployディレクトリを除いてアップロード
rsync -avz --progress \
  --exclude 'data/' \
  --exclude 'deploy/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.git/' \
  "$(dirname "$0")/../" \
  "${SSH_USER}@${SERVER_IP}:${PROJECT_DIR}/"

echo ""
echo "=== アップロード完了 ==="
echo "サーバーで以下を実行:"
echo "  sudo systemctl restart bot-short bot-medium bot-long bot-dashboard"
