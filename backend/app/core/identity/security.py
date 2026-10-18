from pwdlib import PasswordHash

# Argon2 with pwdlib's recommended settings. Argon2 is deliberately slow and
# memory-hungry, so someone who steals the users table can't cheaply guess passwords.
_hasher = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    # The result includes a random salt, so two users with the same password
    # get different hashes.
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _hasher.verify(plain, hashed)
