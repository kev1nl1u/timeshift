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

    return {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat(),
        "clients": clients_data,
        "sessions": sessions_data,
    }


class ImportPayload(BaseModel):
    version: int = 1
    clients: List[dict]
    sessions: List[dict]


@app.post("/import")
def import_data(payload: ImportPayload, db: Session = Depends(get_db)):
    # Clear existing data (sessions first due to FK)
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
            continue  # skip orphan sessions
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

    db.commit()
    return {"imported_clients": len(id_map), "imported_sessions": len(payload.sessions)}
