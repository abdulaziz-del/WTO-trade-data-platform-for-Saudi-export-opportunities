from fastapi import FastAPI
from app.routers.ingestion import router as ingestion_router

app = FastAPI(
    title="WTO Trade Intelligence Platform",
    version="1.0.0"
)

app.include_router(
    ingestion_router,
    prefix="/api/v1/ingestion",
    tags=["Ingestion"]
)

@app.get("/")
async def root():
    return {
        "status": "running",
        "message": "WTO Trade Intelligence Platform API"
    }
