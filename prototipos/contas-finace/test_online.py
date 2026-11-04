"""Verifica o contrato HTTPS da versão hospedada sem enviar e-mails."""
import http.client
import http.server
import json
import os
import threading
import unittest
from http.cookies import SimpleCookie
from unittest.mock import Mock, patch

from online import OnlineHandler, initial_wallet


class OnlineTest(unittest.TestCase):
    def test_email_login_issues_private_cookies_and_enforces_wallet_owner(self):
        host = "finace-preview.example.org"
        owner = "c5181074-496a-42fc-9ed9-185a50cf7053"
        email = "ana@example.org"
        auth = Mock(configured=True)
        auth.verify_code.return_value = {"id": owner, "email": email, "tokens": ("test-access", "test-refresh", 3600)}
        auth.call.return_value = {"id": owner, "email": email}
        cloud = Mock()
        cloud.snapshot.return_value = initial_wallet()
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), OnlineHandler) as server, \
                patch.dict(os.environ, {"FINACE_ONLINE_HOSTS": host, "VERCEL_ENV": "preview"}), \
                patch("online.online_auth", return_value=auth), patch("online.CloudWallet", return_value=cloud):
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                def call(method, path, body=None, **headers):
                    c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    c.request(method, path, json.dumps(body) if body is not None else None,
                              {"Host": host, "Origin": "https://" + host, "X-Prototype": "local", **headers})
                    r = c.getresponse()
                    output = (r.status, r.getheaders(), r.read().decode())
                    c.close()
                    return output

                verify = "/conta/api/auth/verify"
                status, headers, result = call("POST", verify, {"challenge": email, "code": "123456"})
                self.assertEqual(status, 200)
                self.assertNotIn("test-refresh", result)
                cookies = [v for k, v in headers if k == "Set-Cookie"]
                self.assertEqual(len(cookies), 2)
                self.assertTrue(all("HttpOnly" in value and "Secure" in value for value in cookies))
                jar = SimpleCookie()
                for value in cookies:
                    jar.load(value)
                cookie = "; ".join(f"{item.key}={item.coded_value}" for item in jar.values())
                self.assertEqual(call("GET", "/conta/api/session", Cookie=cookie)[0], 200)
                route = "/conta/api/app/carteiras?id=eq." + owner
                self.assertEqual(call("GET", route, Cookie=cookie, **{"X-Wallet": "outra"})[0], 403)
                self.assertEqual(call("GET", route, Cookie=cookie, **{"X-Wallet": owner})[0], 200)
                self.assertEqual(call("POST", verify, {}, Origin="https://outra.example.org")[0], 403)
            finally:
                server.shutdown()
                thread.join()
