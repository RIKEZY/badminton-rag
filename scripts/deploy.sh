#!/usr/bin/env bash
# =============================================================================
# badminton-rag 一键部署脚本
#
# 做四件事：备份 → 传文件 → 重启 → 健康检查（失败自动回滚）。
#
# 用法（在项目根目录或任意位置执行均可）：
#   bash scripts/deploy.sh              # 正常部署，不传 .env
#   bash scripts/deploy.sh --dry-run    # 只打印将要执行的命令，不碰服务器
#   bash scripts/deploy.sh --with-env   # 额外覆盖服务器上的 .env（危险，默认不传）
#   bash scripts/deploy.sh --with-index # 连同 chunks_v2.json / vectors_v2.npy 一起传
#   bash scripts/deploy.sh -h           # 帮助
#
# 设计约定：
#   * 备份先做，备份失败就中止，绝不改服务器上的任何文件。
#   * 备份路径由备份脚本自己打印（BACKUP_PATH= 行）并被本地捕获，
#     不再事后用 `ls -1t | head -1` 猜——并发部署或备份被清理时会拿错版本。
#   * 传输阶段的任意一步失败也会回滚（此时服务还没重启，回滚只是把文件还原）。
#   * 健康检查三项全过才算成功：/ 返回 200、/ops/ 返回 200、日志无 error/traceback。
#   * 回滚先解包到临时目录并校验（tar -tzf + app.py 存在），确认无误才整体切换：
#     备份里有的顶层条目整份替换，部署后新增的顶层条目删掉（保留 backups/ 与
#     .venv/）；随后**同时重启两个服务**，再跑一遍健康检查。
#     解包/校验失败时线上文件一个都没动。
#   * 回滚只用 tar/mv/rm，不额外要求服务器装 rsync。
#   * 远端路径都写成 user@host:/opt/... 的形式，Git Bash 不会误改写成 Windows 路径。
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# 1. 配置区（改这里就够了）
# -----------------------------------------------------------------------------
SSH_USER="ubuntu"
SSH_HOST="35.78.108.43"
SSH_KEY="/tmp/brag.pem"
REMOTE_DIR="/opt/badminton-rag"
SERVICE_NAME="badminton-rag"
APP_PORT="8501"
# 管理后台是独立服务（Streamlit 不允许同一进程挂两个 baseUrlPath，
# 而且 pages/ 目录会让主应用侧边栏出现入口）
ADMIN_SERVICE_NAME="badminton-admin"
ADMIN_PORT="8502"

# 备份保留份数（含本次新生成的）
BACKUP_KEEP=5

# 重启服务用。若 ubuntu 用户已配置免密 sudo，保持 "sudo -n"；
# 若服务是用户级 systemd（systemctl --user），改成空字符串 ""。
SUDO="sudo -n"

# 部署清单：代码文件（相对项目根目录）
# 后三个是 app.py 的间接依赖（day3/hybrid 会被 import），漏传会直接起不来，所以一并带上
CODE_FILES=(
  app.py
  agent_core.py
  agent_tools.py
  rerank.py
  chunker.py
  answer_generator.py
  run_eval.py
  document_loader.py
  index_builder.py
  hybrid.py
)

# 索引缓存（默认不传；语料有改动时用 --with-index 一起传，否则线上仍是旧索引）
INDEX_FILES=(
  chunks_v2.json
  vectors_v2.npy
)

# 部署清单：工具文件（含 sqlite 库）
TOOL_FILES=(
  tools/equipment_query.py
  tools/query_log.py
  tools/equipment.db
)

# 部署清单：语料目录（只传 *.txt，不传 pdf）与管理后台（只传 *.py）
# 后台不再用 pages/ —— Streamlit 会因此生成侧边栏入口，且触发 _mpa_v1 分支；
# 现在跑在独立服务 8502 端口，由 nginx 反代到 /ops/
CORPUS_DIR="data_rules_only"
PAGE_DIR="admin"
CORPUS_GLOB="*.txt"
PAGE_GLOB="*.py"

# .env 默认不传；--with-env 才传
ENV_FILE=".env"

# SSH 通用参数：避免 Windows Git Bash 下的 known_hosts 交互提示
SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -o ConnectTimeout=15
)
SSH_TARGET="${SSH_USER}@${SSH_HOST}"

