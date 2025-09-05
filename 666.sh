#!/bin/bash

# ---------- 1. 创建目录 ----------
PANEL_DIR="/root/ssh_panel"
mkdir -p "$PANEL_DIR"
cd "$PANEL_DIR" || { echo "进入目录失败"; exit 1; }

# ---------- 2. 下载文件 ----------
BASE_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main"

FILES=("app.py" "hosts.json" "deploy_ssh_panel_config.sh")
TEMPLATES=("index.html")

# 下载主文件
for file in "${FILES[@]}"; do
    curl -fsSL "$BASE_URL/$file" -O || { echo "下载 $file 失败"; exit 1; }
done

# 下载 templates 目录
mkdir -p templates
for file in "${TEMPLATES[@]}"; do
    curl -fsSL "$BASE_URL/$file" -o "templates/$file" || { echo "下载 templates/$file 失败"; exit 1; }
done

# ---------- 3. 设置权限 ----------
chmod 755 deploy_ssh_panel_config.sh

# ---------- 4. 执行部署脚本 ----------
sudo ./deploy_ssh_panel_config.sh
