#!/bin/bash
set -e

# ================= 常量 =================
BASE_DIR="/root"
REPO="apool-io/apoolminer"
ACCOUNT="CP_qcy"
LOG_FILE="$BASE_DIR/miner_deploy.log"

# ================= 日志函数 =================
log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "=== 一键部署脚本开始 ==="

# ================= 安装必要工具 =================
log "检查并安装必要工具: jq, wget, tar"
apt-get update
for cmd in jq wget tar; do
    if ! command -v $cmd >/dev/null 2>&1; then
        log "$cmd 未安装，正在安装..."
        apt-get install -y $cmd
        log "$cmd 安装完成 ✅"
    else
        log "$cmd 已安装 ✅"
    fi
done

# ================= 停止已有 systemd 服务 =================
SERVICES=("apoolminer.service" "cpu-watchdog.service" "agent.service" "miner.service")
log "停止已有相关 systemd 服务..."
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        systemctl stop "$svc"
        log "$svc 已停止"
    else
        log "$svc 未运行"
    fi
    if systemctl is-enabled --quiet "$svc"; then
        systemctl disable "$svc"
        log "$svc 已禁用开机自启"
    else
        log "$svc 开机自启未启用"
    fi
done

# ================= 清理 root 目录非必要文件 =================
log "清理 root 目录非必要文件..."
shopt -s extglob
cd "$BASE_DIR"
# 保留系统隐藏文件（如 .bashrc、.profile 等）和目录 /root/.ssh
rm -rf !(".bash*"|".profile"|".ssh"|".cache"|".local")
shopt -u extglob
log "清理完成 ✅"


# ================= 获取最新版本 =================
log "获取最新版本信息..."
LATEST_VERSION=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.tag_name')
if [ "$LATEST_VERSION" == "null" ]; then
    log "无法获取最新版本号，退出脚本。"
    exit 1
fi
log "最新版本：$LATEST_VERSION"
# ================= 保存版本号到文件 =================
VERSION_FILE="$BASE_DIR/apoolminer_version.txt"
echo "$LATEST_VERSION" > "$VERSION_FILE"
log "最新版本号已保存到 $VERSION_FILE ✅"

DOWNLOAD_URL="https://github.com/$REPO/releases/download/$LATEST_VERSION/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"
TAR_FILE="$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"
MINER_DIR="$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}"

# ================= 下载并解压 =================
log "开始下载压缩包：$DOWNLOAD_URL"
RETRY_COUNT=0
MAX_RETRIES=5
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    wget -q --show-progress "$DOWNLOAD_URL" -O "$TAR_FILE"
    if [ $? -eq 0 ] && [ -s "$TAR_FILE" ]; then
        log "压缩包下载完成，正在验证..."
        if tar -tzf "$TAR_FILE" >/dev/null 2>&1; then
            log "压缩包验证通过，开始解压..."
            tar -xzf "$TAR_FILE"
            chmod -R 777 "$MINER_DIR"
            log "目录权限已修改为 777 ✅"
            break
        else
            log "压缩包损坏，重新下载..."
            rm -f "$TAR_FILE"
        fi
    else
        log "下载失败，正在重试...($((RETRY_COUNT+1)))"
        rm -f "$TAR_FILE"
    fi
    RETRY_COUNT=$((RETRY_COUNT+1))
    sleep 5
done
[ $RETRY_COUNT -ge $MAX_RETRIES ] && log "下载失败，达到最大重试次数，退出脚本。" && exit 1

# ================= 配置 miner.conf =================
log "配置 miner.conf"
cd "$MINER_DIR"
cat > miner.conf <<EOF
algo=qubic_xmr
account=$ACCOUNT
pool=qubic.asia.apool.io:4334

cpu-off = false
xmr-cpu-off = false
xmr-1gb-pages = true
no-cpu-affinity = true

gpu-off = true
xmr-gpu-off = true
EOF
log "miner.conf 配置完成 ✅"

# ================= 创建守护脚本 =================
log "创建守护脚本"
WATCHDOG="$BASE_DIR/apoolminer_watchdog.sh"
cat > "$WATCHDOG" <<'EOF'
#!/bin/bash

LOG_FILE="/root/apoolminer_run.log"
MINER_DIR="/root/apoolminer_linux_qubic_autoupdate_v3.3.0"
ACCOUNT="CP_qcy"

log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "=== 守护进程启动 ==="
log "矿工目录: $MINER_DIR"
log "日志文件: $LOG_FILE"

while true; do
    PIDS=($(pgrep -f "apoolminer.*--account $ACCOUNT"))

    if [ ${#PIDS[@]} -eq 0 ]; then
        log "apoolminer 未运行，启动中..."
        cd "$MINER_DIR" || { log "无法进入矿工目录: $MINER_DIR"; sleep 10; continue; }
        chmod +x run.sh apoolminer
        /bin/bash run.sh >> "$LOG_FILE" 2>&1 &
        sleep 5
        PID=$(pgrep -f "apoolminer.*--account $ACCOUNT")
        if [ -n "$PID" ]; then
            log "apoolminer 已启动 ✅ PID=$PID"
        else
            log "apoolminer 启动失败 ❌ 请检查 $LOG_FILE"
        fi
    elif [ ${#PIDS[@]} -gt 1 ]; then
        log "检测到多个 apoolminer 实例，全部杀掉并重启..."
        for pid in "${PIDS[@]}"; do
            kill -9 "$pid"
        done
        sleep 2
        cd "$MINER_DIR" || { log "无法进入矿工目录: $MINER_DIR"; sleep 10; continue; }
        chmod +x run.sh apoolminer
        /bin/bash run.sh >> "$LOG_FILE" 2>&1 &
        sleep 5
        PID=$(pgrep -f "apoolminer.*--account $ACCOUNT")
        if [ -n "$PID" ]; then
            log "apoolminer 重启成功 ✅ PID=$PID"
        else
            log "apoolminer 重启失败 ❌ 请检查 $LOG_FILE"
        fi
    else
        log "apoolminer 已在运行中 ✅ PID=${PIDS[0]}"
    fi

    sleep 10
done

EOF

chmod +x "$WATCHDOG"
log "守护脚本创建完成 ✅"


# ================= 创建 systemd 服务 =================
log "创建 systemd 服务"
SERVICE_FILE="/etc/systemd/system/apoolminer.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Apoolminer Watchdog Service
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash $WATCHDOG
Restart=always
RestartSec=10
WorkingDirectory=$MINER_DIR
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable apoolminer.service
systemctl restart apoolminer.service
log "systemd 服务创建完成并启动 ✅"

# ================= 创建 logrotate 配置 =================
log "创建 logrotate 配置"
LOGROTATE_FILE="/etc/logrotate.d/apoolminer"
cat > "$LOGROTATE_FILE" <<EOF
$BASE_DIR/apoolminer_run.log {
    daily
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
log "logrotate 配置完成 ✅"

log "=== 一键部署完成，矿工守护中 ==="
log "查看日志: tail -f $BASE_DIR/apoolminer_run.log 或 journalctl -u apoolminer.service -f"
