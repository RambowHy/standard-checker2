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
from typing import List, Optional

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

  def query_single(self, standard_no: str, sleep_after: bool = True) -> StandardResult:
    """
    查询单个标准

    Args:
      standard_no: 标准号，如 "GB 2757-2012"
      sleep_after: 查询成功后是否按 delay 等待（批量查询时最后一条传 False）

    Returns:
      StandardResult
    """
    retry_count = 0
    last_error: Optional[str] = None

    while retry_count <= self.max_retries:
      try:
        if retry_count > 0:
          self._update_headers()

        data = {"a100": standard_no, "page": 1, "limit": 10}
        response = self.session.post(API_URL, json=data, timeout=self.timeout)

        if response.status_code != 200:
          last_error = f"HTTP错误 {response.status_code}"
          if response.status_code == 429 or response.status_code >= 500:
            self.stats.rate_limited += 1
            retry_count += 1
            if retry_count <= self.max_retries:
              wait_time = self._calculate_wait_time(retry_count)
              time.sleep(wait_time)
              continue
          self.stats.failed += 1
          return StandardResult(标准号=standard_no, 错误=last_error)

        result = response.json()

        if result.get("code") != 0:
          error_msg = result.get('message', '未知错误')
          last_error = f"API错误: {error_msg}"

          if '限流' in error_msg or '验证码' in error_msg:
            self.stats.rate_limited += 1
            retry_count += 1
            if retry_count <= self.max_retries:
              wait_time = self._calculate_wait_time(retry_count)
              logger.warning("触发限流，等待 %.1f 秒后重试 (%d/%d)...", wait_time, retry_count, self.max_retries)
              time.sleep(wait_time)
              continue

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
        if sleep_after:
          time.sleep(self._random_delay())
        return StandardResult(
          标准号=standard_no,
          状态=friendly_status,
          替代标准=replacement_list,
        )

      except requests.exceptions.Timeout:
        last_error = "查询超时"
        retry_count += 1
        if retry_count <= self.max_retries:
          wait_time = self._calculate_wait_time(retry_count)
          time.sleep(wait_time)
          continue
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

      except requests.exceptions.RequestException as e:
        last_error = f"请求异常: {e}"
        retry_count += 1
        if retry_count <= self.max_retries:
          wait_time = self._calculate_wait_time(retry_count)
          time.sleep(wait_time)
          continue
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

      except Exception as e:
        last_error = f"错误: {e}"
        self.stats.failed += 1
        return StandardResult(标准号=standard_no, 错误=last_error)

    self.stats.failed += 1
    return StandardResult(标准号=standard_no, 错误=last_error or "超过最大重试次数")
