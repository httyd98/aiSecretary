-- SegretarioLLM — Schema iniziale database
-- Eseguire con: psql $DATABASE_URL -f migrations/001_initial.sql

CREATE TABLE IF NOT EXISTS clients (
    id          SERIAL PRIMARY KEY,
    wa_id       VARCHAR(20) UNIQUE NOT NULL,
    name        VARCHAR(100),
    created_at  TIMESTAMP DEFAULT NOW(),
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id          SERIAL PRIMARY KEY,
    client_id   INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    started_at  TIMESTAMP DEFAULT NOW(),
    last_msg_at TIMESTAMP DEFAULT NOW(),
    status      VARCHAR(20) DEFAULT 'active',
    -- 'active' | 'resolved' | 'waiting_prof'
    summary     TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    wa_message_id   VARCHAR(100) UNIQUE,
    role            VARCHAR(20) NOT NULL,
    -- 'client' | 'bot' | 'professional'
    content         TEXT NOT NULL,
    timestamp       TIMESTAMP DEFAULT NOW(),
    is_processed    BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS directives (
    id          SERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP
    -- NULL = valida per sempre
);

-- Indici per query frequenti
CREATE INDEX IF NOT EXISTS idx_messages_wa_id ON messages(wa_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_client_status ON conversations(client_id, status);
CREATE INDEX IF NOT EXISTS idx_clients_wa_id ON clients(wa_id);
