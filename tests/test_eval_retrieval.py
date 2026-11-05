"""18 题检索评测（@pytest.mark.api：需要 LLM / embedding / rerank API）。

题目来源：
    - 老 10 题：run_eval.EVAL_SET（规则 / 技术 / 装备 / 跨文档）
    - 新 8 题：tools/eval_new.py 的 EVAL_V2（裁判 / 赛事 / 术语 / 跨文档）

判定沿用原脚本：top5 里存在一块，文件名一致 + 页码在容差内 + 文本含关键词。
老题允许页码 ±1（原 run_eval 的行为），新题要求页码精确（原 eval_new 的行为）。
"""

import pytest

pytestmark = pytest.mark.api


def _is_hit(hits, expected, page_tol: int) -> bool:
    for _, chunk in hits:
        text = chunk["text"].lower()
        for source, page, keyword in expected:
            if (chunk["source"] == source
                    and abs(chunk["page"] - page) <= page_tol
                    and keyword.lower() in text):
                return True
    return False


def _run_cases(cases) -> None:
    import app

    # 防呆：如果 conftest 的环境变量没生效，这里会加载成 82 块的旧语料
    assert len(app.chunks) >= 800, f"语料块数异常偏少：{len(app.chunks)}"

    misses = []
    for i, (question, expected, page_tol, tag) in enumerate(cases, 1):
        try:
            _, hits = app.retrieve(question, 5)
            # 改写由 LLM 生成，同一问题多次运行结果会摆动；未命中时重试一次，
            # 连续两次都 miss 才判失败（真实回归不会靠重试蒙混过关）。
            if not _is_hit(hits, expected, page_tol):
                _, hits = app.retrieve(question, 5)
        except Exception as exc:                       # noqa: BLE001 - 记录后统一断言
            misses.append(f"[{i}] {tag} {question} → 调用异常 {type(exc).__name__}: {exc}")
            continue

        if not _is_hit(hits, expected, page_tol):
            if hits:
                top = f"{hits[0][1]['source']} p{hits[0][1]['page']}"
            else:
                top = "空结果"
            misses.append(f"[{i}] {tag} {question} → top1={top}")

    assert not misses, (
        f"Recall@5 未达标：{len(cases) - len(misses)}/{len(cases)} 命中\n"
        + "\n".join(misses)
    )


def test_old_10_questions_recall_at_5():
    from run_eval import EVAL_SET

    cases = [(q, expected, 1, "老题") for q, expected in EVAL_SET]
    assert len(cases) == 10
    _run_cases(cases)


def test_new_8_questions_recall_at_5():
    from tools.eval_new import EVAL_V2

    cases = [(q, expected, 0, tag) for q, expected, tag in EVAL_V2]
    assert len(cases) == 8
    _run_cases(cases)
