# Big Little Bombaye POS

Two-interface cafe POS:

- Customer: `/menu` (QR codes can use `/menu?table=12`)
- Cafe: `/staff`
- Backend/API: FastAPI + SQLite (`pos.db`)
- AI Butler: optional Groq integration

## Run

```powershell
.\start.bat
```

Open:

- http://localhost:8000/menu
- http://localhost:8000/staff

Orders are persisted in `pos.db`. Revenue is calculated from completed orders; history stores completed and cancelled orders.

Keep `.env` private and never commit it. Use `.env.example` for GitHub.
