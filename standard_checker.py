#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准状态查询工具
功能：查询国家标准在 ndls.org.cn 的现行有效性及替代信息
作者：RambowHy
版本：2.0 - 支持大批量查询和断点续传
"""

import pandas as pd
import requests
import json
import argparse
import sys
import os
import re
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
import time
import pickle

# API 配置
API_URL = "https://www.ndls.org.cn/api/standard/list"
DETAIL_URL = "https://www.ndls.org.cn/api/standard/detail"

# User-Agent 轮换列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# 状态映射
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
    """进度跟踪器 - 支持断点续传"""
    
    def __init__(self, progress_file: str = ".query_progress.pkl"):
        self.progress_file = progress_file
        self.completed = set()
        self.failed = {}
        self.load()
    
    def load(self):
        """加载进度"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'rb') as f:
                    data = pickle.load(f)
                    self.completed = data.get('completed', set())
                    self.failed = data.get('failed', {})
                print(f"[进度] 已加载进度: {len(self.completed)} 条已完成, {len(self.failed)} 条失败")
            except Exception as e:
                print(f"[警告] 加载进度文件失败: {e}")
                self.completed = set()
                self.failed = {}
    
    def save(self):
        """保存进度"""
        try:
            with open(self.progress_file, 'wb') as f:
                pickle.dump({
                    'completed': self.completed,
                    'failed': self.failed
                }, f)
        except Exception as e:
            print(f"[警告] 保存进度文件失败: {e}")
    
    def mark_completed(self, standard_no: str):
        """标记为已完成"""
        self.completed.add(standard_no)
        if standard_no in self.failed:
            del self.failed[standard_no]
        self.save()
    
    def mark_failed(self, standard_no: str, error: str):
        """标记为失败"""
        self.failed[standard_no] = error
        self.save()
    
    def is_completed(self, standard_no: str) -> bool:
        """检查是否已完成"""
        return standard_no in self.completed
    
    def clear(self):
        """清除进度"""
        self.completed = set()
        self.failed = {}
        if os.path.exists(self.progress_file):
            os.remove(self.progress_file)
        print("[进度] 已清除所有进度")