# -----------------------------------------------------------------------------
# 2. 参数解析
# -----------------------------------------------------------------------------
DRY_RUN=0
WITH_ENV=0
WITH_INDEX=0

usage() {
  awk '/^# =====/ { n++; next } n == 1' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n)  DRY_RUN=1 ;;
    --with-env)    WITH_ENV=1 ;;
    --with-index)  WITH_INDEX=1 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

# -----------------------------------------------------------------------------
# 3. 基础工具函数
# -----------------------------------------------------------------------------
log()  { echo; echo "==> $*"; }
info() { echo "    $*"; }
warn() { echo "!!  $*" >&2; }

# run_remote <描述> <远程 bash 脚本内容>
run_remote() {
  local desc="$1" script="$2"
  info "$desc"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] ssh ${SSH_OPTS[*]} -i $SSH_KEY $SSH_TARGET 'bash -s' <<'REMOTE'"
    printf '%s\n' "$script" | sed 's/^/    | /'
    echo "    REMOTE"
  else
    printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_TARGET" 'bash -s'
  fi
}

# push_files <描述> <远程目录> <本地文件...>
push_files() {
  local desc="$1" rdir="$2"
  shift 2
  local files=("$@")
  info "$desc（${#files[@]} 个文件 → $rdir）"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] scp ${SSH_OPTS[*]} -i $SSH_KEY \\"
    echo "              ${files[*]} \\"
    echo "              $SSH_TARGET:$rdir"
  else
    scp "${SSH_OPTS[@]}" -i "$SSH_KEY" "${files[@]}" "$SSH_TARGET:$rdir"
  fi
}

# 收集目录下匹配的文件，写入全局数组（避免 nullglob/空数组展开的坑）
collect() {  # collect <变量名> <目录> <glob>
  local __name="$1" __dir="$2" __glob="$3" __f
  local __out=()
  while IFS= read -r __f; do
    [ -n "$__f" ] && __out+=("$__f")
  done < <(find "$__dir" -maxdepth 1 -type f -name "$__glob" | sort)
  eval "$__name=(\"\${__out[@]}\")"
}

