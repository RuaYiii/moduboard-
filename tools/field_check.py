"""Offline preflight for the industrial workbench."""

import importlib
import socket
import sys
from importlib import metadata


REQUIRED = {
    "flask": "Flask",
    "flask_cors": "flask-cors",
    "asyncua": "asyncua",
    "pymodbus": "pymodbus",
    "serial": "pyserial",
    "cryptography": "cryptography",
}


def main() -> int:
    print("=" * 58)
    print("ModuBoard Industrial Workbench - Field Check")
    print("=" * 58)
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    missing = []
    for module_name, package_name in REQUIRED.items():
        try:
            importlib.import_module(module_name)
            print(f"[OK] {package_name} {metadata.version(package_name)}")
        except Exception as exc:
            missing.append(package_name)
            print(f"[FAIL] {package_name}: {exc}")

    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        if ports:
            print("\nSerial ports:")
            for port in ports:
                print(f"  {port.device:<10} {port.description}")
        else:
            print("\nSerial ports: none detected (Modbus TCP / OPC UA are unaffected)")
    except Exception:
        pass

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 5000))
        print("[OK] Local UI port 5000 is available")
    except OSError as exc:
        print(f"[WARN] Local UI port 5000 is occupied: {exc}")
    finally:
        probe.close()

    if missing:
        print("\nResult: NOT READY")
        print("Run INSTALL_OFFLINE.cmd before going onsite.")
        return 1
    print("\nResult: READY FOR FIELD CONNECTION")
    print("Remember: verify IP/VLAN/firewall, Unit ID, address mode, and OPC security policy onsite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
