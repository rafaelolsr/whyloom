import hashlib


class TokenService:
    def fingerprint(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

