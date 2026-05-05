#!/bin/bash
#=============================================================================
# rollback.sh — 回滚验证脚本
# Phase 6: Version Governance
#
# 功能:
#   将平台回滚到指定 release 的 Git commit，并验证组件一致性。
#
# 用法:
#   ./scripts/rollback.sh <target_release_id> [--dry-run]
#
# 示例:
#   ./scripts/rollback.sh release_2026_05_05_001            # 执行回滚
#   ./scripts/rollback.sh release_2026_05_05_001 --dry-run   # 仅检查，不执行
#
# 回滚步骤:
#   1. 检查目标 release 的 Manifest 是否存在
#   2. 记录当前 Git HEAD 以备恢复
#   3. Git checkout 到目标 release 的 commit
#   4. 验证 active-release.yaml 与 Manifest 一致
#   5. 验证所有组件文件存在
#   6. 更新 active-release.yaml 指向目标 release
#   7. 在失败 release 的 Manifest 中记录回滚事件
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 颜色定义 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 参数解析 ──
TARGET_RELEASE="${1:-}"
DRY_RUN=false
if [[ "${2:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

if [[ -z "$TARGET_RELEASE" ]]; then
    echo "用法: $0 <target_release_id> [--dry-run]"
    echo ""
    echo "示例:"
    echo "  $0 release_2026_05_05_001"
    echo "  $0 release_2026_05_05_001 --dry-run"
    exit 1
fi

# ── 检查 yq ──
if ! command -v yq &>/dev/null; then
    log_error "需要 'yq' 命令行工具来处理 YAML。"
    log_error "安装: brew install yq  或  pip install yq"
    exit 1
fi

# ── 检查 Manifest ──
MANIFEST_FILE="$WORKSPACE_ROOT/config/releases/${TARGET_RELEASE}.yaml"
if [[ ! -f "$MANIFEST_FILE" ]]; then
    log_error "目标 release 的 Manifest 文件不存在: $MANIFEST_FILE"
    log_error "可用的 releases:"
    ls -1 "$WORKSPACE_ROOT/config/releases/"*.yaml 2>/dev/null | sed 's/.*\///;s/\.yaml$//' | sed 's/^/  /'
    exit 1
fi

# ── 读取目标 Manifest ──
TARGET_COMMIT=$(yq eval '.git_commit // ""' "$MANIFEST_FILE")
TARGET_TAG=$(yq eval '.git_tag // ""' "$MANIFEST_FILE")
TARGET_WF_VER=$(yq eval '.components.workflow_version // ""' "$MANIFEST_FILE")
TARGET_CONST_VER=$(yq eval '.components.constraint_pack_version // ""' "$MANIFEST_FILE")
TARGET_PROMPT_VER=$(yq eval '.components.prompt_version // ""' "$MANIFEST_FILE")
TARGET_EVAL_VER=$(yq eval '.components.evaluator_version // ""' "$MANIFEST_FILE")
TARGET_KB_VER=$(yq eval '.components.knowledge_base_version // ""' "$MANIFEST_FILE")

echo "============================================"
echo "  回滚目标: $TARGET_RELEASE"
echo "  Git Commit: ${TARGET_COMMIT:-<通过 Git tag>}"
echo "  Git Tag: ${TARGET_TAG:-<无>}"
echo "============================================"
echo ""

if [[ -z "$TARGET_COMMIT" && -z "$TARGET_TAG" ]]; then
    log_error "Manifest 中既没有 git_commit 也没有 git_tag，无法定位目标版本。"
    exit 1
fi

# ── 获取当前 Git 信息 ──
CURRENT_COMMIT=$(git -C "$WORKSPACE_ROOT" rev-parse HEAD)
CURRENT_BRANCH=$(git -C "$WORKSPACE_ROOT" rev-parse --abbrev-ref HEAD)
log_info "当前 HEAD: $CURRENT_COMMIT (分支: $CURRENT_BRANCH)"

# ── 检查 Git 工作区 ──
if ! git -C "$WORKSPACE_ROOT" diff --quiet --exit-code; then
    log_warn "Git 工作区有未提交的修改。建议先提交或 stash。"
    if [[ "$DRY_RUN" == "false" ]]; then
        log_warn "继续执行回滚（未提交的修改可能丢失）..."
    fi
fi

# ── 确定 Git checkout 目标 ──
GIT_TARGET="${TARGET_TAG:-$TARGET_COMMIT}"

# ── 验证 Git 目标存在 ──
if ! git -C "$WORKSPACE_ROOT" rev-parse --verify "$GIT_TARGET" &>/dev/null; then
    log_error "Git 目标不存在: $GIT_TARGET"
    exit 1
fi
log_ok "Git 目标可访问: $GIT_TARGET"

# ── 组件一致性验证 ──
echo ""
echo "── 组件一致性验证 ──"

# 验证 active-release.yaml 中的版本
ACTIVE_WF=$(yq eval '.active_release.workflow_version // "?"' "$WORKSPACE_ROOT/config/active-release.yaml")
ACTIVE_CONST=$(yq eval '.active_release.constraint_pack_version // "?"' "$WORKSPACE_ROOT/config/active-release.yaml")

COMPATIBLE=true
if [[ "$ACTIVE_WF" != "$TARGET_WF_VER" ]]; then
    log_warn "active-release 工作流版本 ($ACTIVE_WF) ≠ Manifest ($TARGET_WF_VER)"
    COMPATIBLE=false
fi
if [[ "$ACTIVE_CONST" != "$TARGET_CONST_VER" ]]; then
    log_warn "active-release 约束版本 ($ACTIVE_CONST) ≠ Manifest ($TARGET_CONST_VER)"
    COMPATIBLE=false
fi

# 验证 key 组件文件存在
echo ""
log_info "检查组件文件..."
MISSING_FILES=0

# 读取工作流列表
while IFS= read -r wf; do
    wf_path="$WORKSPACE_ROOT/$wf"
    if [[ ! -f "$wf_path" ]]; then
        log_error "工作流文件缺失: $wf_path"
        MISSING_FILES=$((MISSING_FILES + 1))
    fi
done < <(yq eval '.workflow_list[]' "$MANIFEST_FILE")

# 读取约束列表
while IFS= read -r c; do
    c_path="$WORKSPACE_ROOT/$c"
    if [[ ! -f "$c_path" ]]; then
        log_error "约束文件缺失: $c_path"
        MISSING_FILES=$((MISSING_FILES + 1))
    fi
done < <(yq eval '.constraint_list[]' "$MANIFEST_FILE")

if [[ $MISSING_FILES -eq 0 ]]; then
    log_ok "所有组件文件存在"
fi

echo ""
echo "── 验证结果 ──"
if [[ "$MISSING_FILES" -gt 0 ]]; then
    log_error "缺少 $MISSING_FILES 个组件文件，回滚可能不完整。"
    if [[ "$DRY_RUN" == "false" ]]; then
        echo ""
        log_warn "是否继续回滚? (输入 yes 继续)"
        read -r CONFIRM
        if [[ "$CONFIRM" != "yes" ]]; then
            log_info "回滚已取消"
            exit 1
        fi
    fi
else
    log_ok "组件完整性检查通过"
fi

# ── Dry-run 模式 ──
if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    log_info "DRY RUN — 未执行实际回滚"
    echo ""
    echo "将执行的操作:"
    echo "  1. Git checkout $GIT_TARGET"
    echo "  2. 更新 active-release.yaml → $TARGET_RELEASE"
    echo "  3. 在 config/releases/${TARGET_RELEASE}.yaml 中更新回滚状态"
    echo "  4. 创建 rollback checkpoint 记录"
    exit 0
fi

# ── 执行回滚 ──
echo ""
log_info "执行回滚到 $GIT_TARGET..."
echo ""

# 步骤 1: 记录当前状态用于事后恢复
CHECKPOINT_FILE="$WORKSPACE_ROOT/runtime/rollback_checkpoint_${TARGET_RELEASE}.json"
mkdir -p "$WORKSPACE_ROOT/runtime"
cat > "$CHECKPOINT_FILE" <<EOF
{
  "rollback_checkpoint": true,
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "from_commit": "$CURRENT_COMMIT",
  "from_branch": "$CURRENT_BRANCH",
  "from_release": "$(yq eval '.active_release.id // "unknown"' "$WORKSPACE_ROOT/config/active-release.yaml")",
  "to_release": "$TARGET_RELEASE",
  "to_commit": "$GIT_TARGET",
  "status": "in_progress"
}
EOF
log_ok "Checkpoint 已保存: $CHECKPOINT_FILE"

# 步骤 2: Git checkout
log_info "执行: git checkout $GIT_TARGET"
git -C "$WORKSPACE_ROOT" checkout "$GIT_TARGET"
log_ok "Git checkout 完成"

# 步骤 3: 验证回滚后的状态
POST_COMMIT=$(git -C "$WORKSPACE_ROOT" rev-parse HEAD)
log_ok "当前 HEAD: $POST_COMMIT"

# 步骤 4: 更新 active-release.yaml 中的 release_id
yq eval -i ".active_release.id = \"$TARGET_RELEASE\"" "$WORKSPACE_ROOT/config/active-release.yaml"
yq eval -i ".active_release.git_commit = \"$POST_COMMIT\"" "$WORKSPACE_ROOT/config/active-release.yaml"
log_ok "active-release.yaml 已更新"

# 步骤 5: 在目标 Manifest 中记录回滚事件
ROLLBACK_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Manifest 可能来自已回退的 commit，所以直接编辑当前文件
if [[ -f "$MANIFEST_FILE" ]]; then
    yq eval -i ".status = \"published\"" "$MANIFEST_FILE"
    # 添加 rollback 记录 (如果 rollback 字段为空则创建)
    RB_EXISTS=$(yq eval '.rollback' "$MANIFEST_FILE" 2>/dev/null)
    if [[ "$RB_EXISTS" == "null" ]]; then
        yq eval -i ".rollback = null" "$MANIFEST_FILE"
    fi
    yq eval -i ".rollback.rolled_back_from = \"$CURRENT_COMMIT\"" "$MANIFEST_FILE"
    yq eval -i ".rollback.rolled_back_to = \"$TARGET_RELEASE\"" "$MANIFEST_FILE"
    yq eval -i ".rollback.reason = \"Emergency rollback via rollback.sh\"" "$MANIFEST_FILE"
    yq eval -i ".rollback.timestamp = \"$ROLLBACK_TIMESTAMP\"" "$MANIFEST_FILE"
    yq eval -i ".rollback.verified = false" "$MANIFEST_FILE"
    log_ok "Manifest 回滚记录已更新"
fi

# 步骤 6: 更新 checkpoint 为完成
cat > "$CHECKPOINT_FILE" <<EOF
{
  "rollback_checkpoint": true,
  "timestamp": "$ROLLBACK_TIMESTAMP",
  "from_commit": "$CURRENT_COMMIT",
  "from_branch": "$CURRENT_BRANCH",
  "to_release": "$TARGET_RELEASE",
  "to_commit": "$POST_COMMIT",
  "status": "completed"
}
EOF

echo ""
echo "============================================"
log_ok "回滚完成: $TARGET_RELEASE"
echo "  回滚前: $CURRENT_COMMIT"
echo "  回滚后: $POST_COMMIT"
echo "  Checkpoint: $CHECKPOINT_FILE"
echo "============================================"
echo ""
log_info "建议后续步骤:"
echo "  1. 运行工作流测试验证功能正常"
echo "  2. 运行 schema 验证: yq eval '.' config/active-release.yaml"
echo "  3. 如一切正常，提交回滚结果并打新的 fix tag"
echo "  4. 复盘回滚原因并更新预防措施"
