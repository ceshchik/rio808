#!/usr/bin/env python3
"""
OpenFlux CLI Management Tool
A complete tool for managing OpenFlux covert VPN tunnels and multi-user setups.
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openflux_cli.config import (
    BIN_PATH,
    SUPPORTED_TRANSPORTS,
    ensure_directories,
)
from openflux_cli.installer import install_openflux, verify_installation
from openflux_cli.runner import (
    build_openflux_command,
    generate_encryption_key,
    run_openflux_background,
    run_openflux_foreground,
)
from openflux_cli.users import UserManager


def cmd_install(args):
    """Handle installation of OpenFlux binary."""
    print("=" * 60)
    print("OpenFlux Binary Installer")
    print("=" * 60)
    try:
        dest = install_openflux(
            target_path=Path(args.target) if args.target else BIN_PATH,
            version=args.version,
            build_from_source=args.build,
        )
        print(f"\n[+] Ready! Binary available at: {dest}")
    except Exception as e:
        print(f"\n[-] Installation error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_start(args):
    """Handle starting a VPN tunnel with encryption."""
    if not BIN_PATH.exists():
        print(f"[!] OpenFlux binary not found at {BIN_PATH}.")
        print("[*] Running automatic installation...")
        cmd_install(argparse.Namespace(target=None, version=None, build=False))

    ensure_directories()

    # Determine encryption key
    key_file = None
    if args.no_encryption:
        print("[*] Running in UNENCRYPTED mode (--no-encryption).")
        key_file = None
    elif args.key:
        key_file = generate_encryption_key(name="temp_key")
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(args.key.strip())
        print(f"[*] Using provided secret key.")
    elif args.key_file:
        key_file = Path(args.key_file)
        if not key_file.exists():
            print(f"[-] Key file not found: {key_file}", file=sys.stderr)
            sys.exit(1)
        print(f"[*] Using key file: {key_file}")
    else:
        # Automatically generate AES-256 secret key
        key_file = generate_encryption_key(name=args.name or "session")
        print(f"[+] Auto-generated new AES-256 encryption key: {key_file}")

    cmd = build_openflux_command(
        role=args.role,
        mode=args.mode,
        transport=args.transport,
        url=args.url,
        key_file=key_file,
        share=not args.no_share,
        negotiate=not args.no_negotiate,
        bin_path=BIN_PATH,
        extra_args=args.extra,
    )

    if args.background:
        name = args.name or f"{args.transport}_node"
        run_openflux_background(name, cmd)
    else:
        run_openflux_foreground(cmd)


def cmd_user(args, um: UserManager):
    """Handle multi-user management subcommands."""
    sub = args.user_cmd

    if sub == "add":
        if not args.name or not args.url:
            print("[-] Missing required arguments: user name and URL (--url) are required.", file=sys.stderr)
            sys.exit(1)
        try:
            user = um.add_user(
                name=args.name,
                transport=args.transport,
                url=args.url,
                key=args.key,
                mode=args.mode,
                negotiate=not args.no_negotiate if not args.no_encryption else False,
                encrypted=not args.no_encryption,
            )
            print(f"[+] Successfully added user '{args.name}'.")
            print(f"    Transport: {user['transport']}")
            print(f"    URL:       {user['url']}")
            print(f"    Key file:  {user['key_file']}")
            print(f"    Mode:      {user['mode']}")
            print(f"\n[*] Start this user's connection with:")
            print(f"    openflux-cli user start {args.name}")
        except Exception as e:
            print(f"[-] Error adding user: {e}", file=sys.stderr)
            sys.exit(1)

    elif sub == "start":
        if not args.name:
            print("[-] Specify user name to start.", file=sys.stderr)
            sys.exit(1)
        if not BIN_PATH.exists():
            print(f"[!] OpenFlux binary not found. Installing first...")
            cmd_install(argparse.Namespace(target=None, version=None, build=False))
        um.start_user(args.name)

    elif sub == "stop":
        if not args.name:
            print("[-] Specify user name to stop.", file=sys.stderr)
            sys.exit(1)
        um.stop_user(args.name)

    elif sub == "restart":
        if not args.name:
            print("[-] Specify user name to restart.", file=sys.stderr)
            sys.exit(1)
        um.restart_user(args.name)

    elif sub == "list":
        users = um.list_users()
        if not users:
            print("No users configured yet. Add one with: openflux-cli user add <name> --url <url>")
            return

        print("\n" + "=" * 80)
        print(f"{'User':<15} {'Transport':<12} {'Status':<10} {'PID':<8} {'Mode':<6} {'URL'}")
        print("-" * 80)
        for u in users:
            status = "RUNNING" if u["running"] else "STOPPED"
            pid_str = str(u["pid"]) if u["pid"] else "-"
            print(f"{u['name']:<15} {u['transport']:<12} {status:<10} {pid_str:<8} {u.get('mode', 'l4'):<6} {u['url'][:35]}...")
        print("=" * 80 + "\n")

    elif sub == "share":
        if not args.name:
            print("[-] Specify user name.", file=sys.stderr)
            sys.exit(1)
        user = um.get_user(args.name)
        link = um.extract_share_link_from_logs(args.name) or user.get("last_share_link")
        print("=" * 60)
        print(f"Connection details for User: {args.name}")
        print("=" * 60)
        print(f"Transport: {user['transport']}")
        print(f"URL:       {user['url']}")
        print(f"Key file:  {user['key_file']}")
        if link:
            print(f"\n[+] Client Share Link (Import in OpenFlux mobile/desktop app):")
            print(f"\n    {link}\n")
        else:
            print(f"\n[*] Link not captured yet. Make sure the user is started (openflux-cli user start {args.name}).")
            log_file = LOGS_DIR / f"{args.name}.log"
            if log_file.exists():
                print(f"    Check logs at: {log_file}")

    elif sub == "delete":
        if not args.name:
            print("[-] Specify user name to delete.", file=sys.stderr)
            sys.exit(1)
        um.delete_user(args.name)

    elif sub == "run-service":
        # Used by systemd service unit to run in foreground
        if not args.name:
            sys.exit(1)
        user = um.get_user(args.name)
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
        run_openflux_foreground(cmd)


def cmd_systemd(args, um: UserManager):
    """Handle systemd unit generation and installation."""
    template = um.generate_systemd_template()

    if args.systemd_cmd == "show":
        print(template)
        return

    if args.systemd_cmd == "install":
        unit_path = Path("/etc/systemd/system/openflux-user@.service")
        print(f"[*] Installing systemd service template to {unit_path}...")
        try:
            if os.geteuid() != 0:
                print("[-] Root privileges required. Run with sudo: sudo openflux-cli systemd install")
                sys.exit(1)
            with open(unit_path, "w", encoding="utf-8") as f:
                f.write(template)
            os.system("systemctl daemon-reload")
            print("[+] Systemd template installed successfully!")
            print("[*] You can now manage users with systemctl, e.g.:")
            print("    sudo systemctl enable --now openflux-user@alice")
            print("    sudo systemctl status openflux-user@alice")
            print("    sudo journalctl -u openflux-user@alice -f")
        except Exception as e:
            print(f"[-] Failed to install systemd template: {e}", file=sys.stderr)
            sys.exit(1)


def cmd_status(um: UserManager):
    """Show global OpenFlux status."""
    print("=" * 60)
    print("OpenFlux System Status")
    print("=" * 60)
    print(f"Binary path:    {BIN_PATH} ({'EXISTS' if BIN_PATH.exists() else 'NOT FOUND'})")
    if BIN_PATH.exists():
        verify_installation(BIN_PATH)

    users = um.list_users()
    running = sum(1 for u in users if u["running"])
    print(f"Configured users: {len(users)} (Running: {running})")
    print("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openflux-cli",
        description="OpenFlux CLI Management & Multi-user Server Manager",
    )

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # install command
    p_install = subparsers.add_parser("install", help="Download and install OpenFlux binary")
    p_install.add_argument("--target", "-o", help="Target installation binary path")
    p_install.add_argument("--version", "-v", help="Release tag version to install")
    p_install.add_argument("--build", action="store_true", help="Compile from source with Go instead of prebuilt binary")

    # start command
    p_start = subparsers.add_parser("start", help="Start VPN connection with encryption")
    p_start.add_argument("--transport", "-t", default="telemost", choices=SUPPORTED_TRANSPORTS, help="Transport protocol (default: telemost)")
    p_start.add_argument("--url", "-u", required=True, help="Connection URL (e.g. Telemost conference link)")
    p_start.add_argument("--role", "-r", default="exit", choices=["exit", "client"], help="Role: exit (server) or client (default: exit)")
    p_start.add_argument("--mode", "-m", default="l4", choices=["l4", "l3"], help="Exit backend mode: l4 (gVisor userspace) or l3 (Linux raw) (default: l4)")
    p_start.add_argument("--key-file", "-k", help="Path to shared secret key file (auto-generated if omitted)")
    p_start.add_argument("--key", help="Inline shared secret key (min 16 chars)")
    p_start.add_argument("--no-encryption", action="store_true", help="Run without AES encryption (plain carrier traffic)")
    p_start.add_argument("--no-negotiate", action="store_true", help="Disable authenticated capability negotiation")
    p_start.add_argument("--no-share", action="store_true", help="Disable printing openflux:// link and QR code")
    p_start.add_argument("--background", "-d", action="store_true", help="Run in background daemon mode")
    p_start.add_argument("--name", help="Name identifier for background run or key")
    p_start.add_argument("extra", nargs="*", help="Additional flags passed directly to OpenFlux")

    # user command
    p_user = subparsers.add_parser("user", help="Manage multi-user VPN channels")
    user_subs = p_user.add_subparsers(dest="user_cmd")

    # user add
    p_u_add = user_subs.add_parser("add", help="Add a new user channel")
    p_u_add.add_argument("name", help="Unique user name identifier")
    p_u_add.add_argument("--url", "-u", required=True, help="User's dedicated conference/document URL")
    p_u_add.add_argument("--transport", "-t", default="telemost", choices=SUPPORTED_TRANSPORTS, help="Transport (default: telemost)")
    p_u_add.add_argument("--key", help="Custom secret key (auto-generated if omitted)")
    p_u_add.add_argument("--no-encryption", action="store_true", help="Configure user without encryption")
    p_u_add.add_argument("--mode", "-m", default="l4", choices=["l4", "l3"], help="Exit mode (default: l4)")
    p_u_add.add_argument("--no-negotiate", action="store_true", help="Disable capability negotiation")

    # user start / stop / restart / share / delete
    for action in ["start", "stop", "restart", "share", "delete", "run-service"]:
        p_act = user_subs.add_parser(action, help=f"{action.capitalize()} user instance")
        p_act.add_argument("name", help="User name identifier")

    # user list
    user_subs.add_parser("list", help="List all configured users and their status")

    # systemd command
    p_sys = subparsers.add_parser("systemd", help="Manage Linux systemd service template")
    p_sys.add_argument("systemd_cmd", choices=["show", "install"], help="Show template or install to /etc/systemd/system")

    # status command
    subparsers.add_parser("status", help="Show system status and OpenFlux information")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    um = UserManager()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "user":
        if not args.user_cmd:
            parser.parse_args(["user", "--help"])
        else:
            cmd_user(args, um)
    elif args.command == "systemd":
        cmd_systemd(args, um)
    elif args.command == "status":
        cmd_status(um)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
