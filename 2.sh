#!/bin/bash

# 当前目录（或修改为具体路径）
BASE_DIR="$(pwd)"
cd "$BASE_DIR" || exit


# 删除指定文件夹
FOLDER="apoolminer_linux_qubic_autoupdate_v3.2.1"
if [ -d "$FOLDER" ]; then
    rm -rf "$FOLDER"
    echo "已删除文件夹: $FOLDER"
else
    echo "文件夹不存在: $FOLDER"
fi

# 删除所有匹配的压缩包
for zip in apoolminer_linux_qubic_autoupdate*.tar.gz*; do
    if [ -f "$zip" ]; then
        rm -f "$zip"
        echo "已删除压缩包: $zip"
    fi
done

echo "清理完成 ✅"