# -----------------------------------------------------------------------------
# 4. 远端脚本模板
# -----------------------------------------------------------------------------
backup_script() {
  cat <<EOF
set -euo pipefail
cd "${REMOTE_DIR}"
mkdir -p backups
chmod 700 backups
ts=\$(date +%Y%m%d-%H%M%S)
bak="${REMOTE_DIR}/backups/\${ts}.tar.gz"
tar -czf "backups/\${ts}.tar.gz" \\
  --exclude='./.venv' \\
  --exclude='./backups' \\
  --exclude='./__pycache__' \\
  --exclude='*/__pycache__' \\
  --exclude='*.pyc' \\
  --exclude='./.rollback.*' \\
  -C "${REMOTE_DIR}" .
# 记下「上一版本」到底是哪一份：latest.path 供人工排查，BACKUP_PATH= 供本地捕获。
# 回滚只认这一份文件，不再回头猜最新备份。
printf '%s\n' "\$bak" > backups/latest.path
echo "   备份文件: \$bak (\$(du -h "backups/\${ts}.tar.gz" | cut -f1))"
echo "BACKUP_PATH=\$bak"
ls -1t backups/*.tar.gz | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f --
echo "   现有备份: \$(ls -1 backups/*.tar.gz | wc -l) 份（保留上限 ${BACKUP_KEEP}）"
EOF
}

restart_script() {
  cat <<EOF
set -euo pipefail
# 记下重启时刻：健康检查只看这之后的日志。
# 用 -n 40 会读到重启前的历史日志——实测把昨天的崩溃翻出来，
# 误判成这次部署失败并触发无谓回滚。
date +%s > /tmp/badminton-rag-restart.ts
${SUDO} systemctl restart ${SERVICE_NAME} ${ADMIN_SERVICE_NAME}
echo "   已重启 ${SERVICE_NAME} / ${ADMIN_SERVICE_NAME}，等待 8 秒…"
sleep 8
echo "   当前状态: \$(systemctl is-active ${SERVICE_NAME} ${ADMIN_SERVICE_NAME} | tr '\n' ' ')"
EOF
}

health_script() {
  cat <<EOF
set -uo pipefail
rc=0

check_url() {
  local path="\$1" port="\${2:-${APP_PORT}}" code
  # -L 跟随重定向：Streamlit 对 baseUrlPath 会先 301 补斜杠，不跟随会误判成失败
  code=\$(curl -sL -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:\${port}\${path}" || echo 000)
  if [ "\$code" = "200" ]; then
    echo "   [OK]   GET :\${port}\${path}  -> HTTP \$code"
  else
    echo "   [FAIL] GET :\${port}\${path}  -> HTTP \$code"
    rc=1
  fi
}
check_url /
# 后台在独立端口，拿主服务端口查 /ops/ 只会拿到 301
check_url /ops/ ${ADMIN_PORT}

# 只看本次重启之后的日志，避免把历史错误算到这次部署头上
SINCE_ARG="--since -3min"
if [ -f /tmp/badminton-rag-restart.ts ]; then
  SINCE_ARG="--since @\$(cat /tmp/badminton-rag-restart.ts)"
fi

check_log() {
  local svc="\$1" log
  if ! log=\$(${SUDO} journalctl -u "\$svc" \$SINCE_ARG --no-pager 2>&1); then
    echo "   [FAIL] \$svc 日志读取失败（可能权限不足）"
    rc=1
    return
  fi
  if printf '%s\n' "\$log" | grep -Eqi 'error|traceback'; then
    echo "   [FAIL] \$svc 重启后日志含 error/traceback："
    printf '%s\n' "\$log" | grep -Ei 'error|traceback' | tail -n 5 | sed 's/^/          /'
    rc=1
  else
    echo "   [OK]   \$svc 重启后无 error/traceback"
  fi
}
check_log ${SERVICE_NAME}
check_log ${ADMIN_SERVICE_NAME}

exit \$rc
EOF
}

rollback_script() {  # rollback_script <备份绝对路径>
  local bak="$1"
  cat <<EOF
set -euo pipefail
cd "${REMOTE_DIR}"

bak="${bak}"
if [ ! -f "\$bak" ]; then
  echo "   备份不存在: \$bak（线上文件未改动）" >&2
  exit 1
fi

# 先验证归档本身没坏，坏了就不要动线上文件
if ! tar -tzf "\$bak" >/dev/null 2>&1; then
  echo "   备份归档损坏: \$bak（线上文件未改动），需要人工介入" >&2
  exit 4
fi

tmp=\$(mktemp -d "${REMOTE_DIR}/.rollback.XXXXXX")
cleanup() { rm -rf "\$tmp"; }
trap cleanup EXIT
echo "   解包备份到临时目录: \$tmp"
tar -xzf "\$bak" -C "\$tmp"
# 归档里必须有 app.py；不完整就中止，此时线上仍是部署后的版本，但至少不是混合状态
if [ ! -f "\$tmp/app.py" ]; then
  echo "   备份里没有 app.py，疑似不完整（线上文件未改动），需要人工介入" >&2
  exit 5
fi

# 整体切换而不是覆盖解包。先删部署后新增、备份里没有的顶层条目
# （否则回滚完还是混合状态），再用备份里的条目整份替换。
# 顺序不能反：替换会把 tmp 清空，之后再判断「备份里有没有」就全判成没有了。
shopt -s dotglob nullglob
for p in *; do
  name="\${p##*/}"
  case "\$name" in
    backups|.venv|.rollback.*) continue ;;
  esac
  [ -e "\$tmp/\$name" ] || rm -rf -- "\$name"
done
for p in "\$tmp"/*; do
  name="\${p##*/}"
  rm -rf -- "\$name"
  mv -- "\$p" "\$name"
done
echo "   已还原到备份内容"

# 记下回滚重启时刻，健康检查只看此后的日志
date +%s > /tmp/badminton-rag-restart.ts
${SUDO} systemctl restart ${SERVICE_NAME} ${ADMIN_SERVICE_NAME}
echo "   已回滚并重启 ${SERVICE_NAME} / ${ADMIN_SERVICE_NAME}，等待 8 秒…"
sleep 8
echo "   当前状态: \$(systemctl is-active ${SERVICE_NAME} ${ADMIN_SERVICE_NAME} | tr '\n' ' ')"
EOF
}

# -----------------------------------------------------------------------------
# 5. 健康检查（本地调用，内部走 ssh）
# -----------------------------------------------------------------------------
health_check() {
  local out
  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] 跳过真实健康检查，将执行："
    health_script | sed 's/^/    | /'
    return 0
  fi
  if out=$(printf '%s\n' "$(health_script)" | ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_TARGET" 'bash -s'); then
    printf '%s\n' "$out"
    return 0
  else
    printf '%s\n' "$out"
    return 1
  fi
}

