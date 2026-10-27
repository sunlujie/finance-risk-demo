from pathlib import Path
from io import BytesIO
import hashlib

import joblib
import numpy as np
import pandas as pd
import streamlit as st

from src.train_baselines import make_matrix


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = (
    PROJECT_ROOT / "models" / "baseline_v1" / "A_base.joblib"
)

# 上传文件必须提供的字段
REQUIRED_COLUMNS = ["step", "tx_type", "amount"]

# 程序规范化后保留的字段
INPUT_COLUMNS = ["tx_id", "step", "tx_type", "amount"]
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000

RESULT_KEY = "upload_prediction_result"
CONTEXT_KEY = "upload_prediction_context"


def validate_upload(raw, allowed_types):
    """验证并规范化原始交易；发现问题时停止预测。"""
    missing = set(REQUIRED_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"缺少必填字段：{sorted(missing)}")

    if raw.empty:
        raise ValueError("CSV 没有交易记录。")

    if len(raw) > MAX_ROWS:
        raise ValueError(f"一次最多上传 {MAX_ROWS:,} 笔交易。")

    # 仅选取原始输入字段，不使用用户上传的标签或衍生特征
    # 仅保留模型需要的原始字段，额外列自动忽略
    data = raw[REQUIRED_COLUMNS].copy()

    if "tx_id" in raw.columns:
        # 用户提供编号时，保留原编号
        data.insert(0, "tx_id", raw["tx_id"])
    else:
        # 用户未提供编号时，按上传文件中的记录顺序生成
        generated_ids = [
            f"upload_{i:06d}"
            for i in range(1, len(data) + 1)
        ]
        data.insert(0, "tx_id", generated_ids)

    for column in ["tx_id", "tx_type"]:
        data[column] = data[column].astype("string").str.strip()

        if data[column].isna().any() or data[column].eq("").any():
            raise ValueError(f"{column} 存在空值。")

    if data["tx_id"].duplicated().any():
        raise ValueError("tx_id 存在重复，请保证文件内每笔交易编号唯一。")

    unknown_types = sorted(
        set(data["tx_type"]) - set(allowed_types)
    )
    if unknown_types:
        raise ValueError(f"存在不支持的交易类型：{unknown_types}")

    for column in ["step", "amount"]:
        values = pd.to_numeric(data[column], errors="coerce")
        numbers = values.to_numpy(dtype=np.float64)

        if not np.isfinite(numbers).all():
            raise ValueError(
                f"{column} 包含空值、非数字或无穷大。"
            )

        data[column] = numbers

    if (
        (data["step"] < 1)
        | (data["step"] % 1 != 0)
        | (data["step"] > 2**53 - 1)
    ).any():
        raise ValueError("step 必须是有效的正整数小时编号。")

    if (data["amount"] < 0).any():
        raise ValueError("amount 不能为负数。")

    # 现有模型的输入矩阵使用 float32
    if (data["amount"] > np.finfo(np.float32).max).any():
        raise ValueError("amount 超出模型输入支持的数值范围。")

    data["step"] = data["step"].astype("int64")
    return data
def predict_transactions(data, bundle, model_version):
    """生成模型特征，使用冻结模型与阈值评分。"""
    features = data.copy()

    features["log_amount"] = np.log1p(features["amount"])

    phase = 2 * np.pi * (features["step"] % 24) / 24
    features["phase_sin"] = np.sin(phase)
    features["phase_cos"] = np.cos(phase)

    numeric_columns = bundle["numeric_columns"]

    missing_features = set(numeric_columns) - set(features.columns)
    if missing_features:
        raise ValueError(
            f"当前页面无法生成模型所需特征：{sorted(missing_features)}"
        )

    # 复用训练代码，保持特征顺序和交易类型编码一致
    X, _ = make_matrix(
        features,
        numeric_columns,
        bundle["type_columns"],
    )

    if not np.isfinite(X).all():
        raise ValueError("生成的模型输入包含无效数值。")

    model = bundle["model"]
    positive_index = np.flatnonzero(model.classes_ == 1).item()
    scores = model.predict_proba(X)[:, positive_index]

    if (
        not np.isfinite(scores).all()
        or not ((scores >= 0) & (scores <= 1)).all()
    ):
        raise ValueError("模型输出了无效风险分数。")

    threshold = float(bundle["threshold"])

    result = data.copy()
    result["risk_score"] = scores
    result["threshold"] = threshold
    result["is_alert"] = scores >= threshold
    result["model_version"] = model_version

    return result
st.set_page_config(
    page_title="批量交易风险预测",
    layout="wide",
)

st.title("批量交易风险预测")

st.info(
    "支持 PaySim 格式的模拟交易批量评分。"
    "风险分数用于排序与告警，不代表已经确认欺诈，"
    "也不应解释为经过校准的真实欺诈概率。"
)

if not MODEL_PATH.exists():
    st.error("找不到已保存的 A 模型，请检查模型文件路径。")
    st.stop()

# 从同一份模型字节加载并计算版本，避免版本与模型不一致
model_bytes = MODEL_PATH.read_bytes()
model_hash = hashlib.sha256(model_bytes).hexdigest()[:12]
model_version = f"baseline_v1_A_base_{model_hash}"
bundle = joblib.load(BytesIO(model_bytes))

expected_features = {
    "amount", "log_amount", "phase_sin", "phase_cos"
}
if set(bundle["numeric_columns"]) != expected_features:
    st.error("当前页面仅支持现有 A 模型，请核对模型文件。")
    st.stop()

threshold = float(bundle["threshold"])
if not np.isfinite(threshold) or not 0 <= threshold <= 1:
    st.error("模型中保存的阈值无效。")
    st.stop()

allowed_types = sorted(
    column.removeprefix("type_")
    for column in bundle["type_columns"]
)

