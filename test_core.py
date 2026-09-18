#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国家标准查询工具 - 自动化测试"""

import os
import pickle
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
  API_URL,
  BaseStandardChecker,
  DETAIL_URL,
  ProgressTracker,
  QueryStats,
  ReplacementStandard,
  StandardResult,
  STATUS_MAP,
  USER_AGENTS,
  normalize_standard_nos,
)


class TestReplacementStandard(unittest.TestCase):
  def test_create(self):
    r = ReplacementStandard(标准号="GB 2716-2018", 标准名="植物油")
    self.assertEqual(r.标准号, "GB 2716-2018")
    self.assertEqual(r.标准名, "植物油")

  def test_default_name(self):
    r = ReplacementStandard(标准号="GB/T 8170-2008")
    self.assertEqual(r.标准名, "")


class TestNormalizeStandardNos(unittest.TestCase):
  def test_strip_and_dedupe_keep_order(self):
    result = normalize_standard_nos([" GB 1 ", "GB 1", "", "  ", "GB 2", None, "GB 2 "])
    self.assertEqual(result, ["GB 1", "GB 2"])

  def test_empty(self):
    self.assertEqual(normalize_standard_nos([]), [])
    self.assertEqual(normalize_standard_nos([None, "  "]), [])


class TestStandardResult(unittest.TestCase):
  def test_basic(self):
    r = StandardResult(标准号="GB 2757-2012", 状态="现行有效")
    self.assertIsNone(r.错误)
    self.assertEqual(r.替代标准, [])
    self.assertEqual(r.替代标准号, "")
    self.assertEqual(r.替代标准名, "")

  def test_with_replacements(self):
    r = StandardResult(
      标准号="GB 2757-2012",
      状态="已被代替",
      替代标准=[
        ReplacementStandard(标准号="GB 2716-2018", 标准名="植物油"),
        ReplacementStandard(标准号="GB/T 5009.37-2003", 标准名="食用植物油卫生标准"),
      ],
    )
    self.assertEqual(r.替代标准号, "GB 2716-2018, GB/T 5009.37-2003")
    self.assertEqual(r.替代标准名, "植物油, 食用植物油卫生标准")

  def test_error_result(self):
    r = StandardResult(标准号="GB 9999-9999", 错误="未找到")
    self.assertEqual(r.状态, None)
    self.assertEqual(r.错误, "未找到")




class TestQueryStats(unittest.TestCase):
  def test_init(self):
    s = QueryStats()
    self.assertEqual(s.success, 0)
    self.assertEqual(s.failed, 0)
    self.assertEqual(s.rate_limited, 0)
    self.assertIsNone(s.start_time)

  def test_reset(self):
    s = QueryStats(success=10, failed=2, rate_limited=1, start_time=100.0)
    s.reset()
    self.assertEqual(s.success, 0)
    self.assertEqual(s.failed, 0)
    self.assertEqual(s.rate_limited, 0)
    self.assertIsNone(s.start_time)


