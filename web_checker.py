#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web版国家标准查询模块
适配Streamlit界面，支持实时进度回调
"""

import pandas as pd
import requests
import json
import os
import re
import random
import pickle
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Callable
import time

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


class ProgressTracker:
  def __init__(self, progress_file: str = ".web_query_progress.pkl"):
    self.progress_file = progress_file
    self.completed = set()
    self.failed = {}
    self.load()
  
  def load(self):
    if os.path.exists(self.progress_file):
      try:
        with open(self.progress_file, 'rb') as f:
          data = pickle.load(f)
          self.completed = data.get('completed', set())
          self.failed = data.get('failed', {})
      except Exception:
        self.completed = set()
        self.failed = {}
  
  def save(self):
    try:
      with open(self.progress_file, 'wb') as f:
        pickle.dump({
          'completed': self.completed,
          'failed': self.failed
        }, f)
    except Exception:
      pass
  
  def mark_completed(self, standard_no: str):
    self.completed.add(standard_no)
    if standard_no in self.failed:
      del self.failed[standard_no]
    self.save()
  
  def mark_failed(self, standard_no: str, error: str):
    self.failed[standard_no] = error
    self.save()
  
  def is_completed(self, standard_no: str) -> bool:
    return standard_no in self.completed
  
  def clear(self):
    self.completed = set()
    self.failed = {}
    if os.path.exists(self.progress_file):
      os.remove(self.progress_file)


class WebStandardChecker:
  def __init__(self, delay: float = 3.0, max_retries: int = 5, use_proxy: Optional[str] = None):
    self.delay = delay
    self.max_retries = max_retries
    self.use_proxy = use_proxy
    self.session = requests.Session()
    self._update_headers()
    
    if use_proxy:
      self.session.proxies = {
        'http': use_proxy,
        'https': use_proxy
      }
    
    self.stats = {
      'success': 0,
      'failed': 0,
      'rate_limited': 0,
      'start_time': None
    }
    
    self.tracker = ProgressTracker()
  
  def _update_headers(self):
    headers = {
      "Content-Type": "application/json",
      "User-Agent": random.choice(USER_AGENTS),
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      "Accept-Encoding": "gzip, deflate, br",
      "Origin": "https://www.ndls.org.cn",
      "Referer": "https://www.ndls.org.cn/"
    }
    self.session.headers.update(headers)
  
  def _calculate_wait_time(self, retry_count: int) -> float:
    base_wait = self.delay * (2 ** retry_count)
    jitter = random.uniform(0, 1)
    return base_wait + jitter
  
  def query_single(self, standard_no: str) -> Tuple[Optional[str], Optional[str], List[dict]]:
    retry_count = 0
    last_error = None
    
    while retry_count <= self.max_retries:
      try:
        if retry_count > 0:
          self._update_headers()
        
        data = {"a100": standard_no, "page": 1, "limit": 10}
        response = self.session.post(API_URL, json=data, timeout=15)
        
        if response.status_code != 200:
          last_error = f"HTTP错误 {response.status_code}"
          if retry_count < self.max_retries:
            retry_count += 1
            wait_time = self._calculate_wait_time(retry_count)
            time.sleep(wait_time)
            continue
          return None, last_error, []
        
        result = response.json()
        
        if result.get("code") != 0:
          error_msg = result.get('message', '未知错误')
          last_error = f"API错误: {error_msg}"
          
          if '限流' in error_msg or '验证码' in error_msg:
            self.stats['rate_limited'] += 1
            if retry_count < self.max_retries:
              retry_count += 1
              wait_time = self._calculate_wait_time(retry_count)
              time.sleep(wait_time)
              continue
          
          return None, last_error, []
        
        results = result.get("data", {}).get("results", [])
        
        if not results:
          return None, "未找到", []
        
        standard_info = results[0]
        status = standard_info.get("a000", "未知")
        yf001 = standard_info.get("yf001", "")
        
        friendly_status = STATUS_MAP.get(status, status)
        
        replacement_list = []
        if status == "被代替" and yf001:
          replacement_list = self._get_replacements(yf001)
        
        self.stats['success'] += 1
        return friendly_status, None, replacement_list
        
      except requests.exceptions.Timeout:
        last_error = "查询超时"
        if retry_count < self.max_retries:
          retry_count += 1
          wait_time = self._calculate_wait_time(retry_count)
          time.sleep(wait_time)
          continue
        self.stats['failed'] += 1
        return None, last_error, []
        
      except requests.exceptions.RequestException as e:
        last_error = f"请求异常: {str(e)}"
        if retry_count < self.max_retries:
          retry_count += 1
          wait_time = self._calculate_wait_time(retry_count)
          time.sleep(wait_time)
          continue
        self.stats['failed'] += 1
        return None, last_error, []
        
      except Exception as e:
        last_error = f"错误: {str(e)}"
        self.stats['failed'] += 1
        return None, last_error, []
      finally:
        if retry_count == 0:
          time.sleep(self.delay)
    
    self.stats['failed'] += 1
    return None, last_error or "超过最大重试次数", []
  
  def _get_replacements(self, yf001: str) -> List[dict]:
    try:
      response = self.session.get(f"{DETAIL_URL}/{yf001}", timeout=15)
      
      if response.status_code != 200:
        return []
      
      result = response.json()
      
      if result.get("code") != 0:
        return []
      
      detail = result.get("data", {})
      replacement_nos_raw = detail.get("a461list", [])
      
      replacement_nos = []
      for raw in replacement_nos_raw:
        match = re.search(r'被(.+?)代替', raw)
        if match:
          replacement_nos.append(match.group(1))
        else:
          replacement_nos.append(raw)
      
      replacements = []
      for replacement_no in replacement_nos:
        data = {"a100": replacement_no, "page": 1, "limit": 10}
        try:
          resp = self.session.post(API_URL, json=data, timeout=15)
          if resp.status_code == 200:
            res = resp.json()
            if res.get("code") == 0:
              results = res.get("data", {}).get("results", [])
              if results:
                replacements.append({
                  "标准号": replacement_no,
                  "标准名": results[0].get("a298", "")
                })
        except:
          pass
        time.sleep(self.delay * 0.5)
      
      return replacements
      
    except Exception:
      return []
  
  def query_batch_with_callback(
    self, 
    standard_nos: List[str], 
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    log_callback: Optional[Callable[[str], None]] = None
  ) -> List[dict]:
    results = []
    total = len(standard_nos)
    self.stats['start_time'] = time.time()
    
    pending_nos = standard_nos
    
    if not pending_nos:
      return []
    
    for i, standard_no in enumerate(pending_nos, 1):
      elapsed = time.time() - self.stats['start_time']
      avg_time = elapsed / i if i > 0 else 0
      remaining = len(pending_nos) - i
      eta = avg_time * remaining
      eta_str = str(timedelta(seconds=int(eta)))
      
      status_msg = f"[{i}/{total}] {standard_no} - ETA: {eta_str}"
      
      if progress_callback:
        progress_callback(i, total, status_msg)
      
      if log_callback:
        log_callback(f"正在查询: {standard_no}")
      
      status, error, replacements = self.query_single(standard_no)
      
      if error:
        result_entry = {
          "标准号": standard_no,
          "状态": error,
          "替代标准": ""
        }
        results.append(result_entry)
        self.tracker.mark_failed(standard_no, error)
        
        if log_callback:
          log_callback(f"❌ {standard_no}: {error}")
      else:
        replacement_str = ""
        if replacements:
          replacement_str = ", ".join([r["标准号"] for r in replacements])
        
        result_entry = {
          "标准号": standard_no,
          "状态": status,
          "替代标准": replacement_str,
          "替代列表": replacements
        }
        results.append(result_entry)
        self.tracker.mark_completed(standard_no)
        
        if log_callback:
          log_callback(f"✅ {standard_no}: {status}")
      
      time.sleep(self.delay)
    
    return results
