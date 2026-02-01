from __future__ import annotations

from cryptography.fernet import Fernet


class TokenCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        return self._fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