class TestProgressTracker(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.progress_file = os.path.join(self.tmpdir, "test_progress.pkl")

  def tearDown(self):
    if os.path.exists(self.progress_file):
      os.remove(self.progress_file)
    os.rmdir(self.tmpdir)

  def test_new_tracker(self):
    tracker = ProgressTracker(self.progress_file)
    self.assertEqual(tracker.completed_count(), 0)
    self.assertEqual(len(tracker.completed), 0)

  def test_mark_completed(self):
    tracker = ProgressTracker(self.progress_file)
    tracker.mark_completed("GB 2757-2012", StandardResult(标准号="GB 2757-2012", 状态="现行有效"))
    self.assertTrue(tracker.is_completed("GB 2757-2012"))
    self.assertFalse(tracker.is_completed("GB/T 8170-2008"))
    self.assertEqual(tracker.completed_count(), 1)

  def test_get_stored_result(self):
    tracker = ProgressTracker(self.progress_file)
    result = StandardResult(标准号="GB 2757-2012", 状态="现行有效")
    tracker.mark_completed("GB 2757-2012", result)
    self.assertEqual(tracker.get_result("GB 2757-2012").状态, "现行有效")
    self.assertIsNone(tracker.get_result("GB/T 8170-2008"))

  def test_failed_not_persisted(self):
    # 失败条目不标记完成，下次运行仍会重新查询
    tracker = ProgressTracker(self.progress_file)
    tracker.mark_completed("GB 2757-2012", StandardResult(标准号="GB 2757-2012", 状态="现行有效"))
    self.assertTrue(tracker.is_completed("GB 2757-2012"))
    self.assertFalse(tracker.is_completed("GB 9999-9999"))
    self.assertEqual(tracker.completed_count(), 1)

  def test_persistence(self):
    tracker1 = ProgressTracker(self.progress_file)
    tracker1.mark_completed("GB 2757-2012", StandardResult(标准号="GB 2757-2012", 状态="现行有效"))
    del tracker1

    tracker2 = ProgressTracker(self.progress_file)
    self.assertTrue(tracker2.is_completed("GB 2757-2012"))
    self.assertEqual(tracker2.get_result("GB 2757-2012").状态, "现行有效")
    self.assertFalse(tracker2.is_completed("GB 9999-9999"))

  def test_clear(self):
    tracker = ProgressTracker(self.progress_file)
    tracker.mark_completed("GB 2757-2012", StandardResult(标准号="GB 2757-2012", 状态="现行有效"))
    tracker.clear()
    self.assertEqual(tracker.completed_count(), 0)
    self.assertFalse(os.path.exists(self.progress_file))

  def test_version_incompatible(self):
    with open(self.progress_file, 'wb') as f:
      pickle.dump({'version': 999, 'results': {'GB 2757-2012': None}}, f)
    tracker = ProgressTracker(self.progress_file)
    self.assertEqual(tracker.completed_count(), 0)

  def test_corrupt_file(self):
    with open(self.progress_file, 'wb') as f:
      f.write(b"not valid pickle data")
    tracker = ProgressTracker(self.progress_file)
    self.assertEqual(tracker.completed_count(), 0)


class TestBaseStandardChecker(unittest.TestCase):
  def test_parse_replacement_nos(self):
    raw = ["被GB 2716-2018代替", "被GB/T 5009.37-2003代替"]
    result = BaseStandardChecker._parse_replacement_nos(raw)
    self.assertEqual(result, ["GB 2716-2018", "GB/T 5009.37-2003"])

  def test_parse_replacement_nos_no_match(self):
    raw = ["GB 2716-2018"]
    result = BaseStandardChecker._parse_replacement_nos(raw)
    self.assertEqual(result, ["GB 2716-2018"])

  def test_parse_replacement_nos_empty(self):
    result = BaseStandardChecker._parse_replacement_nos([])
    self.assertEqual(result, [])

  def test_calculate_wait_time(self):
    checker = BaseStandardChecker(delay=3.0, max_retries=5)
    with patch('core.random.uniform', return_value=0.5):
      wait = checker._calculate_wait_time(0)
      self.assertAlmostEqual(wait, 3.5, places=1)
      wait = checker._calculate_wait_time(1)
      self.assertAlmostEqual(wait, 6.5, places=1)
      wait = checker._calculate_wait_time(2)
      self.assertAlmostEqual(wait, 12.5, places=1)

  def test_random_delay_bounds(self):
    checker = BaseStandardChecker(delay=5.0, jitter_ratio=0.5)
    with patch('core.random.uniform', return_value=-2.5):
      self.assertAlmostEqual(checker._random_delay(), 2.5, places=4)
    with patch('core.random.uniform', return_value=2.5):
      self.assertAlmostEqual(checker._random_delay(), 7.5, places=4)
    with patch('core.random.uniform', return_value=0.0):
      self.assertAlmostEqual(checker._random_delay(), 5.0, places=4)

  def test_random_delay_zero_ratio_is_fixed(self):
    checker = BaseStandardChecker(delay=5.0, jitter_ratio=0)
    with patch('core.random.uniform') as mock_uniform:
      self.assertAlmostEqual(checker._random_delay(), 5.0, places=4)
      mock_uniform.assert_not_called()

  def test_update_headers_rotates_ua(self):
    checker = BaseStandardChecker()
    with patch('core.random.choice', return_value=USER_AGENTS[0]):
      checker._update_headers()
      self.assertIn(USER_AGENTS[0], checker.session.headers.get("User-Agent", ""))

  def test_query_single_success(self):
    checker = BaseStandardChecker(delay=0)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {
        "results": [{
          "a000": "现行",
          "a100": "GB 2757-2012",
          "a298": "蒸馏酒及配制酒",
          "yf001": "test_yf001",
        }]
      }
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        result = checker.query_single("GB 2757-2012")
    self.assertEqual(result.标准号, "GB 2757-2012")
    self.assertEqual(result.状态, "现行有效")
    self.assertIsNone(result.错误)

  def test_query_single_not_found(self):
    checker = BaseStandardChecker(delay=0)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": []}
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        result = checker.query_single("GB 99999-9999")
    self.assertEqual(result.错误, "未找到")

  def test_query_single_http_error(self):
    checker = BaseStandardChecker(delay=0, max_retries=0)
    mock_response = MagicMock()
    mock_response.status_code = 500
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        result = checker.query_single("GB 2757-2012")
    self.assertIn("HTTP错误", result.错误)

  def test_4xx_no_retry(self):
    # 400/404 等客户端错误不应重试
    checker = BaseStandardChecker(delay=3.0, max_retries=5)
    mock_response = MagicMock()
    mock_response.status_code = 404
    with patch.object(checker.session, 'post', return_value=mock_response) as mock_post:
      with patch('core.time.sleep') as mock_sleep:
        result = checker.query_single("GB 2757-2012")
    self.assertIn("HTTP错误 404", result.错误)
    self.assertEqual(mock_post.call_count, 1)
    mock_sleep.assert_not_called()

  def test_429_retries(self):
    checker = BaseStandardChecker(delay=0, max_retries=2)
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": "现行", "a100": "GB 2757-2012", "yf001": "y"}]},
    }
    with patch.object(checker.session, 'post', side_effect=[rate_limited, ok_response]):
      with patch('core.time.sleep'):
        result = checker.query_single("GB 2757-2012", sleep_after=False)
    self.assertEqual(result.状态, "现行有效")
    self.assertGreaterEqual(checker.stats.rate_limited, 1)

  def test_no_sleep_after_last_when_disabled(self):
    checker = BaseStandardChecker(delay=5.0)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": "现行", "a100": "GB 2757-2012", "yf001": "y"}]},
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep') as mock_sleep:
        checker.query_single("GB 2757-2012", sleep_after=False)
    mock_sleep.assert_not_called()

  def test_success_sleep_uses_jittered_delay(self):
    checker = BaseStandardChecker(delay=5.0, jitter_ratio=0.5)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": "现行", "a100": "GB 2757-2012", "yf001": "y"}]},
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.random.uniform', return_value=2.0):
        with patch('core.time.sleep') as mock_sleep:
          checker.query_single("GB 2757-2012", sleep_after=True)
    mock_sleep.assert_called_once_with(7.0)

  def test_query_single_replaced(self):
    checker = BaseStandardChecker(delay=0)
    mock_list_response = MagicMock()
    mock_list_response.status_code = 200
    mock_list_response.json.return_value = {
      "code": 0,
      "data": {
        "results": [{
          "a000": "被代替",
          "a100": "GB 2757-2012",
          "yf001": "test_yf001",
        }]
      }
    }
    mock_detail_response = MagicMock()
    mock_detail_response.status_code = 200
    mock_detail_response.json.return_value = {
      "code": 0,
      "data": {"a461list": ["被GB 2716-2018代替"]}
    }
    mock_name_response = MagicMock()
    mock_name_response.status_code = 200
    mock_name_response.json.return_value = {
      "code": 0,
      "data": {
        "results": [{"a298": "植物油"}]
      }
    }
    with patch.object(checker.session, 'post', return_value=mock_list_response):
      with patch.object(checker.session, 'get', return_value=mock_detail_response):
        with patch('core.time.sleep'):
          with patch.object(checker, '_fetch_standard_name', return_value="植物油"):
            result = checker.query_single("GB 2757-2012")
    self.assertEqual(result.状态, "已被代替")
    self.assertEqual(len(result.替代标准), 1)
    self.assertEqual(result.替代标准[0].标准号, "GB 2716-2018")

  def test_proxy_setting(self):
    checker = BaseStandardChecker(use_proxy="http://127.0.0.1:7890")
    self.assertEqual(checker.session.proxies['http'], "http://127.0.0.1:7890")
    self.assertEqual(checker.session.proxies['https'], "http://127.0.0.1:7890")


