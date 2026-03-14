import time
import csv
import os
import sys
import pytz
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from crypto15 import update_all_token_ids, update_all_5m_token_ids

load_dotenv(override=True)


def get_env_value(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    if isinstance(value, str):
        return value.strip().strip('"').strip("'")
    return default


def get_env_bool(name: str, default: str = "1") -> bool:
    value = get_env_value(name, default).lower()
    return value in {"1", "true", "yes", "y", "on"}

POLYMARKET_CONFIG = {
    "FUNDER_ADDRESS": get_env_value("POLYMARKET_FUNDER_ADDRESS", ""),
    "PRIVATE_KEY": get_env_value("POLYMARKET_PRIVATE_KEY", ""),
    "SIGNATURE_TYPE": int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "2")),
    "DATA_TIMEZONE": get_env_value("POLYMARKET_DATA_TIMEZONE", "Asia/Shanghai"),
}

COLLECTION_CONFIG = {
    "ENABLE_POLYMARKET": get_env_bool("ENABLE_POLYMARKET", "1"),
    "ENABLE_BINANCE": get_env_bool("ENABLE_BINANCE", "1"),
}

# 全局变量
MARKET_TOKEN_IDS = {
    "BTC": {"UP": "none"},
    "ETH": {"UP": "none"},
    "SOL": {"UP": "none"},
    "XRP": {"UP": "none"},
    "BTC5": {"UP": "none"},  # BTC 5分钟周期
    "ETH5": {"UP": "none"},  # ETH 5分钟周期
    "SOL5": {"UP": "none"},  # SOL 5分钟周期
    "XRP5": {"UP": "none"},  # XRP 5分钟周期
}

# 用于跟踪连续获取 none 的次数
none_counter = {
    "BTC": 0,
    "ETH": 0,
    "SOL": 0,
    "XRP": 0,
    "BTC5": 0,
    "ETH5": 0,
    "SOL5": 0,
    "XRP5": 0,
}

binance_none_counter = {
    "BTC": 0,
    "ETH": 0,
    "SOL": 0,
    "XRP": 0,
}

# 连续 none 的阈值（15秒=15次）
MAX_NONE_COUNT = 15

BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
}

BINANCE_API_URL = "https://api.binance.com/api/v3/ticker/price"
binance_session = requests.Session()


# ======================== 客户端初始化 ========================
CLOB_API = "https://clob.polymarket.com"
client = None

if COLLECTION_CONFIG["ENABLE_POLYMARKET"]:
    if not POLYMARKET_CONFIG["PRIVATE_KEY"] or not POLYMARKET_CONFIG["FUNDER_ADDRESS"]:
        print("[警告] ENABLE_POLYMARKET=1 但缺少 Polymarket 密钥配置，已自动关闭 Polymarket 采集")
        COLLECTION_CONFIG["ENABLE_POLYMARKET"] = False
    else:
        try:
            client = ClobClient(
                CLOB_API,
                key=POLYMARKET_CONFIG["PRIVATE_KEY"],
                chain_id=137,
                signature_type=POLYMARKET_CONFIG["SIGNATURE_TYPE"],
                funder=POLYMARKET_CONFIG["FUNDER_ADDRESS"],
            )
            # Get & Set API credentials
            creds = client.derive_api_key()
            client.set_api_creds(creds)
        except Exception as ex:
            print(f"[警告] Polymarket 客户端初始化失败，已自动关闭 Polymarket 采集: {ex}")
            COLLECTION_CONFIG["ENABLE_POLYMARKET"] = False


def get_data_now() -> datetime:
    """获取用于落盘的当前时间（可配置时区）"""
    timezone_name = POLYMARKET_CONFIG.get("DATA_TIMEZONE", "Asia/Shanghai")
    return datetime.now(pytz.timezone(timezone_name))


