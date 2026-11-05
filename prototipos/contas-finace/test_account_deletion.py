"""Exclusão em bancos temporários e provedor simulado, sem identidades reais."""
import http.client
import http.server
import json
import os
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import Mock, patch

from account_deletion import AccountDeletion
from auth_supabase import AuthError
from online import OnlineHandler, ACCESS_COOKIE, REFRESH_COOKIE, DELETION_COOKIE
from server import create_server, uid
from test_server import Client


class DeletionProofTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"FINACE_SUPABASE_SECRET_KEY": "sb_secret_test-only",
                                          "FINACE_ACCOUNT_DELETION_READY": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = AccountDeletion(Mock(url="https://test.supabase.co"))
        self.owner = uid()

    def test_proof_is_bound_to_owner_session_and_expiration(self):
        with patch("account_deletion.time.time", return_value=1000):
            proof = self.service.proof(self.owner, "session-a")
            self.service.validate(proof, self.owner, "session-a")
            for owner, refresh in [(uid(), "session-a"), (self.owner, "session-b")]:
                with self.assertRaises(AuthError): self.service.validate(proof, owner, refresh)
            with self.assertRaises(AuthError): self.service.validate(proof + "x", self.owner, "session-a")
        with patch("account_deletion.time.time", return_value=1300):
            with self.assertRaises(AuthError): self.service.validate(proof, self.owner, "session-a")

    def test_disabled_service_never_calls_upstream(self):
        with patch.dict(os.environ, {"FINACE_ACCOUNT_DELETION_READY": "false"}), \
                patch("account_deletion.request_json") as request:
            service = AccountDeletion(self.service.auth)
            self.assertFalse(service.available)
            with self.assertRaises(AuthError): service.delete(self.owner)
            request.assert_not_called()

    def test_public_key_cannot_enable_administrative_deletion(self):
        with patch.dict(os.environ, {"FINACE_SUPABASE_SECRET_KEY": "sb_publishable_test-only"}):
            self.assertFalse(AccountDeletion(self.service.auth).available)

    def test_modern_secret_is_not_sent_as_a_user_jwt(self):
        with patch("account_deletion.request_json", return_value={}) as request:
            self.service.delete(self.owner)
        headers = request.call_args.args[1]
        self.assertEqual(headers["apikey"], "sb_secret_test-only")
        self.assertNotIn("Authorization", headers)


class ExternalDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finace-delete-")
        self.server = create_server(0, Path(self.temp.name) / "test.sqlite3", auth_mode="demo")
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.owner, self.second, self.external = Client(self), Client(self), Client(self)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def test_external_flow_deletes_only_verified_account_and_all_its_sessions(self):
        self.owner.login("ana@finace.test")
        self.second.login("ana@finace.test")
        challenge, _ = self.external.request("/api/account/deletion/request", {"email": "ana@finace.test"})
        self.external.request("/api/account/deletion/verify", {"challenge": challenge["challenge"], "code": challenge["demo_code"]})
        session, _ = self.external.request("/api/session")
        self.external.csrf = session["csrf"]
        self.external.request("/api/account/delete", {"confirmation": "wrong"}, status=403)
        self.external.request("/api/account/delete", {"confirmation": "EXCLUIR"})
        self.owner.request("/api/session", status=401)
        self.second.request("/api/session", status=401)
        self.external.request("/api/session", status=401)
        with self.server.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE email='ana@finace.test'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wallets WHERE owner=?", (session["user"]["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE email='bruno@finace.test'").fetchone()[0], 1)

    def test_external_unknown_address_does_not_create_a_new_account(self):
        challenge, _ = self.external.request("/api/account/deletion/request", {"email": "unknown@finace.test"})
        self.external.request("/api/account/deletion/verify", {"challenge": challenge["challenge"], "code": challenge["demo_code"]}, status=400)
        with self.server.store.db() as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE email='unknown@finace.test'").fetchone())

    def test_external_flow_rejects_wrong_and_reused_codes(self):
        challenge, _ = self.external.request("/api/account/deletion/request", {"email": "ana@finace.test"})
        wrong = "111111" if challenge["demo_code"] != "111111" else "222222"
        body = {"challenge": challenge["challenge"], "code": wrong}
        self.external.request("/api/account/deletion/verify", body, status=400)
        body["code"] = challenge["demo_code"]
        self.external.request("/api/account/deletion/verify", body)
        self.external.request("/api/account/deletion/verify", body, status=400)


