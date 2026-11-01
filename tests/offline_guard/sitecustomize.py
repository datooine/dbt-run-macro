"""Test-only guard inherited by workers; pure compilation must never reach these APIs."""

import os

if os.environ.get("DBT_INVOKE_TEST_OFFLINE") == "1":
    import socket

    import google.auth

    def blocked(*args, **kwargs):
        path = os.environ.get("DBT_INVOKE_TEST_ATTEMPTS")
        if path:
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("network or credential discovery attempted\n")
        raise RuntimeError("Offline test forbids network access and credential discovery")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    google.auth.default = blocked
