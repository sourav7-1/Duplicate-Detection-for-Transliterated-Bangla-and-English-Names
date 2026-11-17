"""Cached PostgreSQL connection for the Streamlit app (settings from .env)."""
import streamlit as st

from load_data import connect


@st.cache_resource
def _cached_conn():
    """One connection per server process, reused across reruns and sessions.
    A failed connect raises and is not cached, so the next rerun tries again."""
    conn = connect()          # reads DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD from .env
    conn.autocommit = True
    return conn


def get_conn():
    """The cached connection; reconnects if it was closed or broke (e.g. server restart)."""
    conn = _cached_conn()
    if conn.closed or conn.broken:
        _cached_conn.clear()
        conn = _cached_conn()
    return conn


def connection_error():
    """None if the database answers, otherwise the error text (for the help message)."""
    try:
        with get_conn().cursor() as cur:
            cur.execute("SELECT 1")
        return None
    except Exception as e:  # bad .env values, server down, database missing, ...
        _cached_conn.clear()
        return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
