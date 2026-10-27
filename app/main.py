import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="MyCode Gateway",
    description="A private model-routing gateway for coding assistants.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "MyCode Gateway",
        "version": "0.1.0",
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    page = TEMPLATES_DIR / "index.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8088")),
        reload=True,
    )
