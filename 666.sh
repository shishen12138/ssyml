#!/bin/bash

# ---------- 日志函数 ----------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# ---------- 1. 创建目录 ----------
PANEL_DIR="/root/ssh_panel"
log "开始创建目录: $PANEL_DIR"
mkdir -p "$PANEL_DIR" && log "目录创建成功: $PANEL_DIR" || { log "目录创建失败"; exit 1; }
cd "$PANEL_DIR" || { log "进入目录失败"; exit 1; }

# ---------- 2. 下载文件 ----------
BASE_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main"
FILES=("app.py" "hosts.json" "deploy_ssh_panel_config.sh")

log "开始下载主文件..."
for file in "${FILES[@]}"; do
    log "正在下载 $file ..."
    if curl -fsSL "$BASE_URL/$file" -O; then
        log "下载成功: $file"
    else
        log "下载失败: $file"
        exit 1
    fi
done

# 下载 templates/index.html
log "创建 templates 目录并下载 index_ws.html"
mkdir -p templates
if curl -fsSL "$BASE_URL/index_ws.html" -o templates/index_ws.html; then
    log "下载成功: templates/index_ws.html"
else
    log "下载失败: templates/index_ws.html"
    exit 1
fi

# ---------- 3. 设置权限 ----------
log "设置 deploy_ssh_panel_config.sh 权限为 755"
chmod 755 deploy_ssh_panel_config.sh && log "权限设置成功" || { log "权限设置失败"; exit 1; }

# ---------- 4. 执行部署脚本 ----------
log "执行部署脚本: deploy_ssh_panel_config.sh"
if sudo ./deploy_ssh_panel_config.sh; then
    log "部署脚本执行完成"
else
    log "部署脚本执行失败"
    exit 1
fi

log "SSH 面板部署完成 ✅"
