#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准状态查询 - Web应用
基于Streamlit构建
"""

import base64
import hashlib
import io
import threading
from datetime import datetime

import pandas as pd
import streamlit as st

from core import ProgressTracker, normalize_standard_nos
from web_checker import WebStandardChecker

OUTPUT_COLUMNS = ['ndls状态', 'ndls查询时间', '替代标准号', '替代标准名']

st.set_page_config(
  page_title="国家标准状态查询",
  page_icon="📋",
  layout="wide",
  initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .main-header {
    font-size: 2.5rem;
    font-weight: bold;
    color: #1f77b4;
    margin-bottom: 1rem;
  }
  .sub-header {
    font-size: 1.2rem;
    color: #666;
    margin-bottom: 2rem;
  }
</style>
""", unsafe_allow_html=True)


def get_download_link(df, filename="查询结果.xlsx"):
  output = io.BytesIO()
  with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='查询结果')
  output.seek(0)
  b64 = base64.b64encode(output.read()).decode()
  return (
    f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}"'
    f' download="{filename}" style="text-decoration: none;">'
    f'<button style="background-color: #4CAF50; color: white; padding: 10px 20px;'
    f' border: none; border-radius: 5px; cursor: pointer; font-size: 16px;">'
    f'📥 下载结果文件</button></a>'
  )


def fill_result_columns(df, results):
  """把查询结果按标准号回填到 DataFrame（重复行全部回填）"""
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  result_map = {r.标准号: r for r in results}
  matched = df['标准号'].isin(result_map.keys())
  for idx in df[matched].index:
    result = result_map[df.at[idx, '标准号']]
    df.at[idx, 'ndls状态'] = result.错误 or result.状态 or ""
    df.at[idx, 'ndls查询时间'] = now_str
    df.at[idx, '替代标准号'] = result.替代标准号
    df.at[idx, '替代标准名'] = result.替代标准名
  return df


def render_result_panel(df, checker, standard_nos, *, auto_clean=True):
  """渲染统计、完整结果与下载；全部完成时自动清理进度"""
  st.subheader("📈 查询结果统计")
  col_stat1, col_stat2, col_stat3 = st.columns(3)

  with col_stat1:
    st.write("状态分布:")
    st.write(df['ndls状态'].value_counts().to_string())

  with col_stat2:
    replaced_count = len(df[df['替代标准号'] != ''])
    st.metric("有替代标准的记录", replaced_count)

  with col_stat3:
    completed_count = checker.tracker.completed_count()
    st.metric("已完成查询", f"{completed_count}/{len(standard_nos)}")

  with st.expander("👁️ 查看完整结果"):
    st.dataframe(df, use_container_width=True)

  st.subheader("💾 下载结果")
  st.markdown(get_download_link(df), unsafe_allow_html=True)

  if auto_clean and checker.tracker.completed_count() == len(standard_nos):
    checker.tracker.clear()
    st.info("🗑️ 所有数据查询完毕，进度文件已自动清理")


def render_progress_panel(df, standard_nos):
  """后台线程执行查询，fragment 每秒轮询状态并支持取消"""
  job = st.session_state.job

  @st.fragment(run_every=1.0)
  def panel():
    if job['error'] is not None:
      container.error(f"❌ 查询过程中出错: {job['error']}")
      return

    if not job['done'] and not job['cancel_event'].is_set():
      if st.button("⏹️ 取消查询", type="secondary"):
        job['cancel_event'].set()
        st.rerun()
      st.progress(job['progress'][0] / max(job['progress'][1], 1),
                  text=f"⏳ {job['status_msg']}")
      st.code('\n'.join(job['logs'][-20:]), language='text')
      return

    if job['cancel_event'].is_set() and not job['done']:
      st.warning("⏹️ 已取消，已完成条目已保存进度，重新点击「开始查询」可继续")
      return

    results = [job['checker'].tracker.get_result(s) for s in standard_nos
               if job['checker'].tracker.is_completed(s)]
    fill_result_columns(df, results)
    render_result_panel(df, job['checker'], standard_nos)

  panel()


def start_job(checker, pending_nos):
  """在后台线程中启动批量查询，线程间通过共享 job 字典传递状态"""
  job = {
    'checker': checker,
    'done': False,
    'error': None,
    'cancel_event': threading.Event(),
    'progress': (0, len(pending_nos)),
    'status_msg': "准备中...",
    'logs': [],
    'df': None,
  }

  def worker():
    try:
      checker.query_batch_with_callback(
        pending_nos,
        progress_callback=lambda current, total, msg: job.update(
          progress=(current, total), status_msg=msg),
        log_callback=lambda msg: job['logs'].append(msg),
        should_stop=job['cancel_event'].is_set,
      )
      if not job['cancel_event'].is_set():
        job['done'] = True
    except Exception as e:
      job['error'] = str(e)

  threading.Thread(target=worker, daemon=True).start()
  st.session_state.job = job


