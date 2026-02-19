import time
import math
import requests
import json
from typing import Dict, Optional
import pytz
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 全局变量（保持不变，供外部引用）---
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


# --- 内部优化：连接池与缓存 ---
# 建立一个全局 Session，复用 TCP 连接，显著提升速度
def _create_session():
    s = requests.Session()
    # 配置重试策略：遇到 5xx 错误或 429 限流自动重试
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


_GLOBAL_SESSION = _create_session()
_INTERNAL_CACHE = {}  # 简单的内存缓存


# --- 核心函数 ---

def get_5m_cycle_start_ts(offset_minutes: int = 0) -> int:
    """
    计算当前（或偏移后）最近的 5 分钟周期开始时间的 Unix timestamp（秒级）
    """
    utc_now = datetime.now(pytz.utc)
    # 转换为美东时间
    et_tz = pytz.timezone("America/New_York")
    et_now = utc_now.astimezone(et_tz)

    # 获取当天午夜
    et_midnight = et_now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 计算当前是第几个 5 分钟
    minutes_since_midnight = (et_now - et_midnight).total_seconds() / 60
    cycle_index = math.floor(minutes_since_midnight / 5)

    # 计算目标时间
    cycle_start_minutes = cycle_index * 5
    cycle_start_et = et_midnight + timedelta(minutes=cycle_start_minutes)
    adjusted = cycle_start_et + timedelta(minutes=offset_minutes)

    return int(adjusted.astimezone(pytz.utc).timestamp())


def get_15m_cycle_start_ts(offset_minutes: int = 0) -> int:
    """
    计算当前（或偏移后）最近的 15 分钟周期开始时间的 Unix timestamp（秒级）
    保持原有逻辑的准确性，但优化了计算过程
    """
    utc_now = datetime.now(pytz.utc)
    # 转换为美东时间
    et_tz = pytz.timezone("America/New_York")
    et_now = utc_now.astimezone(et_tz)

    # 获取当天午夜
    et_midnight = et_now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 计算当前是第几个 15 分钟
    minutes_since_midnight = (et_now - et_midnight).total_seconds() / 60
    cycle_index = math.floor(minutes_since_midnight / 15)

    # 计算目标时间
    cycle_start_minutes = cycle_index * 15
    cycle_start_et = et_midnight + timedelta(minutes=cycle_start_minutes)
    adjusted = cycle_start_et + timedelta(minutes=offset_minutes)

    return int(adjusted.astimezone(pytz.utc).timestamp())


def cached_fetch_5m_market_token_id(coin: str, cache_key: int) -> Optional[Dict[str, str]]:
    full_key = f"{coin}5_{cache_key}"
    return _INTERNAL_CACHE.get(full_key)


# 为了兼容原代码的引用，保留此函数名，但内部逻辑不再使用 lru_cache 装饰器导致的复杂依赖
# 如果外部代码显式调用了这个函数，它依然能工作
def cached_fetch_15m_market_token_ids(coin: str, cache_key: int) -> Optional[Dict[str, str]]:
    full_key = f"{coin}_{cache_key}"
    return _INTERNAL_CACHE.get(full_key)


