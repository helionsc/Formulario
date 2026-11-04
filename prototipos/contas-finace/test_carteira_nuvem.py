"""Exercita a integração HTTP da prévia com duas sessões e um armazenamento de teste."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from auth_supabase import SupabaseAuth
from server import create_server, uid
from test_server import Client


class CloudPreviewTest(unittest.TestCase):
    def test_same_account_recovers_import_and_another_account_cannot_read_it(self):
        users = {name + "@example.org": uid() for name in ("ana", "bruno")}
        snapshots = {}

        def auth(path, payload, token):
            if path == "/otp":
                return {}
            if path == "/verify":
                return {"access_token": payload["email"], "refresh_token": "test-refresh", "expires_in": 3600}
            if path == "/user":
                return {"id": users[token], "email": token, "email_confirmed_at": "2026-11-04T10:00:00Z"}
            self.fail("Unexpected Auth call: " + path)

        def rest(url, headers, payload, method, **_):
            owner = users[headers["Authorization"].removeprefix("Bearer ")]
            route = urlsplit(url)
            self.assertEqual(route.path, "/rest/v1/finace_previa_carteiras")
            filters = parse_qs(route.query)
            if method == "POST":
                self.assertEqual(headers["Prefer"], "resolution=ignore-duplicates,return=minimal")
                snapshots.setdefault(owner, copy.deepcopy(payload["prefs"]))
                return None
            self.assertEqual(filters["owner_id"], ["eq." + owner])
            if method == "GET":
                return [{"prefs": copy.deepcopy(snapshots[owner])}]
            if method == "PATCH" and filters["prefs->>revision"] == ["eq." + snapshots[owner]["revision"]]:
                snapshots[owner] = copy.deepcopy(payload["prefs"])
                return [{"owner_id": owner}]
            return []

        def login(client, email):
            c, _ = client.request("/api/auth/request", {"email": email})
            client.request("/api/auth/verify", {"challenge": c["challenge"], "code": "123456"})
            data, _ = client.request("/api/session")
            client.csrf = data["csrf"]
            client.wallet = data["wallets"][0]["id"]

        with tempfile.TemporaryDirectory() as root, patch("carteira_nuvem.request_json", side_effect=rest):
            provider = SupabaseAuth("https://finace-contract-tests.supabase.co", "sb_publishable_test", auth, otp_ready=True)
            for instance in ("first", "second"):
                server = create_server(0, Path(root) / (instance + ".sqlite3"), auth_provider=provider, cloud_wallet=True)
                self.addCleanup(server.server_close)
                thread = threading.Thread(target=lambda s=server: s.serve_forever(poll_interval=.01), daemon=True)
                thread.start()
                self.addCleanup(server.shutdown)
                self.server = server
                a = Client(self)
                login(a, "ana@example.org")
                if instance == "first":
                    row = a.snapshot()
                    original_revision = row["prefs"]["revision"]
                    backup = json.loads((Path(__file__).parent / "web/exemplo-backup.json").read_text())
                    row["prefs"].update(carteira=backup["carteira"], revision=uid())
                    endpoint = "/api/app/carteiras?id=eq." + a.wallet + "&prefs->>revision=eq." + original_revision
                    self.assertEqual(a.request(endpoint, row, "PATCH")[0][0]["prefs"], row["prefs"])
                    self.assertEqual(a.request(endpoint, row, "PATCH")[0], [])
                else:
                    self.assertEqual(a.snapshot()["prefs"], row["prefs"])
                    b = Client(self)
                    login(b, "bruno@example.org")
                    self.assertEqual(b.snapshot()["prefs"]["carteira"], [])
                    b.request("/api/app/carteiras?id=eq." + a.wallet, headers={"X-Wallet": a.wallet}, status=403)
