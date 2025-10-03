#!/bin/bash
set -e

# ================= 常量 =================
BASE_DIR="/root"
REPO="apool-io/apoolminer"
ACCOUNT="CP_qcy"
VERSION_FILE="$BASE_DIR/apoolminer_version.txt"
RUN_LOG="$BASE_DIR/apoolminer_run.log"
UPDATE_LOG="$BASE_DIR/apoolminer_update.log"

# ================= 日志函数 =================
log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$BASE_DIR/miner_deploy.log"
}

log "=== 一键部署脚本开始 ==="

# ================= 安装必要工具 =================
for cmd in jq wget tar; do
    if ! command -v $cmd >/dev/null 2>&1; then
        log "$cmd 未安装，正在安装..."
        apt-get update && apt-get install -y $cmd
        log "$cmd 安装完成 ✅"
    else
        log "$cmd 已安装 ✅"
    fi
done

# ================= 获取最新版本 =================
log "获取最新版本信息..."

# 方式1：GitHub API
LATEST_VERSION=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.tag_name')

# 如果 API 获取失败，用备用方式（网页抓取）
if [ "$LATEST_VERSION" == "null" ] || [ -z "$LATEST_VERSION" ]; then
    log "GitHub API 获取失败，尝试备用方式..."
    LATEST_VERSION=$(curl -s "https://github.com/$REPO/releases" | grep -oP '/'$REPO'/releases/tag/\K[^\"]+' | head -n 1)
fi

if [ -z "$LATEST_VERSION" ]; then
    log "无法获取最新版本号，退出脚本。"
    exit 1
fi

echo "$LATEST_VERSION" > "$VERSION_FILE"
MINER_DIR="$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}"
TAR_FILE="$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/$REPO/releases/download/$LATEST_VERSION/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"

log "最新版本: $LATEST_VERSION"
log "下载地址: $DOWNLOAD_URL"

# ================= 下载并解压（带重试） =================
MAX_RETRY=3
for i in $(seq 1 $MAX_RETRY); do
    log "下载最新版本: $DOWNLOAD_URL (第 $i 次尝试)"
    wget -q --show-progress "$DOWNLOAD_URL" -O "$TAR_FILE"
    if [ $? -eq 0 ] && [ -s "$TAR_FILE" ]; then
        log "下载成功 ✅"
        break
    else
        log "下载失败 ❌"
        [ $i -lt $MAX_RETRY ] && log "等待 5 秒后重试..." && sleep 5
    fi
done

# 下载多次失败仍然为空文件，则退出
if [ ! -s "$TAR_FILE" ]; then
    log "下载失败超过 $MAX_RETRY 次，退出脚本 ❌"
    exit 1
fi

# 解压
tar -xzf "$TAR_FILE" -C "$BASE_DIR"

# 设置权限为 777
chmod -R 777 "$MINER_DIR"
log "解压完成并设置权限 ✅"


# ================= 配置 miner.conf =================
log "配置 miner.conf"
cat > "$MINER_DIR/miner.conf" <<EOF
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

# ================= 创建矿工守护脚本 =================
WATCHDOG="$BASE_DIR/apoolminer_watchdog.sh"
log "创建矿工守护脚本 $WATCHDOG"
cat > "$WATCHDOG" <<'EOF'
#!/bin/bash
LOG_FILE="/root/apoolminer_run.log"
VERSION_FILE="/root/apoolminer_version.txt"
ACCOUNT="CP_qcy"
LAST_DATE=""
log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

log "=== 守护进程启动 ==="

