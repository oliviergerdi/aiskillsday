"""Toy shop v1: the old service."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.toys import data

app = FastAPI(title="Toy shop v1", version="1.0.0")


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


class Customer(BaseModel):
    id: int
    fullName: str
    email: str
    type: str
    currency: str
    legacyCode: str


@app.get("/orders", response_model=OrderPage)
def list_orders(page: int = Query(1, ge=1)) -> OrderPage:
    orders = data.sorted_orders()
    pages = math.ceil(len(orders) / data.PAGE_SIZE)
    if page > pages:
        return OrderPage(page=page, items=[])
    start = (page - 1) * data.PAGE_SIZE
    chunk = orders[start:start + data.PAGE_SIZE]
    return OrderPage(page=page, items=[OrderSummary(**data.summary(o)) for o in chunk])


@app.post("/orders", response_model=CreatedOrder)
def create_order(body: NewOrder) -> CreatedOrder:
    items = [i.model_dump() for i in body.items]
    return CreatedOrder(
        id=f"ord_{uuid.uuid4()}",
        createdAt=datetime.now(UTC).isoformat(),
        customerId=body.customerId,
        items=body.items,
        total=data.total_v1(items),
        currency=data.CURRENCY,
        status="pending",
    )


@app.get("/orders/{id}", response_model=Order)
def get_order(id: int) -> Order:
    order = data.ORDERS.get(id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(**order, total=data.total_v1(order["items"]), currency=data.CURRENCY)


@app.get("/customers/{id}", response_model=Customer)
def get_customer(id: int) -> Customer:
    customer = data.CUSTOMERS.get(id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return Customer(**customer)
