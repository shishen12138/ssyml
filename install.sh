#!/bin/bash
set -euo pipefail

# ---------------- 配置 ----------------
BASE_DIR="/root"
MINER_DIR="$BASE_DIR/apoolminer"
REPO="apool-io/apoolminer"
ACCOUNT="CP_qcy"
UPDATE_SCRIPT="/usr/local/bin/apoolminer-update.sh"
INSTALL_LOG="$BASE_DIR/apoolminer-install.log"
UPDATE_LOG="$BASE_DIR/apoolminer-update.log"

# 安装日志输出
exec > >(tee -a "$INSTALL_LOG") 2>&1

echo "=========================================="
echo "🚀 开始安装 Apoolminer 环境..."
echo "账户: $ACCOUNT"
echo "安装目录: $MINER_DIR"
echo "安装日志: $INSTALL_LOG"
echo "更新日志: $UPDATE_LOG"
echo "=========================================="

# ---------------- 写更新脚本 ----------------
echo "📦 写入更新脚本: $UPDATE_SCRIPT"
cat > "$UPDATE_SCRIPT" <<EOF
#!/bin/bash
set -euo pipefail

LOG_FILE="$UPDATE_LOG"
exec > >(tee -a "\$LOG_FILE") 2>&1

BASE_DIR="/root"
MINER_DIR="\$BASE_DIR/apoolminer"
REPO="apool-io/apoolminer"
ACCOUNT="CP_qcy"

echo "------------------------------------------"
echo "⏰ \$(date '+%F %T') - 开始检查更新..."

# 获取 GitHub 最新版本
LATEST=\$(curl -s https://api.github.com/repos/\$REPO/releases/latest | grep '"tag_name":' | cut -d'"' -f4)
if [[ -z "\$LATEST" ]]; then
    echo "❌ 获取 GitHub 最新版本失败"
    exit 1
fi
echo "🔎 最新版本: \$LATEST"

# 当前版本
CURRENT=""
[[ -f "\$MINER_DIR/VERSION" ]] && CURRENT=\$(cat "\$MINER_DIR/VERSION")
[[ "\$LATEST" == "\$CURRENT" ]] && echo "✅ 已是最新版本: \$CURRENT" && exit 0

echo "⬇️ 下载新版本: \$LATEST"
TAR_FILE="\$BASE_DIR/apoolminer_\${LATEST}.tar.gz"
URL="https://github.com/\$REPO/releases/download/\$LATEST/apoolminer_linux_qubic_autoupdate_\${LATEST}.tar.gz"

wget -q "\$URL" -O "\$TAR_FILE" || { echo "❌ 下载失败"; exit 1; }

rm -rf "\$MINER_DIR"
mkdir -p "\$MINER_DIR"
tar -xzf "\$TAR_FILE" -C "\$MINER_DIR" --strip-components=1
rm -f "\$TAR_FILE"
chmod -R 777 "\$MINER_DIR"

echo "\$LATEST" > "\$MINER_DIR/VERSION"

# 写配置
cat > "\$MINER_DIR/miner.conf" <<EOCONF
algo=qubic_xmr
account=\$ACCOUNT
pool=qubic.asia.apool.io:4334

#worker = my_worker

cpu-off = false
xmr-cpu-off = false
xmr-1gb-pages = true
no-cpu-affinity = true

gpu-off = true
xmr-gpu-off = true
EOCONF

echo "✅ 更新完成: \$LATEST"

# 重启挖矿服务
systemctl restart apoolminer.service || true
EOF

chmod +x "$UPDATE_SCRIPT"

# ---------------- 写 systemd 服务 ----------------
echo "⚙️ 写入 systemd 服务: /etc/systemd/system/apoolminer.service"
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
echo "⚙️ 写入 systemd 定时器..."
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

# ---------------- 执行首次安装/更新 ----------------
echo "⬇️ 执行首次安装/更新..."
$UPDATE_SCRIPT

# ---------------- 启动并启用服务和定时器 ----------------
echo "⚙️ 启动服务和定时器..."
systemctl daemon-reload
systemctl enable --now apoolminer.service
systemctl enable --now apoolminer-update.timer

echo "=========================================="
echo "✅ Apoolminer 安装完成并已启动"
echo "   - 查看挖矿服务: systemctl status apoolminer"
echo "   - 查看更新定时器: systemctl list-timers | grep apoolminer"
echo "   - 安装日志: $INSTALL_LOG"
echo "   - 更新日志: $UPDATE_LOG"
echo "=========================================="
