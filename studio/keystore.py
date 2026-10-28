"""API keys and other secrets: read from the environment, the macOS Keychain, or the local .env file.

Rules (studio policy):
* A secret is NEVER stored in the SQLite settings, in prompts, in logs, or in any file that git tracks.
* Lookup order: process environment (incl. .env loaded by run.sh) -> macOS Keychain -> .env file on disk.
* The dashboard only ever sees `mask(value)` (e.g. "sk-a...9f2c") or "set / not set".
* Keychain entries use service "ai-game-studio" and account = the env var name, so you can also manage them in
  Keychain Access.app or with `security find-generic-password -s ai-game-studio -a ANTHROPIC_API_KEY -w`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

KEYCHAIN_SERVICE = "ai-game-studio"
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

Runner = Callable[..., subprocess.CompletedProcess]


def mask(value: str | None) -> str:
    if not value:
        return ""
    v = str(value)
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}...{v[-4:]}"


class Keychain:
    """Thin wrapper around /usr/bin/security (macOS). `runner` is injectable so tests never touch a real keychain."""

    def __init__(self, runner: Runner | None = None, binary: str = "security", force: bool | None = None):
        self.runner = runner or subprocess.run
        self.binary = binary
        self._force = force

    @property
    def available(self) -> bool:
        if self._force is not None:
            return self._force
        return sys.platform == "darwin" and bool(shutil.which(self.binary))

    def get(self, name: str) -> str | None:
        if not self.available:
            return None
        try:
            p = self.runner([self.binary, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
                            capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return None
        return (p.stdout or "").strip() or None

    def set(self, name: str, value: str) -> None:
        if not self.available:
            raise ValueError("macOS Keychain is not available on this machine; save to .env instead")
        # -U updates an existing item. The value is passed as an argument to `security` (a local process on your
        # own Mac); it never reaches the database, logs, or git.
        p = self.runner([self.binary, "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", name,
                         "-l", f"AI Game Studio {name}", "-w", value], capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            raise ValueError(f"Keychain refused to save {name}: {(p.stderr or '').strip()[:200]}")

    def delete(self, name: str) -> bool:
        if not self.available:
            return False
        p = self.runner([self.binary, "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name],
                        capture_output=True, text=True, timeout=10)
        return p.returncode == 0


class SecretStore:
    def __init__(self, env_file: Path, keychain: Keychain | None = None):
        self.env_file = Path(env_file)
        self.keychain = keychain or Keychain()
        self._origin: dict[str, str] = {}    # where a key saved in this session went (env vars mirror it)

    # -------------------------------------------------------------- .env file
    def _read_env_file(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if not self.env_file.exists():
            return out
        for line in self.env_file.read_text(errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            if k:
                out[k] = v
        return out

    def _write_env_value(self, name: str, value: str) -> None:
        lines = self.env_file.read_text().splitlines() if self.env_file.exists() else []
        pat = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
        quoted = "'" + value.replace("'", "") + "'"
        new, done = [], False
        for line in lines:
            if pat.match(line):
                if not done:
                    new.append(f"{name}={quoted}")
                    done = True
                continue
            new.append(line)
        if not done:
            new.append(f"{name}={quoted}")
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text("\n".join(new) + "\n")
        try:
            os.chmod(self.env_file, 0o600)
        except OSError:
            pass

    # -------------------------------------------------------------- public API
    def get(self, name: str) -> str | None:
        v = os.environ.get(name)
        if v:
            return v
        v = self.keychain.get(name)
        if v:
            return v
        return self._read_env_file().get(name) or None

    def source(self, name: str) -> str:
        if name in self._origin and os.environ.get(name):
            return self._origin[name]
        if os.environ.get(name):
            return "env"
        if self.keychain.get(name):
            return "keychain"
        if self._read_env_file().get(name):
            return ".env"
        return ""

    def status(self, name: str) -> dict:
        v = self.get(name)
        return {"name": name, "set": bool(v), "masked": mask(v), "source": self.source(name) if v else ""}

    def set(self, name: str, value: str, backend: str = "keychain") -> dict:
        if not NAME_RE.match(name or ""):
            raise ValueError("secret name must look like ANTHROPIC_API_KEY")
        value = (value or "").strip()
        if not value or len(value) > 4096 or any(c in value for c in "\r\n"):
            raise ValueError("the key is empty, too long, or has line breaks")
        if backend == "keychain":
            self.keychain.set(name, value)
        elif backend == "env":
            self._write_env_value(name, value)
        else:
            raise ValueError("backend must be keychain or env")
        os.environ[name] = value      # usable right away by this process; never written anywhere else
        self._origin[name] = "keychain" if backend == "keychain" else ".env"
        return {"name": name, "set": True, "masked": mask(value), "source": self._origin[name]}

    def available_backends(self) -> list[str]:
        return (["keychain"] if self.keychain.available else []) + ["env"]