class TestCLIQuery(unittest.TestCase):
  def test_single_query_output(self):
    from standard_checker import StandardChecker
    checker = StandardChecker(delay=0)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {
        "results": [{
          "a000": "现行",
          "a100": "GB 2757-2012",
          "yf001": "test_yf001",
        }]
      }
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        results = checker.query_batch(["GB 2757-2012"])
    self.assertEqual(len(results), 1)
    self.assertEqual(results[0].标准号, "GB 2757-2012")
    self.assertEqual(results[0].状态, "现行有效")


class TestResume(unittest.TestCase):
  """断点续跑：已完成条目的结果必须从进度记录恢复，不能丢失"""

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.progress_file = os.path.join(self.tmpdir, "test_progress.pkl")

  def tearDown(self):
    for name in os.listdir(self.tmpdir):
      os.remove(os.path.join(self.tmpdir, name))
    os.rmdir(self.tmpdir)

  def _mock_response(self, status: str):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": status, "a100": "x", "yf001": "y"}]},
    }
    return mock_response

  def test_query_batch_resume_merges_history(self):
    from standard_checker import StandardChecker
    all_nos = ["GB 2757-2012", "GB/T 8170-2008"]
    queried = []

    def post_side_effect(url, json=None, timeout=None):
      queried.append(json["a100"])
      status = "现行" if json["a100"] == "GB 2757-2012" else "废止"
      return self._mock_response(status)

    # 第一轮：只查第一个标准（模拟中断）
    checker1 = StandardChecker(delay=0)
    tracker1 = ProgressTracker(self.progress_file)
    with patch.object(checker1.session, 'post', side_effect=post_side_effect):
      with patch('core.time.sleep'):
        results1 = checker1.query_batch([all_nos[0]], tracker=tracker1)
    self.assertEqual([r.标准号 for r in results1], [all_nos[0]])

    # 第二轮：传入完整列表，已完成的应跳过且结果被带回
    checker2 = StandardChecker(delay=0)
    tracker2 = ProgressTracker(self.progress_file)
    with patch.object(checker2.session, 'post', side_effect=post_side_effect):
      with patch('core.time.sleep'):
        results2 = checker2.query_batch(all_nos, tracker=tracker2)

    self.assertEqual(queried, all_nos)
    self.assertEqual([r.标准号 for r in results2], all_nos)
    self.assertEqual(results2[0].状态, "现行有效")
    self.assertEqual(results2[1].状态, "已废止")

  def test_update_excel_resume_fills_all_rows(self):
    from standard_checker import StandardChecker
    input_file = os.path.join(self.tmpdir, "resume_input.xlsx")
    output_file = os.path.join(self.tmpdir, "resume_output.xlsx")

    import pandas as pd
    pd.DataFrame({"标准号": ["GB 2757-2012", "GB/T 8170-2008"]}).to_excel(input_file, index=False)

    def ok_response(no: str, status: str):
      mock_response = MagicMock()
      mock_response.status_code = 200
      mock_response.json.return_value = {
        "code": 0,
        "data": {"results": [{"a000": status, "a100": no, "yf001": "y"}]},
      }
      return mock_response

    def not_found_response():
      mock_response = MagicMock()
      mock_response.status_code = 200
      mock_response.json.return_value = {"code": 0, "data": {"results": []}}
      return mock_response

    # 第一轮：第二条「未找到」，第一条成功并留存进度
    def first_round(url, json=None, timeout=None):
      if json["a100"] == "GB 2757-2012":
        return ok_response("GB 2757-2012", "现行")
      return not_found_response()

    checker1 = StandardChecker(delay=0, max_retries=0)
    with patch.object(checker1.session, 'post', side_effect=first_round):
      with patch('core.time.sleep'):
        checker1.update_excel(input_file, output_file)

    self.assertTrue(os.path.exists(input_file + ".progress.pkl"))

    # 第二轮：第二条恢复正常，续跑后两行都必须有状态（含第一轮的历史结果）
    def second_round(url, json=None, timeout=None):
      status = "现行" if json["a100"] == "GB 2757-2012" else "废止"
      return ok_response(json["a100"], status)

    queried = []

    def tracking_post(url, json=None, timeout=None):
      queried.append(json["a100"])
      return second_round(url, json=json, timeout=timeout)

    checker2 = StandardChecker(delay=0, max_retries=0)
    with patch.object(checker2.session, 'post', side_effect=tracking_post):
      with patch('core.time.sleep'):
        checker2.update_excel(input_file, output_file)

    self.assertEqual(queried, ["GB/T 8170-2008"])
    result_df = pd.read_excel(output_file)
    self.assertEqual(result_df['ndls状态'].tolist(), ["现行有效", "已废止"])
    self.assertFalse(os.path.exists(input_file + ".progress.pkl"))


