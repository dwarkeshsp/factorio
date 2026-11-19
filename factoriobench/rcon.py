"""A minimal Source RCON client, enough for Factorio's console.

Factorio answers each command with exactly one packet, however long the output, so no
sentinel packet is needed to find the end of a response (checked with a 56 kB reply on 2.1.24).
"""
from __future__ import annotations

import socket
import struct
import threading

AUTH, AUTH_RESPONSE, EXEC, RESPONSE = 3, 2, 2, 0


class RconError(RuntimeError):
    pass


def encode_packet(request_id: int, kind: int, body: str) -> bytes:
    payload = struct.pack("<ii", request_id, kind) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def decode_packet(payload: bytes) -> tuple[int, int, str]:
    request_id, kind = struct.unpack("<ii", payload[:8])
    return request_id, kind, payload[8:-2].decode("utf-8", "replace")


class Rcon:
    def __init__(self, host: str, port: int, password: str, timeout: float = 30.0):
        self._lock = threading.Lock()
        self._next_id = 0
        self._sock = socket.create_connection((host, port), timeout=timeout)
        request_id = self._send(AUTH, password)
        reply_id, _, _ = self._receive()
        if reply_id != request_id:
            self._sock.close()
            raise RconError("RCON authentication failed")

    def _send(self, kind: int, body: str) -> int:
        self._next_id += 1
        self._sock.sendall(encode_packet(self._next_id, kind, body))
        return self._next_id

    def _read(self, n: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < n:
            chunk = self._sock.recv(n - len(chunks))
            if not chunk:
                raise RconError("RCON connection closed by the server")
            chunks.extend(chunk)
        return bytes(chunks)

    def _receive(self) -> tuple[int, int, str]:
        (length,) = struct.unpack("<i", self._read(4))
        return decode_packet(self._read(length))

    def command(self, text: str) -> str:
        with self._lock:
            request_id = self._send(EXEC, text)
            while True:
                reply_id, _, body = self._receive()
                if reply_id == request_id:
                    return body.rstrip("\n")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
