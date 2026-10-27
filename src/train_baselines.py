from pathlib import Path
import gc
import json
import joblib
import duckdb
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 改成你现有脚本使用的数据库路径
DB_PATH = PROJECT_ROOT / "data" / "risk.duckdb"

BASE_NUMERIC = [
    "amount",
    "log_amount",
    "phase_sin",
    "phase_cos",
]

HISTORY_NUMERIC = [
    "receiver_cnt_1h",
    "receiver_sum_1h",
    "receiver_avg_1h",
    "receiver_cnt_24h",
    "receiver_sum_24h",
    "receiver_avg_24h",
    "receiver_cnt_168h",
    "receiver_sum_168h",
    "receiver_avg_168h",
    "receiver_has_history_168h",
    "receiver_history_ge5_168h",
]


def make_matrix(frame, numeric_columns, type_columns=None):
    """类别编码列以训练集为准；保留数值缺失值。"""
    encoded = pd.get_dummies(
        frame["tx_type"],
        prefix="type",
        dtype=np.float32,
    )

    if type_columns is None:
        type_columns = encoded.columns.tolist()

    encoded = encoded.reindex(
        columns=type_columns,
        fill_value=0,
    )

    numeric = frame[numeric_columns].to_numpy(
        dtype=np.float32,
        na_value=np.nan,
    )

    matrix = np.concatenate(
        [numeric, encoded.to_numpy(dtype=np.float32)],
        axis=1,
    )

    return matrix, type_columns


def select_threshold(y_true, scores):
    """只在验证集上选择F1最高的阈值。"""
    precision, recall, thresholds = precision_recall_curve(
        y_true, scores
    )

    # 最后一组precision/recall没有对应阈值
    precision = precision[:-1]
    recall = recall[:-1]

    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(precision),
        where=(precision + recall) > 0,
    )

    best_index = int(np.argmax(f1))

    return float(thresholds[best_index])


def evaluate(y_true, scores, threshold):
    predictions = (scores >= threshold).astype(np.int8)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1],
    ).ravel()

    return {
        "AP": average_precision_score(y_true, scores),
        "ROC_AUC": roc_auc_score(y_true, scores),
        "threshold": threshold,
        "precision": precision_score(
            y_true, predictions, zero_division=0
        ),
        "recall": recall_score(
            y_true, predictions, zero_division=0
        ),
        "F1": f1_score(
            y_true, predictions, zero_division=0
        ),
        "alert_rate": float(predictions.mean()),
        "TP": int(tp),
        "FP": int(fp),
        "FN": int(fn),
        "TN": int(tn),
    }

def evaluate_review_budget(y_true, scores):
    # 真实标签和模型分数，顺序必须一一对应
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)

    # 按风险分数从高到低排列
    order = np.argsort(-s, kind="stable")
    ranked_y = y[order]

    # cumulative_tp[k-1]：前 k 笔交易里有多少真实欺诈
    cumulative_tp = np.cumsum(ranked_y)
    total_fraud = int(y.sum())

    rows = []

    # 模拟不同审核能力；这些比例是实验设置
    for budget in [0.001, 0.005, 0.01, 0.02, 0.05]:
        k = max(1, int(len(y) * budget))

        tp = int(cumulative_tp[k - 1])
        fp = k - tp
        fn = total_fraud - tp

        rows.append({
            "target_review_rate": budget,
            "review_count": k,
            "precision": tp / k,
            "recall": tp / total_fraud if total_fraud else np.nan,
            "TP": tp,
            "FP": fp,
            "FN": fn,
        })

    return pd.DataFrame(rows)

