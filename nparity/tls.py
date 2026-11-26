"""TLS verification against the OS trust store (macOS keychain) when truststore is installed.

Corporate TLS inspection puts its root CA in the keychain, not in certifi's bundle, so plain httpx
fails with CERTIFICATE_VERIFY_FAILED. Verification is never disabled.
"""

from __future__ import annotations


def tls_verify() -> object:
    try:
        import ssl

        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
