#!/bin/bash
# 清理旧版本
BASE_DIR="/root"
cd "$BASE_DIR" || exit

# 删除旧文件夹
if [ -d "apoolminer_linux_qubic_autoupdate_v3.2.1" ]; then
    rm -rf "apoolminer_linux_qubic_autoupdate_v3.2.1"
    echo "已删除文件夹: apoolminer_linux_qubic_autoupdate_v3.2.1"
fi

# 删除旧压缩包
for zip in apoolminer_linux_qubic_autoupdate*.tar.gz*; do
    if [ -f "$zip" ]; then
        rm -f "$zip"
        echo "已删除压缩包: $zip"
    fi
done

echo "清理完成 ✅"

# 进入新版本目录
NEW_DIR="apoolminer_linux_qubic_autoupdate_v3.2.2"
cd "$BASE_DIR/$NEW_DIR" || exit

# 查看日志
tail -f qubic_xmr.log