def main():
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"数据库不存在：{DB_PATH}")
    model_dir = PROJECT_ROOT / "models" / "baseline_v1"
    report_dir = PROJECT_ROOT / "reports" / "baseline_v1"

    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    numeric_columns = BASE_NUMERIC + HISTORY_NUMERIC
    feature_sql = ", ".join(f"f.{c}" for c in numeric_columns)

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        # 标签必须一笔交易一行，防止JOIN放大行数
        label_rows, label_ids = con.execute("""
            SELECT COUNT(*), COUNT(DISTINCT tx_id)
            FROM evaluation_labels
        """).fetchone()

        if label_rows != label_ids:
            raise ValueError("标签表的tx_id存在重复或空值")

        feature_rows = con.execute("""
            SELECT COUNT(*) FROM feature_transactions
        """).fetchone()[0]

        data = con.execute(f"""
            SELECT
                f.tx_id,
                f.step,
                f.tx_type,
                {feature_sql},
                l.is_fraud
            FROM feature_transactions AS f
            LEFT JOIN evaluation_labels AS l
                ON f.tx_id = l.tx_id
            ORDER BY f.step, f.tx_id
        """).df()

    if len(data) != feature_rows:
        raise ValueError("关联标签后行数发生变化")

    if data["step"].isna().any():
        raise ValueError("step存在缺失")

    if not data["is_fraud"].isin([0, 1]).all():
        raise ValueError("标签缺失或标签不是0/1")

    # 按时间跨度划分，不随机打乱
    first_step = int(data["step"].min())
    last_step = int(data["step"].max())
    time_span = last_step - first_step + 1

    valid_start = first_step + int(time_span * 0.70)
    test_start = first_step + int(time_span * 0.85)

    masks = {
        "train": data["step"] < valid_start,
        "valid": (
            (data["step"] >= valid_start)
            & (data["step"] < test_start)
        ),
        "test": data["step"] >= test_start,
    }

    print(
        f"时间边界：训练 step < {valid_start}；"
        f"验证 {valid_start} <= step < {test_start}；"
        f"测试 step >= {test_start}"
    )

    split_summary = []
    labels = {}

    for name, mask in masks.items():
        part = data.loc[mask, ["step", "is_fraud"]]
        labels[name] = part["is_fraud"].to_numpy(dtype=np.int8)

        if part.empty or part["is_fraud"].nunique() != 2:
            raise ValueError(f"{name}为空或未同时包含两类标签")

        split_summary.append({
            "split": name,
            "min_step": part["step"].min(),
            "max_step": part["step"].max(),
            "rows": len(part),
            "fraud_count": int(part["is_fraud"].sum()),
            "fraud_rate": part["is_fraud"].mean(),
        })

    print("\n数据划分：")
    print(pd.DataFrame(split_summary).to_string(index=False))

    experiments = {
        "A_base": BASE_NUMERIC,
        "B_history": BASE_NUMERIC + HISTORY_NUMERIC,
    }

    fitted_models = []
    valid_results = []
    valid_predictions = data.loc[
        masks["valid"],
        [
            "tx_id",
            "step",
            "tx_type",
            "amount",
            "receiver_cnt_168h",
            "is_fraud",
        ],
    ].copy()

    # 先完成两个模型的训练和验证，冻结阈值
    for name, columns in experiments.items():
        print(f"\n正在训练 {name} ...", flush=True)

        x_train, type_columns = make_matrix(
            data.loc[masks["train"], ["tx_type"] + columns],
            columns,
        )

        model = HistGradientBoostingClassifier(
            learning_rate=0.1,
            max_iter=100,
            max_leaf_nodes=15,
            min_samples_leaf=50,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=42,
        )

        model.fit(x_train, labels["train"])
        del x_train
        gc.collect()

        x_valid, _ = make_matrix(
            data.loc[masks["valid"], ["tx_type"] + columns],
            columns,
            type_columns,
        )

        valid_scores = model.predict_proba(x_valid)[:, 1]

                # 取得与验证集预测顺序一致的交易明细
        audit = data.loc[
            masks["valid"],
            [
                "tx_id",
                "tx_type",
                "is_fraud",
                "receiver_cnt_168h",
            ],
        ].copy().reset_index(drop=True)

        # 核对标签顺序
        np.testing.assert_array_equal(
            audit["is_fraud"].to_numpy(),
            np.asarray(labels["valid"]),
        )

        audit["risk_score"] = np.asarray(valid_scores)

        # 在整个验证集中，统一选出风险最高的 1%
        review_k = max(1, int(len(audit) * 0.01))
        review_order = np.argsort(
            -audit["risk_score"].to_numpy(),
            kind="stable",
        )

        audit["is_alert"] = False
        audit.loc[review_order[:review_k], "is_alert"] = True

        # 区分过去 168 小时是否有收款历史
        audit["history_168h"] = np.where(
            audit["receiver_cnt_168h"].fillna(0) > 0,
            "with_history",
            "without_history",
        )

        actual_fraud = audit["is_fraud"].eq(1)
        selected = audit["is_alert"]

        audit["TP"] = actual_fraud & selected
        audit["FP"] = ~actual_fraud & selected
        audit["FN"] = actual_fraud & ~selected

        # 分别按交易类型、历史覆盖情况汇总
        for group_col in ["tx_type", "history_168h"]:
            group_report = audit.groupby(
                group_col, dropna=False
            ).agg(
                rows=("tx_id", "size"),
                fraud_count=("is_fraud", "sum"),
                alert_count=("is_alert", "sum"),
                TP=("TP", "sum"),
                FP=("FP", "sum"),
                FN=("FN", "sum"),
            )

            group_report["precision"] = (
                group_report["TP"]
                / group_report["alert_count"].replace(0, np.nan)
            )
            group_report["recall"] = (
                group_report["TP"]
                / group_report["fraud_count"].replace(0, np.nan)
            )

            print(f"\n验证集分组评估：{group_col}，全局审核比例 1%")
            print(
                group_report.to_string(
                    float_format=lambda x: f"{x:.4f}"
                )
            )

        budget_report = evaluate_review_budget(
            labels["valid"],
            valid_scores,
        )
        print("\n验证集：固定审核量评估")
        print(
            budget_report.to_string(
                index=False,
                float_format=lambda x: f"{x:.4f}",
            )
        )
        threshold = select_threshold(
            labels["valid"], valid_scores
        )
        # 保存当前模型对应的验证分数
        score_column = {
            "A_base": "score_A",
            "B_history": "score_B",
        }[name]

        valid_predictions[score_column] = valid_scores

        # 将模型及预测时需要的配置放在一起
        model_bundle = {
            "model": model,
            "model_name": name,
            "numeric_columns": columns,
            "type_columns": type_columns,
            "threshold": threshold,
            "valid_start": valid_start,
            "test_start": test_start,
        }

        model_path = model_dir / f"{name}.joblib"

        joblib.dump(model_bundle, model_path)

        print(f"模型已保存：{model_path}")

        valid_results.append({
            "model": name,
            **evaluate(labels["valid"], valid_scores, threshold),
        })

        fitted_models.append(
            (name, model, columns, type_columns, threshold)
        )

        del x_valid, valid_scores
        gc.collect()
    # 保存逐笔验证预测
    valid_predictions.to_csv(
        report_dir / "valid_predictions.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.17g",
    )

    # 保存验证指标
    pd.DataFrame(valid_results).to_csv(
        report_dir / "valid_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 保存数据划分概况
    pd.DataFrame(split_summary).to_csv(
        report_dir / "split_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 保存实验说明
    experiment_info = {
        "experiment_name": "baseline_v1",
        "first_step": first_step,
        "last_step": last_step,
        "valid_start": valid_start,
        "test_start": test_start,
        "threshold_rule": "验证集F1最大",
        "base_numeric": BASE_NUMERIC,
        "history_numeric": HISTORY_NUMERIC,
    }

    with (report_dir / "experiment_info.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(
            experiment_info,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"报告已保存：{report_dir}")
    print("\n验证集结果：")
    print(
        pd.DataFrame(valid_results).to_string(
            index=False, float_format=lambda x: f"{x:.6f}"
        )
    )
    # 当前阶段只保存模型并做验证集诊断，暂不重复评估测试集
    return
    # 所有设置冻结后，再评估测试集
    test_results = []

    for name, model, columns, type_columns, threshold in fitted_models:
        x_test, _ = make_matrix(
            data.loc[masks["test"], ["tx_type"] + columns],
            columns,
            type_columns,
        )

        test_scores = model.predict_proba(x_test)[:, 1]

        test_results.append({
            "model": name,
            **evaluate(labels["test"], test_scores, threshold),
        })

        del x_test, test_scores
        gc.collect()

    print("\n测试集结果：")
    print(
        pd.DataFrame(test_results).to_string(
            index=False, float_format=lambda x: f"{x:.6f}"
        )
    )


if __name__ == "__main__":
    main()