#!/bin/bash
set -e

# ---------------- 提权 ----------------
if [ "$EUID" -ne 0 ]; then
    echo "非 root 用户，使用 sudo 提权..."
    exec sudo bash "$0" "$@"
fi

# ---------------- 参数 ----------------
WORKDIR="/root"
VENV_DIR="$WORKDIR/pyenv"

MINER_SERVICE="miner.service"
WATCHDOG_SERVICE="watchdog_updater.service"
AGENT_SERVICE="agent.service"

MINER_LOG="$WORKDIR/miner.log"
WATCHDOG_LOG="$WORKDIR/watchdog_updater.log"
AGENT_LOG="$WORKDIR/agent.log"

SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"

WATCHDOG_SCRIPT="$WORKDIR/watchdog_updater.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

# ---------------- 清理旧环境 ----------------
echo "🔹 清理旧服务和环境..."
systemctl stop $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE 2>/dev/null || true
systemctl disable $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE 2>/dev/null || true
rm -f /etc/systemd/system/$MINER_SERVICE /etc/systemd/system/$WATCHDOG_SERVICE /etc/systemd/system/$AGENT_SERVICE
rm -rf "$VENV_DIR" "$WATCHDOG_SCRIPT" "$AGENT_SCRIPT"
rm -f "$MINER_LOG" "$WATCHDOG_LOG" "$AGENT_LOG"
systemctl daemon-reload || true
systemctl reset-failed || true

# ---------------- 安装依赖 ----------------
echo "🔹 安装依赖..."
if command -v apt >/dev/null 2>&1; then
    apt update -y
    apt install -y wget curl git python3 python3-venv python3-pip gcc make tar
elif command -v yum >/dev/null 2>&1; then
    yum install -y wget curl git python3 python3-virtualenv python3-pip gcc make tar
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y wget curl git python3 python3-virtualenv python3-pip gcc make tar
elif command -v zypper >/dev/null 2>&1; then
    zypper install -y wget curl git python3 python3-venv python3-pip gcc make tar
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm wget curl git python python-virtualenv python-pip base-devel tar
elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache wget curl git python3 py3-virtualenv py3-pip build-base tar
else
    echo "❌ 未找到支持的包管理器，请手动安装依赖"
    exit 1
fi

# ---------------- 找到可用 Python ----------------
PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ 系统未安装 Python"
    exit 1
fi
echo "✅ 使用 Python: $PYTHON_BIN"

# ---------------- 创建虚拟环境 ----------------
echo "🔹 创建虚拟环境..."
$PYTHON_BIN -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "🔹 安装 Python 依赖..."
pip install --upgrade pip
pip install websockets psutil requests

# ---------------- miner.service ----------------
cat > /etc/systemd/system/$MINER_SERVICE <<EOF
[Unit]
Description=Auto start apoolminer script
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash -c 'wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $MINER_LOG'
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

# ---------------- watchdog+updater ----------------
cat > $WATCHDOG_SCRIPT <<'EOF'
#!/bin/bash
set -e
LOG_FILE="/root/watchdog_updater.log"
MINER_SERVICE="miner.service"
BASE_DIR="/root"
VERSION_FILE="$BASE_DIR/apoolminer_linux_qubic_autoupdate/version.txt"
REPO_API="https://api.github.com/repos/apool-io/apoolminer/releases/latest"
THRESHOLD=50
MAX_LOW=3
LOW_COUNT=0
LAST_UPDATE_CHECK=0
UPDATE_INTERVAL=3600

echo "$(date) Watchdog+Updater 启动" | tee -a $LOG_FILE

while true; do
    # CPU监控
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))
    echo "$(date) CPU 使用率: $USAGE%" | tee -a $LOG_FILE
    if [ "$USAGE" -lt "$THRESHOLD" ]; then
        LOW_COUNT=$((LOW_COUNT+1))
        if [ "$LOW_COUNT" -ge "$MAX_LOW" ]; then
            echo "$(date) CPU 连续低于 $THRESHOLD% $MAX_LOW 次，重启 miner.service" | tee -a $LOG_FILE
            systemctl restart $MINER_SERVICE || reboot
            LOW_COUNT=0
        fi
    else
        LOW_COUNT=0
    fi

    # 自动更新
    NOW=$(date +%s)
    if (( NOW - LAST_UPDATE_CHECK >= UPDATE_INTERVAL )); then
        LAST_UPDATE_CHECK=$NOW
        LATEST=$(curl -s $REPO_API | grep '"tag_name":' | head -1 | awk -F'"' '{print $4}')
        LOCAL="none"
        [ -f "$VERSION_FILE" ] && LOCAL=$(cat "$VERSION_FILE")
        if [ "$LATEST" != "$LOCAL" ]; then
            echo "$(date) 检测到新版本 $LATEST，开始更新..." | tee -a $LOG_FILE
            wget -q "https://github.com/apool-io/apoolminer/releases/download/$LATEST/apoolminer_linux_qubic_autoupdate_${LATEST}.tar.gz" -O "$BASE_DIR/miner.tar.gz"
            tar -xzf "$BASE_DIR/miner.tar.gz" -C "$BASE_DIR"
            echo "$LATEST" > "$VERSION_FILE"
            systemctl restart $MINER_SERVICE
            echo "$(date) 更新完成" | tee -a $LOG_FILE
        fi
    fi

    sleep 30
done
EOF
chmod +x $WATCHDOG_SCRIPT

cat > /etc/systemd/system/$WATCHDOG_SERVICE <<EOF
[Unit]
Description=Watchdog + Miner Auto Updater
After=network.target

[Service]
ExecStart=/bin/bash $WATCHDOG_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

# ---------------- agent.service ----------------
wget -q $AGENT_URL -O $AGENT_SCRIPT
chmod +x $AGENT_SCRIPT

cat > /etc/systemd/system/$AGENT_SERVICE <<EOF
[Unit]
Description=Agent Python Script
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $AGENT_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 启动服务 ----------------
echo "🔹 启用并启动服务..."
systemctl daemon-reload
systemctl enable $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE
systemctl start $MINER_SERVICE $WATCHDOG_SERVICE $AGENT_SERVICE

echo "✅ 安装完成！"
echo "日志路径:"
echo "  Miner   -> $MINER_LOG"
echo "  Watchdog-> $WATCHDOG_LOG"
echo "  Agent   -> $AGENT_LOG"