class OnlineDeletionTests(unittest.TestCase):
    def test_https_external_flow_requires_proof_and_revokes_before_hard_deletion(self):
        host, owner = "finace-test.example.org", uid()
        auth = Mock(configured=True)
        auth.call.return_value = {"id": owner, "email": "ana@example.org"}
        auth.verify_code.return_value = {"id": owner, "email": "ana@example.org", "tokens": ("access", "refresh", 3600)}
        events = []
        def transport(url, headers, payload=None, method="GET", **kwargs):
            events.append((url, method, payload))
            return {}
        def authenticate(path, payload=None, access_token=None):
            events.append((path, access_token))
            return {"id": owner, "email": "ana@example.org"}
        auth.call.side_effect = authenticate
        environment = {"FINACE_ONLINE_HOSTS": host, "VERCEL_ENV": "preview",
                       "FINACE_SUPABASE_SECRET_KEY": "sb_secret_fixture", "FINACE_ACCOUNT_DELETION_READY": "true"}
        auth.url = "https://test.supabase.co"
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), OnlineHandler) as server, \
                patch.dict(os.environ, environment), patch("online.online_auth", return_value=auth), \
                patch("online.CloudWallet") as cloud, patch("account_deletion.request_json", side_effect=transport):
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                jar = SimpleCookie()
                def call(path, body, **extra):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    headers = {"Host": host, "Origin": "https://" + host, "X-Prototype": "local",
                               "Cookie": "; ".join(f"{v.key}={v.coded_value}" for v in jar.values()), **extra}
                    connection.request("POST", "/conta/api/" + path, json.dumps(body), headers)
                    response = connection.getresponse()
                    for key, value in response.getheaders():
                        if key == "Set-Cookie": jar.load(value)
                    output = (response.status, response.read())
                    connection.close()
                    return output
                self.assertEqual(call("account/deletion/request", {"email": "ana@example.org"})[0], 200)
                auth.request_code.assert_called_once_with("ana@example.org", create_user=False)
                self.assertEqual(call("account/deletion/verify", {"challenge": "ana@example.org", "code": "123456"})[0], 200)
                cloud.return_value.ensure_wallet.assert_not_called()
                original = jar[DELETION_COOKIE].value
                jar[DELETION_COOKIE] = original + "x"
                self.assertEqual(call("account/delete", {"confirmation": "EXCLUIR"})[0], 403)
                self.assertFalse(any("/admin/users/" in event[0] for event in events))
                jar[DELETION_COOKIE] = original
                self.assertEqual(call("account/delete", {"confirmation": "EXCLUIR"}, Origin="https://other.example.org")[0], 403)
                self.assertEqual(call("account/delete", {"confirmation": "EXCLUIR", "owner": uid()})[0], 200)
                revoke = next(i for i, event in enumerate(events) if event[0] == "/logout?scope=global")
                delete = next(i for i, event in enumerate(events) if "/admin/users/" in event[0])
                self.assertLess(revoke, delete)
                self.assertEqual(events[delete][0], "https://test.supabase.co/auth/v1/admin/users/" + owner)
                self.assertEqual(events[delete][1:], ("DELETE", {"should_soft_delete": False}))
                self.assertTrue(all(jar[name]["max-age"] == "0" for name in (ACCESS_COOKIE, REFRESH_COOKIE, DELETION_COOKIE)))
            finally:
                server.shutdown(); thread.join()
