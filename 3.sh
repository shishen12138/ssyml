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

MINER_SERVICE="miner.service"
WATCHDOG_SERVICE="cpu-watchdog.service"
AGENT_SERVICE="agent.service"

MINER_LOG="$WORKDIR/miner.log"
WATCHDOG_LOG="$WORKDIR/watchdog.log"
AGENT_LOG="$WORKDIR/agent.log"

WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"

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

# ---------------- watchdog 脚本 ----------------
cat > $WATCHDOG_SCRIPT <<'EOF'
#!/bin/bash
LOG_FILE="/root/watchdog.log"
MINER_SERVICE="miner.service"
CHECK_INTERVAL=300  # 每 5 分钟检测一次
LOW_COUNT=0
THRESHOLD=50
MAX_LOW=3
MINER_BASE="/root"
MINER_DIR="$MINER_BASE/apoolminer_linux_qubic_autoupdate"
UPDATE_URL="https://github.com/apool-io/apoolminer/releases/latest"

echo "$(date) Watchdog 启动" | tee -a $LOG_FILE

get_latest_version() {
    curl -sL -o /dev/null -w "%{url_effective}" $UPDATE_URL | awk -F '/' '{print $NF}'
}

get_current_version() {
    [ -f "$MINER_DIR/version.txt" ] && cat "$MINER_DIR/version.txt" || echo "none"
}

update_miner() {
    local latest=$1
    echo "$(date) 检测到新版本 $latest，正在更新..." | tee -a $LOG_FILE

    cd "$MINER_BASE"
    wget -q "https://github.com/apool-io/apoolminer/releases/download/$latest/apoolminer_linux_qubic_autoupdate_${latest}.tar.gz" -O miner_update.tar.gz
    tar -xzf miner_update.tar.gz
    rm -f miner_update.tar.gz

    # 保留旧配置
    if [ -f "$MINER_DIR/miner.conf" ]; then
        cp "$MINER_DIR/miner.conf" "$MINER_DIR/miner.conf.bak"
    fi

    # 如果新版本没有配置，则恢复旧配置
    if [ ! -f "$MINER_DIR/miner.conf" ] && [ -f "$MINER_DIR/miner.conf.bak" ]; then
        cp "$MINER_DIR/miner.conf.bak" "$MINER_DIR/miner.conf"
    fi

    echo "$latest" > "$MINER_DIR/version.txt"
    echo "$(date) 更新完成，重启 Miner 服务..." | tee -a $LOG_FILE
    systemctl restart $MINER_SERVICE
}

while true; do
    # CPU 使用率检测
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))
    echo "$(date) CPU 使用率: $USAGE%" | tee -a $LOG_FILE

    if [ "$USAGE" -lt "$THRESHOLD" ]; then
        LOW_COUNT=$((LOW_COUNT+1))
        if [ "$LOW_COUNT" -ge "$MAX_LOW" ]; then
            echo "$(date) CPU 连续低负载，重启 Miner 服务..." | tee -a $LOG_FILE
            systemctl restart $MINER_SERVICE || true
            LOW_COUNT=0
        fi
    else
        LOW_COUNT=0
    fi

    # 自动更新检测
    LATEST_VER=$(get_latest_version)
    CURRENT_VER=$(get_current_version)
    if [ "$LATEST_VER" != "$CURRENT_VER" ]; then
        update_miner "$LATEST_VER"
    fi

    sleep $CHECK_INTERVAL
done
EOF
chmod +x $WATCHDOG_SCRIPT

cat > /etc/systemd/system/$WATCHDOG_SERVICE <<EOF
[Unit]
Description=CPU Watchdog & Auto-update Miner
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
