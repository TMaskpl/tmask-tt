import io

import paramiko

KEY_CLASSES = (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey)


def load_private_key(key_str: str, password: str | None = None) -> paramiko.PKey:
    """Load a private key of unknown type (RSA/Ed25519/ECDSA/DSS) from its string
    content. `paramiko.PKey.from_private_key()` only works when called on a
    concrete subclass (its `__init__` accepts `file_obj`, the abstract base's
    does not) — this tries each supported type in turn, mirroring how
    `paramiko.SSHClient.connect(key_filename=...)` resolves key type internally.
    """
    last_exception = None
    for key_class in KEY_CLASSES:
        try:
            return key_class.from_private_key(io.StringIO(key_str), password=password)
        except paramiko.SSHException as e:
            last_exception = e
    raise last_exception
