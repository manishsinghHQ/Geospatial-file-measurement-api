from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .api.routes import router
from .core.database import init_db

init_db()

app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a Shapefile (.zip) or KML and get per-feature area / length measurements.",
    version="1.0.0",
)
app.include_router(router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
