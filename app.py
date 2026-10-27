
from src.app_config import DB_PATH
import duckdb
import pandas as pd
import streamlit as st





st.set_page_config(
    page_title="金融交易风险监测",
    page_icon="📊",
    layout="wide",
)

st.title("金融交易风险监测平台")
st.subheader("交易运营概览")

st.caption(
    "PaySim模拟数据｜展示所选时段的历史交易汇总｜金额单位沿用数据集"
)

if not DB_PATH.is_file():
    st.error(f"数据库不存在：{DB_PATH}")
    st.stop()
def load_hour_type():
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        columns = con.execute(
            "DESCRIBE dws_hour_type"
        ).df()["column_name"].tolist()

        # 兼容你之前使用过的两种金额列名
        if "tx_amount" in columns:
            amount_column = "tx_amount"
        elif "total_amount" in columns:
            amount_column = "total_amount"
        else:
            raise ValueError(
                "dws_hour_type中没有tx_amount或total_amount字段"
            )

        data = con.execute(
            f"""
            SELECT
                step,
                tx_type,
                tx_count,
                {amount_column} AS tx_amount
            FROM dws_hour_type
            ORDER BY step, tx_type
            """
        ).df()

    return data


data = load_hour_type()

if data.empty:
    st.warning("dws_hour_type中没有数据，请先完成数仓建表。")
    st.stop()
st.sidebar.header("筛选条件")

min_step = int(data["step"].min())
max_step = int(data["step"].max())

if min_step < max_step:
    start_step, end_step = st.sidebar.slider(
        "交易小时范围",
        min_value=min_step,
        max_value=max_step,
        value=(min_step, max_step),
        step=1,
    )
else:
    start_step = end_step = min_step

all_types = sorted(data["tx_type"].dropna().unique().tolist())

selected_types = st.sidebar.multiselect(
    "交易类型",
    options=all_types,
    default=all_types,
)

if not selected_types:
    st.info("请至少选择一种交易类型。")
    st.stop()

filtered = data.loc[
    data["step"].between(start_step, end_step)
    & data["tx_type"].isin(selected_types)
].copy()

if filtered.empty:
    st.info("当前筛选条件下没有交易。")
    st.stop()

st.caption(
    f"当前统计范围：step {start_step}～{end_step}，"
    f"交易类型：{', '.join(selected_types)}"
)
total_count = int(filtered["tx_count"].sum())
total_amount = float(filtered["tx_amount"].sum())

average_amount = (
    total_amount / total_count
    if total_count > 0
    else 0.0
)

col1, col2, col3 = st.columns(3)

col1.metric(
    "交易笔数",
    f"{total_count:,}",
)

col2.metric(
    "交易总金额",
    f"{total_amount:,.2f}",
)

col3.metric(
    "平均每笔金额",
    f"{average_amount:,.2f}",
)
# 将不同类型合并，得到每小时的总笔数和总金额
hourly = (
    filtered.groupby("step")[["tx_count", "tx_amount"]]
    .sum()
    .sort_index()
)

# 补齐所选范围内没有交易的小时，显示为0
hourly = hourly.reindex(
    pd.RangeIndex(
        start=start_step,
        stop=end_step + 1,
        name="step",
    ),
    fill_value=0,
)

st.subheader("每小时交易笔数")
st.line_chart(
    hourly.rename(columns={"tx_count": "交易笔数"})[["交易笔数"]]
)

st.subheader("每小时交易金额")
st.line_chart(
    hourly.rename(columns={"tx_amount": "交易金额"})[["交易金额"]]
)

# 将不同时段合并，得到各交易类型的汇总
by_type = (
    filtered.groupby("tx_type")[["tx_count", "tx_amount"]]
    .sum()
    .sort_values("tx_count", ascending=False)
)

by_type["count_share_pct"] = (
    by_type["tx_count"] / total_count * 100
)

st.subheader("各类型交易笔数")
st.bar_chart(
    by_type.rename(columns={"tx_count": "交易笔数"})[["交易笔数"]]
)

st.subheader("各类型交易汇总")

display_table = (
    by_type.reset_index()
    .rename(
        columns={
            "tx_type": "交易类型",
            "tx_count": "交易笔数",
            "tx_amount": "交易金额",
            "count_share_pct": "笔数占比（%）",
        }
    )
)

st.dataframe(
    display_table,
    hide_index=True,
)

st.download_button(
    label="下载当前类型汇总",
    data=display_table.to_csv(index=False).encode("utf-8-sig"),
    file_name="transaction_type_summary.csv",
    mime="text/csv",
)