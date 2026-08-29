from dotenv import load_dotenv

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from groq import Groq
except ImportError:  # AI is optional; POS ordering must still work without it.
    Groq = None

DB_PATH = os.path.join(BASE_DIR, "pos.db")
MENU_PATH = os.path.join(BASE_DIR, "menu.json")

app = FastAPI(title="Big Little Bombaye POS", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def load_menu():
    with open(MENU_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


MENU = load_menu()


def find_item(item_name: str):
    target = item_name.strip().lower()
    for category in MENU.get("categories", []):
        for item in category.get("items", []):
            if item.get("item_name", "").strip().lower() == target:
                return item
    return None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL UNIQUE,
                table_number TEXT NOT NULL,
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'RECEIVED',
                subtotal REAL NOT NULL,
                bill_generated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                tier TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT UNIQUE NOT NULL,
                stock INTEGER NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'units'
            );

            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
            """
        )


init_db()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    item_name: str
    user_message: str
    history: list[ChatMessage] = Field(default_factory=list)


class OrderItemRequest(BaseModel):
    item_name: str
    tier: str = "Standard"
    price: Optional[float] = None
    quantity: int = Field(default=1, ge=1, le=99)


class OrderRequest(BaseModel):
    table_number: str = Field(min_length=1, max_length=20)
    notes: str = Field(default="", max_length=500)
    items: list[OrderItemRequest] = Field(min_length=1, max_length=50)


class StatusRequest(BaseModel):
    status: str


class InventoryItemRequest(BaseModel):
    item_name: str
    stock: int = 0
    unit: str = "units"


class InventoryUpdateRequest(BaseModel):
    stock: int


VALID_STATUSES = {"RECEIVED", "PREPARING", "READY", "COMPLETED", "CANCELLED"}


def serialize_order(conn, row):
    items = conn.execute(
        "SELECT item_name, tier, price, quantity FROM order_items WHERE order_id = ? ORDER BY id",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "order_number": row["order_number"],
        "table_number": row["table_number"],
        "notes": row["notes"] or "",
        "status": row["status"],
        "subtotal": round(row["subtotal"], 2),
        "bill_generated": bool(row["bill_generated"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [dict(item) for item in items],
    }


@app.get("/")
def serve_customer():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/menu")
def serve_customer_menu():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/staff")
def serve_staff():
    return FileResponse(os.path.join(BASE_DIR, "staff.html"))


MAX_TABLES = 12


def validate_table_number(table_str: str) -> str:
    table_str_clean = table_str.strip()
    match = re.search(r"\d+", table_str_clean)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Invalid table number format. Please provide a valid table number between 1 and 12.",
        )
    table_num = int(match.group())
    if table_num < 1 or table_num > MAX_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid table number. Table '{table_str_clean}' does not exist. Please enter a valid table number (1-{MAX_TABLES}).",
        )
    return table_str_clean


@app.get("/api/menu")
def get_menu():
    return MENU


@app.post("/api/orders")
def create_order(payload: OrderRequest):
    validated_table = validate_table_number(payload.table_number)
    # Never trust prices sent by the browser. Recalculate from menu.json on the server.
    normalized_items = []
    subtotal = 0.0
    for requested in payload.items:
        item = find_item(requested.item_name)
        if item is None:
            raise HTTPException(status_code=400, detail=f"Dish '{requested.item_name}' is not on the menu.")

        pricing = item.get("pricing", {})
        tier = requested.tier
        if tier not in pricing:
            if len(pricing) == 1:
                tier = next(iter(pricing))
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid variant '{requested.tier}' for {item['item_name']}.",
                )

        price = float(pricing[tier])
        normalized_items.append((item["item_name"], tier, price, requested.quantity))
        subtotal += price * requested.quantity

    now = datetime.now(timezone.utc).isoformat()
    order_number = f"BLB-{datetime.now().strftime('%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO orders (order_number, table_number, notes, status, subtotal, created_at, updated_at)
            VALUES (?, ?, ?, 'RECEIVED', ?, ?, ?)
            """,
            (order_number, validated_table, payload.notes.strip(), round(subtotal, 2), now, now),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, item_name, tier, price, quantity) VALUES (?, ?, ?, ?, ?)",
            [(order_id, *item) for item in normalized_items],
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return serialize_order(conn, row)


@app.get("/api/orders")
def get_orders(status: Optional[str] = Query(default=None)):
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid order status.")
    with db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        return [serialize_order(conn, row) for row in rows]


@app.get("/api/orders/{order_id}")
def get_order(order_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        return serialize_order(conn, row)


@app.post("/api/orders/{order_id}/bill")
def generate_bill(order_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE orders SET bill_generated = 1, updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return serialize_order(conn, row)


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: StatusRequest):
    status = payload.status.upper().strip()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid order status.")

    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, order_id),
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return serialize_order(conn, row)