def fetch_binance_single_price(symbol: str) -> str | None:
    """获取单个币安现货价格"""
    try:
        response = binance_session.get(
            BINANCE_API_URL,
            params={"symbol": symbol},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("price") is not None:
            return str(data["price"])
    except Exception:
        pass
    return None


def fetch_binance_prices() -> dict | int:
    """并发获取币安现货价格（BTC/ETH/SOL/XRP），任一失败则返回0"""
    result = {}

    with ThreadPoolExecutor(max_workers=len(BINANCE_SYMBOLS)) as executor:
        future_map = {
            executor.submit(fetch_binance_single_price, symbol): coin
            for coin, symbol in BINANCE_SYMBOLS.items()
        }

        for future in as_completed(future_map):
            coin = future_map[future]
            price = future.result()
            if price is not None:
                result[coin] = price

    if len(result) == len(BINANCE_SYMBOLS):
        return result
    return 0


def fetch_polymarket_prices() -> dict:
    """并发获取所有 Polymarket 市场价格"""
    result = {}

    with ThreadPoolExecutor(max_workers=len(MARKET_TOKEN_IDS)) as executor:
        future_map = {
            executor.submit(get_price_sync, tokens["UP"]): coin
            for coin, tokens in MARKET_TOKEN_IDS.items()
        }

        for future in as_completed(future_map):
            coin = future_map[future]
            try:
                result[coin] = future.result()
            except Exception:
                result[coin] = "none"

    return result


def save_binance_to_csv(coin: str, current_datetime: datetime, price_str: str):
    """将币安数据保存到对应的CSV文件（仅 time 与 price 两列）"""
    timestamp = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
    date_str = current_datetime.strftime('%Y-%m-%d')
    month_str = date_str[:7]

    data_dir = os.path.join("data", month_str, date_str)
    os.makedirs(data_dir, exist_ok=True)

    filename = f"{coin}_BINANCE_{date_str}.csv"
    file_path = os.path.join(data_dir, filename)
    file_exists = os.path.exists(file_path)

    with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(['time', 'price'])
        writer.writerow([timestamp, price_str])

# 保存数据到CSV文件
def save_to_csv(coin: str, current_datetime: datetime, price_str: str):
    """将数据保存到对应的CSV文件"""
    timestamp = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
    # 生成日期信息
    date_str = current_datetime.strftime('%Y-%m-%d')
    month_str = date_str[:7]  # YYYY-MM

    # 创建目录结构：data/YYYY-MM/YYYY-MM-DD
    data_dir = os.path.join("data", month_str, date_str)
    os.makedirs(data_dir, exist_ok=True)

    # 生成文件名（按日期）
    # 5分钟市场使用不同的文件名前缀以避免混淆
    if coin.endswith("5"):
        filename = f"{coin}MIN_{date_str}.csv"
    else:
        filename = f"{coin}_{date_str}.csv"

    file_path = os.path.join(data_dir, filename)
    
    # 检查文件是否存在，如果不存在则写入表头
    file_exists = os.path.exists(file_path)
    
    with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # 如果是新文件，写入表头
        if not file_exists:
            writer.writerow(['time', 'price'])
        # 写入数据行
        writer.writerow([timestamp, price_str])

# 同步获取价格函数
def get_price_sync(token_id: str) -> str:
    """使用官方客户端获取价格，返回字符串格式"""
    if client is None or not token_id or token_id == "none":
        return "none"
    
    try:
        # 使用客户端的官方方法获取价格
        midpoint_data = client.get_midpoint(token_id)
        mid_price = 0.0

        if isinstance(midpoint_data, dict):
            midpoint_value = midpoint_data.get('midpoint', 0) or midpoint_data.get('mid', 0)
            mid_price = float(midpoint_value or 0)
        elif isinstance(midpoint_data, (int, float, str)):
            mid_price = float(midpoint_data)
        
        if mid_price > 0:
            return f"{mid_price:.2f}"
            
        # 备选：尝试orderbook
        book = client.get_order_book(token_id)
        if hasattr(book, 'bids') and book.bids:
            best_bid = float(book.bids[0].price)
            if best_bid > 0:
                return f"{best_bid:.2f}"
                
    except Exception:
        pass
    
    return "none"

# 计算下一个5分钟周期开始时间（美东时间）
def get_next_5m_cycle_start():
    """获取下一个5分钟周期的美东时间开始时刻"""
    et_tz = pytz.timezone("America/New_York")
    now_et = datetime.now(et_tz)
    
    # 计算当前是第几个5分钟周期
    minutes_since_midnight = now_et.hour * 60 + now_et.minute
    current_cycle = minutes_since_midnight // 5
    
    # 计算下一个周期的开始时间
    next_cycle_start_minutes = (current_cycle + 1) * 5
    next_cycle_hour = next_cycle_start_minutes // 60
    next_cycle_minute = next_cycle_start_minutes % 60
    
    next_cycle_start = now_et.replace(
        hour=next_cycle_hour,
        minute=next_cycle_minute,
        second=0,
        microsecond=0
    )
    
    if next_cycle_start <= now_et:
        next_cycle_start += timedelta(days=1)
    
    return next_cycle_start


# 计算下一个15分钟周期开始时间（美东时间）
def get_next_cycle_start():
    """获取下一个15分钟周期的美东时间开始时刻"""
    et_tz = pytz.timezone("America/New_York")
    now_et = datetime.now(et_tz)
    
    # 计算当前是第几个15分钟周期
    minutes_since_midnight = now_et.hour * 60 + now_et.minute
    current_cycle = minutes_since_midnight // 15
    
    # 计算下一个周期的开始时间
    next_cycle_start_minutes = (current_cycle + 1) * 15
    next_cycle_hour = next_cycle_start_minutes // 60
    next_cycle_minute = next_cycle_start_minutes % 60
    
    next_cycle_start = now_et.replace(
        hour=next_cycle_hour,
        minute=next_cycle_minute,
        second=0,
        microsecond=0
    )
    
    if next_cycle_start <= now_et:
        next_cycle_start += timedelta(days=1)
    
    return next_cycle_start

# 重启脚本
def restart_script():
    """重启当前脚本"""
    print("\n" + "=" * 50)
    print("检测到连续15秒获取价格失败，正在重启脚本...")
    print("=" * 50)
    time.sleep(2)  # 等待2秒让消息显示
    
    # 重启当前Python脚本
    python = sys.executable
    os.execl(python, python, *sys.argv)

# 主监控循环
def main_loop():
    """主监控循环 - 每秒执行一次"""
    while True:
        # 获取当前时间戳
        current_datetime = get_data_now()
        timestamp = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
        
        # 输出时间戳
        print(f"[{timestamp}]")
        
        if COLLECTION_CONFIG["ENABLE_POLYMARKET"]:
            # 并发获取并保存所有币种价格
            polymarket_prices = fetch_polymarket_prices()
            for coin in MARKET_TOKEN_IDS.keys():
                price_str = polymarket_prices.get(coin, "none")
                print(f"  {coin}: {price_str}")
                save_to_csv(coin, current_datetime, price_str)

                # 更新 none 计数器
                if price_str == "none":
                    none_counter[coin] += 1
                    print(f"    ⚠️ {coin} 连续 {none_counter[coin]} 秒获取失败")

                    # 检查是否达到重启阈值
                    if none_counter[coin] >= MAX_NONE_COUNT:
                        print(f"    ✗ {coin} 连续 {none_counter[coin]} 秒获取失败，触发重启！")
                        restart_script()
                else:
                    # 价格正常，重置计数器
                    if none_counter[coin] > 0:
                        print(f"    ✓ {coin} 恢复正常，重置计数器")
                    none_counter[coin] = 0

        if COLLECTION_CONFIG["ENABLE_BINANCE"]:
            # 获取并保存币安秒级现货价格
            binance_prices = fetch_binance_prices()
            for coin in BINANCE_SYMBOLS.keys():
                if isinstance(binance_prices, dict):
                    price_str = binance_prices.get(coin, "0")
                else:
                    price_str = "0"
                print(f"  {coin}_BINANCE: {price_str}")
                save_binance_to_csv(coin, current_datetime, price_str)

                if price_str in {"none", "0"}:
                    binance_none_counter[coin] += 1
                    print(f"    ⚠️ {coin}_BINANCE 连续 {binance_none_counter[coin]} 秒获取失败")

                    if binance_none_counter[coin] >= MAX_NONE_COUNT:
                        print(f"    ✗ {coin}_BINANCE 连续 {binance_none_counter[coin]} 秒获取失败，触发重启！")
                        restart_script()
                else:
                    if binance_none_counter[coin] > 0:
                        print(f"    ✓ {coin}_BINANCE 恢复正常，重置计数器")
                    binance_none_counter[coin] = 0
        
        print("-" * 30)
        
        # 精确等待1秒
        time.sleep(1)

# 定时更新token_id
def update_tokens_thread():
    """后台线程：按美东时间周期更新token_id（15分钟和5分钟）"""
    while True:
        # 获取两个周期的下一个开始时间
        next_15m_cycle = get_next_cycle_start()
        next_5m_cycle = get_next_5m_cycle_start()
        
        # 选择最近的更新时间
        et_tz = pytz.timezone("America/New_York")
        now_et = datetime.now(et_tz)
        
        next_update = min(next_15m_cycle, next_5m_cycle)
        wait_seconds = (next_update - now_et).total_seconds()
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"下次更新: {next_update.strftime('%Y-%m-%d %H:%M:%S')} (美东)")
        time.sleep(wait_seconds)
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 更新token_id...")
        
        # 检查是否需要更新15分钟周期
        if abs((next_update - next_15m_cycle).total_seconds()) < 1:  # 允许1秒误差
            print("执行15分钟周期更新...")
            update_all_token_ids(MARKET_TOKEN_IDS)
            print("15分钟周期更新完成")
        
        # 检查是否需要更新5分钟周期
        if abs((next_update - next_5m_cycle).total_seconds()) < 1:  # 允许1秒误差
            print("执行5分钟周期更新...")
            update_all_5m_token_ids(MARKET_TOKEN_IDS)
            print("5分钟周期更新完成")
        
        print("更新完成")

