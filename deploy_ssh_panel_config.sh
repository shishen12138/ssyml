#!/bin/bash

# ---------- 配置 ----------
PANEL_DIR="/root/ssh_panel"
PANEL_PORT=12138
LOG_FILE="$PANEL_DIR/ssh_web_panel.log"
SERVICE_FILE="/etc/systemd/system/ssh_web_panel.service"
APP_FILE="$PANEL_DIR/app.py"

echo "面板目录: $PANEL_DIR"
echo "面板端口: $PANEL_PORT"
echo "日志文件: $LOG_FILE"

# ---------- 检测系统 ----------
if [ -f /etc/debian_version ]; then OS="debian"
elif [ -f /etc/redhat-release ]; then OS="redhat"
else echo "不支持的系统"; exit 1; fi
echo "系统类型：$OS"

# ---------- 安装系统依赖 ----------
install_system_packages(){
    echo "安装系统依赖..."
    packages=("ifstat" "net-tools" "awk" "procps" "curl" "wget" "python3-venv" "python3-pip" "git")
    for pkg in "${packages[@]}"; do
        command -v $pkg >/dev/null 2>&1 || {
            echo "$pkg 未安装，正在安装..."
            if [ "$OS" == "debian" ]; then sudo apt update -y && sudo apt install -y $pkg
            else sudo yum install -y $pkg; fi
        }
    done
}

# ---------- 安装 Python3 ----------
install_python(){
    if ! command -v python3 >/dev/null 2>&1; then
        echo "安装 Python3..."
        if [ "$OS" == "debian" ]; then sudo apt update -y && sudo apt install -y python3 python3-venv python3-pip
        else sudo yum install -y python3 python3-pip; fi
    else echo "Python3 已安装"; fi

    # 修复 pip3 路径
    if ! command -v pip3 >/dev/null 2>&1; then
        [ -x "/usr/bin/pip3" ] && sudo ln -sf /usr/bin/pip3 /usr/local/bin/pip3
        [ -x "/usr/bin/pip" ] && sudo ln -sf /usr/bin/pip /usr/local/bin/pip3
    fi
}

# ---------- 安装 Python 库 ----------
install_python_packages(){
    echo "安装 Python 库..."
    PIP_PACKAGES=("flask" "flask-socketio" "asyncssh" "paramiko" "boto3" "requests" "psutil" "eventlet")
    pip3 install --upgrade pip --break-system-packages
    pip3 install "${PIP_PACKAGES[@]}" --break-system-packages
}

# ---------- 创建日志 ----------
prepare_log(){
    sudo mkdir -p "$(dirname "$LOG_FILE")"
    sudo touch "$LOG_FILE"
    sudo chmod 644 "$LOG_FILE"
}

# ---------- 下载或检查 app.py ----------
prepare_app(){
    sudo mkdir -p "$PANEL_DIR"
    if [ ! -f "$APP_FILE" ]; then
        echo "app.py 不存在，正在下载示例版本..."
        sudo wget -O "$APP_FILE" "https://raw.githubusercontent.com/shishen12138/ssyml/main/app.py" || {
            echo "下载失败，请手动上传 app.py"; exit 1; }
    fi
}

# ---------- 创建 systemd 服务 ----------
create_systemd_service(){
    echo "创建 systemd 服务..."
    sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=SSH WebSocket 面板
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PANEL_DIR
Environment=PANEL_PORT=$PANEL_PORT
Environment=LOG_FILE=$LOG_FILE
ExecStart=/usr/bin/python3 $APP_FILE
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

    sudo systemctl daemon-reload
    sudo systemctl enable ssh_web_panel
    sudo systemctl restart ssh_web_panel
    echo "systemd 服务已启动并开机自启"
}

# ---------- 执行 ----------
install_system_packages
install_python
install_python_packages
prepare_log
prepare_app
create_systemd_service

echo "======================================"
echo "部署完成！"
echo "面板访问：http://服务器IP:$PANEL_PORT"
echo "日志文件：$LOG_FILE"
echo "服务管理：systemctl start/stop/restart/status ssh_web_panel"
echo "======================================"
