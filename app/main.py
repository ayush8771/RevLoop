"""
RevLoop — AI Revenue Recovery Agent: live FastAPI application.

Observe -> Diagnose -> Predict -> Decide -> Validate -> Execute
        -> Verify -> Measure -> Re-evaluate

AI/ML recommends. Deterministic guardrails authorize. Execution
performs. Verified outcomes update state.

Run:  uvicorn app.main:app --reload
"""
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import AUTH_ENABLED, MOCK_MODE
from app.database import initialize_database
from app.auth import router as auth_router, initialize_admin_user
from app.decision_api import router as decision_router
from app.transactions_api import router as transactions_router
from app.webhooks import router as webhook_router
from app.dashboard import router as dashboard_router
from app.recoveries import router as recoveries_router
from app.recovery_verification import router as verification_router

app = FastAPI(
    title="RevLoop — AI Revenue Recovery Agent",
    description=("AI revenue recovery: EV-based decisioning under deterministic "
                 "guardrails, executed through Razorpay Payment Links."),
    version="1.0.0",
)

initialize_database()
initialize_admin_user()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500", "http://localhost:5500",
        "http://127.0.0.1:8000", "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {
    "/", "/health", "/auth/login", "/docs", "/openapi.json", "/redoc",
    "/webhooks/razorpay",
}


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    if not AUTH_ENABLED:
        return await call_next(request)
    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_PATHS:
        return await call_next(request)
    if path.startswith("/docs") or path.startswith("/ui"):
        return await call_next(request)
    from app.auth import get_current_user
    try:
        get_current_user(request)
    except Exception as error:
        status = getattr(error, "status_code", 401)
        detail = getattr(error, "detail", "Authentication required")
        return JSONResponse(status_code=status, content={"detail": detail})
    return await call_next(request)


app.include_router(auth_router)
app.include_router(decision_router)
app.include_router(transactions_router)
app.include_router(webhook_router)
app.include_router(dashboard_router)
app.include_router(recoveries_router)
app.include_router(verification_router)

_FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/ui", StaticFiles(directory=_FRONTEND_DIR, html=True), name="ui")


@app.get("/")
def root():
    return {
        "name": "RevLoop — AI Revenue Recovery Agent",
        "status": "running",
        "version": "1.0.0",
        "mock_mode": MOCK_MODE,
        "ui": "/ui/",
        "decision_authority": "core/decision/decision_engine.py (single)",
    }


@app.get("/health")
def health():
    return {"status": "healthy", "mock_mode": MOCK_MODE}
