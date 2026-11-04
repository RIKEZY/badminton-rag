"""agent_tools._runtime 的模块选择逻辑（离线，不调 API）。

背景：Streamlit 把 app.py 当 __main__ 执行，agent_tools 不能再 import app
（会二次执行脚本、重复注册侧边栏控件）。_runtime 优先复用 sys.modules["__main__"]。
这里用假模块验证这条分支，不触发真正的 import app。
"""

import sys
import types


def test_runtime_reuses_registered_main_module(monkeypatch):
    from agent_tools import _runtime

    fake = types.ModuleType("__main__")
    fake.retrieve = lambda *args, **kwargs: None
    fake.chunks = []

    monkeypatch.setitem(sys.modules, "__main__", fake)

    assert _runtime() is fake
