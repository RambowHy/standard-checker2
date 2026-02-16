#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家标准状态查询 - Web应用
基于Streamlit构建
"""

import streamlit as st
import pandas as pd
import io
import base64
from datetime import datetime
from web_checker import WebStandardChecker

# 页面配置
st.set_page_config(
  page_title="国家标准状态查询",
  page_icon="📋",
  layout="wide",
  initial_sidebar_state="expanded"
)

# CSS样式
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
  .info-box {
    background-color: #f0f2f6;
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
  }
  .success-box {
    background-color: #d4edda;
    color: #155724;
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
  }
  .error-box {
    background-color: #f8d7da;
    color: #721c24;
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
  }
</style>
""", unsafe_allow_html=True)


def get_download_link(df, filename="查询结果.xlsx"):
  """生成Excel下载链接"""
  output = io.BytesIO()
  with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='查询结果')
  output.seek(0)
  
  b64 = base64.b64encode(output.read()).decode()
  return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}" style="text-decoration: none;"><button style="background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px;">📥 下载结果文件</button></a>'


def main():
  # 标题区域
  st.markdown('<div class="main-header">📋 国家标准状态查询工具</div>', unsafe_allow_html=True)
  st.markdown('<div class="sub-header">自动查询国家标准在 ndls.org.cn 的现行有效性及替代信息</div>', unsafe_allow_html=True)
  
  # 侧边栏 - 参数设置
  with st.sidebar:
    st.header("⚙️ 查询设置")
    
    delay = st.slider(
      "查询间隔（秒）",
      min_value=1.0,
      max_value=10.0,
      value=3.0,
      step=0.5,
      help="每次查询之间的间隔时间，建议3-5秒以避免触发限流"
    )
    
    max_retries = st.slider(
      "最大重试次数",
      min_value=1,
      max_value=10,
      value=5,
      step=1,
      help="查询失败时的最大重试次数"
    )
    
    use_proxy = st.text_input(
      "代理地址（可选）",
      placeholder="http://127.0.0.1:7890",
      help="如果需要代理访问，请填写代理地址"
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
    - 查询过程可能需要几分钟，请耐心等待
    - 程序会自动保存进度，刷新页面不会丢失
    """)
  
  # 主内容区
  col1, col2 = st.columns([2, 1])
  
  with col1:
    st.subheader("📁 上传文件")
    uploaded_file = st.file_uploader(
      "选择Excel文件",
      type=['xlsx', 'xls'],
      help="支持 .xlsx 和 .xls 格式"
    )
    
    if uploaded_file is not None:
      # 读取并显示文件预览
      try:
        df = pd.read_excel(uploaded_file)
        st.success(f"✅ 成功读取文件，共 {len(df)} 行数据")
        
        # 检查必需的列
        if '标准号' not in df.columns:
          st.error("❌ 文件缺少必需的'标准号'列，请检查文件格式")
          return
        
        # 显示数据预览
        with st.expander("👁️ 查看数据预览"):
          st.dataframe(df.head(10), use_container_width=True)
          st.caption(f"显示前10行，共{len(df)}行")
        
        # 准备输出列
        for col in ['ndls状态', 'ndls查询时间', '替代标准号', '替代标准名']:
          if col not in df.columns:
            df[col] = ''
        
      except Exception as e:
        st.error(f"❌ 读取文件失败: {str(e)}")
        return
  
  with col2:
    st.subheader("📊 统计信息")
    if uploaded_file is not None:
      total = len(df)
      valid_count = df['标准号'].notna().sum()
      
      st.metric("总记录数", total)
      st.metric("有效标准号", valid_count)
      
      # 预估时间
      estimated_time = total * delay / 60
      st.metric("预估耗时", f"{estimated_time:.1f} 分钟")
  
  # 查询执行区域
  if uploaded_file is not None and 'df' in locals():
    st.divider()
    st.subheader("🚀 执行查询")
    
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 3])
    
    with col_btn1:
      start_button = st.button("▶️ 开始查询", type="primary", use_container_width=True)
    
    with col_btn2:
      clear_button = st.button("🔄 重置进度", use_container_width=True)
    
    if clear_button:
      # 清除session state中的进度
      if 'checker' in st.session_state:
        st.session_state.checker.tracker.clear()
      st.success("✅ 进度已重置")
      st.rerun()
    
    if start_button:
      # 执行查询
      proxy = use_proxy if use_proxy else None
      
      # 初始化查询器
      checker = WebStandardChecker(
        delay=delay,
        max_retries=max_retries,
        use_proxy=proxy
      )
      st.session_state.checker = checker
      
      # 获取标准号列表
      standard_nos = df['标准号'].dropna().astype(str).tolist()
      
      # 过滤已完成的
      pending_nos = [s for s in standard_nos if not checker.tracker.is_completed(s)]
      skipped = len(standard_nos) - len(pending_nos)
      
      if skipped > 0:
        st.info(f"⏭️ 跳过已完成的 {skipped} 条记录，剩余 {len(pending_nos)} 条待查询")
      
      if not pending_nos:
        st.success("✅ 所有记录已查询完毕！")
      else:
        # 进度显示区域
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.empty()
        
        log_messages = []
        
        # 执行批量查询
        try:
          results = checker.query_batch_with_callback(
            pending_nos,
            progress_callback=lambda current, total, msg: (
              progress_bar.progress(current / total),
              status_text.text(f"⏳ 查询进度: {current}/{total} ({current/total*100:.1f}%) - {msg}")
            ),
            log_callback=lambda msg: log_messages.append(msg) or log_container.code('\n'.join(log_messages[-20:]), language='text')
          )
          
          # 更新DataFrame
          for result in results:
            mask = df['标准号'] == result['标准号']
            if mask.any():
              idx = df[mask].index[0]
              df.at[idx, 'ndls状态'] = result['状态']
              df.at[idx, 'ndls查询时间'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
              df.at[idx, '替代标准号'] = result['替代标准']
              
              if result.get('替代列表'):
                names = [r['标准名'] for r in result['替代列表']]
                df.at[idx, '替代标准名'] = ", ".join(names)
          
          # 显示完成信息
          st.success("✅ 查询完成！")
          
          # 统计
          st.subheader("📈 查询结果统计")
          col_stat1, col_stat2, col_stat3 = st.columns(3)
          
          with col_stat1:
            status_counts = df['ndls状态'].value_counts()
            st.write("状态分布:")
            st.write(status_counts.to_string())
          
          with col_stat2:
            replaced_count = len(df[df['替代标准号'] != ''])
            st.metric("有替代标准的记录", replaced_count)
          
          with col_stat3:
            completed_count = len(checker.tracker.completed)
            st.metric("已完成查询", f"{completed_count}/{len(standard_nos)}")
          
          # 结果显示
          with st.expander("👁️ 查看完整结果"):
            st.dataframe(df, use_container_width=True)
          
          # 下载按钮
          st.subheader("💾 下载结果")
          st.markdown(get_download_link(df), unsafe_allow_html=True)
          
          # 如果全部完成，清理进度文件
          if len(checker.tracker.completed) == len(standard_nos):
            checker.tracker.clear()
            st.info("🗑️ 所有数据查询完毕，进度文件已自动清理")
          
        except Exception as e:
          st.error(f"❌ 查询过程中出错: {str(e)}")
          st.exception(e)


if __name__ == "__main__":
  main()
