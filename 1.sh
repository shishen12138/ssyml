#!/bin/bash
set -e  # 出错立即退出

# ---------------- 常量 ----------------
BASE_DIR="/root"
MINER_VERSION="v3.2.2"
TAR_NAME="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}.tar.gz"
MINER_DIR="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}"
ACCOUNT="CP_qcy"
GPU_OFF="gpu-off = true"

cd "$BASE_DIR"

# ---------------- 下载 & 解压 ----------------
echo "开始下载文件..."
if ! wget -q "https://github.com/apool-io/apoolminer/releases/download/$MINER_VERSION/$TAR_NAME" -O "$TAR_NAME"; then
    echo "下载失败，稍后重试..."
    exit 1
fi
echo "下载完成"

echo "开始解压文件..."
tar -xzf "$TAR_NAME"
echo "解压完成"

cd "$MINER_DIR"

# ---------------- 修改权限 & 配置 ----------------
echo "修改权限..."
chmod -R 755 .
sleep 1

echo "修改 miner.conf 账户..."
if grep -q "^account=" miner.conf; then
    sed -i "s/^account=.*/account=$ACCOUNT/" miner.conf
else
    echo "account=$ACCOUNT" >> miner.conf
fi

echo "修改 miner.conf GPU 设置..."
sed -i "s/#gpu-off = true/$GPU_OFF/" miner.conf || echo "$GPU_OFF" >> miner.conf

# ---------------- 启动矿工 ----------------
echo "启动 miner..."
bash run.sh

# ---------------- 循环检测进程 ----------------
echo "等待 apoolminer 启动..."
START_TIME=$(date +%s)
TIMEOUT=30
while ! pgrep -f apoolminer > /dev/null; do
    sleep 1
    NOW=$(date +%s)
    if (( NOW - START_TIME > TIMEOUT )); then
        echo "apoolminer 启动超时！"
        exit 1
    fi
done
echo "apoolminer 启动成功"

# ---------------- 查看日志 ----------------
echo "显示日志，按 Ctrl+C 退出..."
tail -f qubic_xmr.log
