import os
import secrets
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from openflux_cli.config import (
    BIN_PATH,
    DEFAULT_SECRET_BYTES,
    KEYS_DIR,
    LOGS_DIR,
    MIN_SECRET_CHARS,
    RUN_DIR,
    ensure_directories,
)


def generate_encryption_key(dest_path: Optional[Path] = None, name: str = "default") -> Path:
    """
    Generates a cryptographically strong shared secret for AES-256-GCM.
    OpenFlux requires secret length >= 16 characters (counted as UTF-16 code units).
    Returns the Path to the created secret file.
    """
    ensure_directories()
    target_file = dest_path or (KEYS_DIR / f"{name}.key")

    # Generate 32 bytes (256-bit) of high entropy alphanumeric characters
    alphabet = string.ascii_letters + string.digits
    secret_str = "".join(secrets.choice(alphabet) for _ in range(DEFAULT_SECRET_BYTES))

    with open(target_file, "w", encoding="utf-8") as f:
        f.write(secret_str)

    # Secure permissions (0600 - only current user can read/write)
    try:
        os.chmod(target_file, 0o600)
    except OSError:
        pass

    return target_file


def build_openflux_command(
    role: str = "exit",
    mode: str = "l4",
    transport: str = "telemost",
    url: str = "",
    key_file: Optional[Path] = None,
    share: bool = True,
    negotiate: bool = True,
    bin_path: Optional[Path] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """
    Constructs the exact OpenFlux command with encryption and modern CLI flags.
    """
    executable = str(bin_path or BIN_PATH)

    cmd = [
        executable,
        f"--role={role}",
        f"--mode={mode}",
        "--transport", transport,
        "--url", url,
    ]

    # Add encryption key
    if key_file:
        if not Path(key_file).exists():
            raise FileNotFoundError(f"Encryption key file not found: {key_file}")
        cmd.extend(["--encryption-key-file", str(key_file)])

    # Enable authenticated negotiation if encryption is on
    if negotiate and key_file:
        cmd.append("--negotiate")

    # Exit node sharing: generates and prints QR code + openflux:// link
    if share and role == "exit":
        cmd.append("--share")

    if extra_args:
        cmd.extend(extra_args)

    return cmd


def run_openflux_foreground(cmd: List[str]):
    """
    Executes OpenFlux in the foreground, streaming stdout/stderr directly.
    Catches SIGINT cleanly.
    """
    print(f"[*] Starting OpenFlux...")
    print(f"[*] Command: {' '.join(cmd)}\n" + "-" * 60)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
        )
        proc.wait()
    except KeyboardInterrupt:
        print("\n[*] Stopping OpenFlux gracefully...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("[*] OpenFlux stopped.")


def run_openflux_background(
    name: str,
    cmd: List[str],
    log_file: Optional[Path] = None,
    pid_file: Optional[Path] = None,
) -> subprocess.Popen:
    """
    Launches OpenFlux as a background daemon process.
    Stores PID and redirects output to log file.
    """
    ensure_directories()
    out_log = log_file or (LOGS_DIR / f"{name}.log")
    out_pid = pid_file or (RUN_DIR / f"{name}.pid")

    log_handle = open(out_log, "a", encoding="utf-8")
    log_handle.write(f"\n--- OpenFlux session started at {time.ctime()} ---\n")
    log_handle.write(f"Command: {' '.join(cmd)}\n")
    log_handle.flush()

    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # Detach process group
    )

    with open(out_pid, "w") as f:
        f.write(str(proc.pid))

    print(f"[+] Started background instance '{name}' (PID: {proc.pid})")
    print(f"[+] Logs streaming to: {out_log}")
    return proc
