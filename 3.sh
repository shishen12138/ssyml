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

# ---------------- 配置 miner.conf ----------------
echo "更新 miner.conf 设置..."
CONF_FILE="miner.conf"

cat > miner.conf <<EOF
algo=qubic_xmr
account=$ACCOUNT
pool=qubic.asia.apool.io:4334

#worker = my_worker

# ---------------- CPU 挖矿 ----------------
cpu-off = false
xmr-cpu-off = false
xmr-1gb-pages = true
no-cpu-affinity = true

# ---------------- GPU 关闭 ----------------
gpu-off = true
xmr-gpu-off = true
EOF

# ---------------- 启动矿工 ----------------
echo "启动 miner..."
bash run.sh &

# ---------------- 查看日志 ----------------
echo "显示日志，按 Ctrl+C 退出..."
tail -f qubic_xmr.log
