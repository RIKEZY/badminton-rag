"""装备 SQL 查询测试（离线，不调 API；只读 tools/equipment.db）。

覆盖：
    - 型号归一化（去空格 / 大写 / 去分隔符）
    - 精确型号查询忽略空格与大小写（100ZZ → ASTROX 100 ZZ）
    - 磅数解析（tension_json）
    - 属性筛选（硬度 / 品牌 / 磅数下限）

DB 是构建产物：不存在时整个模块 skip，而不是 fail。
"""

import sqlite3

import pytest

from tools.equipment_query import filter_by, normalize, search_model, tension_of

pytestmark = pytest.mark.usefixtures("equipment_db")


# ---------------------------------------------------------------- 归一化

@pytest.mark.parametrize("raw,expected", [
    ("100ZZ", "100ZZ"),
    ("100 zz", "100ZZ"),
    ("ASTROX 100 ZZ", "ASTROX100ZZ"),
    ("ast 100zz", "AST100ZZ"),
    ("88s-pro", "88SPRO"),
    ("88s_pro", "88SPRO"),
    ("", ""),
    (None, ""),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


# ---------------------------------------------------------------- 型号查询

def test_db_has_34_rackets(equipment_db):
    conn = sqlite3.connect(equipment_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM rackets").fetchone()[0]
    finally:
        conn.close()
    assert count == 34


def test_search_model_hits_100zz_without_space():
    rows = search_model("100ZZ")

    assert [r["model"] for r in rows] == ["ASTROX 100 ZZ"]
    assert "天斧" in rows[0]["full_title"]


def test_search_model_is_space_and_case_insensitive():
    assert [r["model"] for r in search_model("100 zz")] == ["ASTROX 100 ZZ"]
    assert [r["model"] for r in search_model("astrox 100 zz")] == ["ASTROX 100 ZZ"]


def test_search_model_hyphen_insensitive():
    rows = search_model("88s-pro")
    assert [r["model"] for r in rows] == ["ASTROX 88S PRO"]


def test_search_model_returns_all_series_variants():
    models = [r["model"] for r in search_model("88S")]

    assert len(models) == 3
    assert set(models) == {"ASTROX 88S PRO", "ASTROX 88S TOUR", "ASTROX 88S GAME"}


def test_search_model_unknown_returns_empty():
    assert search_model("雷霆99XYZ") == []


# ---------------------------------------------------------------- 磅数

def test_tension_of_returns_parsed_range():
    result = tension_of("88S PRO", "4U")

    assert result is not None
    assert len(result) == 1
    assert result[0]["model"] == "ASTROX 88S PRO"
    assert result[0]["weight"] == "4U"
    assert result[0]["range"] == [20, 28]
    assert "20-28" in result[0]["raw"]


def test_tension_of_without_weight_returns_all_specs():
    result = tension_of("88S PRO")

    assert result is not None
    assert result[0]["all"] == {"4U": [20, 28], "3U": [21, 29]}


def test_tension_of_missing_weight_is_none_but_model_still_found():
    # ASTROX 88S GAME 只有 4U
    result = tension_of("88S GAME", "3U")

    assert result is not None
    assert result[0]["range"] is None


def test_tension_of_unknown_model_returns_none():
    assert tension_of("不存在的拍子") is None


# ---------------------------------------------------------------- 属性筛选

def test_filter_by_stiffness():
    rows = filter_by(stiffness="硬")

    assert len(rows) == 13
    assert all("硬" in (r["stiffness"] or "") for r in rows)
    assert "ASTROX 88S PRO" in [r["model"] for r in rows]


def test_filter_by_brand():
    rows = filter_by(brand="李宁")

    assert len(rows) == 3
    assert all("李宁" in (r["brand"] or "") for r in rows)


def test_filter_by_min_tension():
    rows = filter_by(min_tension=28)

    assert len(rows) == 27
    assert "ASTROX 88S PRO" in [r["model"] for r in rows]


def test_filter_without_conditions_returns_all():
    assert len(filter_by()) == 34