# 主函数
def main():
    print(f"数据落盘时区: {POLYMARKET_CONFIG.get('DATA_TIMEZONE', 'Asia/Shanghai')}")
    print(f"采集开关: Polymarket={COLLECTION_CONFIG['ENABLE_POLYMARKET']}, Binance={COLLECTION_CONFIG['ENABLE_BINANCE']}")

    if not COLLECTION_CONFIG["ENABLE_POLYMARKET"] and not COLLECTION_CONFIG["ENABLE_BINANCE"]:
        raise ValueError("ENABLE_POLYMARKET 和 ENABLE_BINANCE 不能同时关闭")

    if COLLECTION_CONFIG["ENABLE_POLYMARKET"]:
        print("正在初始化 token_id...")
        # 初始化15分钟周期token_id
        update_all_token_ids(MARKET_TOKEN_IDS)
        # 初始化5分钟周期token_id
        update_all_5m_token_ids(MARKET_TOKEN_IDS)
        print("初始化完成")
        print("=" * 50)

        # 显示当前监控的市场
        print("当前监控的市场:")
        for coin, tokens in MARKET_TOKEN_IDS.items():
            status = "✓" if tokens["UP"] != "none" else "✗"
            print(f"  {status} {coin}")
        print("=" * 50)

        # 启动定时更新线程
        import threading
        update_thread = threading.Thread(target=update_tokens_thread, daemon=True)
        update_thread.start()
        print("定时更新线程已启动")
    else:
        print("已关闭 Polymarket 采集，仅运行币安采集")
    
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n程序已停止")

if __name__ == "__main__":
    main()