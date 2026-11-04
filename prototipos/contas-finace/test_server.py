"""Testes HTTP reais, somente em banco temporário e endereço de loopback."""
import copy
import http.cookiejar
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from server import create_server, uid


class Client:
    def __init__(self, test):
        self.test = test
        self.base = f"http://127.0.0.1:{test.server.server_port}"
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), urllib.request.ProxyHandler({}))
        self.csrf = ""
        self.wallet = ""

    def request(self, path, body=None, method=None, status=200, headers=None):
        hdr = {"Content-Type": "application/json", "Origin": self.base, "X-Prototype": "local", "X-CSRF-Token": self.csrf, "X-Wallet": self.wallet, **(headers or {})}
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data, hdr, method=method or ("POST" if body is not None else "GET"))
        try:
            r = self.http.open(req, timeout=4)
        except urllib.error.HTTPError as e:
            r = e
        self.test.assertEqual(r.status, status, (path, r.read().decode()) if r.status != status else path)
        raw = r.read()
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            result = raw
        return result, r.headers

    def login(self, email):
        challenge, _ = self.request("/api/auth/request", {"email": email})
        self.request("/api/auth/verify", {"challenge": challenge["challenge"], "code": challenge["demo_code"]})
        data, _ = self.request("/api/session")
        self.csrf = data["csrf"]
        self.wallet = data["wallets"][0]["id"]
        self.user = data["user"]["id"]
        return data

    def snapshot(self):
        return self.request("/api/app/carteiras?id=eq." + self.wallet)[0][0]

    def update(self, amount=12345):
        row = self.snapshot()
        rev = row["prefs"]["revision"]
        row["prefs"]["revision"] = uid()
        row["prefs"]["carteira"][0]["valor"] = amount
        return self.request("/api/app/carteiras?id=eq." + self.wallet + "&prefs->>revision=eq." + rev, row, "PATCH")[0]


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finace-teste-")
        self.server = create_server(0, Path(self.temp.name) / "teste.sqlite3", auth_mode="demo")
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.a, self.b = Client(self), Client(self)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def pair(self):
        self.a.login("ana@finace.test")
        self.b.login("bruno@finace.test")

    def test_01_no_access_without_login(self):
        self.a.request("/api/session", status=401)
        self.a.request("/app.html?wallet=" + uid(), status=401)
        self.a.request("/api/app/carteiras?id=eq." + uid(), status=401)

    def test_02_static_content_and_external_connections_blocked(self):
        html, headers = self.a.request("/")
        self.assertIn(b"PR\xc3\x89VIA LOCAL", html)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.a.request("/dados-locais/teste.sqlite3", status=404)
        self.a.request("/../server.py", status=404)

    def test_03_only_fictitious_email(self):
        self.a.request("/api/auth/request", {"email": "pessoa@example.com"}, status=400)
        self.a.request("/api/auth/request", {"email": "nao-email"}, status=400)

    def test_04_session_cookie_is_httponly_and_scoped(self):
        self.a.login("ana@finace.test")
        cookie = list(self.a.jar)[0]
        self.assertIn("HttpOnly", cookie._rest)
        self.assertEqual(cookie._rest["SameSite"], "Strict")
        self.assertEqual(cookie.path, "/")
        html, _ = self.a.request("/app.html?wallet=" + self.a.wallet)
        self.assertNotIn(b"supabase.co", html)
        self.assertNotIn(b"SB_KEY", html)
        self.assertNotIn(cookie.value.encode(), html)

    def test_05_wrong_otp_and_replay_rejected(self):
        c, _ = self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        wrong = "000000" if c["demo_code"] != "000000" else "111111"
        self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": wrong}, status=400)
        self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": c["demo_code"]})
        self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": c["demo_code"]}, status=400)

    def test_06_five_wrong_attempts_lock_challenge(self):
        c, _ = self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        wrong = "000000" if c["demo_code"] != "000000" else "111111"
        for _ in range(5):
            self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": wrong}, status=400)
        self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": c["demo_code"]}, status=400)

    def test_07_expired_otp_rejected(self):
        c, _ = self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        with self.server.store.db() as db:
            db.execute("UPDATE challenges SET expires=0 WHERE id=?", (c["challenge"],))
        self.a.request("/api/auth/verify", {"challenge": c["challenge"], "code": c["demo_code"]}, status=400)

    def test_08_new_code_invalidates_previous(self):
        old, _ = self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        new, _ = self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        self.a.request("/api/auth/verify", {"challenge": old["challenge"], "code": old["demo_code"]}, status=400)
        self.a.request("/api/auth/verify", {"challenge": new["challenge"], "code": new["demo_code"]})

    def test_09_otp_request_rate_limited(self):
        for _ in range(5):
            self.a.request("/api/auth/request", {"email": "nova@finace.test"})
        self.a.request("/api/auth/request", {"email": "nova@finace.test"}, status=429)

    def test_10_csrf_and_cross_origin_rejected(self):
        self.a.login("ana@finace.test")
        self.a.request("/api/auth/logout", {}, headers={"X-CSRF-Token": "wrong"}, status=403)
        self.a.request("/api/auth/logout", {}, headers={"Origin": "https://example.com"}, status=403)
        self.a.request("/api/auth/logout", {}, headers={"X-Prototype": ""}, status=403)
        self.a.request("/api/session")

    def test_11_logout_revokes_server_session(self):
        self.a.login("ana@finace.test")
        self.a.request("/api/auth/logout", {})
        self.a.request("/api/session", status=401)

    def test_12_expired_session_rejected(self):
        self.a.login("ana@finace.test")
        with self.server.store.db() as db:
            db.execute("UPDATE sessions SET expires=0")
        self.a.request("/api/session", status=401)

    def test_13_new_account_has_empty_wallet(self):
        self.a.login("vazia@finace.test")
        self.assertEqual(self.a.snapshot()["prefs"]["carteira"], [])

    def test_14_account_isolation_and_wallet_header_forgery(self):
        self.pair()
        self.assertNotEqual(self.a.wallet, self.b.wallet)
        self.a.request("/api/app/carteiras?id=eq." + self.b.wallet, status=403)
        self.a.request("/api/app/carteiras?id=eq." + self.b.wallet, headers={"X-Wallet": self.b.wallet}, status=403)
        self.a.request("/app.html?wallet=" + self.b.wallet, status=403)
        self.assertEqual(sum(p["valor"] for p in self.a.snapshot()["prefs"]["carteira"]), 18000)
        self.assertEqual(sum(p["valor"] for p in self.b.snapshot()["prefs"]["carteira"]), 6000)

    def test_15_no_unfiltered_collection_read(self):
        self.a.login("ana@finace.test")
        self.a.request("/api/app/carteiras", status=403)
        self.a.request("/api/app/carteiras?id=not.is.null", status=403)
        self.a.request("/api/app/posicoes", status=404)

    def test_16_wrong_wallet_write_and_owner_change_rejected(self):
        self.pair()
        row = self.a.snapshot()
        revision = row["prefs"]["revision"]
        url = "/api/app/carteiras?id=eq." + self.a.wallet + "&prefs->>revision=eq." + revision
        row["id"] = self.b.wallet
        self.a.request(url, row, "PATCH", status=403)
        row["id"] = self.a.wallet
        row["owner"] = self.b.user
        self.a.request(url, row, "PATCH", status=400)
        self.a.request("/api/app/carteiras", row, status=405)

    def test_17_same_account_on_second_device_and_conflict(self):
        self.a.login("ana@finace.test")
        self.b.login("ana@finace.test")
        self.assertEqual(self.a.wallet, self.b.wallet)
        stale = self.b.snapshot()
        revision = stale["prefs"]["revision"]
        self.a.update(12000)
        stale["prefs"]["revision"] = uid()
        stale["prefs"]["carteira"][0]["valor"] = 1
        result, _ = self.b.request("/api/app/carteiras?id=eq." + self.b.wallet + "&prefs->>revision=eq." + revision, stale, "PATCH")
        self.assertEqual(result, [])
        self.assertEqual(self.b.snapshot()["prefs"]["carteira"][0]["valor"], 12000)

    def test_18_invite_does_not_grant_access_until_accepted(self):
        self.pair()
        self.a.request("/api/sharing/invite", {"email": "bruno@finace.test"})
        self.b.request("/api/app/carteiras?id=eq." + self.a.wallet, headers={"X-Wallet": self.a.wallet}, status=403)
        data, _ = self.b.request("/api/session")
        invite = data["invites"][0]["id"]
        self.a.request("/api/invites/accept", {"invite": invite}, status=403)
        self.b.request("/api/invites/accept", {"invite": invite})
        self.b.wallet = self.a.wallet
        self.assertEqual(self.b.snapshot(), self.a.snapshot())
        self.b.update(11000)
        self.assertEqual(self.a.snapshot()["prefs"]["carteira"][0]["valor"], 11000)

    def test_19_shared_editor_cannot_manage_members(self):
        self.test_18_invite_does_not_grant_access_until_accepted()
        self.b.request("/api/sharing/invite", {"email": "terceiro@finace.test"}, status=403)
        self.b.request("/api/sharing/revoke", {"member": self.a.user}, status=403)

    def test_20_revocation_blocks_existing_session_read_and_write(self):
        self.test_18_invite_does_not_grant_access_until_accepted()
        row = self.b.snapshot()
        self.a.request("/api/sharing/revoke", {"member": self.b.user})
        self.b.request("/api/app/carteiras?id=eq." + self.b.wallet, status=403)
        self.b.request("/api/app/carteiras?id=eq." + self.b.wallet, row, "PATCH", status=403)
        self.b.request("/app.html?wallet=" + self.b.wallet, status=403)

    def test_21_invite_can_be_cancelled_and_expires(self):
        self.pair()
        self.a.request("/api/sharing/invite", {"email": "bruno@finace.test"})
        data, _ = self.b.request("/api/session")
        invite = data["invites"][0]["id"]
        self.a.request("/api/sharing/revoke", {"invite": invite})
        self.b.request("/api/invites/accept", {"invite": invite}, status=403)
        self.a.request("/api/sharing/invite", {"email": "bruno@finace.test"})
        with self.server.store.db() as db:
            db.execute("UPDATE invites SET expires=0")
        self.assertEqual(self.b.request("/api/session")[0]["invites"], [])

    def test_22_restore_versions_and_stale_restore_rejected(self):
        self.a.login("ana@finace.test")
        before = self.a.snapshot()
        self.a.update(12000)
        versions, _ = self.a.request("/api/versions")
        version = versions["versions"][0]["id"]
        self.a.request("/api/versions/restore", {"version": version, "revision": "old"}, status=409)
        current = self.a.snapshot()["prefs"]["revision"]
        self.a.request("/api/versions/restore", {"version": version, "revision": current})
        restored = self.a.snapshot()
        self.assertEqual(restored["prefs"]["carteira"], before["prefs"]["carteira"])
        self.assertNotEqual(restored["prefs"]["revision"], before["prefs"]["revision"])
        self.assertEqual(len(self.a.request("/api/versions")[0]["versions"]), 2)

    def test_23_versions_isolated_and_capped(self):
        self.pair()
        for i in range(23):
            self.a.update(1000 + i)
        versions = self.a.request("/api/versions")[0]["versions"]
        self.assertEqual(len(versions), 20)
        self.assertEqual(self.b.request("/api/versions")[0]["versions"], [])
        self.b.request("/api/versions/restore", {"version": versions[0]["id"], "revision": self.b.snapshot()["prefs"]["revision"]}, status=404)

    def test_24_malformed_data_cannot_replace_confirmed_snapshot(self):
        self.a.login("ana@finace.test")
        before = self.a.snapshot()
        for field, value in [("valor", -1), ("banco", "<script>"), ("data", "2026-02-30"), ("tipo", "INEXISTENTE")]:
            invalid = copy.deepcopy(before)
            invalid["prefs"]["carteira"][0][field] = value
            self.a.request("/api/app/carteiras?id=eq." + self.a.wallet + "&prefs->>revision=eq." + before["prefs"]["revision"], invalid, "PATCH", status=400)
        self.assertEqual(self.a.snapshot(), before)

    def test_25_json_snapshot_preserves_ids_history_and_assumptions(self):
        self.a.login("vazia@finace.test")
        fixture = json.loads((Path(__file__).parent / "web/exemplo-backup.json").read_text())
        row = self.a.snapshot()
        revision = row["prefs"]["revision"]
        row["prefs"] = {"snapshot": 2, "revision": uid(), **{key: fixture[key] for key in ["carteira", "diario", "premissas"]}}
        self.a.request("/api/app/carteiras?id=eq." + self.a.wallet + "&prefs->>revision=eq." + revision, row, "PATCH")
        actual = self.a.snapshot()["prefs"]
        for key in ["carteira", "diario", "premissas"]:
            self.assertEqual(actual[key], fixture[key])

    def deletion_grant(self, client, email):
        c, _ = client.request("/api/auth/request", {"email": email, "purpose": "delete"})
        client.request("/api/auth/verify", {"challenge": c["challenge"], "code": c["demo_code"]})

    def test_26_deletion_requires_reauthentication_and_exact_confirmation(self):
        self.a.login("ana@finace.test")
        self.a.request("/api/account/delete", {"confirmation": "EXCLUIR"}, status=403)
        self.a.request("/api/auth/request", {"email": "bruno@finace.test", "purpose": "delete"}, status=403)
        self.deletion_grant(self.a, "ana@finace.test")
        self.a.request("/api/account/delete", {"confirmation": "sim"}, status=403)
        self.a.request("/api/session")

    def test_27_deletion_removes_all_owned_data_and_other_sessions(self):
        self.pair()
        second = Client(self)
        second.login("ana@finace.test")
        wallet, user = self.a.wallet, self.a.user
        self.a.update(13000)
        self.a.request("/api/sharing/invite", {"email": "bruno@finace.test"})
        self.deletion_grant(self.a, "ana@finace.test")
        self.a.request("/api/account/delete", {"confirmation": "EXCLUIR"})
        second.request("/api/session", status=401)
        self.a.request("/api/session", status=401)
        with self.server.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wallets WHERE owner=?", (user,)).fetchone()[0], 0)
            for table in ["versions", "invites", "members"]:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE wallet=?", (wallet,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE user=?", (user,)).fetchone()[0], 0)
        self.b.snapshot()

    def test_28_deleting_member_preserves_other_owners_wallet(self):
        self.test_18_invite_does_not_grant_access_until_accepted()
        self.deletion_grant(self.b, "bruno@finace.test")
        self.b.request("/api/account/delete", {"confirmation": "EXCLUIR"})
        self.a.snapshot()
        self.assertEqual(self.a.request("/api/sharing")[0]["members"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
