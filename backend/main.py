import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship, Session

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./timeshift.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    hourly_rate = Column(Float, nullable=False)
    color = Column(String, default="#6366F1")
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("WorkSession", back_populates="client", cascade="all, delete-orphan")


class WorkSession(Base):
    __tablename__ = "work_sessions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    date = Column(String, nullable=False)        # YYYY-MM-DD
    start_time = Column(String, nullable=True)   # HH:MM
    end_time = Column(String, nullable=True)      # HH:MM
    hours = Column(Float, nullable=False)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="sessions")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    icon = Column(String, default="💳")
    color = Column(String, default="#6366F1")
    initial_balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)           # expense, income, transfer
    amount = Column(Float, nullable=False)
    date = Column(String, nullable=False)            # YYYY-MM-DD
    category = Column(String, default="")
    description = Column(Text, default="")
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id])
    to_account = relationship("Account", foreign_keys=[to_account_id])


Base.metadata.create_all(bind=engine)

app = FastAPI(title="TimeShift API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str
    hourly_rate: float
    color: str = "#6366F1"


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    hourly_rate: Optional[float] = None
    color: Optional[str] = None


class ClientOut(BaseModel):
    id: int
    name: str
    hourly_rate: float
    color: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkSessionCreate(BaseModel):
    client_id: int
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: Optional[float] = None
    note: str = ""


class WorkSessionUpdate(BaseModel):
    client_id: Optional[int] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: Optional[float] = None
    note: Optional[str] = None


class WorkSessionOut(BaseModel):
    id: int
    client_id: int
    date: str
    start_time: Optional[str]
    end_time: Optional[str]
    hours: float
    note: str
    client: ClientOut

    model_config = {"from_attributes": True}


# ── Account schemas ──────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    icon: str = "💳"
    color: str = "#6366F1"
    initial_balance: float = 0.0


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    initial_balance: Optional[float] = None


class AccountOut(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    initial_balance: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Transaction schemas ──────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type: str                        # expense, income, transfer
    amount: float
    date: str
    category: str = ""
    description: str = ""
    account_id: int
    to_account_id: Optional[int] = None


class TransactionUpdate(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    account_id: Optional[int] = None
    to_account_id: Optional[int] = None


class TransactionOut(BaseModel):
    id: int
    type: str
    amount: float
    date: str
    category: str
    description: str
    account_id: int
    to_account_id: Optional[int]
    account: AccountOut
    to_account: Optional[AccountOut]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_hours(start: str, end: str) -> float:
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    mins = (eh * 60 + em) - (sh * 60 + sm)
    if mins < 0:
        mins += 24 * 60
    return round(mins / 60, 2)


# ── Client endpoints ──────────────────────────────────────────────────────────

@app.get("/clients", response_model=List[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).order_by(Client.created_at).all()


@app.post("/clients", response_model=ClientOut, status_code=201)
def create_client(data: ClientCreate, db: Session = Depends(get_db)):
    client = Client(**data.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@app.put("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: int, data: ClientUpdate, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(client, k, v)
    db.commit()
    db.refresh(client)
    return client


@app.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    db.delete(client)
    db.commit()


# ── Session endpoints ─────────────────────────────────────────────────────────

@app.get("/sessions", response_model=List[WorkSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(WorkSession).order_by(WorkSession.date.desc(), WorkSession.id.desc()).all()


@app.post("/sessions", response_model=WorkSessionOut, status_code=201)
def create_session(data: WorkSessionCreate, db: Session = Depends(get_db)):
    hours = data.hours
    if hours is None:
        if data.start_time and data.end_time:
            hours = _compute_hours(data.start_time, data.end_time)
        else:
            raise HTTPException(status_code=422, detail="Inserisci le ore oppure inizio e fine")
    payload = data.model_dump()
    payload["hours"] = hours
    session = WorkSession(**payload)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.put("/sessions/{session_id}", response_model=WorkSessionOut)
def update_session(session_id: int, data: WorkSessionUpdate, db: Session = Depends(get_db)):
    session = db.query(WorkSession).filter(WorkSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    updates = data.model_dump(exclude_unset=True)
    # Recompute hours if times changed but hours not explicitly provided
    if "hours" not in updates:
        start = updates.get("start_time", session.start_time)
        end = updates.get("end_time", session.end_time)
        if start and end:
            updates["hours"] = _compute_hours(start, end)
    for k, v in updates.items():
        setattr(session, k, v)
    db.commit()
    db.refresh(session)
    return session


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(WorkSession).filter(WorkSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    db.delete(session)
    db.commit()


# ── Account endpoints ────────────────────────────────────────────────────────

@app.get("/accounts", response_model=List[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.created_at).all()


@app.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    account = Account(**data.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@app.put("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Conto non trovato")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(account, k, v)
    db.commit()
    db.refresh(account)
    return account


@app.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Conto non trovato")
    # Check for transactions
    tx_count = db.query(Transaction).filter(
        (Transaction.account_id == account_id) | (Transaction.to_account_id == account_id)
    ).count()
    if tx_count > 0:
        db.query(Transaction).filter(
            (Transaction.account_id == account_id) | (Transaction.to_account_id == account_id)
        ).delete(synchronize_session=False)
    db.delete(account)
    db.commit()


# ── Transaction endpoints ────────────────────────────────────────────────────

@app.get("/transactions", response_model=List[TransactionOut])
def list_transactions(db: Session = Depends(get_db)):
    return db.query(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).all()


@app.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    if data.type not in ("expense", "income", "transfer"):
        raise HTTPException(status_code=422, detail="Tipo deve essere: expense, income, transfer")
    if data.type == "transfer" and not data.to_account_id:
        raise HTTPException(status_code=422, detail="Seleziona il conto di destinazione")
    if data.type == "transfer" and data.account_id == data.to_account_id:
        raise HTTPException(status_code=422, detail="Il conto di origine e destinazione devono essere diversi")
    tx = Transaction(**data.model_dump())
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


@app.put("/transactions/{tx_id}", response_model=TransactionOut)
def update_transaction(tx_id: int, data: TransactionUpdate, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Movimento non trovato")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(tx, k, v)
    db.commit()
    db.refresh(tx)
    return tx


@app.delete("/transactions/{tx_id}", status_code=204)
def delete_transaction(tx_id: int, db: Session = Depends(get_db)):
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Movimento non trovato")
    db.delete(tx)
    db.commit()


# ── Finance stats endpoint ───────────────────────────────────────────────────

@app.get("/finance-stats")
def get_finance_stats(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    transactions = db.query(Transaction).all()

    account_balances = []
    total_balance = 0.0
    total_income = 0.0
    total_expenses = 0.0

    for acc in accounts:
        balance = acc.initial_balance
        for tx in transactions:
            if tx.type == "income" and tx.account_id == acc.id:
                balance += tx.amount
            elif tx.type == "expense" and tx.account_id == acc.id:
                balance -= tx.amount
            elif tx.type == "transfer":
                if tx.account_id == acc.id:
                    balance -= tx.amount
                elif tx.to_account_id == acc.id:
                    balance += tx.amount
        total_balance += balance
        account_balances.append({
            "account_id": acc.id,
            "account_name": acc.name,
            "account_icon": acc.icon,
            "account_color": acc.color,
            "balance": round(balance, 2),
        })

    for tx in transactions:
        if tx.type == "income":
            total_income += tx.amount
        elif tx.type == "expense":
            total_expenses += tx.amount

    # Expenses by category
    by_category = {}
    for tx in transactions:
        if tx.type == "expense":
            cat = tx.category or "Altro"
            by_category[cat] = by_category.get(cat, 0) + tx.amount
    expenses_by_category = [{"category": k, "amount": round(v, 2)} for k, v in sorted(by_category.items(), key=lambda x: -x[1])]

    # Account balance history over time
    account_history = []
    if accounts and transactions:
        sorted_txs = sorted(transactions, key=lambda t: t.date)
        # Collect all unique dates
        all_dates = sorted(set(t.date for t in sorted_txs))
        for acc in accounts:
            running = acc.initial_balance
            points = [{"date": all_dates[0], "balance": round(running, 2)}] if all_dates else []
            # Pre-group transactions by date for this account
            for d in all_dates:
                for tx in sorted_txs:
                    if tx.date != d:
                        continue
                    if tx.type == "income" and tx.account_id == acc.id:
                        running += tx.amount
                    elif tx.type == "expense" and tx.account_id == acc.id:
                        running -= tx.amount
                    elif tx.type == "transfer":
                        if tx.account_id == acc.id:
                            running -= tx.amount
                        elif tx.to_account_id == acc.id:
                            running += tx.amount
                points.append({"date": d, "balance": round(running, 2)})
            account_history.append({
                "account_id": acc.id,
                "account_name": acc.name,
                "account_color": acc.color,
                "points": points,
            })

    return {
        "account_balances": account_balances,
        "total_balance": round(total_balance, 2),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "expenses_by_category": expenses_by_category,
        "account_history": account_history,
    }


# ── AI operator context endpoint ─────────────────────────────────────────────

@app.get("/ai-context")
def get_ai_context(db: Session = Depends(get_db)):
    """Returns everything an AI operator needs to build valid transaction JSON."""
    accs = db.query(Account).order_by(Account.id).all()
    return {
        "accounts": [
            {"id": a.id, "name": a.name}
            for a in accs
        ],
        "expense_categories": [
            "Cibo", "Trasporti", "Casa", "Abbigliamento", "Svago",
            "Salute", "Bollette", "Spesa", "Ristorante", "Regali", "Altro",
        ],
        "income_categories": [
            "Stipendio", "Freelance", "Regalo", "Rimborso", "Investimenti", "Altro",
        ],
        "transaction_schema": {
            "description": "Array di oggetti transazione da inviare via POST a /api/transactions/bulk",
            "items": {
                "type": {
                    "type": "string",
                    "enum": ["expense", "income", "transfer"],
                    "required": True,
                },
                "amount": {
                    "type": "number",
                    "description": "Importo positivo in euro (es. 12.50)",
                    "required": True,
                },
                "date": {
                    "type": "string",
                    "format": "YYYY-MM-DD",
                    "description": "Data del movimento (es. 2026-03-21)",
                    "required": True,
                },
                "account_id": {
                    "type": "integer",
                    "description": "ID del conto (vedi lista accounts)",
                    "required": True,
                },
                "to_account_id": {
                    "type": "integer | null",
                    "description": "Solo per type=transfer: ID del conto di destinazione",
                    "required": False,
                },
                "category": {
                    "type": "string",
                    "description": "Categoria (vedi expense_categories o income_categories). Vuoto per transfer.",
                    "required": False,
                },
                "description": {
                    "type": "string",
                    "description": "Descrizione libera del movimento",
                    "required": False,
                },
            },
        },
        "example": [
            {
                "type": "expense",
                "amount": 45.00,
                "date": "2026-03-21",
                "account_id": accs[0].id if accs else 1,
                "category": "Spesa",
                "description": "Spesa settimanale al supermercato",
            },
            {
                "type": "income",
                "amount": 1500.00,
                "date": "2026-03-01",
                "account_id": accs[0].id if accs else 1,
                "category": "Stipendio",
                "description": "Stipendio Marzo",
            },
            {
                "type": "transfer",
                "amount": 200.00,
                "date": "2026-03-15",
                "account_id": accs[0].id if accs else 1,
                "to_account_id": accs[1].id if len(accs) > 1 else 2,
                "category": "",
                "description": "Ricarica contanti",
            },
        ],
        "bulk_endpoint": {
            "method": "POST",
            "path": "/api/transactions/bulk",
            "body": {
                "transactions": "[ ...array di oggetti come da schema sopra... ]"
            },
            "description": "Invia un array di transazioni. Restituisce il conteggio degli inserimenti.",
        },
    }


# ── Bulk transactions endpoint ───────────────────────────────────────────────

class BulkTransactionsPayload(BaseModel):
    transactions: List[TransactionCreate]


@app.post("/transactions/bulk")
def bulk_create_transactions(payload: BulkTransactionsPayload, db: Session = Depends(get_db)):
    created = 0
    errors = []
    for i, data in enumerate(payload.transactions):
        if data.type not in ("expense", "income", "transfer"):
            errors.append(f"[{i}] Tipo non valido: {data.type}")
            continue
        if data.type == "transfer" and not data.to_account_id:
            errors.append(f"[{i}] Manca to_account_id per transfer")
            continue
        if data.type == "transfer" and data.account_id == data.to_account_id:
            errors.append(f"[{i}] account_id e to_account_id devono essere diversi")
            continue
        acc = db.query(Account).filter(Account.id == data.account_id).first()
        if not acc:
            errors.append(f"[{i}] account_id {data.account_id} non trovato")
            continue
        if data.to_account_id:
            to_acc = db.query(Account).filter(Account.id == data.to_account_id).first()
            if not to_acc:
                errors.append(f"[{i}] to_account_id {data.to_account_id} non trovato")
                continue
        tx = Transaction(**data.model_dump())
        db.add(tx)
        created += 1
    db.commit()
    return {"created": created, "errors": errors}


# ── Stats endpoint ────────────────────────────────────────────────────────────

@app.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    clients = db.query(Client).all()
    by_client = []
    total_hours = 0.0
    total_earnings = 0.0

    for client in clients:
        client_hours = sum(s.hours for s in client.sessions)
        client_earnings = client_hours * client.hourly_rate
        total_hours += client_hours
        total_earnings += client_earnings
        by_client.append({
            "client_id": client.id,
            "client_name": client.name,
            "client_color": client.color,
            "hourly_rate": client.hourly_rate,
            "total_hours": round(client_hours, 2),
            "total_earnings": round(client_earnings, 2),
        })

    return {
        "by_client": by_client,
        "total_hours": round(total_hours, 2),
        "total_earnings": round(total_earnings, 2),
    }


# ── Export / Import ──────────────────────────────────────────────────────────

@app.get("/export")
def export_data(db: Session = Depends(get_db)):
    clients_data = []
    for c in db.query(Client).order_by(Client.id).all():
        clients_data.append({
            "id": c.id,
            "name": c.name,
            "hourly_rate": c.hourly_rate,
            "color": c.color,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    sessions_data = []
    for s in db.query(WorkSession).order_by(WorkSession.id).all():
        sessions_data.append({
            "id": s.id,
            "client_id": s.client_id,
            "date": s.date,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "hours": s.hours,
            "note": s.note,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    accounts_data = []
    for a in db.query(Account).order_by(Account.id).all():
        accounts_data.append({
            "id": a.id,
            "name": a.name,
            "icon": a.icon,
            "color": a.color,
            "initial_balance": a.initial_balance,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })

    transactions_data = []
    for t in db.query(Transaction).order_by(Transaction.id).all():
        transactions_data.append({
            "id": t.id,
            "type": t.type,
            "amount": t.amount,
            "date": t.date,
            "category": t.category,
            "description": t.description,
            "account_id": t.account_id,
            "to_account_id": t.to_account_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "version": 2,
        "exported_at": datetime.utcnow().isoformat(),
        "clients": clients_data,
        "sessions": sessions_data,
        "accounts": accounts_data,
        "transactions": transactions_data,
    }


class ImportPayload(BaseModel):
    version: int = 1
    clients: List[dict]
    sessions: List[dict]
    accounts: List[dict] = []
    transactions: List[dict] = []


@app.post("/import")
def import_data(payload: ImportPayload, db: Session = Depends(get_db)):
    # Clear existing data (children first due to FK)
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.query(WorkSession).delete()
    db.query(Client).delete()
    db.commit()

    # Map old client IDs to new ones
    id_map = {}
    for c in payload.clients:
        client = Client(
            name=c["name"],
            hourly_rate=c["hourly_rate"],
            color=c.get("color", "#6366F1"),
        )
        if c.get("created_at"):
            try:
                client.created_at = datetime.fromisoformat(c["created_at"])
            except (ValueError, TypeError):
                pass
        db.add(client)
        db.flush()
        id_map[c["id"]] = client.id

    for s in payload.sessions:
        new_client_id = id_map.get(s["client_id"])
        if new_client_id is None:
            continue
        session = WorkSession(
            client_id=new_client_id,
            date=s["date"],
            start_time=s.get("start_time"),
            end_time=s.get("end_time"),
            hours=s["hours"],
            note=s.get("note", ""),
        )
        if s.get("created_at"):
            try:
                session.created_at = datetime.fromisoformat(s["created_at"])
            except (ValueError, TypeError):
                pass
        db.add(session)

    # Import accounts
    acc_map = {}
    for a in payload.accounts:
        account = Account(
            name=a["name"],
            icon=a.get("icon", "💳"),
            color=a.get("color", "#6366F1"),
            initial_balance=a.get("initial_balance", 0),
        )
        if a.get("created_at"):
            try:
                account.created_at = datetime.fromisoformat(a["created_at"])
            except (ValueError, TypeError):
                pass
        db.add(account)
        db.flush()
        acc_map[a["id"]] = account.id

    for t in payload.transactions:
        new_acc_id = acc_map.get(t["account_id"])
        if new_acc_id is None:
            continue
        new_to_acc_id = acc_map.get(t.get("to_account_id")) if t.get("to_account_id") else None
        tx = Transaction(
            type=t["type"],
            amount=t["amount"],
            date=t["date"],
            category=t.get("category", ""),
            description=t.get("description", ""),
            account_id=new_acc_id,
            to_account_id=new_to_acc_id,
        )
        if t.get("created_at"):
            try:
                tx.created_at = datetime.fromisoformat(t["created_at"])
            except (ValueError, TypeError):
                pass
        db.add(tx)

    db.commit()
    return {
        "imported_clients": len(id_map),
        "imported_sessions": len(payload.sessions),
        "imported_accounts": len(acc_map),
        "imported_transactions": len(payload.transactions),
    }
