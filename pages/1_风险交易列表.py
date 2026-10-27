
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import duckdb
import pandas as pd
import streamlit as st
from src.app_config import DB_PATH, USE_API, API_BASE_URL



st.set_page_config(
    page_title="风险交易列表",
    page_icon="🔎",
    layout="wide",
)

st.title("风险交易列表")

st.caption(
    "验证时段开发演示｜展示已保存的风险评分｜告警不等于已经确认欺诈"
)

if not DB_PATH.is_file():
    st.error(f"数据库不存在：{DB_PATH}")
    st.stop()


def query_df(sql, params=None):
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(
            sql,
            params if params is not None else [],
        ).df()
def api_get(path, params=None):
    """调用本机 FastAPI；失败时在页面显示提示。"""
    url = API_BASE_URL + path

    if params:
        url += "?" + urlencode(params)

    try:
        with urlopen(url, timeout=15) as response:
            return json.load(response)

    except HTTPError as exc:
        try:
            detail = json.loads(
                exc.read().decode("utf-8")
            ).get("detail", "接口请求失败")
        except (ValueError, UnicodeDecodeError):
            detail = "接口请求失败"

        st.error(f"API 返回错误 {exc.code}：{detail}")
        st.stop()

    except (URLError, TimeoutError):
        st.error(
            "无法连接风险查询 API 或请求超时。"
            "请确认 FastAPI 已在 127.0.0.1:8000 启动。"
        )
        st.stop()


def load_alerts_from_api(
    model_version,
    start_step,
    end_step,
    selected_type,
    display_limit,
):
    """接口每次最多返回100笔，按需翻页获取页面所需记录。"""
    params = {
        "model_version": model_version,
        "scoring_scope": "validation_demo",
        "start_step": start_step,
        "end_step": end_step,
    }

    if selected_type != "全部":
        params["tx_type"] = selected_type

    items = []
    total = 0

    while len(items) < display_limit:
        batch_limit = min(100, display_limit - len(items))

        payload = api_get(
            "/alerts",
            {
                **params,
                "limit": batch_limit,
                "offset": len(items),
            },
        )

        total = int(payload["total"])
        batch = payload["items"]
        items.extend(batch)

        if not batch or len(items) >= total:
            break

    # 明确列名，确保空结果也具有正确的表结构
    columns = [
        "tx_id",
        "step",
        "tx_type",
        "amount",
        "sender_id",
        "receiver_id",
        "risk_score",
        "threshold",
        "is_alert",
    ]

    return total, pd.DataFrame(items, columns=columns)
versions = query_df("""
    SELECT
        model_version,
        MIN(step) AS min_step,
        MAX(step) AS max_step,
        COUNT(*) AS scored_rows,
        COUNT(*) FILTER (WHERE is_alert) AS alert_rows,
        MIN(threshold) AS min_threshold,
        MAX(threshold) AS max_threshold,
        MAX(scored_at) AS latest_scored_at
    FROM ads_transaction_risk
    WHERE scoring_scope = 'validation_demo'
    GROUP BY model_version
    ORDER BY latest_scored_at DESC, model_version
""")

if versions.empty:
    st.info("暂无评分结果，请先运行评分入库脚本。")
    st.stop()

st.sidebar.header("风险列表筛选")

selected_version = st.sidebar.selectbox(
    "模型版本",
    options=versions["model_version"].tolist(),
)

version_info = versions.loc[
    versions["model_version"] == selected_version
].iloc[0]

if version_info["min_threshold"] != version_info["max_threshold"]:
    st.error("同一个模型版本存在不同阈值，请先检查评分数据。")
    st.stop()

total_scored = int(version_info["scored_rows"])
total_alerts = int(version_info["alert_rows"])
threshold = float(version_info["min_threshold"])

col1, col2, col3 = st.columns(3)

col1.metric("该版本已评分交易", f"{total_scored:,}")
col2.metric("该版本告警交易", f"{total_alerts:,}")
col3.metric("告警阈值", f"{threshold:.6f}")

st.caption(
    "以上三个指标覆盖所选模型版本的全部验证评分记录，"
    "不随下面的时间、类型和告警筛选变化。"
)
min_step = int(version_info["min_step"])
max_step = int(version_info["max_step"])

if min_step < max_step:
    start_step, end_step = st.sidebar.slider(
        "交易小时范围",
        min_value=min_step,
        max_value=max_step,
        value=(min_step, max_step),
    )
else:
    start_step = end_step = min_step

type_data = query_df(
    """
    SELECT DISTINCT d.tx_type
    FROM ads_transaction_risk AS r
    JOIN dwd_transactions AS d
        ON r.tx_id = d.tx_id
    WHERE r.model_version = ?
      AND r.scoring_scope = 'validation_demo'
    ORDER BY d.tx_type
    """,
    [selected_version],
)

selected_type = st.sidebar.selectbox(
    "交易类型",
    options=["全部"] + type_data["tx_type"].tolist(),
)

only_alerts = st.sidebar.checkbox(
    "只看告警交易",
    value=True,
)

