#!/bin/bash
#=============================================================================
# run_all_tests.sh — 统一测试运行入口
#
# 功能：按阶段顺序运行所有测试，汇总测试结果，生成测试报告。
#       支持指定阶段运行、跳过特定阶段、仅生成报告等模式。
#
# 用法：
#   ./scripts/run_all_tests.sh              # 运行所有测试
#   ./scripts/run_all_tests.sh --phase 7a   # 仅运行 phase7a 测试
#   ./scripts/run_all_tests.sh --skip 7e    # 跳过 phase7e
#   ./scripts/run_all_tests.sh --report     # 仅生成报告（不运行测试）
#   ./scripts/run_all_tests.sh --help       # 显示帮助
#
# 关联：
#   - tests/phase7a/  — LLM-as-Judge 评估引擎测试
#   - tests/phase7b/  — 动态评估集管理测试
#   - tests/phase7c/  — 候选变更管线测试
#   - tests/phase7d/  — 沙箱回归测试
#   - tests/phase7e/  — 灰度发布管理测试
#   - tests/phase7f/  — 质量仪表盘测试
#   - tests/phase8/   — 工作流编排引擎测试
#   - tests/phase9/   — 中断处理与恢复测试
#   - scripts/regression_test.py — 回归测试
#=============================================================================

set -e

# ── 配置 ──
REPORT_DIR="outputs/test_reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="${REPORT_DIR}/test_report_${TIMESTAMP}.md"
SUMMARY_FILE="${REPORT_DIR}/test_summary_${TIMESTAMP}.json"
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_TESTS=()

# 阶段定义：名称 -> 目录/命令
declare -A PHASES
PHASES["phase7a"]="tests/phase7a"
PHASES["phase7b"]="tests/phase7b"
PHASES["phase7c"]="tests/phase7c"
PHASES["phase7d"]="tests/phase7d"
PHASES["phase7e"]="tests/phase7e"
PHASES["phase7f"]="tests/phase7f"
PHASES["phase8"]="tests/phase8"
PHASES["phase9"]="tests/phase9"
PHASES["regression"]="regression"

# 阶段顺序
PHASE_ORDER=("phase7a" "phase7b" "phase7c" "phase7d" "phase7e" "phase7f" "phase8" "phase9" "regression")

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 帮助 ──
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --phase <name>   仅运行指定阶段（如 7a, 7b, ... 9, regression）"
    echo "  --skip <name>    跳过指定阶段"
    echo "  --report         仅生成报告（不运行测试）"
    echo "  --help           显示此帮助"
    echo ""
    echo "可用阶段:"
    for phase in "${PHASE_ORDER[@]}"; do
        echo "  - ${phase} (${PHASES[$phase]})"
    done
    exit 0
}

# ── 参数解析 ──
RUN_ALL=true
RUN_ONLY=""
SKIP_PHASES=()
REPORT_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)
            RUN_ALL=false
            RUN_ONLY="$2"
            shift 2
            ;;
        --skip)
            SKIP_PHASES+=("$2")
            shift 2
            ;;
        --report)
            REPORT_ONLY=true
            shift
            ;;
        --help)
            show_help
            ;;
        *)
            echo "未知选项: $1"
            show_help
            ;;
    esac
done

# ── 初始化报告目录 ──
mkdir -p "${REPORT_DIR}"

