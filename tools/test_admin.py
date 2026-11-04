"""验证管理后台：未登录被拦、登录后能看到访问流"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from streamlit.testing.v1 import AppTest

ADMIN = ROOT / "pages" / "1_admin.py"
PWD = os.getenv("ADMIN_PASSWORD", "")

at = AppTest.from_file(str(ADMIN), default_timeout=60)
at.run()

print(f"未登录时异常：{len(at.exception)}")
print(f"是否显示密码框：{len(at.text_input) > 0}")
print(f"标题：{[t.value for t in at.title]}")

# 输错密码
if at.text_input:
    at.text_input[0].set_value("wrong-password")
    at.button[0].click()
    at.run()
    print(f"输错密码后仍被拦：{len(at.text_input) > 0}")

# 输对密码
if at.text_input:
    at.text_input[0].set_value(PWD)
    at.button[0].click()
    at.run()

print(f"\n登录后异常：{len(at.exception)}")
if at.exception:
    for e in at.exception:
        print(f"  {e.type}: {e.message[:200]}")

print(f"登录后标题：{[t.value for t in at.title]}")
print(f"指标卡：{[(m.label, m.value) for m in at.metric]}")
print(f"子标题：{[h.value for h in at.subheader]}")