def main():
  st.markdown('<div class="main-header">📋 国家标准状态查询工具</div>', unsafe_allow_html=True)
  st.markdown('<div class="sub-header">自动查询国家标准在 ndls.org.cn 的现行有效性及替代信息</div>', unsafe_allow_html=True)

  with st.sidebar:
    st.header("⚙️ 查询设置")

    delay = st.slider(
      "查询间隔（秒）",
      min_value=1.0, max_value=10.0, value=5.0, step=0.5,
      help="每次查询之间的间隔时间，建议3-5秒以避免触发限流",
    )

    max_retries = st.slider(
      "最大重试次数",
      min_value=1, max_value=10, value=3, step=1,
      help="限流或服务端错误（429/5xx）时的最大重试次数",
    )

    use_proxy = st.text_input(
      "代理地址（可选）",
      placeholder="http://127.0.0.1:7890",
      help="如果需要代理访问，请填写代理地址",
    )

    st.divider()
    st.info("""
    **使用说明：**
    1. 上传包含"标准号"列的Excel文件
    2. 设置合适的查询间隔
    3. 点击"开始查询"
    4. 等待查询完成并下载结果

    **注意：**
    - Excel文件必须包含名为"标准号"的列
    - 查询过程可能需要几分钟，可随时取消
    - 程序会自动保存进度，刷新页面不会丢失
    """)

  col1, col2 = st.columns([2, 1])

  df = None
  progress_file = None

  with col1:
    st.subheader("📁 上传文件")
    uploaded_file = st.file_uploader(
      "选择Excel文件",
      type=['xlsx', 'xls'],
      help="支持 .xlsx 和 .xls 格式",
    )

    if uploaded_file is not None:
      try:
        df = pd.read_excel(uploaded_file)
        st.success(f"✅ 成功读取文件，共 {len(df)} 行数据")

        if '标准号' not in df.columns:
          st.error("❌ 文件缺少必需的'标准号'列，请检查文件格式")
          return

        with st.expander("👁️ 查看数据预览"):
          st.dataframe(df.head(10), use_container_width=True)
          st.caption(f"显示前10行，共{len(df)}行")

        for col in OUTPUT_COLUMNS:
          if col not in df.columns:
            df[col] = ''

        df['标准号'] = df['标准号'].dropna().astype(str).map(str.strip)

        file_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()[:12]
        progress_file = f".web_query_progress_{file_hash}.pkl"

      except Exception as e:
        st.error(f"❌ 读取文件失败: {e}")
        return

  with col2:
    st.subheader("📊 统计信息")
    if df is not None:
      raw_nos = df['标准号'].dropna().astype(str).tolist()
      standard_nos = normalize_standard_nos(raw_nos)
      st.metric("总记录数", len(df))
      st.metric("有效标准号（去重后）", len(standard_nos))
      estimated_time = len(standard_nos) * delay / 60
      st.metric("预估耗时", f"{estimated_time:.1f} 分钟")

  if df is None:
    return

  standard_nos = normalize_standard_nos(df['标准号'].dropna().astype(str).tolist())

  st.divider()
  st.subheader("🚀 执行查询")

  col_btn1, col_btn2, _ = st.columns([1, 1, 3])

  with col_btn1:
    start_button = st.button("▶️ 开始查询", type="primary", use_container_width=True)

  with col_btn2:
    clear_button = st.button("🔄 重置进度", use_container_width=True)

  job = st.session_state.get('job')
  if job is not None and not job['done'] and job['error'] is None:
    if job['cancel_event'].is_set():
      st.warning("⏹️ 已取消，已完成条目已保存进度，重新点击「开始查询」可继续")
      return
    render_progress_panel(df, standard_nos)
    return

  if clear_button:
    session_checker = st.session_state.get('checker')
    if session_checker is not None and session_checker.tracker.progress_file == progress_file:
      session_checker.tracker.clear()
    else:
      ProgressTracker(progress_file).clear()
    st.session_state.pop('job', None)
    st.success("✅ 进度已重置")
    st.rerun()

  if start_button:
    proxy = use_proxy if use_proxy else None
    checker = WebStandardChecker(
      delay=delay, max_retries=max_retries, use_proxy=proxy,
      progress_file=progress_file,
    )
    st.session_state.checker = checker

    pending_nos = [s for s in standard_nos if not checker.tracker.is_completed(s)]
    skipped = len(standard_nos) - len(pending_nos)

    if skipped > 0:
      st.info(f"⏭️ 跳过已完成的 {skipped} 条记录，剩余 {len(pending_nos)} 条待查询")

    if not pending_nos:
      results = [checker.tracker.get_result(s) for s in standard_nos
                 if checker.tracker.is_completed(s)]
      fill_result_columns(df, results)
      render_result_panel(df, checker, standard_nos)
      return

    start_job(checker, pending_nos)
    st.rerun()


if __name__ == "__main__":
  main()
