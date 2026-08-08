from elysium.security.password_hashing import hash_password, verify_password


def test_hash_is_not_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_correct_password():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_incorrect_password():
    hashed = hash_password("hunter2")
    assert verify_password("wrong-password", hashed) is False


def test_same_password_hashes_differently_each_time():
    # Argon2 salts each hash, so two hashes of the same password must differ,
    # even though both verify correctly.
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True
