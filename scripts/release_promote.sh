#!/bin/bash
#=============================================================================
# release_promote.sh — 发布晋升脚本
# Phase 6: Version Governance
#
# 功能:
#   将 release 在生命周期状态间晋升:
#     draft → review → published
#
# 用法:
#   ./scripts/release_promote.sh <release_id> <target_status> [--force]
#
# 示例:
#   ./scripts/release_promote.sh release_2026_05_05_001 review
#   ./scripts/release_promote.sh release_2026_05_05_001 published
#
# 前置条件:
#   - Git 工作区干净 (published 时需要)
#   - release manifest 文件存在于 config/releases/<release_id>.yaml
#   - yq (YAML 命令行工具) 已安装
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
RELEASE_ID="${1:-}"
TARGET_STATUS="${2:-}"
FORCE="${3:-}"

if [[ -z "$RELEASE_ID" || -z "$TARGET_STATUS" ]]; then
    echo "用法: $0 <release_id> <target_status> [--force]"
    echo ""
    echo "支持的状态转换:"
    echo "  draft → review"
    echo "  review → published"
    echo "  published → deprecated"
    exit 1
fi

# ── 验证状态值 ──
VALID_STATUSES=("draft" "review" "published" "deprecated")
FOUND=false
for s in "${VALID_STATUSES[@]}"; do
    if [[ "$s" == "$TARGET_STATUS" ]]; then
        FOUND=true
        break
    fi
done
if [[ "$FOUND" == "false" ]]; then
    log_error "无效的目标状态: $TARGET_STATUS"
    log_error "有效值: ${VALID_STATUSES[*]}"
    exit 1
fi

# ── 定位 Manifest 文件 ──
MANIFEST_FILE="$WORKSPACE_ROOT/config/releases/${RELEASE_ID}.yaml"
if [[ ! -f "$MANIFEST_FILE" ]]; then
    log_error "Release manifest 文件不存在: $MANIFEST_FILE"
    exit 1
fi

# ── 检查 yq 是否安装 ──
if ! command -v yq &>/dev/null; then
    log_error "需要 'yq' 命令行工具来处理 YAML。"
    log_error "安装: brew install yq  或  pip install yq"
    exit 1
fi

# ── 读取当前状态 ──
CURRENT_STATUS=$(yq eval '.status // "unknown"' "$MANIFEST_FILE")
log_info "当前状态: $CURRENT_STATUS → 目标状态: $TARGET_STATUS"

# ── 验证状态转换合法性 ──
validate_transition() {
    local from="$1"
    local to="$2"

    case "$from" in
        draft)
            [[ "$to" == "review" ]]
            ;;
        review)
            [[ "$to" == "published" ]]
            ;;
        published)
            [[ "$to" == "deprecated" ]]
            ;;
        *)
            return 1
            ;;
    esac
}

if ! validate_transition "$CURRENT_STATUS" "$TARGET_STATUS"; then
    log_error "不允许的状态转换: $CURRENT_STATUS → $TARGET_STATUS"
    log_error "允许的转换: draft→review, review→published, published→deprecated"
    if [[ "$FORCE" != "--force" ]]; then
        exit 1
    fi
    log_warn "已使用 --force，继续执行（风险自负）..."
fi

# ── 前置检查 ──
pre_checks() {
    case "$TARGET_STATUS" in
        review)
            log_info "执行 Review 前置检查..."
            # 检查 CHANGELOG 是否填写了 Unreleased 区
            if grep -q "## \[Unreleased\]" "$WORKSPACE_ROOT/CHANGELOG.md" 2>/dev/null; then
                log_ok "CHANGELOG.md 存在 [Unreleased] 区"
            else
                log_warn "CHANGELOG.md 缺少 [Unreleased] 区"
            fi
            log_ok "前置检查完成（draft→review 为轻量检查）"
            ;;
        published)
            log_info "执行 Published 前置检查..."
            # 检查 Git 工作区是否干净
            if ! git -C "$WORKSPACE_ROOT" diff --quiet --exit-code; then
                log_error "Git 工作区有未提交的修改。请在 published 前提交或 stash。"
                exit 1
            fi
            if ! git -C "$WORKSPACE_ROOT" diff --cached --quiet --exit-code; then
                log_error "Git 暂存区有未提交的修改。请在 published 前提交。"
                exit 1
            fi
            log_ok "Git 工作区干净"

            # 验证 active-release.yaml 中的版本号是否匹配
            ACTIVE_WF=$(yq eval '.active_release.workflow_version' "$WORKSPACE_ROOT/config/active-release.yaml")
            MANIFEST_WF=$(yq eval '.components.workflow_version' "$MANIFEST_FILE")
            if [[ "$ACTIVE_WF" != "$MANIFEST_WF" ]]; then
                log_warn "active-release.yaml 工作流版本 ($ACTIVE_WF) 与 manifest ($MANIFEST_WF) 不一致"
            else
                log_ok "active-release.yaml 版本与 manifest 一致"
            fi
            log_ok "Published 前置检查通过"
            ;;
        deprecated)
            log_info "Deprecated 无需前置检查"
            ;;
    esac
}

