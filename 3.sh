#!/bin/bash
set -e

WORKDIR="/root"
LOG_FILE="$WORKDIR/miner.log"
VENV_DIR="$WORKDIR/pyenv"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

echo "----------------- 安装依赖 -----------------"
if [ -f /etc/debian_version ]; then
    apt update | tee -a $LOG_FILE
    apt install -y wget build-essential git python3-venv python3-pip | tee -a $LOG_FILE
elif [ -f /etc/redhat-release ]; then
    yum install -y wget gcc gcc-c++ make git python3-venv python3-pip | tee -a $LOG_FILE
else
    echo "未知 Linux 发行版" | tee -a $LOG_FILE
    exit 1
fi

echo "----------------- 创建虚拟环境 -----------------"
python3 -m venv "$VENV_DIR" | tee -a $LOG_FILE
source "$VENV_DIR/bin/activate"

echo "----------------- 安装 pip 依赖 -----------------"
pip install --upgrade pip | tee -a $LOG_FILE
pip install websockets psutil requests | tee -a $LOG_FILE

echo "----------------- 下载 agent.py -----------------"
wget $AGENT_URL -O $AGENT_SCRIPT | tee -a $LOG_FILE
chmod +x $AGENT_SCRIPT

echo "----------------- 配置 systemd 服务 -----------------"
# miner.service
tee /etc/systemd/system/miner.service > /dev/null <<EOF
[Unit]
Description=Auto start apoolminer script
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'wget -O - $SCRIPT_URL | bash 2>&1 | tee -a $LOG_FILE'
RemainAfterExit=true
User=root
WorkingDirectory=$WORKDIR
StandardOutput=inherit
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

# cpu-watchdog.service
tee $WATCHDOG_SCRIPT > /dev/null <<'EOF'
#!/bin/bash
LOG_FILE="/root/miner.log"
THRESHOLD=50
MAX_LOW=3
LOW_COUNT=0
echo "$(date) watchdog 启动" | tee -a $LOG_FILE
while true; do
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))
    echo "$(date) CPU 使用率: $USAGE%" | tee -a $LOG_FILE
    if [ "$USAGE" -lt "$THRESHOLD" ]; then
        LOW_COUNT=$((LOW_COUNT+1))
        echo "$(date) CPU < $THRESHOLD%，连续低使用次数: $LOW_COUNT" | tee -a $LOG_FILE
        if [ "$LOW_COUNT" -ge "$MAX_LOW" ]; then
            echo "$(date) CPU 连续低于 $THRESHOLD% $MAX_LOW 次，重启服务器..." | tee -a $LOG_FILE
            reboot
        fi
    else
        LOW_COUNT=0
    fi
    sleep 30
done
EOF
chmod +x $WATCHDOG_SCRIPT

tee /etc/systemd/system/cpu-watchdog.service > /dev/null <<EOF
[Unit]
Description=CPU watchdog
After=network.target

[Service]
ExecStart=/bin/bash $WATCHDOG_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR
StandardOutput=inherit
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

# agent.service
tee /etc/systemd/system/agent.service > /dev/null <<EOF
[Unit]
Description=Agent Python Script
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $AGENT_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR
StandardOutput=inherit
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

echo "----------------- 启动服务 -----------------"
systemctl daemon-reload
systemctl enable miner.service cpu-watchdog.service agent.service | tee -a $LOG_FILE
systemctl start miner.service cpu-watchdog.service agent.service | tee -a $LOG_FILE

echo "安装完成！虚拟环境路径: $VENV_DIR，服务日志: $LOG_FILE"
echo "可以用 'journalctl -f -u agent.service' 查看 agent 运行日志"