# -----------------------------------------------------------------------------
# 6. 预检
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo "=================================================================="
echo " badminton-rag 部署"
echo "   本地项目 : ${PROJECT_ROOT}"
echo "   目标     : ${SSH_TARGET}:${REMOTE_DIR}"
echo "   服务     : ${SERVICE_NAME} (127.0.0.1:${APP_PORT})"
echo "   模式     : $([ "$DRY_RUN" -eq 1 ] && echo 'DRY-RUN（不改动服务器）' || echo '真实部署')"
echo "   上传 .env: $([ "$WITH_ENV" -eq 1 ] && echo '是（会覆盖服务器 .env）' || echo '否')"
echo "   上传索引 : $([ "$WITH_INDEX" -eq 1 ] && echo '是（覆盖 chunks/vectors 缓存）' || echo '否')"
echo "=================================================================="

log "预检：本地文件与密钥"
if [ ! -f "$SSH_KEY" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    warn "密钥不存在：$SSH_KEY（dry-run 下仅警告）"
  else
    warn "密钥不存在：$SSH_KEY"
    exit 2
  fi
else
  info "密钥: $SSH_KEY"
  # ssh 会拒绝权限过宽的私钥，这里顺手收紧（仅真实部署时）
  if [ "$DRY_RUN" -eq 0 ] && [ "$(stat -c '%a' "$SSH_KEY" 2>/dev/null || echo 600)" != "600" ]; then
    chmod 600 "$SSH_KEY" && info "已把密钥权限修正为 600"
  fi
fi

missing=0
for f in "${CODE_FILES[@]}" "${TOOL_FILES[@]}"; do
  if [ ! -f "$f" ]; then warn "缺少文件: $f"; missing=1; fi
done
[ "$missing" -eq 0 ] || exit 2

collect CORPUS_FILES "$CORPUS_DIR" "$CORPUS_GLOB"
collect PAGE_FILES   "$PAGE_DIR"   "$PAGE_GLOB"

if [ "${#CORPUS_FILES[@]}" -eq 0 ]; then warn "语料目录 $CORPUS_DIR 下没有 $CORPUS_GLOB"; exit 2; fi
if [ "${#PAGE_FILES[@]}" -eq 0 ];   then warn "后台目录 $PAGE_DIR 下没有 $PAGE_GLOB";   exit 2; fi

info "代码 ${#CODE_FILES[@]} 个 / 语料 ${#CORPUS_FILES[@]} 个 / 工具 ${#TOOL_FILES[@]} 个 / 后台 ${#PAGE_FILES[@]} 个"

if [ "$WITH_ENV" -eq 1 ] && [ ! -f "$ENV_FILE" ]; then
  warn "--with-env 指定了但本地找不到 $ENV_FILE"
  exit 2
fi

if [ "$WITH_INDEX" -eq 1 ]; then
  for f in "${INDEX_FILES[@]}"; do
    if [ ! -f "$f" ]; then warn "--with-index 指定了但本地找不到 $f"; exit 2; fi
  done
  info "索引 ${#INDEX_FILES[@]} 个 / 共 $(du -ch "${INDEX_FILES[@]}" | tail -1 | cut -f1)"
fi

log "预检：SSH 连通性"
if [ "$DRY_RUN" -eq 1 ]; then
  info "[dry-run] ssh ${SSH_OPTS[*]} -i $SSH_KEY $SSH_TARGET \"test -d '${REMOTE_DIR}' && test -f '${REMOTE_DIR}/app.py'\""
else
  if ! ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_TARGET" \
        "test -d '${REMOTE_DIR}' && test -f '${REMOTE_DIR}/app.py'" ; then
    warn "无法连接服务器，或 ${REMOTE_DIR} 不存在 / 不是有效部署目录"
    exit 2
  fi
  info "连接正常，${REMOTE_DIR} 存在"
fi

# -----------------------------------------------------------------------------
# 7. 备份
# -----------------------------------------------------------------------------
log "第 1 步：部署前备份（服务器端 tar，保留最近 ${BACKUP_KEEP} 份）"

# 备份路径必须由这次备份自己给出：BACKUP_PATH= 行由 backup_script 打印。
# 旧写法「再开一个 ssh 跑 ls -1t | head -1」会拿到最新文件而不是本次备份
# （并发部署、备份清理、或本次备份没生成时都会错），回滚就回错版本。
if [ "$DRY_RUN" -eq 1 ]; then
  info "[dry-run] 备份脚本（回滚路径取其中的 BACKUP_PATH= 行）"
  backup_script | sed 's/^/    | /'
  BACKUP_PATH="<本次备份>.tar.gz"
else
  info "打包当前版本到 ${REMOTE_DIR}/backups/"
  if ! backup_out=$(printf '%s\n' "$(backup_script)" \
        | ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_TARGET" 'bash -s'); then
    warn "备份失败，服务器未做任何改动，中止部署"
    exit 2
  fi
  printf '%s\n' "$backup_out" | grep -v '^BACKUP_PATH=' || true
  BACKUP_PATH=$(printf '%s\n' "$backup_out" | sed -n 's/^BACKUP_PATH=//p' | tail -n 1)
  if [ -z "$BACKUP_PATH" ]; then
    warn "备份脚本没有返回路径，无法保证可回滚，中止部署"
    exit 2
  fi
  info "本次备份: $BACKUP_PATH"
fi

# -----------------------------------------------------------------------------
# 8. 传文件（按类别）
# -----------------------------------------------------------------------------
log "第 2 步：上传文件"

run_remote "确保远端目录存在" "$(cat <<EOF
set -euo pipefail
mkdir -p '${REMOTE_DIR}/admin' '${REMOTE_DIR}/tools' '${REMOTE_DIR}/data_rules_only'
EOF
)"

if ! push_files "代码" "${REMOTE_DIR}/" "${CODE_FILES[@]}"; then
  warn "代码上传失败"; ROLLBACK_REASON="代码上传失败"; TRANSFER_FAILED=1
fi
TRANSFER_FAILED=${TRANSFER_FAILED:-0}

if [ "$TRANSFER_FAILED" -eq 0 ]; then
  if ! push_files "语料（txt）" "${REMOTE_DIR}/${CORPUS_DIR}/" "${CORPUS_FILES[@]}"; then
    warn "语料上传失败"; ROLLBACK_REASON="语料上传失败"; TRANSFER_FAILED=1
  fi
fi

if [ "$TRANSFER_FAILED" -eq 0 ]; then
  if ! push_files "工具（py + db）" "${REMOTE_DIR}/tools/" "${TOOL_FILES[@]}"; then
    warn "工具上传失败"; ROLLBACK_REASON="工具上传失败"; TRANSFER_FAILED=1
  fi
fi

if [ "$TRANSFER_FAILED" -eq 0 ]; then
  if ! push_files "管理后台" "${REMOTE_DIR}/admin/" "${PAGE_FILES[@]}"; then
    warn "后台上传失败"; ROLLBACK_REASON="后台上传失败"; TRANSFER_FAILED=1
  fi
fi

if [ "$TRANSFER_FAILED" -eq 0 ] && [ "$WITH_INDEX" -eq 1 ]; then
  if ! push_files "索引缓存" "${REMOTE_DIR}/" "${INDEX_FILES[@]}"; then
    warn "索引上传失败"; ROLLBACK_REASON="索引上传失败"; TRANSFER_FAILED=1
  fi
fi

if [ "$TRANSFER_FAILED" -eq 0 ] && [ "$WITH_ENV" -eq 1 ]; then
  if ! push_files ".env（覆盖）" "${REMOTE_DIR}/" "$ENV_FILE"; then
    warn ".env 上传失败"; ROLLBACK_REASON=".env 上传失败"; TRANSFER_FAILED=1
  elif [ "$DRY_RUN" -eq 0 ]; then
    run_remote "收紧 .env 权限" "chmod 600 '${REMOTE_DIR}/${ENV_FILE}'"
  fi
fi

# -----------------------------------------------------------------------------
# 8.5 清理已废弃的文件
# -----------------------------------------------------------------------------
# 文件重命名后（day*.py → document_loader / index_builder / answer_generator），
# 旧文件不会自动消失。它们不影响运行（已经没人 import），但会一直躺在服务器上：
# 下次排查问题时看到 day2.py，会以为还在用。
#
# 只删明确列出的文件，不用通配符——通配符一旦写错，删掉的就是不该删的。
if [ "$TRANSFER_FAILED" -eq 0 ]; then
  log "第 2.5 步：清理已废弃的文件"
  if ! run_remote "删除废弃脚本" "$(cat <<EOF
set -uo pipefail
cd '${REMOTE_DIR}'
removed=0
# query_log.py 规范位置是 tools/ 下，根目录那份是早期手动 scp 的残留
for f in day1.py day2.py day3.py day4.py step1_bm25.py test_api.py test_chunker.py test_hybrid.py query_log.py; do
  if [ -f "\$f" ]; then
    rm -f "\$f" && echo "   已删除 \$f" && removed=\$((removed+1))
  fi
done
if [ "\$removed" -eq 0 ]; then
  echo "   无废弃文件需要清理"
fi
EOF
)"; then
    # 清理失败不触发回滚：它只是卫生问题，不影响服务能不能跑
    warn "清理失败，但不影响运行，继续"
  fi
