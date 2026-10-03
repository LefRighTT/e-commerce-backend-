from fastapi import FastAPI
from app.routers import products
from app.routers import auth

app = FastAPI()

app.include_router(products.router)
app.include_router(auth.router)

