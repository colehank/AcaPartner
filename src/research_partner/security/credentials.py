"""Shared credential-file validity for HTTP and durable grant revalidation."""
import hashlib
from pathlib import Path


def token_fingerprint(reference):
    # Preserve HTTP's literal path semantics: no expanduser/resolve/follow-symlink
    # convenience that could keep a durable grant alive after login is rejected.
    try:
        path = Path(reference)
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077: return None
        value = path.read_text().strip()
        if len(value) < 24: return None
        return hashlib.sha256(value.encode()).hexdigest()
    except (OSError, ValueError): return None
