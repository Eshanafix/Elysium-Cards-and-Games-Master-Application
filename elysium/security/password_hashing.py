"""
Password hashing (LLD 6.4: salted + hashed with a modern algorithm, never
stored or displayed in plaintext). Argon2id via argon2-cffi, per
docs/IMPLEMENTATION_PLAN.md section 10 item 7.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plaintext_password: str) -> str:
    return _hasher.hash(plaintext_password)


def verify_password(plaintext_password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, plaintext_password)
        return True
    except VerifyMismatchError:
        return False
