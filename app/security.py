import bcrypt

PASSWORD_POLICY_MSG = (
    "La contraseña debe tener al menos 8 caracteres, incluir un número y un símbolo "
    "(por ejemplo ! ? @ #)."
)


def validate_password_policy(plain: str) -> None:
    """
    Comprueba longitud (≥8), dígito y símbolo (registro y cambio de contraseña).
    Lanza ValueError con mensaje en español si falla.
    """
    v = str(plain)
    if len(v) < 8:
        raise ValueError(PASSWORD_POLICY_MSG)
    if not any(c.isdigit() for c in v):
        raise ValueError(PASSWORD_POLICY_MSG)
    if not any((not c.isalnum() and not c.isspace()) for c in v):
        raise ValueError(PASSWORD_POLICY_MSG)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
