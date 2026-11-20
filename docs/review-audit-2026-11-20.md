# 2026-11-19 审查结论完成度盘点（2026-11-20）

> 依据：`docs/review-2026-11-19.md` 的 4 个 P0 + 12 个 P1，逐条对照当前**未提交 diff**（基线 `0e2fed1`）。
> 判定口径：只看本批 worktree 改动是否覆盖该条；本批没碰的文件一律记「未修（本批无关）」，不代表问题不存在。
> 验证：`pytest -q` → `71 passed, 4 skipped, 4 deselected`；10 题评测有重排 `10/10`、无重排 `8/10`（与 `docs/eval-hybrid-*.txt` 一致，详见文末「验证记录」）。

## 一、P0（4 条）

| 编号 | 问题 | 判定 | 证据 / 说明 |
|---|---|---|---|
| P0-1 | 切块把引言块与后续章节粘连（`chunker.py:152-159`） | **未修（本批无关）** | `chunker.py` 无 diff |
| P0-2 | 向量缓存只比对块数（`index_builder.py:106-108`） | **未修（本批无关）** | `index_builder.py` 无 diff |
| P0-3 | BM25 零分块被塞进 RRF（`hybrid.py:60-62`） | **已修** | `hybrid.py:60-68`：`k<=0` 返回空；先过滤 `s > 0` 再排序截断，保留原始下标。规格测试 `tests/test_retrieval_hybrid.py:82-104`（3 例：正分块少于候选池、全零分、`k=0`） |
| P0-4 | 部署回滚未真正恢复系统（`scripts/deploy.sh:249-252,356-357`） | **未修（本批无关）** | `scripts/deploy.sh` 无 diff |

**P0 完成度：1/4。**

## 二、P1（12 条）

| 编号 | 问题 | 判定 | 证据 / 说明 |
|---|---|---|---|
| P1-1 | 生成层对空 `choices` / `usage` 无防护（`answer_generator.py:101,137`） | **未修（本批无关）** | `answer_generator.py` 无 diff。注：`agent_core.py:143` 另加了空 `choices` 防护，但不在该文件 |
| P1-2 | 切块参数非法会死循环（`document_loader.py:108-111`） | **未修（本批无关）** | `document_loader.py` 无 diff |
| P1-3 | 装备型号模糊查询返回任意球拍（`tools/equipment_query.py:40`、`agent_tools.py:33`） | **部分修** | 空串已堵：`tools/equipment_query.py:38-39` 空关键词返回 `[]`；`agent_tools.py:24-28` 空型号返回 `missing_model`。**未修**：`%`/`_` 等 LIKE 元字符仍未转义（`tools/equipment_query.py:40`），`agent_tools.py:33` 仍 `rows[0]` 取首条、多命中不返回候选 |
| P1-4 | 管理后台密码可无限尝试（`admin/admin_app.py:38`） | **未修（本批无关）** | `admin/admin_app.py` 无 diff |
| P1-5 | 查询日志时区口径错误（`tools/query_log.py:51,73,131`） | **未修（本批无关）** | `tools/query_log.py` 无 diff |
| P1-6 | 会话 ID 只有 8 位十六进制（`tools/query_log.py:93`） | **未修（本批无关）** | 同上 |
| P1-7 | 评测脚本重复记录结果（`run_eval.py:181,202`） | **未修** | 本批改了 `run_eval.py`，但重复记录仍在：`run_eval.py:206` 命中后追加，`run_eval.py:227` 生成异常时再追加一次。证据文件已暴露该问题：`docs/eval-hybrid-recall10.txt` 报 `8/10` 却列 3 道未命中（第 6 题超时无判定、第 10 题命中后异常又被记一次） |
| P1-8 | 改写前缀用 `lstrip` 字符集（`run_eval.py:103`） | **未修** | `run_eval.py:109` 仍为 `lstrip("0123456789.-、) ")` |
| P1-9 | 部署通道关闭 SSH 主机校验（`scripts/deploy.sh:84-85`） | **未修（本批无关）** | `scripts/deploy.sh` 无 diff |
| P1-10 | 部署健康检查易误判（`scripts/deploy.sh:190,228`） | **未修（本批无关）** | 同上 |
| P1-11 | `app.py` 检索统计不可信（`app.py:397,263,41`） | **未修（本批无关）** | `app.py` 无 diff。注：`run_eval.py:33-36` 新增的 `RERANK_POOL` 解析已做 `max(TOP_K, ...)` 与非法值兜底，可作 `app.py:41` 的参考实现，但未改 `app.py` |
| P1-12 | `agent_core.py` 异常与配置边界静默降级（`agent_core.py:172,40-52,201`） | **部分修** | 已修：`act()` 的 `try` 只包住工具执行（`agent_core.py:182-205`），`format_evidence` 已移出异常路径；`_chat` 空 `choices` 有防护（`:143-145`）；配置读取有默认值兜底（`:40-56`）。**未修**：`decide()` 仍把 API 调用与 JSON 解析共用一个 `except Exception`（`:171-176`），API 故障仍被伪装成正常兜底决策；`_env_num` 未做 `math.isfinite`，`AGENT_LOW_RELEVANCE=nan/inf` 仍会通过 |

