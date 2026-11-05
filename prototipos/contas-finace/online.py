"""API HTTPS para a carteira pessoal. Sessões não dependem de disco local."""
import base64
import hashlib
import json
import mimetypes
import os
import re
import uuid
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs, urlsplit

from auth_supabase import AuthError, SupabaseAuth, normalize_email
from carteira_nuvem import CloudWallet
from account_deletion import AccountDeletion, PROOF_SECONDS
from server import Error, Handler, ROOT, valid_prefs, site_information

REFRESH_MAX_AGE = 30 * 86400
ACCESS_COOKIE = "__Secure-finace-access"
REFRESH_COOKIE = "__Secure-finace-refresh"
DELETION_COOKIE = "__Secure-finace-delete"
PREFIX = "/conta/"
FILES = {"": "index.html", "app.html": "app-online.html", "conta.js": "conta.js",
         "conta.css": "conta.css", "privacidade.html": "privacidade.html",
         "exemplo-backup.json": "exemplo-backup.json", "favicon.svg": "favicon.svg",
         "suporte.html": "suporte.html", "politica.js": "politica.js",
         "excluir-conta.html": "excluir-conta.html", "excluir-conta.js": "excluir-conta.js"}


def session_cookie(name, value, age):
    jar = SimpleCookie()
    jar[name] = value
    cookie = jar[name]
    cookie["secure"] = True
    cookie["httponly"] = True
    cookie["samesite"] = "Strict"
    cookie["path"] = PREFIX
    cookie["max-age"] = age
    return cookie.OutputString()


def initial_wallet():
    return {"snapshot": 2, "revision": str(uuid.uuid4()), "carteira": [], "diario": {},
            "premissas": {"selic12": None, "ipca": 5.02, "atualizado": None}}


def online_auth():
    auth = SupabaseAuth.from_file(ROOT / ".env.local")
    if auth.has_config:
        return auth
    # A URL e a chave anon já integram o index público desta distribuição.
    source = (ROOT.parent.parent / "index.html").read_text()
    settings = [re.search(r"const SB_" + name + r"\s*=\s*'([^']+)'", source) for name in ("URL", "KEY")]
    return SupabaseAuth(*(m[1] for m in settings), otp_ready=True) if all(settings) else auth


