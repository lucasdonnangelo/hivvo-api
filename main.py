from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse as _JSONResponse
from sqlmodel import Session, text

from app.core.config import settings
from app.core.database import engine
from app.routers import auth, transactions, categories, cards, invoices, installments, statistics, ai


class UTF8JSONResponse(_JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Hivvo API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(cards.router)
app.include_router(invoices.router)
app.include_router(installments.router)
app.include_router(statistics.router)
app.include_router(ai.router)


@app.get("/health", tags=["health"])
def health_check():
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        return {"status": "ok", "database": "connected", "environment": settings.ENVIRONMENT}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")
