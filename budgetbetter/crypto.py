"""Encryption of Item access tokens at rest. See ADR-0005.

The key lives in .env as APP_ENCRYPTION_KEY; ciphertext lives in the database.
"""

import sys

from cryptography.fernet import Fernet, InvalidToken


def generate_key() -> str:
    """A fresh Fernet key, for pasting into .env."""
    return Fernet.generate_key().decode()


class TokenCipher:
    """Encrypts and decrypts a single Item's access token."""

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError(
                "APP_ENCRYPTION_KEY is not set. Generate one with "
                "`python -m budgetbetter.crypto keygen` and put it in .env."
            )
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "APP_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
                "`python -m budgetbetter.crypto keygen`."
            ) from exc

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Could not decrypt the stored access token. The APP_ENCRYPTION_KEY "
                "in .env does not match the one used to store it — re-link the Item."
            ) from exc


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "keygen":
        print(generate_key())
    else:
        print("usage: python -m budgetbetter.crypto keygen", file=sys.stderr)
        sys.exit(1)
