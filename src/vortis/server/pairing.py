"""Pair a phone / tablet / TV browser with the server by scanning a QR code.

Flow (idea from FatihMakes/Mark-LVII ``dashboard/server.py``; independent
implementation, see NOTICE):

1. On the PC, the HUD calls ``POST /v1/pairing/start`` (loopback or master
   API key only) and shows the returned ``pair_url`` as a QR code.
2. The phone opens ``/pair#code=...`` (a fragment, so the code never reaches
   access logs), which posts the code to ``POST /pair/claim``.
3. The server answers with a long random device token. Only its SHA-256 is
   stored. The phone keeps the token and sends it as ``Bearer`` like an API key.

Codes are single use, expire after five minutes, and every code is voided
after too many wrong guesses. Devices are listed and revoked from the HUD.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from vortis.core.paths import get_config_dir

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 300
MAX_FAILED_CLAIMS = 10
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairingStore:
    """Paired devices on disk plus short-lived pairing codes in memory."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or (get_config_dir() / "paired_devices.json")
        self._lock = threading.Lock()
        self._codes: Dict[str, float] = {}
        self._failed = 0
        self._devices: Optional[List[Dict[str, Any]]] = None


    def _load(self) -> List[Dict[str, Any]]:
        if self._devices is None:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._devices = [d for d in data.get("devices", []) if "hash" in d]
            except FileNotFoundError:
                self._devices = []
            except (OSError, ValueError):
                logger.warning("Unreadable %s; starting with no devices", self._path)
                self._devices = []
        return self._devices

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"devices": self._devices or []}, indent=2))
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self._path)


    def new_code(self) -> Dict[str, Any]:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        expires = time.time() + CODE_TTL_SECONDS
        with self._lock:
            self._prune_codes()
            self._codes[code] = expires
        return {"code": code, "expires_at": expires}

    def _prune_codes(self) -> None:
        now = time.time()
        for code, exp in list(self._codes.items()):
            if exp < now:
                self._codes.pop(code, None)

    def claim(self, code: str, name: str) -> Optional[Dict[str, Any]]:
        code = (code or "").strip().upper().replace("-", "")
        with self._lock:
            self._prune_codes()
            if code not in self._codes:
                self._failed += 1
                if self._failed >= MAX_FAILED_CLAIMS:
                    logger.warning("Too many bad pairing codes; voiding all codes")
                    self._codes.clear()
                    self._failed = 0
                return None
            self._codes.pop(code)
            self._failed = 0
            token = f"vt_dev_{secrets.token_urlsafe(32)}"
            device = {
                "id": uuid.uuid4().hex[:12],
                "name": (name or "device").strip()[:60] or "device",
                "hash": _hash(token),
                "created_at": time.time(),
                "last_seen": None,
            }
            self._load().append(device)
            self._save()
        return {"token": token, "device": _public(device)}


    def verify(self, token: str) -> bool:
        if not token or not token.startswith("vt_dev_"):
            return False
        digest = _hash(token)
        with self._lock:
            for device in self._load():
                if secrets.compare_digest(device["hash"], digest):
                    device["last_seen"] = time.time()
                    return True
        return False

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [_public(d) for d in self._load()]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            devices = self._load()
            kept = [d for d in devices if d["id"] != device_id]
            if len(kept) == len(devices):
                return False
            self._devices = kept
            self._save()
            return True


def _public(device: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in device.items() if k != "hash"}


_STORE: Optional[PairingStore] = None
_STORE_LOCK = threading.Lock()


def get_pairing_store() -> PairingStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = PairingStore()
        return _STORE


def set_pairing_store(store: Optional[PairingStore]) -> None:
    """Swap the store (tests)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store


def verify_device_token(token: str) -> bool:
    try:
        return get_pairing_store().verify(token)
    except Exception:
        logger.debug("device token check failed", exc_info=True)
        return False


def lan_address() -> str:
    """Best guess at this machine's LAN IP (no packet is actually sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


router = APIRouter()


class PairStart(BaseModel):
    host: Optional[str] = Field(default=None, max_length=255)


class PairClaim(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(default="phone", max_length=60)


@router.post("/v1/pairing/start")
async def pairing_start(request: Request, body: Optional[PairStart] = None):
    auth_kind = getattr(request.state, "auth_kind", "")
    if auth_kind == "device" or (auth_kind != "master" and not _is_loopback(request)):
        raise HTTPException(403, "Pairing can only be started on the main computer")
    issued = get_pairing_store().new_code()
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    host = (body.host if body and body.host else None) or lan_address()
    origin = f"{request.url.scheme}://{host}:{port}"
    return {
        **issued,
        "origin": origin,
        "pair_url": f"{origin}/pair#code={issued['code']}",
        "lan_reachable": not _bound_to_loopback(request),
    }


def _bound_to_loopback(request: Request) -> bool:
    server = request.scope.get("server") or ("", 0)
    try:
        return ipaddress.ip_address(server[0]).is_loopback
    except ValueError:
        return False


@router.post("/pair/claim")
async def pairing_claim(body: PairClaim):
    result = get_pairing_store().claim(body.code, body.name)
    if result is None:
        raise HTTPException(400, "Invalid or expired pairing code")
    return result


@router.get("/v1/pairing/devices")
async def pairing_devices():
    return {"devices": get_pairing_store().list()}


@router.delete("/v1/pairing/devices/{device_id}")
async def pairing_revoke(device_id: str, request: Request):
    if getattr(request.state, "auth_kind", "") == "device":
        raise HTTPException(403, "Only the main computer can revoke devices")
    if not get_pairing_store().revoke(device_id):
        raise HTTPException(404, "Unknown device")
    return {"revoked": device_id}


__all__ = [
    "PairingStore",
    "get_pairing_store",
    "lan_address",
    "router",
    "set_pairing_store",
    "verify_device_token",
]
