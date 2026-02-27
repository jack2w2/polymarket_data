import os

# 从环境变量读取配置，如果没有则使用默认值
POLYMARKET_CONFIG = {
    "FUNDER_ADDRESS": "0x0bd6b78d5953d2e11d6f1d00fb8ca33a836047a0",
    "PRIVATE_KEY": "0x053f86336fb7558eb89dc01159dfccccde1d658f464acefb1ad0972b7fe5b7d1",
    "SIGNATURE_TYPE": 2
}
# Signature types:
# 0 = EOA (MetaMask, hardware wallet)
# 1 = Email/Magic wallet
# 2 = Browser wallet proxy


