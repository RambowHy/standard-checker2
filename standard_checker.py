#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准状态查询工具 - CLI版
功能：查询国家标准在 ndls.org.cn 的现行有效性及替代信息
作者：RambowHy
版本：3.0 - 重构版，消除代码重复，修复已知问题
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

import pandas as pd

from core import (
  BaseStandardChecker,
  BatchOutcome,
  ProgressTracker,
  normalize_standard_nos,
  logger,
)

FORMAT = "%(message)s"


def setup_logging():
  handler = logging.StreamHandler(sys.stderr)
  handler.setFormatter(logging.Formatter(FORMAT))
  logger.addHandler(handler)
  logger.setLevel(logging.INFO)


class StandardChecker(BaseStandardChecker):
  """CLI版国家标准查询器"""

  def query_batch(self, standard_nos: list, tracker: ProgressTracker = None,
                  resume: bool = True, recovery_wait: float = 60.0) -> BatchOutcome:
    """批量查询（含熔断与限流补查），返回 BatchOutcome"""
    standard_nos = normalize_standard_nos(standard_nos)
    logger.info("\n开始查询 %d 个标准...", len(standard_nos))
    logger.info("查询间隔: %.1f秒 | 最大重试: %d次 | 限流冷却: %.0f秒",
                self.delay, self.max_retries, 60)
    logger.info("-" * 100)

    def on_progress(idx, total, no):
      elapsed = _now() - self.stats.start_time
      avg_time = elapsed / idx if idx > 0 else 0
      eta_str = str(timedelta(seconds=int(avg_time * (total - idx))))
      logger.info("[%3d/%d] [%-25s] ETA: %s", idx, total, no, eta_str)

    outcome = self._run_recovery_batch(
      standard_nos, tracker, resume=resume, recovery_wait=recovery_wait,
      on_progress=on_progress, on_log=logger.info,
    )

    logger.info("-" * 100)
    self._print_stats(len(standard_nos), outcome)
    return outcome

  def update_excel(self, input_file: str, output_file: str = None,
                   resume: bool = True, clear_progress: bool = False,
                   recovery_wait: float = 60.0):
    """
    更新Excel文件

    Args:
      input_file: 输入Excel文件路径
      output_file: 输出文件路径（默认覆盖原文件）
      resume: 是否启用断点续传
      clear_progress: 是否清除进度重新开始
    """
    if output_file is None:
      output_file = input_file

    progress_file = f"{input_file}.progress.pkl"
    tracker = ProgressTracker(progress_file)

    if clear_progress:
      tracker.clear()

    try:
      logger.info("\n读取文件: %s", input_file)
      df = pd.read_excel(input_file)
      logger.info("数据行数: %d", len(df))

      for col in ['ndls状态', 'ndls查询时间', '替代标准号', '替代标准名']:
        if col not in df.columns:
          df[col] = ''
        else:
          # 预存的空输出列可能被读成 float64，统一转文本否则赋空串会报 TypeError
          df[col] = df[col].astype('object').where(df[col].notna(), '')

      raw_nos = df['标准号'].dropna().astype(str).tolist()
      standard_nos = normalize_standard_nos(raw_nos)
      df['标准号'] = df['标准号'].dropna().astype(str).map(str.strip)
      outcome = self.query_batch(standard_nos, tracker=tracker, resume=resume,
                                 recovery_wait=recovery_wait)

      now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      result_map = {r.标准号: r for r in outcome.results}
      failure_map = dict(outcome.failures)
      matched = df['标准号'].isin(set(result_map) | set(failure_map))
      for idx in df[matched].index:
        no = df.at[idx, '标准号']
        if no in result_map:
          result = result_map[no]
          df.at[idx, 'ndls状态'] = result.错误 or result.状态 or ""
          df.at[idx, '替代标准号'] = result.替代标准号
          df.at[idx, '替代标准名'] = result.替代标准名
        else:
          df.at[idx, 'ndls状态'] = failure_map[no]
        df.at[idx, 'ndls查询时间'] = now_str

      output_dir = os.path.dirname(os.path.abspath(output_file))
      fd, tmp_path = tempfile.mkstemp(suffix=".xlsx", dir=output_dir)
      os.close(fd)
      df.to_excel(tmp_path, index=False)
      os.replace(tmp_path, output_file)
      logger.info("\n结果已保存: %s", output_file)

      logger.info("\n状态统计:")
      logger.info(df['ndls状态'].value_counts().to_string())

      replaced_count = len(df[df['替代标准号'] != ''])
      if replaced_count > 0:
        logger.info("\n发现 %d 个有替代标准的记录", replaced_count)

      remaining = len(standard_nos) - tracker.completed_count()
      if remaining == 0:
        tracker.clear()
        logger.info("\n[完成] 所有数据查询完毕，进度文件已清理")
      elif outcome.cancelled:
        logger.info("\n[取消] 已完成进度已保存，可重新运行续查剩余 %d 条", remaining)
      else:
        logger.info("\n[提示] 还有 %d 条未查询（多为限流），可重新运行续查", remaining)

    except FileNotFoundError:
      logger.error("错误: 找不到文件 '%s'", input_file)
      sys.exit(1)
    except Exception as e:
      logger.error("错误: %s", e)
      import traceback
      traceback.print_exc()
      sys.exit(1)

  def _print_stats(self, total: int, outcome: BatchOutcome = None):
    if self.stats.start_time is None:
      return
    total_time = _now() - self.stats.start_time
    logger.info("\n查询统计:")
    logger.info("  总计: %d 条", total)
    logger.info("  成功: %d 条", self.stats.success)
    fail_count = self.stats.failed
    if outcome is not None:
      rate_fail = len(outcome.rate_limited)
      fail_count = len(outcome.failures)
      logger.info("  失败: %d 条（其中限流未完成 %d 条，可重跑续查）", fail_count, rate_fail)
      if outcome.cancelled:
        logger.info("  状态: 已取消")
    else:
      logger.info("  失败: %d 条", fail_count)
    logger.info("  限流触发: %d 次", self.stats.rate_limited)
    logger.info("  耗时: %s", timedelta(seconds=int(total_time)))


