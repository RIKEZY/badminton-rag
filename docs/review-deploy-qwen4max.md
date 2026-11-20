
─── scripts/deploy.sh:249-250 ───
[bug · high] Rollback is incomplete in three ways:
1. Only `${SERVICE_NAME}` is restarted — `${ADMIN_SERVICE_NAME}` keeps running the broken new admin
code, so the rollback doesn't actually restore the admin service.
2. `tar -xzf` over the live directory only overwrites archived paths; files newly added by the
failed deploy (new `admin/*.py`, corpus txt, index files, `.env`) survive the rollback and can still
be imported/served.
3. The restart timestamp file is not refreshed here, so the subsequent `health_check` in
`do_rollback` uses `--since` from the *failed* deploy's restart (or an older deploy's timestamp when
rolling back after a transfer failure). The failed deploy's error lines are then counted against the
rollback, producing a false "回滚后健康检查仍未通过" even when the rollback succeeded.

At minimum, restart both services and reset the timestamp; ideally also remove files not present in
the backup (e.g., extract into a clean dir and swap, or diff the file lists).

+ date +%s > /tmp/badminton-rag-restart.ts
  tar -xzf "${bak}" -C "${REMOTE_DIR}"
- ${SUDO} systemctl restart ${SERVICE_NAME}
+ ${SUDO} systemctl restart ${SERVICE_NAME} ${ADMIN_SERVICE_NAME}


─── scripts/deploy.sh:356-357 ───
[bug · high] `BACKUP_PATH` is re-derived from directory mtime ordering instead of using the exact
timestamped filename that `backup_script` just created. A concurrent deploy/backup (or any process
touching `backups/`) between the backup step and this query can make `ls -1t | head -n 1` return a
*different* archive, silently rolling back to the wrong version. Have `backup_script` emit the exact
path (e.g., `echo "BACKUP_PATH=${REMOTE_DIR}/backups/${ts}.tar.gz"`) and parse that marker from
`run_remote`'s output instead of guessing.



─── scripts/deploy.sh:189-190 ───
[bug · high] No readiness retry: a fixed `sleep 8` followed by a single curl attempt per URL will
fail while the app is still loading indexes/embeddings (common for a RAG app on cold start),
triggering an unnecessary destructive rollback. Replace the fixed sleep with a bounded retry loop,
e.g. poll `check_url` every 3–5s for up to 60–90s before declaring failure.



─── scripts/deploy.sh:228-228 ───
[bug · medium] `grep -Eqi 'error|traceback'` matches any benign occurrence of the substring:
`errors=0`, `error_handler`, logger/module names, INFO lines like "0 errors", etc. A single such
line fails the health check and triggers a rollback of a perfectly healthy deploy. Tighten the
pattern to actual failure indicators, e.g. `grep -Eq 'Traceback \(most recent call
last\)|\bERROR\b|CRITICAL|Exception'` (case-sensitive for level tags), and/or exclude known-benign
patterns.



─── scripts/deploy.sh:68-68 ───
[bug · high] `tools/equipment.db` is in the always-pushed `TOOL_FILES` list, so every deploy
unconditionally overwrites the live server-side SQLite database with the local copy — including any
rows written in production by `tools/query_log.py`. This is silent production data loss (the tar
backup is the only recovery path). Unlike `.env` and the index files, there is no opt-in flag.
Remove the DB from the default manifest and gate it behind an explicit flag (e.g. `--with-db`), or
push it only if it doesn't exist on the server.



─── scripts/deploy.sh:84-85 ───
[security · high] `StrictHostKeyChecking=no` combined with `UserKnownHostsFile=/dev/null` fully
disables host-key verification, removing MITM protection on a channel that uploads secrets (`.env`
with `--with-env`) and executes remote `sudo systemctl`/`rm` commands. An attacker who can intercept
the connection gets the deploy payload, the secrets, and arbitrary command execution as the deploy
user. Use `StrictHostKeyChecking=accept-new` with a persistent per-project known_hosts file (e.g.
`-o UserKnownHostsFile=~/.ssh/known_hosts_brag`), which still avoids the interactive prompt on Git
Bash while pinning the key after first connect.

-   -o StrictHostKeyChecking=no
-   -o UserKnownHostsFile=/dev/null
+   -o StrictHostKeyChecking=accept-new
+   -o UserKnownHostsFile="$HOME/.ssh/known_hosts_brag"


─── scripts/deploy.sh:27-27 ───
[security · medium] The SSH private key is hardcoded to `/tmp/brag.pem`. `/tmp` is world-writable,
so on a shared machine another local user can pre-create or replace this path (symlink/plant their
own key), and the script will happily `chmod 600` and use it — potentially authenticating with
attacker-controlled material or leaking access patterns. Store the key under `~/.ssh/` with 600
permissions (e.g. `SSH_KEY="${HOME}/.ssh/brag.pem"`) and allow overriding via an environment
variable.

- SSH_KEY="/tmp/brag.pem"
+ SSH_KEY="${BRAG_SSH_KEY:-${HOME}/.ssh/brag.pem}"


─── scripts/deploy.sh:187-187 ───
[security · low] The restart timestamp is written to a fixed, predictable path in world-writable
`/tmp` using `>` redirection, which follows symlinks. Another local user on the server can
pre-create `/tmp/badminton-rag-restart.ts` as a symlink to any file writable by the deploy user and
have it truncated/overwritten; they can also pre-set the timestamp to manipulate which logs the
health check inspects. Use a per-user path (e.g. `${REMOTE_DIR}/.last-restart.ts` or `mktemp` under
`$HOME`) instead.




──────── Project Summary ────────

### Top Issues

