"""
索引构建与向量检索

把切好的块编码成向量并缓存，提供按语义距离检索的能力。

为什么用 embedding 而不是关键词搜索：语料主要是英文 BWF 文档，用户问中文。
搜「领先两分」在文档里一个都找不到，原文写的是 "two-point lead"。
embedding 把中英文映射到同一语义空间，所以能对上。

两级缓存（都按 RAG_TAG 命名，例如 chunks_v2.json / vectors_v2.npy）：
    chunks   切块结果
    vectors  块向量
缓存按「语料文件是否比缓存新」判断失效——只判断文件存在，会导致
语料更新后仍用旧索引，静默答错。

前置条件：.env 里配好 SILICONFLOW_API_KEY（bge-m3 模型免费）。

运行：
    python index_builder.py
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from chunker import chunk_document
from document_loader import DATA_DIR, load_documents

load_dotenv()

HERE = Path(__file__).parent
# 缓存按语料标签分开，切换语料时不互相覆盖
# 默认跟生产版本走（v2 = 649 块）。app.py 也会 setdefault 成 v2，
# 这里保持一致——否则直接跑 tools/ 下的脚本会读到旧的 chunks_all.json。
TAG = os.getenv("RAG_TAG", "v2")
CHUNK_CACHE = HERE / f"chunks_{TAG}.json"
VEC_CACHE = HERE / f"vectors_{TAG}.npy"

EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3").strip()
BATCH_SIZE = 32          # 一次发多少条，太大会被拒
TOP_K = 5                # 每次返回几块


# ---------------------------------------------------------------- 准备数据

def _corpus_changed_since(cache: Path) -> bool:
    """语料里有没有文件比缓存新

    为什么需要：原来只判断「缓存文件存在」就直接读，不看语料。
    部署时只传语料、不传索引（或忘了重建），线上会拿旧索引回答新内容，
    而且完全没有报错——是最隐蔽的一类故障。
    """
    if not cache.exists() or not DATA_DIR.exists():
        return True
    try:
        cache_mtime = cache.stat().st_mtime
    except OSError:
        return True
    for p in DATA_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in (".pdf", ".txt", ".md"):
            try:
                if p.stat().st_mtime > cache_mtime:
                    return True
            except OSError:
                continue
    return False


def build_chunks() -> list[dict]:
    """结构感知切块（按条款编号），结果缓存到 chunks.json"""
    if CHUNK_CACHE.exists() and not _corpus_changed_since(CHUNK_CACHE):
        print(f"读取缓存 {CHUNK_CACHE.name}")
        return json.loads(CHUNK_CACHE.read_text(encoding="utf-8"))

    if CHUNK_CACHE.exists():
        print(f"语料比 {CHUNK_CACHE.name} 新，重新切块")

    print("按条款切块中...")
    docs = load_documents()

    # 按文件分组，chunk_document 需要「同一文件的按页文本」
    by_source: dict[str, list[tuple[int, str]]] = {}
    for doc in docs:
        by_source.setdefault(doc["source"], []).append((doc["page"], doc["text"]))

    chunks = []
    for source, pages in by_source.items():
        chunks.extend(chunk_document(pages, source))

    CHUNK_CACHE.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"切成 {len(chunks)} 块，已缓存到 {CHUNK_CACHE.name}")
    return chunks


def build_vectors(chunks: list[dict], client: OpenAI) -> np.ndarray:
    """给每块算向量，缓存到 vectors.npy。第二次跑就不用再花钱"""
    if VEC_CACHE.exists():
        vecs = np.load(VEC_CACHE)
        if len(vecs) == len(chunks):
            print(f"读取缓存 {VEC_CACHE.name}，形状 {vecs.shape}")
            return vecs
        print("缓存和块数对不上，重新计算")

    print(f"正在算向量：{len(chunks)} 块，每批 {BATCH_SIZE} 条")
    all_vecs = []
    start = time.time()

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = [c["text"] for c in chunks[i:i + BATCH_SIZE]]
        resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        all_vecs.extend([d.embedding for d in resp.data])

        done = min(i + BATCH_SIZE, len(chunks))
        pct = done / len(chunks) * 100
        print(f"  {done}/{len(chunks)}  ({pct:.0f}%)", end="\r")

    print(f"\n完成，耗时 {time.time() - start:.1f} 秒")

    vecs = np.array(all_vecs, dtype=np.float32)
    # 归一化：之后用点积就等于余弦相似度，省一次除法
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    np.save(VEC_CACHE, vecs)
    print(f"向量形状 {vecs.shape}，已缓存到 {VEC_CACHE.name}")
    return vecs


# ---------------------------------------------------------------- 检索

def embed_query(client: OpenAI, question: str) -> np.ndarray:
    resp = client.embeddings.create(model=EMBED_MODEL, input=[question])
    v = np.array(resp.data[0].embedding, dtype=np.float32)
    return v / np.linalg.norm(v)


def search(client: OpenAI, chunks: list[dict], vecs: np.ndarray,
           question: str, top_k: int = TOP_K) -> list[tuple[float, dict]]:
    """返回 [(相似度, 块), ...]，按相似度从高到低"""
    q = embed_query(client, question)
    scores = vecs @ q                      # 归一化后点积 = 余弦相似度
    top_idx = np.argsort(scores)[::-1][:top_k]
    return [(float(scores[i]), chunks[i]) for i in top_idx]


# ---------------------------------------------------------------- 主流程

def main() -> None:
    api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "缺少 SILICONFLOW_API_KEY\n"
            "1. 去 https://cloud.siliconflow.cn 注册\n"
            "2. 创建一个 API Key\n"
            "3. 填进 .env 的 SILICONFLOW_API_KEY= 后面"
        )

    client = OpenAI(api_key=api_key, base_url=EMBED_BASE_URL)

    chunks = build_chunks()
    vecs = build_vectors(chunks, client)

    print("\n" + "=" * 60)
    print("可以提问了。输入 q 退出。")
    print("试试：20 平之后要领先几分才算赢？")
    print("=" * 60)

    while True:
        try:
            question = input("\n问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() == "q":
            break

        results = search(client, chunks, vecs, question)
        for rank, (score, c) in enumerate(results, 1):
            preview = c["text"][:120].replace("\n", " ")
            print(f"\n[{rank}] 相似度 {score:.3f} | {c['source']} 第 {c['page']} 页")
            print(f"    {preview}...")


if __name__ == "__main__":
    main()
