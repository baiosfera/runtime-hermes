"""
Hermes Database Manager & Auto-Initialization Engine
Ensures idempotent schema bootstrapping and resilient persistence across container cold-boots and restarts.
"""
import os
import sys
import logging
from typing import Optional

logger = logging.getLogger("hermes.db")

SCHEMA_DDL = """
-- 1. Hermes Chat Messages (Conversational SSoT)
CREATE TABLE IF NOT EXISTS hermes_messages (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hermes_messages_chat_id ON hermes_messages (chat_id, id DESC);

-- 2. General Store Settings & Meta
CREATE TABLE IF NOT EXISTS site_settings (
    key VARCHAR(255) PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Products Catalog (Business-Agnostic)
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    base_price NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    stock INT NOT NULL DEFAULT 0,
    images JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_products_slug ON products (slug);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products (is_active);

-- 4. Services & Consulting Catalog
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    duration_minutes INT NOT NULL DEFAULT 60,
    images JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_services_slug ON services (slug);
CREATE INDEX IF NOT EXISTS idx_services_is_active ON services (is_active);

-- 5. Orders & Transactions
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(50),
    customer_email VARCHAR(255),
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at DESC);

-- 6. Bookings & Appointments
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(50),
    customer_email VARCHAR(255),
    service_name VARCHAR(255) NOT NULL,
    appointment_date TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL DEFAULT 'confirmed',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings (appointment_date);

-- 7. Client Astrological Feeds & Dumps
CREATE TABLE IF NOT EXISTS client_feeds (
    id SERIAL PRIMARY KEY,
    client_id UUID NOT NULL,
    feed_name VARCHAR(100) NOT NULL,
    feed_xml TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_client_feeds_client_id ON client_feeds (client_id);

CREATE TABLE IF NOT EXISTS client_dumps (
    id SERIAL PRIMARY KEY,
    client_id UUID NOT NULL UNIQUE,
    dump_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

SQLITE_FALLBACK_DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS hermes_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hermes_messages_chat_id ON hermes_messages (chat_id, id DESC);
"""

async def init_db() -> bool:
    """
    Auto-initializes PostgreSQL 18 tables and local SQLite replica idempotently.
    Returns True if PostgreSQL is connected and initialized, False on failure.
    """
    db_url = os.getenv("DATABASE_URL")
    pg_ok = False
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url, timeout=5.0)
            await conn.execute(SCHEMA_DDL)
            await conn.close()
            print("[Hermes DB] PostgreSQL 18 schema auto-initialized and verified successfully.")
            pg_ok = True
        except Exception as e:
            print(f"[Hermes DB ERROR] PostgreSQL schema initialization failed: {e}", file=sys.stderr)
    else:
        print("[Hermes DB WARNING] DATABASE_URL not set in environment.", file=sys.stderr)

    # Initialize local SQLite WAL replica
    try:
        import aiosqlite
        local_dir = os.getenv("LOCAL_STORAGE_PATH", "/mnt/localstorage/hermes")
        os.makedirs(local_dir, exist_ok=True)
        db_path = os.path.join(local_dir, "sessions.db")
        async with aiosqlite.connect(db_path, timeout=5.0) as sdb:
            await sdb.executescript(SQLITE_FALLBACK_DDL)
        print(f"[Hermes DB] Local SQLite WAL replica auto-initialized at {db_path}.")
    except Exception as e:
        print(f"[Hermes DB WARNING] SQLite fallback init warning: {e}", file=sys.stderr)

    return pg_ok
