from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str

    # WhatsApp / Meta
    whatsapp_token: str
    verify_token: str
    phone_number_id: str  # L'unico numero API (quello del bot)
    prof_wa_id: str  # Numero WhatsApp personale del professionista (es. "393331234567")

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"


settings = Settings()
