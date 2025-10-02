"""Database adapter - automatically selects SQLite or PostgreSQL based on DATABASE_URL."""
import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    from .db_postgres import *
else:
    from .db import *
