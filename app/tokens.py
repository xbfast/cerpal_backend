import os
import time

import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "dev-cambiar-en-produccion")
JWT_ALG = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "7"))


def create_access_token(*, sub: str) -> str:
    now = int(time.time())
    expire = now + JWT_EXPIRE_DAYS * 86400
    return jwt.encode(
        {"sub": sub, "iat": now, "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
