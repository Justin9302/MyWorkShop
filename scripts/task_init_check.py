#!/usr/bin/env python3
"""
task_init_check.py — 任务启动检查脚本

在每次任务启动时运行，检查：
1. 是否已读取强制启动序列中的文件
2. 当前 release 版本和活跃组件
3. 待办检查项列表

用法：
    python scripts/task_init_check.py

输出：
    检查结果报告（JSON 格式），包含通过/失败状态和待办项
"""

import os
import sys
import json
from datetime import datetime

# 工作空间根目录
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 强制启动序列（与 config/context-loading.yaml 保持一致）
# 注意：docs/INDEX.md 是文档索引，按需查阅而非强制读取，不在此列表中
REQUIRED_STARTUP_FILES = [
    "docs/model_context.md",
    "config/active-release.yaml",
    "README.md",
    "docs/current_workspace_creation_plan.md",
    "constraints/baseline/context_intent_gate.yaml",
    "config/workspace_usage_guide.md",
]

# 检查清单（与 config/workspace_usage_guide.md 保持一致）
CHECKLIST_ITEMS = [
    {"id": "force_load", "description": "强制加载：已读 model_context.md、active-release.yaml、README.md、current_workspace_creation_plan.md、context_intent_gate.yaml？"},
    {"id": "step1_intent", "description": "第一步：理解意图 — 三个问题想清楚了吗？意图确认输出写了吗？"},
    {"id": "step2_industry", "description": "第二步：行业对齐 — 调研对标方案了吗？"},
    {"id": "step3_draft", "description": "第三步：输出初稿 — 目标80分，结构完整吗？"},
    {"id": "step4_confirm", "description": "第四步：主动确认 — 问对方\"是否符合预期\"了吗？"},
    {"id": "step5_iterate", "description": "第五步：优化迭代 — 是微调还是大改？"},
    {"id": "retrospective", "description": "复盘：任务完成后写复盘了吗？"},
    {"id": "index_update", "description": "索引更新：本次任务是否涉及新增/修改/废弃文档？INDEX.md 更新了吗？"},
    {"id": "header_sync", "description": "头部同步：本次任务是否修改了关键文件？头部简介同步更新了吗？"},
    {"id": "session_tracking", "description": "会话跟踪：更新 session-tracking.yaml 和 user_profile.md 了吗？"},
]


def check_file_exists(filepath):
    """检查文件是否存在"""
    full_path = os.path.join(WORKSPACE_ROOT, filepath)
    exists = os.path.isfile(full_path)
    return {
        "file": filepath,
        "exists": exists,
        "full_path": full_path,
    }


def parse_active_release():
    """解析 active-release.yaml 获取当前版本信息"""
    release_path = os.path.join(WORKSPACE_ROOT, "config/active-release.yaml")
    if not os.path.isfile(release_path):
        return {"error": "active-release.yaml not found"}

    release_info = {}
    try:
        import yaml
        with open(release_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "active_release" in data:
            ar = data["active_release"]
            release_info["id"] = ar.get("id", "unknown")
            release_info["status"] = ar.get("status", "unknown")
            release_info["stage"] = ar.get("stage", "unknown")
            release_info["workflow_version"] = ar.get("workflow_version", "unknown")
            release_info["constraint_pack_version"] = ar.get("constraint_pack_version", "unknown")
            release_info["prompt_version"] = ar.get("prompt_version", "unknown")
            release_info["evaluator_version"] = ar.get("evaluator_version", "unknown")
            release_info["lattice_version"] = ar.get("lattice_version", "unknown")
    except ImportError:
        release_info["error"] = "PyYAML not installed"
    except Exception as e:
        release_info["error"] = str(e)

    return release_info


def check_git_status():
    """检查 Git 状态"""
    git_info = {}
    try:
        import subprocess
        # 检查是否有未提交的更改
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=WORKSPACE_ROOT,
        )
        if result.returncode == 0:
            changes = result.stdout.strip()
            git_info["has_uncommitted_changes"] = bool(changes)
            git_info["uncommitted_count"] = len([l for l in changes.split("\n") if l.strip()]) if changes else 0
        else:
            git_info["error"] = "Not a git repository or git not available"

        # 获取当前分支
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True,
            cwd=WORKSPACE_ROOT,
        )
        if branch_result.returncode == 0:
            git_info["branch"] = branch_result.stdout.strip()

        # 获取最新 commit
        commit_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            cwd=WORKSPACE_ROOT,
        )
        if commit_result.returncode == 0:
            git_info["latest_commit"] = commit_result.stdout.strip()

    except Exception as e:
        git_info["error"] = str(e)

    return git_info


