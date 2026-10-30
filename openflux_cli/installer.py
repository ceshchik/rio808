import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import json
from pathlib import Path
from typing import Optional, Tuple

from openflux_cli.config import (
    BIN_DIR,
    BIN_PATH,
    GITHUB_API_LATEST,
    ensure_directories,
)


def get_platform_target() -> Tuple[str, str]:
    """
    Detect OS and Architecture, mapping them to OpenFlux release asset naming.
    Returns: (os_name, arch_name), e.g. ("darwin", "arm64") or ("linux", "amd64").
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        os_name = "darwin"
    elif system == "linux":
        os_name = "linux"
    elif system == "windows":
        os_name = "windows"
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")

    if machine in ["x86_64", "amd64"]:
        arch_name = "amd64"
    elif machine in ["arm64", "aarch64"]:
        arch_name = "arm64"
    elif machine.startswith("armv7") or machine == "arm":
        arch_name = "arm"
    else:
        raise RuntimeError(f"Unsupported machine architecture: {machine}")

    return os_name, arch_name


def get_expected_asset_name(os_name: str, arch_name: str) -> str:
    """Returns the expected asset filename, e.g. openflux-darwin-arm64."""
    ext = ".exe" if os_name == "windows" else ""
    return f"openflux-{os_name}-{arch_name}{ext}"


def fetch_latest_release_info() -> dict:
    """Fetch latest release metadata from GitHub API."""
    req = urllib.request.Request(
        GITHUB_API_LATEST,
        headers={"User-Agent": "openflux-cli-installer/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Failed to fetch release info: HTTP {resp.status}")
        return json.loads(resp.read().decode())


def download_with_progress(url: str, dest_path: Path):
    """Download a file with console progress indicator."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "openflux-cli-installer/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        total_size = resp.getheader("Content-Length")
        total_size = int(total_size) if total_size else 0

        downloaded = 0
        block_size = 65536
        temp_dest = dest_path.with_suffix(".tmp")

        print(f"[*] Downloading from: {url}")
        with open(temp_dest, "wb") as f:
            while True:
                chunk = resp.read(block_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    mb_cur = downloaded / (1024 * 1024)
                    mb_tot = total_size / (1024 * 1024)
                    sys.stdout.write(f"\r    [{percent:5.1f}%] {mb_cur:.1f} MB / {mb_tot:.1f} MB")
                else:
                    mb_cur = downloaded / (1024 * 1024)
                    sys.stdout.write(f"\r    {mb_cur:.1f} MB downloaded")
                sys.stdout.flush()

        print()  # newline after progress
        temp_dest.rename(dest_path)


def install_openflux(
    target_path: Optional[Path] = None,
    version: Optional[str] = None,
    build_from_source: bool = False
) -> Path:
    """
    Install the OpenFlux executable.
    Downloads the prebuilt binary from GitHub Releases or builds it from source if requested.
    """
    ensure_directories()
    dest = target_path or BIN_PATH

    if build_from_source:
        return build_openflux_from_source(dest)

    os_name, arch_name = get_platform_target()
    asset_name = get_expected_asset_name(os_name, arch_name)

    print(f"[*] Detecting system: {os_name} ({arch_name})")
    print(f"[*] Target asset: {asset_name}")

    try:
        print("[*] Checking GitHub for latest release...")
        release_info = fetch_latest_release_info()
        tag_name = release_info.get("tag_name", "unknown")
        print(f"[*] Found release: {tag_name}")

        download_url = None
        for asset in release_info.get("assets", []):
            if asset.get("name") == asset_name:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            raise RuntimeError(f"Asset '{asset_name}' not found in release {tag_name}")

    except Exception as e:
        print(f"[!] Could not query GitHub API ({e}). Falling back to release URL convention.")
        tag = version or "v0.17.1"
        download_url = f"https://github.com/p1neappleXpress/OpenFlux/releases/download/{tag}/{asset_name}"

    # Download binary
    download_with_progress(download_url, dest)

    # Ensure executable permissions on Unix
    if os_name != "windows":
        os.chmod(dest, 0o755)

    print(f"[+] OpenFlux successfully installed to: {dest}")

    # Verify installation
    verify_installation(dest)
    return dest


def build_openflux_from_source(dest_path: Path) -> Path:
    """Clone and compile OpenFlux using local Go compiler."""
    if not shutil.which("go"):
        raise RuntimeError("Go compiler ('go') not found in PATH. Install Go or download prebuilt binary.")
    if not shutil.which("git"):
        raise RuntimeError("Git ('git') not found in PATH.")

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "OpenFlux"
        print(f"[*] Cloning OpenFlux repository into temporary directory...")
        subprocess.run(["git", "clone", "--depth=1", "https://github.com/p1neappleXpress/OpenFlux.git", str(clone_dir)], check=True)

        print("[*] Building OpenFlux binary with Go...")
        subprocess.run(["go", "build", "-o", str(dest_path), "."], cwd=clone_dir, check=True)

    if platform.system().lower() != "windows":
        os.chmod(dest_path, 0o755)

    print(f"[+] Built and installed to {dest_path}")
    verify_installation(dest_path)
    return dest_path


def verify_installation(bin_path: Path) -> bool:
    """Runs openflux --help to verify binary works."""
    try:
        proc = subprocess.run([str(bin_path), "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        out = proc.stdout + proc.stderr
        if "openflux" in out.lower() or "written by p1neappleXpress" in out:
            print("[+] Verification passed: OpenFlux binary is executable and responsive.")
            return True
        else:
            print("[?] Binary ran but unexpected banner. Output:")
            print(out[:300])
            return True
    except Exception as e:
        print(f"[-] Verification failed: {e}")
        return False