class StandardChecker:
    """国家标准查询器"""
    
    def __init__(self, delay: float = 3.0, max_retries: int = 5, use_proxy: Optional[str] = None):
        """
        初始化查询器
        
        Args:
            delay: 每次查询间隔（秒），默认3秒
            max_retries: 最大重试次数
            use_proxy: 代理地址，如 "http://127.0.0.1:7890"
        """
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
        
        # 统计信息
        self.stats = {
            'success': 0,
            'failed': 0,
            'rate_limited': 0,
            'start_time': None
        }
    
    def _update_headers(self):
        """更新请求头（轮换User-Agent）"""
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
        """计算等待时间（指数退避+随机抖动）"""
        base_wait = self.delay * (2 ** retry_count)
        jitter = random.uniform(0, 1)  # 0-1秒随机抖动
        return base_wait + jitter
    
    def query_single(self, standard_no: str) -> Tuple[Optional[str], Optional[str], List[dict]]:
        """
        查询单个标准
        
        Args:
            standard_no: 标准号，如 "GB 2757-2012"
            
        Returns:
            tuple: (状态, 错误信息, 替代标准列表)
        """
        retry_count = 0
        last_error = None
        
        while retry_count <= self.max_retries:
            try:
                # 轮换User-Agent
                if retry_count > 0:
                    self._update_headers()
                
                # 查询基本信息
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
                    
                    # 检查是否是限流错误
                    if '限流' in error_msg or '验证码' in error_msg:
                        self.stats['rate_limited'] += 1
                        if retry_count < self.max_retries:
                            retry_count += 1
                            wait_time = self._calculate_wait_time(retry_count)
                            print(f"\n  [!] 触发限流，等待 {wait_time:.1f} 秒后重试 ({retry_count}/{self.max_retries})...")
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
                
                # 如果被代替，查询替代标准
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
                if retry_count == 0:  # 只在非重试时执行基础延迟
                    time.sleep(self.delay)
        
        self.stats['failed'] += 1
        return None, last_error or "超过最大重试次数", []
    
    def _get_replacements(self, yf001: str) -> List[dict]:
        """获取替代标准列表"""
        try:
            response = self.session.get(f"{DETAIL_URL}/{yf001}", timeout=15)
            
            if response.status_code != 200:
                return []
            
            result = response.json()
            
            if result.get("code") != 0:
                return []
            
            detail = result.get("data", {})
            replacement_nos_raw = detail.get("a461list", [])
            
            # 提取标准号，格式如 "被GB 2716-2018代替" -> "GB 2716-2018"
            replacement_nos = []
            for raw in replacement_nos_raw:
                match = re.search(r'被(.+?)代替', raw)
                if match:
                    replacement_nos.append(match.group(1))
                else:
                    replacement_nos.append(raw)
            
            replacements = []
            for replacement_no in replacement_nos:
                # 查询替代标准的名称
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
                time.sleep(self.delay * 0.5)  # 替代标准查询使用半延迟
            
            return replacements
            
        except Exception:
            return []
    
    def query_batch(self, standard_nos: List[str], tracker: Optional[ProgressTracker] = None, 
                    resume: bool = True) -> List[dict]:
        """
        批量查询标准
        
        Args:
            standard_nos: 标准号列表
            tracker: 进度跟踪器
            resume: 是否启用断点续传
            
        Returns:
            查询结果列表
        """
        results = []
        total = len(standard_nos)
        self.stats['start_time'] = time.time()
        
        # 过滤已完成的
        if resume and tracker:
            pending_nos = [s for s in standard_nos if not tracker.is_completed(s)]
            skipped = total - len(pending_nos)
            if skipped > 0:
                print(f"[进度] 跳过已完成的 {skipped} 条，剩余 {len(pending_nos)} 条待查询")
        else:
            pending_nos = standard_nos
        
        if not pending_nos:
            print("[完成] 所有标准已查询完毕")
            return []
        
        print(f"\n开始查询 {len(pending_nos)} 个标准...")
        print(f"查询间隔: {self.delay}秒 | 最大重试: {self.max_retries}次")
        print("-" * 100)
        
        for i, standard_no in enumerate(pending_nos, 1):
            # 计算预估时间
            elapsed = time.time() - self.stats['start_time']
            avg_time = elapsed / i if i > 0 else 0
            remaining = len(pending_nos) - i
            eta = avg_time * remaining
            eta_str = str(timedelta(seconds=int(eta)))
            
            print(f"[{i:3d}/{len(pending_nos)}] [{standard_no:<25}] ETA: {eta_str}", end=" ")
            
            status, error, replacements = self.query_single(standard_no)
            
            if error:
                print(f"=> 错误: {error}")
                results.append({
                    "标准号": standard_no,
                    "状态": error,
                    "替代标准": ""
                })
                if tracker:
                    tracker.mark_failed(standard_no, error)
            else:
                replacement_str = ""
                if replacements:
                    replacement_str = ", ".join([r["标准号"] for r in replacements])
                    print(f"=> {status} (替代: {replacement_str})")
                else:
                    print(f"=> {status}")
                
                results.append({
                    "标准号": standard_no,
                    "状态": status,
                    "替代标准": replacement_str,
                    "替代列表": replacements
                })
                if tracker:
                    tracker.mark_completed(standard_no)
        
        print("-" * 100)
        
        # 显示统计
        total_time = time.time() - self.stats['start_time']
        print(f"\n查询统计:")
        print(f"  总计: {len(pending_nos)} 条")
        print(f"  成功: {self.stats['success']} 条")
        print(f"  失败: {self.stats['failed']} 条")
        print(f"  限流: {self.stats['rate_limited']} 次")
        print(f"  耗时: {timedelta(seconds=int(total_time))}")
        print(f"  平均: {total_time/len(pending_nos):.2f} 秒/条")
        
        return results


