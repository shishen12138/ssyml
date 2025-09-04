#!/bin/bash

# ---------------- 错误检查 ----------------
set -e  # 出错立即退出
LOG_FILE="/var/log/startup_script.log"
exec > >(tee -a "$LOG_FILE") 2>&1  # 将输出记录到日志文件

echo "----------------------------------"
echo "开始执行 startup.sh 脚本"
echo "----------------------------------"

# ---------------- 下载目标脚本并保存到 /root/startup.sh ----------------
echo "下载脚本..."
RETRY_COUNT=0
MAX_RETRIES=5
URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
DEST="/root/startup.sh"

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
    echo "第 $((RETRY_COUNT + 1)) 次尝试下载..."
    if wget -O "$DEST" "$URL"; then
        echo "脚本下载成功！"
        break
    else
        RETRY_COUNT=$((RETRY_COUNT+1))
        echo "脚本下载失败，正在重试...($RETRY_COUNT/$MAX_RETRIES)"
        sleep 5
    fi
done

if [[ $RETRY_COUNT -ge $MAX_RETRIES ]]; then
    echo "下载失败，退出脚本"
    exit 1
fi

echo "下载完成，保存至 $DEST"

# ---------------- 赋予脚本 755 权限 ----------------
echo "赋予脚本 755 权限..."
if ! chmod 755 "$DEST"; then
    echo "赋予权限失败，退出脚本"
    exit 1
fi
echo "权限赋予成功"

# ---------------- 创建 systemd 服务文件 ----------------
echo "创建 systemd 服务..."
cat > /etc/systemd/system/startup.service <<EOL
[Unit]
Description=Startup Script
After=network.target

[Service]
Type=forking  # 后台执行
ExecStart=/root/startup.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

echo "systemd 服务文件创建成功"

# ---------------- 重新加载 systemd 配置 ----------------
echo "重新加载 systemd 配置..."
if ! systemctl daemon-reload; then
    echo "重新加载 systemd 配置失败，退出脚本"
    exit 1
fi
echo "systemd 配置重新加载完成"

# ---------------- 设置服务开机自启并启动 ----------------
echo "设置开机自启并启动服务..."
if ! systemctl enable startup.service; then
    echo "设置开机自启失败，退出脚本"
    exit 1
fi
echo "设置开机自启成功"

# ---------------- 手动执行一次下载的脚本 ----------------
echo "手动执行一次下载的脚本..."
if ! /root/startup.sh; then
    echo "手动执行下载的脚本失败，退出脚本"
    exit 1
fi
echo "手动执行脚本成功"

# ---------------- 完成 ----------------
echo "脚本下载、保存并设置为开机自启后，已手动执行一次！"
echo "----------------------------------"
echo "startup.sh 脚本执行完成"
echo "----------------------------------"
