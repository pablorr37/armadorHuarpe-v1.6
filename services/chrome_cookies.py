# services/chrome_cookies.py
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

# Necesita: pip install cryptography
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import logging
_log = logging.getLogger(__name__)


# ----- DPAPI (Windows) -----
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

PCRYPTPROTECT_PROMPTSTRUCT = ctypes.c_void_p
CRYPTPROTECT_UI_FORBIDDEN = 0x01

_CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
_CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    PCRYPTPROTECT_PROMPTSTRUCT,
    wt.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
_CryptUnprotectData.restype = wt.BOOL

def _dpapi_decrypt(buf: bytes) -> bytes:
    if not buf:
        return b""
    in_blob = DATA_BLOB(
        len(buf),
        ctypes.cast(ctypes.create_string_buffer(buf, len(buf)), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = DATA_BLOB()
    if not _CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise WindowsError("CryptUnprotectData failed")
    try:
        size = int(out_blob.cbData)
        data = ctypes.string_at(out_blob.pbData, size)
        return data
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

# ----- Utilidades Chrome -----
def _user_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or "") / "Google" / "Chrome" / "User Data"

def _local_state_path(user_data_dir: Path) -> Path:
    return user_data_dir / "Local State"

def _profile_dir(profile: Optional[str], user_data_dir: Optional[Path]) -> Path:
    udd = (Path(user_data_dir) if user_data_dir else _user_data_dir())
    prof = profile or "Default"
    return udd / prof

def _get_master_key(user_data_dir: Optional[Path] = None) -> bytes:
    udd = Path(user_data_dir) if user_data_dir else _user_data_dir()
    ls_path = _local_state_path(udd)
    if not ls_path.exists():
        return b""

    j = json.loads(ls_path.read_text(encoding="utf-8"))
    enc_key_b64 = j.get("os_crypt", {}).get("encrypted_key", "")
    if not enc_key_b64:
        return b""

    enc_key = base64.b64decode(enc_key_b64)
    if enc_key.startswith(b"DPAPI"):
        enc_key = enc_key[5:]
    key = _dpapi_decrypt(enc_key)
    return key

def _decrypt_cookie_value(encrypted_value: bytes, master_key: bytes) -> str:
    if not encrypted_value:
        return ""
    try:
        if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
            if not master_key:
                return _dpapi_decrypt(encrypted_value).decode("utf-8", errors="replace")
            nonce = encrypted_value[3:15]
            ct = encrypted_value[15:]
            aes = AESGCM(master_key)
            plain = aes.decrypt(nonce, ct, None)
            return plain.decode("utf-8", errors="replace")
        else:
            plain = _dpapi_decrypt(encrypted_value)
            return plain.decode("utf-8", errors="replace")
    except Exception:
        return ""

@dataclass
class ChromeCookie:
    host_key: str
    name: str
    path: str
    value: str
    expires_utc: int
    is_secure: int
    is_httponly: int
    samesite: int

def read_cookies_for_domains(
    domains: Iterable[str],
    profile: Optional[str] = None,
    user_data_dir: Optional[Path] = None
) -> List[ChromeCookie]:
    domains = list(domains or [])
    prof_dir = _profile_dir(profile, user_data_dir)

    # Chrome nuevo (>= 139) guarda cookies en Network/Cookies
    candidates = [
        prof_dir / "Cookies",
        prof_dir / "Network" / "Cookies",
        prof_dir / "Extension Cookies",
    ]
    db_path = None
    for c in candidates:
        if c.exists():
            db_path = c
            break

    if not db_path:
        _log.info(f"[SCRAPER] No encontré archivo de cookies en {prof_dir}")
        return []

    tmp_dir = Path(tempfile.gettempdir())
    tmp_path = tmp_dir / f"cookies_copy_{os.getpid()}.sqlite"
    try:
        shutil.copy2(db_path, tmp_path)
    except Exception:
        tmp_path = db_path

    master_key = _get_master_key(user_data_dir)

    where = " OR ".join("host_key LIKE ?" for _ in domains) if domains else "1=1"
    args = [f"%{d.strip('%')}%" for d in domains] if domains else []
    sql = f"""
        SELECT host_key, name, path, encrypted_value, expires_utc, is_secure, is_httponly, samesite, value
        FROM cookies
        WHERE {where};
    """

    cookies: List[ChromeCookie] = []
    con = None
    try:
        con = sqlite3.connect(str(tmp_path))
        cur = con.cursor()
        cur.execute(sql, args)
        for (host_key, name, path, enc_val, exp, is_sec, is_http, samesite, plain_val) in cur.fetchall():
            enc_bytes = bytes(enc_val) if isinstance(enc_val, (bytes, memoryview)) else b""
            if enc_bytes:
                value = _decrypt_cookie_value(enc_bytes, master_key).strip()
            else:
                value = (plain_val or "").strip()

            if not value:
                continue

            cookies.append(ChromeCookie(
                host_key=host_key,
                name=name,
                path=path or "/",
                value=value,
                expires_utc=int(exp or 0),
                is_secure=int(is_sec or 0),
                is_httponly=int(is_http or 0),
                samesite=int(samesite or 0),
            ))
    finally:
        try:
            if con:
                con.close()
        except Exception:
            pass
        if tmp_path != db_path:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    return cookies

def load_cookies_into_session(
    session,
    domains: Iterable[str],
    profile: Optional[str] = None,
    user_data_dir: Optional[Path] = None
) -> int:
    from requests.cookies import create_cookie

    cookies = read_cookies_for_domains(domains, profile=profile, user_data_dir=user_data_dir)
    count = 0
    for c in cookies:
        try:
            ck = create_cookie(
                name=c.name,
                value=c.value,
                domain=c.host_key,
                path=c.path or "/"
            )
            session.cookies.set_cookie(ck)
            count += 1
        except Exception:
            continue
    return count
