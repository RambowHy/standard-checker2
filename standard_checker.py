#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准状态查询工具
功能：查询国家标准在 ndls.org.cn 的现行有效性及替代信息
作者：RambowHy
版本：1.0
"""

import pandas as pd
import requests
import json
import argparse
import sys
from datetime import datetime
from typing import Optional, Tuple, List
import time

# API 配置
API_URL = "https://www.ndls.org.cn/api/standard/list"
DETAIL_URL = "https://www.ndls.org.cn/api/standard/detail"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

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


class StandardChecker:
    """国家标准查询器"""
    
    def __init__(self, delay: float = 0.5):
        """
        初始化查询器
        
        Args:
            delay: 每次查询间隔（秒），避免请求过快
        """
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
    def query_single(self, standard_no: str) -> Tuple[str, str, List[dict]]:
        """
        查询单个标准
        
        Args:
            standard_no: 标准号，如 "GB 2757-2012"
            
        Returns:
            tuple: (状态, 错误信息, 替代标准列表)
        """
        try:
            # 查询基本信息
            data = {"a100": standard_no, "page": 1, "limit": 10}
            response = self.session.post(API_URL, json=data, timeout=10)
            
            if response.status_code != 200:
                return None, f"HTTP错误 {response.status_code}", []
            
            result = response.json()
            
            if result.get("code") != 0:
                return None, f"API错误: {result.get('message', '未知错误')}", []
            
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
            
            return friendly_status, None, replacement_list
            
        except requests.exceptions.Timeout:
            return None, "查询超时", []
        except requests.exceptions.RequestException as e:
            return None, f"请求异常: {str(e)}", []
        except Exception as e:
            return None, f"错误: {str(e)}", []
        finally:
            time.sleep(self.delay)
    
    def _get_replacements(self, yf001: str) -> List[dict]:
        """获取替代标准列表"""
        try:
            response = self.session.get(f"{DETAIL_URL}/{yf001}", timeout=10)
            
            if response.status_code != 200:
                return []
            
            result = response.json()
            
            if result.get("code") != 0:
                return []
            
            detail = result.get("data", {})
            replacement_nos = detail.get("a461list", [])
            
            replacements = []
            for replacement_no in replacement_nos:
                # 查询替代标准的名称
                data = {"a100": replacement_no, "page": 1, "limit": 10}
                try:
                    resp = self.session.post(API_URL, json=data, timeout=10)
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
                time.sleep(0.3)
            
            return replacements
            
        except Exception:
            return []
    
    def query_batch(self, standard_nos: List[str]) -> List[dict]:
        """
        批量查询标准
        
        Args:
            standard_nos: 标准号列表
            
        Returns:
            查询结果列表
        """
        results = []
        total = len(standard_nos)
        
        print(f"开始查询 {total} 个标准...")
        print("-" * 80)
        
        for i, standard_no in enumerate(standard_nos, 1):
            print(f"[{i:3d}/{total}] 查询: {standard_no:<25}", end=" ")
            
            status, error, replacements = self.query_single(standard_no)
            
            if error:
                print(f"=> 错误: {error}")
                results.append({
                    "标准号": standard_no,
                    "状态": error,
                    "替代标准": ""
                })
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
        
        print("-" * 80)
        return results


def update_excel(input_file: str, output_file: Optional[str] = None):
    """
    更新Excel文件
    
    Args:
        input_file: 输入Excel文件路径
        output_file: 输出文件路径（默认覆盖原文件）
    """
    if output_file is None:
        output_file = input_file
    
    try:
        # 读取Excel
        print(f"\n读取文件: {input_file}")
        df = pd.read_excel(input_file)
        
        # 确保列存在
        for col in ['ndls状态', 'ndls查询时间', '替代标准号', '替代标准名']:
            if col not in df.columns:
                df[col] = ''
        
        # 获取标准号列表
        standard_nos = df['标准号'].dropna().astype(str).tolist()
        
        # 批量查询
        checker = StandardChecker(delay=0.5)
        results = checker.query_batch(standard_nos)
        
        # 更新DataFrame
        for i, result in enumerate(results):
            df.at[i, 'ndls状态'] = result['状态']
            df.at[i, 'ndls查询时间'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df.at[i, '替代标准号'] = result['替代标准']
            
            # 如果有替代标准，获取名称
            if result.get('替代列表'):
                names = [r['标准名'] for r in result['替代列表']]
                df.at[i, '替代标准名'] = ", ".join(names)
        
        # 保存文件
        df.to_excel(output_file, index=False)
        print(f"\n结果已保存: {output_file}")
        
        # 显示统计
        print("\n状态统计:")
        print(df['ndls状态'].value_counts().to_string())
        
        replaced_count = len(df[df['替代标准号'] != ''])
        if replaced_count > 0:
            print(f"\n发现 {replaced_count} 个有替代标准的记录")
        
    except FileNotFoundError:
        print(f"错误: 找不到文件 '{input_file}'")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='国家标准状态查询工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 查询单个标准
  python standard_checker.py -s "GB 2757-2012"
  
  # 批量查询多个标准
  python standard_checker.py -s "GB 2757-2012" "GB/T 8170-2008"
  
  # 更新Excel文件
  python standard_checker.py -f standards.xlsx
  
  # 更新并保存到新文件
  python standard_checker.py -f standards.xlsx -o standards_updated.xlsx
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
        default=0.5,
        help='查询间隔（秒），默认0.5'
    )
    
    args = parser.parse_args()
    
    if not args.standards and not args.file:
        parser.print_help()
        sys.exit(0)
    
    if args.file:
        # 更新Excel模式
        update_excel(args.file, args.output)
    else:
        # 单个/批量查询模式
        checker = StandardChecker(delay=args.delay)
        results = checker.query_batch(args.standards)
        
        # 显示结果表格
        print("\n查询结果:")
        print("=" * 100)
        print(f"{'标准号':<25} {'状态':<12} {'替代标准'}")
        print("-" * 100)
        for r in results:
            print(f"{r['标准号']:<25} {r['状态']:<12} {r['替代标准']}")
        print("=" * 100)


if __name__ == "__main__":
    main()
