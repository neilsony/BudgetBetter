"""Settings, read from a gitignored .env. See ADR-0005."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# How much history to ask Plaid for on the first Refresh of an Item.
INITIAL_BACKFILL_DAYS = 730


@dataclass(frozen=True)
class Settings:
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str
    encryption_key: str
    database_path: Path

    @property
    def is_sandbox(self) -> bool:
        return self.plaid_env.lower() != "production"

    def missing(self) -> list[str]:
        """Which required settings are still blank."""
        required = {
            "PLAID_CLIENT_ID": self.plaid_client_id,
            "PLAID_SECRET": self.plaid_secret,
            "APP_ENCRYPTION_KEY": self.encryption_key,
        }
        return [name for name, value in required.items() if not value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    database = os.getenv("BUDGETBETTER_DB", "budgetbetter.db")
    return Settings(
        plaid_client_id=os.getenv("PLAID_CLIENT_ID", "").strip(),
        plaid_secret=os.getenv("PLAID_SECRET", "").strip(),
        plaid_env=os.getenv("PLAID_ENV", "sandbox").strip(),
        encryption_key=os.getenv("APP_ENCRYPTION_KEY", "").strip(),
        database_path=(PROJECT_ROOT / database) if not os.path.isabs(database) else Path(database),
    )
