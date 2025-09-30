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

# ---------------- 修复系统 Python ----------------
echo "修复系统 Python..."
if [ -f /etc/debian_version ]; then
    apt update
    apt install -y --reinstall python3 python3-minimal python3-apt python3-setuptools python3-wheel python3-pip python3-distutils
    apt install -y python3-venv python3-lib2to3 || true
elif [ -f /etc/redhat-release ]; then
    yum install -y python3 python3-venv python3-pip python3-setuptools || true
else
    echo "未知 Linux 发行版"
    exit 1
fi

# 修复未完成的 dpkg 配置
dpkg --configure -a || true
apt install -f -y || true

# 检查 python3 和 pip 是否可用
if ! command -v python3 &>/dev/null; then
    echo "python3 修复失败，请手动处理"
    exit 1
fi
if ! command -v pip3 &>/dev/null; then
    echo "pip3 修复失败，请手动处理"
    exit 1
fi

# ---------------- 停止并清理旧服务 ----------------
echo "停止旧服务并清理旧环境..."
systemctl stop miner.service cpu-watchdog.service agent.service || true
systemctl disable miner.service cpu-watchdog.service agent.service || true
rm -rf "$VENV_DIR"
rm -f "$AGENT_SCRIPT"
rm -f /etc/systemd/system/miner.service /etc/systemd/system/cpu-watchdog.service /etc/systemd/system/agent.service
rm -f "$WORKDIR/cpu_watchdog.sh"

# ---------------- 创建虚拟环境 ----------------
echo "创建虚拟环境 $VENV_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# ---------------- 安装 pip 依赖 ----------------
echo "安装 pip 依赖..."
pip install --upgrade pip
pip install websockets psutil requests

# ---------------- 创建 miner.service ----------------
tee /etc/systemd/system/miner.service > /dev/null <<EOF
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
tee "$WATCHDOG_SCRIPT" > /dev/null <<'EOF'
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
chmod +x "$WATCHDOG_SCRIPT"

tee /etc/systemd/system/cpu-watchdog.service > /dev/null <<EOF
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
wget -q "$AGENT_URL" -O "$AGENT_SCRIPT"
chmod +x "$AGENT_SCRIPT"

# ---------------- 创建 agent.service ----------------
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

# ---------------- 启用并启动服务 ----------------
systemctl daemon-reload
systemctl enable miner.service cpu-watchdog.service agent.service
systemctl restart miner.service cpu-watchdog.service agent.service

echo "安装完成！虚拟环境路径: $VENV_DIR，服务日志: $LOG_FILE"
