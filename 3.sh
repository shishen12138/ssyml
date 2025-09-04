#!/bin/bash

# ---------------- 错误检查 ----------------
set -e  # 出错立即退出
LOG_FILE="/var/log/startup_script.log"
exec > >(tee -a "$LOG_FILE") 2>&1  # 将输出记录到日志文件

# ---------------- 下载目标脚本并保存到 /root/startup.sh ----------------
echo "下载脚本..."
RETRY_COUNT=0
MAX_RETRIES=5
URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
DEST="/root/startup.sh"

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
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

# ---------------- 赋予脚本 777 权限 ----------------
echo "赋予脚本 777 权限..."
if ! chmod 777 "$DEST"; then
    echo "赋予权限失败，退出脚本"
    exit 1
fi

# ---------------- 创建 systemd 服务文件 ----------------
echo "创建 systemd 服务..."
cat > /etc/systemd/system/startup.service <<EOL
[Unit]
Description=Startup Script
After=network.target

[Service]
Type=simple
ExecStart=/root/startup.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOL

# ---------------- 重新加载 systemd 配置 ----------------
echo "重新加载 systemd 配置..."
if ! systemctl daemon-reload; then
    echo "重新加载 systemd 配置失败，退出脚本"
    exit 1
fi

# ---------------- 设置服务开机自启并启动 ----------------
echo "设置开机自启并启动服务..."
if ! systemctl enable startup.service; then
    echo "设置开机自启失败，退出脚本"
    exit 1
fi

# ---------------- 延时30秒后执行脚本 ----------------
echo "设置延时30秒后执行脚本..."
cat > /etc/systemd/system/startup-delay.service <<EOL
[Unit]
Description=Startup Script with Delay
After=network.target

[Service]
Type=simple
ExecStart=/root/startup.sh
Restart=on-failure
ExecStartPre=/bin/sleep 30

[Install]
WantedBy=multi-user.target
EOL

# ---------------- 重新加载 systemd 配置 ----------------
echo "重新加载 systemd 配置..."
if ! systemctl daemon-reload; then
    echo "重新加载 systemd 配置失败，退出脚本"
    exit 1
fi

# ---------------- 设置服务开机自启并启动 ----------------
echo "设置开机自启并启动延时服务..."
if ! systemctl enable startup-delay.service; then
    echo "设置开机自启失败，退出脚本"
    exit 1
fi

if ! systemctl start startup-delay.service; then
    echo "启动延时服务失败，退出脚本"
    exit 1
fi

# ---------------- 完成 ----------------
echo "脚本下载、保存并设置为开机自启后，已设置延时执行！"
