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

# ---------------- 日志函数 ----------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# ---------------- 安装依赖 ----------------
log "---------------- 安装依赖 ----------------"
if [ -f /etc/debian_version ]; then
    log "更新 apt 源并安装依赖"
    apt update | tee -a $LOG_FILE
    apt install -y wget build-essential git python3-venv python3-pip | tee -a $LOG_FILE
elif [ -f /etc/redhat-release ]; then
    log "安装 yum 依赖"
    yum install -y wget gcc gcc-c++ make git python3-venv python3-pip | tee -a $LOG_FILE
else
    log "未知 Linux 发行版"
    exit 1
fi

# ---------------- 创建虚拟环境 ----------------
log "---------------- 创建虚拟环境 ----------------"
python3 -m venv "$VENV_DIR" --prompt pyenv | tee -a $LOG_FILE
source "$VENV_DIR/bin/activate"
log "虚拟环境创建完成: $VENV_DIR"

# ---------------- 安装 pip 依赖 ----------------
log "---------------- 安装 pip 依赖 ----------------"
pip install --upgrade pip | tee -a $LOG_FILE
pip install websockets psutil requests | tee -a $LOG_FILE
log "pip 依赖安装完成"

# ---------------- 下载 agent.py ----------------
log "---------------- 下载 agent.py ----------------"
wget -q $AGENT_URL -O $AGENT_SCRIPT
chmod +x $AGENT_SCRIPT
log "agent.py 下载完成: $AGENT_SCRIPT"

# ---------------- 创建 CPU Watchdog ----------------
log "---------------- 创建 CPU Watchdog ----------------"
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
log "CPU Watchdog 脚本创建完成: $WATCHDOG_SCRIPT"

# ---------------- 创建 systemd 服务 ----------------
log "---------------- 创建 systemd 服务 ----------------"

log "创建 miner.service..."
tee /etc/systemd/system/miner.service <<EOF | tee -a $LOG_FILE
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
log "miner.service 创建完成"

log "创建 cpu-watchdog.service..."
tee /etc/systemd/system/cpu-watchdog.service <<EOF | tee -a $LOG_FILE
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
log "cpu-watchdog.service 创建完成"

log "创建 agent.service..."
tee /etc/systemd/system/agent.service <<EOF | tee -a $LOG_FILE
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
log "agent.service 创建完成"

# ---------------- 启用并启动服务 ----------------
log "---------------- 启用并启动服务 ----------------"
systemctl daemon-reload | tee -a $LOG_FILE
systemctl enable miner.service cpu-watchdog.service agent.service | tee -a $LOG_FILE
systemctl start miner.service cpu-watchdog.service agent.service | tee -a $LOG_FILE
log "所有服务启动完成"

log "安装完成！虚拟环境路径: $VENV_DIR，服务日志: $LOG_FILE"
