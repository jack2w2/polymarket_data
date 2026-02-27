import os

# 从环境变量读取配置，如果没有则使用默认值
POLYMARKET_CONFIG = {
    "FUNDER_ADDRESS": "",
    "PRIVATE_KEY": "",
    "SIGNATURE_TYPE": 2
}
# Signature types:
# 0 = EOA (MetaMask, hardware wallet)
# 1 = Email/Magic wallet
# 2 = Browser wallet proxy



