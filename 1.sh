#!/bin/bash
set -e  # 出错立即退出

cd /root

# ---------------- MSR 检查 ----------------
echo "检测 MSR 模块..."
if modprobe msr 2>/dev/null; then
    echo "✅ MSR 模块已加载成功"
else
    echo "⚠ MSR 模块无法加载 (云服务器通常不支持)，忽略 WARN"
fi

# ---------------- 下载 & 解压 ----------------
echo "开始下载文件..."
wget https://github.com/apool-io/apoolminer/releases/download/v3.2.2/apoolminer_linux_qubic_autoupdate_v3.2.2.tar.gz
sleep 1

echo "开始解压文件..."
tar -xzvf apoolminer_linux_qubic_autoupdate_v3.2.2.tar.gz
sleep 1

cd apoolminer_linux_qubic_autoupdate_v3.2.2
sleep 1

# ---------------- 修改权限 & 配置 ----------------
echo "修改权限..."
chmod -R 777 .
sleep 1

echo "修改 miner.conf 账户..."
sed -i 's/account=CP_.*/account=CP_qcy/' miner.conf
sleep 1

echo "修改 miner.conf GPU 设置..."
sed -i 's/#gpu-off = true/gpu-off = true/' miner.conf
sleep 1

# ---------------- 启动矿工 ----------------
echo "启动 miner..."
bash run.sh &

sleep 5

echo "查看日志，按 Ctrl+C 退出..."
tail -f qubic_xmr.log

