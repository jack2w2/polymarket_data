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

当前配置文件是 `config.py`，核心参数：
- `FUNDER_ADDRESS`
- `PRIVATE_KEY`
- `SIGNATURE_TYPE`

运行前请确认以上值有效。

> 安全建议：不要在公开仓库中提交真实私钥，建议改成从环境变量读取。

---

## 4. 运行

```bash
python main.py
```

程序会：
- 初始化 15 分钟和 5 分钟市场的 token_id
- 每秒拉取价格
- 自动按日期写入 `data/YYYY-MM/YYYY-MM-DD/*.csv`

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
