#!/bin/bash
set -e

SERVICE_NAME="miner.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
WORKDIR="/root"
LOG_FILE="$WORKDIR/miner.log"

echo "正在创建 systemd 服务..."

# 创建 systemd 服务文件
sudo bash -c "cat > $SERVICE_PATH <<EOF
[Unit]
Description=Auto start apoolminer script
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'wget -q $SCRIPT_URL -O - | bash >> $LOG_FILE 2>&1'
RemainAfterExit=true
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF"

echo "重新加载 systemd 配置..."
sudo systemctl daemon-reload

echo "启用开机自启动..."
sudo systemctl enable $SERVICE_NAME

echo "立即启动服务..."
sudo systemctl start $SERVICE_NAME

echo "操作完成 ✅"
echo "可以用以下命令查看状态和日志："
echo "  systemctl status $SERVICE_NAME"
echo "  tail -f $LOG_FILE"
