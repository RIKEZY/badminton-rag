"""
Day 3 · 向量化与检索

Day 2 把 14 万字切成了 376 块。这一版给每块算一个"向量"（一串数字），
然后用"语义距离"找相关块——中文问题也能匹配英文文档。

为什么必须用 embedding 而不是关键词搜索：
你的文档是英文，你问的是中文。搜「领先两分」在文档里一个都找不到，
文档写的是 "two-point lead"。embedding 把中英文映射到同一个语义空间，
所以能对上。

准备工作（只需一次）：
1. 去 https://cloud.siliconflow.cn 注册，手机号就行
2. 控制台里创建一个 API Key（新用户有免费额度，bge-m3 这个模型本身免费）
3. 把 key 填进 .env 的 SILICONFLOW_API_KEY=

运行：
    python day3.py
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
from day2 import DATA_DIR, load_documents

load_dotenv()

HERE = Path(__file__).parent
# 缓存按语料标签分开，切换语料时不互相覆盖
TAG = os.getenv("RAG_TAG", "all")
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