def check_mcp_config():
    """检查 MCP 配置状态"""
    mcp_path = os.path.join(WORKSPACE_ROOT, ".vscode/mcp.json")
    mcp_info = {"configured_servers": []}
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "mcpServers" in data:
                mcp_info["configured_servers"] = list(data["mcpServers"].keys())
        except Exception as e:
            mcp_info["error"] = str(e)
    else:
        mcp_info["error"] = ".vscode/mcp.json not found"
    return mcp_info


def run_check():
    """运行所有检查"""
    results = {
        "check_time": datetime.now().isoformat(),
        "workspace_root": WORKSPACE_ROOT,
        "status": "pass",
        "summary": {},
        "details": {},
        "checklist": [],
        "recommendations": [],
    }

    # 1. 检查强制启动文件
    file_checks = [check_file_exists(f) for f in REQUIRED_STARTUP_FILES]
    missing_files = [f for f in file_checks if not f["exists"]]
    results["details"]["startup_files"] = file_checks
    results["summary"]["startup_files"] = {
        "total": len(REQUIRED_STARTUP_FILES),
        "found": len(REQUIRED_STARTUP_FILES) - len(missing_files),
        "missing": len(missing_files),
    }
    if missing_files:
        results["status"] = "fail"
        results["recommendations"].append(
            f"缺少强制启动文件: {', '.join(f['file'] for f in missing_files)}"
        )

    # 2. 解析 active-release
    release_info = parse_active_release()
    results["details"]["active_release"] = release_info
    if "error" in release_info:
        results["recommendations"].append(f"无法解析 active-release: {release_info['error']}")

    # 3. 检查 Git 状态
    git_info = check_git_status()
    results["details"]["git_status"] = git_info
    if git_info.get("has_uncommitted_changes"):
        results["recommendations"].append(
            f"有 {git_info['uncommitted_count']} 个未提交的更改，建议先提交或暂存"
        )

    # 4. 检查 MCP 配置
    mcp_info = check_mcp_config()
    results["details"]["mcp_config"] = mcp_info

    # 5. 生成检查清单
    results["checklist"] = [
        {"id": item["id"], "description": item["description"], "checked": False}
        for item in CHECKLIST_ITEMS
    ]

    # 6. 生成摘要
    results["summary"]["release"] = release_info.get("id", "unknown")
    results["summary"]["branch"] = git_info.get("branch", "unknown")
    results["summary"]["latest_commit"] = git_info.get("latest_commit", "unknown")
    results["summary"]["mcp_servers"] = mcp_info.get("configured_servers", [])

    return results


def print_report(results):
    """打印可读的报告"""
    print("=" * 60)
    print(f"  Workspace 启动检查报告")
    print(f"  检查时间: {results['check_time']}")
    print("=" * 60)

    # 状态
    status_icon = "✅" if results["status"] == "pass" else "⚠️"
    print(f"\n{status_icon} 整体状态: {results['status'].upper()}")

    # Release 信息
    release = results["summary"]
    print(f"\n📦 Release: {release['release']}")
    print(f"   Branch: {release['branch']}")
    print(f"   Commit: {release['latest_commit']}")
    print(f"   MCP Servers: {', '.join(release['mcp_servers']) if release['mcp_servers'] else 'None configured'}")

    # 启动文件
    sf = results["summary"]["startup_files"]
    print(f"\n📋 启动文件: {sf['found']}/{sf['total']} 已找到")
    for f in results["details"]["startup_files"]:
        icon = "✅" if f["exists"] else "❌"
        print(f"   {icon} {f['file']}")

    # 检查清单
    print(f"\n📝 检查清单（请逐项确认）:")
    for item in results["checklist"]:
        print(f"   □ {item['description']}")

    # 建议
    if results["recommendations"]:
        print(f"\n💡 建议:")
        for r in results["recommendations"]:
            print(f"   • {r}")

    print("\n" + "=" * 60)


def main():
    """主入口"""
    results = run_check()

    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_report(results)

    # 返回非零退出码表示检查失败
    return 0 if results["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
