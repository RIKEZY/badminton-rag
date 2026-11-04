"""用 Streamlit 官方测试框架验证：Agent 模式不再触发重复元素错误

这个测试复现了服务器上的崩溃路径：
    app.py 作为 __main__ 运行 → agent_tools 里 import app → app.py 被二次执行
    → 侧边栏 st.slider 重复 → StreamlitDuplicateElementId
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"
at = AppTest.from_file(str(APP), default_timeout=180)
at.run()
print(f"首次渲染：{len(at.exception)} 个异常")

# 打开「启用 Agent 路由」开关
toggles = {t.label: t for t in at.toggle}
print(f"侧边栏开关：{list(toggles)}")
toggles["启用 Agent 路由"].set_value(True)

# 提交一个会触发工具调用的 Agent 问题
at.text_input[0].set_value("ASTROX 88S PRO 的 4U 建议磅数是多少？")
at.button[0].click()
at.run()

if at.exception:
    print("\n❌ 仍有异常：")
    for e in at.exception:
        print(f"  {e.type}: {e.message[:200]}")
else:
    print("\n✅ 无异常，Agent 模式正常")

print(f"\n渲染的 markdown 块数：{len(at.markdown)}")
print(f"caption 数：{len(at.caption)}")
for c in at.caption[:6]:
    print(f"  · {c.value[:80]}")