**P1 完成度：0 条全修，2 条部分修（P1-3、P1-12），10 条未修。其中本批已触及文件但未顺手修的有 P1-7、P1-8。**

## 三、本批 diff 中不属于 P0/P1 的改动

| 文件 | 内容 | 对应审查条目 |
|---|---|---|
| `agent_core.py:40-56` | `_env_num` 容错读取数值环境变量，非法值退回默认 | 与 P1-11（`app.py` 同类问题）、P1-12 相关，但审查未单列 `agent_core` 的导入期崩溃 |
| `agent_core.py:58-77` | LLM 客户端延迟构造，缺配置时在调用点报明确错误 | 同上，属健壮性加固 |
| `agent_core.py:143-145` | LLM 返回空 `choices` 时抛明确 `RuntimeError` | 与 P1-1 同类，但改在 agent 层 |
| `agent_core.py:208-250` | 零命中不再产出低相关度 block，`run()` 的「没检索到」兜底真正生效 | 与 P2 `answer_generator.py:259` 同类，agent 侧先修 |
| `agent_core.py:184-190`、`agent_tools.py:24-28`、`tools/equipment_query.py:31-41` | 空型号/空关键词显式拒绝 | P1-3 的一部分 |
| `.gitignore:61-64` | 忽略 Cloudflare Origin 私钥与安装脚本 | 安全卫生，审查未列 |

## 四、与既有记录不一致处

1. **无重排评测的复跑命令**：变更记录与任务口径都写 `python run_eval.py` → 8/10。但本机 `.env` 第 12 行有 `RAG_RERANK=true`，`load_dotenv()` 会把它读进来，直接运行实际是「重排开」→ 10/10。必须显式 `RAG_RERANK=false python run_eval.py` 才是 8/10。属**环境配置口径**问题，不是代码回归；`.env` 未入库。
2. **`docs/eval-hybrid-recall10.txt` 的未命中清单**：文件报 `8/10` 却列 3 道题（第 2、6、10 题）。本次复跑为 `8/10`、未命中 2 道（第 2、6 题）。差异由 P1-7 重复记录造成：第 6 题 API 超时未判定、第 10 题命中后生成异常又被追加为未命中。命中总数一致。
3. 变更记录中的 blob 锚点与当前 worktree 完全一致：`hybrid.py` = `1b79f15…`、`tests/test_retrieval_hybrid.py` = `faeeed3…`、`run_eval.py` = `dace83e…`。

## 五、验证记录（2026-11-20）

| 项 | 命令 | 结果 |
|---|---|---|
| 全量离线测试 | `.venv/Scripts/python.exe -m pytest -q` | `71 passed, 4 skipped, 4 deselected in 3.90s` |
| 跳过项 | 同上 `-rs` | `tests/test_admin_auth.py:29/42/55/68`，原因是 `pages/1_admin.py` 不存在 |
| 需 API 用例 | `pytest -q -m api --collect-only` | 4 条：`test_agent_mode_renders_without_duplicate_element_error`、`test_agent_pipeline_answers_equipment_question`、`test_old_10_questions_recall_at_5`、`test_new_8_questions_recall_at_5` |
| 10 题有重排 | `RAG_RERANK=true python run_eval.py` | `Recall@5: 10/10 (100%)` |
| 10 题无重排 | `RAG_RERANK=false python run_eval.py` | `Recall@5: 8/10 (80%)`，未命中：60 秒间歇、正手高远球常见错误 |

> 说明：README 提到的「68 项离线」是旧数字；本批新增 3 个 BM25 规格测试后为 71 通过 + 4 跳过（后台页面缺失）。4 条 API 用例默认由 `pytest.ini` 的 `-m "not api"` 排除。