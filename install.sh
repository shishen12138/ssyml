#!/bin/bash
set -euo pipefail

# ==========================================
# Apoolminer 一键安装 + 自动更新脚本（详细日志版）
# ==========================================

# ---------------- 配置 ----------------
BASE_DIR="/root"
MINER_DIR="$BASE_DIR/apoolminer"
ACCOUNT="CP_qcy"
UPDATE_SCRIPT="$BASE_DIR/apoolminer-update.sh"
INSTALL_LOG="$BASE_DIR/apoolminer-install.log"
UPDATE_LOG="$BASE_DIR/apoolminer-update.log"

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
set -euo pipefail

BASE_DIR="/root"
MINER_DIR="$BASE_DIR/apoolminer"
ACCOUNT="CP_qcy"
UPDATE_LOG="$BASE_DIR/apoolminer-update.log"

# 日志输出
exec > >(tee -a "$UPDATE_LOG") 2>&1
echo "------------------------------------------"
echo "⏰ $(date '+%F %T') - 开始自动更新"

cleanup_old() {
    echo "🧹 停止旧守护与清理进程..."

    # 停止所有相关 systemd 服务
    echo "🔎 检测旧服务..."
    systemctl list-unit-files 2>/dev/null | grep -i 'miner' | awk '{print $1}' | while read svc; do
        echo "⚠️ 尝试停止服务: $svc"
        systemctl stop "$svc" >/dev/null 2>&1 || echo "⚠️ 服务 $svc 不存在或已停止"
        systemctl disable "$svc" >/dev/null 2>&1 || true
    done

    # 杀掉相关进程
    echo "🔎 检测运行中的挖矿进程..."
    if pgrep -f apoolminer >/dev/null 2>&1; then
        pkill -9 -f apoolminer
        echo "✅ 已结束 apoolminer 进程"
    else
        echo "ℹ️ 没有发现运行中的 apoolminer 进程"
    fi

    if pgrep -f run.sh >/dev/null 2>&1; then
        pkill -9 -f run.sh
        echo "✅ 已结束 run.sh 进程"
    else
        echo "ℹ️ 没有发现运行中的 run.sh 进程"
    fi

    # 清理目录和压缩包
    if [ -d "$MINER_DIR" ]; then
        rm -rf "$MINER_DIR"
        echo "✅ 已删除旧挖矿目录: $MINER_DIR"
    else
        echo "ℹ️ 没有发现旧挖矿目录"
    fi

    rm -f "$BASE_DIR"/apoolminer_*.tar.gz >/dev/null 2>&1 || true
    echo "✅ 清理旧压缩包完成"
}

download_and_extract() {
    local latest="$1"
    TAR_FILE="$BASE_DIR/apoolminer_${latest}.tar.gz"
    URL="https://github.com/apool-io/apoolminer/releases/download/v${latest}/apoolminer_linux_qubic_autoupdate_v${latest}.tar.gz"

    echo "⬇️ 下载最新版本: $URL"
    if wget -q "$URL" -O "$TAR_FILE"; then
        echo "✅ 下载完成: $TAR_FILE"
    else
        echo "❌ 下载失败: $URL"
        exit 1
    fi

    echo "📦 解压文件..."
    mkdir -p "$MINER_DIR"
    tar -xzf "$TAR_FILE" -C "$MINER_DIR" --strip-components=1
    echo "✅ 解压完成: $MINER_DIR"
    rm -f "$TAR_FILE"
    chmod -R 777 "$MINER_DIR"
    echo "🔑 目录权限设置为 777"
}

write_config() {
    echo "📝 写入 miner.conf 配置..."
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
    echo "✅ 配置写入完成"
}

start_miner() {
    echo "▶️ 启动矿工 run.sh..."
    if bash "$MINER_DIR/run.sh" &; then
        echo "✅ 挖矿程序已启动"
    else
        echo "❌ 启动挖矿程序失败"
    fi
}

# 获取最新版本
# 获取 GitHub 最新版本号（用 API 更可靠）
LATEST=$(curl -s https://api.github.com/repos/apool-io/apoolminer/releases/latest | \
         grep '"tag_name":' | cut -d'"' -f4 | sed 's/^v//')

if [[ -z "$LATEST" ]]; then
    echo "❌ 获取 GitHub 最新版本失败"
    exit 1
fi

echo "🔎 最新版本: $LATEST"


# 当前版本
CURRENT=""
[[ -f "$MINER_DIR/VERSION" ]] && CURRENT=$(cat "$MINER_DIR/VERSION")
echo "ℹ️ 当前版本: ${CURRENT:-未安装}"

if [[ "$LATEST" == "$CURRENT" ]]; then
    echo "✅ 已是最新版本，无需更新"
    exit 0
fi

echo "⬇️ 发现新版本 $LATEST，开始更新..."
cleanup_old
download_and_extract "$LATEST"
write_config
echo "$LATEST" > "$MINER_DIR/VERSION"
echo "✅ 已写入版本号文件"
start_miner

# 重载 systemd 守护服务
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable --now apoolminer.service >/dev/null 2>&1 || true
echo "✅ 守护服务已启动"

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