def _now() -> float:
  return time.time()


def main():
  setup_logging()

  parser = argparse.ArgumentParser(
    description='国家标准状态查询工具 v3.0 - 支持大批量查询和断点续传',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
使用示例:
  # 查询单个标准
  python standard_checker.py -s "GB 2757-2012"

  # 批量查询（默认间隔5秒）
  python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"

  # 更新Excel文件（推荐间隔3-5秒）
  python standard_checker.py -f standards.xlsx -d 5.0

  # 清除进度重新开始
  python standard_checker.py -f standards.xlsx --clear-progress

  # 使用代理
  python standard_checker.py -f standards.xlsx --proxy http://127.0.0.1:7890

  # 300条数据推荐配置
  python standard_checker.py -f standards.xlsx -d 5.0 -o output.xlsx

说明:
  - 程序自动保存进度，中断后可重新运行继续查询
  - 进度文件保存在输入文件同目录（.progress.pkl）
  - 遇到限流会长冷却重试（约60/120/180秒），连续限流自动熔断并在当轮慢速补查一次
  - 仍未完成的条目结果标注“限流，未完成，请重新运行续查”，重跑自动续查
  - 实际查询间隔在 delay 基础上随机抖动（默认±50%），避免固定频率触发限流
        """
  )

  parser.add_argument('-s', '--standards', nargs='+', help='要查询的标准号列表（空格分隔）')
  parser.add_argument('-f', '--file', help='Excel文件路径（将更新文件中的状态列）')
  parser.add_argument('-o', '--output', help='输出文件路径（默认覆盖原文件）')
  parser.add_argument('-d', '--delay', type=float, default=5.0, help='查询间隔（秒），默认5.0，建议3-5秒')
  parser.add_argument('--jitter-ratio', type=float, default=0.5,
                      help='间隔随机抖动比例，默认0.5（实际间隔为delay的0.5-1.5倍），设0为固定间隔')
  parser.add_argument('--clear-progress', action='store_true', help='清除进度重新开始')
  parser.add_argument('--proxy', help='代理地址，如 http://127.0.0.1:7890')
  parser.add_argument('--no-resume', action='store_true', help='禁用断点续传（默认启用）')

  args = parser.parse_args()

  if not args.standards and not args.file:
    parser.print_help()
    sys.exit(0)

  checker = StandardChecker(
    delay=args.delay, use_proxy=args.proxy, jitter_ratio=args.jitter_ratio,
  )

  if args.file:
    checker.update_excel(
      args.file,
      args.output,
      resume=not args.no_resume,
      clear_progress=args.clear_progress,
    )
  else:
    outcome = checker.query_batch(args.standards)
    rows = outcome.results + outcome.failure_results

    logger.info("\n查询结果:")
    logger.info("=" * 100)
    logger.info("%-25s %-20s %s", "标准号", "状态", "替代标准")
    logger.info("-" * 100)
    for r in rows:
      logger.info("%-25s %-20s %s", r.标准号, r.错误 or r.状态 or "", r.替代标准号)
    logger.info("=" * 100)


if __name__ == "__main__":
  main()
