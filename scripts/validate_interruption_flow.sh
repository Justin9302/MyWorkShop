#!/usr/bin/env bash
#
# validate_interruption_flow.sh
# Phase 9: 验证中断与恢复机制的完整性和合规性
#
# 检查范围:
#   1. config/interruption-policy.yaml 存在且合法
#   2. schemas/interruption_event.schema.json 存在且合法
#   3. scripts/interruption_handler.py 存在且语法正确
#   4. 所有工作流 YAML 定义了中断节点
#   5. 所有中断节点包含 pause_reason、resume_condition、cancel_condition、audit_fields
#   6. 所有中断类型符合 policy 定义
#   7. 运行时快照包含中断字段
#   8. Checkpoint 目录存在
#   9. 中断处理脚本 CLI 子命令可用
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
echo "  中断流程验证 — Phase 9"
echo "  Interruption Flow Validation"
echo "============================================"
echo ""

# ── 1. 检查核心配置文件 ──
echo "【1/9】核心配置文件检查"
if [[ -f "$ROOT_DIR/config/interruption-policy.yaml" ]]; then
  log_ok "config/interruption-policy.yaml 存在"
  # 检查版本
  if grep -q "version: \"0.2.0\"" "$ROOT_DIR/config/interruption-policy.yaml" 2>/dev/null; then
    log_ok "  interruption-policy.yaml 版本 0.2.0 (Phase 9)"
  fi
else
  log_err "config/interruption-policy.yaml 不存在"
fi

if [[ -f "$ROOT_DIR/schemas/interruption_event.schema.json" ]]; then
  log_ok "schemas/interruption_event.schema.json 存在"
else
  log_err "schemas/interruption_event.schema.json 不存在"
fi

# 检查 human_review.yaml 包含中断触发规则
if grep -q "interruption_trigger: true" "$ROOT_DIR/constraints/baseline/human_review.yaml" 2>/dev/null; then
  log_ok "constraints/baseline/human_review.yaml 包含中断触发规则"
else
  log_warn "constraints/baseline/human_review.yaml 缺少中断触发规则"
fi
echo ""

# ── 2. 检查中断处理脚本 ──
echo "【2/9】中断处理脚本检查"
if [[ -f "$ROOT_DIR/scripts/interruption_handler.py" ]]; then
  log_ok "scripts/interruption_handler.py 存在"
  # 语法检查
  if python3 -c "import ast; ast.parse(open('$ROOT_DIR/scripts/interruption_handler.py').read())" 2>/dev/null; then
    log_ok "  Python 语法正确"
  else
    log_err "  Python 语法错误"
  fi
  # 检查关键函数
  for func in "create_interruption" "process_resume_event" "validate_resume" "create_checkpoint" "update_snapshot_with_interruption" "extract_structured_patch"; do
    if grep -q "def $func" "$ROOT_DIR/scripts/interruption_handler.py" 2>/dev/null; then
      verbose "  ✓ 函数 $func 已定义"
    else
      log_warn "  函数 $func 未定义"
    fi
  done
  # 检查 CLI 子命令
  for cmd in "create-interruption" "process-resume" "validate-resume" "create-checkpoint" "update-snapshot"; do
    if grep -q "\"$cmd\"" "$ROOT_DIR/scripts/interruption_handler.py" 2>/dev/null; then
      verbose "  ✓ CLI 子命令 $cmd 已定义"
    else
      log_warn "  CLI 子命令 $cmd 未定义"
    fi
  done
else
  log_err "scripts/interruption_handler.py 不存在"
fi
echo ""

# ── 3. 检查 workflow_runner.py 中断/恢复子命令 ──
echo "【3/9】workflow_runner.py 中断/恢复子命令检查"
if [[ -f "$ROOT_DIR/scripts/workflow_runner.py" ]]; then
  for cmd in "interrupt" "resume" "checkpoint"; do
    if grep -q "subparsers.add_parser(\"$cmd\"" "$ROOT_DIR/scripts/workflow_runner.py" 2>/dev/null; then
      log_ok "  workflow_runner.py 包含 '$cmd' 子命令"
    else
      log_warn "  workflow_runner.py 缺少 '$cmd' 子命令"
    fi
  done
else
  log_err "scripts/workflow_runner.py 不存在"
fi
echo ""

# ── 4. 检查工作流中断节点定义 ──
echo "【4/9】工作流中断节点检查"
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

# ── 5. 检查中断节点字段完整性 ──
echo "【5/9】中断节点字段完整性检查"
NODE_TOTAL=0
NODE_MISSING=0

while IFS= read -r wf; do
  wf_rel="${wf#$ROOT_DIR/}"

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
      if [[ "$line" =~ ^[a-z] ]] && ! [[ "$line" =~ ^[[:space:]]+- ]]; then
        break
      fi

      if [[ "$line" =~ ^[[:space:]]+-[[:space:]]node_id: ]]; then
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

# ── 6. 检查中断类型合法性 ──
echo "【6/9】中断类型合法性检查"
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

# ── 7. 检查运行时快照是否包含中断字段 ──
echo "【7/9】运行时快照中断字段检查"
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

# ── 8. 检查 Checkpoint 和中断运行时目录 ──
echo "【8/9】运行时目录检查"
for dir in "runtime/checkpoints" "runtime/interruptions"; do
  if [[ -d "$ROOT_DIR/$dir" ]]; then
    log_ok "$dir 目录存在"
  else
    log_warn "$dir 目录不存在 (将在首次运行时自动创建)"
  fi
done
echo ""

# ── 9. 检查中断处理脚本 CLI 可用性 ──
echo "【9/9】中断处理脚本 CLI 可用性检查"
if python3 "$ROOT_DIR/scripts/interruption_handler.py" --help >/dev/null 2>&1; then
  log_ok "interruption_handler.py CLI 可用"
  # 检查子命令
  for cmd in "create-interruption" "process-resume" "validate-resume" "create-checkpoint" "update-snapshot"; do
    if python3 "$ROOT_DIR/scripts/interruption_handler.py" "$cmd" --help >/dev/null 2>&1; then
      verbose "  ✓ 子命令 '$cmd' 可用"
    else
      log_warn "  子命令 '$cmd' 不可用"
    fi
  done
else
  log_err "interruption_handler.py CLI 不可用"
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
