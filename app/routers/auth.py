from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import UserCreate, UserLogin
from app.database import db
from passlib.context import CryptContext
from jose import jwt, JWTError 
import os

router = APIRouter()
security = HTTPBearer()  # For token-based authentication

# This tells passlib to use bcrypt for hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Secret key for signing JWT tokens - in production this comes from .env
SECRET_KEY = os.getenv("SECRET_KEY", "changethislater")
ALGORITHM = "HS256"
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict) -> str:
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
async def get_current_admin(current_user: str = Depends(get_current_user)) -> str:
    user = await db["users"].find_one({"email": current_user})
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

@router.post("/register")
async def register(user: UserCreate):
    # Check if email already exists
    existing = await db["users"].find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash the password before storing
    hashed = hash_password(user.password)
    
    # Store user in database
    await db["users"].insert_one({
        "email": user.email,
        "username": user.username,
        "hashed_password": hashed,
        "role": "customer"
    })
    
    return {"message": "User registered successfully"}

@router.post("/login")
async def login(user: UserLogin):
    # Find user by email
    found = await db["users"].find_one({"email": user.email})
    if not found:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not verify_password(user.password, found["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create JWT token
    token = create_token({"sub": user.email})
    
    return {"access_token": token, "token_type": "bearer"}