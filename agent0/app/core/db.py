import os
import psycopg2
from contextlib import contextmanager


def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


@contextmanager
def get_db():
    
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
