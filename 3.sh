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
LOCK_FILE="$WORKDIR/watchdog.lock"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
MINER_SERVICE="miner.service"
AGENT_SERVICE="agent.service"

# ---------------- 清理旧服务 ----------------
echo "🔹 清理旧服务..."
systemctl stop $MINER_SERVICE $AGENT_SERVICE 2>/dev/null || true
systemctl disable $MINER_SERVICE $AGENT_SERVICE 2>/dev/null || true
rm -f /etc/systemd/system/$MINER_SERVICE /etc/systemd/system/$AGENT_SERVICE
rm -f "$WATCHDOG_SCRIPT" "$LOG_FILE" "$WORKDIR/agent.py" "$LOCK_FILE"

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
if [ ! -f "$WORKDIR/agent.py" ]; then
    wget -q -O "$WORKDIR/agent.py" "$AGENT_URL"
    chmod +x "$WORKDIR/agent.py"
fi

# ---------------- 创建 agent.service ----------------
cat > /etc/systemd/system/$AGENT_SERVICE <<EOF
[Unit]
Description=Python Agent Service
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $WORKDIR/agent.py
Restart=always
RestartSec=10
User=root
WorkingDirectory=$WORKDIR
StandardOutput=journal
StandardError=journal

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
LOCK_FILE="/root/watchdog.lock"
MINER_NAME="apoolminer_linux_qubic_autoupdate"
CHECK_INTERVAL=30
RETRY_THRESHOLD=6
MINER_MISSING_COUNT=0

# 防止多实例运行
exec 200>"$LOCK_FILE"
flock -n 200 || {
    echo "$(date) watchdog 已在运行，退出" | tee -a "$LOG_FILE"
    exit 1
}

run_latest_script() {
    echo "$(date) ⚡ 执行 1.sh" | tee -a "$LOG_FILE"
    wget -q -O "$SCRIPT" "https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
    chmod +x "$SCRIPT"
    /bin/bash "$SCRIPT" 2>&1 | tee -a "$LOG_FILE"
}

# 启动时执行一次
if ! pgrep -f "$MINER_NAME" > /dev/null; then
    run_latest_script
fi

# 守护循环
while true; do
    if ! pgrep -f "$MINER_NAME" > /dev/null; then
        MINER_MISSING_COUNT=$((MINER_MISSING_COUNT+1))
        echo "$(date) 矿工未运行，连续次数: $MINER_MISSING_COUNT" | tee -a "$LOG_FILE"
        if [ "$MINER_MISSING_COUNT" -ge "$RETRY_THRESHOLD" ]; then
            run_latest_script
            MINER_MISSING_COUNT=0
        fi
    else
        MINER_MISSING_COUNT=0
    fi
    sleep $CHECK_INTERVAL
done
EOF

chmod +x "$WATCHDOG_SCRIPT"

# ---------------- 创建 miner.service ----------------
cat > /etc/systemd/system/$MINER_SERVICE <<EOF
[Unit]
Description=Miner Watchdog Service
After=network.target

[Service]
ExecStart=/bin/bash $WATCHDOG_SCRIPT
Restart=always
RestartSec=10
User=root
WorkingDirectory=$WORKDIR
StandardOutput=journal
StandardError=journal

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
