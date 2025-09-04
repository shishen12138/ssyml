#!/bin/bash

# 下载目标脚本并保存到 /usr/local/bin/startup.sh
echo "下载脚本..."
wget -O /usr/local/bin/startup.sh https://raw.githubusercontent.com/shishen12138/ssyml/main/1.sh

# 赋予脚本执行权限
echo "赋予执行权限..."
chmod +x /usr/local/bin/startup.sh

# 创建 systemd 服务文件，使得脚本开机自启
echo "创建 systemd 服务..."
cat > /etc/systemd/system/startup.service <<EOL
[Unit]
Description=Startup Script
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/startup.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOL

# 重新加载 systemd 配置
echo "重新加载 systemd 配置..."
systemctl daemon-reload

# 设置服务开机自启并启动
echo "设置开机自启并启动服务..."
systemctl enable startup.service
systemctl start startup.service

# 手动执行一次下载的脚本
echo "执行一次下载的脚本..."
/usr/local/bin/startup.sh

echo "脚本下载、保存并设置为开机自启后，已手动执行一次！"
