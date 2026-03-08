"""
Endpoint webhook WhatsApp.
GET  /webhook — verifica iniziale Meta (una volta sola)
POST /webhook — ricezione messaggi
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app import database as db
from app.handlers import process_incoming_message

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    """
    Handshake iniziale con Meta.
    Meta chiama questo endpoint una volta sola per verificare che il server sia tuo.
    Risponde con hub_challenge se il token corrisponde.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token di verifica non valido")


@router.post("/webhook")
async def receive_message(request: Request):
    """
    Ricezione messaggi in arrivo da WhatsApp.
    Risponde sempre 200 a Meta — anche in caso di errori interni —
    per evitare che Meta ri-invii lo stesso messaggio all'infinito.
    """
    try:
        body = await request.json()
        change = body["entry"][0]["changes"][0]["value"]

        # Ignora notifiche di stato (delivered, read, ecc.)
        if "messages" not in change:
            return {"status": "ignored"}

        message = change["messages"][0]
        sender = message["from"]
        text = message.get("text", {}).get("body", "")
        message_id = message["id"]

        # Ignora messaggi non testuali per ora (immagini, audio, ecc.)
        if message.get("type") != "text" or not text:
            return {"status": "ignored_non_text"}

        # Deduplicazione
        if await db.is_duplicate(message_id):
            return {"status": "duplicate"}

        # Smista al handler appropriato (in background per rispondere subito a Meta)
        asyncio.create_task(
            process_incoming_message(sender, text, message_id)
        )

    except (KeyError, IndexError) as e:
        print(f"[Webhook] Payload malformato: {e}")
    except Exception as e:
        print(f"[Webhook] Errore inatteso: {e}")

    return {"status": "ok"}
