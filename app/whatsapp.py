"""
Invio messaggi WhatsApp tramite Meta Graph API.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from app.config import settings
from app import database as db

GRAPH_API_VERSION = "v18.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }


async def send_whatsapp_message(to: str, text: str) -> bool:
    """Invia un messaggio di testo semplice tramite l'unico numero API."""
    url = f"{GRAPH_BASE_URL}/{settings.phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload, headers=_auth_headers())

    if response.status_code == 200:
        return True

    print(f"[WhatsApp] Errore invio a {to}: {response.status_code} — {response.text}")
    return False


async def send_to_professional(text: str) -> bool:
    """Shortcut per mandare un messaggio al professionista."""
    return await send_whatsapp_message(to=settings.prof_wa_id, text=text)


async def send_formatted_summary(to: str, messages_list: list[dict]) -> bool:
    """
    Manda un riassunto formattato con la sintassi WhatsApp.
    `messages_list` è lista di dict con chiavi: client_name, last_message, timestamp.
    """
    lines = ["*📋 Riassunto messaggi di oggi*\n"]
    for msg in messages_list:
        ts = msg.get("timestamp", "")
        if isinstance(ts, datetime):
            ts = ts.strftime("%H:%M")
        lines.append(f"👤 *{msg['client_name']}*")
        lines.append(f'_{msg["last_message"]}_')
        lines.append(f"🕐 {ts}\n")

    return await send_whatsapp_message(to, "\n".join(lines))


async def send_message_with_buttons(
    to: str, body: str, buttons: list[dict]
) -> bool:
    """
    Invia un messaggio con pulsanti interattivi (max 3).
    `buttons` è lista di dict con chiavi: id, title.
    """
    url = f"{GRAPH_BASE_URL}/{settings.phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload, headers=_auth_headers())

    return response.status_code == 200


async def send_safe_message(to: str, text: str, conv_id: int) -> bool:
    """
    Invia un messaggio rispettando la finestra 24h di WhatsApp.
    Se la finestra è scaduta, manda un template pre-approvato invece del testo libero.
    """
    last_ts = await db.get_last_client_message_time(conv_id)

    if last_ts is None:
        print(f"[WhatsApp] Nessun messaggio precedente per conv {conv_id}, invio bloccato")
        return False

    window_open = (datetime.now() - last_ts) < timedelta(hours=24)

    if window_open:
        return await send_whatsapp_message(to, text)

    # Finestra scaduta: usa template pre-approvato
    return await _send_template_message(to, template_name="ricontatto_base")


async def _send_template_message(to: str, template_name: str) -> bool:
    """
    Invia un template message pre-approvato da Meta.
    Richiede che il template sia stato creato e approvato nella Meta dashboard.
    """
    url = f"{GRAPH_BASE_URL}/{settings.phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "it"},
        },
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload, headers=_auth_headers())

    if response.status_code != 200:
        print(f"[WhatsApp] Errore template {template_name}: {response.text}")
    return response.status_code == 200