# ── 运行单个阶段的测试 ──
run_phase() {
    local phase_name=$1
    local phase_target=$2

    # 检查是否被跳过
    for skip in "${SKIP_PHASES[@]}"; do
        if [[ "$skip" == "$phase_name" ]]; then
            echo -e "${YELLOW}⏭️  跳过 ${phase_name}${NC}"
            SKIP_COUNT=$((SKIP_COUNT + 1))
            return 0
        fi
    done

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  运行测试阶段: ${phase_name}${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

    local start_time=$(date +%s)

    if [[ "$phase_target" == "regression" ]]; then
        # 回归测试使用专用脚本
        echo "运行回归测试..."
        if python3 scripts/regression_test.py 2>&1; then
            local duration=$(( $(date +%s) - start_time ))
            echo -e "${GREEN}✅ ${phase_name} 通过 (${duration}s)${NC}"
            PASS_COUNT=$((PASS_COUNT + 1))
            return 0
        else
            local duration=$(( $(date +%s) - start_time ))
            echo -e "${RED}❌ ${phase_name} 失败 (${duration}s)${NC}"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            FAILED_TESTS+=("${phase_name}")
            return 1
        fi
    else
        # 标准 pytest 测试
        if python3 -m pytest "${phase_target}" -v --tb=short 2>&1; then
            local duration=$(( $(date +%s) - start_time ))
            echo -e "${GREEN}✅ ${phase_name} 通过 (${duration}s)${NC}"
            PASS_COUNT=$((PASS_COUNT + 1))
            return 0
        else
            local duration=$(( $(date +%s) - start_time ))
            echo -e "${RED}❌ ${phase_name} 失败 (${duration}s)${NC}"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            FAILED_TESTS+=("${phase_name}")
            return 1
        fi
    fi
}

# ── 生成报告 ──
generate_report() {
    local total=$((PASS_COUNT + FAIL_COUNT + SKIP_COUNT))
    local pass_rate=0
    if [[ $total -gt 0 ]]; then
        pass_rate=$(( (PASS_COUNT * 100) / total ))
    fi

    cat > "${REPORT_FILE}" << EOF
# 测试报告

**日期:** $(date +"%Y-%m-%d %H:%M:%S")
**Git 提交:** $(git rev-parse HEAD 2>/dev/null || echo "N/A")
**Release:** $(grep 'id:' config/active-release.yaml | head -1 | awk '{print $2}')

---

## 汇总

| 指标 | 数值 |
|------|------|
| 总计 | ${total} |
| 通过 | ${PASS_COUNT} |
| 失败 | ${FAIL_COUNT} |
| 跳过 | ${SKIP_COUNT} |
| 通过率 | ${pass_rate}% |

EOF

    if [[ ${#FAILED_TESTS[@]} -gt 0 ]]; then
        echo "## 失败的测试阶段" >> "${REPORT_FILE}"
        for failed in "${FAILED_TESTS[@]}"; do
            echo "- ❌ ${failed}" >> "${REPORT_FILE}"
        done
        echo "" >> "${REPORT_FILE}"
    fi

    echo "## 各阶段详情" >> "${REPORT_FILE}"
    for phase in "${PHASE_ORDER[@]}"; do
        local target="${PHASES[$phase]}"
        echo "- ${phase} (${target})" >> "${REPORT_FILE}"
    done

    echo "" >> "${REPORT_FILE}"
    echo "---" >> "${REPORT_FILE}"
    echo "_报告由 run_all_tests.sh 自动生成_" >> "${REPORT_FILE}"

    # 生成 JSON 摘要
    cat > "${SUMMARY_FILE}" << EOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "git_commit": "$(git rev-parse HEAD 2>/dev/null || echo "N/A")",
  "total": ${total},
  "passed": ${PASS_COUNT},
  "failed": ${FAIL_COUNT},
  "skipped": ${SKIP_COUNT},
  "pass_rate": ${pass_rate},
  "failed_tests": [$(for f in "${FAILED_TESTS[@]}"; do echo "\"${f}\","; done | sed 's/,$//')]
}
EOF

    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  报告已生成:${NC}"
    echo -e "  ${REPORT_FILE}"
    echo -e "  ${SUMMARY_FILE}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
}

# ── 主流程 ──
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           Workspace_1 统一测试运行入口                      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ "$REPORT_ONLY" == true ]]; then
    echo "仅生成报告模式..."
    generate_report
    exit 0
fi

# 运行测试
if [[ "$RUN_ALL" == true ]]; then
    for phase in "${PHASE_ORDER[@]}"; do
        run_phase "${phase}" "${PHASES[$phase]}"
    done
else
    # 仅运行指定阶段
    for phase in "${PHASE_ORDER[@]}"; do
        if [[ "$phase" == "$RUN_ONLY" ]]; then
            run_phase "${phase}" "${PHASES[$phase]}"
        fi
    done
fi

# 生成报告
generate_report

# 输出最终结果
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "  测试结果:"
echo -e "  ✅ 通过: ${PASS_COUNT}"
echo -e "  ❌ 失败: ${FAIL_COUNT}"
echo -e "  ⏭️  跳过: ${SKIP_COUNT}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

# 如果有失败，返回非零退出码
if [[ $FAIL_COUNT -gt 0 ]]; then
    exit 1
fi

exit 0