def fetch_5m_market_token_id(
        coin: str = "BTC", max_retries: int = 3, base_delay: float = 2.0
) -> Optional[Dict[str, str]]:
    """
    获取指定币种 5分钟 Up 市场 token_id
    """
    coin = coin.upper()
    coin_lower = coin.lower()

    # 1. 检查缓存 (基于当前周期时间戳)
    current_cycle_ts = get_5m_cycle_start_ts(0)
    cache_key = f"{coin}5_{current_cycle_ts}"

    if cache_key in _INTERNAL_CACHE:
        # print(f"[BTC5] 使用内部缓存") # 调试用，可注释
        return _INTERNAL_CACHE[cache_key]

    # 2. 定义尝试的偏移：当前 -> 下一个 -> 上一个
    offsets = [0, 5, -5]

    for offset_min in offsets:
        ts = get_5m_cycle_start_ts(offset_min)
        slug = f"{coin_lower}-updown-5m-{ts}"
        url = "https://gamma-api.polymarket.com/markets"
        params = {"slug": slug}

        try:
            # 使用全局 Session 发起请求，速度更快
            # timeout 设置短一点，依靠 Session 的自动重试
            resp = _GLOBAL_SESSION.get(url, params=params, timeout=6)

            if resp.status_code == 200:
                data = resp.json()
                # 兼容返回列表或字典
                market = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None

                if not market or "clobTokenIds" not in market:
                    continue

                # 检查市场是否已关闭 (比字符串匹配更稳健)
                if market.get("closed") is True:
                    continue

                clob_raw = market["clobTokenIds"]
                clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw

                if len(clob_ids) < 1:
                    continue

                outcomes_raw = market.get("outcomes", '["Up"]')
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

                up_token = clob_ids[0]
                question = market.get("question", "")

                result = {
                    "UP": up_token,
                    "slug": slug,
                    "question": question,
                }

                print(f"[{coin}5] 获取成功（偏移 {offset_min}min）：{question[:40]}...")

                # 更新缓存：只缓存当前或未来周期的结果，过期数据不缓存
                if offset_min >= 0:
                    _INTERNAL_CACHE[cache_key] = result

                return result

        except Exception as e:
            # 这里的异常主要由 Session 重试后依然失败抛出
            # 为了不刷屏，仅在最后一次尝试失败时打印详细信息
            continue

    print(f"[{coin}5] 所有尝试失败")
    return None


def fetch_15m_market_token_ids(
        coin: str, max_retries: int = 3, base_delay: float = 2.0
) -> Optional[Dict[str, str]]:
    """
    获取指定币种的 15 分钟 Up/Down 市场 token_ids
    参数 max_retries 和 base_delay 被保留以维持接口兼容性，
    但实际上我们会使用更高效的 Session 重试机制。
    """
    coin_lower = coin.lower()

    # 1. 检查缓存 (基于当前周期时间戳)
    current_cycle_ts = get_15m_cycle_start_ts(0)
    cache_key = f"{coin}_{current_cycle_ts}"

    if cache_key in _INTERNAL_CACHE:
        # print(f"[{coin}] 使用内部缓存") # 调试用，可注释
        return _INTERNAL_CACHE[cache_key]

    # 2. 定义尝试的偏移：当前 -> 下一个 -> 上一个
    offsets = [0, 15, -15]

    for offset_min in offsets:
        ts = get_15m_cycle_start_ts(offset_min)
        slug = f"{coin_lower}-updown-15m-{ts}"
        url = "https://gamma-api.polymarket.com/markets"
        params = {"slug": slug}

        try:
            # 使用全局 Session 发起请求，速度更快
            # timeout 设置短一点，依靠 Session 的自动重试
            resp = _GLOBAL_SESSION.get(url, params=params, timeout=6)

            if resp.status_code == 200:
                data = resp.json()
                # 兼容返回列表或字典
                market = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None

                if not market or "clobTokenIds" not in market:
                    continue

                # 检查市场是否已关闭 (比字符串匹配更稳健)
                if market.get("closed") is True:
                    continue

                clob_raw = market["clobTokenIds"]
                clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw

                if len(clob_ids) < 2:
                    continue

                outcomes_raw = market.get("outcomes", '["Up", "Down"]')
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

                # 确保 Up/Down 对应正确
                # Polymarket 这里的顺序通常固定，但为了安全起见做个映射
                # 如果找不到明确的 "Up"/"Down" 标签，回退到默认顺序
                up_token = clob_ids[0]
                down_token = clob_ids[1]

                # 尝试更智能的匹配
                if len(outcomes) == 2:
                    if "down" in str(outcomes[0]).lower():
                        up_token, down_token = down_token, up_token

                question = market.get("question", "")

                result = {
                    "UP": up_token,
                    "DOWN": down_token,
                    "slug": slug,
                    "question": question,
                }

                print(f"[{coin}] 获取成功（偏移 {offset_min}min）：{question[:40]}...")

                # 更新缓存：只缓存当前或未来周期的结果，过期数据不缓存
                if offset_min >= 0:
                    _INTERNAL_CACHE[cache_key] = result

                return result

        except Exception as e:
            # 这里的异常主要由 Session 重试后依然失败抛出
            # 为了不刷屏，仅在最后一次尝试失败时打印详细信息
            continue

    print(f"[{coin}] 所有尝试失败")
    return None


