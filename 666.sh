#!/bin/bash

# ---------- 1. 创建目录 ----------
PANEL_DIR="/ssh_panel"
mkdir -p "$PANEL_DIR"
cd "$PANEL_DIR" || exit

# ---------- 2. 下载四个文件 ----------
BASE_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main"

FILES=("app.py" "templates/index.html" "hosts.json" "deploy_ssh_panel_config.sh")

# 创建 templates 目录
mkdir -p templates

for file in "${FILES[@]}"; do
    if [[ "$file" == "templates/index.html" ]]; then
        curl -o "templates/index.html" "$BASE_URL/templates/index.html"
    else
        curl -O "$BASE_URL/$file"
    fi
done

# ---------- 3. 设置权限 ----------
chmod 777 deploy_ssh_panel_config.sh

# ---------- 4. 执行部署脚本 ----------
sudo ./deploy_ssh_panel_config.sh
