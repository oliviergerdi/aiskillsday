"""Toy shop v2: the rewrite. Seeded differences are marked DIFF #n (answer key numbering)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.toys import data

app = FastAPI(title="Toy shop v2", version="2.0.0")


class OrderItem(BaseModel):
    sku: str
    qty: int
    unit: float


class OrderSummary(BaseModel):
    id: int
    customerId: int
    status: str


class OrderPage(BaseModel):
    page: int
    items: list[OrderSummary]


class Order(BaseModel):
    id: int
    customerId: int
    items: list[OrderItem]
    total: float
    currency: str
    status: str


class NewOrder(BaseModel):
    customerId: int
    items: list[OrderItem]


class CreatedOrder(BaseModel):
    id: str
    createdAt: str
    customerId: int
    items: list[OrderItem]
    total: float
    currency: str
    status: str


class Client(BaseModel):
    id: int
    name: str                      # DIFF #4: fullName renamed
    email: str
    type: str
    currency: str | None = None    # DIFF #8: optional now, and omitted for businesses
    # DIFF #5: legacyCode dropped


@app.get("/orders", response_model=OrderPage)
def list_orders(page: int = Query(1, ge=1)) -> OrderPage:
    orders = data.sorted_orders()
    pages = len(orders) // data.PAGE_SIZE          # DIFF #7: floor, so the last partial page vanishes
    if page > pages:
        return OrderPage(page=page, items=[])
    start = (page - 1) * data.PAGE_SIZE
    chunk = orders[start:start + data.PAGE_SIZE]
    items = [OrderSummary(**data.summary(o)) for o in reversed(chunk)]   # DIFF #1: order differs (noise)
    return OrderPage(page=page, items=items)


@app.post("/orders", response_model=CreatedOrder, status_code=201)     # DIFF #3: 201 on create
def create_order(body: NewOrder) -> CreatedOrder:
    items = [i.model_dump() for i in body.items]
    return CreatedOrder(
        id=f"ord_{uuid.uuid4()}",                  # DIFF #2: new id and timestamp every call (noise)
        createdAt=datetime.now(UTC).isoformat(),
        customerId=body.customerId,
        items=body.items,
        total=data.total_v2(items),
        currency=data.CURRENCY,
        status="pending",
    )


@app.get("/orders/{id}", response_model=Order)
def get_order(id: int) -> Order:
    order = data.ORDERS.get(id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"No order with id {id}")   # DIFF #9: wording
    return Order(**order, total=data.total_v2(order["items"]), currency=data.CURRENCY)   # DIFF #6


@app.get("/clients/{clientId}", response_model=Client, response_model_exclude_none=True)   # DIFF #10: moved
def get_client(clientId: int) -> Client:
    customer = data.CUSTOMERS.get(clientId)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return Client(
        id=customer["id"],
        name=customer["fullName"],
        email=customer["email"],
        type=customer["type"],
        currency=None if customer["type"] == "business" else customer["currency"],
    )
