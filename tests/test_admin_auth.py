"""管理后台鉴权测试（离线，不调 API；只读 query_log.db）。

用 Streamlit 官方 AppTest 真实执行 pages/1_admin.py，断言：
    - 未登录：只显示密码框，不泄露任何统计
    - 密码错误：仍被拦住，提示「密码错误」
    - 密码正确：显示概览指标
    - 未配置 ADMIN_PASSWORD：直接拒绝访问
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "pages" / "1_admin.py"
PASSWORD = "pytest-admin-pwd"

pytestmark = pytest.mark.skipif(not ADMIN.exists(), reason="管理后台页面不存在")


def _run_admin(monkeypatch, password: str = PASSWORD) -> AppTest:
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    at = AppTest.from_file(str(ADMIN), default_timeout=60)
    at.run()
    return at


def test_unauthenticated_shows_only_login(monkeypatch):
    at = _run_admin(monkeypatch)

    assert len(at.exception) == 0
    assert any("管理后台" in t.value for t in at.title)
    assert len(at.text_input) == 1
    assert at.text_input[0].label == "管理员密码"
    # proto.type == 1 表示 password 输入框（掩码显示）
    assert at.text_input[0].proto.type == 1
    # 未登录时不能渲染任何统计指标
    assert len(at.metric) == 0


def test_wrong_password_is_rejected(monkeypatch):
    at = _run_admin(monkeypatch)

    at.text_input[0].set_value("wrong-password")
    at.button[0].click()
    at.run()

    assert len(at.exception) == 0
    assert len(at.text_input) == 1                 # 还在登录页
    assert len(at.metric) == 0
    assert any("密码错误" in e.value for e in at.error)


def test_correct_password_shows_dashboard(monkeypatch):
    at = _run_admin(monkeypatch)

    at.text_input[0].set_value(PASSWORD)
    at.button[0].click()
    at.run()

    assert len(at.exception) == 0
    assert len(at.text_input) == 0                 # 登录后不再显示密码框
    labels = {m.label for m in at.metric}
    assert {"总提问", "今日", "会话数", "未命中率", "平均耗时"} <= labels


def test_missing_admin_password_blocks_access(monkeypatch):
    """未配置 ADMIN_PASSWORD 时，页面必须直接报错并停止。"""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    # 阻断 .env 把密码又加载回来
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(str(ADMIN), default_timeout=60)
    at.run()

    assert len(at.exception) == 0
    assert len(at.metric) == 0
    assert any("未配置" in e.value and "ADMIN_PASSWORD" in e.value for e in at.error)
