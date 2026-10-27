from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports" / "baseline_v1"


st.set_page_config(
    page_title="模型实验对比",
    page_icon="📈",
    layout="wide",
)

st.title("模型实验对比")

st.caption("实验版本：baseline_v1")

st.info(
    "本页前半部分展示验证集上的模型开发与选择结果，"
    "阈值也在验证集上确定。"
    "测试集结果单独展示在页面下方的“测试集最终评估”区域。"
)


def load_report(filename):
    path = REPORT_DIR / filename

    if not path.is_file():
        st.error(f"找不到报告文件：{path}")
        st.stop()

    data = pd.read_csv(path)

    if data.empty:
        st.error(f"报告文件为空：{filename}")
        st.stop()

    return data


split_summary = load_report("split_summary.csv")
valid_metrics = load_report("valid_metrics.csv")
budget_comparison = load_report("budget_comparison.csv")
st.subheader("一、数据时间划分")

split_display = split_summary.copy()

split_display["fraud_rate_pct"] = (
    split_display["fraud_rate"] * 100
)

split_display = split_display[
    [
        "split",
        "min_step",
        "max_step",
        "rows",
        "fraud_count",
        "fraud_rate_pct",
    ]
].rename(
    columns={
        "split": "数据集",
        "min_step": "起始step",
        "max_step": "结束step",
        "rows": "交易笔数",
        "fraud_count": "欺诈笔数",
        "fraud_rate_pct": "欺诈占比（%）",
    }
)

st.dataframe(
    split_display,
    hide_index=True,
)

st.caption(
    "数据按时间跨度划分，因此各集合的交易笔数不一定按70%、15%、15%分布。"
    "不同时间段的欺诈比例也可能不同。"
)
st.subheader("二、各自阈值下的验证表现")

st.write(
    "每个模型分别使用在验证集上使F1最大的阈值。"
    "因此两个模型的告警数量可能不同。"
)

metric_display = valid_metrics[
    [
        "model",
        "AP",
        "ROC_AUC",
        "threshold",
        "precision",
        "recall",
        "F1",
        "alert_rate",
        "TP",
        "FP",
        "FN",
    ]
].copy()

for column in ["precision", "recall", "alert_rate"]:
    metric_display[column] = metric_display[column] * 100

metric_display = metric_display.rename(
    columns={
        "model": "模型",
        "threshold": "告警阈值",
        "precision": "精确率（%）",
        "recall": "召回率（%）",
        "alert_rate": "告警比例（%）",
        "TP": "发现欺诈",
        "FP": "正常交易误报",
        "FN": "欺诈漏报",
    }
)

st.dataframe(
    metric_display,
    hide_index=True,
)

st.caption(
    "AP和ROC-AUC根据连续分数计算，不依赖表中的单个告警阈值；"
    "精确率、召回率、F1和告警比例依赖所选阈值。"
)
st.subheader("三、相同审核容量下的比较")

budget_options = sorted(
    budget_comparison["budget_ratio"].unique().tolist()
)

default_index = min(
    range(len(budget_options)),
    key=lambda i: abs(budget_options[i] - 0.01),
)

selected_budget = st.selectbox(
    "审核容量",
    options=budget_options,
    index=default_index,
    format_func=lambda value: f"{value:.1%}",
)

selected_comparison = budget_comparison.loc[
    budget_comparison["budget_ratio"] == selected_budget
].copy()

if (
    set(selected_comparison["model"]) != {"A_base", "B_history"}
    or selected_comparison["model"].duplicated().any()
):
    st.error("当前容量下，报告应包含A、B各一行结果。")
    st.stop()

if selected_comparison["review_count"].nunique() != 1:
    st.error("两个模型的审核笔数不同，无法进行固定容量比较。")
    st.stop()

review_count = int(
    selected_comparison["review_count"].iloc[0]
)

st.write(
    f"两个模型各选取风险排名前 **{review_count:,}笔** 交易。"
    "选中的交易可以不同，但数量相同。"
)

budget_display = selected_comparison[
    [
        "model",
        "review_count",
        "TP",
        "FP",
        "FN",
        "precision",
        "recall",
    ]
].copy()

budget_display["precision"] *= 100
budget_display["recall"] *= 100

budget_display = budget_display.rename(
    columns={
        "model": "模型",
        "review_count": "审核笔数",
        "TP": "发现欺诈",
        "FP": "正常交易误报",
        "FN": "欺诈漏报",
        "precision": "精确率（%）",
        "recall": "召回率（%）",
    }
)

st.dataframe(
    budget_display,
    hide_index=True,
)

chart_data = (
    selected_comparison
    .set_index("model")[["TP"]]
    .rename(columns={"TP": "发现欺诈笔数"})
)

st.bar_chart(chart_data)
comparison_by_model = selected_comparison.set_index("model")

tp_a = int(comparison_by_model.loc["A_base", "TP"])
tp_b = int(comparison_by_model.loc["B_history", "TP"])

difference = tp_a - tp_b

if difference > 0:
    st.success(
        f"在当前审核容量下，A比B多发现 {difference} 笔欺诈。"
    )
elif difference < 0:
    st.success(
        f"在当前审核容量下，B比A多发现 {-difference} 笔欺诈。"
    )
else:
    st.info("在当前审核容量下，A和B发现的欺诈笔数相同。")

st.caption(
    "切换容量仅用于观察结果，不会改变评分表中的模型或告警阈值。"
    "固定前k笔的排序比较，也不等同于固定分数阈值告警。"
)
with st.expander("查看审核边界的同分情况"):
    tie_columns = [
        "model",
        "cutoff_score",
        "cutoff_tie_count",
        "selected_at_cutoff",
    ]

    st.dataframe(
        selected_comparison[tie_columns],
        hide_index=True,
    )

    st.write(
        "分数相同时，按tx_id升序选择，未使用真实标签打破同分。"
        "如果边界处大量交易同分，而只选入其中一部分，"
        "结果可能受到同分排序规则影响。"
    )

