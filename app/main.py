from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.routers import products
from app.routers import auth

app = FastAPI(title="E-commerce API")

app.include_router(products.router)
app.include_router(auth.router)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(STATIC_DIR / "index.html")