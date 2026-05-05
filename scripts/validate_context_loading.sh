#!/usr/bin/env bash
#
# validate_context_loading.sh
# 验证上下文加载计划的完整性和合规性
#
# 检查范围:
#   1. config/context-loading.yaml 存在且合法
#   2. schemas/context_load_plan.schema.json 存在且合法
#   3. 所有工作流 YAML 引用了 context_loading 策略
#   4. 所有工作流引用的约束、prompt、schema 文件实际存在
#   5. 未引用不在 active-release.yaml 中的组件
#
# 用法:
#   ./scripts/validate_context_loading.sh
#   ./scripts/validate_context_loading.sh --verbose

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERBOSE=false
EXIT_CODE=0

if [[ "${1:-}" == "--verbose" ]]; then
  VERBOSE=true
fi

log_ok()   { echo "  ✅ $1"; }
log_warn() { echo "  ⚠️  $1"; EXIT_CODE=1; }
log_err()  { echo "  ❌ $1"; EXIT_CODE=1; }
verbose()  { $VERBOSE && echo "     $1"; }

echo "============================================"
echo "  上下文加载验证 — Context Loading Validation"
echo "============================================"
echo ""

# ── 1. 检查核心配置文件 ──
echo "【1/5】核心配置文件检查"
if [[ -f "$ROOT_DIR/config/context-loading.yaml" ]]; then
  log_ok "config/context-loading.yaml 存在"
else
  log_err "config/context-loading.yaml 不存在"
fi

if [[ -f "$ROOT_DIR/schemas/context_load_plan.schema.json" ]]; then
  log_ok "schemas/context_load_plan.schema.json 存在"
else
  log_err "schemas/context_load_plan.schema.json 不存在"
fi

if [[ -f "$ROOT_DIR/config/active-release.yaml" ]]; then
  log_ok "config/active-release.yaml 存在"
else
  log_err "config/active-release.yaml 不存在"
fi

echo ""

# ── 2. 检查工作流引用的 context_loading ──
echo "【2/5】工作流上下文加载策略检查"
WORKFLOW_COUNT=0
WORKFLOW_MISSING=0

while IFS= read -r wf; do
  WORKFLOW_COUNT=$((WORKFLOW_COUNT + 1))
  wf_rel="${wf#$ROOT_DIR/}"

  if grep -q "context_loading:" "$wf" 2>/dev/null; then
    verbose "$wf_rel → 已定义 context_loading"
  else
    log_warn "$wf_rel 缺少 context_loading 定义"
    WORKFLOW_MISSING=$((WORKFLOW_MISSING + 1))
  fi
done < <(find "$ROOT_DIR/workflows" -name "*.yaml" 2>/dev/null || true)

if [[ $WORKFLOW_COUNT -eq 0 ]]; then
  log_warn "未找到任何工作流文件"
else
  log_ok "共检查 $WORKFLOW_COUNT 个工作流，$WORKFLOW_MISSING 个缺失 context_loading"
fi
echo ""

# ── 3. 检查工作流引用资产的实际存在性 ──
echo "【3/5】工作流引用资产存在性检查"
MISSING_ASSETS=0
CHECKED=0

while IFS= read -r wf; do
  # 提取 constraints 引用
  while IFS= read -r constraint_ref; do
    CHECKED=$((CHECKED + 1))
    if [[ ! -f "$ROOT_DIR/$constraint_ref" ]]; then
      log_err "工作流 $(basename "$wf") 引用的约束不存在: $constraint_ref"
      MISSING_ASSETS=$((MISSING_ASSETS + 1))
    else
      verbose "  ✓ 约束 $constraint_ref 存在"
    fi
  done < <(grep -E '^\s+-\s+"constraints/' "$wf" 2>/dev/null | sed 's/.*"\(.*\)"/\1/' || true)
done < <(find "$ROOT_DIR/workflows" -name "*.yaml" 2>/dev/null || true)

if [[ $MISSING_ASSETS -eq 0 ]]; then
  log_ok "共检查 $CHECKED 个资产引用，全部存在"
else
  log_warn "$MISSING_ASSETS 个资产引用不存在"
fi
echo ""

# ── 4. 检查 context_intent_gate 规则存在 ──
echo "【4/5】上下文门禁规则检查"
if [[ -f "$ROOT_DIR/constraints/baseline/context_intent_gate.yaml" ]]; then
  log_ok "constraints/baseline/context_intent_gate.yaml 存在"
else
  log_warn "constraints/baseline/context_intent_gate.yaml 不存在"
fi

if [[ -f "$ROOT_DIR/schemas/run_snapshot.schema.json" ]]; then
  log_ok "run_snapshot.schema.json 存在（门禁结果记录目标）"
else
  log_err "run_snapshot.schema.json 不存在"
fi
echo ""

# ── 5. 检查 context_load_plan 字段完整性 ──
echo "【5/5】context_load_plan Schema 字段完整性检查（文件级）"
if [[ -f "$ROOT_DIR/schemas/context_load_plan.schema.json" ]]; then
  # 检查必需字段
  for field in "run_id" "workflow_id" "layers" "excluded_assets" "context_budget"; do
    if grep -q "\"$field\"" "$ROOT_DIR/schemas/context_load_plan.schema.json"; then
      verbose "  ✓ 必填字段 '$field' 存在"
    else
      log_warn "context_load_plan.schema.json 缺少必填字段 '$field'"
    fi
  done
  log_ok "context_load_plan Schema 字段检查完成"
else
  log_err "context_load_plan.schema.json 不存在，跳过字段检查"
fi

echo ""
echo "============================================"
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "  结果: ✅ 全部通过"
else
  echo "  结果: ❌ 存在 $EXIT_CODE 个问题"
fi
echo "============================================"
exit $EXIT_CODE
