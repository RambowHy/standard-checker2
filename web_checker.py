#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web版国家标准查询模块
适配Streamlit界面，支持实时进度回调、取消、限流熔断与补查
"""

from datetime import timedelta
from typing import Callable, List, Optional

from core import (
  BaseStandardChecker,
  BatchOutcome,
  ProgressTracker,
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
  ) -> BatchOutcome:
    """
    带回调的批量查询（自动 strip + 去重，含熔断与限流补查）

    Args:
      standard_nos: 标准号列表
      progress_callback: 进度回调 (current, total, msg)
      log_callback: 日志回调 (msg)
      should_stop: 返回 True 则尽快中止（含冷却等待期间）

    Returns:
      BatchOutcome
    """
    def on_progress(current, total, no):
      if self.stats.start_time is not None:
        import time
        elapsed = time.time() - self.stats.start_time
        avg_time = elapsed / current if current > 0 else 0
        eta = str(timedelta(seconds=int(avg_time * (total - current))))
        msg = f"[{current}/{total}] {no} - ETA: {eta}"
      else:
        msg = f"[{current}/{total}] {no}"
      if progress_callback:
        progress_callback(current, total, msg)

    def on_log(msg):
      if log_callback:
        log_callback(msg)
      else:
        logger.info(msg)

    return self._run_recovery_batch(
      list(standard_nos), self.tracker,
      on_progress=on_progress, on_log=on_log, should_stop=should_stop,
    )
