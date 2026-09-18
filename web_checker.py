#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web版国家标准查询模块
适配Streamlit界面，支持实时进度回调
"""

import time
from datetime import timedelta
from typing import Callable, List, Optional

from core import (
  BaseStandardChecker,
  ProgressTracker,
  StandardResult,
  normalize_standard_nos,
  logger,
)


class WebStandardChecker(BaseStandardChecker):
  """Web版国家标准查询器"""

  def __init__(self, delay: float = 5.0, max_retries: int = 3, use_proxy: Optional[str] = None,
               progress_file: str = ".web_query_progress.pkl", timeout: float = 15.0,
               jitter_ratio: float = 0.5):
    super().__init__(
      delay=delay, max_retries=max_retries, use_proxy=use_proxy, timeout=timeout,
      jitter_ratio=jitter_ratio,
    )
    self.tracker = ProgressTracker(progress_file=progress_file)

  def query_batch_with_callback(
    self,
    standard_nos: List[str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
  ) -> List[StandardResult]:
    """
    带回调的批量查询

    Args:
      standard_nos: 标准号列表（自动 strip + 去重）
      progress_callback: 进度回调 (current, total, msg)
      log_callback: 日志回调 (msg)
      should_stop: 每条查询前调用，返回 True 则中止批次

    Returns:
      已完成的查询结果列表（StandardResult）
    """
    standard_nos = normalize_standard_nos(standard_nos)
    total = len(standard_nos)
    self.stats.reset()
    self.stats.start_time = time.time()

    if not standard_nos:
      return []

    for i, standard_no in enumerate(standard_nos, 1):
      if should_stop is not None and should_stop():
        if log_callback:
          log_callback("⏹️ 已取消，后续条目可重新点击开始继续")
        break

      elapsed = time.time() - self.stats.start_time
      avg_time = elapsed / i if i > 0 else 0
      remaining = total - i
      eta_str = str(timedelta(seconds=int(avg_time * remaining)))

      status_msg = f"[{i}/{total}] {standard_no} - ETA: {eta_str}"

      if progress_callback:
        progress_callback(i, total, status_msg)

      if log_callback:
        log_callback(f"正在查询: {standard_no}")

      result = self.query_single(standard_no, sleep_after=(i < total))

      if result.错误:
        if log_callback:
          log_callback(f"❌ {standard_no}: {result.错误}")
      else:
        self.tracker.mark_completed(standard_no, result)
        if log_callback:
          log_callback(f"✅ {standard_no}: {result.状态}")

    return [self.tracker.get_result(s) for s in standard_nos
            if self.tracker.is_completed(s)]
