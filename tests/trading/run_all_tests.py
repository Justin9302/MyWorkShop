#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易策略层全面测试套件

运行方式：
    python3 tests/trading/run_all_tests.py

测试覆盖：
  - 5 个策略模块（solar, wind, bess, hybrid, wind_bess）
  - 每个模块 5-8 个测试用例
  - 总计 30+ 个测试用例

测试维度：
  ✅ 基本功能验证
  ✅ 边界条件（零容量、零电价、无套利空间）
  ✅ 负电价场景（弃电 + 电网充电）
  ✅ 效率影响（RTE 对结果的影响）
  ✅ SOC 边界限制
  ✅ 年化逻辑验证（典型日 × 365）
  ✅ 多次运行一致性
  ✅ 参数敏感性（储能时长、充放电阈值）
"""

import sys
import time
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 导入所有测试模块
from tests.trading import (
    test_solar_strategy,
    test_wind_strategy,
    test_bess_strategy,
    test_hybrid_strategy,
    test_wind_bess_strategy,
)


def run_test_module(module, name):
    """运行一个测试模块中的所有 test_ 开头的函数"""
    print(f"\n{'=' * 55}")
    print(f"  {name}")
    print(f"{'=' * 55}")

    test_functions = [
        func for func in dir(module)
        if func.startswith("test_") and callable(getattr(module, func))
    ]

    passed = 0
    failed = 0
    for func_name in test_functions:
        func = getattr(module, func_name)
        try:
            func()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {func_name} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {func_name} 异常: {e}")
            failed += 1

    return passed, failed


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        交易策略层全面测试套件                                ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    modules = [
        (test_solar_strategy, "光伏交易策略 (solar_strategy)"),
        (test_wind_strategy, "风电交易策略 (wind_strategy)"),
        (test_bess_strategy, "BESS 交易策略 (bess_strategy)"),
        (test_hybrid_strategy, "光储混合交易策略 (hybrid_strategy)"),
        (test_wind_bess_strategy, "风储混合交易策略 (wind_bess_strategy)"),
    ]

    total_passed = 0
    total_failed = 0
    start_time = time.time()

    for module, name in modules:
        passed, failed = run_test_module(module, name)
        total_passed += passed
        total_failed += failed

    elapsed = time.time() - start_time

    print(f"\n{'=' * 55}")
    print(f"  测试完成")
    print(f"{'=' * 55}")
    print(f"  总测试数: {total_passed + total_failed}")
    print(f"  通过: {total_passed} ✅")
    print(f"  失败: {total_failed} {'❌' if total_failed > 0 else '✅'}")
    print(f"  耗时: {elapsed:.2f} 秒")

    if total_failed > 0:
        print("\n⚠️  存在失败的测试，请检查以上输出。")
        sys.exit(1)
    else:
        print("\n🎉 所有测试通过！")


if __name__ == "__main__":
    main()
