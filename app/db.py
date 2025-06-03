# app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession # Alias to avoid confusion
from app.config import settings
from app.models import Base # Ensure Base is imported if needed for create_all, though Alembic handles it

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db_session() -> SQLAlchemySession:
    """Dependency to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Optional: function to create all tables (useful for testing without Alembic, but Alembic is primary)
# def init_db():
#     Base.metadata.create_all(bind=engine)

# if __name__ == '__main__':
#     # For basic connectivity test or initial table creation if not using Alembic for that
#     print(f"Database URL: {settings.DATABASE_URL}")
#     print("Attempting to connect to the database...")
#     try:
#         with engine.connect() as connection:
#             print("Successfully connected to the database.")
#         # init_db() # Call this if you want to create tables directly (e.g., for a quick test setup)
#         # print("Database tables initialized (if not already present).")
#     except Exception as e:
#         print(f"Failed to connect to the database: {e}")
