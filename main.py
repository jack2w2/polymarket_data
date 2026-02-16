import time
import csv
import os
import sys
import pytz
from datetime import datetime, timedelta
from config import POLYMARKET_CONFIG
from py_clob_client.client import ClobClient
from crypto15 import update_all_token_ids, update_btc5_token_id

# 全局变量
MARKET_TOKEN_IDS = {
    "BTC": {"UP": "none"},
    "ETH": {"UP": "none"},
    "SOL": {"UP": "none"},
    "XRP": {"UP": "none"},
    "BTC5": {"UP": "none"},  # BTC 5分钟周期
}

# 用于跟踪连续获取 none 的次数
none_counter = {
    "BTC": 0,
    "ETH": 0,
    "SOL": 0,
    "XRP": 0,
    "BTC5": 0,
}

# 连续 none 的阈值（15秒=15次）
MAX_NONE_COUNT = 15


# ======================== 客户端初始化 ========================
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
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

# 保存数据到CSV文件
def save_to_csv(coin: str, timestamp: str, price_str: str):
    """将数据保存到对应的CSV文件"""
    # 生成文件名（按日期）
    date_str = timestamp.split()[0]  # 提取日期部分
    # BTC5使用不同的文件名前缀以避免混淆
    if coin == "BTC5":
        filename = f"BTC5MIN_{date_str}.csv"
    else:
        filename = f"{coin}_{date_str}.csv"
    
    # 检查文件是否存在，如果不存在则写入表头
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # 如果是新文件，写入表头
        if not file_exists:
            writer.writerow(['time', 'price'])
        # 写入数据行
        writer.writerow([timestamp, price_str])

# 同步获取价格函数
def get_price_sync(token_id: str) -> str:
    """使用官方客户端获取价格，返回字符串格式"""
    if not token_id or token_id == "none":
        return "none"
    
    try:
        # 使用客户端的官方方法获取价格
        midpoint_data = client.get_midpoint(token_id)
        mid_price = float(midpoint_data.get('midpoint', 0)) or float(midpoint_data.get('mid', 0))
        
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
        current_datetime = datetime.now()
        timestamp = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
        
        # 输出时间戳
        print(f"[{timestamp}]")
        
        # 获取并保存所有币种价格
        for coin, tokens in MARKET_TOKEN_IDS.items():
            price_str = get_price_sync(tokens["UP"])
            print(f"  {coin}: {price_str}")
            save_to_csv(coin, timestamp, price_str)
            
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
            update_btc5_token_id(MARKET_TOKEN_IDS)
            print("5分钟周期更新完成")
        
        print("更新完成")

# 主函数
def main():
    print("正在初始化 token_id...")
    # 初始化15分钟周期token_id
    update_all_token_ids(MARKET_TOKEN_IDS)
    # 初始化5分钟周期token_id
    update_btc5_token_id(MARKET_TOKEN_IDS)
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
    
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n程序已停止")

if __name__ == "__main__":
    main()