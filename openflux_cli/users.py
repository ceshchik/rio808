import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openflux_cli.config import (
    BIN_PATH,
    KEYS_DIR,
    LOGS_DIR,
    RUN_DIR,
    USERS_FILE,
    ensure_directories,
)
from openflux_cli.runner import (
    build_openflux_command,
    generate_encryption_key,
    run_openflux_background,
)


class UserManager:
    def __init__(self, users_file: Optional[Path] = None):
        ensure_directories()
        self.users_file = users_file or USERS_FILE
        self._load_users()

    def _load_users(self):
        if self.users_file.exists():
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    self.users: Dict[str, dict] = json.load(f)
            except Exception:
                self.users = {}
        else:
            self.users = {}

    def _save_users(self):
        with open(self.users_file, "w", encoding="utf-8") as f:
            json.dump(self.users, f, indent=2, ensure_ascii=False)

    def add_user(
        self,
        name: str,
        transport: str = "telemost",
        url: str = "",
        key: Optional[str] = None,
        mode: str = "l4",
        negotiate: bool = True,
        encrypted: bool = False,
    ) -> dict:
        """Create and store a new user profile with isolated keys."""
        if name in self.users:
            raise ValueError(f"User '{name}' already exists.")

        key_path = None
        if encrypted:
            key_path = KEYS_DIR / f"{name}.key"
            if key:
                with open(key_path, "w", encoding="utf-8") as f:
                    f.write(key.strip())
                os.chmod(key_path, 0o600)
            else:
                generate_encryption_key(key_path, name=name)

        user_data = {
            "name": name,
            "transport": transport,
            "url": url,
            "mode": mode,
            "key_file": str(key_path) if key_path else None,
            "negotiate": negotiate if encrypted else False,
            "created_at": datetime.now().isoformat(),
            "last_share_link": "",
        }

        self.users[name] = user_data
        self._save_users()
        return user_data

    def get_user(self, name: str) -> dict:
        if name not in self.users:
            raise KeyError(f"User '{name}' not found.")
        return self.users[name]

    def is_user_running(self, name: str) -> Tuple[bool, int]:
        pid_file = RUN_DIR / f"{name}.pid"
        if not pid_file.exists():
            return False, 0

        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            return False, 0

        # Check if PID exists and is running
        try:
            os.kill(pid, 0)
            return True, pid
        except OSError:
            # Stale PID file
            try:
                pid_file.unlink()
            except OSError:
                pass
            return False, 0

    def start_user(
        self,
        name: str,
        wait_for_link: bool = True,
        timeout: float = 6.0,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Start the OpenFlux exit node instance for the specified user and wait for share link."""
        user = self.get_user(name)
        running, pid = self.is_user_running(name)
        if running:
            print(f"[!] User '{name}' is already running with PID {pid}.")
            link, qr = self.extract_share_info_from_logs(name)
            return True, link, qr

        key_path = Path(user["key_file"]) if user.get("key_file") else None
        cmd = build_openflux_command(
            role="exit",
            mode=user.get("mode", "l4"),
            transport=user.get("transport", "telemost"),
            url=user.get("url", ""),
            key_file=key_path,
            share=True,
            negotiate=user.get("negotiate", True) if key_path else False,
            bin_path=BIN_PATH,
        )

        proc = run_openflux_background(name, cmd)

        link = None
        qr_code = None

        if wait_for_link:
            start_time = time.time()
            while time.time() - start_time < timeout:
                time.sleep(0.3)
                if proc.poll() is not None:
                    print(f"[-] Процесс OpenFlux для '{name}' завершился (код {proc.returncode}).")
                    log_file = LOGS_DIR / f"{name}.log"
                    if log_file.exists():
                        try:
                            lines = log_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                            print(f"[-] Последние строки лога:\n" + "\n".join(lines[-6:]))
                        except Exception:
                            pass
                    return False, None, None

                link, qr_code = self.extract_share_info_from_logs(name)
                if link:
                    break

        return True, link, qr_code

    def stop_user(self, name: str) -> bool:
        """Stop the OpenFlux exit node instance for the specified user."""
        running, pid = self.is_user_running(name)
        if not running:
            print(f"[!] User '{name}' is not currently running.")
            return False

        print(f"[*] Stopping instance for user '{name}' (PID: {pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.2)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

        pid_file = RUN_DIR / f"{name}.pid"
        if pid_file.exists():
            pid_file.unlink()

        print(f"[+] User '{name}' stopped.")
        return True

    def restart_user(self, name: str):
        self.stop_user(name)
        time.sleep(1)
        self.start_user(name)

    def delete_user(self, name: str, keep_logs: bool = False):
        """Stop user instance and remove profile and key files."""
        if name not in self.users:
            raise KeyError(f"User '{name}' not found.")

        running, _ = self.is_user_running(name)
        if running:
            self.stop_user(name)

        user = self.users.pop(name)
        self._save_users()

        if user.get("key_file"):
            key_file = Path(user["key_file"])
            if key_file.exists():
                try:
                    key_file.unlink()
                except OSError:
                    pass

        if not keep_logs:
            log_file = LOGS_DIR / f"{name}.log"
            if log_file.exists():
                try:
                    log_file.unlink()
                except OSError:
                    pass

        print(f"[+] User '{name}' successfully deleted.")

    def list_users(self) -> List[dict]:
        """List all users with their active runtime status."""
        result = []
        for name, data in self.users.items():
            running, pid = self.is_user_running(name)
            item = dict(data)
            item["running"] = running
            item["pid"] = pid
            result.append(item)
        return result

    def extract_share_info_from_logs(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        """Scans the user's log file for openflux://v1/ link and the terminal QR code."""
        log_file = LOGS_DIR / f"{name}.log"
        if not log_file.exists():
            return None, None

        link = None
        qr_lines = []
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for line in lines:
                if "openflux://v1/" in line:
                    start_idx = line.find("openflux://v1/")
                    link = line[start_idx:].strip().split()[0]

            capturing = False
            for line in lines:
                stripped = line.rstrip("\r\n")
                if any(c in stripped for c in ["▀", "▄", "█"]):
                    capturing = True
                    qr_lines.append(stripped)
                elif capturing:
                    break

            qr_code = "\n".join(qr_lines) if qr_lines else None

            if link and link != self.users[name].get("last_share_link"):
                self.users[name]["last_share_link"] = link
                self._save_users()

            return link, qr_code
        except Exception:
            return None, None

    def extract_share_link_from_logs(self, name: str) -> Optional[str]:
        """Scans the user's log file for openflux://v1/ links and saves it."""
        link, _ = self.extract_share_info_from_logs(name)
        return link

    def generate_systemd_template(self) -> str:
        """
        Generates systemd service template content: openflux-user@.service
        """
        python_exe = sys.executable
        cli_script = Path(__file__).parent / "main.py"
        return f"""[Unit]
Description=OpenFlux Exit Node for User %I
After=network.target

[Service]
Type=simple
User={os.getlogin() if hasattr(os, 'getlogin') else 'root'}
ExecStart={python_exe} {cli_script} user run-service %I
Restart=always
RestartSec=3
KillMode=process
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""


# Type alias for clarity
Tuple_Status = tuple