fi

# -----------------------------------------------------------------------------
# 9. 重启 + 健康检查 + 回滚
# -----------------------------------------------------------------------------
# 失败路径（脚本退出码）：
#   2  预检/备份/回滚前置条件失败——服务器未改动，或已停止继续操作
#   1  部署失败但回滚成功（服务已回到部署前版本，需要查这次改动为什么坏）
#   2  部署失败且回滚也失败——线上可能仍是坏版本，需要人工介入
# 触发回滚的时机：文件传输任一步失败、systemctl restart 失败、健康检查未通过。
# 回滚本身逐项校验（备份存在 → 归档完整 → 含 app.py → 整体切换 →
# 两个服务都重启 → 健康检查）；任何一步失败都明确报「需要人工介入」，
# 不会静默留在半坏状态。
#
# 返回 0 表示回滚成功，1 表示回滚失败（需要人工介入）
do_rollback() {
  local reason="$1"
  echo
  warn "部署失败：${reason}"
  log "开始回滚到本次部署前的备份"
  info "回滚目标: ${BACKUP_PATH:-<未记录>}"

  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] 将校验 ${BACKUP_PATH}、解包到临时目录、整体切换顶层条目，"
    info "[dry-run] 同时重启 ${SERVICE_NAME} / ${ADMIN_SERVICE_NAME}，再跑健康检查"
    return 0
  fi

  local bak="${BACKUP_PATH:-}"
  if [ -z "$bak" ] || ! printf '%s\n' "test -f '${bak}'" \
      | ssh "${SSH_OPTS[@]}" -i "$SSH_KEY" "$SSH_TARGET" 'bash -s'; then
    warn "找不到可用备份（$bak），回滚无法进行，需要人工介入"
    return 1
  fi

  if ! run_remote "校验备份、还原文件并重启两个服务" "$(rollback_script "$bak")"; then
    warn "回滚过程出错，需要人工介入"
    return 1
  fi

  log "回滚后健康检查"
  if health_check; then
    info "回滚完成，服务已恢复到备份版本"
    return 0
  fi
  warn "回滚后健康检查仍未通过，需要人工介入"
  return 1
}

if [ "${TRANSFER_FAILED:-0}" -eq 1 ]; then
  if do_rollback "${ROLLBACK_REASON}"; then exit 1; else exit 2; fi
fi

log "第 3 步：重启服务"
if ! run_remote "systemctl restart ${SERVICE_NAME}" "$(restart_script)"; then
  if do_rollback "服务重启失败"; then exit 1; else exit 2; fi
fi

log "第 4 步：健康检查（/ 、/ops/ 、journalctl）"
if ! health_check; then
  if do_rollback "健康检查未通过（见上方 [FAIL] 行）"; then exit 1; else exit 2; fi
fi

# -----------------------------------------------------------------------------
# 10. 完成
# -----------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY-RUN 结束（以上命令均未执行，服务器未做任何改动）"
else
  log "部署成功"
  info "版本备份: ${BACKUP_PATH}"
  info "访问地址: http://${SSH_HOST}/  （管理后台 http://${SSH_HOST}/ops/）"
  if [ "$WITH_INDEX" -eq 0 ]; then
    info "提示: 本次未上传索引缓存；语料内容若已变化，需加 --with-index 或让服务端重建索引，否则仍用旧索引作答"
  fi
fi
echo
