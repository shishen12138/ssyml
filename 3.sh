#!/bin/bash
set -e

# ---------------- 参数 ----------------
SERVICE_NAME="miner.service"
WATCHDOG_NAME="cpu-watchdog.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
WATCHDOG_PATH="/etc/systemd/system/$WATCHDOG_NAME"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
WORKDIR="/root"
LOG_FILE="$WORKDIR/miner.log"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"

# ---------------- 创建 miner.service ----------------
echo "正在创建 $SERVICE_NAME ..."
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

# ---------------- 创建 CPU Watchdog 脚本 ----------------
echo "正在创建 CPU Watchdog 脚本 ..."
sudo tee $WATCHDOG_SCRIPT > /dev/null <<'EOF'
#!/bin/bash
LOG_FILE="/root/miner.log"
THRESHOLD=50      # CPU 使用率阈值
MAX_LOW=3         # 连续低于阈值次数触发重启
LOW_COUNT=0

echo "$(date) watchdog 启动" >> $LOG_FILE

while true; do
    # 获取 CPU 空闲率
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))

    echo "$(date) CPU 使用率: $USAGE%" >> $LOG_FILE

    if [ "$USAGE" -lt "$THRESHOLD" ]; then
        LOW_COUNT=$((LOW_COUNT+1))
        echo "$(date) CPU < $THRESHOLD%，连续低使用次数: $LOW_COUNT" >> $LOG_FILE

        if [ "$LOW_COUNT" -ge "$MAX_LOW" ]; then
            echo "$(date) CPU 连续低于 $THRESHOLD% $MAX_LOW 次，重启服务器..." >> $LOG_FILE
            sudo reboot
        fi
    else
        LOW_COUNT=0
    fi

    sleep 30
done
EOF

sudo chmod +x $WATCHDOG_SCRIPT

# ---------------- 创建 cpu-watchdog.service ----------------
echo "正在创建 $WATCHDOG_NAME ..."
sudo tee $WATCHDOG_PATH > /dev/null <<EOF
[Unit]
Description=CPU watchdog (reboot if CPU usage < 50% for 3 consecutive checks)
After=network.target

[Service]
ExecStart=/bin/bash $WATCHDOG_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 启用服务 ----------------
echo "重新加载 systemd 配置 ..."
sudo systemctl daemon-reload

echo "启用开机自启 ..."
sudo systemctl enable $SERVICE_NAME
sudo systemctl enable $WATCHDOG_NAME

echo "立即启动服务 ..."
sudo systemctl start $SERVICE_NAME
sudo systemctl start $WATCHDOG_NAME

# ---------------- 立即执行一次 1.sh ----------------
echo "立即执行一次 1.sh ..."
wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $LOG_FILE


fi
