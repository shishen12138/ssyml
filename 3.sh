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
PYTHON_BUILD_LOG="$WORKDIR/python_build.log"
SCRIPT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh"
AGENT_URL="https://raw.githubusercontent.com/shishen12138/ssyml/main/agent.py"
WATCHDOG_SCRIPT="$WORKDIR/cpu_watchdog.sh"
AGENT_SCRIPT="$WORKDIR/agent.py"

# ---------------- 安装依赖 ----------------
echo "安装依赖..."
if [ -f /etc/debian_version ]; then
    apt update
    apt install -y wget build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev curl llvm \
        libncurses-dev xz-utils tk-dev libffi-dev liblzma-dev python3-openssl git
elif [ -f /etc/redhat-release ]; then
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

# ---------------- 下载并编译安装 Python ----------------
cd /usr/src
wget -c https://www.python.org/ftp/python/$PYTHON_LATEST/Python-$PYTHON_LATEST.tgz
tar xzf Python-$PYTHON_LATEST.tgz
cd Python-$PYTHON_LATEST

echo "开始编译 Python $PYTHON_LATEST ..."
./configure --enable-optimizations >> $PYTHON_BUILD_LOG 2>&1
make -j$(nproc) >> $PYTHON_BUILD_LOG 2>&1
make altinstall >> $PYTHON_BUILD_LOG 2>&1

# ---------------- 覆盖系统 python3 ----------------
ln -sf /usr/local/bin/python3.${PYTHON_LATEST%%.*} /usr/bin/python3
ln -sf /usr/local/bin/pip3.${PYTHON_LATEST%%.*} /usr/bin/pip3

echo "Python $PYTHON_LATEST 编译安装完成！"
python3 --version
pip3 --version

# ---------------- 安装 pip & 依赖 ----------------
echo "安装 pip 依赖..." | tee -a $LOG_FILE
python3 -m ensurepip --upgrade >> $LOG_FILE 2>&1
python3 -m pip install --upgrade pip >> $LOG_FILE 2>&1
python3 -m pip install --force-reinstall websockets psutil requests >> $LOG_FILE 2>&1

# ---------------- 创建 miner.service ----------------
SERVICE_NAME="miner.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
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
wget -q $AGENT_URL -O $AGENT_SCRIPT
chmod +x $AGENT_SCRIPT

# ---------------- 创建 agent.service ----------------
AGENT_SERVICE_NAME="agent.service"
AGENT_PATH="/etc/systemd/system/$AGENT_SERVICE_NAME"
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
systemctl daemon-reload
systemctl enable miner.service cpu-watchdog.service agent.service
systemctl start miner.service cpu-watchdog.service agent.service

# ---------------- 立即执行一次 1.sh & agent.py ----------------
wget -q $SCRIPT_URL -O - | bash 2>&1 | tee -a $LOG_FILE
nohup python3 $AGENT_SCRIPT >> $LOG_FILE 2>&1 &

echo "安装完成！Python 编译日志: $PYTHON_BUILD_LOG，服务日志: $LOG_FILE"
