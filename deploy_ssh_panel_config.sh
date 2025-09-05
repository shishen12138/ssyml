#!/bin/bash

# ---------- 默认配置（无需交互） ----------
PANEL_DIR="/root/ssh_panel"
PANEL_PORT=12138
LOG_FILE="$PANEL_DIR/ssh_web_panel.log"

SERVICE_FILE="/etc/systemd/system/ssh_web_panel.service"

echo "配置如下:"
echo "面板目录: $PANEL_DIR"
echo "面板端口: $PANEL_PORT"
echo "日志文件: $LOG_FILE"

# ---------- 检测系统 ----------
if [ -f /etc/debian_version ]; then
    OS="debian"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
else
    echo "不支持的系统"
    exit 1
fi
echo "系统类型：$OS"

# ---------- 安装系统依赖 ----------
install_system_packages() {
    echo "检查并安装系统依赖..."
    packages=("ifstat" "net-tools" "awk" "procps" "curl" "wget" "python3-pip")

    for pkg in "${packages[@]}"; do
        case $pkg in
            net-tools)
                check_cmd="ifconfig"
                ;;
            procps)
                check_cmd="ps"
                ;;
            python3-pip)
                check_cmd="pip3"
                ;;
            *)
                check_cmd=$pkg
                ;;
        esac

        if ! command -v $check_cmd >/dev/null 2>&1; then
            echo "$pkg 未安装，正在安装..."
            if [ "$OS" == "debian" ]; then
                sudo apt update -y && sudo apt install -y $pkg
            else
                sudo yum install -y $pkg
            fi
        else
            echo "$pkg 已安装"
        fi
    done
}

# ---------- 安装 Python3 ----------
install_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "未检测到 Python3，正在安装..."
        if [ "$OS" == "debian" ]; then
            sudo apt update -y && sudo apt install -y python3 python3-venv python3-pip
        else
            sudo yum install -y python3 python3-pip
        fi
    else
        echo "Python3 已安装"
    fi

    # 修复 pip3 路径问题
    if ! command -v pip3 >/dev/null 2>&1; then
        if [ -x "/usr/bin/pip3" ]; then
            sudo ln -sf /usr/bin/pip3 /usr/local/bin/pip3
        elif [ -x "/usr/bin/pip" ]; then
            sudo ln -sf /usr/bin/pip /usr/local/bin/pip3
        fi
    fi
    if command -v pip3 >/dev/null 2>&1; then
        echo "pip3 已安装: $(pip3 --version)"
    else
        echo "pip3 仍未找到，请手动检查 python3-pip 安装"
    fi
}

# ---------- 安装 Python 库 ----------
install_python_packages() {
    echo "安装 Python 库..."
    pip3 install --upgrade pip --break-system-packages
    pip3 install flask paramiko boto3 requests --break-system-packages
}

# ---------- 创建日志文件 ----------
prepare_log() {
    sudo mkdir -p $(dirname "$LOG_FILE")
    sudo touch "$LOG_FILE"
    sudo chmod 666 "$LOG_FILE"
}

# ---------- 创建 systemd 服务 ----------
create_systemd_service() {
    echo "创建 systemd 服务..."
    sudo mkdir -p "$PANEL_DIR"
    sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=SSH Web 面板
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PANEL_DIR
Environment=PANEL_PORT=$PANEL_PORT
Environment=LOG_FILE=$LOG_FILE
ExecStart=/usr/bin/python3 $PANEL_DIR/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOL

    sudo systemctl daemon-reload
    sudo systemctl enable ssh_web_panel
    sudo systemctl restart ssh_web_panel
    echo "systemd 服务已启动，开机自启，日志文件：$LOG_FILE"
}

# ---------- 执行 ----------
install_python
install_system_packages
install_python_packages
prepare_log
create_systemd_service

echo "======================================"
echo "部署完成！面板访问：http://服务器IP:$PANEL_PORT"
echo "日志文件：$LOG_FILE"
echo "使用 systemctl 管理服务：start/stop/restart/status"
echo "======================================"
