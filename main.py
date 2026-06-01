from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings

from api.auth import router as auth_router
from api.calendar import router as calendar_router
from api.recommendations import router as recommendations_router
from api.visualization import router as visualization_router
from api.checkin import router as checkin_router
from api.health import router as health_router
from api.burnout import router as burnout_router
from scheduler.tasks import start_scheduler
from db.schema_init import ensure_schema

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Celestios - AI Calendar & Productivity Assistant",
    version="1.0.0",
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Production
        "https://celesti.life",
        "https://www.celesti.life",
        "https://astounding-brigadeiros-5e5293.netlify.app",
        # Local development only (can be removed if not needed)
        "http://localhost:8000",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth_router)
app.include_router(calendar_router)
app.include_router(recommendations_router)
app.include_router(visualization_router)
app.include_router(checkin_router)
app.include_router(health_router)
app.include_router(burnout_router)

@app.on_event("startup")
async def startup_event():
    """Start background tasks when the server starts."""
    ensure_schema()
    start_scheduler()

@app.get("/")
def read_root():
    return {"message": "Welcome to Celestios API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
