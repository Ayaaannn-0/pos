from dotenv import load_dotenv

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
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
BUSINESS_TIMEZONE = ZoneInfo("Asia/Kolkata")
PRINT_QUEUE_DIR = Path(BASE_DIR) / "print_queue"
UPI_VPA = os.getenv("UPI_VPA", "merchant@upi")
UPI_MERCHANT_NAME = os.getenv("UPI_MERCHANT_NAME", "CafeName")

app = FastAPI(title="Big Little Bombaye POS", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


class EventBroadcaster:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def publish(self, event: str, data: dict):
        message = {"event": event, "data": data, "emitted_at": datetime.now(timezone.utc).isoformat()}
        failed = []
        for websocket in self.connections.copy():
            try:
                await websocket.send_json(message)
            except Exception:
                failed.append(websocket)
        for websocket in failed:
            self.disconnect(websocket)


events = EventBroadcaster()


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


def ensure_column(conn, table: str, column: str, definition: str):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


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

            CREATE TABLE IF NOT EXISTS customers (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        for column, definition in (
            ("order_type", "order_type TEXT NOT NULL DEFAULT 'DINE_IN'"),
            ("source", "source TEXT NOT NULL DEFAULT 'WALK_IN'"),
            ("token_number", "token_number INTEGER"),
            ("token_date", "token_date TEXT"),
            ("customer_phone", "customer_phone TEXT"),
            ("customer_name", "customer_name TEXT NOT NULL DEFAULT ''"),
            ("tax_rate", "tax_rate REAL NOT NULL DEFAULT 0"),
            ("tax_amount", "tax_amount REAL NOT NULL DEFAULT 0"),
            ("service_charge", "service_charge REAL NOT NULL DEFAULT 0"),
            ("grand_total", "grand_total REAL NOT NULL DEFAULT 0"),
            ("payment_status", "payment_status TEXT NOT NULL DEFAULT 'PENDING_PAYMENT'"),
        ):
            ensure_column(conn, "orders", column, definition)

        conn.execute("UPDATE orders SET order_type = 'DINE_IN' WHERE order_type IS NULL OR order_type = ''")
        conn.execute("UPDATE orders SET source = 'WALK_IN' WHERE source IS NULL OR source = ''")
        conn.execute("UPDATE orders SET grand_total = subtotal WHERE grand_total IS NULL OR grand_total = 0")
        conn.execute("UPDATE orders SET payment_status = 'PAID' WHERE bill_generated = 1 AND payment_status = 'UNPAID'")
        conn.execute("UPDATE orders SET payment_status = 'PENDING_PAYMENT' WHERE payment_status = 'UNPAID'")
        # Older versions stored labels such as "Table 7". Canonicalize them so
        # the active-order constraint applies to both old and new orders.
        rows = conn.execute("SELECT id, table_number FROM orders").fetchall()
        for row in rows:
            match = re.fullmatch(
                r"(?:table\s*|t\s*)?(\d+)", row["table_number"].strip(), flags=re.IGNORECASE
            )
            if match:
                conn.execute(
                    "UPDATE orders SET table_number = ? WHERE id = ?",
                    (str(int(match.group(1))), row["id"]),
                )
        legacy_orders = conn.execute(
            "SELECT id, created_at FROM orders WHERE token_number IS NULL OR token_date IS NULL ORDER BY created_at, id"
        ).fetchall()
        next_token_by_day = {}
        for row in legacy_orders:
            token_day = (row["created_at"] or "")[:10] or datetime.now(BUSINESS_TIMEZONE).date().isoformat()
            if token_day not in next_token_by_day:
                highest = conn.execute(
                    "SELECT COALESCE(MAX(token_number), 0) FROM orders WHERE token_date = ?", (token_day,)
                ).fetchone()[0]
                next_token_by_day[token_day] = int(highest) + 1
            conn.execute(
                "UPDATE orders SET token_date = ?, token_number = ? WHERE id = ?",
                (token_day, next_token_by_day[token_day], row["id"]),
            )
            next_token_by_day[token_day] += 1

        conn.execute("DROP INDEX IF EXISTS idx_active_orders_table")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_active_orders_table ON orders(table_number) "
            "WHERE order_type = 'DINE_IN' AND status IN ('RECEIVED', 'PREPARING', 'READY')"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_token ON orders(token_date, token_number)"
        )
        for key, value in {
            "tax_rate": "5",
            "service_charge_rate": "0",
            "printer_name": "Browser print dialog",
            "printer_station": "Kitchen",
        }.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


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
    table_number: Optional[str] = Field(default=None, max_length=20)
    order_type: str = "DINE_IN"
    source: str = "WALK_IN"
    customer_phone: Optional[str] = Field(default=None, max_length=20)
    customer_name: str = Field(default="", max_length=100)
    payment_status: str = "PENDING_PAYMENT"
    notes: str = Field(default="", max_length=500)
    items: list[OrderItemRequest] = Field(min_length=1, max_length=50)


class StatusRequest(BaseModel):
    status: str


class InventoryItemRequest(BaseModel):
    item_name: str = Field(min_length=1, max_length=100)
    stock: int = Field(default=0, ge=0)
    unit: str = Field(default="units", min_length=1, max_length=30)


class InventoryUpdateRequest(BaseModel):
    stock: int = Field(ge=0)


class PaymentLineRequest(BaseModel):
    method: str
    amount: float = Field(gt=0)


class BillRequest(BaseModel):
    payments: list[PaymentLineRequest] = Field(default_factory=list, max_length=3)


class SettingsRequest(BaseModel):
    tax_rate: float = Field(ge=0, le=50)
    service_charge_rate: float = Field(ge=0, le=50)
    printer_name: str = Field(default="Browser print dialog", min_length=1, max_length=100)
    printer_station: str = Field(default="Kitchen", min_length=1, max_length=100)


class MockPaymentWebhookRequest(BaseModel):
    order_id: int = Field(gt=0)


VALID_STATUSES = {"RECEIVED", "PREPARING", "READY", "COMPLETED", "CANCELLED"}
VALID_ORDER_TYPES = {"DINE_IN", "TAKEAWAY", "DELIVERY"}
VALID_DELIVERY_SOURCES = {"DELIVERY", "SWIGGY", "ZOMATO"}
VALID_PAYMENT_METHODS = {"CASH", "UPI", "CARD"}
VALID_PAYMENT_STATUSES = {"PENDING_PAYMENT", "PREPAID", "PAID"}
VALID_STATUS_TRANSITIONS = {
    "RECEIVED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"READY", "CANCELLED"},
    "READY": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def generate_upi_intent(amount: float, order_id: int | str) -> str:
    """Return the payment-app intent string used for this order's UPI checkout."""
    normalized_amount = f"{float(amount):.2f}"
    return (
        f"upi://pay?pa={UPI_VPA}&pn={UPI_MERCHANT_NAME}"
        f"&tr={order_id}&am={normalized_amount}&cu=INR"
    )


def build_escpos_kot_payload(order: dict, station: str) -> bytes:
    """Create a printer-ready ESC/POS ticket without relying on the browser."""
    def line(value: str = "") -> bytes:
        return (value + "\n").encode("ascii", errors="replace")

    payload = bytearray(b"\x1b@\x1ba\x01\x1d!\x11")
    payload.extend(line("KITCHEN ORDER TICKET"))
    payload.extend(b"\x1d!\x00")
    payload.extend(line(station))
    payload.extend(line(f"TOKEN #{order['token_number']}  {order['order_label']}"))
    payload.extend(line("-" * 32))
    for item in order["items"]:
        payload.extend(line(f"{item['quantity']}x {item['item_name']} [{item['tier']} ]"))
    if order["notes"]:
        payload.extend(line("-" * 32))
        payload.extend(line(f"NOTE: {order['notes']}"))
    payload.extend(b"\n\n\n\x1dV\x00")
    return bytes(payload)


def dispatch_kot_to_local_queue(order: dict, station: str) -> dict:
    """Atomically stage an ESC/POS payload for a local printer bridge to consume."""
    PRINT_QUEUE_DIR.mkdir(exist_ok=True)
    filename = f"kot-{order['id']}-{uuid.uuid4().hex[:8]}.escpos"
    queued_path = PRINT_QUEUE_DIR / filename
    temporary_path = PRINT_QUEUE_DIR / f".{filename}.tmp"
    temporary_path.write_bytes(build_escpos_kot_payload(order, station))
    temporary_path.replace(queued_path)
    return {"order_id": order["id"], "token_number": order["token_number"], "station": station, "queue_file": filename}


def get_settings_from_conn(conn):
    values = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}
    return {
        "tax_rate": float(values.get("tax_rate", "5")),
        "service_charge_rate": float(values.get("service_charge_rate", "0")),
        "printer_name": values.get("printer_name", "Browser print dialog"),
        "printer_station": values.get("printer_station", "Kitchen"),
    }


def order_label(row):
    order_type = row["order_type"]
    if order_type == "DINE_IN":
        return f"DINE-IN T-{row['table_number']}"
    if order_type == "TAKEAWAY":
        return f"TAKEAWAY #{row['token_number']}"
    return f"{row['source']} #{row['token_number']}"


def serialize_order(conn, row):
    items = conn.execute(
        "SELECT item_name, tier, price, quantity FROM order_items WHERE order_id = ? ORDER BY id",
        (row["id"],),
    ).fetchall()
    payments = conn.execute(
        "SELECT method, amount, created_at FROM payments WHERE order_id = ? ORDER BY id", (row["id"],)
    ).fetchall()
    result = {
        "id": row["id"],
        "order_number": row["order_number"],
        "token_number": row["token_number"],
        "token_date": row["token_date"],
        "order_type": row["order_type"],
        "source": row["source"],
        "order_label": order_label(row),
        "table_number": row["table_number"],
        "customer_phone": row["customer_phone"] or "",
        "customer_name": row["customer_name"] or "",
        "notes": row["notes"] or "",
        "status": row["status"],
        "subtotal": round(row["subtotal"], 2),
        "tax_rate": round(row["tax_rate"], 2),
        "tax_amount": round(row["tax_amount"], 2),
        "service_charge": round(row["service_charge"], 2),
        "grand_total": round(row["grand_total"], 2),
        "bill_generated": bool(row["bill_generated"]),
        "payment_status": row["payment_status"],
        "payments": [dict(payment) for payment in payments],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [dict(item) for item in items],
    }
    return result


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
    match = re.fullmatch(r"(?:table\s*|t\s*)?(\d+)", table_str_clean, flags=re.IGNORECASE)
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
    return str(table_num)


@app.get("/api/menu")
def get_menu():
    return MENU


@app.patch('/api/menu/{item_name}/toggle')
def toggle_menu_item(item_name: str, available: bool = Query(...)):
    item = find_item(item_name)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item['available'] = available
    with open(MENU_PATH, 'w', encoding='utf-8') as f:
        json.dump(MENU, f, indent=2)
    return {"message": "Success", "item_name": item_name, "available": available}



@app.post("/api/orders")
async def create_order(payload: OrderRequest):
    order_type = payload.order_type.upper().strip()
    if order_type not in VALID_ORDER_TYPES:
        raise HTTPException(status_code=400, detail="Order type must be DINE_IN, TAKEAWAY, or DELIVERY.")

    source = payload.source.upper().strip() or "WALK_IN"
    if order_type == "DELIVERY":
        if source not in VALID_DELIVERY_SOURCES:
            raise HTTPException(status_code=400, detail="Delivery source must be DELIVERY, SWIGGY, or ZOMATO.")
    else:
        source = "WALK_IN"

    validated_table = ""
    if order_type == "DINE_IN":
        if not payload.table_number:
            raise HTTPException(status_code=400, detail="A dine-in order requires a table number.")
        validated_table = validate_table_number(payload.table_number)

    customer_phone = re.sub(r"\D", "", payload.customer_phone or "")
    if customer_phone and len(customer_phone) != 10:
        raise HTTPException(status_code=400, detail="Customer mobile number must contain exactly 10 digits.")
    customer_name = payload.customer_name.strip()
    payment_status = payload.payment_status.upper().strip()
    if payment_status not in VALID_PAYMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Payment status must be PENDING_PAYMENT, PREPAID, or PAID.")

    # Never trust prices sent by the browser. Recalculate from menu.json on the server.
    normalized_items = []
    subtotal = 0.0
    for requested in payload.items:
        item = find_item(requested.item_name)
        if item is None:
            raise HTTPException(status_code=400, detail=f"Dish '{requested.item_name}' is not on the menu.")

        if item.get("available") is False:
            raise HTTPException(status_code=400, detail=f"Dish '{requested.item_name}' is currently unavailable (86'd).")


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

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    token_date = now_dt.astimezone(BUSINESS_TIMEZONE).date().isoformat()
    order_number = f"BLB-{now_dt.astimezone(BUSINESS_TIMEZONE).strftime('%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if order_type == "DINE_IN":
            active_order = conn.execute(
                "SELECT order_number FROM orders WHERE table_number = ? AND order_type = 'DINE_IN' "
                "AND status IN ('RECEIVED', 'PREPARING', 'READY')",
                (validated_table,),
            ).fetchone()
            if active_order:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Table {validated_table} already has an active order "
                        f"({active_order['order_number']}). Complete or cancel it before placing another order."
                    ),
                )

        token_number = int(
            conn.execute(
                "SELECT COALESCE(MAX(token_number), 0) FROM orders WHERE token_date = ?", (token_date,)
            ).fetchone()[0]
        ) + 1
        settings = get_settings_from_conn(conn)
        tax_amount = round(subtotal * settings["tax_rate"] / 100, 2)
        service_charge = round(subtotal * settings["service_charge_rate"] / 100, 2)
        grand_total = round(subtotal + tax_amount + service_charge, 2)

        if customer_phone:
            existing_customer = conn.execute(
                "SELECT name FROM customers WHERE phone = ?", (customer_phone,)
            ).fetchone()
            if not customer_name and existing_customer:
                customer_name = existing_customer["name"]
            conn.execute(
                "INSERT INTO customers (phone, name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(phone) DO UPDATE SET name = CASE WHEN excluded.name <> '' THEN excluded.name ELSE customers.name END, "
                "updated_at = excluded.updated_at",
                (customer_phone, customer_name, now, now),
            )

        cur = conn.execute(
            """
            INSERT INTO orders (
                order_number, token_number, token_date, order_type, source, table_number,
                customer_phone, customer_name, notes, status, subtotal, tax_rate, tax_amount,
                service_charge, grand_total, payment_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_number, token_number, token_date, order_type, source, validated_table,
                customer_phone or None, customer_name, payload.notes.strip(), round(subtotal, 2),
                settings["tax_rate"], tax_amount, service_charge, grand_total, payment_status, now, now,
            ),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, item_name, tier, price, quantity) VALUES (?, ?, ?, ?, ?)",
            [(order_id, *item) for item in normalized_items],
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        created_order = serialize_order(conn, row)

    await events.publish("order.created", created_order)
    if payment_status == "PREPAID":
        print_event = dispatch_kot_to_local_queue(created_order, settings["printer_station"])
        await events.publish("kot.auto_printed", print_event)
    return created_order


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


@app.get("/api/orders/{order_id}/upi-intent")
def get_upi_intent(order_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        if row["status"] == "CANCELLED":
            raise HTTPException(status_code=409, detail="A cancelled order cannot be paid.")
        return {
            "order_id": order_id,
            "amount": round(row["grand_total"], 2),
            "upi_intent": generate_upi_intent(row["grand_total"], order_id),
        }


@app.post("/api/webhooks/mock-payment")
async def mock_payment_webhook(payload: MockPaymentWebhookRequest):
    """Idempotent development webhook that confirms an order's UPI payment."""
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (payload.order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        if row["status"] == "CANCELLED":
            raise HTTPException(status_code=409, detail="A cancelled order cannot be paid.")

        now = datetime.now(timezone.utc).isoformat()
        has_upi_payment = conn.execute(
            "SELECT 1 FROM payments WHERE order_id = ? AND method = 'UPI'", (payload.order_id,)
        ).fetchone()
        if not has_upi_payment:
            conn.execute(
                "INSERT INTO payments (order_id, method, amount, created_at) VALUES (?, 'UPI', ?, ?)",
                (payload.order_id, row["grand_total"], now),
            )
        conn.execute(
            "UPDATE orders SET payment_status = 'PAID', bill_generated = 1, updated_at = ? WHERE id = ?",
            (now, payload.order_id),
        )
        paid_row = conn.execute("SELECT * FROM orders WHERE id = ?", (payload.order_id,)).fetchone()
        paid_order = serialize_order(conn, paid_row)

    await events.publish("order.payment_confirmed", paid_order)
    return {"ok": True, "order": paid_order}


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await events.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        events.disconnect(websocket)


@app.post("/api/orders/{order_id}/bill")
async def generate_bill(order_id: int, payload: Optional[BillRequest] = None):
    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        if row["status"] == "CANCELLED":
            raise HTTPException(status_code=409, detail="A cancelled order cannot be billed.")
        if row["bill_generated"]:
            return serialize_order(conn, row)

        requested_payments = payload.payments if payload else []
        if not requested_payments:
            requested_payments = [PaymentLineRequest(method="CASH", amount=row["grand_total"])]

        payments = []
        for payment in requested_payments:
            method = payment.method.upper().strip()
            if method not in VALID_PAYMENT_METHODS:
                raise HTTPException(status_code=400, detail="Payment method must be CASH, UPI, or CARD.")
            payments.append((method, round(payment.amount, 2)))

        paid_total = round(sum(amount for _, amount in payments), 2)
        if abs(paid_total - round(row["grand_total"], 2)) > 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"Payment total must equal ₹{row['grand_total']:.2f}.",
            )
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO payments (order_id, method, amount, created_at) VALUES (?, ?, ?, ?)",
            [(order_id, method, amount, now) for method, amount in payments],
        )
        conn.execute(
            "UPDATE orders SET bill_generated = 1, payment_status = 'PAID', updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        billed_order = serialize_order(conn, row)
    await events.publish("order.payment_received", billed_order)
    return billed_order


@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, payload: StatusRequest):
    status = payload.status.upper().strip()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid order status.")

    with db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        if status not in VALID_STATUS_TRANSITIONS[row["status"]]:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change an order from {row['status']} to {status}.",
            )
        if status == "COMPLETED" and not row["bill_generated"] and row["payment_status"] not in {"PREPAID", "PAID"}:
            raise HTTPException(status_code=409, detail="Generate and collect the bill before completing this order.")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, order_id),
        )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        updated_order = serialize_order(conn, row)
    await events.publish("order.status_changed", updated_order)
    return updated_order


