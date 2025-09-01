#!/bin/bash
set -e  # 出错立即退出

# ---------------- 常量 ----------------
BASE_DIR="/root"
MINER_VERSION="v3.2.2"
MINER_DIR="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}"
ACCOUNT="CP_qcy"
GPU_OFF="gpu-off = true"

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
bash run.sh &

# ---------------- 查看日志 ----------------
echo "显示日志，按 Ctrl+C 退出..."
tail -f qubic_xmr.log
