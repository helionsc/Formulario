"""Confere a exclusão real com identidades descartáveis antes do deploy de produção."""
import copy
import http.client
import json
import os
import threading
import urllib.error
import uuid
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer

from account_deletion import AccountDeletion
from auth_supabase import request_json
from online import OnlineHandler, online_auth


class TestClient:
    def __init__(self, port, host):
        self.port, self.host, self.cookies = port, host, SimpleCookie()

    def call(self, method, path, body=None, expected=200, **extra):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": self.host, "Origin": "https://" + self.host,
                   "X-Prototype": "local", "Content-Type": "application/json",
                   "Cookie": "; ".join(f"{v.key}={v.coded_value}" for v in self.cookies.values()), **extra}
        try:
            connection.request(method, "/conta/api/" + path,
                               json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            for key, value in response.getheaders():
                if key.lower() == "set-cookie":
                    self.cookies.load(value)
            result = json.loads(response.read())
            if response.status != expected:
                raise RuntimeError(f"Verificação {path.split('?')[0]}: HTTP {response.status}, esperado {expected}.")
            return result
        finally:
            connection.close()


def verify():
    if os.environ.get("VERCEL_ENV") != "production":
        print("Pré-publicação: verificação real reservada ao ambiente Production.")
        return
    auth = online_auth()
    deletion = AccountDeletion(auth)
    deletion.require_available()
    created = []
    host = "finace-pre-publicacao.invalid"
    previous_hosts = os.environ.get("FINACE_ONLINE_HOSTS", "")
    os.environ["FINACE_ONLINE_HOSTS"] = previous_hosts + "," + host
    headers = {"apikey": deletion.secret, "Content-Type": "application/json"}
    if deletion.secret.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + deletion.secret

    def admin(path, payload=None, method="GET"):
        return request_json(auth.url + "/auth/v1/admin" + path, headers, payload, method)

    def identity():
        email = "finace-deploy-" + uuid.uuid4().hex + "@example.org"
        user = admin("/users", {"email": email, "email_confirm": True,
                                "user_metadata": {"finace_disposable_deploy_test": True}}, "POST")
        owner = str(uuid.UUID(user["id"]))
        created.append(owner)
        if user.get("email") != email:
            raise RuntimeError("O provedor devolveu uma identidade diferente da conta de teste.")
        return owner, email

    def code_for(email):
        # generate_link produz o código no servidor e não envia e-mail.
        result = admin("/generate_link", {"type": "magiclink", "email": email}, "POST")
        return result.get("email_otp") or result.get("properties", {}).get("email_otp")

    def rows(table, owner):
        return request_json(auth.url + "/rest/v1/" + table + "?select=owner_id&owner_id=eq." + owner,
                            headers)

    try:
        owner_a, email_a = identity()
        owner_b, email_b = identity()
        with ThreadingHTTPServer(("127.0.0.1", 0), OnlineHandler) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                a, b = TestClient(server.server_port, host), TestClient(server.server_port, host)
                a.call("POST", "auth/verify", {"challenge": email_a, "code": code_for(email_a)})
                b.call("POST", "auth/verify", {"challenge": email_b, "code": code_for(email_b)})
                route_a = "app/carteiras?id=eq." + owner_a
                route_b = "app/carteiras?id=eq." + owner_b
                initial_a = a.call("GET", route_a, **{"X-Wallet": owner_a})[0]["prefs"]
                initial_b = b.call("GET", route_b, **{"X-Wallet": owner_b})[0]["prefs"]
                if initial_a["carteira"] or initial_b["carteira"]:
                    raise RuntimeError("Uma conta nova não começou vazia.")
                a.call("GET", route_b, expected=403, **{"X-Wallet": owner_b})
                changed = copy.deepcopy(initial_a)
                changed["revision"] = str(uuid.uuid4())
                changed["premissas"]["ipca"] = 5.1
                a.call("PATCH", route_a + "&prefs->>revision=eq." + initial_a["revision"],
                       {"id": owner_a, "prefs": changed}, **{"X-Wallet": owner_a})
                if not rows("finace_contas_versoes", owner_a):
                    raise RuntimeError("A versão de recuperação de teste não foi criada.")
                a.call("POST", "account/delete", {"confirmation": "EXCLUIR"}, expected=403)
                a.call("POST", "auth/verify", {"purpose": "delete", "challenge": email_a,
                                               "code": code_for(email_a)})
                a.call("POST", "account/delete", {"confirmation": "incorreta"}, expected=403)
                a.call("POST", "account/delete", {"confirmation": "EXCLUIR", "owner": owner_b})
                a.call("GET", "session", expected=401)
                try:
                    admin("/users/" + owner_a)
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
                else:
                    raise RuntimeError("A identidade excluída ainda existe no provedor.")
                if rows("finace_contas_carteiras", owner_a) or rows("finace_contas_versoes", owner_a):
                    raise RuntimeError("Restaram dados ativos vinculados à identidade excluída.")
                b.call("GET", "session")
                if b.call("GET", route_b, **{"X-Wallet": owner_b})[0]["prefs"] != initial_b:
                    raise RuntimeError("A carteira da segunda conta foi alterada.")
                b.call("POST", "auth/logout")
            finally:
                server.shutdown()
                thread.join()
        print("Pré-publicação OK: login real, contas vazias, isolamento, confirmação recente, exclusão e cascata conferidos.")
    finally:
        try:
            for owner in created:
                # Somente IDs retornados pela criação deste teste podem ser removidos.
                deletion.delete(owner)
        finally:
            os.environ["FINACE_ONLINE_HOSTS"] = previous_hosts


if __name__ == "__main__":
    try:
        verify()
    except Exception as error:
        # Credenciais, códigos e respostas do provedor nunca entram nos logs do build.
        print("Falha na verificação de pré-publicação:", type(error).__name__,
              str(error) if isinstance(error, RuntimeError) else
              getattr(error, "message", "Confira a configuração privada e o fluxo de exclusão."))
        raise SystemExit(1)
