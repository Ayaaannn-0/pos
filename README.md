# Big Little Bombaye POS

Two-interface cafe POS with a customer QR ordering flow and a staff operations portal.

## Customer
- `/menu`
- QR links can use `/menu?table=7`
- Browse menu, choose variants, add to cart, enter table/notes, place order

## Staff
- `/staff`
- Overview with live orders, revenue, floor status, and recent history
- Manual Orders with live table occupancy and 12 tables
- Inventory with stock editing
- Insights with revenue/order/AOV metrics
- History with search and status filtering
- Bill generation and printable receipt
- Order lifecycle: RECEIVED → PREPARING → READY → COMPLETED/CANCELLED

## Data
- FastAPI backend
- SQLite database (`pos.db`, created automatically)
- Prices are recalculated server-side from `menu.json`
- Revenue is counted from completed orders
- AI Butler is optional and does not block POS ordering

## Run

```powershell
.\\start.bat
```

Open:

- http://localhost:8000/menu
- http://localhost:8000/staff

Keep `.env` private and never commit it. Use `.env.example` for GitHub.
