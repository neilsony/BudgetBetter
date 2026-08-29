import pytest

from budgetbetter.crypto import TokenCipher, generate_key


def test_a_token_survives_an_encrypt_decrypt_round_trip():
    cipher = TokenCipher(generate_key())
    assert cipher.decrypt(cipher.encrypt("access-sandbox-abc123")) == "access-sandbox-abc123"


def test_the_ciphertext_does_not_contain_the_token():
    cipher = TokenCipher(generate_key())
    assert "access-sandbox-abc123" not in cipher.encrypt("access-sandbox-abc123")


def test_the_same_token_encrypts_differently_each_time():
    cipher = TokenCipher(generate_key())
    assert cipher.encrypt("access-sandbox-abc123") != cipher.encrypt("access-sandbox-abc123")


def test_a_different_key_cannot_decrypt_the_token():
    written = TokenCipher(generate_key()).encrypt("access-sandbox-abc123")
    with pytest.raises(ValueError):
        TokenCipher(generate_key()).decrypt(written)


def test_a_missing_key_is_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="APP_ENCRYPTION_KEY"):
        TokenCipher("")
