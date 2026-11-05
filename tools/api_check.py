"""
诊断脚本：绕过 openai 库，直接用标准库发请求。

目的：区分是「openai SDK 版本问题」还是「API/模型本身不兼容」。
不用装任何新包，Python 自带 urllib 就够。

运行：
    python test_api.py
"""

import sys
from pathlib import Path

# 本脚本在 tools/ 下，业务模块在项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip().rstrip("/")
api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
model = os.getenv("DEEPSEEK_MODEL", "").strip()

print(f"base_url : {base_url}")
print(f"model    : {model}")
print(f"key      : {api_key[:8]}...{api_key[-4:]}  (长度 {len(api_key)})")
print()

url = f"{base_url}/chat/completions"
body = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": "你好，回复两个字"}],
    "temperature": 0,
}).encode("utf-8")

req = urllib.request.Request(
    url,
    data=body,
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    method="POST",
)

print(f"请求地址：{url}\n")

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8")
        print(f"✅ 成功，HTTP {resp.status}")
        print(data[:600])
except urllib.error.HTTPError as e:
    print(f"❌ HTTP {e.code}")
    print(e.read().decode("utf-8", errors="ignore")[:600])
except Exception as e:
    print(f"❌ {type(e).__name__}: {e}")