@app.get("/api/revenue/summary")
def revenue_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        revenue_row = conn.execute(
            "SELECT COALESCE(SUM(subtotal), 0) AS revenue, COUNT(*) AS completed_orders "
            "FROM orders WHERE status = 'COMPLETED' AND substr(created_at, 1, 10) = ?",
            (today,),
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status IN ('RECEIVED', 'PREPARING', 'READY')"
        ).fetchone()["count"]
        all_completed = conn.execute(
            "SELECT COALESCE(SUM(subtotal), 0) AS revenue, COUNT(*) AS count FROM orders WHERE status = 'COMPLETED'"
        ).fetchone()
        return {
            "today_revenue": round(revenue_row["revenue"], 2),
            "today_completed_orders": revenue_row["completed_orders"],
            "active_orders": active,
            "all_time_revenue": round(all_completed["revenue"], 2),
            "all_time_completed_orders": all_completed["count"],
        }


@app.get("/api/history")
def order_history(limit: int = Query(default=100, ge=1, le=500)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status IN ('COMPLETED', 'CANCELLED') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [serialize_order(conn, row) for row in rows]


@app.get("/api/inventory")
def get_inventory():
    with db() as conn:
        rows = conn.execute("SELECT * FROM inventory ORDER BY item_name ASC").fetchall()
        return [dict(row) for row in rows]


@app.post("/api/inventory")
def add_inventory(payload: InventoryItemRequest):
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO inventory (item_name, stock, unit) VALUES (?, ?, ?)",
                (payload.item_name.strip(), payload.stock, payload.unit.strip()),
            )
            row = conn.execute("SELECT * FROM inventory WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Item already exists in inventory.")


@app.patch("/api/inventory/{item_id}")
def update_inventory(item_id: int, payload: InventoryUpdateRequest):
    with db() as conn:
        row = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Inventory item not found.")
        conn.execute(
            "UPDATE inventory SET stock = ? WHERE id = ?",
            (payload.stock, item_id),
        )
        row = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
        return dict(row)


@app.get("/api/insights")
def get_insights(timeframe: str = Query(default="last_24h")):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    
    if timeframe == "last_24h":
        start_date = now - dt.timedelta(hours=24)
    elif timeframe == "last_7d":
        start_date = now - dt.timedelta(days=7)
    elif timeframe == "last_30d":
        start_date = now - dt.timedelta(days=30)
    elif timeframe == "last_1y":
        start_date = now - dt.timedelta(days=365)
    else:
        raise HTTPException(status_code=400, detail="Invalid timeframe.")
        
    start_iso = start_date.isoformat()
    
    with db() as conn:
        revenue_row = conn.execute(
            "SELECT COALESCE(SUM(subtotal), 0) AS revenue, COUNT(*) AS completed_orders "
            "FROM orders WHERE status = 'COMPLETED' AND created_at >= ?",
            (start_iso,),
        ).fetchone()
        
        # Additional metrics can be added here
        revenue = round(revenue_row["revenue"], 2)
        orders_count = revenue_row["completed_orders"]
        avg_order = round(revenue / orders_count, 2) if orders_count > 0 else 0.0
        
        return {
            "timeframe": timeframe,
            "revenue": revenue,
            "orders": orders_count,
            "avg_order_value": avg_order
        }


@app.post("/api/chat")
def chat(payload: ChatRequest):
    item = find_item(payload.item_name)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Dish '{payload.item_name}' not found on the menu.")

    if Groq is None:
        raise HTTPException(status_code=503, detail="AI Butler is unavailable because the Groq package is not installed.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI Butler is not configured. Add GROQ_API_KEY to .env.")

    dish_details = {
        "item_name": item.get("item_name"),
        "description": item.get("description"),
        "pricing": item.get("pricing"),
        "tags": item.get("tags"),
    }

    system_prompt = f"""/no_think
You are the refined, charming, and highly knowledgeable AI Butler at Big Little Bombaye.
Answer questions about the selected dish accurately and concisely. Never reveal internal reasoning.
Keep answers to one or two short sentences. Do not invent ingredients, prices, or dietary properties.
Dish details:
{json.dumps(dish_details)}"""

    messages = (
        [{"role": "system", "content": system_prompt}]
        + [{"role": m.role, "content": m.content} for m in payload.history]
        + [{"role": "user", "content": payload.user_message}]
    )

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.6,
            max_tokens=100,
        )
    except Exception as exc:
        print("AI provider error:", repr(exc))
        raise HTTPException(status_code=502, detail="The AI service is temporarily unavailable. Your POS ordering system is still available.")

    raw_reply = completion.choices[0].message.content or ""
    reply = re.sub(r"<think>.*?(?:</think>|$)", "", raw_reply, flags=re.DOTALL).strip()
    return {"reply": reply or "I apologize, could you please repeat that?"}