st.subheader("四、实验解释")

st.markdown(
    """
- **A基础模型**：使用当前交易金额、对数金额、24小时周期位置和交易类型。
- **B历史增强模型**：在A的基础上，加入接收端过去1、24、168小时的统计特征。
- **主要选择标准**：验证集前1%审核容量内发现的欺诈笔数。
- **当前演示模型**：依据已完成的比较，采用A；B保留为对照。
- **结论边界**：历史特征的收益随审核容量变化，不能据此断言A或B全面更优，也未进行统计显著性检验。
"""
)

st.download_button(
    label="下载完整审核容量比较结果",
    data=budget_comparison.to_csv(index=False).encode("utf-8-sig"),
    file_name="budget_comparison.csv",
    mime="text/csv",
)

st.caption(
    "本页仅展示已保存报告。之后如果重新训练或修改实验，"
    "应同步更新模型、预测、诊断报告和评分结果，避免混用不同实验产物。"
)

st.divider()
st.header("测试集最终评估")

st.write(
    "固定使用验证阶段选定的 A 模型，"
    "在时间更晚的测试集上检查效果。"
    "本区域不重新训练模型，也不调整阈值。"
)

test_report_dir = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "baseline_v1"
)

overview_path = test_report_dir / "test_overview.csv"
policies_path = test_report_dir / "test_policy_metrics.csv"

if not overview_path.exists() or not policies_path.exists():
    st.info(
        "尚未生成测试集报告。请在项目根目录运行："
        "python -m src.evaluate_test"
    )
else:
    test_overview = pd.read_csv(overview_path).iloc[0]
    test_policies = pd.read_csv(policies_path)

    versions_match = test_policies["model_version"].eq(
        test_overview["model_version"]
    ).all()

    if not versions_match:
        st.error("两份测试报告的模型版本不一致，请重新生成报告。")
        st.stop()

    st.caption(
        f"模型版本：{test_overview['model_version']} ｜ "
        f"测试时间：第 {int(test_overview['step_min'])}"
        f"～{int(test_overview['step_max'])} 小时"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "测试交易数",
        f"{int(test_overview['transaction_count']):,}",
    )
    c2.metric(
        "真实欺诈数",
        f"{int(test_overview['fraud_count']):,}",
    )
    c3.metric(
        "欺诈占比",
        f"{test_overview['fraud_rate']:.2%}",
    )

    c4, c5 = st.columns(2)
    c4.metric("AP", f"{test_overview['ap']:.4f}")
    c5.metric("ROC-AUC", f"{test_overview['roc_auc']:.4f}")

    st.caption(
        "AP 和 ROC-AUC 评价风险分数的排序能力；"
        "下面的指标评价具体告警策略。"
    )

    st.subheader("两种固定策略的结果")

    st.write(
        f"**固定阈值策略：**风险分数 ≥ "
        f"{test_overview['threshold']:.6f} 时告警。"
        "该阈值来自验证集，告警数量由测试集分数决定。"
    )

    st.write(
        "**前 1% 策略：**按风险分数从高到低选择测试集的前 1%，"
        "选中数量向下取整；分数相同按交易编号升序排列。"
        "这是整段测试数据上的离线容量评估。"
    )

    display = test_policies[
        [
            "policy",
            "alert_count",
            "alert_rate",
            "precision",
            "recall",
            "f1",
            "tp",
            "fp",
            "fn",
            "tn",
        ]
    ].copy()

    display["policy"] = display["policy"].replace({
        "validation_threshold": "验证集固定阈值",
        "top_1_percent": "风险分数前 1%",
    })

    for column in ["alert_rate", "precision", "recall", "f1"]:
        display[column] = display[column].map(
            lambda value: f"{value:.2%}"
        )

    display = display.rename(columns={
        "policy": "策略",
        "alert_count": "告警数",
        "alert_rate": "告警占比",
        "precision": "精确率",
        "recall": "召回率",
        "f1": "F1",
        "tp": "识别欺诈 TP",
        "fp": "误报正常 FP",
        "fn": "漏掉欺诈 FN",
        "tn": "正确排除 TN",
    })

    st.dataframe(display, hide_index=True)

    st.caption(
        "精确率：告警交易中有多少是真的欺诈；"
        "召回率：所有真实欺诈中有多少被识别出来。"
    )

    with st.expander("前 1% 的边界并列情况"):
        budget_row = test_policies.loc[
            test_policies["policy"].eq("top_1_percent")
        ].iloc[0]

        st.write(
            f"选中数量：{int(budget_row['alert_count']):,}；"
            f"边界分数：{budget_row['cutoff_score']:.8f}；"
            f"与边界同分的交易共 "
            f"{int(budget_row['cutoff_tie_count']):,} 笔，"
            f"其中选中 "
            f"{int(budget_row['selected_at_cutoff']):,} 笔。"
        )

    st.info(
        "阅读说明：本项目早期已查看过测试集指标。"
        "这里展示当前冻结方案的测试结果；"
        "不据此反复选择模型、阈值或审核容量。"
        "测试集是较晚时间段的模拟数据，"
        "结果不等同于真实上线效果。"
    )

    st.download_button(
        label="下载测试集策略评估报告",
        data=test_policies.to_csv(index=False).encode("utf-8-sig"),
        file_name="test_policy_metrics.csv",
        mime="text/csv",
        key="download_test_policy_metrics",
    )