def update_excel(input_file: str, output_file: Optional[str] = None, 
                 delay: float = 3.0, resume: bool = True, 
                 clear_progress: bool = False, proxy: Optional[str] = None):
    """
    更新Excel文件
    
    Args:
        input_file: 输入Excel文件路径
        output_file: 输出文件路径（默认覆盖原文件）
        delay: 查询间隔（秒）
        resume: 是否启用断点续传
        clear_progress: 是否清除进度重新开始
        proxy: 代理地址
    """
    if output_file is None:
        output_file = input_file
    
    # 初始化进度跟踪器
    progress_file = f"{input_file}.progress.pkl"
    tracker = ProgressTracker(progress_file)
    
    if clear_progress:
        tracker.clear()
    
    try:
        # 读取Excel
        print(f"\n读取文件: {input_file}")
        df = pd.read_excel(input_file)
        
        print(f"数据行数: {len(df)}")
        
        # 确保列存在
        for col in ['ndls状态', 'ndls查询时间', '替代标准号', '替代标准名']:
            if col not in df.columns:
                df[col] = ''
        
        # 获取标准号列表
        standard_nos = df['标准号'].dropna().astype(str).tolist()
        
        # 批量查询
        checker = StandardChecker(delay=delay, use_proxy=proxy)
        results = checker.query_batch(standard_nos, tracker=tracker, resume=resume)
        
        # 更新DataFrame
        for result in results:
            # 找到对应的行索引
            mask = df['标准号'] == result['标准号']
            if mask.any():
                idx = df[mask].index[0]
                df.at[idx, 'ndls状态'] = result['状态']
                df.at[idx, 'ndls查询时间'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                df.at[idx, '替代标准号'] = result['替代标准']
                
                # 如果有替代标准，获取名称
                if result.get('替代列表'):
                    names = [r['标准名'] for r in result['替代列表']]
                    df.at[idx, '替代标准名'] = ", ".join(names)
        
        # 保存文件
        df.to_excel(output_file, index=False)
        print(f"\n结果已保存: {output_file}")
        
        # 显示统计
        print("\n状态统计:")
        print(df['ndls状态'].value_counts().to_string())
        
        replaced_count = len(df[df['替代标准号'] != ''])
        if replaced_count > 0:
            print(f"\n发现 {replaced_count} 个有替代标准的记录")
        
        # 清理进度文件（如果全部完成）
        if len(tracker.completed) == len(standard_nos):
            tracker.clear()
            print("\n[完成] 所有数据查询完毕，进度文件已清理")
        else:
            print(f"\n[提示] 还有 {len(standard_nos) - len(tracker.completed)} 条未查询，可重新运行继续")
        
    except FileNotFoundError:
        print(f"错误: 找不到文件 '{input_file}'")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='国家标准状态查询工具 v2.0 - 支持大批量查询和断点续传',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 查询单个标准
  python standard_checker.py -s "GB 2757-2012"
  
  # 批量查询（默认间隔3秒）
  python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"
  
  # 更新Excel文件（推荐间隔3-5秒）
  python standard_checker.py -f standards.xlsx -d 3.0
  
  # 清除进度重新开始
  python standard_checker.py -f standards.xlsx --clear-progress
  
  # 使用代理
  python standard_checker.py -f standards.xlsx --proxy http://127.0.0.1:7890
  
  # 300条数据推荐配置
  python standard_checker.py -f standards.xlsx -d 5.0 -o output.xlsx
  
说明:
  - 程序自动保存进度，中断后可重新运行继续查询
  - 进度文件保存在输入文件同目录（.progress.pkl）
  - 遇到限流会自动重试，最多5次，使用指数退避策略
        """
    )
    
    parser.add_argument(
        '-s', '--standards',
        nargs='+',
        help='要查询的标准号列表（空格分隔）'
    )
    
    parser.add_argument(
        '-f', '--file',
        help='Excel文件路径（将更新文件中的状态列）'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='输出文件路径（默认覆盖原文件）'
    )
    
    parser.add_argument(
        '-d', '--delay',
        type=float,
        default=3.0,
        help='查询间隔（秒），默认3.0，建议3-5秒'
    )
    
    parser.add_argument(
        '--clear-progress',
        action='store_true',
        help='清除进度重新开始'
    )
    
    parser.add_argument(
        '--proxy',
        help='代理地址，如 http://127.0.0.1:7890'
    )
    
    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='禁用断点续传（默认启用）'
    )
    
    args = parser.parse_args()
    
    if not args.standards and not args.file:
        parser.print_help()
        sys.exit(0)
    
    if args.file:
        # 更新Excel模式
        update_excel(
            args.file, 
            args.output, 
            delay=args.delay,
            resume=not args.no_resume,
            clear_progress=args.clear_progress,
            proxy=args.proxy
        )
    else:
        # 单个/批量查询模式
        checker = StandardChecker(delay=args.delay, use_proxy=args.proxy)
        results = checker.query_batch(args.standards)
        
        # 显示结果表格
        print("\n查询结果:")
        print("=" * 100)
        print(f"{'标准号':<25} {'状态':<20} {'替代标准'}")
        print("-" * 100)
        for r in results:
            print(f"{r['标准号']:<25} {r['状态']:<20} {r['替代标准']}")
        print("=" * 100)


if __name__ == "__main__":
    main()