class TestWebChecker(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.progress_file = os.path.join(self.tmpdir, "web_progress.pkl")

  def tearDown(self):
    for name in os.listdir(self.tmpdir):
      os.remove(os.path.join(self.tmpdir, name))
    os.rmdir(self.tmpdir)

  def test_batch_with_callback(self):
    from web_checker import WebStandardChecker
    checker = WebStandardChecker(delay=0, progress_file=self.progress_file)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {
        "results": [{
          "a000": "现行",
          "a100": "GB 2757-2012",
          "yf001": "test_yf001",
        }]
      }
    }
    progress_calls = []
    log_calls = []

    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        results = checker.query_batch_with_callback(
          ["GB 2757-2012"],
          progress_callback=lambda c, t, m: progress_calls.append((c, t, m)),
          log_callback=lambda m: log_calls.append(m),
        )

    self.assertEqual(len(results), 1)
    self.assertEqual(results[0].状态, "现行有效")
    self.assertEqual(len(progress_calls), 1)
    self.assertTrue(len(log_calls) >= 1)

  def test_cancelled_returns_only_completed(self):
    from web_checker import WebStandardChecker
    checker = WebStandardChecker(delay=0, progress_file=self.progress_file)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": "现行", "a100": "x", "yf001": "y"}]},
    }
    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        results = checker.query_batch_with_callback(
          ["GB 2757-2012", "GB/T 8170-2008"],
          should_stop=lambda: True,
        )
    self.assertEqual(results, [])
    self.assertEqual(checker.tracker.completed_count(), 0)

  def test_normalize_and_dedupe(self):
    from web_checker import WebStandardChecker
    checker = WebStandardChecker(delay=0, progress_file=self.progress_file)
    queried = []
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "code": 0,
      "data": {"results": [{"a000": "现行", "a100": "x", "yf001": "y"}]},
    }

    def post_side_effect(url, json=None, timeout=None):
      queried.append(json["a100"])
      return mock_response

    with patch.object(checker.session, 'post', side_effect=post_side_effect):
      with patch('core.time.sleep'):
        results = checker.query_batch_with_callback(
          [" GB 1 ", "GB 1", "", "GB 2"],
        )
    self.assertEqual(queried, ["GB 1", "GB 2"])
    self.assertEqual([r.标准号 for r in results], ["GB 1", "GB 2"])


