#!/bin/bash
set -e

# 参数
SERVICE_NAME="miner.service"
WATCHDOG_NAME="cpu-watchdog.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
WATCHDOG_PATH="/etc/systemd/system/$WATCHDOG_NAME"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
WORKDIR="/root"
LOG_FILE="$WORKDIR/miner.log"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"

echo "正在创建 miner.service ..."

# 创建 miner.service
sudo tee $SERVICE_PATH > /dev/null <<EOF
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
EOF

echo "正在创建 CPU Watchdog 脚本 ..."
# 创建 watchdog 脚本
sudo tee $WATCHDOG_SCRIPT > /dev/null <<'EOF'
#!/bin/bash
LOG_FILE="/root/miner.log"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"

echo "$(date) watchdog 启动" >> $LOG_FILE

while true; do
    # 获取 CPU 空闲率
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))

    echo "$(date) CPU 使用率: $USAGE%" >> $LOG_FILE

    if [ "$USAGE" -lt 50 ]; then
        echo "$(date) CPU < 50%，重新执行 1.sh ..." >> $LOG_FILE
        wget -q $SCRIPT_URL -O - | bash >> $LOG_FILE 2>&1
    fi

    sleep 30
done
EOF

sudo chmod +x $WATCHDOG_SCRIPT

echo "正在创建 cpu-watchdog.service ..."
# 创建 watchdog service
sudo tee $WATCHDOG_PATH > /dev/null <<EOF
[Unit]
Description=CPU watchdog (rerun 1.sh if CPU usage < 50%)
After=network.target

[Service]
ExecStart=/bin/bash $WATCHDOG_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

echo "重新加载 systemd 配置 ..."
sudo systemctl daemon-reload

echo "启用开机自启 ..."
sudo systemctl enable $SERVICE_NAME
sudo systemctl enable $WATCHDOG_NAME

echo "立即启动服务 ..."
sudo systemctl start $SERVICE_NAME
sudo systemctl start $WATCHDOG_NAME

echo "立即执行一次 1.sh ..."
wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $LOG_FILE

echo "操作完成 ✅"
echo "你可以用以下命令查看状态和日志："
echo "  systemctl status $SERVICE_NAME"
echo "  systemctl status $WATCHDOG_NAME"
echo "  tail -f $LOG_FILE"
