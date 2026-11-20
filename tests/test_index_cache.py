"""向量缓存失效判断（P0-2）：命中要真命中，失效要真重建。

缓存只比块数时，「改了几个字但块数不变」和「换了 embedding 模型但维度相同」
都会继续用旧向量，召回静默答错。这里锁住四条路径：
内容不变命中、内容变化重建、模型变化重建、旧版无指纹文件重建。
"""

from types import SimpleNamespace

import numpy as np
import pytest

import index_builder as ib


class _FakeEmbeddings:
    def __init__(self):
        self.calls: list[list[str]] = []

    def create(self, model: str, input: list[str]):
        self.calls.append(list(input))
        data = [
            SimpleNamespace(embedding=[float(len(t) + 1), float(sum(map(ord, t)) % 13 + 1), 2.0, 1.0])
            for t in input
        ]
        return SimpleNamespace(data=data)


class _FakeClient:
    def __init__(self):
        self.embeddings = _FakeEmbeddings()


def _no_call_client() -> _FakeClient:
    """命中缓存时不该调用 API；一旦调用就让测试失败。"""
    client = _FakeClient()

    def boom(model, input):  # pragma: no cover - 命中时不会执行
        raise AssertionError("命中缓存却仍然调用了 embedding API")

    client.embeddings.create = boom
    return client


@pytest.fixture
def cache_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ib, "VEC_CACHE", tmp_path / "vectors_test.npy")
    monkeypatch.setattr(ib, "VEC_META", tmp_path / "vectors_test.meta.json")
    monkeypatch.setattr(ib, "EMBED_MODEL", "test/bge-m3")
    return ib.VEC_CACHE, ib.VEC_META


def _chunks(*texts: str) -> list[dict]:
    return [{"text": t} for t in texts]


def test_cache_hits_when_chunks_unchanged(cache_paths):
    chunks = _chunks("发球高度不得低于 1.15 米", "球拍框架宽度不超过 23 厘米")

    first = ib.build_vectors(chunks, _FakeClient())
    second = ib.build_vectors(chunks, _no_call_client())

    assert np.array_equal(first, second)


def test_cache_rebuilds_when_content_changes_with_same_count(cache_paths):
    before = _chunks("发球高度不得低于 1.15 米", "球拍框架宽度不超过 23 厘米")
    after = _chunks("发球高度不得低于 1.15 米", "球拍框架宽度不得超过 23 厘米")

    ib.build_vectors(before, _FakeClient())
    client = _FakeClient()
    vecs = ib.build_vectors(after, client)

    assert len(client.embeddings.calls) == 1, "块内容变了必须重算"
    assert vecs.shape == (2, 4)
    assert ib.VEC_META.exists()


def test_cache_rebuilds_when_embedding_model_changes(cache_paths, monkeypatch):
    chunks = _chunks("网柱高度 1.55 米")

    ib.build_vectors(chunks, _FakeClient())
    monkeypatch.setattr(ib, "EMBED_MODEL", "test/another-model")
    client = _FakeClient()
    ib.build_vectors(chunks, client)

    assert len(client.embeddings.calls) == 1, "换模型必须重算"


def test_legacy_cache_without_meta_is_rebuilt(cache_paths):
    vec_cache, _ = cache_paths
    chunks = _chunks("重发球", "换边")
    # 旧版本只写了 .npy，没有指纹文件；形状完全对得上也不能信
    np.save(vec_cache, np.ones((2, 4), dtype=np.float32))

    client = _FakeClient()
    vecs = ib.build_vectors(chunks, client)

    assert len(client.embeddings.calls) == 1, "无指纹的旧缓存必须重建"
    assert not np.allclose(vecs, 1.0)


def test_corrupt_meta_is_rebuilt(cache_paths):
    vec_cache, vec_meta = cache_paths
    chunks = _chunks("界内", "界外")
    np.save(vec_cache, np.ones((2, 4), dtype=np.float32))
    vec_meta.write_text("{ 不是合法 JSON", encoding="utf-8")

    client = _FakeClient()
    ib.build_vectors(chunks, client)

    assert len(client.embeddings.calls) == 1