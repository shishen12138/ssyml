#!/bin/bash
set -e  # 出错立即退出

# ---------------- 常量 ----------------
BASE_DIR="/root"
MINER_VERSION="v3.3.0"
MINER_DIR="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}"
ACCOUNT="CP_qcy"
DOWNLOAD_URL="https://github.com/apool-io/apoolminer/releases/download/$MINER_VERSION/apoolminer_linux_qubic_autoupdate_${MINER_VERSION}.tar.gz"
TAR_FILE="apoolminer_linux_qubic_autoupdate_${MINER_VERSION}.tar.gz"

cd "$BASE_DIR"

# ---------------- 结束已有进程 ----------------
echo "检查是否已有 apoolminer 进程..."
while pgrep -f apoolminer > /dev/null; do
    echo "发现 apoolminer 进程，正在结束..."
    pkill -f apoolminer
    sleep 2
done
echo "没有 apoolminer 进程，继续执行脚本..."

# ---------------- 清理旧版本 ----------------
echo "清理旧版本文件..."
for dir in apoolminer_linux_qubic_autoupdate*; do
    if [ -d "$BASE_DIR/$dir" ]; then
        rm -rf "$BASE_DIR/$dir"
        echo "已删除文件夹: $dir"
    fi
done

for zip in "$BASE_DIR"/apoolminer_linux_qubic_autoupdate*.tar.gz*; do
    if [ -f "$zip" ]; then
        rm -f "$zip"
        echo "已删除压缩包: $zip"
    fi
done
echo "清理完成 ✅"

# ---------------- 下载 & 解压 ----------------
echo "开始下载并解压新版本文件..."
RETRY_COUNT=0
MAX_RETRIES=5

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    wget -q "$DOWNLOAD_URL" -O "$TAR_FILE"
    
    if [ $? -eq 0 ] && [ -s "$TAR_FILE" ]; then
        echo "压缩包下载完成，正在检查..."
        tar -tzf "$TAR_FILE" > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo "压缩包验证通过，开始解压..."
            tar -xz -f "$TAR_FILE"
            echo "下载并解压完成"
            echo "等待 5 秒让解压文件就绪..."
            sleep 5
            break
        else
            echo "压缩包损坏，重新下载..."
            rm -f "$TAR_FILE"
        fi
    else
        echo "下载失败，正在重试... (尝试次数：$RETRY_COUNT)"
        rm -f "$TAR_FILE"
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 5
done

if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "下载失败，已达到最大重试次数。退出脚本。"
    exit 1
fi

cd "$MINER_DIR"

# ---------------- 修改权限 & 配置 ----------------
echo "修改权限..."
chmod -R 777 .
sleep 2

echo "更新 miner.conf 设置..."
CONF_FILE="miner.conf"
cat > "$CONF_FILE" <<EOF
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
echo "矿工已启动"
