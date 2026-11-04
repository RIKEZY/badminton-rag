"""Agent 模式测试（@pytest.mark.api：会真实调用 LLM / embedding / 重排）。

两个层次：
    1. AppTest 渲染：复现服务器崩溃路径（app.py 作为 __main__ → agent_tools
       里 import app → 二次执行 → 侧边栏 slider 重复）。
    2. 子进程跑 agent_core.run：不经过 Streamlit，验证「决策 → 工具调用 → 生成」
       整条链路能给出带参数的回答。

为什么都放子进程：
    bare 模式下 import app 会在 Streamlit 的 context_dg_stack 里留下一个未退出的
    form 上下文，污染同进程后续的 AppTest；子进程隔离后测试之间没有顺序依赖。

已知问题（2026-11 现状）：
    项目有 pages/ 目录时，Streamlit 走 _mpa_v1 分支，page.run() 创建的 __main__
    模块**没有注册进 sys.modules**，agent_tools._runtime 找不到正在运行的 app，
    回退到 `import app`，导致 slider 重复注册。原 tools/test_app_agent.py 同样
    会失败，与 pytest 无关。修复前该用例标记为 xfail，修复后会自动变成普通通过。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"

pytestmark = pytest.mark.api

_APPTEST_SCRIPT = """
import json
from streamlit.testing.v1 import AppTest

at = AppTest.from_file({app!r}, default_timeout=180)
at.run()

first = [f"{{e.type}}: {{e.message}}" for e in at.exception]
toggles = {{t.label: t for t in at.toggle}}

if not first and "启用 Agent 路由" in toggles and len(at.text_input) > 0:
    toggles["启用 Agent 路由"].set_value(True)
    at.text_input[0].set_value("ASTROX 88S PRO 的 4U 建议磅数是多少？")
    at.button[0].click()
    at.run()

print("APPTEST_RESULT=" + json.dumps({{
    "first_exceptions": first,
    "exceptions": [f"{{e.type}}: {{e.message}}" for e in at.exception],
    "metric_labels": [m.label for m in at.metric],
    "markdown_count": len(at.markdown),
    "text_inputs": len(at.text_input),
}}, ensure_ascii=True))
""".format(app=str(APP))

_AGENT_SCRIPT = """
import json
import sys

sys.path.insert(0, {root!r})

import app  # noqa: F401  先按普通模块加载，agent_tools._runtime 会复用它
from agent_core import run

steps, answer = run("ASTROX 88S PRO 的 4U 建议磅数是多少？", max_steps=2)
print("AGENT_RESULT=" + json.dumps({{
    "actions": [s["action"] for s in steps],
    "summaries": [s["summary"] for s in steps],
    "answer": answer,
}}, ensure_ascii=True))
""".format(root=str(ROOT))


def _run_child(script: str, marker: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"子进程退出码 {proc.returncode}\n"
        f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(marker)]
    assert lines, (
        f"子进程没有输出 {marker}\n"
        f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    return json.loads(lines[-1].split("=", 1)[1])


@pytest.mark.skipif(not APP.exists(), reason="app.py 不存在")
def test_agent_mode_renders_without_duplicate_element_error():
    payload = _run_child(_APPTEST_SCRIPT, "APPTEST_RESULT=")

    assert payload["first_exceptions"] == [], payload["first_exceptions"]

    if payload["exceptions"]:
        if any("multiple `slider` elements" in m for m in payload["exceptions"]):
            pytest.xfail(
                "已知问题：pages/ 存在时 Streamlit _mpa_v1 不注册 __main__，"
                "agent_tools._runtime 回退 import app，slider 重复注册；"
                "原 tools/test_app_agent.py 同样失败"
            )
        pytest.fail("Agent 模式渲染异常：\n" + "\n".join(payload["exceptions"]))

    assert "工具调用" in payload["metric_labels"]
    assert "耗时" in payload["metric_labels"]
    assert payload["markdown_count"] > 0


def test_agent_pipeline_answers_equipment_question():
    payload = _run_child(_AGENT_SCRIPT, "AGENT_RESULT=")

    assert "query_racket" in payload["actions"], payload
    assert any("20-28" in s for s in payload["summaries"]), payload
    assert payload["answer"].strip(), "Agent 没有生成回答"
    # 参数必须原样引用，不能被模型改写
    assert re.search(r"20\s*[-–~]\s*28", payload["answer"]), payload["answer"]
