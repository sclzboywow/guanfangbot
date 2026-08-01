from app.services.qq_signature import sign_validation, verify_request_signature


def test_official_validation_example() -> None:
    # From QQ Bot docs: event subscription validation sample
    secret = "DG5g3B4j9X2KOErG"
    plain_token = "Arq0D5A61EgUu4OxUvOp"
    event_ts = "1725442341"
    expected = (
        "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d0"
        "1bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"
    )
    assert sign_validation(secret, event_ts, plain_token) == expected


def test_request_signature_roundtrip() -> None:
    secret = "DG5g3B4j9X2KOErG"
    timestamp = "1725442341"
    body = b'{"op":0,"d":{},"t":"GATEWAY_EVENT_NAME"}'
    from app.services.qq_signature import private_key_from_secret

    signature = private_key_from_secret(secret).sign(timestamp.encode() + body).hex()
    assert verify_request_signature(secret, timestamp, body, signature)
    assert not verify_request_signature(secret, timestamp, body + b"x", signature)
