#!/bin/bash
# 删除当前目录下指定文件夹和所有版本压缩包

# 使用当前目录
BASE_DIR="$(pwd)"
cd "$BASE_DIR" || exit

# 删除固定文件夹
if [ -d "apoolminer_linux_qubic_autoupdate_v3.2.1" ]; then
    rm -rf "apoolminer_linux_qubic_autoupdate_v3.2.1"
    echo "已删除文件夹: apoolminer_linux_qubic_autoupdate_v3.2.1"
fi

# 删除所有匹配压缩包
for zip in apoolminer_linux_qubic_autoupdate*.tar.gz*; do
    if [ -f "$zip" ]; then
        rm -f "$zip"
        echo "已删除压缩包: $zip"
    fi
done

echo "清理完成 ✅"
