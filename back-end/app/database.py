import os
from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine

_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./marqab.db")
engine = create_engine(_DB_URL, connect_args={"check_same_thread": False})

DEFAULT_UNITS = [
    {
        "unit_id": "vision-01",
        "unit_type": "vision",
        "name": "Vision Node 01",
        "lat": 24.7636,
        "lng": 46.7253,
    },
    {
        "unit_id": "vision-02",
        "unit_type": "vision",
        "name": "Vision Node 02",
        "lat": 24.6636,
        "lng": 46.6253,
    },
    {
        "unit_id": "acoustic-01",
        "unit_type": "acoustic",
        "name": "Acoustic Node 01",
        "lat": 24.7136,
        "lng": 46.7753,
    },
    {
        "unit_id": "camera-local",
        "unit_type": "vision",
        "name": "Local Camera",
        "lat": 24.7136,
        "lng": 46.6753,
    },
    {
        "unit_id": "mic-local",
        "unit_type": "acoustic",
        "name": "Local Microphone",
        "lat": 24.7136,
        "lng": 46.6753,
    },
]


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def init_default_units() -> None:
    from sqlmodel import select
    from app.models import Unit

    with Session(engine) as session:
        # Insert any missing default units
        for data in DEFAULT_UNITS:
            if session.get(Unit, data["unit_id"]) is None:
                session.add(
                    Unit(
                        **data,
                        status="offline",
                        last_seen=datetime.now(timezone.utc),
                    )
                )

        # Reset ALL units to offline on every startup.
        # Status is set to "online" only when a unit actively sends data;
        # a server restart means no units are connected yet.
        for unit in session.exec(select(Unit)).all():
            unit.status = "offline"
            session.add(unit)

        session.commit()
