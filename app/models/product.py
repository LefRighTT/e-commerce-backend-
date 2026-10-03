from pydantic import BaseModel, field_validator

class Product(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("price must be greater than 0")
        return v

    @field_validator("stock")
    @classmethod
    def stock_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError("stock cannot be negative")
        return v