st.caption(
    f"模型版本：{model_version} ｜ "
    f"固定告警阈值：{threshold:.6f}"
)

st.subheader("1. 准备交易文件")

st.write(
    "CSV 必须包含 step、tx_type、amount 三列。"
    "tx_id 可选，未提供时自动生成本批次交易编号。"
    "允许包含其他列，预测时会自动忽略。"
    "step 沿用训练数据的时间起点和小时编号口径，"
    "不要为每次上传重新从 1 编号。"
)
st.write("支持的交易类型：" + "、".join(allowed_types))

template = pd.DataFrame({
    "step": [744, 744, 745],
    "tx_type": ["PAYMENT", "TRANSFER", "CASH_OUT"],
    "amount": [100.0, 50000.0, 80000.0],
})

st.download_button(
    label="下载 CSV 示例模板",
    data=template.to_csv(index=False).encode("utf-8-sig"),
    file_name="transaction_upload_template.csv",
    mime="text/csv",
    key="download_upload_template",
)

st.caption(
    "示例交易为人为构造，仅用于检查上传流程，"
    "没有真实欺诈标签。文件请保存为 CSV UTF-8。"
)

st.subheader("2. 上传并检查")

uploaded = st.file_uploader(
    "上传交易 CSV（最多 10 MB、100,000 笔）",
    type=["csv"],
    key="transaction_csv_upload",
)

if uploaded is None:
    st.session_state.pop(RESULT_KEY, None)
    st.session_state.pop(CONTEXT_KEY, None)
    st.stop()

if uploaded.size > MAX_FILE_BYTES:
    st.session_state.pop(RESULT_KEY, None)
    st.error("文件超过 10 MB，请拆分后上传。")
    st.stop()

file_bytes = uploaded.getvalue()
file_hash = hashlib.sha256(file_bytes).hexdigest()
context = (file_hash, model_version)

# 文件或模型改变后，清除上一批结果
if st.session_state.get(CONTEXT_KEY) != context:
    st.session_state.pop(RESULT_KEY, None)
    st.session_state[CONTEXT_KEY] = context

try:
    # 优先读取 UTF-8；解码失败时尝试常见中文编码
    try:
        raw = pd.read_csv(
            BytesIO(file_bytes),
            dtype="string",
            encoding="utf-8-sig",
            nrows=MAX_ROWS + 1,
        )
        detected_encoding = "UTF-8"

    except UnicodeDecodeError:
        try:
            raw = pd.read_csv(
                BytesIO(file_bytes),
                dtype="string",
                encoding="gb18030",
                nrows=MAX_ROWS + 1,
            )
            detected_encoding = "GB18030（兼容常见 GBK 文件）"

        except UnicodeDecodeError as exc:
            raise ValueError(
                "无法按 UTF-8 或 GB18030 读取文件，"
                "请在 Excel 中另存为“CSV UTF-8（逗号分隔）”后上传。"
            ) from exc

    # 两种编码只要有一种读取成功，就继续检查字段和数据
    data = validate_upload(raw, allowed_types)

except (
    ValueError,
    UnicodeDecodeError,
    pd.errors.ParserError,
    pd.errors.EmptyDataError,
) as exc:
    st.session_state.pop(RESULT_KEY, None)
    st.error(f"文件检查未通过：{exc}")
    st.stop()

# 读取和校验都成功后，才执行这里
st.caption(f"本次成功使用的读取编码：{detected_encoding}")

extra_columns = sorted(
    set(raw.columns) - set(INPUT_COLUMNS)
)
if extra_columns:
    st.caption(
        "以下额外列不参与预测：" + "、".join(extra_columns)
    )
if "tx_id" not in raw.columns:
    st.caption(
        "文件未提供 tx_id，已按记录顺序生成本批次交易编号。"
    )
st.success(f"检查通过，共 {len(data):,} 笔交易。")
st.dataframe(data.head(20), hide_index=True)
st.caption("这里只预览前 20 笔，预测将处理全部通过检查的交易。")

if st.button("开始预测", type="primary"):
    st.session_state.pop(RESULT_KEY, None)

    try:
        with st.spinner("正在生成特征并评分……"):
            result = predict_transactions(
                data, bundle, model_version
            )
        st.session_state[RESULT_KEY] = result

    except ValueError as exc:
        st.error(f"预测失败：{exc}")
        st.stop()

if RESULT_KEY not in st.session_state:
    st.stop()

result = st.session_state[RESULT_KEY]

st.subheader("3. 查看预测结果")

alert_count = int(result["is_alert"].sum())

c1, c2, c3 = st.columns(3)
c1.metric("已评分交易数", f"{len(result):,}")
c2.metric("风险告警数", f"{alert_count:,}")
c3.metric("告警占比", f"{result['is_alert'].mean():.2%}")

st.caption(
    "本页使用固定阈值告警，因此告警占比不一定是 1%。"
    "没有真实标签时，无法计算精确率和召回率。"
)

only_alerts = st.checkbox(
    "仅查看触发告警的交易",
    value=False,
)

view = result.loc[result["is_alert"]].copy() if only_alerts else result.copy()
view = view.sort_values(
    ["risk_score", "tx_id"],
    ascending=[False, True],
)

st.write(f"符合当前筛选条件：{len(view):,} 笔。")
st.dataframe(view.head(1000), hide_index=True)
st.caption("表格最多展示 1,000 笔；下方下载包含本批全部预测结果。")

st.download_button(
    label="下载本批全部预测结果",
    data=result.to_csv(
        index=False,
        float_format="%.17g",
    ).encode("utf-8-sig"),
    file_name="transaction_risk_predictions.csv",
    mime="text/csv",
    key="download_uploaded_predictions",
)