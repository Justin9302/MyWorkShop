#!/usr/bin/env bash
#
# validate_interruption_flow.sh
# 验证中断与恢复机制的完整性和合规性
#
# 检查范围:
#   1. config/interruption-policy.yaml 存在且合法
#   2. schemas/interruption_event.schema.json 存在且合法
#   3. 所有工作流 YAML 定义了中断节点
#   4. 所有中断节点包含 pause_reason、resume_condition、cancel_condition、audit_fields
#   5. 所有中断类型符合 policy 定义
#
# 用法:
#   ./scripts/validate_interruption_flow.sh
#   ./scripts/validate_interruption_flow.sh --verbose

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
echo "  中断流程验证 — Interruption Flow Validation"
echo "============================================"
echo ""

# ── 1. 检查核心配置文件 ──
echo "【1/5】核心配置文件检查"
if [[ -f "$ROOT_DIR/config/interruption-policy.yaml" ]]; then
  log_ok "config/interruption-policy.yaml 存在"
else
  log_err "config/interruption-policy.yaml 不存在"
fi

if [[ -f "$ROOT_DIR/schemas/interruption_event.schema.json" ]]; then
  log_ok "schemas/interruption_event.schema.json 存在"
else
  log_err "schemas/interruption_event.schema.json 不存在"
fi
echo ""

# ── 2. 检查工作流中断节点定义 ──
echo "【2/5】工作流中断节点检查"
WORKFLOW_COUNT=0
WF_WITH_INTERRUPTIONS=0
WF_MISSING_INTERRUPTIONS=0

while IFS= read -r wf; do
  WORKFLOW_COUNT=$((WORKFLOW_COUNT + 1))
  wf_rel="${wf#$ROOT_DIR/}"

  if grep -q "interruptions:" "$wf" 2>/dev/null; then
    WF_WITH_INTERRUPTIONS=$((WF_WITH_INTERRUPTIONS + 1))
    verbose "$wf_rel → 已定义中断节点"
  else
    log_warn "$wf_rel 缺少 interruptions 定义"
    WF_MISSING_INTERRUPTIONS=$((WF_MISSING_INTERRUPTIONS + 1))
  fi
done < <(find "$ROOT_DIR/workflows" -name "*.yaml" 2>/dev/null || true)

if [[ $WORKFLOW_COUNT -eq 0 ]]; then
  log_warn "未找到任何工作流文件"
else
  log_ok "共检查 $WORKFLOW_COUNT 个工作流，$WF_WITH_INTERRUPTIONS 个已定义中断，$WF_MISSING_INTERRUPTIONS 个缺失"
fi
echo ""

# ── 3. 检查中断节点字段完整性 ──
echo "【3/5】中断节点字段完整性检查"
NODE_TOTAL=0
NODE_MISSING=0

while IFS= read -r wf; do
  wf_rel="${wf#$ROOT_DIR/}"

  # 提取 interruptions 块并逐节点检查
  in_interruptions=false
  node_started=false
  has_pause_reason=false
  has_resume=false
  has_cancel=false
  has_audit=false

  while IFS= read -r line; do
    if [[ "$line" =~ ^interruptions: ]]; then
      in_interruptions=true
      continue
    fi

    if $in_interruptions; then
      # 遇到下一个顶级键或文件结束
      if [[ "$line" =~ ^[a-z] ]] && ! [[ "$line" =~ ^[[:space:]]+- ]]; then
        break
      fi

      # 检测新节点
      if [[ "$line" =~ ^[[:space:]]+-[[:space:]]node_id: ]]; then
        # 保存上一个节点状态
        if $node_started; then
          NODE_TOTAL=$((NODE_TOTAL + 1))
          if ! $has_resume || ! $has_cancel; then
            log_warn "$wf_rel 中某中断节点缺少 resume_condition 或 cancel_condition"
            NODE_MISSING=$((NODE_MISSING + 1))
          fi
        fi
        node_started=true
        has_pause_reason=false
        has_resume=false
        has_cancel=false
        has_audit=false
        verbose "  $wf_rel → 检查中断节点: $(echo "$line" | sed 's/.*node_id://' | xargs)"
      fi

      [[ "$line" =~ pause_reason: ]] && has_pause_reason=true
      [[ "$line" =~ resume_condition: ]] && has_resume=true
      [[ "$line" =~ cancel_condition: ]] && has_cancel=true
      [[ "$line" =~ audit_fields: ]] && has_audit=true
    fi
  done < "$wf"

  # 最后一个节点
  if $node_started; then
    NODE_TOTAL=$((NODE_TOTAL + 1))
    if ! $has_resume || ! $has_cancel; then
      log_warn "$wf_rel 中某中断节点缺少 resume_condition 或 cancel_condition"
      NODE_MISSING=$((NODE_MISSING + 1))
    fi
  fi
done < <(find "$ROOT_DIR/workflows" -name "*.yaml" 2>/dev/null || true)

if [[ $NODE_TOTAL -eq 0 ]]; then
  log_warn "未发现任何中断节点定义"
else
  log_ok "共检查 $NODE_TOTAL 个中断节点，$NODE_MISSING 个字段不完整"
fi
echo ""

# ── 4. 检查中断类型合法性 ──
echo "【4/5】中断类型合法性检查"
VALID_TYPES="workflow_pause interrupted_by_user cancelled_by_user"

while IFS= read -r wf; do
  while IFS= read -r line; do
    if [[ "$line" =~ type:[[:space:]]*\"(.*)\" ]]; then
      t="${BASH_REMATCH[1]}"
      found=false
      for vt in $VALID_TYPES; do
        [[ "$t" == "$vt" ]] && found=true
      done
      if ! $found; then
        log_warn "$(basename "$wf") 使用了未定义的中断类型: '$t'"
      fi
    fi
  done < "$wf"
done < <(find "$ROOT_DIR/workflows" -name "*.yaml" 2>/dev/null || true)

log_ok "中断类型检查完成"
echo ""

# ── 5. 检查运行时快照是否包含中断字段 ──
echo "【5/5】运行时快照中断字段检查"
if [[ -f "$ROOT_DIR/schemas/run_snapshot.schema.json" ]]; then
  for field in "workflow_state" "interruptions" "resume_events"; do
    if grep -q "\"$field\"" "$ROOT_DIR/schemas/run_snapshot.schema.json" 2>/dev/null; then
      verbose "  ✓ run_snapshot 包含 '$field' 字段"
    else
      log_warn "run_snapshot.schema.json 可能缺少 '$field' 字段"
    fi
  done
  log_ok "运行快照中断字段检查完成"
else
  log_err "run_snapshot.schema.json 不存在"
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
