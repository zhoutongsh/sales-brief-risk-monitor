"""FastAPI 入口。

首次启动自动建库、生成确定性演示源数据并跑一次批处理。
只提供 PC Web，不提供移动端 /m 页面。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .audit import write_audit
from .auth import read_session
from .batch import run_batch
from .config import DEMO_DATE, WEB_DIR
from .db import connect, init_db
from .risk_service import RiskServiceError
from .seed import generate_source_files

logger = logging.getLogger("mvp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def ensure_demo_ready(db_path: Path) -> None:
    """没有数据库或没有当天日报时，自动初始化并跑批。"""
    init_db(db_path)
    needs_batch = True
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM daily_briefs WHERE as_of=?", (DEMO_DATE.isoformat(),)
        ).fetchone()
        needs_batch = not row or row[0] == 0
        has_orgs = conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0]
    finally:
        conn.close()
    if not has_orgs or not (Path(__file__).resolve().parent.parent / "data" / "source" / "orgs.csv").exists():
        logger.info("生成演示源数据 …")
        generate_source_files()
    if needs_batch:
        logger.info("首次启动：运行批处理 …")
        result = run_batch(DEMO_DATE, trigger_type="startup", triggered_by="system", db_path=db_path)
        if result["status"] != "success":
            logger.error("启动批处理失败：%s", result.get("error"))
        else:
            logger.info("启动批处理完成：%s，耗时 %.2fs", result["batch_id"], result["duration_seconds"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = app.state.db_path
    ensure_demo_ready(db_path)
    yield


app = FastAPI(
    title="日常销售数据动态监控 MVP V0.1",
    description=(
        "演示环境，不是生产系统。金额在数据库以元存储，API 输出万元并保留 1 位小数；"
        "所有列表、详情、导出均按登录角色在服务端做行级过滤。"
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.state.db_path = Path(__import__("os").environ.get("MVP_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mvp.db")))
app.include_router(router)


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RiskServiceError)
async def risk_error_handler(request: Request, exc: RiskServiceError):
    if exc.status_code == 403:
        _audit_denied(request, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        _audit_denied(request, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "detail": "请求参数不完整或格式不正确",
        "errors": exc.errors(),
    })


def _audit_denied(request: Request, detail: str) -> None:
    """403 审计：即使被拒绝，也记录“谁试图访问哪个路径”。"""
    db_path = getattr(request.app.state, "db_path", None)
    if not db_path:
        return
    user_id = None
    try:
        user_id = read_session(request)
    except HTTPException:
        user_id = None
    conn = None
    try:
        conn = connect(db_path)
        write_audit(
            conn, user_id, "access.denied", "api", request.url.path,
            detail, request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
    except Exception:
        logger.exception("写越权审计失败")
    finally:
        if conn:
            conn.close()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/index.html", include_in_schema=False)
def index_html():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {"ok": True, "demo": True, "mobile_supported": False}


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
