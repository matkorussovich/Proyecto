
CREATE TABLE historial_chats (
    id SERIAL PRIMARY KEY,
    ds_telefono VARCHAR(20) UNIQUE NOT NULL,
    s3_chat_history_key VARCHAR(1024) NOT NULL,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_telefono ON historial_chats (ds_telefono);