def update_btc5_token_id(market_token_ids: Dict[str, Dict[str, str]]) -> bool:
    """
    兼容旧调用：更新 BTC5 token_id
    """
    return update_single_5m_token_id(market_token_ids, "BTC5")


def update_single_5m_token_id(market_token_ids: Dict[str, Dict[str, str]], coin_key: str) -> bool:
    """
    更新单个 5分钟 token_id（如 BTC5 / ETH5 / SOL5 / XRP5）
    """
    try:
        if not coin_key.endswith("5"):
            return False

        base_coin = coin_key[:-1]
        info = fetch_5m_market_token_id(base_coin)
        if info and "UP" in info:
            market_token_ids[coin_key]["UP"] = info["UP"]
            return True
        else:
            return False
    except Exception as e:
        return False


def update_all_5m_token_ids(market_token_ids: Dict[str, Dict[str, str]]) -> int:
    """
    并行更新所有 5分钟键（*5）token_id，返回成功数量
    """
    updated_count = 0
    five_min_keys = [k for k in market_token_ids.keys() if k.endswith("5")]

    if not five_min_keys:
        return 0

    with ThreadPoolExecutor(max_workers=len(five_min_keys)) as executor:
        future_to_coin_key = {
            executor.submit(update_single_5m_token_id, market_token_ids, coin_key): coin_key
            for coin_key in five_min_keys
        }

        for future in as_completed(future_to_coin_key):
            coin_key = future_to_coin_key[future]
            try:
                ok = future.result()
                if ok:
                    updated_count += 1
                else:
                    print(f"[{coin_key}] 更新失败，保持旧值")
            except Exception as e:
                print(f"[{coin_key}] 更新线程异常: {str(e)[:80]}")

    print(f"5分钟 token 更新完成：成功 {updated_count}/{len(five_min_keys)} 个")
    return updated_count


def update_all_token_ids(market_token_ids: Dict[str, Dict[str, str]]) -> int:
    """
    并行更新 4 个币种的 Up/Down token_ids，返回成功数量
    保持原有函数签名完全一致
    """
    updated_count = 0
    coins = [k for k in market_token_ids.keys() if not k.endswith("5")]  # 仅15分钟键

    if not coins:
        return 0

    # 使用线程池并发
    with ThreadPoolExecutor(max_workers=len(coins)) as executor:
        # 这里提交任务时，不再显式传递 max_retries，使用默认值即可兼容
        future_to_coin = {
            executor.submit(fetch_15m_market_token_ids, coin): coin for coin in coins
        }

        for future in as_completed(future_to_coin):
            coin = future_to_coin[future]
            try:
                info = future.result()
                if info and "UP" in info and "DOWN" in info:
                    market_token_ids[coin]["UP"] = info["UP"]
                    market_token_ids[coin]["DOWN"] = info["DOWN"]
                    # print(f"[{coin}] 更新内存成功")
                    updated_count += 1
                else:
                    print(f"[{coin}] 更新失败，保持旧值")
            except Exception as e:
                print(f"[{coin}] 更新线程异常: {str(e)[:80]}")

    print(f"15分钟 token 更新完成：成功 {updated_count}/{len(coins)} 个")
    return updated_count


# 主入口（保持不变，方便测试）
if __name__ == "__main__":
    print(f"开始更新所有 Up/Down token IDs ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})...")
    success_count_15m = update_all_token_ids(MARKET_TOKEN_IDS)
    success_count_5m = update_all_5m_token_ids(MARKET_TOKEN_IDS)
    print(f"更新结束，15分钟成功 {success_count_15m} 个币种，5分钟成功 {success_count_5m} 个币种")

    # 打印最终结果
    print("\n最终 MARKET_TOKEN_IDS:")
    for coin, tokens in MARKET_TOKEN_IDS.items():
        up_val = tokens.get("UP", "none")
        down_val = tokens.get("DOWN")
        up_show = f"{up_val[:12]}..." if isinstance(up_val, str) and len(up_val) > 12 else str(up_val)
        if down_val is not None:
            down_show = f"{down_val[:12]}..." if isinstance(down_val, str) and len(down_val) > 12 else str(down_val)
            print(f"[{coin}] UP: {up_show} | DOWN: {down_show}")
        else:
            print(f"[{coin}] UP: {up_show}")
    
