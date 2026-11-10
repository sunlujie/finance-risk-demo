"""Shared presentation only; source data and exported values are untouched."""
import pandas as pd
import streamlit as st


def setup(section):
    st.markdown("""<style>
    .stMainBlockContainer {padding-top:2.5rem; padding-bottom:3rem; max-width:1500px;}
    h1 {font-size:2rem!important; letter-spacing:-.03em;}
    h2 {font-size:1.45rem!important; margin-top:1rem!important;}
    h3 {font-size:1.12rem!important; margin-top:.6rem!important;}
    [data-testid="stMetric"] {background:#1A1D24; border:1px solid #2A303C;
      border-radius:12px; padding:18px 20px; min-height:115px;}
    [data-testid="stMetricValue"] {font-size:clamp(1rem,1.65vw,1.65rem); font-variant-numeric:tabular-nums;}
    [data-testid="stMetricLabel"] {color:#A9B4C4;}
    [data-testid="stCaption"] p, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:#A9B4C4!important; line-height:1.6;}
    [data-testid="stSidebar"] {border-right:1px solid #2A303C;}
    [data-testid="stSidebar"] h2 {font-size:1rem!important;}
    [data-testid="stDataFrame"] {border-radius:10px; overflow:hidden;}
    .eyebrow {color:#60A5FA; font-size:.75rem; letter-spacing:.12em; font-weight:600; margin-bottom:.4rem;}
    button, a {transition:background-color .15s;}
    @media(max-width:800px) {[data-testid="stMetricValue"] {font-size:1.3rem;} .stMainBlockContainer {padding-top:1.5rem;}}
    </style>""", unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('### FINANCE / RISK')
        st.caption('金融交易风险监测 · PaySim')
        st.page_link('app.py', label='交易运营概览', icon=':material/dashboard:')
        st.page_link('pages/1_风险交易列表.py', label='风险交易列表', icon=':material/manage_search:')
        st.page_link('pages/2_模型实验对比.py', label='模型实验对比', icon=':material/monitoring:')
        st.page_link('pages/3_批量交易风险预测.py', label='批量交易风险预测', icon=':material/upload_file:')
        st.divider()
    st.markdown(f'<div class="eyebrow">FINANCIAL ANALYTICS / {section}</div>', unsafe_allow_html=True)


def table(data, **kwargs):
    """Apply labels and precision without changing the underlying frame."""
    labels = {'tx_id':'交易 ID', 'step':'交易小时', 'tx_type':'交易类型',
              'amount':'交易金额', 'sender_id':'发起账户', 'receiver_id':'接收账户',
              'risk_score':'风险分数', 'threshold':'告警阈值', 'is_alert':'触发告警',
              'model_version':'模型版本'}
    config = {}
    for col in data.columns:
        label = labels.get(col, col)
        if col == 'risk_score':
            config[col] = st.column_config.ProgressColumn(label, min_value=0, max_value=1, format='%.6f', width='medium')
        elif col in {'threshold', '告警阈值'}:
            config[col] = st.column_config.NumberColumn(label, format='%.6f')
        elif col in {'amount', '交易金额', '数值'}:
            config[col] = st.column_config.NumberColumn(label, format='localized')
        elif pd.api.types.is_float_dtype(data[col]):
            config[col] = st.column_config.NumberColumn(label, format='%.4f')
        elif pd.api.types.is_integer_dtype(data[col]) and col not in {'tx_id','step','起始step','结束step'}:
            config[col] = st.column_config.NumberColumn(label, format='localized')
        elif col in labels:
            config[col] = st.column_config.Column(label)
    kwargs.setdefault('width', 'stretch')
    kwargs.setdefault('column_config', config)
    return st.dataframe(data, **kwargs)
