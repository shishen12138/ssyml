#!/bin/bash
set -e  # 出错立即退出

# ---------------- 常量 ----------------
BASE_DIR="/root"
MINER_VERSION="v3.2.2"
MINER_DIR="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}"
ACCOUNT="CP_qcy"

cd "$BASE_DIR"

# ---------------- 结束已有进程 ----------------
echo "检查是否已有 apoolminer 进程..."
while pgrep -f apoolminer > /dev/null; do
    echo "发现 apoolminer 进程，正在结束..."
    pkill -f apoolminer
    sleep 2
done
echo "没有 apoolminer 进程，继续执行脚本..."

# ---------------- 下载 & 解压（不保存 tar.gz） ----------------
echo "开始下载并解压文件..."
wget -q "https://github.com/apool-io/apoolminer/releases/download/$MINER_VERSION/apoolminer_linux_qubic_autoupdate_${MINER_VERSION}.tar.gz" -O - | tar -xz
echo "下载并解压完成"

cd "$MINER_DIR"

# ---------------- 修改权限 & 配置 ----------------
echo "修改权限..."
chmod -R 777 .
sleep 1

# ---------------- 更新 miner.conf 前三行 ----------------
echo "更新 miner.conf 的 algo、account、pool..."
CONF_FILE="miner.conf"

# algo
if grep -q "^algo=" "$CONF_FILE"; then
    sed -i "s/^algo=.*/algo=qubic_xmr/" "$CONF_FILE"
else
    sed -i "1i algo=qubic_xmr" "$CONF_FILE"
fi

# account
if grep -q "^account=" "$CONF_FILE"; then
    sed -i "s/^account=.*/account=$ACCOUNT/" "$CONF_FILE"
else
    sed -i "2i account=$ACCOUNT" "$CONF_FILE"
fi

# pool
if grep -q "^pool=" "$CONF_FILE"; then
    sed -i "s/^pool=.*/pool=qubic.asia.apool.io:4334/" "$CONF_FILE"
else
    sed -i "3i pool=qubic.asia.apool.io:4334" "$CONF_FILE"
fi

# ---------------- 启动矿工 ----------------
echo "启动 miner..."
bash run.sh &

# ---------------- 查看日志 ----------------
echo "显示日志，按 Ctrl+C 退出..."
tail -f qubic_xmr.log