@app.get("/api/revenue/summary")
def revenue_summary():
    business_now = datetime.now(BUSINESS_TIMEZONE)
    day_start = business_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    start_utc = day_start.astimezone(timezone.utc).isoformat()
    end_utc = day_end.astimezone(timezone.utc).isoformat()
    with db() as conn:
        revenue_row = conn.execute(
            "SELECT COALESCE(SUM(grand_total), 0) AS revenue, COUNT(*) AS completed_orders "
            "FROM orders WHERE status = 'COMPLETED' AND created_at >= ? AND created_at < ?",
            (start_utc, end_utc),
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status IN ('RECEIVED', 'PREPARING', 'READY')"
        ).fetchone()["count"]
        all_completed = conn.execute(
            "SELECT COALESCE(SUM(grand_total), 0) AS revenue, COUNT(*) AS count FROM orders WHERE status = 'COMPLETED'"
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
    item_name = payload.item_name.strip()
    unit = payload.unit.strip()
    if not item_name:
        raise HTTPException(status_code=400, detail="Inventory item name is required.")
    if not unit:
        raise HTTPException(status_code=400, detail="Inventory unit is required.")
    with db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO inventory (item_name, stock, unit) VALUES (?, ?, ?)",
                (item_name, payload.stock, unit),
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


@app.get("/api/customers/{phone}")
def get_customer(phone: str):
    normalized_phone = re.sub(r"\D", "", phone)
    if len(normalized_phone) != 10:
        raise HTTPException(status_code=400, detail="Customer mobile number must contain exactly 10 digits.")
    with db() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE phone = ?", (normalized_phone,)).fetchone()
        if not customer:
            return {"phone": normalized_phone, "name": "", "is_new": True, "favorites": [], "orders": []}
        orders = conn.execute(
            "SELECT * FROM orders WHERE customer_phone = ? ORDER BY id DESC LIMIT 10", (normalized_phone,)
        ).fetchall()
        favorites = conn.execute(
            "SELECT oi.item_name, COUNT(*) AS times_ordered FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id WHERE o.customer_phone = ? "
            "AND o.status != 'CANCELLED' GROUP BY oi.item_name ORDER BY times_ordered DESC, oi.item_name LIMIT 3",
            (normalized_phone,),
        ).fetchall()
        return {
            "phone": normalized_phone,
            "name": customer["name"],
            "is_new": False,
            "favorites": [dict(favorite) for favorite in favorites],
            "orders": [serialize_order(conn, order) for order in orders],
        }


@app.get("/api/settings")
def get_settings():
    with db() as conn:
        return get_settings_from_conn(conn)


@app.patch("/api/settings")
def update_settings(payload: SettingsRequest):
    values = {
        "tax_rate": str(payload.tax_rate),
        "service_charge_rate": str(payload.service_charge_rate),
        "printer_name": payload.printer_name.strip(),
        "printer_station": payload.printer_station.strip(),
    }
    if not values["printer_name"] or not values["printer_station"]:
        raise HTTPException(status_code=400, detail="Printer name and station are required.")
    with db() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        return get_settings_from_conn(conn)


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
            "SELECT COALESCE(SUM(grand_total), 0) AS revenue, COUNT(*) AS completed_orders "
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

class PrintPayload(BaseModel):
    receipt_type: str
    order: dict

@app.post("/api/printer/print")
def print_receipt(payload: PrintPayload):
    import time
    time.sleep(0.1) # Simulate print spooler delay
    if payload.receipt_type == 'KOT':
        aggregated = {}
        for item in payload.order.get('items', []):
            tier = item.get('tier', 'Standard')
            # Group by item name and tier/modifier
            key = f"{item['item_name']} ({tier})" if tier and tier not in ('Standard', 'S', 'M', 'L') else item['item_name']
            if key not in aggregated:
                aggregated[key] = 0
            aggregated[key] += item.get('quantity', 1)
        
        print(f"\n=== PRINTER BRIDGE: KOT ===")
        print(f"TABLE: {payload.order.get('table_number')} | TOKEN: {payload.order.get('token_number')}")
        for k, v in aggregated.items():
            print(f"{v}x {k}")
        if payload.order.get('notes'):
            print(f"NOTES: {payload.order['notes']}")
        print("===========================\n")
    else:
        print(f"\n=== PRINTER BRIDGE: BILL ===")
        print(f"TOKEN: {payload.order.get('token_number')}")
        print(f"TOTAL: Rs. {payload.order.get('grand_total')}")
        print("============================\n")
    
    return {"status": "success"}

class TillFloat(BaseModel):
    opening_float: float

@app.post("/api/revenue/open-register")
def open_register(payload: TillFloat):
    date_str = datetime.now(BUSINESS_TIMEZONE).strftime("%Y-%m-%d")
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO till_sessions (date, opening_float) VALUES (?, ?)", (date_str, payload.opening_float))
        conn.execute("UPDATE till_sessions SET opening_float = ? WHERE date = ? AND closed = 0", (payload.opening_float, date_str))
    return {"status": "success"}

class TillClose(BaseModel):
    actual_cash: float

@app.post("/api/revenue/close-register")
def close_register(payload: TillClose):
    business_now = datetime.now(BUSINESS_TIMEZONE)
    date_str = business_now.strftime("%Y-%m-%d")
    day_start = business_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    with db() as conn:
        session = conn.execute("SELECT * FROM till_sessions WHERE date = ?", (date_str,)).fetchone()
        opening_float = session['opening_float'] if session else 0.0
        
        cash_sales = conn.execute("""
            SELECT COALESCE(SUM(p.amount), 0) as total 
            FROM payments p
            JOIN orders o ON p.order_id = o.id
            WHERE p.method = 'CASH' AND o.created_at >= ? AND o.created_at < ?
        """, (day_start.astimezone(timezone.utc).isoformat(), day_end.astimezone(timezone.utc).isoformat())).fetchone()['total']
        
        variance = payload.actual_cash - (opening_float + cash_sales)
        
        # ensure session exists
        if not session:
            conn.execute("INSERT INTO till_sessions (date, opening_float) VALUES (?, ?)", (date_str, 0.0))
            
        conn.execute("""
            UPDATE till_sessions 
            SET closed = 1, actual_cash = ?, variance = ?, closed_at = ?
            WHERE date = ?
        """, (payload.actual_cash, variance, business_now.isoformat(), date_str))
        
        return {"variance": round(variance, 2), "expected_cash": round(opening_float + cash_sales, 2)}
        
@app.get("/api/revenue/till")
def get_till():
    date_str = datetime.now(BUSINESS_TIMEZONE).strftime("%Y-%m-%d")
    with db() as conn:
        session = conn.execute("SELECT * FROM till_sessions WHERE date = ?", (date_str,)).fetchone()
        return dict(session) if session else {"opening_float": 0, "closed": 0}
