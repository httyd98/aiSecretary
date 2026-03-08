"""
Layer database — asyncpg + PostgreSQL.
Tutte le query sono centralizzate qui.
"""
from __future__ import annotations

import asyncpg
from asyncpg import Pool

from app.config import settings

_pool: Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("DB pool non inizializzato. Avvia l'app tramite lifespan.")
    return _pool


# ──────────────────────────────────────────────
# Deduplicazione messaggi
# ──────────────────────────────────────────────

async def is_duplicate(message_id: str) -> bool:
    """Ritorna True se il messaggio WhatsApp è già stato processato."""
    row = await get_pool().fetchrow(
        "SELECT id FROM messages WHERE wa_message_id = $1", message_id
    )
    return row is not None


# ──────────────────────────────────────────────
# Clienti
# ──────────────────────────────────────────────

async def get_or_create_client(wa_id: str, name: str | None = None) -> asyncpg.Record:
    pool = get_pool()
    client = await pool.fetchrow("SELECT * FROM clients WHERE wa_id = $1", wa_id)
    if client:
        # Aggiorna il nome se arriva per la prima volta
        if name and not client["name"]:
            client = await pool.fetchrow(
                "UPDATE clients SET name = $1 WHERE wa_id = $2 RETURNING *",
                name, wa_id,
            )
        return client
    return await pool.fetchrow(
        "INSERT INTO clients (wa_id, name) VALUES ($1, $2) RETURNING *",
        wa_id, name,
    )


async def find_client_by_name(name: str) -> asyncpg.Record | None:
    """Ricerca case-insensitive parziale sul nome del cliente."""
    return await get_pool().fetchrow(
        "SELECT * FROM clients WHERE LOWER(name) LIKE $1 LIMIT 1",
        f"%{name.lower()}%",
    )


# ──────────────────────────────────────────────
# Conversazioni
# ──────────────────────────────────────────────

async def get_or_create_conversation(client_id: int) -> asyncpg.Record:
    pool = get_pool()
    conv = await pool.fetchrow(
        """
        SELECT * FROM conversations
        WHERE client_id = $1 AND status = 'active'
        ORDER BY last_msg_at DESC LIMIT 1
        """,
        client_id,
    )
    if conv:
        return conv
    return await pool.fetchrow(
        "INSERT INTO conversations (client_id) VALUES ($1) RETURNING *",
        client_id,
    )


async def get_active_conversation(client_id: int) -> asyncpg.Record | None:
    return await get_pool().fetchrow(
        """
        SELECT * FROM conversations
        WHERE client_id = $1 AND status = 'active'
        ORDER BY last_msg_at DESC LIMIT 1
        """,
        client_id,
    )


async def update_conversation_timestamp(conv_id: int) -> None:
    await get_pool().execute(
        "UPDATE conversations SET last_msg_at = NOW() WHERE id = $1", conv_id
    )


# ──────────────────────────────────────────────
# Messaggi
# ──────────────────────────────────────────────

async def save_message(
    conv_id: int,
    role: str,
    content: str,
    wa_message_id: str | None = None,
) -> None:
    await get_pool().execute(
        """
        INSERT INTO messages (conversation_id, wa_message_id, role, content)
        VALUES ($1, $2, $3, $4)
        """,
        conv_id, wa_message_id, role, content,
    )
    await update_conversation_timestamp(conv_id)


async def get_conversation_history(
    conv_id: int, limit: int = 10
) -> list[dict]:
    """Ritorna gli ultimi `limit` messaggi in ordine cronologico (dal più vecchio)."""
    rows = await get_pool().fetch(
        """
        SELECT role, content FROM messages
        WHERE conversation_id = $1
        ORDER BY timestamp DESC
        LIMIT $2
        """,
        conv_id, limit,
    )
    return [
        {
            "role": "user" if r["role"] == "client" else "assistant",
            "content": r["content"],
        }
        for r in reversed(rows)
    ]


async def get_last_client_message_time(conv_id: int):
    """Ritorna il timestamp dell'ultimo messaggio del cliente nella conversazione."""
    return await get_pool().fetchval(
        """
        SELECT timestamp FROM messages
        WHERE conversation_id = $1 AND role = 'client'
        ORDER BY timestamp DESC LIMIT 1
        """,
        conv_id,
    )


async def get_today_messages() -> list[asyncpg.Record]:
    """Tutti i messaggi di oggi raggruppati per cliente — usato per il riassunto."""
    return await get_pool().fetch(
        """
        SELECT
            c.name AS client_name,
            c.wa_id,
            m.content AS last_message,
            m.role,
            m.timestamp
        FROM messages m
        JOIN conversations conv ON m.conversation_id = conv.id
        JOIN clients c ON conv.client_id = c.id
        WHERE m.timestamp >= CURRENT_DATE
          AND m.role = 'client'
        ORDER BY m.timestamp DESC
        """
    )


# ──────────────────────────────────────────────
# Direttive
# ──────────────────────────────────────────────

async def get_active_directives() -> str:
    """Ritorna le direttive attive come stringa da iniettare nel system prompt."""
    rows = await get_pool().fetch(
        """
        SELECT content FROM directives
        WHERE is_active = TRUE
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY created_at DESC
        """
    )
    if not rows:
        return "Nessuna direttiva specifica."
    return "\n".join(f"- {r['content']}" for r in rows)


async def save_directive(content: str, expires_at=None) -> None:
    await get_pool().execute(
        "INSERT INTO directives (content, expires_at) VALUES ($1, $2)",
        content, expires_at,
    )