pre_checks

# ── 执行晋升 ──
execute_promote() {
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local actor="${USER:-system}"

    log_info "执行晋升: $CURRENT_STATUS → $TARGET_STATUS"

    # 更新 Manifest 文件中的 status 和 lifecycle
    # 使用 yq 原地更新
    yq eval -i ".status = \"$TARGET_STATUS\"" "$MANIFEST_FILE"
    yq eval -i ".updated_at = \"$timestamp\"" "$MANIFEST_FILE"

    # 添加 transition 记录
    TRANSITION_COUNT=$(yq eval '.lifecycle.transitions | length' "$MANIFEST_FILE")
    yq eval -i ".lifecycle.current_phase = \"$TARGET_STATUS\"" "$MANIFEST_FILE"
    yq eval -i ".lifecycle.transitions[$TRANSITION_COUNT].from = \"$CURRENT_STATUS\"" "$MANIFEST_FILE"
    yq eval -i ".lifecycle.transitions[$TRANSITION_COUNT].to = \"$TARGET_STATUS\"" "$MANIFEST_FILE"
    yq eval -i ".lifecycle.transitions[$TRANSITION_COUNT].timestamp = \"$timestamp\"" "$MANIFEST_FILE"
    yq eval -i ".lifecycle.transitions[$TRANSITION_COUNT].actor = \"$actor\"" "$MANIFEST_FILE"
    yq eval -i ".lifecycle.transitions[$TRANSITION_COUNT].reason = \"晋升 via release_promote.sh\"" "$MANIFEST_FILE"

    log_ok "Manifest 已更新: $MANIFEST_FILE"

    # ── 如果是 published，打 Git tag ──
    if [[ "$TARGET_STATUS" == "published" ]]; then
        local GIT_TAG="$RELEASE_ID"
        if git -C "$WORKSPACE_ROOT" tag --list | grep -q "^${GIT_TAG}$"; then
            log_warn "Git tag '$GIT_TAG' 已存在，跳过打 tag"
        else
            git -C "$WORKSPACE_ROOT" tag -a "$GIT_TAG" -m "Release $RELEASE_ID (published)"
            log_ok "Git tag 已创建: $GIT_TAG"

            # 更新 manifest 中的 git_tag
            yq eval -i ".git_tag = \"$GIT_TAG\"" "$MANIFEST_FILE"
            yq eval -i ".git_commit = \"$(git -C "$WORKSPACE_ROOT" rev-parse HEAD)\"" "$MANIFEST_FILE"
        fi

        # 更新 active-release.yaml 中的 release_id
        yq eval -i ".active_release.id = \"$RELEASE_ID\"" "$WORKSPACE_ROOT/config/active-release.yaml"
        yq eval -i ".active_release.status = \"published\"" "$WORKSPACE_ROOT/config/active-release.yaml"
        log_ok "active-release.yaml 已更新"
    fi

    # ── 如果是 review，不自动打 tag，但更新 active-release ──
    if [[ "$TARGET_STATUS" == "review" ]]; then
        yq eval -i ".active_release.id = \"$RELEASE_ID\"" "$WORKSPACE_ROOT/config/active-release.yaml"
        yq eval -i ".active_release.status = \"review\"" "$WORKSPACE_ROOT/config/active-release.yaml"
        log_ok "active-release.yaml 已同步为 review 状态"
    fi

    echo ""
    log_ok "晋升完成: $CURRENT_STATUS → $TARGET_STATUS"
    echo "    Release: $RELEASE_ID"
    echo "    Timestamp: $timestamp"
    echo "    Actor: $actor"
}

execute_promote