while true; do

    # --- 每天清空日志 ---
    TODAY=$(date +%Y-%m-%d)
    if [ "$TODAY" != "$LAST_DATE" ]; then
        > "$LOG_FILE"
        LAST_DATE="$TODAY"
        log "日志已清空 ✅"
    fi
    # --- 新增锁文件检测，避免和更新冲突 ---
    LOCK_FILE="/tmp/apoolminer_updating.lock"
    if [ -f "$LOCK_FILE" ]; then
        log "检测到更新中，暂不启动矿工"
        sleep 10
        continue
    fi

    [ -f "$VERSION_FILE" ] || { sleep 10; continue; }
    VERSION=$(cat "$VERSION_FILE")
    MINER_DIR="/root/apoolminer_linux_qubic_autoupdate_${VERSION}"

    PIDS=($(pgrep -f "apoolminer.*--account $ACCOUNT"))

    if [ ${#PIDS[@]} -eq 0 ]; then
        log "apoolminer 未运行，启动中..."
        cd "$MINER_DIR" || { log "无法进入矿工目录"; sleep 10; continue; }
        chmod +x run.sh apoolminer
        /bin/bash run.sh >> "$LOG_FILE" 2>&1 &
        sleep 5
        PID=$(pgrep -f "apoolminer.*--account $ACCOUNT")
        [ -n "$PID" ] && log "apoolminer 已启动 ✅ PID=$PID" || log "启动失败 ❌"
    elif [ ${#PIDS[@]} -gt 1 ]; then
        log "检测到多个实例，全部杀掉并重启..."
        for pid in "${PIDS[@]}"; do kill -9 "$pid"; done
        sleep 2
        cd "$MINER_DIR" || { sleep 10; continue; }
        chmod +x run.sh apoolminer
        /bin/bash run.sh >> "$LOG_FILE" 2>&1 &
        sleep 5
        PID=$(pgrep -f "apoolminer.*--account $ACCOUNT")
        [ -n "$PID" ] && log "apoolminer 重启成功 ✅ PID=$PID" || log "重启失败 ❌"
    else
        log "apoolminer 已在运行中 ✅ PID=${PIDS[0]}"
    fi

    sleep 10
done
EOF
chmod +x "$WATCHDOG"

# ================= 创建自动更新脚本 =================
UPDATE_CHECKER="$BASE_DIR/apoolminer_update_checker.sh"
log "创建自动更新检查脚本 $UPDATE_CHECKER"
cat > "$UPDATE_CHECKER" <<'EOF'
#!/bin/bash
set -e

# ================= 常量 =================
BASE_DIR="/root"
ACCOUNT="CP_qcy"
REPO="apool-io/apoolminer"
VERSION_FILE="$BASE_DIR/apoolminer_version.txt"
RUN_LOG="$BASE_DIR/apoolminer_run.log"
UPDATE_LOG="$BASE_DIR/apoolminer_update.log"
LOCK_FILE="/tmp/apoolminer_updating.lock"
LAST_DATE=""

# ================= 日志函数 =================
log_update() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$UPDATE_LOG"
}

# ================= 主循环 =================
while true; do
    # --- 每天清空更新日志 ---
    TODAY=$(date +%Y-%m-%d)
    if [ "$TODAY" != "$LAST_DATE" ]; then
        > "$UPDATE_LOG"
        LAST_DATE="$TODAY"
        log_update "更新日志已清空 ✅"
    fi

    # --- 获取最新版本 ---
    LATEST_VERSION=$(curl -s "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.tag_name')
    if [ "$LATEST_VERSION" == "null" ] || [ -z "$LATEST_VERSION" ]; then
        log_update "GitHub API 获取版本失败，尝试备用方式..."
        LATEST_VERSION=$(curl -s "https://github.com/$REPO/releases" \
            | grep -oP '/'$REPO'/releases/tag/\K[^\"]+' | head -n 1)
    fi

    if [ -z "$LATEST_VERSION" ]; then
        log_update "获取版本失败 ❌，跳过本轮更新"
        continue
    fi
    log_update "最新版本: $LATEST_VERSION"

    # --- 检查当前版本 ---
    [ -f "$VERSION_FILE" ] || echo "" > "$VERSION_FILE"
    CURRENT_VERSION=$(cat "$VERSION_FILE")
    if [ "$LATEST_VERSION" == "$CURRENT_VERSION" ]; then
        log_update "已是最新版本: $CURRENT_VERSION"
        continue
    fi

    log_update "检测到新版本 $LATEST_VERSION (当前 $CURRENT_VERSION)"

    # --- 创建锁文件，通知守护脚本暂停操作 ---
    touch "$LOCK_FILE"

    TAR_FILE="$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"
    DOWNLOAD_URL="https://github.com/$REPO/releases/download/$LATEST_VERSION/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}.tar.gz"

    # --- 下载最新版本，重试机制 ---
    MAX_RETRY=3
    for i in $(seq 1 $MAX_RETRY); do
        log_update "下载最新版本: $DOWNLOAD_URL (第 $i 次尝试)"
        wget -q --show-progress "$DOWNLOAD_URL" -O "$TAR_FILE"
        if [ $? -eq 0 ] && [ -s "$TAR_FILE" ]; then
            log_update "下载成功 ✅"
            break
        else
            log_update "下载失败 ❌"
            [ $i -lt $MAX_RETRY ] && log_update "等待 5 秒后重试..." && sleep 5
        fi
    done

    # --- 下载失败，直接跳过 ---
    if [ ! -s "$TAR_FILE" ]; then
        log_update "下载失败超过 $MAX_RETRY 次 ❌，跳过本轮更新"
        rm -f "$LOCK_FILE"
        continue
    fi

    # --- 解压并设置权限 ---
    tar -xzf "$TAR_FILE" -C "$BASE_DIR"
    chmod -R 777 "$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}"

    # --- 配置 miner.conf ---
    cat > "$BASE_DIR/apoolminer_linux_qubic_autoupdate_${LATEST_VERSION}/miner.conf" <<MINER_EOF
algo=qubic_xmr
account=$ACCOUNT
pool=qubic.asia.apool.io:4334

cpu-off = false
xmr-cpu-off = false
xmr-1gb-pages = true
no-cpu-affinity = true

gpu-off = true
xmr-gpu-off = true
MINER_EOF

    # --- 更新版本文件 ---
    echo "$LATEST_VERSION" > "$VERSION_FILE"
    log_update "版本更新完成 ✅"

    # --- 杀掉旧版本矿工 ---
    OLD_PIDS=($(pgrep -f "apoolminer.*--account $ACCOUNT"))
    if [ ${#OLD_PIDS[@]} -gt 0 ]; then
        log_update "杀掉旧版本矿工: ${OLD_PIDS[*]}"
        for pid in "${OLD_PIDS[@]}"; do kill -9 "$pid"; done
    fi

    # --- 删除锁文件 ---
    rm -f "$LOCK_FILE"

    # 等待下一轮
    sleep 3600
done


EOF
chmod +x "$UPDATE_CHECKER"

# ================= 创建 systemd 服务 =================
log "创建 systemd 服务"

# 守护服务
WATCHDOG_SERVICE="/etc/systemd/system/apoolminer.service"
cat > "$WATCHDOG_SERVICE" <<EOF
[Unit]
Description=Apoolminer Watchdog Service
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash $WATCHDOG
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 自动更新服务
UPDATE_SERVICE="/etc/systemd/system/apoolminer_update.service"
cat > "$UPDATE_SERVICE" <<EOF
[Unit]
Description=Apoolminer Auto Update Service
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash $UPDATE_CHECKER
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable apoolminer.service
systemctl enable apoolminer_update.service
systemctl restart apoolminer.service
systemctl restart apoolminer_update.service

log "=== 部署完成 ✅ 矿工守护与自动更新已启动 ==="
log "查看矿工日志: tail -f $RUN_LOG"
log "查看更新日志: tail -f $UPDATE_LOG"
