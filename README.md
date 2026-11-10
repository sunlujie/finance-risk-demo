# finance-risk-demo
PaySim transaction risk monitoring demo


## 运行展示模式

```bash
APP_MODE=demo python -m streamlit run app.py --browser.gatherUsageStats false
```

在仓库根目录运行，以加载 `.streamlit/config.toml` 中的主题及导航设置。
展示模式使用 `deploy_data/demo.duckdb`，批量评分使用已有冻结 A 模型；不启动 API、不重新训练。

界面分支：`ui/financial-dashboard`。主题采用深灰背景与柔和蓝主色。
`src/ui.py` 统一导航、指标卡片和表格格式，仅影响展示，CSV 导出保留原始字段与精度。

批量上传：CSV UTF-8 或 GB18030，最多 10 MB / 100,000 笔；检查通过后点击“开始预测”。
风险列表导出当前显示记录；批量评分导出本批全部记录，不受告警筛选影响。
