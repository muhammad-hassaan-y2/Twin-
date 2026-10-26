from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db, engine
from app.api.routes import router as api_router
from app.services.seeder import seed_database
from app.database import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    
    # Seed database if empty
    db = SessionLocal()
    try:
        from app.models.incident import Incident
        if db.query(Incident).count() == 0:
            seed_database(db)
    finally:
        db.close()
    
    yield
    
    # Shutdown
    engine.dispose()


app = FastAPI(
    title="Factory Maintenance AI System",
    description="AI-powered factory maintenance coordination system with 11 AI agents",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for uploads
import os
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/api/files", StaticFiles(directory=settings.UPLOAD_DIR), name="files")

# Include API routes
app.include_router(api_router)


@app.get("/")
def root():
    return {
        "message": "Factory Maintenance AI System API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)