display_limit = int(
    st.sidebar.selectbox(
        "最多显示多少笔",
        options=[100, 500, 2000],
        index=0,
    )
)
if only_alerts and USE_API:
    # 本地模式：告警列表通过 FastAPI 查询
    matched_rows, risk_list = load_alerts_from_api(
        model_version=selected_version,
        start_step=start_step,
        end_step=end_step,
        selected_type=selected_type,
        display_limit=display_limit,
    )

else:
    # 展示模式直接查询数据库
    conditions = [
        "r.model_version = ?",
        "r.scoring_scope = 'validation_demo'",
        "r.step BETWEEN ? AND ?",
    ]

    params = [
        selected_version,
        start_step,
        end_step,
    ]

    if selected_type != "全部":
        conditions.append("d.tx_type = ?")
        params.append(selected_type)

    if only_alerts:
        conditions.append("r.is_alert = TRUE")

    where_sql = " AND ".join(conditions)

    count_result = query_df(
        f"""
        SELECT COUNT(*) AS matched_rows
        FROM ads_transaction_risk AS r
        JOIN dwd_transactions AS d
            ON r.tx_id = d.tx_id
        WHERE {where_sql}
        """,
        params,
    )

    matched_rows = int(count_result.iloc[0]["matched_rows"])

    risk_list = query_df(
        f"""
        SELECT
            r.tx_id,
            r.step,
            d.tx_type,
            d.amount,
            d.sender_id,
            d.receiver_id,
            r.risk_score,
            r.threshold,
            r.is_alert
        FROM ads_transaction_risk AS r
        JOIN dwd_transactions AS d
            ON r.tx_id = d.tx_id
        WHERE {where_sql}
        ORDER BY r.risk_score DESC, r.tx_id ASC
        LIMIT ?
        """,
        params + [display_limit],
    )
st.write(
    f"当前条件共匹配 **{matched_rows:,}** 笔交易，"
    f"下表显示风险排序前 **{len(risk_list):,}** 笔。"
)

if risk_list.empty:
    st.info("当前筛选条件下没有交易，请调整筛选条件。")
    st.stop()

st.dataframe(
    risk_list,
    hide_index=True,
)

st.download_button(
    label="下载当前显示的交易列表",
    data=risk_list.to_csv(index=False).encode("utf-8-sig"),
    file_name="risk_transactions.csv",
    mime="text/csv",
)

st.caption("下载内容仅包含当前表格显示的记录，不是全部匹配记录。")
st.subheader("查看单笔交易背景")

selected_tx_id = st.selectbox(
    "从当前列表选择交易ID",
    options=risk_list["tx_id"].tolist(),
)

selected_transaction = risk_list.loc[
    risk_list["tx_id"] == selected_tx_id
].iloc[0]

if USE_API:
    transaction_detail = api_get(
        f"/transactions/{int(selected_tx_id)}"
    )
else:
    # 当前列表已经包含这笔交易的基础信息，可以直接使用
    transaction_detail = {
        "tx_id": int(selected_transaction["tx_id"]),
        "step": int(selected_transaction["step"]),
        "tx_type": selected_transaction["tx_type"],
        "amount": float(selected_transaction["amount"]),
        "sender_id": selected_transaction["sender_id"],
        "receiver_id": selected_transaction["receiver_id"],
    }

st.write(
    f"交易类型：{transaction_detail['tx_type']} ｜ "
    f"交易小时：{transaction_detail['step']}"
)

st.write(
    f"发起账户：{transaction_detail['sender_id']} ｜ "
    f"接收账户：{transaction_detail['receiver_id']}"
)

detail_col1, detail_col2, detail_col3 = st.columns(3)

detail_col1.metric(
    "当前交易金额",
    f"{transaction_detail['amount']:,.2f}",
)

detail_col2.metric(
    "模型风险分数",
    f"{selected_transaction['risk_score']:.6f}",
)

detail_col3.metric(
    "是否告警",
    "是" if selected_transaction["is_alert"] else "否",
)

history = query_df(
    """
    SELECT
        receiver_cnt_1h,
        receiver_sum_1h,
        receiver_avg_1h,

        receiver_cnt_24h,
        receiver_sum_24h,
        receiver_avg_24h,

        receiver_cnt_168h,
        receiver_sum_168h,
        receiver_avg_168h

    FROM feature_transactions
    WHERE tx_id = ?
    """,
    [int(selected_tx_id)],
)

if history.empty:
    st.warning("没有找到这笔交易对应的历史特征。")
else:
    # 转置后，一行显示一个特征，方便阅读
    history_display = history.iloc[0].rename("数值").to_frame()
    history_display.index.name = "历史特征"

    st.dataframe(history_display)

st.caption(
    "历史统计仅使用当前交易小时之前的记录。"
    "缺失均值表示没有可计算的历史，并不等于金额为0。"
)

st.info(
    "当前演示使用A基础模型，接收端历史字段仅作为交易背景展示，"
    "并未参与A模型评分，也不代表模型的判定原因。"
)