import socket
import struct
import threading

import pytest

from factoriobench.rcon import AUTH, EXEC, Rcon, RconError, decode_packet, encode_packet


def test_packet_round_trip():
    packet = encode_packet(7, EXEC, "/silent-command rcon.print('héllo')")
    (length,) = struct.unpack("<i", packet[:4])
    assert length == len(packet) - 4
    assert decode_packet(packet[4:]) == (7, EXEC, "/silent-command rcon.print('héllo')")


def serve(password: str, replies: dict[str, str]):
    """A one-connection RCON server on a free port, answering like Factorio does."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def read(conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data

    def handle():
        conn, _ = listener.accept()
        try:
            while True:
                (length,) = struct.unpack("<i", read(conn, 4))
                request_id, kind, body = decode_packet(read(conn, length))
                if kind == AUTH:
                    conn.sendall(encode_packet(request_id if body == password else -1, 2, ""))
                else:
                    conn.sendall(encode_packet(request_id, 0, replies.get(body, "") + "\n"))
        except (EOFError, OSError):
            pass
        finally:
            conn.close()
            listener.close()

    threading.Thread(target=handle, daemon=True).start()
    return listener.getsockname()[1]


def test_command_returns_the_reply_without_the_trailing_newline():
    port = serve("secret", {"/version": "2.1.24", "big": "x" * 60000})
    rcon = Rcon("127.0.0.1", port, "secret")
    assert rcon.command("/version") == "2.1.24"
    assert rcon.command("big") == "x" * 60000
    assert rcon.command("unknown") == ""
    rcon.close()


def test_wrong_password_is_refused():
    port = serve("secret", {})
    with pytest.raises(RconError):
        Rcon("127.0.0.1", port, "wrong")
