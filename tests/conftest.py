"""pytest 公共配置与共享 fixture。

关键陷阱：index_builder 在**模块导入时**就读取 RAG_TAG / RAG_DATA_DIR 决定用哪份缓存
（chunks_<tag>.json / vectors_<tag>.npy）。如果先 import 了别的业务模块，
或者外部 shell 里残留了 RAG_TAG=rules，就会加载到 82 块的旧语料。

conftest 的模块级代码在所有测试模块之前执行，所以在这里强制固定：
    RAG_TAG=v2          → chunks_v2.json（649 块）
    RAG_DATA_DIR=data_rules_only
"""

import json
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# api 测试需要 .env 里的 Key；离线测试不依赖它
load_dotenv(ROOT / ".env")

# 强制覆盖，不依赖外部 shell 是否设置过
os.environ["RAG_TAG"] = "v2"
os.environ["RAG_DATA_DIR"] = str(ROOT / "data_rules_only")

CHUNKS_V2 = ROOT / "chunks_v2.json"
VECTORS_V2 = ROOT / "vectors_v2.npy"
EQUIPMENT_DB = ROOT / "tools" / "equipment.db"
DATA_DIR = ROOT / "data_rules_only"

EXPECTED_CHUNK_COUNT = 649


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def cached_chunks() -> list[dict]:
    """v2 语料缓存（649 块），不存在时跳过而不是失败。"""
    if not CHUNKS_V2.exists():
        pytest.skip(f"缺少语料缓存 {CHUNKS_V2.name}，先跑一次 index_builder.py 生成")
    return json.loads(CHUNKS_V2.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bm25_index(cached_chunks):
    """BM25 索引建一次，整个 session 复用。"""
    from hybrid import build_bm25

    return build_bm25(cached_chunks)


@pytest.fixture(scope="session")
def equipment_db() -> Path:
    """装备库不存在时跳过（DB 是构建产物，不进版本库）。"""
    if not EQUIPMENT_DB.exists():
        pytest.skip(f"缺少装备库 {EQUIPMENT_DB}，先跑 tools/build_equipment_db.py")
    return EQUIPMENT_DB
