"""
Layer AI — integrazione Claude API (Anthropic).
Tre responsabilità separate:
  1. Classificatore (messaggi del professionista)
  2. Risponditore (messaggi dei clienti)
  3. Estrattore di direttive
  4. Notifica intelligente al professionista
  5. Riassunto giornaliero
"""
from __future__ import annotations

import json

import anthropic

from app.config import settings
from app import database as db
from app import whatsapp

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
MODEL = settings.claude_model


# ──────────────────────────────────────────────
# 1. Classificatore messaggi del professionista
# ──────────────────────────────────────────────

async def classify_professional_message(text: str) -> dict:
    """
    Analizza il testo del professionista e ritorna:
    {
      "type": "directive|manual_reply|summary_request|question",
      "target_client": "<nome o null>",
      "content": "<testo pulito>"
    }
    """
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=(
            "Sei un classificatore di messaggi. Analizza il messaggio del professionista "
            "e rispondi SOLO con un JSON valido, nessun testo extra prima o dopo.\n\n"
            "Categorie:\n"
            '- "directive": aggiunge/modifica una regola di comportamento del bot\n'
            '- "manual_reply": vuole rispondere manualmente a un cliente specifico\n'
            '- "summary_request": chiede un riassunto dei messaggi recenti\n'
            '- "question": fa una domanda generica sul sistema\n\n'
            "Formato risposta:\n"
            '{"type": "...", "target_client": "<nome o null>", "content": "<testo pulito>"}'
        ),
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text.strip()
    return json.loads(raw)


# ──────────────────────────────────────────────
# 2. Risponditore AI per i clienti
# ──────────────────────────────────────────────

async def generate_client_response(
    conv_id: int,
    client_name: str,
    new_message: str,
) -> str:
    """
    Genera una risposta al messaggio del cliente usando:
    - direttive attive dal DB
    - storia della conversazione
    """
    directives = await db.get_active_directives()
    history = await db.get_conversation_history(conv_id, limit=10)

    system_prompt = (
        "Sei un assistente virtuale professionale e cordiale. "
        f"Rispondi ai clienti a nome del professionista. "
        f"Il cliente si chiama {client_name}.\n\n"
        "## DIRETTIVE AGGIORNATE\n"
        f"{directives}\n\n"
        "## COMPORTAMENTO GENERALE\n"
        "- Sii sempre educato e professionale\n"
        "- Se non sai rispondere a qualcosa, di' che riferirai al professionista\n"
        "- Non inventare informazioni che non hai\n"
        "- Rispondi in italiano salvo diversa indicazione del cliente"
    )

    messages = history + [{"role": "user", "content": new_message}]

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


# ──────────────────────────────────────────────
# 3. Estrattore e normalizzatore di direttive
# ──────────────────────────────────────────────

async def extract_and_save_directive(raw_text: str) -> str:
    """
    Normalizza il messaggio grezzo del professionista in una direttiva chiara,
    la salva nel DB e ritorna il testo normalizzato.
    """
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=(
            "Converti il messaggio in una direttiva chiara e concisa per un assistente virtuale. "
            "Rispondi SOLO con un JSON valido:\n"
            '{"content": "<direttiva normalizzata>", "expires_at": "<ISO datetime o null>"}\n\n'
            "Esempi:\n"
            'Input: "questa settimana sono in ferie"\n'
            'Output: {"content": "Il professionista è in ferie questa settimana, non fissare appuntamenti", '
            '"expires_at": "2024-01-21T23:59:59"}\n\n'
            'Input: "il prezzo base è 80 euro"\n'
            'Output: {"content": "Il prezzo della consulenza base è 80€", "expires_at": null}'
        ),
        messages=[{"role": "user", "content": raw_text}],
    )

    directive = json.loads(response.content[0].text.strip())
    await db.save_directive(directive["content"], directive.get("expires_at"))
    return directive["content"]


# ──────────────────────────────────────────────
# 4. Notifica intelligente al professionista
# ──────────────────────────────────────────────

async def maybe_notify_professional(
    client: dict,
    client_msg: str,
    bot_reply: str,
) -> None:
    """
    Decide se lo scambio merita attenzione del professionista e invia notifica.
    Casi tipici: urgenza, reclami, richieste complesse, importi elevati.
    """
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=150,
        system=(
            "Rispondi SOLO con JSON valido.\n"
            "Decidi se questo scambio richiede attenzione del professionista.\n"
            "Casi che richiedono notifica: urgenza, reclami, richieste complesse, "
            "importi elevati, situazioni ambigue o non gestibili dal bot.\n"
            '{"notify": true/false, "reason": "<motivazione breve o null>"}'
        ),
        messages=[
            {
                "role": "user",
                "content": f"Messaggio cliente: {client_msg}\nRisposta bot: {bot_reply}",
            }
        ],
    )

    result = json.loads(response.content[0].text.strip())

    if result.get("notify"):
        client_label = client.get("name") or client.get("wa_id", "sconosciuto")
        await whatsapp.send_to_professional(
            f"⚠️ *Attenzione richiesta*\n"
            f"Cliente: {client_label}\n"
            f"Motivo: {result['reason']}\n\n"
            f"Messaggio: _{client_msg}_"
        )


# ──────────────────────────────────────────────
# 5. Riassunto giornaliero
# ──────────────────────────────────────────────

async def generate_daily_summary() -> str:
    """
    Genera un riassunto testuale dei messaggi ricevuti oggi.
    """
    today_msgs = await db.get_today_messages()

    if not today_msgs:
        return "📭 Nessun messaggio ricevuto oggi."

    # Prepara i dati per l'AI
    msg_lines = "\n".join(
        f"- {r['client_name'] or r['wa_id']}: \"{r['last_message']}\""
        for r in today_msgs
    )

    response = await _client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=(
            "Sei un assistente che prepara riassunti per un professionista. "
            "Crea un riassunto conciso e ben strutturato dei messaggi ricevuti oggi. "
            "Usa la formattazione WhatsApp (*grassetto* per nomi, _corsivo_ per citazioni). "
            "Evidenzia eventuali urgenze o richieste in sospeso."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Messaggi di oggi:\n{msg_lines}",
            }
        ],
    )
    return response.content[0].text
