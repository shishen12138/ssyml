import os
import re
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from requests.adapters import HTTPAdapter, Retry
import math

# ====== 配置区 ======
ACCOUNT = "qcycloud@proton.me"
PASSWORD = "jie1994@06"
LOGIN_URL = "https://www.apool.io/login?redirect=https://www.apool.io/myMiner"
API_URL = "https://client.apool.io/miner/list"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), "Desktop", "apool_token.txt")
IP_PATTERN = re.compile(r"\d+\.\d+\.\d+\.\d+")
PAGE_SIZE = 100
MAX_RETRIES = 5
UPDATE_INTERVAL = 600

# 新账户
ACCOUNTS = ["CP_qcy", "CP_qcy1"]
IP_FILES = {
    "CP_qcy": os.path.join(os.path.expanduser("~"), "Desktop", "apool_web_ips.txt"),
    "CP_qcy1": os.path.join(os.path.expanduser("~"), "Desktop", "apool_web_ips1.txt")
}

# ====== 登录获取 token ======
def get_token_via_selenium():
    print("🚀 启动浏览器登录 Apool ...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(LOGIN_URL)

    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "input")))

    inputs = driver.find_elements(By.TAG_NAME, "input")
    inputs[0].send_keys(ACCOUNT)
    inputs[1].send_keys(PASSWORD)
    print("✅ 输入账号密码")

    login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'login-btn')]")))
    login_btn.click()
    print("🔐 登录中，请稍候...")
    time.sleep(10)

    token = driver.execute_script("""
        return localStorage.getItem('token') 
            || sessionStorage.getItem('token') 
            || localStorage.getItem('web-token') 
            || sessionStorage.getItem('web-token');
    """)

    if not token:
        cookies = driver.get_cookies()
        for c in cookies:
            if 'token' in c['name']:
                token = c['value']
                break

    driver.quit()
    if not token:
        raise Exception("❌ 未找到 token，请检查登录是否成功。")

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    print(f"✅ 成功获取 token: {token[:40]}... (已保存到桌面)")

    return token

# ====== 读取本地 token ======
def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

# ====== 验证 token 是否有效 ======
def check_token_valid(token):
    headers = {"Authorization": token}
    try:
        res = requests.get(API_URL, headers=headers, params={
            "account": ACCOUNTS[0],  # 默认使用第一个账户进行验证
            "tag": "online",
            "currency": "Qubic",
            "pageNum": 1,
            "pageSize": 1
        }, timeout=10)
        data = res.json()
        print(f"📄 验证 token 响应：{data}")  # 打印返回数据
        return res.status_code == 200 and data.get("code") == 0
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

# ====== 读取已存在 IP ======
def read_existing_ips(account):
    output_file = IP_FILES[account]
    if not os.path.exists(output_file):
        return set()
    with open(output_file, "r", encoding="utf-8") as f:
        return set(f.read().splitlines())

# ====== 保存 IP（去重 + 排序） ======
def save_ips(account, ips):
    output_file = IP_FILES[account]
    sorted_ips = sorted(ips, key=lambda x: tuple(int(i) for i in x.split(".")))
    with open(output_file, "w", encoding="utf-8") as f:
        for ip in sorted_ips:
            f.write(ip + "\n")

# ====== 带重试请求 ======
def requests_get_with_retry(url, headers, params, retries=MAX_RETRIES):
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=2,  # 增加等待间隔的指数因子
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    response = session.get(url, headers=headers, params=params, timeout=10)
    time.sleep(5)  # 可以根据需要调整等待时间
    return response

# ====== 分页抓取在线 IP ======
def fetch_online_ips(token, account_name):
    headers = {
        "Authorization": token,
        "Origin": "https://www.apool.io",
        "Referer": "https://www.apool.io/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    all_ips = set()
    page = 1
    round_count = 1

    while True:
        print(f"🔄 {account_name} 第 {round_count} 轮抓取开始...")

        while True:
            params = {
                "account": account_name,  # 使用指定账户抓取
                "tag": "online",
                "currency": "Qubic",
                "pageNum": page,
                "pageSize": PAGE_SIZE,
            }
            try:
                res = requests_get_with_retry(API_URL, headers, params)
            except Exception as e:
                print(f"⚠️ 第 {page} 页请求异常: {e}, 跳过...")
                page += 1
                continue

            data = res.json()
            miners = data.get("result", {}).get("miners", [])
            total_online = data.get("result", {}).get("tag", {}).get("online", 0)
            total = data.get("result", {}).get("pagination", {}).get("total", 0)

            total_pages = math.ceil(total / PAGE_SIZE)  # 计算总页数

            print(f"⚡️ 当前抓取第 {page} 页，共 {total_pages} 页")
            print(f"🌐 当前页在线矿机数: {len(miners)}，已抓取的在线 IP 数: {len(all_ips)}")
            print(f"💬 总的在线账号数量: {total_online}")

            if not miners:
                break

            for miner in miners:
                ip = miner.get("name", "")
                if IP_PATTERN.match(ip):
                    all_ips.add(ip)

            page += 1
            if page > total_pages:
                break

        if len(all_ips) >= total_online:
            print(f"✅ {account_name} 抓取完成，共抓取到 {len(all_ips)} 个 IP")
            break

        round_count += 1
        page = 1  # 重置页数，重新抓取

    return all_ips

# ====== 定时更新（新增 + 删除离线） ======
def update_ips(token):
    while True:
        if not check_token_valid(token):  # 在更新前检查token是否有效
            print("🔑 Token无效，重新登录获取Token...")
            token = get_token_via_selenium()

        # 分开抓取每个账户的IP
        for account in ACCOUNTS:
            print(f"\n==================== {account} ====================")
            print(f"⏰ 开始更新在线 IP ({account}) ...")
            online_ips = fetch_online_ips(token, account)
            existing_ips = read_existing_ips(account)

            # 删除离线 IP
            removed_ips = existing_ips - online_ips
            if removed_ips:
                print(f"❌ 删除离线 IP: {removed_ips}")

            # 新增 IP
            new_ips = online_ips - existing_ips
            if new_ips:
                print(f"✅ 新增在线 IP: {new_ips}")

            # 保存更新后的 IP
            save_ips(account, online_ips)
            print(f"📄 更新完成，共 {len(online_ips)} 个在线 IP ({account})。")

        print(f"💤 等待 {UPDATE_INTERVAL / 60} 分钟后再次更新...")
        time.sleep(UPDATE_INTERVAL)

# ====== 主程序入口 ======
if __name__ == "__main__":
    token = load_token()
    if token and check_token_valid(token):
        print("✅ 本地 token 有效，直接使用。")
    else:
        print("🔄 token 无效或不存在，自动登录获取新 token ...")
        token = get_token_via_selenium()

    update_ips(token)
