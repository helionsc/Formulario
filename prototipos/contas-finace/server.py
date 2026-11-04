"""Protótipo local. Sem e-mail real, Supabase ou conexão externa."""
import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import http.cookies
import json
import math
import mimetypes
import re
import secrets
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from auth_supabase import AuthError, SupabaseAuth, normalize_email
from carteira_nuvem import CloudWallet

ROOT = Path(__file__).resolve().parent
EMAIL = re.compile(r"^[a-z0-9.!#$%&*+/=?^_`{|}~-]+@[a-z0-9.-]+\.test$")
MAX_BODY = 20_000_000
SESSION_MAX_AGE = 30 * 24 * 60 * 60
SESSION_RENEW_INTERVAL = 60 * 60


class Error(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def email_value(raw):
    value = str(raw or "").strip().lower()
    if len(value) > 180 or not EMAIL.fullmatch(value):
        raise Error(400, "Use um endereço fictício terminado em .test.")
    return value


def valid_prefs(prefs):
    if not isinstance(prefs, dict) or prefs.get("snapshot") != 2:
        raise Error(400, "Formato de carteira inválido.")
    try:
        uuid.UUID(prefs["revision"])
        positions = prefs["carteira"]
        if not isinstance(positions, list) or len(positions) > 10000:
            raise ValueError()
        ids = set()
        for p in positions:
            uuid.UUID(p["id"])
            if p["id"] in ids:
                raise ValueError()
            ids.add(p["id"])
            if not isinstance(p["banco"], str) or not 1 <= len(p["banco"].strip()) <= 80 or re.search(r'''[<>"'`\x00-\x1f]''', p["banco"]):
                raise ValueError()
            if p["tipo"] not in ["CDB", "RDB", "LCI", "LCA", "LC", "TESOURO", "CRI", "DEB", "POUP"] or p["index"] not in ["cdi", "selic", "selic_spread", "pre", "ipca"]:
                raise ValueError()
            for field, low, high in [("valor", 0, 1e12), ("taxa", -1e-100, 10000)]:
                n = float(p[field])
                if isinstance(p[field], bool) or not math.isfinite(n) or not low < n <= high:
                    raise ValueError()
            start = dt.date.fromisoformat(p["data"])
            if not dt.date(2000, 1, 1) <= start <= dt.date.today():
                raise ValueError()
            for field in ["venc", "car"]:
                if p.get(field) and not start <= dt.date.fromisoformat(p[field]) <= dt.date(2100, 12, 31):
                    raise ValueError()
            if p.get("car") and p.get("venc") and p["car"] > p["venc"]:
                raise ValueError()
            if p.get("g") and not re.fullmatch(r"[\w-]{1,90}", p["g"], re.ASCII):
                raise ValueError()
            for redemption in p.get("resg", []):
                if not start <= dt.date.fromisoformat(redemption["data"]) <= dt.date.today():
                    raise ValueError()
                for field, maximum in [("f", 1), ("bruto", 1e15), ("ir", 1e15)]:
                    n = float(redemption[field])
                    if not math.isfinite(n) or not 0 <= n <= maximum or (field == "f" and n == 0):
                        raise ValueError()
        if not isinstance(prefs.get("diario", {}), dict):
            raise ValueError()
        for day, record in prefs.get("diario", {}).items():
            dt.date.fromisoformat(day)
            if not isinstance(record, dict) or not isinstance(record.get("itens"), dict):
                raise ValueError()
            for key, item in record["itens"].items():
                if not re.fullmatch(r"[\w-]{1,90}", key, re.ASCII) or not isinstance(item, dict):
                    raise ValueError()
                if not isinstance(item.get("centavos"), int) or isinstance(item["centavos"], bool) or abs(item["centavos"]) > 1e15:
                    raise ValueError()
                if not isinstance(item.get("banco"), str) or len(item["banco"]) > 80:
                    raise ValueError()
        assumptions = prefs.get("premissas", {"selic12": None, "ipca": 5.02})
        ipca = float(assumptions["ipca"])
        selic = assumptions.get("selic12")
        if not math.isfinite(ipca) or not 0 <= ipca <= 50 or (selic is not None and (not math.isfinite(float(selic)) or not 0 <= float(selic) <= 60)):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        raise Error(400, "Confira aplicações, histórico e premissas do backup.")
    # Não deixa campos administrativos ou de outra conta entrarem no snapshot.
    return {key: prefs[key] for key in ["snapshot", "revision", "carteira", "diario", "oculto", "antecipa", "premissas", "extras"] if key in prefs}


class Store:
    def __init__(self, path, seed=True):
        self.path = str(path)
        self.secret = secrets.token_bytes(32)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS wallets(id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,prefs TEXT NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS members(wallet TEXT REFERENCES wallets(id) ON DELETE CASCADE,user TEXT REFERENCES users(id) ON DELETE CASCADE,PRIMARY KEY(wallet,user));
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user TEXT REFERENCES users(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires REAL NOT NULL,delete_until REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,email TEXT NOT NULL,purpose TEXT NOT NULL,code TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER DEFAULT 0,used INTEGER DEFAULT 0,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS invites(id TEXT PRIMARY KEY,wallet TEXT REFERENCES wallets(id) ON DELETE CASCADE,email TEXT NOT NULL,expires REAL NOT NULL,UNIQUE(wallet,email));
                CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,wallet TEXT REFERENCES wallets(id) ON DELETE CASCADE,prefs TEXT NOT NULL,created REAL NOT NULL,reason TEXT NOT NULL);
            """)
            if seed and not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                for email, value in [("ana@finace.test", 18000), ("bruno@finace.test", 6000)]:
                    user = self.make_user(db, email)
                    wallet = db.execute("SELECT * FROM wallets WHERE owner=?", (user,)).fetchone()
                    start = (dt.date.today() - dt.timedelta(days=42)).isoformat()
                    positions = [{"id": uid(), "banco": "Itaú Unibanco", "tipo": "CDB", "index": "cdi", "taxa": 102, "valor": value * .6, "data": start}, {"id": uid(), "banco": "Banco Inter", "tipo": "LCI", "index": "cdi", "taxa": 95, "valor": value * .4, "data": start}]
                    prefs = json.loads(wallet["prefs"])
                    prefs["carteira"] = positions
                    db.execute("UPDATE wallets SET prefs=? WHERE id=?", (json.dumps(prefs), wallet["id"]))

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def make_user(self, db, email, identity=None, wallet_id=None):
        user, wallet = identity or uid(), wallet_id or uid()
        prefs = {"snapshot": 2, "revision": uid(), "carteira": [], "diario": {}, "premissas": {"selic12": None, "ipca": 5.02, "atualizado": None}}
        db.execute("INSERT INTO users VALUES(?,?)", (user, email))
        db.execute("INSERT INTO wallets VALUES(?,?,?,?,?)", (wallet, user, "Minha carteira", json.dumps(prefs), time.time()))
        return user

    def otp_hash(self, challenge, code):
        return hmac.new(self.secret, (challenge + ":" + code).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def wallet(db, user, wallet):
        row = db.execute("SELECT w.* FROM wallets w WHERE w.id=? AND (w.owner=? OR EXISTS(SELECT 1 FROM members m WHERE m.wallet=w.id AND m.user=?))", (wallet, user, user)).fetchone()
        if not row:
            raise Error(403, "Esta conta não tem acesso a esta carteira.")
        return row

    @staticmethod
    def backup(db, wallet, reason):
        db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (uid(), wallet["id"], wallet["prefs"], time.time(), reason))
        db.execute("DELETE FROM versions WHERE wallet=? AND id NOT IN(SELECT id FROM versions WHERE wallet=? ORDER BY created DESC LIMIT 20)", (wallet["id"], wallet["id"]))


class Handler(BaseHTTPRequestHandler):
    server_version = "FinaceLocal/1"

    def log_message(self, *_):
        pass  # Não registra e-mails, códigos, cookies nem dados de carteiras.

    def send(self, status, data=None, headers=None, raw=False):
        body = data if raw else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        for key, value in {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'; object-src 'none'", **(headers or {})}.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def session(self, db):
        try:
            cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie[self.server.cookie_name].value
        except (KeyError, http.cookies.CookieError):
            raise Error(401, "Entre na sua conta de teste.")
        row = db.execute("SELECT s.*,u.email FROM sessions s JOIN users u ON u.id=s.user WHERE s.token=? AND s.expires>?", (digest(token), time.time())).fetchone()
        if not row:
            raise Error(401, "Sua sessão terminou. Entre novamente.")
        if self.command != "GET" and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), row["csrf"]):
            raise Error(403, "Reabra a página para confirmar sua sessão.")
        return row

    def issue_session(self, db, user, now, tokens=None):
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        old = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        cookie = self.server.cookie_name
        if cookie in old:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(old[cookie].value),))
        session_key = digest(token)
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,0)", (session_key, user, csrf, now + SESSION_MAX_AGE))
        if tokens is not None:
            self.server.cloud.remember_session(db, session_key, tokens, now)
        return {"ok": True}, self.session_cookie(token, SESSION_MAX_AGE)

    def session_cookie(self, token, max_age):
        name = self.server.cookie_name
        return {"Set-Cookie": f"{name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}"}

    def renew_session(self, db, session, now):
        expires = now + SESSION_MAX_AGE
        if session["expires"] > expires - SESSION_RENEW_INTERVAL:
            return {}
        # A sessão pode ter sido encerrada em outra aba após a leitura.
        updated = db.execute(
            "UPDATE sessions SET expires=? WHERE token=? AND expires>? AND expires<=?",
            (expires, session["token"], now, expires - SESSION_RENEW_INTERVAL),
        )
        if updated.rowcount == 0:
            return {}
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return self.session_cookie(cookies[self.server.cookie_name].value, SESSION_MAX_AGE)

    def email(self, value):
        return normalize_email(value) if self.server.auth_mode == "supabase" else email_value(value)

    def request_body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_BODY:
                raise Error(413, "Arquivo maior que 20 MB.")
            if size <= 0:
                return {}
            data = json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(data, (dict, list)):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise Error(400, "JSON inválido.")

    def handle_request(self):
        try:
            host = self.headers.get("Host", "")
            allowed = f"127.0.0.1:{self.server.server_port}"
            if host != allowed:
                raise Error(403, "A prévia funciona somente no endereço local informado.")
            self.origin = "http://" + allowed
            path = urlsplit(self.path)
            query = parse_qs(path.query)
            if self.command != "GET":
                if self.headers.get("Origin") != self.origin or self.headers.get("X-Prototype") != "local":
                    raise Error(403, "Origem da solicitação recusada.")
            body = self.request_body() if self.command != "GET" else {}
            with self.server.store.db() as db:
                # Uma transação serializa comparação de revisão, concessões e exclusões.
                if self.command != "GET":
                    db.execute("BEGIN IMMEDIATE")
                result, headers = self.route(db, path.path, query, body)
            if headers is not None:
                self.send(200, result, headers)
        except Error as e:
            self.send(e.status, {"error": e.message})
        except AuthError as e:
            self.send(e.status, {"error": e.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send(500, {"error": "Não foi possível concluir. Os dados confirmados foram preservados."})

    def route(self, db, path, query, body):
        now = time.time()
        real_auth = self.server.auth_mode == "supabase"
        cloud = self.server.cloud
        if path == "/api/config" and self.command == "GET":
            return {"auth_mode": self.server.auth_mode, "cloud_wallet": cloud is not None,
                    "configured": not real_auth or self.server.auth_provider.configured,
                    "otp_digits": 6, "otp_seconds": 300, "resend_seconds": 60 if real_auth else 0,
                    "account_deletion_available": not real_auth}, {}
        if path == "/api/auth/request" and self.command == "POST":
            email = self.email(body.get("email"))
            purpose = body.get("purpose", "login")
            if purpose not in ["login", "delete"]:
                raise Error(400, "Finalidade inválida.")
            if purpose == "delete" and self.session(db)["email"] != email:
                raise Error(403, "Confirme o e-mail da sua própria conta.")
            recent = db.execute("SELECT COUNT(*) FROM challenges WHERE email=? AND created>?", (email, now - 60)).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM challenges WHERE created>?", (now - 60,)).fetchone()[0]
            if recent >= 5 or total >= 60:
                raise Error(429, "Aguarde um minuto antes de pedir outro código.")
            if real_auth:
                last = db.execute("SELECT MAX(created) FROM challenges WHERE email=?", (email,)).fetchone()[0]
                if last and now - last < 60:
                    raise Error(429, "Aguarde um minuto antes de pedir outro código.")
                self.server.auth_provider.request_code(email, create_user=purpose == "login")
                db.execute("UPDATE challenges SET used=1 WHERE email=? AND purpose=?", (email, purpose))
                challenge = secrets.token_urlsafe(32)
                db.execute("INSERT INTO challenges VALUES(?,?,?,?,?,0,0,?)", (challenge, email, purpose, "supabase", now + 300, now))
                return {"challenge": challenge, "expires_in": 300, "simulated": False, "delivery": "email"}, {}
            db.execute("UPDATE challenges SET used=1 WHERE email=? AND purpose=?", (email, purpose))
            challenge, code = secrets.token_urlsafe(32), f"{secrets.randbelow(1000000):06d}"
            db.execute("INSERT INTO challenges VALUES(?,?,?,?,?,0,0,?)", (challenge, email, purpose, self.server.store.otp_hash(challenge, code), now + 300, now))
            return {"challenge": challenge, "demo_code": code, "expires_in": 300, "simulated": True}, {}
        if path == "/api/auth/verify" and self.command == "POST":
            challenge, code = str(body.get("challenge", "")), str(body.get("code", ""))
            row = db.execute("SELECT * FROM challenges WHERE id=?", (challenge,)).fetchone()
            if not row or row["used"] or row["expires"] < now or row["attempts"] >= 5:
                raise Error(400, "Código expirado ou já utilizado. Peça um novo.")
            if real_auth:
                try:
                    identity = self.server.auth_provider.verify_code(row["email"], code, include_tokens=cloud is not None)
                except AuthError as error:
                    if error.status == 400:
                        db.execute("UPDATE challenges SET attempts=attempts+1 WHERE id=?", (challenge,))
                        db.commit()
                    raise
                if row["purpose"] == "delete":
                    current = self.session(db)
                    if current["user"] != identity["id"] or current["email"] != identity["email"]:
                        raise Error(403, "A confirmação não corresponde à sua conta.")
                    db.execute("UPDATE sessions SET delete_until=? WHERE token=?", (now + 300, current["token"]))
                    result, headers = {"verified_for_deletion": True}, {}
                else:
                    existing = db.execute("SELECT id FROM users WHERE email=?", (identity["email"],)).fetchone()
                    if existing and existing["id"] != identity["id"]:
                        raise Error(409, "Este e-mail está vinculado a outra identidade. A carteira foi preservada para revisão.")
                    known = db.execute("SELECT id FROM users WHERE id=?", (identity["id"],)).fetchone()
                    if not known:
                        wallet_id = identity["id"] if cloud else None
                        self.server.store.make_user(db, identity["email"], identity["id"], wallet_id)
                    else:
                        db.execute("UPDATE users SET email=? WHERE id=?", (identity["email"], identity["id"]))
                    tokens = identity.get("tokens")
                    if cloud:
                        prefs = db.execute("SELECT prefs FROM wallets WHERE id=? AND owner=?",
                                           (identity["id"], identity["id"])).fetchone()
                        cloud.ensure_wallet(tokens[0], json.loads(prefs["prefs"]))
                        db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
                    result, headers = self.issue_session(db, identity["id"], now, tokens)
                db.execute("UPDATE challenges SET used=1 WHERE id=?", (challenge,))
                return result, headers
            if not hmac.compare_digest(row["code"], self.server.store.otp_hash(challenge, code)):
                db.execute("UPDATE challenges SET attempts=attempts+1 WHERE id=?", (challenge,))
                db.commit()  # A tentativa inválida também precisa persistir.
                raise Error(400, "Código incorreto. Confira os seis números.")
            if row["purpose"] == "delete":
                session = self.session(db)
                if session["email"] != row["email"]:
                    raise Error(403, "Código de outra conta recusado.")
                db.execute("UPDATE sessions SET delete_until=? WHERE token=?", (now + 300, session["token"]))
                result, headers = {"verified_for_deletion": True}, {}
            else:
                user = db.execute("SELECT id FROM users WHERE email=?", (row["email"],)).fetchone()
                user = user[0] if user else self.server.store.make_user(db, row["email"])
                result, headers = self.issue_session(db, user, now)
            db.execute("UPDATE challenges SET used=1 WHERE id=?", (challenge,))
            return result, headers

        if path.startswith("/api/"):
            session = self.session(db)
            user = session["user"]
            if path == "/api/session" and self.command == "GET":
                wallets = db.execute("SELECT w.id,w.name,w.updated,u.email AS owner_email,CASE WHEN w.owner=? THEN 'owner' ELSE 'editor' END AS role FROM wallets w JOIN users u ON u.id=w.owner WHERE w.owner=? OR EXISTS(SELECT 1 FROM members m WHERE m.wallet=w.id AND m.user=?) ORDER BY role DESC,w.name", (user, user, user)).fetchall()
                invites = db.execute("SELECT i.id,w.name,u.email AS sender FROM invites i JOIN wallets w ON w.id=i.wallet JOIN users u ON u.id=w.owner WHERE i.email=? AND i.expires>?", (session["email"], now)).fetchall()
                return {"user": {"id": user, "email": session["email"]}, "csrf": session["csrf"], "wallets": [dict(w) for w in wallets], "invites": [dict(i) for i in invites], "prototype": True}, self.renew_session(db, session, now)
            if path == "/api/auth/logout" and self.command == "POST":
                db.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
                return {"ok": True}, self.session_cookie("", 0)
            if path == "/api/account/delete" and self.command == "POST":
                if real_auth:
                    raise Error(503, "A exclusão da conta real ainda precisa ser conectada ao serviço de autenticação. Nenhum dado foi apagado.")
                if session["delete_until"] < now or body.get("confirmation") != "EXCLUIR":
                    raise Error(403, "Confirme o código e digite EXCLUIR para apagar sua conta de teste.")
                db.execute("DELETE FROM invites WHERE email=?", (session["email"],))
                db.execute("DELETE FROM challenges WHERE email=?", (session["email"],))
                db.execute("DELETE FROM users WHERE id=?", (user,))
                return {"ok": True}, self.session_cookie("", 0)
            if cloud:
                return self.cloud_route(db, session, path, query, body)
            if path == "/api/invites/accept" and self.command == "POST":
                invite = db.execute("SELECT * FROM invites WHERE id=? AND email=? AND expires>?", (body.get("invite"), session["email"], now)).fetchone()
                if not invite:
                    raise Error(403, "Convite indisponível para esta conta.")
                db.execute("INSERT OR IGNORE INTO members VALUES(?,?)", (invite["wallet"], user))
                db.execute("DELETE FROM invites WHERE id=?", (invite["id"],))
                return {"wallet": invite["wallet"]}, {}

            wallet_id = self.headers.get("X-Wallet", "")
            wallet = self.server.store.wallet(db, user, wallet_id)
            owner = wallet["owner"] == user
            if path == "/api/sharing" and self.command == "GET":
                if not owner:
                    return {"role": "editor", "members": [], "invites": []}, {}
                members = db.execute("SELECT u.id,u.email FROM members m JOIN users u ON u.id=m.user WHERE m.wallet=?", (wallet_id,)).fetchall()
                invites = db.execute("SELECT id,email FROM invites WHERE wallet=? AND expires>?", (wallet_id, now)).fetchall()
                return {"role": "owner", "members": [dict(r) for r in members], "invites": [dict(r) for r in invites]}, {}
            if path == "/api/sharing/invite" and self.command == "POST":
                if not owner:
                    raise Error(403, "Somente o proprietário pode convidar pessoas.")
                email = self.email(body.get("email"))
                if email == session["email"]:
                    raise Error(400, "Sua conta já é proprietária desta carteira.")
                existing = db.execute("SELECT 1 FROM members m JOIN users u ON u.id=m.user WHERE m.wallet=? AND u.email=?", (wallet_id, email)).fetchone()
                if existing:
                    raise Error(400, "Esta conta já participa da carteira.")
                db.execute("INSERT INTO invites VALUES(?,?,?,?) ON CONFLICT(wallet,email) DO UPDATE SET id=excluded.id,expires=excluded.expires", (uid(), wallet_id, email, now + 172800))
                return {"ok": True, "simulated": True}, {}
            if path == "/api/sharing/revoke" and self.command == "POST":
                if not owner:
                    raise Error(403, "Somente o proprietário pode remover acessos.")
                db.execute("DELETE FROM members WHERE wallet=? AND user=?", (wallet_id, body.get("member")))
                db.execute("DELETE FROM invites WHERE wallet=? AND id=?", (wallet_id, body.get("invite")))
                return {"ok": True}, {}
            if path == "/api/versions" and self.command == "GET":
                rows = db.execute("SELECT id,created,reason FROM versions WHERE wallet=? ORDER BY created DESC LIMIT 20", (wallet_id,)).fetchall()
                return {"versions": [dict(r) for r in rows]}, {}
            if path == "/api/versions/restore" and self.command == "POST":
                if not owner:
                    raise Error(403, "Somente o proprietário pode restaurar versões do servidor.")
                version = db.execute("SELECT * FROM versions WHERE id=? AND wallet=?", (body.get("version"), wallet_id)).fetchone()
                if not version:
                    raise Error(404, "Versão não encontrada nesta carteira.")
                if json.loads(wallet["prefs"])["revision"] != body.get("revision"):
                    raise Error(409, "A carteira mudou. Atualize a página antes de restaurar.")
                self.server.store.backup(db, wallet, "Antes de restaurar uma versão")
                prefs = json.loads(version["prefs"])
                prefs["revision"] = uid()
                db.execute("UPDATE wallets SET prefs=?,updated=? WHERE id=?", (json.dumps(prefs), now, wallet_id))
                return {"ok": True}, {}
            if path == "/api/app/carteiras":
                if self.command == "GET":
                    if query.get("id") != ["eq." + wallet_id]:
                        raise Error(403, "Consulta fora da carteira autenticada recusada.")
                    return [{"id": wallet_id, "prefs": json.loads(wallet["prefs"])}], {}
                if self.command == "PATCH":
                    if query.get("id") != ["eq." + wallet_id] or not isinstance(body, dict) or body.get("id") != wallet_id:
                        raise Error(403, "Alteração fora da carteira autenticada recusada.")
                    if set(body) - {"id", "prefs", "visto_em"}:
                        raise Error(400, "Campos administrativos não podem ser alterados pelo app.")
                    current = json.loads(wallet["prefs"])
                    if query.get("prefs->>revision") != ["eq." + current["revision"]]:
                        return [], {}  # Mesmo protocolo de conflito da versão atual.
                    prefs = valid_prefs(body.get("prefs"))
                    self.server.store.backup(db, wallet, "Antes de uma alteração")
                    db.execute("UPDATE wallets SET prefs=?,updated=? WHERE id=?", (json.dumps(prefs), now, wallet_id))
                    return [{"id": wallet_id, "prefs": prefs}], {}
                raise Error(405, "Carteiras são criadas e vinculadas pela conta autenticada.")
            raise Error(404, "Recurso indisponível.")

        if self.command != "GET":
            raise Error(404, "Página não encontrada.")
        if path == "/app.html":
            session = self.session(db)
            wallet = self.server.store.wallet(db, session["user"], query.get("wallet", [""])[0])
            html = (ROOT / "web" / "app.html").read_text()
            if cloud:
                html = html.replace("PRÉVIA LOCAL", "PRÉVIA · CARTEIRA NA NUVEM")
                html = html.replace("Nesta prévia, os dados ficam somente neste computador.",
                                    "Nesta prévia, a carteira de teste fica vinculada à sua conta.")
            owner_email = db.execute("SELECT email FROM users WHERE id=?", (wallet["owner"],)).fetchone()[0]
            boot = json.dumps({"user": session["user"], "email": session["email"], "wallet": wallet["id"], "owner_email": owner_email, "role": "owner" if wallet["owner"] == session["user"] else "editor", "csrf": session["csrf"]}, ensure_ascii=True).replace("<", "\\u003c")
            self.send(200, html.replace("/*__PROTOTYPE_BOOT__*/null", boot).encode(), {"Content-Type": "text/html; charset=utf-8"}, raw=True)
            return None, None
        files = {"/": "index.html", "/index.html": "index.html", "/conta.js": "conta.js", "/conta.css": "conta.css", "/favicon.svg": "favicon.svg", "/apple-touch-icon.png": "apple-touch-icon.png", "/privacidade.html": "privacidade.html", "/exemplo-backup.json": "exemplo-backup.json"}
        if path not in files:
            raise Error(404, "Página não encontrada.")
        file = ROOT / "web" / files[path]
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        contents = file.read_bytes()
        if cloud and path == "/privacidade.html":
            contents = contents.decode().replace(
                "As aplicações desta prévia ficam em um banco SQLite separado, neste computador. Elas não são gravadas nas tabelas de carteiras do Supabase.",
                "As aplicações desta prévia ficam em tabelas de teste no Supabase, separadas das carteiras do app publicado."
            ).replace(
                "Os tokens recebidos do Supabase não são enviados ao navegador da prévia nem guardados no armazenamento do navegador.",
                "Os tokens do Supabase ficam no servidor da prévia. O navegador recebe somente o cookie de sessão."
            ).encode()
        self.send(200, contents, {"Content-Type": content_type + ("; charset=utf-8" if content_type.startswith("text/") else "")}, raw=True)
        return None, None

    def do_GET(self):
        self.handle_request()

    do_POST = do_GET
    do_PATCH = do_GET
    do_DELETE = do_GET

    def cloud_route(self, db, session, path, query, body):
        owner = session["user"]
        if self.headers.get("X-Wallet") != owner:
            raise Error(403, "Esta conta não tem acesso a esta carteira de teste.")
        cloud = self.server.cloud
        if path == "/api/sharing" and self.command == "GET":
            return {"role": "owner", "members": [], "invites": []}, {}
        if path == "/api/versions" and self.command == "GET":
            return {"versions": cloud.history(cloud.access(db, session), owner)}, {}
        if path == "/api/versions/restore" and self.command == "POST":
            if not isinstance(body, dict) or not all(isinstance(body.get(key), str) for key in ("version", "revision")):
                raise Error(400, "Informe a versão e a revisão da carteira.")
            token = cloud.access(db, session)
            previous = cloud.old_snapshot(token, owner, body["version"])
            if previous is None:
                raise Error(404, "Versão não encontrada nesta carteira.")
            prefs = valid_prefs(previous)
            prefs["revision"] = uid()
            if not cloud.save(token, owner, body["revision"], prefs):
                raise Error(409, "A carteira mudou. Atualize a página antes de restaurar.")
            return {"ok": True}, {}
        if path != "/api/app/carteiras":
            raise Error(404, "Recurso indisponível nesta prévia.")
        if query.get("id") != ["eq." + owner]:
            raise Error(403, "Consulta fora da carteira autenticada recusada.")
        if self.command == "GET":
            return [{"id": owner, "prefs": cloud.snapshot(cloud.access(db, session), owner)}], {}
        if self.command != "PATCH":
            raise Error(405, "Operação indisponível para esta carteira.")
        if not isinstance(body, dict) or body.get("id") != owner or set(body) - {"id", "prefs", "visto_em"}:
            raise Error(400, "Formato de atualização da carteira inválido.")
        revision = query.get("prefs->>revision", [""])[0]
        try:
            if not revision.startswith("eq.") or str(uuid.UUID(revision[3:])) != revision[3:]:
                raise ValueError()
        except ValueError:
            raise Error(400, "Revisão inválida.")
        prefs = valid_prefs(body.get("prefs"))
        saved = cloud.save(cloud.access(db, session), owner, revision[3:], prefs)
        return ([{"id": owner, "prefs": prefs}] if saved else []), {}


def create_server(port=8768, db_path=None, seed=True, auth_mode="supabase", auth_provider=None, cloud_wallet=False):
    if auth_mode not in ["demo", "supabase"]:
        raise ValueError("Modo de autenticação inválido.")
    if cloud_wallet and auth_mode != "supabase":
        raise ValueError("A carteira na nuvem exige login real.")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.auth_mode = auth_mode
    server.auth_provider = auth_provider or SupabaseAuth.from_file(ROOT / ".env.local")
    server.cloud = CloudWallet(server.auth_provider) if cloud_wallet else None
    server.cookie_name = "finace_real" if auth_mode == "supabase" else "finace_demo"
    database = "auth-real.sqlite3" if auth_mode == "supabase" else "teste.sqlite3"
    if cloud_wallet:
        server.cookie_name = "finace_nuvem_teste"
        if db_path is None:
            directory = ROOT / "dados-locais" / "nuvem"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)
            db_path = directory / "sessoes.sqlite3"
        db_path = Path(db_path)
        db_path.touch(mode=0o600, exist_ok=True)
        db_path.chmod(0o600)
    server.store = Store(db_path or ROOT / "dados-locais" / database, seed and auth_mode == "demo")
    if cloud_wallet:
        with server.store.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cloud_sessions(
                token TEXT PRIMARY KEY REFERENCES sessions(token) ON DELETE CASCADE,
                access TEXT NOT NULL, refresh TEXT NOT NULL, expires REAL NOT NULL
            )""")
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--auth", choices=["supabase", "demo"], default="supabase")
    parser.add_argument("--cloud-wallet", action="store_true")
    args = parser.parse_args()
    server = create_server(args.port, auth_mode=args.auth, cloud_wallet=args.cloud_wallet)
    print(f"Protótipo local: http://127.0.0.1:{server.server_port}/", flush=True)
    print("Autenticação: " + ("Supabase OTP real" if args.auth == "supabase" else "demonstração .test sem envio de e-mail"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
