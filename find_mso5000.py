#!/usr/bin/env python3
"""
Simple MSO5000 Network Discovery

This script will automatically find your Rigol MSO5000 oscilloscope on the network.
The MSO5000 uses raw TCP sockets on port 5555 (not VISA).
"""

import sys
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_local_network():
    """Get the local network range"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return ".".join(local_ip.split(".")[:-1])
    except Exception:
        return "192.168.1"


def ping_ip(ip):
    """Ping a single IP address"""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0
    except Exception:
        return False


def test_mso5000_connection(ip, port=5555):
    """Test if IP has an MSO5000 oscilloscope via raw TCP SCPI"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((ip, port))
        sock.sendall(b"*IDN?\n")
        response = sock.recv(4096).decode("utf-8", errors="ignore").strip()
        sock.close()

        if "RIGOL" in response.upper() and "MSO5" in response.upper():
            return response
        return False
    except Exception:
        return False


def find_mso5000():
    """Find MSO5000 on the network"""
    print("Searching for Rigol MSO5000 on the network...")
    print("This may take a minute...")

    network_base = get_local_network()
    print(f"Scanning network: {network_base}.x")

    # First, find responsive hosts
    print("\nStep 1: Finding responsive hosts...")
    responsive_ips = []

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {}
        for i in range(1, 255):
            ip = f"{network_base}.{i}"
            futures[executor.submit(ping_ip, ip)] = ip

        for future in as_completed(futures):
            ip = futures[future]
            if future.result():
                responsive_ips.append(ip)
                print(f"  Found: {ip}")

    if not responsive_ips:
        print("No responsive hosts found. Check your network connection.")
        return None

    print(f"\nFound {len(responsive_ips)} responsive hosts")

    # Second, test each for MSO5000
    print("\nStep 2: Testing for MSO5000 devices...")

    for ip in responsive_ips:
        print(f"  Testing {ip}...", end=" ")
        device_id = test_mso5000_connection(ip)
        if device_id:
            print(f"FOUND MSO5000!")
            print(f"\nDevice Information:")
            print(f"  IP Address: {ip}")
            print(f"  Device ID: {device_id}")
            return ip, device_id
        else:
            print("no")

    print("\nNo MSO5000 found on the network.")
    return None


def test_ip(ip, port=5555):
    """Test a single IP for MSO5000 connectivity. Returns device ID string or None."""
    result = test_mso5000_connection(ip, port)
    if result:
        return result
    return None


def main():
    """Main function"""
    print("Rigol MSO5000 Network Discovery")
    print("=" * 40)

    result = find_mso5000()

    if result:
        ip, device_id = result
        print(f"\nSUCCESS! Your MSO5000 is at: {ip}")
        print(f"\nTo use it in your code:")
        print(f"  from pymso5000.mso5000 import MSO5000")
        print(f"  mso = MSO5000(address='{ip}')")
        print(f"  mso.connect()")
    else:
        print(f"\nMSO5000 not found.")
        print(f"\nTroubleshooting:")
        print(f"1. Make sure your MSO5000 is connected to the network")
        print(f"2. Check that LAN is enabled on the oscilloscope")
        print(f"3. Verify the device has a valid IP address")


if __name__ == "__main__":
    main()