1. **Unconditional overwrite of the live production database** — `scripts/deploy.sh` includes `tools/equipment.db` in the always-pushed `TOOL_FILES` list. Every deploy replaces the server-side SQLite file with the local copy, discarding rows written in production by `tools/query_log.py`. This is silent, unrecoverable data loss on a routine operation and is the single highest-impact finding.

2. **Rollback does not actually restore a working system** — `scripts/deploy.sh` restarts only `${SERVICE_NAME}`, leaving `${ADMIN_SERVICE_NAME}` running the broken new admin code, and `tar -xzf` over the live directory only overwrites archived paths (files added by the bad release survive). A "successful" rollback can leave a partially-broken deployment that looks restored.

3. **Rollback can restore the wrong backup** — `BACKUP_PATH` is re-derived via `ls -1t | head -n 1` on directory mtime instead of using the exact timestamped filename produced by `backup_script`. Any concurrent deploy/backup or process touching `backups/` between the two steps redirects the restore at an unrelated archive — turning the recovery path into a second data-loss vector.

4. **Health checks produce false failures that trigger destructive rollback** — two compounding defects in `scripts/deploy.sh`: `grep -Eqi 'error|traceback'` matches benign text (`errors=0`, `error_handler`, logger/module names, "0 errors" INFO lines), and a fixed `sleep 8` plus one curl attempt per URL cannot tolerate cold-start index/embedding loading in a RAG app. Either alone can roll back a perfectly healthy deploy; together they make spurious rollbacks likely.

5. **SSH host-key verification fully disabled on a privileged channel** — `StrictHostKeyChecking=no` with `UserKnownHostsFile=/dev/null` in `scripts/deploy.sh` removes MITM protection on a connection that uploads `.env` secrets (`--with-env`) and executes remote `sudo systemctl` / `rm`. Interception yields both credential theft and remote code execution as a privileged user.

6. **Deploy key sourced from a world-writable, hardcoded path** — `/tmp/brag.pem` in `scripts/deploy.sh`. On a shared machine another local user can pre-create or symlink that path; the script `chmod 600`s and uses it regardless, potentially authenticating with an attacker-supplied key or leaking the real one.

7. **Symlink-following write to a predictable `/tmp` path on the server** — the restart timestamp is written with `>` to `/tmp/badminton-rag-restart.ts`. A local user can pre-create it as a symlink to any file writable by the deploy user and have that file truncated/overwritten.

### Module Hotspots

- **`scripts/` (specifically `scripts/deploy.sh`)** — 8/8 comments land in this single file, spanning data loss, broken recovery logic, and three distinct local/remote security weaknesses. Deployment is a single unguarded script that is simultaneously the release path, the backup path, and the recovery path; every defect here is production-facing with no compensating layer.
- **`tools/` (as a deploy payload)** — `tools/equipment.db` and `tools/query_log.py` are implicated by the `TOOL_FILES` handling in `scripts/deploy.sh`. The module boundary between "shipped code" and "server-owned state" is not encoded anywhere, which is what allows the DB overwrite.

### Cross-Cutting Concerns

- **Destructive operations gated by weak or unverified signals.** The rollback path acts on a substring grep and a single curl (`scripts/deploy.sh`), the restore target is chosen by mtime ordering rather than a known handle, and the DB push has no check at all. No step confirms its precondition before irreversibly mutating production.
- **Derived state instead of returned state (TOCTOU).** `BACKUP_PATH` re-queried via `ls -1t`, and `/tmp` paths assumed to be owned by the script (`/tmp/brag.pem`, `/tmp/badminton-rag-restart.ts`) — all in `scripts/deploy.sh`. The pattern is "guess a path/state that another actor can change" rather than capturing it at creation time.
- **World-writable `/tmp` used for security-sensitive and stateful artifacts.** Both the client-side SSH key and the server-side restart marker in `scripts/deploy.sh`; neither uses `mktemp`, ownership checks, or `noclobber`.
- **Partial-coverage semantics in multi-service operations.** Release touches both `${SERVICE_NAME}` and `${ADMIN_SERVICE_NAME}`, but restart/rollback covers only one; extraction is additive rather than a clean restore. Symmetry between deploy and rollback is not maintained.
- **Security controls disabled for convenience.** Host-key checking off, secrets pushed over that same channel, remote `sudo`/`rm` executed — `scripts/deploy.sh` trades the entire transport trust model for unattended execution.

### Quick Wins

- Drop `tools/equipment.db` from `TOOL_FILES` in `scripts/deploy.sh` (one-line change; eliminates the data-loss bug immediately). Add an explicit allowlist comment separating code from server-owned state.
- Have `backup_script` emit/return its exact filename and assign it directly to `BACKUP_PATH`; delete the `ls -1t | head -n 1` lookup.
- Add `${ADMIN_SERVICE_NAME}` to the rollback restart list.
- Replace `sleep 8` + single curl with a bounded retry loop (e.g. 30 attempts × 2s, fail only after the budget is exhausted).
- Tighten the log scan from `grep -Eqi 'error|traceback'` to anchored severity/level patterns (e.g. `\b(ERROR|CRITICAL)\b` at the log-level field, `^Traceback \(most recent call last\)`), and scope it to logs emitted since the restart timestamp.
- Replace `/tmp/brag.pem` and `/tmp/badminton-rag-restart.ts` with `mktemp`-created paths (or a `0700` per-user directory), and set `set -o noclobber` / use `>|` deliberately so redirect targets cannot be silently clobbered via symlink.
- Switch SSH to `StrictHostKeyChecking=accept-new` with a persistent, checked-in-or-provisioned `known_hosts` file instead of `/dev/null`.
