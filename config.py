import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    superadmin_ids: set[int]
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    default_user_interval: int
    default_chat_interval: int

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus
        password = quote_plus(self.db_password)
        user = quote_plus(self.db_user)
        return f"postgresql+asyncpg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN ni .env faylida sozlang.")
    ids = {int(x.strip()) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x.strip()}
    if not ids:
        raise RuntimeError("SUPERADMIN_IDS kamida bitta Telegram ID bo'lishi kerak.")
    return Settings(
        bot_token=token,
        superadmin_ids=ids,
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "krik"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", ""),
        default_user_interval=max(1, int(os.getenv("DEFAULT_USER_INTERVAL_MINUTES", "60"))),
        default_chat_interval=max(1, int(os.getenv("DEFAULT_CHAT_INTERVAL_MINUTES", "60"))),
    )
