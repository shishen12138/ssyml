#!/bin/bash

# ---------- 1. 创建目录 ----------
PANEL_DIR="/root/ssh_panel"
mkdir -p "$PANEL_DIR"
cd "$PANEL_DIR" || { echo "进入目录失败"; exit 1; }

# ---------- 2. 下载文件 ----------
BASE_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main"

FILES=("app.py" "hosts.json" "deploy_ssh_panel_config.sh")

# 下载主文件
for file in "${FILES[@]}"; do
    curl -fsSL "$BASE_URL/$file" -O || { echo "下载 $file 失败"; exit 1; }
done

# 下载 templates/index.html
mkdir -p templates
curl -fsSL "$BASE_URL/index.html" -o templates/index.html || { echo "下载 templates/index.html 失败"; exit 1; }

# ---------- 3. 设置权限 ----------
chmod 755 deploy_ssh_panel_config.sh

# ---------- 4. 执行部署脚本 ----------
sudo ./deploy_ssh_panel_config.sh
