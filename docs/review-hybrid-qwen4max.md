
─── hybrid.py:117-119 ───
[bug · high] The `__main__` block cannot run: every call here mismatches its function signature.
1. `BM25Okapi(chunks)` passes a list of dicts where a tokenized corpus (list of token lists) is
expected — it should use the provided `build_bm25(chunks)` helper.
2. `vector_search_idx(chunks)` is missing the required `client`, `vecs`, and `query` arguments
(signature: `vector_search_idx(client, chunks, vecs, query, k=5)`) → immediate `TypeError`.
3. `bm25_search_idx(chunks)` is missing `bm25` and `query` (signature: `bm25_search_idx(bm25,
chunks, query, k=5)`) → `TypeError`.

Either fix the demo to construct a client/embeddings and pass a real query (e.g. `bm25 =
build_bm25(chunks)`, then call both search functions with full arguments and fuse with
`rrf_fuse(vector_hits, bm25_hits)`), or remove this dead demo block.



─── hybrid.py:58-58 ───
[maintainability · low] The `chunks` parameter is declared but never read inside `bm25_search_idx` —
the function only uses `bm25`, `query`, and `k`. Dead parameters mislead callers into thinking chunk
data affects the result. Consider removing it (and updating call sites accordingly).

- def bm25_search_idx(bm25: BM25Okapi, chunks: list[dict], query: str, k: int = 5):
+ def bm25_search_idx(bm25: BM25Okapi, query: str, k: int = 5):



──────── Project Summary ────────

### Top Issues

1. **`hybrid.py` — `__main__` block is non-executable.** Every call in the demo/entrypoint path mismatches its function signature: `BM25Okapi(chunks)` passes a list of dicts where a tokenized corpus (list of token lists) is expected, and `vector_search_idx(chunks)` is likewise called incorrectly. Any attempt to run the module directly fails, so the entrypoint provides no working reference for callers and cannot serve as a smoke test.
2. **`hybrid.py` — dead `chunks` parameter in `bm25_search_idx`.** The parameter is declared but never read; the function operates only on `bm25`, `query`, and `k`. This advertises a dependency on chunk data that does not exist, misleading callers and making the signature unstable to reason about during refactors.

Both issues share a root cause: the public call signatures in `hybrid.py` have drifted from their implementations, and nothing exercises them.

### Module Hotspots

- `hybrid.py` — the sole file with findings, and both are API-contract defects concentrated in the BM25/vector search entrypoints (`bm25_search_idx`, `vector_search_idx`, `__main__`). With only two comments repo-wide, this file accounts for 100% of reported issues.

### Quick Wins

- Replace `BM25Okapi(chunks)` in the `hybrid.py` `__main__` block with the existing `build_bm25(chunks)` helper — the correct construction path already exists in the same file.
- Fix the remaining `__main__` call sites (e.g. `vector_search_idx(chunks)`) to match their declared signatures; this is a handful of lines and immediately makes the module runnable.
- Drop the unused `chunks` parameter from `bm25_search_idx` and update its call sites (including `__main__`) in the same change, so signature cleanup and entrypoint repair land together.
- Once `__main__` runs, keep it as a minimal executable check for `hybrid.py` so signature drift is caught at run time rather than by review.
