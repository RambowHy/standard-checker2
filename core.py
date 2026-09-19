#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准查询核心模块
公共常量、数据模型、进度跟踪器、查询器基类
"""

import logging
import os
import pickle
import random
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, List, Optional

import requests

logger = logging.getLogger(__name__)

API_URL = "https://www.ndls.org.cn/api/standard/list"
DETAIL_URL = "https://www.ndls.org.cn/api/standard/detail"

USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

STATUS_MAP = {
  "现行": "现行有效",
  "作废": "已作废",
  "废止": "已废止",
  "被代替": "已被代替",
  "已修订": "已修订",
  "历史": "历史标准",
  "未生效": "未生效"
}

# 这些非现行终态需要查详情确认是否有替代标准（作废状态也可能带 a461list）
REPLACEMENT_STATUSES = {"被代替", "作废", "废止", "已修订"}

# 触发限流后的冷却重试等待（秒）：约 60/120/180，封顶 180
RATE_LIMIT_COOLDOWN = 60.0
RATE_LIMIT_COOLDOWN_MAX = 180.0
# 连续多少条限流即熔断（停止本轮，避免加重封禁）
CONSECUTIVE_RATE_LIMIT_BREAK = 3
# 整轮结束后对限流条目慢速补查前的等待（秒）
RECOVERY_ROUND_WAIT = 60.0
# 限流条目最终失败时写入结果的统一原因
RATE_LIMIT_FAIL_MSG = "限流，未完成，请重新运行续查"

PROGRESS_VERSION = 2


@dataclass
class ReplacementStandard:
  """替代标准"""
  标准号: str
  标准名: str = ""


@dataclass
class StandardResult:
  """单条标准查询结果"""
  标准号: str
  状态: Optional[str] = None
  错误: Optional[str] = None
  替代标准: List[ReplacementStandard] = field(default_factory=list)

  @property
  def 替代标准号(self) -> str:
    return ", ".join(r.标准号 for r in self.替代标准)

  @property
  def 替代标准名(self) -> str:
    return ", ".join(r.标准名 for r in self.替代标准)


@dataclass
class QueryStats:
  """查询统计"""
  success: int = 0
  failed: int = 0
  rate_limited: int = 0
  start_time: Optional[float] = None

  def reset(self):
    self.success = 0
    self.failed = 0
    self.rate_limited = 0
    self.start_time = None


@dataclass
class BatchOutcome:
  """批量查询结果"""
  results: List[StandardResult] = field(default_factory=list)
  failures: dict = field(default_factory=dict)
  rate_limited: set = field(default_factory=set)
  cancelled: bool = False

  @property
  def failure_results(self) -> List[StandardResult]:
    """把失败条目也转为 StandardResult，便于统一回填"""
    return [StandardResult(标准号=no, 错误=err) for no, err in self.failures.items()]


def normalize_standard_nos(raw_nos: List[str]) -> List[str]:
  """去空白并按首次出现顺序去重，丢弃空值"""
  normalized = []
  seen = set()
  for raw in raw_nos:
    if raw is None:
      continue
    standard_no = str(raw).strip()
    if standard_no and standard_no not in seen:
      seen.add(standard_no)
      normalized.append(standard_no)
  return normalized


class ProgressTracker:
  """进度跟踪器 - 支持断点续传，持久化已完成条目的查询结果"""

  def __init__(self, progress_file: str = ".query_progress.pkl"):
    self.progress_file = progress_file
    self.results: dict = {}
    self.load()

  @property
  def completed(self) -> set:
    return set(self.results.keys())

  def load(self):
    if not os.path.exists(self.progress_file):
      return
    try:
      with open(self.progress_file, 'rb') as f:
        data = pickle.load(f)
      version = data.get('version', 0)
      if version != PROGRESS_VERSION:
        logger.warning("进度文件版本不兼容，将忽略已有进度")
        self._remove_file()
        return
      self.results = data.get('results', {})
      logger.info("已加载进度: %d 条已完成", len(self.results))
    except Exception as e:
      logger.warning("加载进度文件失败: %s", e)
      self.results = {}

  def save(self):
    try:
      with open(self.progress_file, 'wb') as f:
        pickle.dump({
          'version': PROGRESS_VERSION,
          'results': self.results,
        }, f)
    except Exception as e:
      logger.warning("保存进度文件失败: %s", e)

  def mark_completed(self, standard_no: str, result: StandardResult):
    self.results[standard_no] = result
    self.save()

  def get_result(self, standard_no: str) -> Optional[StandardResult]:
    return self.results.get(standard_no)

  def is_completed(self, standard_no: str) -> bool:
    return standard_no in self.results

  def completed_count(self) -> int:
    return len(self.results)

  def clear(self):
    self.results = {}
    self._remove_file()
    logger.info("已清除所有进度")

  def _remove_file(self):
    if os.path.exists(self.progress_file):
      os.remove(self.progress_file)


class BaseStandardChecker:
  """国家标准查询器基类"""

  def __init__(self, delay: float = 5.0, max_retries: int = 3,
               use_proxy: Optional[str] = None, timeout: float = 15.0,
               jitter_ratio: float = 0.5):
    self.delay = delay
    self.max_retries = max_retries
    self.use_proxy = use_proxy
    self.timeout = timeout
    self.jitter_ratio = jitter_ratio
    self.session = requests.Session()
    self.stats = QueryStats()
    self._update_headers()

    if use_proxy:
      self.session.proxies = {
        'http': use_proxy,
        'https': use_proxy,
      }

  def _update_headers(self):
    headers = {
      "Content-Type": "application/json",
      "User-Agent": random.choice(USER_AGENTS),
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      "Accept-Encoding": "gzip, deflate, br",
      "Origin": "https://www.ndls.org.cn",
      "Referer": "https://www.ndls.org.cn/",
    }
    self.session.headers.update(headers)

  def _calculate_wait_time(self, retry_count: int) -> float:
    base_wait = self.delay * (2 ** retry_count)
    jitter = random.uniform(0, 1)
    return base_wait + jitter

  def _random_delay(self) -> float:
    """以 delay 为均值的随机间隔，范围 delay*(1±jitter_ratio)；ratio=0 时为固定间隔"""
    if self.jitter_ratio <= 0:
      return self.delay
    span = self.delay * self.jitter_ratio
    return self.delay + random.uniform(-span, span)

  @staticmethod
  def _is_rate_limit_message(message: str) -> bool:
    return ('限流' in message) or ('验证码' in message)

  def _rate_limit_cooldown(self, retry_count: int) -> float:
    """限流冷却等待，指数增长并封顶，带 ±20% 抖动"""
    base = min(RATE_LIMIT_COOLDOWN * (2 ** (retry_count - 1)), RATE_LIMIT_COOLDOWN_MAX)
    return base * random.uniform(0.8, 1.2)

  @staticmethod
  def _interruptible_sleep(seconds: float,
                           should_stop: Optional[Callable[[], bool]] = None) -> bool:
    """分片睡眠以便取消；返回 True 表示被中断"""
    remaining = seconds
    while remaining > 0:
      if should_stop is not None and should_stop():
        return True
      step = min(1.0, remaining)
      time.sleep(step)
      remaining -= step
    return should_stop is not None and should_stop()

  @staticmethod
  def _parse_replacement_nos(raw_list: List[str]) -> List[str]:
    """从原始替代文本中提取标准号"""
    replacement_nos = []
    for raw in raw_list:
      match = re.search(r'被(.+?)代替', raw)
      replacement_nos.append(match.group(1) if match else raw)
    return replacement_nos

  def _get_replacements(self, yf001: str) -> List[ReplacementStandard]:
    """获取替代标准列表"""
    try:
      response = self.session.get(f"{DETAIL_URL}/{yf001}", timeout=self.timeout)
      if response.status_code != 200:
        return []

      result = response.json()
      if result.get("code") != 0:
        return []

      detail = result.get("data", {})
      replacement_nos = self._parse_replacement_nos(detail.get("a461list", []))

      replacements: List[ReplacementStandard] = []
      for replacement_no in replacement_nos:
        name = self._fetch_standard_name(replacement_no)
        replacements.append(ReplacementStandard(标准号=replacement_no, 标准名=name))
        time.sleep(self._random_delay() * 0.5)

      return replacements

    except Exception:
      return []

  def _fetch_standard_name(self, standard_no: str) -> str:
    """查询标准名称"""
    data = {"a100": standard_no, "page": 1, "limit": 10}
    try:
      resp = self.session.post(API_URL, json=data, timeout=self.timeout)
      if resp.status_code == 200:
        res = resp.json()
        if res.get("code") == 0:
          results = res.get("data", {}).get("results", [])
          if results:
            return results[0].get("a298", "")
    except Exception:
      pass
    return ""

  def query_single(self, standard_no: str, sleep_after: bool = True,
                   should_stop: Optional[Callable[[], bool]] = None) -> StandardResult:
    """
    查询单个标准

    Args:
      standard_no: 标准号，如 "GB 2757-2012"
      sleep_after: 查询成功后是否按 delay 等待（批量查询时最后一条传 False）
      should_stop: 取消检查，冷却/等待期间被置位则尽快返回“已取消”

    Returns:
      StandardResult（限流重试耗尽时错误为 RATE_LIMIT_FAIL_MSG）
    """
    retry_count = 0
    last_error: Optional[str] = None
    hit_rate_limit = False

    while retry_count <= self.max_retries:
      if should_stop is not None and should_stop():
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误="已取消")

      try:
        if retry_count > 0:
          self._update_headers()

        data = {"a100": standard_no, "page": 1, "limit": 10}
        response = self.session.post(API_URL, json=data, timeout=self.timeout)

        if response.status_code != 200:
          last_error = f"HTTP错误 {response.status_code}"
          rate_limited = response.status_code == 429
          hit_rate_limit = hit_rate_limit or rate_limited
          if rate_limited or response.status_code >= 500:
            retry_count += 1
            if retry_count <= self.max_retries:
              if self._wait_retry(retry_count, rate_limited, should_stop):
                return StandardResult(标准号=standard_no, 错误="已取消")
              continue
          self.stats.failed += 1
          err = RATE_LIMIT_FAIL_MSG if rate_limited else last_error
          return StandardResult(标准号=standard_no, 错误=err)

        result = response.json()

        if result.get("code") != 0:
          error_msg = result.get('message', '未知错误')
          last_error = f"API错误: {error_msg}"

          if self._is_rate_limit_message(error_msg):
            retry_count += 1
            if retry_count <= self.max_retries:
              logger.warning("触发限流，冷却 %.0f 秒后重试 (%d/%d)...",
                             RATE_LIMIT_COOLDOWN, retry_count, self.max_retries)
              if self._wait_retry(retry_count, True, should_stop):
                return StandardResult(标准号=standard_no, 错误="已取消")
              continue
            self.stats.failed += 1
            return StandardResult(标准号=standard_no, 错误=RATE_LIMIT_FAIL_MSG)

          self.stats.failed += 1
          return StandardResult(标准号=standard_no, 错误=last_error)

        results = result.get("data", {}).get("results", [])
        if not results:
          self.stats.failed += 1
          return StandardResult(标准号=standard_no, 错误="未找到")

        standard_info = results[0]
        status = standard_info.get("a000", "未知")
        yf001 = standard_info.get("yf001", "")
        friendly_status = STATUS_MAP.get(status, status)

        replacement_list: List[ReplacementStandard] = []
        if status in REPLACEMENT_STATUSES and yf001:
          replacement_list = self._get_replacements(yf001)

        self.stats.success += 1
        if sleep_after and not self._interruptible_sleep(self._random_delay(), should_stop):
          pass
        return StandardResult(
          标准号=standard_no,
          状态=friendly_status,
          替代标准=replacement_list,
        )

      except requests.exceptions.Timeout:
        last_error = "查询超时"
        retry_count += 1
        if retry_count <= self.max_retries:
          if self._wait_retry(retry_count, False, should_stop):
            return StandardResult(标准号=standard_no, 错误="已取消")
          continue
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

      except requests.exceptions.RequestException as e:
        last_error = f"请求异常: {e}"
        retry_count += 1
        if retry_count <= self.max_retries:
          if self._wait_retry(retry_count, False, should_stop):
            return StandardResult(标准号=standard_no, 错误="已取消")
          continue
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

      except Exception as e:
        last_error = f"错误: {e}"
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

    self.stats.failed += 1
    if hit_rate_limit:
      return StandardResult(标准号=standard_no, 错误=RATE_LIMIT_FAIL_MSG)
    return StandardResult(标准号=standard_no, 错误=last_error or "超过最大重试次数")

  def _wait_retry(self, retry_count: int, rate_limited: bool,
                  should_stop: Optional[Callable[[], bool]] = None) -> bool:
    """重试等待；限流走长冷却，其他错误走短退避。返回 True 表示被取消"""
    if rate_limited:
      self.stats.rate_limited += 1
      wait_time = self._rate_limit_cooldown(retry_count)
    else:
      wait_time = self._calculate_wait_time(retry_count)
    return self._interruptible_sleep(wait_time, should_stop)

  def _run_recovery_batch(
    self,
    standard_nos: List[str],
    tracker: Optional[ProgressTracker] = None,
    *,
    resume: bool = True,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    recovery_wait: float = RECOVERY_ROUND_WAIT,
  ) -> BatchOutcome:
    """批量查询编排：主轮熔断 + 限流条目当轮慢速补查一次"""
    def log(msg: str):
      if on_log:
        on_log(msg)
      else:
        logger.info(msg)

    standard_nos = normalize_standard_nos(standard_nos)
    outcome = BatchOutcome()
    self.stats.reset()
    self.stats.start_time = time.time()

    pending_nos = standard_nos
    if resume and tracker:
      pending_nos = [s for s in standard_nos if not tracker.is_completed(s)]
      skipped = len(standard_nos) - len(pending_nos)
      if skipped:
        log(f"[进度] 跳过已完成的 {skipped} 条，剩余 {len(pending_nos)} 条待查询")

    total = len(pending_nos)
    consecutive_rate_limited = 0
    circuit_broken = False

    def query_one(no: str, idx: int, total_in_round: int) -> StandardResult:
      if on_progress:
        on_progress(idx, total_in_round, no)
      result = self.query_single(
        no,
        sleep_after=(idx < total_in_round),
        should_stop=should_stop,
      )
      return result

    for i, no in enumerate(pending_nos, 1):
      if should_stop is not None and should_stop():
        outcome.cancelled = True
        break

      result = query_one(no, i, total)

      if result.错误:
        is_rate = result.错误 == RATE_LIMIT_FAIL_MSG
        if result.错误 == "已取消":
          outcome.cancelled = True
          break
        if is_rate:
          outcome.failures[no] = result.错误
          outcome.rate_limited.add(no)
          consecutive_rate_limited += 1
          log(f"❌ {no}: 触发限流，先跳过")
          if consecutive_rate_limited >= CONSECUTIVE_RATE_LIMIT_BREAK:
            log("⛔ 连续触发限流，熔断本轮查询以避免加重封禁，稍后可续跑")
            circuit_broken = True
            break
        else:
          outcome.failures[no] = result.错误
          log(f"❌ {no}: {result.错误}")
      else:
        consecutive_rate_limited = 0
        outcome.failures.pop(no, None)
        outcome.rate_limited.discard(no)
        if tracker:
          tracker.mark_completed(no, result)
        else:
          outcome.results.append(result)
        detail = f" (替代: {result.替代标准号})" if result.替代标准 else ""
        log(f"✅ {no}: {result.状态}{detail}")

    # 补查轮：对限流条目慢速重试一次（熔断时不再补查）
    if (not outcome.cancelled and not circuit_broken and outcome.rate_limited
            and (should_stop is None or not should_stop())):
      retry_nos = [s for s in pending_nos if s in outcome.rate_limited]
      if retry_nos:
        log(f"[补查] 等待 {int(recovery_wait)} 秒后，对 {len(retry_nos)} 条限流条目补查…")
        if self._interruptible_sleep(recovery_wait, should_stop):
          outcome.cancelled = True
        else:
          for i, no in enumerate(retry_nos, 1):
            if should_stop is not None and should_stop():
              outcome.cancelled = True
              break
            result = query_one(no, i, len(retry_nos))
            if result.错误:
              if result.错误 == "已取消":
                outcome.cancelled = True
                break
              outcome.failures[no] = result.错误
              log(f"❌ {no}: 仍{result.错误}")
            else:
              outcome.failures.pop(no, None)
              outcome.rate_limited.discard(no)
              if tracker:
                tracker.mark_completed(no, result)
              else:
                outcome.results.append(result)
              log(f"✅ {no}: 补查成功 {result.状态}")

    # 从 tracker 汇总成功结果（含历史进度）
    if tracker:
      outcome.results = [tracker.get_result(s) for s in standard_nos
                         if tracker.is_completed(s)]

    return outcome
