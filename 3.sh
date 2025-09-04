#!/bin/bash

# ---------------- 错误检查 ----------------
set -e  # 出错立即退出
LOG_FILE="/var/log/startup_script.log"
exec > >(tee -a "$LOG_FILE") 2>&1  # 将输出记录到日志文件

# ---------------- 下载目标脚本并保存到 /usr/local/bin/startup.sh ----------------
echo "下载脚本..."
if ! wget -O /usr/local/bin/startup.sh https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh; then
    echo "脚本下载失败，退出脚本"
    exit 1
fi

# ---------------- 赋予脚本执行权限 ----------------
echo "赋予执行权限..."
if ! chmod +x /usr/local/bin/startup.sh; then
    echo "赋予执行权限失败，退出脚本"
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
ExecStart=/usr/local/bin/startup.sh
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

if ! systemctl start startup.service; then
    echo "启动服务失败，退出脚本"
    exit 1
fi

# ---------------- 手动执行一次下载的脚本 ----------------
echo "执行一次下载的脚本..."
if ! /usr/local/bin/startup.sh; then
    echo "手动执行下载的脚本失败，退出脚本"
    exit 1
fi

# ---------------- 完成 ----------------
echo "脚本下载、保存并设置为开机自启后，已手动执行一次！"
