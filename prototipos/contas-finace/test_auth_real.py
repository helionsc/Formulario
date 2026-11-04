"""Testa o contrato de OTP real sem enviar e-mails ou chamar serviços externos."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from auth_supabase import AuthError, SupabaseAuth
from server import create_server, uid
from test_server import Client


class Upstream:
    def __init__(self):
        self.identities = {}
        self.calls = []
        self.email = None
        self.confirmed = True
        self.return_other_email = False
        self.failure = False
        self.subject_override = None

    def __call__(self, path, payload=None, access=None):
        self.calls.append((path, payload, access))
        if self.failure:
            raise AuthError(503, "Envio indisponível no teste.")
        if path == "/otp":
            self.email = payload["email"]
            self.identities.setdefault(self.email, uid())
            return {}
        if path == "/verify":
            if payload["token"] != "654321":
                raise AuthError(400, "Código inválido ou expirado.")
            self.email = payload["email"]
            return {"access_token": "upstream-private-token", "refresh_token": "upstream-private-refresh"}
        if path == "/user":
            return {"id": self.subject_override or self.identities[self.email], "email": "outra@example.org" if self.return_other_email else self.email, "email_confirmed_at": "2026-11-03T12:00:00Z" if self.confirmed else None}
        raise AssertionError(path)


class RealAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finace-auth-")
        self.upstream = Upstream()
        provider = SupabaseAuth("https://finace-contract-tests.supabase.co", "sb_publishable_test", self.upstream, otp_ready=True)
        self.server = create_server(0, Path(self.temp.name) / "real.sqlite3", auth_provider=provider)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.a = Client(self)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, email="ana@example.org"):
        return self.a.request("/api/auth/request", {"email": email})[0]

    def verify(self, challenge, code="654321", status=200):
        return self.a.request("/api/auth/verify", {"challenge": challenge["challenge"], "code": code}, status=status)

    def login(self):
        challenge = self.request()
        result, headers = self.verify(challenge)
        data, _ = self.a.request("/api/session")
        self.a.csrf = data["csrf"]
        self.a.wallet = data["wallets"][0]["id"]
        return result, headers, data

    def test_01_no_demo_code_or_session_after_request(self):
        result = self.request()
        self.assertFalse(result["simulated"])
        self.assertNotIn("demo_code", result)
        self.assertEqual(result["delivery"], "email")
        self.a.request("/api/session", status=401)
        with self.server.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_02_confirmed_email_creates_owned_empty_wallet(self):
        _, _, data = self.login()
        self.assertEqual(data["user"]["id"], self.upstream.identities["ana@example.org"])
        self.assertEqual(self.a.snapshot()["prefs"]["carteira"], [])
        self.assertEqual(data["wallets"][0]["role"], "owner")
        self.assertTrue(any(call[0] == "/user" for call in self.upstream.calls))

    def test_03_invalid_code_cannot_create_account_or_session(self):
        challenge = self.request()
        self.verify(challenge, "000000", status=400)
        self.a.request("/api/session", status=401)
        with self.server.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_04_six_digits_required_and_attempt_limit(self):
        challenge = self.request()
        for code in ["", "abc123", "12345", "1234567", "111111"]:
            self.verify(challenge, code, status=400)
        self.verify(challenge, status=400)

    def test_05_email_must_be_confirmed_by_provider(self):
        challenge = self.request()
        self.upstream.confirmed = False
        self.verify(challenge, status=401)
        self.a.request("/api/session", status=401)

    def test_06_different_verified_email_refused(self):
        challenge = self.request()
        self.upstream.return_other_email = True
        self.verify(challenge, status=401)

    def test_07_challenge_bound_to_email_and_single_use(self):
        challenge = self.request()
        self.a.request("/api/auth/verify", {"challenge": challenge["challenge"], "code": "654321", "email": "invasor@example.org", "user": uid()})
        self.assertEqual(self.a.request("/api/session")[0]["user"]["email"], "ana@example.org")
        self.verify(challenge, status=400)

    def test_08_expired_challenge_refused(self):
        challenge = self.request()
        with self.server.store.db() as db:
            db.execute("UPDATE challenges SET expires=0")
        self.verify(challenge, status=400)

    def test_09_existing_identity_recovers_same_wallet(self):
        _, _, first = self.login()
        self.a.request("/api/auth/logout", {})
        with self.server.store.db() as db:
            db.execute("UPDATE challenges SET created=0")
        _, _, second = self.login()
        self.assertEqual(first["wallets"][0]["id"], second["wallets"][0]["id"])
        self.assertEqual(first["user"]["id"], second["user"]["id"])

    def test_10_same_email_with_new_subject_does_not_claim_previous_wallet(self):
        self.login()
        with self.server.store.db() as db:
            db.execute("UPDATE challenges SET created=0")
        challenge = self.request()
        self.upstream.subject_override = uid()
        self.verify(challenge, status=409)

    def test_11_upstream_tokens_not_exposed_in_cookie_or_response(self):
        result, headers, session = self.login()
        for output in [str(result), str(headers), str(session)]:
            self.assertNotIn("upstream-private-token", output)
            self.assertNotIn("upstream-private-refresh", output)
        self.assertIn("finace_real=", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])

    def test_existing_session_is_renewed_and_reopens_without_another_code(self):
        _, login_headers, first = self.login()
        self.assertIn("Max-Age=2592000", login_headers["Set-Cookie"])
        initial_expiry = time.time() + 12 * 60 * 60
        next(iter(self.a.jar)).expires = int(initial_expiry)
        with self.server.store.db() as db:
            db.execute("UPDATE sessions SET expires=?", (initial_expiry,))

        _, renewal_headers = self.a.request("/api/session")
        self.assertIn("Max-Age=2592000", renewal_headers["Set-Cookie"])
        self.assertGreater(next(iter(self.a.jar)).expires, initial_expiry)
        _, next_headers = self.a.request("/api/session")
        self.assertIsNone(next_headers.get("Set-Cookie"))

        provider_calls = len(self.upstream.calls)
        tomorrow = SimpleNamespace(time=lambda: initial_expiry + 24 * 60 * 60)
        with patch("server.time", tomorrow):
            reopened, _ = self.a.request("/api/session")
            self.assertEqual(reopened["user"], first["user"])
            self.assertEqual(reopened["wallets"], first["wallets"])
            Client(self).request("/api/session", status=401)
            self.a.request("/api/auth/logout", {})
            self.a.request("/api/session", status=401)
        self.assertEqual(len(self.upstream.calls), provider_calls)

    def test_12_request_failure_does_not_claim_email_sent(self):
        self.upstream.failure = True
        result, _ = self.a.request("/api/auth/request", {"email": "ana@example.org"}, status=503)
        self.assertNotIn("challenge", result)
        with self.server.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM challenges").fetchone()[0], 0)

    def test_13_real_mode_refuses_demo_addresses(self):
        self.a.request("/api/auth/request", {"email": "ana@finace.test"}, status=400)
        self.assertEqual(self.upstream.calls, [])

    def test_14_no_fallback_when_not_configured(self):
        self.server.auth_provider = SupabaseAuth()
        self.a.request("/api/auth/request", {"email": "ana@example.org"}, status=503)
        self.a.request("/api/session", status=401)
        self.assertFalse(self.a.request("/api/config")[0]["configured"])

    def test_15_public_config_does_not_expose_keys_and_blocks_partial_deletion(self):
        config, _ = self.a.request("/api/config")
        self.assertEqual(config["auth_mode"], "supabase")
        self.assertNotIn("sb_publishable", str(config))
        self.assertFalse(config["account_deletion_available"])
        self.login()
        self.a.request("/api/account/delete", {"confirmation": "EXCLUIR"}, status=503)
        self.a.snapshot()

    def test_16_resend_waits_one_minute(self):
        self.request()
        self.a.request("/api/auth/request", {"email": "ana@example.org"}, status=429)
        self.assertEqual(len(self.upstream.calls), 1)

    def test_17_private_keys_and_unsafe_urls_not_accepted(self):
        for url, key in [("http://project.supabase.co", "sb_publishable_test"), ("https://evil.example.com", "sb_publishable_test"), ("https://project.supabase.co", "sb_secret_private")]:
            with self.assertRaises(ValueError):
                SupabaseAuth(url, key)

    def test_18_unconfigured_email_template_never_sends_unusable_link(self):
        self.server.auth_provider = SupabaseAuth("https://finace-contract-tests.supabase.co", "sb_publishable_test", self.upstream)
        self.a.request("/api/auth/request", {"email": "ana@example.org"}, status=503)
        self.assertEqual(self.upstream.calls, [])
        self.assertFalse(self.a.request("/api/config")[0]["configured"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