class OnlineHandler(Handler):
    """Reusa o formato JSON e a validação do servidor da prévia."""
    def do_GET(self):
        self.serve_online()

    do_POST = do_GET
    do_PATCH = do_GET
    do_DELETE = do_GET

    def serve_online(self):
        self.cookies_to_set = []
        try:
            host = self.headers.get("Host", "")
            configured_hosts = os.environ.get("FINACE_ONLINE_HOSTS", "").split(",")
            configured_hosts.extend(os.environ.get(name, "") for name in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"))
            if not host or host not in {h.strip() for h in configured_hosts if h.strip()}:
                raise Error(403, "Endereço da carteira não autorizado.")
            self.origin = "https://" + host
            request = urlsplit(self.path)
            query = parse_qs(request.query, keep_blank_values=True)
            if request.path == PREFIX.rstrip("/"):
                path = ""
            elif request.path.startswith(PREFIX):
                path = request.path[len(PREFIX):]
            elif request.path == "/api/finace-conta":
                path = query.pop("finace_route", [""])[0]
            else:
                raise Error(404, "Página não encontrada.")
            if self.command != "GET" and (
                self.headers.get("Origin") != self.origin or self.headers.get("X-Prototype") != "local"
            ):
                raise Error(403, "Origem da solicitação recusada.")
            self.auth = online_auth()
            self.deletion = AccountDeletion(self.auth)
            self.cloud = CloudWallet(self.auth)
            environment = os.environ.get("VERCEL_ENV")
            if environment not in ("preview", "production"):
                raise Error(503, "Ambiente da carteira ainda não configurado.")
            self.production = environment == "production"
            if self.production:
                if os.environ.get("FINACE_ALLOW_LIVE_AUTH") != "true":
                    raise Error(503, "A nova carteira ainda não foi ativada neste endereço.")
                self.cloud.wallets = "finace_contas_carteiras"
                self.cloud.versions = "finace_contas_versoes"
            if path.startswith("api/"):
                body = self.request_body() if self.command != "GET" else {}
                if not isinstance(body, dict):
                    raise Error(400, "Formato da solicitação inválido.")
                self.send(200, self.online_api(path, query, body))
            else:
                self.online_page(path, query)
        except (AuthError, Error) as error:
            self.send(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send(500, {"error": "Não foi possível concluir a solicitação."})

    def send(self, status, data=None, headers=None, raw=False):
        headers = {"X-Robots-Tag": "noindex", **(headers or {})}
        super().send(status, data, headers, raw)

    def end_headers(self):
        for cookie in self.cookies_to_set:
            self.send_header("Set-Cookie", cookie)
        super().end_headers()

    def set_session(self, tokens):
        access, refresh, age = tokens
        self.session_refresh = refresh
        self.cookies_to_set = [session_cookie(ACCESS_COOKIE, access, age),
                               session_cookie(REFRESH_COOKIE, refresh, REFRESH_MAX_AGE)]

    def get_session(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            raise Error(401, "Entre na sua conta.")
        refresh = cookies.get(REFRESH_COOKIE)
        if not refresh:
            raise Error(401, "Entre na sua conta.")
        current = cookies.get(ACCESS_COOKIE)
        if current:
            try:
                user = self.auth.call("/user", access_token=current.value)
                return user, current.value
            except AuthError as error:
                if error.status != 401:
                    raise
        result = self.auth.call("/token?grant_type=refresh_token", {"refresh_token": refresh.value})
        tokens = self.auth.session_tokens(result)
        user = self.auth.call("/user", access_token=tokens[0])
        self.set_session(tokens)
        return user, tokens[0]

    def online_api(self, path, query, body):
        if path == "api/config" and self.command == "GET":
            return {"auth_mode": "supabase", "configured": self.auth.configured,
                    "cloud_wallet": True, "online_wallet": True, "production_wallet": self.production, "resend_seconds": 60,
                    "account_deletion_available": self.deletion.available,
                    "site": site_information(), "preview": not self.production}
        if path == "api/account/deletion/request" and self.command == "POST":
            self.deletion.require_available()
            email = normalize_email(body.get("email"))
            self.auth.request_code(email, create_user=False)
            self.cookies_to_set.append(session_cookie(DELETION_COOKIE, "", 0))
            return {"challenge": email, "simulated": False}
        if path == "api/account/deletion/verify" and self.command == "POST":
            self.deletion.require_available()
            identity = self.auth.verify_code(normalize_email(body.get("challenge")), body.get("code"), include_tokens=True)
            self.set_session(identity["tokens"])
            proof = self.deletion.proof(identity["id"], identity["tokens"][1])
            self.cookies_to_set.append(session_cookie(DELETION_COOKIE, proof, PROOF_SECONDS))
            return {"verified_for_deletion": True}
        if path == "api/auth/request" and self.command == "POST":
            if body.get("purpose") == "delete":
                self.deletion.require_available()
                user, _ = self.get_session()
                if normalize_email(body.get("email")) != user["email"]:
                    raise Error(403, "Confirme o e-mail da sua própria conta.")
                self.auth.request_code(user["email"], create_user=False)
                self.cookies_to_set.append(session_cookie(DELETION_COOKIE, "", 0))
                return {"challenge": user["email"], "simulated": False}
            if body.get("purpose", "login") != "login":
                raise Error(400, "Finalidade inválida.")
            email = normalize_email(body.get("email"))
            self.auth.request_code(email)
            # O Supabase associa o código ao e-mail e limita o reenvio.
            return {"challenge": email, "simulated": False}
        if path == "api/auth/verify" and self.command == "POST":
            if body.get("purpose") == "delete":
                self.deletion.require_available()
                current, _ = self.get_session()
                identity = self.auth.verify_code(normalize_email(body.get("challenge")), body.get("code"))
                if identity["id"] != current["id"] or identity["email"] != current["email"]:
                    raise Error(403, "A confirmação não corresponde à sua conta.")
                refresh = getattr(self, "session_refresh", None) or SimpleCookie(self.headers.get("Cookie", ""))[REFRESH_COOKIE].value
                proof = self.deletion.proof(current["id"], refresh)
                self.cookies_to_set.append(session_cookie(DELETION_COOKIE, proof, PROOF_SECONDS))
                return {"verified_for_deletion": True}
            if body.get("purpose", "login") != "login":
                raise Error(400, "Finalidade inválida.")
            identity = self.auth.verify_code(normalize_email(body.get("challenge")), body.get("code"), include_tokens=True)
            self.cloud.ensure_wallet(identity["tokens"][0], initial_wallet())
            self.set_session(identity["tokens"])
            return {"ok": True}
        if path == "api/auth/logout" and self.command == "POST":
            try:
                _, token = self.get_session()
                self.auth.call("/logout?scope=local", {}, token)
            except AuthError as error:
                if error.status != 401:
                    raise
            except Error as error:
                if error.status != 401:
                    raise
            self.cookies_to_set = [session_cookie(ACCESS_COOKIE, "", 0), session_cookie(REFRESH_COOKIE, "", 0)]
            self.cookies_to_set.append(session_cookie(DELETION_COOKIE, "", 0))
            return {"ok": True}
        user, token = self.get_session()
        owner, email = str(uuid.UUID(user["id"])), user["email"]
        if path == "api/account/delete" and self.command == "POST":
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            if body.get("confirmation") != "EXCLUIR":
                raise Error(403, "Digite EXCLUIR para confirmar.")
            proof = cookies.get(DELETION_COOKIE)
            self.deletion.validate(proof.value if proof else "", owner, cookies[REFRESH_COOKIE].value)
            # A exclusão de auth.users remove a carteira e suas versões pelas FKs em cascata.
            self.auth.call("/logout?scope=global", {}, token)
            self.deletion.delete(owner)
            self.cookies_to_set = [session_cookie(name, "", 0)
                                   for name in (ACCESS_COOKIE, REFRESH_COOKIE, DELETION_COOKIE)]
            return {"ok": True}
        if path == "api/session" and self.command == "GET":
            return {"user": {"id": owner, "email": email}, "invites": [], "wallets": [
                {"id": owner, "name": "Minha carteira", "owner_email": email, "role": "owner"}
            ]}
        if self.headers.get("X-Wallet") != owner:
            raise Error(403, "Esta conta não tem acesso a esta carteira.")
        if path == "api/sharing" and self.command == "GET":
            return {"role": "owner", "members": [], "invites": []}
        if path == "api/versions" and self.command == "GET":
            versions = self.cloud.history(token, owner)
            for version in versions:
                version["reason"] = "Antes de uma alteração na carteira"
            return {"versions": versions}
        if path == "api/versions/restore" and self.command == "POST":
            version = checked_uuid(body.get("version"))
            revision = checked_uuid(body.get("revision"))
            previous = self.cloud.old_snapshot(token, owner, version)
            if previous is None:
                raise Error(404, "Versão não encontrada.")
            prefs = valid_prefs(previous)
            prefs["revision"] = str(uuid.uuid4())
            if not self.cloud.save(token, owner, revision, prefs):
                raise Error(409, "A carteira mudou. Atualize antes de restaurar.")
            return {"ok": True}
        if path != "api/app/carteiras":
            raise Error(404, "Recurso indisponível.")
        if query.get("id") != ["eq." + owner]:
            raise Error(403, "Consulta fora da carteira autenticada recusada.")
        if self.command == "GET":
            return [{"id": owner, "prefs": self.cloud.snapshot(token, owner)}]
        if self.command != "PATCH" or body.get("id") != owner:
            raise Error(403, "Alteração fora da carteira autenticada recusada.")
        revision = query.get("prefs->>revision", [""])[0]
        if not revision.startswith("eq."):
            raise Error(400, "Revisão inválida.")
        prefs = valid_prefs(body.get("prefs"))
        saved = self.cloud.save(token, owner, checked_uuid(revision[3:]), prefs)
        return [{"id": owner, "prefs": prefs}] if saved else []

    def online_page(self, path, query):
        if self.command != "GET" or path not in FILES:
            raise Error(404, "Página não encontrada.")
        file = ROOT / "web" / FILES[path]
        if path == "favicon.svg" and not file.is_file():
            file = ROOT.parent.parent / "favicon.svg"
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        raw = file.read_bytes()
        hashes = []
        if content_type in ("text/html", "text/javascript", "application/javascript"):
            contents = raw.decode()
            if path == "app.html":
                user, _ = self.get_session()
                if query.get("wallet") != [user["id"]]:
                    raise Error(403, "Esta conta não tem acesso a esta carteira.")
                boot = {"user": user["id"], "email": user["email"], "wallet": user["id"], "role": "owner"}
                contents = contents.replace("/*__PROTOTYPE_BOOT__*/null", json.dumps(boot).replace("<", "\\u003c"))
            else:
                contents = re.sub(r'''(["'])/(api/|app\.html|conta\.css|conta\.js|privacidade\.html|exemplo-backup\.json|favicon\.svg)''',
                                  r"\1/conta/\2", contents)
                contents = re.sub(r'''(["'])/(suporte\.html|publicacao\.html|politica\.js|excluir-conta\.html|excluir-conta\.js)''',
                                  r"\1/conta/\2", contents)
                contents = contents.replace('href="/"', 'href="/conta/"')
                contents = contents.replace("finace-teste:", "finace-conta:")
                if path == "":
                    contents = contents.replace("PRÉVIA LOCAL", "CONTA FINACE" if self.production else "PRÉVIA ONLINE")
                    contents = contents.replace("Prévia local · e-mails e taxas simulados", "Finace · Conta e dados")
                    contents = contents.replace("AMBIENTE DE TESTE · SEM CONEXÃO COM O APP PUBLICADO",
                                                 "CARTEIRA PESSOAL" if self.production else "AMBIENTE DE TESTE")
                if path == "privacidade.html":
                    contents = contents.replace(
                        "As aplicações desta prévia ficam em um banco SQLite separado, neste computador. Elas não são gravadas nas tabelas de carteiras do Supabase.",
                        "As aplicações ficam no Supabase, em uma carteira vinculada à sua conta.",
                    ).replace(
                        "Os tokens recebidos do Supabase não são enviados ao navegador da prévia nem guardados no armazenamento do navegador.",
                        "O navegador mantém a sessão em cookies protegidos, inacessíveis ao JavaScript.",
                    ).replace(
                        "O servidor cria uma sessão local em cookie HttpOnly válida por 30 dias e renova o prazo automaticamente com o uso. Sair da conta encerra essa sessão local.",
                        "A sessão é renovada com o uso e pode ser encerrada pelo botão Sair.",
                    )
            if content_type == "text/html":
                for script in re.findall(r"<script>([\s\S]*?)</script>", contents):
                    hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'")
            raw = contents.encode()
        scripts = " ".join(["'self'", *hashes])
        policy = (
            f"default-src 'self'; script-src {scripts}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self' https://api.bcb.gov.br; "
            "frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'; object-src 'none'"
        )
        self.send(200, raw, {"Content-Type": content_type + "; charset=utf-8", "Content-Security-Policy": policy}, raw=True)


def checked_uuid(value):
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise Error(400, "Identificador inválido.") from None
