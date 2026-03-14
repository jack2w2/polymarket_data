# polymarket_data

用于抓取 Polymarket 的 15 分钟与 5 分钟市场（BTC/ETH/SOL/XRP）价格，并按日期写入 CSV。

## 1. Ubuntu 依赖环境

### 系统环境
- Ubuntu 20.04 / 22.04 / 24.04（推荐）
- Python 3.10+（推荐 3.11）
- `pip`、`venv`

### Python 依赖
项目代码里实际使用到的第三方包：
- `py-clob-client`
- `requests`
- `pytz`

> 说明：`urllib3` 由 `requests` 依赖引入，一般无需单独安装。

---

## 2. Ubuntu 安装步骤

在项目目录执行：

```bash
# 1) 更新包索引
sudo apt update

# 2) 安装 Python 基础组件
sudo apt install -y python3 python3-venv python3-pip

# 3) （可选）某些环境编译依赖可能需要
sudo apt install -y build-essential python3-dev libffi-dev libssl-dev

# 4) 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 5) 升级 pip
python -m pip install --upgrade pip

# 6) 安装项目依赖
pip install -r requirements.txt
```

---

## 3. 配置

当前配置使用 `.env` 文件（已由 `python-dotenv` 自动加载）。

1) 复制示例文件：

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

2) 编辑 `.env` 并填写：
- `POLYMARKET_FUNDER_ADDRESS`
- `POLYMARKET_PRIVATE_KEY`
- `POLYMARKET_SIGNATURE_TYPE`
- `POLYMARKET_DATA_TIMEZONE`（默认 `Asia/Shanghai`）
- `ENABLE_POLYMARKET`（默认 `1`，设为 `0` 可关闭 Polymarket 采集）
- `ENABLE_BINANCE`（默认 `1`，设为 `0` 可关闭币安采集）

仅收集币安秒级价格时，建议在 `.env` 设置：

```env
ENABLE_POLYMARKET=0
ENABLE_BINANCE=1
```

这样无需填写 Polymarket 密钥配置也可运行。

> `.env` 已在 `.gitignore` 中，默认不会上传到 GitHub。

---

## 4. 运行

```bash
python main.py
```

程序会：
- 初始化 15 分钟和 5 分钟市场的 token_id
- 每秒拉取价格
- 自动按日期写入 `data/YYYY-MM/YYYY-MM-DD/*.csv`
- 同时每秒拉取币安现货 `BTC/ETH/SOL/XRP` 并写入：
  - `data/YYYY-MM/YYYY-MM-DD/BTC_BINANCE_YYYY-MM-DD.csv`
  - `data/YYYY-MM/YYYY-MM-DD/ETH_BINANCE_YYYY-MM-DD.csv`
  - `data/YYYY-MM/YYYY-MM-DD/SOL_BINANCE_YYYY-MM-DD.csv`
  - `data/YYYY-MM/YYYY-MM-DD/XRP_BINANCE_YYYY-MM-DD.csv`

币安 CSV 固定为两列：`time,price`。

停止程序：
- 按 `Ctrl + C`

---

## 5. 常见问题

### 1) `ModuleNotFoundError: No module named py_clob_client`
虚拟环境里重新安装：

```bash
pip install py-clob-client
```

### 2) 时区相关报错
确保已安装 `pytz`：

```bash
pip install pytz
```

### 3) 网络请求失败或超时
- 检查网络是否可访问：
  - `https://gamma-api.polymarket.com`
  - `https://clob.polymarket.com`
- 稍后重试，程序内置了部分重试逻辑。
