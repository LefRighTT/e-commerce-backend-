from pydantic import BaseModel

class UserCreate(BaseModel):
    email: str
    username: str
    password: str

class UserInDB(BaseModel):
    email: str
    username: str
    hashed_password: str
    role: str = "customer"

class UserLogin(BaseModel):
    email: str
    password: str