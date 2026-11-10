# 界面优化与验证记录

- 仓库：`/workspace/finance-risk-demo`
- 起始分支：`work`；起始提交：`b1817d9`
- 修改分支：`ui/financial-dashboard`；未合并、未部署。
- 入口：`app.py`；另有风险列表、模型对比、批量预测三个页面。
- 环境：Streamlit 1.66.1，已有 finance-risk-demo 虚拟环境。
- 展示命令：`APP_MODE=demo python -m streamlit run app.py --browser.gatherUsageStats false`
- 修改前先启动并查看四页；最终对比截图由原始 HEAD 独立运行于 8503 与修改版 8501 生成，避免多页面切换中的旧内容残留。

## 修改内容

| 文件 | 内容 |
| --- | --- |
| `.streamlit/config.toml` | 指定深色主题与柔和蓝主色，关闭默认文件名导航 |
| `src/ui.py` | 四页共享导航、字体层级、留白、指标卡片与表格格式 |
| `app.py` | 趋势图并排、图表颜色和高度、汇总导出范围说明 |
| `pages/1_风险交易列表.py` | 统一界面、中文表头、风险分数条和精度 |
| `pages/2_模型实验对比.py` | 统一表格与图表样式，保留全部实验说明 |
| `pages/3_批量交易风险预测.py` | 步骤、等待、完成与导出说明；上传控件准确显示既有 10 MB 限制 |
| `README.md` | 运行与交互说明 |
| `.gitignore` | 忽略临时验证资产与 Python 缓存 |
| `docs/ui-validation.md` | 本记录 |

## 验证

- Chromium / Playwright：1512 × 1000 四页展示无 Streamlit 异常；768 × 1024 概览截图检查。
- 概览：全量 6,362,620 笔，类型汇总 CSV 下载成功。
- 风险列表：默认 1,021 笔告警；取消仅告警后 191,147 笔；PAYMENT 告警筛选返回 0 并显示空状态；单笔背景、当前 100 笔 CSV 导出成功。
- 模型对比：审核容量键盘切换、验证和测试区域展示、审核容量比较与测试策略 CSV 下载成功。
- CSV 模板：3 笔有效记录通过检查、预测、告警筛选、完整导出；修改前后评分导出逐字节一致。原始阈值 0.086029357778133447 保留在导出中。
- 混合 CSV：4 笔中 1 笔触发告警；筛选仅显示 1 笔，导出仍有 4 笔，修改前后导出逐字节一致。
- 无效 CSV：缺少 amount 时显示字段错误；上一批结果和导出按钮被清除。
- 既有函数 AST 修改前后一致；数据库、模型、报告、应用模式配置及训练代码无差异。没有训练模型。
- Python 编译与差异检查通过（保留原文件 CRLF，检查时允许 cr-at-eol）。

## 资产与限制

测试脚本、下载样本与逐字节比较数据保存在仓库 `work/`。截图交付副本及下载包保存在 `docs/ui-screenshots/`，下载包内含原始截图和 SHA-256 清单。
四页对比：`before-0.png` 至 `before-3.png`、`after-0.png` 至 `after-3.png`。
另有评分结果、错误提示、768px 视口截图。

当前仓库没有 FastAPI 服务端实现。风险列表中仅保留了 APP_MODE=local 时调用 /alerts 和 /transactions/{tx_id} 的客户端代码；这不是已完成、可用或已验证的功能。本次验证使用 APP_MODE=demo，直接读取 DuckDB，不依赖 FastAPI。未验证线上部署、所有编码/10 MB/100,000 行边界、所有浏览器与手机尺寸。本次验证为展示模式与构造 CSV，不能证明模型真实金融场景效果。
任务指定 `/codex/.../output` 目录在此环境不可创建；普通和提权命令均返回文件系统权限错误。截图保留在上述工作目录并在会话中展示。


## 交付复核

`cba50af` 是首次界面修改的本地提交，随后已实际通过 Git 推送到 GitHub 的 `ui/financial-dashboard` 分支。没有合并主分支或修改部署设置。

云端 Streamlit 进程监听 0.0.0.0:8501，健康检查返回 ok；已使用共享云端 Chrome 原生窗口打开并目视确认概览正常显示。localhost 属于云端环境，用户应通过当前任务的 Desktop 面板操作该浏览器，不能将其当作用户本机可访问链接。

仓库：https://github.com/sunlujie/finance-risk-demo/tree/ui/financial-dashboard
截图下载：https://github.com/sunlujie/finance-risk-demo/raw/refs/heads/ui/financial-dashboard/docs/ui-screenshots/finance-risk-ui-screenshots.zip
