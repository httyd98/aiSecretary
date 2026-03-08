"""
Controller principale — smista i messaggi in arrivo al handler corretto
e orchestra il flusso: DB → AI → WhatsApp.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app import database as db
from app import ai
from app import whatsapp


async def process_incoming_message(
    sender: str,
    text: str,
    message_id: str,
) -> None:
    """
    Entry point per ogni messaggio ricevuto dal webhook.
    Distingue il professionista dai clienti in base al wa_id del mittente.
    """
    if sender == settings.prof_wa_id:
        await handle_professional_message(sender, text, message_id)
    else:
        await handle_client_message(sender, text, message_id)


# ──────────────────────────────────────────────
# Messaggi del professionista
# ──────────────────────────────────────────────

async def handle_professional_message(
    sender: str, text: str, message_id: str
) -> None:
    classification = await ai.classify_professional_message(text)
    msg_type = classification.get("type")

    if msg_type == "directive":
        saved = await ai.extract_and_save_directive(text)
        await whatsapp.send_to_professional(f"✅ Direttiva salvata:\n_{saved}_")

    elif msg_type == "manual_reply":
        target_name = classification.get("target_client")
        content = classification.get("content", text)

        client = await db.find_client_by_name(target_name) if target_name else None

        if client:
            conv = await db.get_active_conversation(client["id"])
            if conv:
                await whatsapp.send_whatsapp_message(client["wa_id"], content)
                await db.save_message(conv["id"], "professional", content)
                await whatsapp.send_to_professional("✅ Messaggio inviato")
            else:
                await whatsapp.send_to_professional(
                    f"⚠️ Nessuna conversazione attiva con {target_name}"
                )
        else:
            await whatsapp.send_to_professional(
                f"⚠️ Cliente '{target_name}' non trovato"
            )

    elif msg_type == "summary_request":
        summary = await ai.generate_daily_summary()
        await whatsapp.send_to_professional(summary)

    elif msg_type == "question":
        # Risponde alla domanda generica usando l'AI senza contesto cliente
        response = await ai._client.messages.create(
            model=settings.claude_model,
            max_tokens=400,
            system=(
                "Sei l'assistente tecnico del sistema SegretarioLLM. "
                "Rispondi alle domande del professionista sul funzionamento del sistema."
            ),
            messages=[{"role": "user", "content": text}],
        )
        await whatsapp.send_to_professional(response.content[0].text)

    else:
        await whatsapp.send_to_professional(
            "⚠️ Comando non riconosciuto. Scrivi una direttiva, "
            "una risposta manuale o chiedi un riassunto."
        )


# ──────────────────────────────────────────────
# Messaggi dei clienti
# ──────────────────────────────────────────────

async def handle_client_message(
    sender: str, text: str, message_id: str
) -> None:
    # Recupera o crea cliente
    client = await db.get_or_create_client(sender)

    # Recupera o crea conversazione attiva
    conv = await db.get_or_create_conversation(client["id"])

    # Salva il messaggio del cliente
    await db.save_message(conv["id"], "client", text, message_id)

    # Genera risposta AI
    ai_response = await ai.generate_client_response(
        conv_id=conv["id"],
        client_name=client["name"] or sender,
        new_message=text,
    )

    # Invia risposta al cliente
    await whatsapp.send_whatsapp_message(sender, ai_response)

    # Salva risposta del bot
    await db.save_message(conv["id"], "bot", ai_response)

    # Notifica intelligente al professionista (in background per non rallentare)
    asyncio.create_task(
        ai.maybe_notify_professional(dict(client), text, ai_response)
    )
