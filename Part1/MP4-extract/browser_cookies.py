#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_BROWSERS = {
    "chrome": {
        "base_dir": Path("~/Library/Application Support/Google/Chrome").expanduser(),
        "keychain_service": "Chrome Safe Storage",
        "keychain_account": "Chrome",
    },
    "edge": {
        "base_dir": Path("~/Library/Application Support/Microsoft Edge").expanduser(),
        "keychain_service": "Microsoft Edge Safe Storage",
        "keychain_account": "Microsoft Edge",
    },
}


def _get_keychain_password(service: str, account: str | None) -> str:
    cmd = ["security", "find-generic-password", "-w", "-s", service]
    if account:
        cmd += ["-a", account]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout:
        return result.stdout.strip()
    if account:
        cmd = ["security", "find-generic-password", "-w", "-s", service]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip()
    raise RuntimeError("Failed to read keychain password.")


def _derive_key(password: str, length: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=length,
        salt=b"saltysalt",
        iterations=1003,
    )
    return kdf.derive(password.encode("utf-8"))


def _decrypt_value(encrypted_value: bytes, key_16: bytes, key_32: bytes) -> str | None:
    if not encrypted_value:
        return None

    if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:]
        if len(ciphertext) < 16:
            return None
        for key in (key_32, key_16):
            if not key:
                continue
            try:
                return AESGCM(key).decrypt(nonce, ciphertext, None).decode(
                    "utf-8", errors="replace"
                )
            except (InvalidTag, ValueError):
                continue
        return None

    iv = b" " * 16
    try:
        cipher = Cipher(algorithms.AES(key_16), modes.CBC(iv))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(encrypted_value) + decryptor.finalize()
    except ValueError:
        return None
    if not plaintext:
        return None
    pad_len = plaintext[-1]
    if 1 <= pad_len <= 16:
        plaintext = plaintext[:-pad_len]
    return plaintext.decode("utf-8", errors="replace")


def _domain_matches(host: str, domain: str) -> bool:
    host = host.lower()
    domain = domain.lstrip(".").lower()
    return host == domain or host.endswith("." + domain)


def _iter_cookies(db_path: Path) -> Iterable[tuple[str, str, str, bytes]]:
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            temp_file = Path(handle.name)
        shutil.copy2(db_path, temp_file)
        conn = sqlite3.connect(temp_file)
        cursor = conn.execute(
            "SELECT host_key, name, value, encrypted_value FROM cookies"
        )
        for host_key, name, value, encrypted_value in cursor.fetchall():
            yield host_key, name, value, encrypted_value
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink(missing_ok=True)


def _resolve_cookie_db(base_dir: Path, profile: str) -> Path:
    primary = base_dir / profile / "Cookies"
    if primary.exists():
        return primary
    network = base_dir / profile / "Network" / "Cookies"
    if network.exists():
        return network
    raise FileNotFoundError("Cookie database not found for profile.")


def build_cookie_header(url: str, browser: str, profile: str = "Default") -> str:
    if sys.platform != "darwin":
        raise RuntimeError("Auto cookie is only supported on macOS.")
    browser = browser.lower()
    if browser not in _BROWSERS:
        raise RuntimeError("Unsupported browser.")
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise RuntimeError("Invalid URL.")

    config = _BROWSERS[browser]
    cookie_db = _resolve_cookie_db(config["base_dir"], profile)
    password = _get_keychain_password(
        config["keychain_service"], config["keychain_account"]
    )
    key_16 = _derive_key(password, 16)
    key_32 = _derive_key(password, 32)

    cookies = []
    for host_key, name, value, encrypted_value in _iter_cookies(cookie_db):
        if isinstance(host_key, bytes):
            host_key = host_key.decode("utf-8", errors="replace")
        if not host_key or not _domain_matches(host, host_key):
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if value:
            cookie_value = value
        else:
            if isinstance(encrypted_value, memoryview):
                encrypted_value = encrypted_value.tobytes()
            cookie_value = _decrypt_value(encrypted_value, key_16, key_32)
        if cookie_value is None:
            continue
        cookies.append(f"{name}={cookie_value}")

    if not cookies:
        raise RuntimeError("No matching cookies found for host.")
    return "; ".join(cookies)
