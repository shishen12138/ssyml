#!/bin/bash
set -e
# ---------------- 提权检查 ----------------
if [ "$EUID" -ne 0 ]; then
    echo "非 root 用户，使用 sudo 提权..."
    exec sudo bash "$0" "$@"
fi
# ---------------- 参数 ----------------
WORKDIR="/root"
LOG_FILE="$WORKDIR/miner.log"
VENV_DIR="$WORKDIR/pyenv"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

MINER_SERVICE="miner.service"
WATCHDOG_SERVICE="cpu-watchdog.service"
AGENT_SERVICE="agent.service"

# ---------------- 停止并禁用旧服务 ----------------
echo "停止旧服务..."
systemctl stop $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE 2>/dev/null || true
systemctl disable $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE 2>/dev/null || true

# ---------------- 安装依赖 ----------------
echo "安装依赖..."
if [ -f /etc/debian_version ]; then
    apt update
    apt install -y wget build-essential git python3-venv python3-pip
elif [ -f /etc/redhat-release ]; then
    yum install -y wget gcc gcc-c++ make git python3-venv python3-pip
else
    echo "未知 Linux 发行版"
    exit 1
fi

# ---------------- 创建虚拟环境 ----------------
echo "删除旧虚拟环境（如果存在）..."
rm -rf "$VENV_DIR"
echo "创建虚拟环境 $VENV_DIR"
python3 -m venv "$VENV_DIR"

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# ---------------- 安装 pip 依赖 ----------------
echo "安装 pip 依赖..."
pip install --upgrade pip
pip install websockets psutil requests

# ---------------- 创建 miner.service ----------------
echo "配置 miner.service ..."
tee /etc/systemd/system/$MINER_SERVICE > /dev/null <<EOF
[Unit]
Description=Auto start apoolminer script
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $LOG_FILE'
RemainAfterExit=true
User=root
WorkingDirectory=$WORKDIR
StandardOutput=inherit
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 创建 CPU Watchdog ----------------
echo "配置 cpu-watchdog.service ..."
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

tee /etc/systemd/system/$WATCHDOG_SERVICE > /dev/null <<EOF
[Unit]
Description=CPU watchdog (reboot if CPU usage < 50% for 3 consecutive checks)
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

# ---------------- 下载 agent.py ----------------
echo "下载 agent.py ..."
wget -q $AGENT_URL -O $AGENT_SCRIPT
chmod +x $AGENT_SCRIPT

# ---------------- 创建 agent.service ----------------
echo "配置 agent.service ..."
tee /etc/systemd/system/$AGENT_SERVICE > /dev/null <<EOF
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

# ---------------- 启用并启动服务 ----------------
echo "重新加载 systemd 配置..."
systemctl daemon-reload

echo "启用服务..."
systemctl enable $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE

echo "启动服务..."
systemctl start $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE

echo "安装完成！虚拟环境路径: $VENV_DIR，服务日志: $LOG_FILE"
