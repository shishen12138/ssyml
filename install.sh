#!/bin/bash

# ==========================================
# Apoolminer 一键安装 + 自动更新脚本
# ==========================================

# ---------------- 配置 ----------------
BASE_DIR="/root"
MINER_DIR="$BASE_DIR/apoolminer"
ACCOUNT="CP_qcy"
UPDATE_SCRIPT="$BASE_DIR/apoolminer-update.sh"
INSTALL_LOG="$BASE_DIR/apoolminer-install.log"
UPDATE_LOG="$BASE_DIR/apoolminer-update.log"
GITHUB_API="https://api.github.com/repos/apool-io/apoolminer/releases/latest"

# 输出安装日志
exec > >(tee -a "$INSTALL_LOG") 2>&1

echo "=========================================="
echo "🚀 开始安装 Apoolminer 环境..."
echo "账户: $ACCOUNT"
echo "安装目录: $MINER_DIR"
echo "安装日志: $INSTALL_LOG"
echo "更新日志: $UPDATE_LOG"
echo "=========================================="

# ---------------- 写自动更新脚本 ----------------
cat > "$UPDATE_SCRIPT" <<'EOF'
#!/bin/bash

BASE_DIR="/root"
MINER_DIR="$BASE_DIR/apoolminer"
ACCOUNT="CP_qcy"
UPDATE_LOG="$BASE_DIR/apoolminer-update.log"

# 输出日志
exec > >(tee -a "$UPDATE_LOG") 2>&1
echo "------------------------------------------"
echo "⏰ $(date '+%F %T') - 开始自动更新"

cleanup_old() {
    echo "🧹 停止旧守护与清理进程"

    # 停掉所有可能的 miner 服务
    systemctl list-unit-files 2>/dev/null | grep -i 'miner' | awk '{print $1}' | while read svc; do
        echo "⚠️ 停止检测到的服务: $svc"
        systemctl stop "$svc" >/dev/null 2>&1 || true
        systemctl disable "$svc" >/dev/null 2>&1 || true
    done

    # 杀掉相关进程
    pkill -9 -f apoolminer >/dev/null 2>&1 || true
    pkill -9 -f run.sh >/dev/null 2>&1 || true

    # 清理目录和压缩包
    rm -rf "$MINER_DIR" >/dev/null 2>&1 || true
    rm -f "$BASE_DIR"/apoolminer_*.tar.gz >/dev/null 2>&1 || true

    echo "✅ 旧文件与进程清理完成"
}

download_and_extract() {
    local latest="$1"
    TAR_FILE="$BASE_DIR/apoolminer_${latest}.tar.gz"
    URL="https://github.com/apool-io/apoolminer/releases/download/v${latest}/apoolminer_linux_qubic_autoupdate_v${latest}.tar.gz"
    echo "⬇️ 下载 $URL"
    wget -q "$URL" -O "$TAR_FILE"

    mkdir -p "$MINER_DIR"
    tar -xzf "$TAR_FILE" -C "$MINER_DIR" --strip-components=1
    rm -f "$TAR_FILE"
    chmod -R 777 "$MINER_DIR"
}

write_config() {
    echo "📝 写入 miner.conf 配置"
    cat > "$MINER_DIR/miner.conf" <<EOCONF
algo=qubic_xmr
account=$ACCOUNT
pool=qubic.asia.apool.io:4334

cpu-off = false
xmr-cpu-off = false
xmr-1gb-pages = true
no-cpu-affinity = true

gpu-off = true
xmr-gpu-off = true
EOCONF
}

start_miner() {
    echo "▶️ 启动矿工 run.sh"
    bash "$MINER_DIR/run.sh" &
}

# 获取最新版本
LATEST=$(curl -s "$GITHUB_API" | grep '"tag_name":' | cut -d'"' -f4 | sed 's/^v//')
if [[ -z "$LATEST" ]]; then
    echo "❌ 获取最新版本失败"
    exit 1
fi
echo "🔎 最新版本: $LATEST"

# 当前版本
CURRENT=""
[[ -f "$MINER_DIR/VERSION" ]] && CURRENT=$(cat "$MINER_DIR/VERSION")

if [[ "$LATEST" == "$CURRENT" ]]; then
    echo "✅ 已是最新版本: $CURRENT"
    exit 0
fi

echo "⬇️ 发现新版本 $LATEST，开始更新..."
cleanup_old
download_and_extract "$LATEST"
write_config
echo "$LATEST" > "$MINER_DIR/VERSION"
start_miner

# 重载守护服务（如果 systemd 服务存在）
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable --now apoolminer.service >/dev/null 2>&1 || true

echo "✅ 自动更新完成"
EOF

chmod +x "$UPDATE_SCRIPT"

# ---------------- 写 systemd 守护服务 ----------------
cat > /etc/systemd/system/apoolminer.service <<EOF
[Unit]
Description=Apoolminer Daemon
After=network.target

[Service]
Type=simple
ExecStartPre=/usr/bin/pkill -f apoolminer || true
ExecStartPre=/usr/bin/pkill -f run.sh || true
ExecStart=/bin/bash $MINER_DIR/run.sh
WorkingDirectory=$MINER_DIR
Restart=always
RestartSec=5
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

# ---------------- 写 systemd 定时器 ----------------
cat > /etc/systemd/system/apoolminer-update.service <<EOF
[Unit]
Description=Update Apoolminer
[Service]
Type=oneshot
ExecStart=$UPDATE_SCRIPT
EOF

cat > /etc/systemd/system/apoolminer-update.timer <<EOF
[Unit]
Description=Check and update Apoolminer hourly
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Unit=apoolminer-update.service
[Install]
WantedBy=timers.target
EOF

# ---------------- 首次安装/更新 ----------------
echo "⬇️ 执行首次安装/更新..."
$UPDATE_SCRIPT

# ---------------- 启动服务与定时器 ----------------
systemctl daemon-reload || true
systemctl enable --now apoolminer.service >/dev/null 2>&1 || true
systemctl enable --now apoolminer-update.timer >/dev/null 2>&1 || true

echo "=========================================="
echo "✅ Apoolminer 安装完成并已启动"
echo "   - 查看挖矿服务: systemctl status apoolminer"
echo "   - 查看更新定时器: systemctl list-timers | grep apoolminer"
echo "   - 安装日志: $INSTALL_LOG"
echo "   - 更新日志: $UPDATE_LOG"
echo "=========================================="
