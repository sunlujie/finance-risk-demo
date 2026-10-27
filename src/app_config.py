import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 默认使用独立展示模式；设置 APP_MODE=local 可恢复本地模式
APP_MODE = os.getenv("APP_MODE", "demo").strip().lower()

if APP_MODE not in {"demo", "local"}:
    raise ValueError("APP_MODE 只能为 demo 或 local。")

IS_DEMO = APP_MODE == "demo"

DB_PATH = PROJECT_ROOT / (
    "deploy_data/demo.duckdb"
    if IS_DEMO
    else "data/risk.duckdb"
)

USE_API = not IS_DEMO

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")