class TestExcelUpdate(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.input_file = os.path.join(self.tmpdir, "test_input.xlsx")
    self.output_file = os.path.join(self.tmpdir, "test_output.xlsx")

    import pandas as pd
    df = pd.DataFrame({"标准号": ["GB 2757-2012", "GB/T 8170-2008"]})
    df.to_excel(self.input_file, index=False)

  def tearDown(self):
    for name in os.listdir(self.tmpdir):
      os.remove(os.path.join(self.tmpdir, name))
    os.rmdir(self.tmpdir)

  def test_update_excel(self):
    from standard_checker import StandardChecker
    checker = StandardChecker(delay=0)

    mock_response = MagicMock()
    mock_response.status_code = 200

    def json_side_effect():
      call_count = getattr(json_side_effect, '_count', 0)
      json_side_effect._count = call_count + 1
      if json_side_effect._count == 1:
        return {"code": 0, "data": {"results": [{"a000": "现行", "a100": "GB 2757-2012", "yf001": "y1"}]}}
      return {"code": 0, "data": {"results": [{"a000": "废止", "a100": "GB/T 8170-2008", "yf001": "y2"}]}}

    mock_response.json = json_side_effect

    with patch.object(checker.session, 'post', return_value=mock_response):
      with patch('core.time.sleep'):
        checker.update_excel(self.input_file, self.output_file)

    import pandas as pd
    result_df = pd.read_excel(self.output_file)
    self.assertIn('ndls状态', result_df.columns)
    self.assertIn('ndls查询时间', result_df.columns)
    self.assertIn('替代标准号', result_df.columns)
    self.assertIn('替代标准名', result_df.columns)

  def test_duplicate_and_whitespace_rows_all_filled(self):
    from standard_checker import StandardChecker
    dup_input = os.path.join(self.tmpdir, "dup_input.xlsx")
    dup_output = os.path.join(self.tmpdir, "dup_output.xlsx")

    import pandas as pd
    pd.DataFrame({"标准号": [" GB 1 ", "GB 1", "GB 2"]}).to_excel(dup_input, index=False)

    checker = StandardChecker(delay=0, max_retries=0)

    def post_side_effect(url, json=None, timeout=None):
      status = "现行" if json["a100"] == "GB 1" else "废止"
      mock_response = MagicMock()
      mock_response.status_code = 200
      mock_response.json.return_value = {
        "code": 0,
        "data": {"results": [{"a000": status, "a100": json["a100"], "yf001": "y"}]},
      }
      return mock_response

    with patch.object(checker.session, 'post', side_effect=post_side_effect):
      with patch('core.time.sleep'):
        checker.update_excel(dup_input, dup_output)

    result_df = pd.read_excel(dup_output)
    self.assertEqual(result_df['标准号'].tolist(), ["GB 1", "GB 1", "GB 2"])
    self.assertEqual(result_df['ndls状态'].tolist(), ["现行有效", "现行有效", "已废止"])
    self.assertFalse(os.path.exists(dup_input + ".progress.pkl"))


class TestModuleImports(unittest.TestCase):
  def test_core_import(self):
    import core
    self.assertTrue(hasattr(core, 'BaseStandardChecker'))
    self.assertTrue(hasattr(core, 'StandardResult'))
    self.assertTrue(hasattr(core, 'ProgressTracker'))

  def test_cli_import(self):
    from standard_checker import StandardChecker
    self.assertTrue(issubclass(StandardChecker, BaseStandardChecker))

  def test_web_import(self):
    from web_checker import WebStandardChecker
    self.assertTrue(issubclass(WebStandardChecker, BaseStandardChecker))

  def test_no_circular_import(self):
    import core
    import standard_checker
    import web_checker
    self.assertIsNotNone(core)
    self.assertIsNotNone(standard_checker)
    self.assertIsNotNone(web_checker)


if __name__ == "__main__":
  unittest.main(verbosity=2)
