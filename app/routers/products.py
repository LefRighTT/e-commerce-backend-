from fastapi import APIRouter, HTTPException, Depends
from app.routers.auth import get_current_admin, get_current_user
from app.models.product import Product
from app.database import db
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from app.database import redis_client
import json

router = APIRouter()

def to_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"'{id_str}' is not a valid ID")

@router.get("/products")
async def get_products(
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    search: str | None = None,
    page: int | None = None,
    limit: int | None = None
):
    filters_used = any([category, min_price is not None, max_price is not None, search, page, limit])

    if not filters_used:
        try:
            cached = await redis_client.get("products:all")
            if cached:
                return {"products": json.loads(cached.decode("utf-8"))}
        except Exception:
            pass

    query = {}
    if category:
        query["category"] = category
    if min_price is not None or max_price is not None:
        query["price"] = {}
        if min_price is not None:
            query["price"]["$gte"] = min_price
        if max_price is not None:
            query["price"]["$lte"] = max_price
    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    cursor = db["products"].find(query)
    if page and limit:
        cursor = cursor.skip((page - 1) * limit).limit(limit)

    products = []
    async for product in cursor:
        product["_id"] = str(product["_id"])
        products.append(product)

    if not filters_used:
        try:
            await redis_client.set("products:all", json.dumps(products), ex=3600)
        except Exception:
            pass

    return {"products": products}

@router.get("/products/cart")
async def get_cart(current_user: str = Depends(get_current_user)):
    products_in_cart = await db["carts"].find_one({"user": current_user})
    if not products_in_cart:
        raise HTTPException(status_code=404, detail="Cart is empty")
    else:
        return {"cart": products_in_cart["items"]}

@router.get("/orders")
async def get_orders(current_user: str = Depends(get_current_user)):
    orders = []
    async for order in db["orders"].find({"user": current_user}):
        order["_id"] = str(order["_id"])
        orders.append(order)
    return {"orders": orders}

@router.get("/orders/{id}")
async def get_order(id: str, current_user: str = Depends(get_current_user)):
    order = await db["orders"].find_one({"_id": to_object_id(id), "user": current_user})
    if order:
        order["_id"] = str(order["_id"])
        return {"order": order}
    else:
        raise HTTPException(status_code=404, detail="Order not found")

@router.get("/products/{id}")
async def get_product(id: str):
    product = await db["products"].find_one({"_id": to_object_id(id)})
    if product:
        product["_id"] = str(product["_id"])
        return {"product": product}
    else:
        raise HTTPException(status_code=404, detail="Product not found")

@router.post("/products")
async def create_product(product: Product, current_user: str = Depends(get_current_admin)):
    new_product = product.model_dump()
    result = await db["products"].insert_one(new_product)
    try:
        await redis_client.delete("products:all")
    except Exception:
        pass
    return {"message": "Product created", "id": str(result.inserted_id)}

@router.post("/products/cart")
async def add_to_cart(product_id: str, current_user: str = Depends(get_current_user)):
    product = await db["products"].find_one({"_id": to_object_id(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    result = await db["carts"].update_one(
        {"user": current_user, "items.product_id": product_id},
        {"$inc": {"items.$.quantity": 1}}
    )

    if result.matched_count == 0:
        await db["carts"].update_one(
            {"user": current_user},
            {"$push": {"items": {"product_id": product_id, "quantity": 1}}},
            upsert=True
        )

    return {"message": "Product added to cart"}

@router.post("/orders")
async def place_order(current_user: str = Depends(get_current_user)):
    cart = await db["carts"].find_one({"user": current_user})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")

    order_items = []
    total = 0.0

    for item in cart.get("items", []):
        product = await db["products"].find_one({"_id": to_object_id(item["product_id"])})
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item['product_id']} no longer exists")
        if product["stock"] < item["quantity"]:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for '{product['name']}' (have {product['stock']}, want {item['quantity']})"
            )
        order_items.append({
            "product_id": item["product_id"],
            "name": product["name"],
            "price": product["price"],
            "quantity": item["quantity"]
        })
        total += product["price"] * item["quantity"]

    decremented = []
    for item in order_items:
        result = await db["products"].update_one(
            {"_id": to_object_id(item["product_id"]), "stock": {"$gte": item["quantity"]}},
            {"$inc": {"stock": -item["quantity"]}}
        )
        if result.modified_count == 0:
            for done in decremented:
                await db["products"].update_one(
                    {"_id": to_object_id(done["product_id"])},
                    {"$inc": {"stock": done["quantity"]}}
                )
            raise HTTPException(
                status_code=409,
                detail=f"'{item['name']}' sold out while placing your order"
            )
        decremented.append(item)

    order = {
        "user": current_user,
        "items": order_items,
        "total": total,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    }
    result = await db["orders"].insert_one(order)

    await db["carts"].update_one(
        {"user": current_user},
        {"$set": {"items": []}}
    )

    try:
        await redis_client.delete("products:all")
    except Exception:
        pass

    return {"message": "Order placed", "order_id": str(result.inserted_id), "total": total}

VALID_STATUSES = ["pending", "shipped", "delivered", "cancelled"]

@router.patch("/orders/{id}/status")
async def update_order_status(id: str, status: str, current_user: str = Depends(get_current_admin)):
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Status must be one of {VALID_STATUSES}")

    order = await db["orders"].find_one({"_id": to_object_id(id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="Order is already cancelled")
    if order["status"] == "delivered" and status != "delivered":
        raise HTTPException(status_code=400, detail="Delivered orders cannot be changed")

    if status == "cancelled":
        for item in order["items"]:
            await db["products"].update_one(
                {"_id": to_object_id(item["product_id"])},
                {"$inc": {"stock": item["quantity"]}}
            )
        try:
            await redis_client.delete("products:all")
        except Exception:
            pass

    await db["orders"].update_one(
        {"_id": to_object_id(id)},
        {"$set": {"status": status}}
    )

    return {"message": f"Order status updated to '{status}'"}

@router.put("/products/{id}")
async def update_product(id: str, product: Product, current_user: str = Depends(get_current_admin)):
    updated_product = product.model_dump()
    result = await db["products"].update_one({"_id": to_object_id(id)}, {"$set": updated_product})
    if result.modified_count:
        try:
            await redis_client.delete("products:all")
        except Exception:
            pass
        return {"message": "Product updated"}
    else:
        raise HTTPException(status_code=404, detail="Product not found")

@router.patch("/products/cart/{product_id}")
async def update_cart_item(product_id: str, quantity: int, current_user: str = Depends(get_current_user)):
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    else:
        result = await db["carts"].update_one(
            {"user": current_user, "items.product_id": product_id},
            {"$set": {"items.$.quantity": quantity}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Product not found in cart")
        return {"message": "Cart item updated"}

@router.delete("/products/{id}")
async def delete_product(id: str, current_user: str = Depends(get_current_admin)):
    result = await db["products"].delete_one({"_id": to_object_id(id)})
    if result.deleted_count:
        try:
            await redis_client.delete("products:all")
        except Exception:
            pass
        return {"message": "Product deleted"}
    else:
        raise HTTPException(status_code=404, detail="Product not found")

@router.delete("/products/cart/{product_id}")
async def remove_from_cart(product_id: str, current_user: str = Depends(get_current_user)):
    result = await db["carts"].update_one(
        {"user": current_user},
        {"$pull": {"items": {"product_id": product_id}}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Product not found in cart")

    return {"message": "Product removed from cart"}