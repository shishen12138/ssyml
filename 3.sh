#!/bin/bash
set -e

# ---------------- 提权检查 ----------------
if [ "$EUID" -ne 0 ]; then
    echo "非 root 用户，使用 sudo 提权..."
    exec sudo bash "$0" "$@"
fi

# ---------------- 参数 ----------------
WORKDIR="/root"
VENV_DIR="$WORKDIR/pyenv"
WATCHDOG_SCRIPT="$WORKDIR/miner_watchdog.sh"
LOG_FILE="$WORKDIR/watchdog.log"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
MINER_SERVICE="miner.service"
AGENT_SERVICE="agent.service"

# ---------------- 清理旧服务 ----------------
echo "🔹 清理旧服务..."
systemctl stop $MINER_SERVICE $AGENT_SERVICE 2>/dev/null || true
systemctl disable $MINER_SERVICE $AGENT_SERVICE 2>/dev/null || true
rm -f /etc/systemd/system/$MINER_SERVICE /etc/systemd/system/$AGENT_SERVICE
rm -f "$WATCHDOG_SCRIPT" "$LOG_FILE" "$WORKDIR/agent.py"

# ---------------- 安装系统依赖 ----------------
echo "🔹 安装系统依赖..."
if command -v apt >/dev/null 2>&1; then
    apt update -y
    apt install -y wget curl git python3 python3-venv python3-pip gcc make
elif command -v yum >/dev/null 2>&1; then
    yum install -y wget curl git python3 python3-virtualenv python3-pip gcc make
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y wget curl git python3 python3-virtualenv python3-pip gcc make
elif command -v zypper >/dev/null 2>&1; then
    zypper install -y wget curl git python3 python3-venv python3-pip gcc make
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm wget curl git python python-virtualenv python-pip base-devel
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache wget curl git python3 py3-virtualenv py3-pip build-base
else
    echo "❌ 未找到支持的包管理器，请手动安装依赖"
    exit 1
fi

# ---------------- 创建虚拟环境 ----------------
echo "🔹 创建虚拟环境..."
PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ 系统未安装 Python"
    exit 1
fi
$PYTHON_BIN -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install websockets psutil requests

# ---------------- 下载 agent.py ----------------
echo "🔹 下载 agent.py..."
wget -q -O "$WORKDIR/agent.py" "$AGENT_URL"
chmod +x "$WORKDIR/agent.py"

# ---------------- 创建 agent.service ----------------
cat > /etc/systemd/system/$AGENT_SERVICE <<EOF
[Unit]
Description=Agent Python Script
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $WORKDIR/agent.py
Restart=always
User=root
WorkingDirectory=$WORKDIR
StandardOutput=inherit
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 创建 miner_watchdog.sh ----------------
echo "🔹 创建 miner_watchdog.sh..."
cat > "$WATCHDOG_SCRIPT" <<'EOF'
#!/bin/bash
WORKDIR="/root"
SCRIPT="/root/1.sh"
LOG_FILE="/root/watchdog.log"
CPU_THRESHOLD=50
CPU_MAX_LOW=3
CPU_LOW_COUNT=0

# 下载最新 1.sh
echo "$(date) 下载 1.sh" | tee -a $LOG_FILE
wget -q -O "$SCRIPT" "https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
chmod +x "$SCRIPT"

# 启动 1.sh
echo "$(date) 启动 1.sh" | tee -a $LOG_FILE
/bin/bash "$SCRIPT" 2>&1 | tee -a $LOG_FILE &
# 延时 30 秒检查 apoolminer 是否在运行
sleep 30
while true; do
    # 检查 apoolminer 是否在运行
    if ! pgrep -f "apoolminer" > /dev/null; then
        echo "$(date) apoolminer 未运行，重新执行 1.sh" | tee -a $LOG_FILE
        /bin/bash "$SCRIPT" 2>&1 | tee -a $LOG_FILE &
    fi

    # CPU 使用率监控
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))
    echo "$(date) CPU 使用率: $USAGE%" | tee -a $LOG_FILE

    if [ "$USAGE" -lt "$CPU_THRESHOLD" ]; then
        CPU_LOW_COUNT=$((CPU_LOW_COUNT+1))
        echo "$(date) CPU < $CPU_THRESHOLD%，连续低使用次数: $CPU_LOW_COUNT" | tee -a $LOG_FILE
        if [ "$CPU_LOW_COUNT" -ge "$CPU_MAX_LOW" ]; then
            echo "$(date) CPU 连续低于 $CPU_THRESHOLD% $CPU_MAX_LOW 次，重新执行 1.sh" | tee -a $LOG_FILE
            /bin/bash "$SCRIPT" 2>&1 | tee -a $LOG_FILE &
            CPU_LOW_COUNT=0
        fi
    else
        CPU_LOW_COUNT=0
    fi

    sleep 30
done
EOF

chmod +x "$WATCHDOG_SCRIPT"

# ---------------- 创建 miner.service ----------------
cat > /etc/systemd/system/$MINER_SERVICE <<EOF
[Unit]
Description=Miner Watchdog Service (monitor apoolminer and CPU)
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

# ---------------- 启用并启动服务 ----------------
echo "🔹 启用服务..."
systemctl daemon-reload
systemctl enable $AGENT_SERVICE $MINER_SERVICE
systemctl start $AGENT_SERVICE $MINER_SERVICE

echo "✅ 安装完成！"
echo "日志路径: $LOG_FILE"
