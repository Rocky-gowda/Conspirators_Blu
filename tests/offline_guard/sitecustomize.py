"""Loaded automatically by Python when this folder is on PYTHONPATH (tests only).

Simulates Wi-Fi off: any network connection to a non-local address is refused and written to the
file in BLU_NET_LOG, so the test can prove the app never tried to reach the internet."""
import ipaddress
import os
import socket

_LOG = os.environ.get("BLU_NET_LOG")
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _local(addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _check(sock, addr):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not _local(addr):
        if _LOG:
            with open(_LOG, "a", encoding="utf-8") as f:
                f.write(f"blocked connection to {addr}\n")
        raise OSError("network is off (offline test)")


def connect(self, addr):
    _check(self, addr)
    return _connect(self, addr)


def connect_ex(self, addr):
    _check(self, addr)
    return _connect_ex(self, addr)


socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
