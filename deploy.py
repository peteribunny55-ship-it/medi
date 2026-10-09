#!/usr/bin/env python3
"""
Medi Hospital Platform - Mobile & Network Deployment Script
Run this script to launch the Streamlit server accessible on desktop and mobile devices.
"""

import os
import socket
import subprocess
import sys


def get_local_ip() -> str:
    """Detect local IP address on Wi-Fi / Local Network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    print("=" * 60)
    print("🏥 MEDI HOSPITAL PLATFORM - LAUNCHING DEPLOYMENT")
    print("=" * 60)

    ip = get_local_ip()
    port = 8501

    print("\n📱 MOBILE ACCESS INSTRUCTIONS:")
    print(f"1. Connect your mobile phone/tablet to the same Wi-Fi network.")
    print(f"2. Open Safari / Chrome / Edge on your mobile device.")
    print(f"3. Navigate to:  http://{ip}:{port}")
    print(f"\n💻 DESKTOP LOCAL ACCESS:")
    print(f"   http://localhost:{port}")
    print("-" * 60)
    print("Press Ctrl+C in this terminal to stop the server.\n")

    venv_python = os.path.join(".venv", "Scripts", "python.exe")
    python_bin = venv_python if os.path.exists(venv_python) else sys.executable

    cmd = [
        python_bin, "-m", "streamlit", "run", "app/1_🏠_Home.py",
        "--server.address=0.0.0.0",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
