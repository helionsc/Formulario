"""Acesso à carteira de teste com o token do próprio usuário e RLS."""
import datetime as dt
import time
import urllib.error
from urllib.parse import urlencode

from auth_supabase import AuthError, request_json


class CloudWallet:
    wallets = "finace_previa_carteiras"
    versions = "finace_previa_versoes"

    def __init__(self, auth):
        self.auth = auth

    def call(self, table, token, query, *, method="GET", payload=None, prefer=None):
        headers = {"apikey": self.auth.public_key, "Authorization": "Bearer " + token,
                   "Content-Type": "application/json", "Accept": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self.auth.url}/rest/v1/{table}?{urlencode(query)}"
        try:
            return request_json(url, headers, payload, method, limit=21_000_000)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise AuthError(401, "Sua sessão terminou. Entre novamente.") from None
            if error.code == 403:
                raise AuthError(403, "Você não tem acesso a esta carteira de teste.") from None
            if error.code in (400, 413, 422):
                raise AuthError(400, "O Supabase recusou o formato ou o tamanho dos dados.") from None
            raise AuthError(503, "A carteira de teste na nuvem está indisponível.") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise AuthError(503, "A carteira de teste na nuvem está indisponível.") from None

    def remember_session(self, db, session, tokens, now):
        access, refresh, lifetime = tokens
        db.execute(
            """INSERT INTO cloud_sessions(token, access, refresh, expires) VALUES(?,?,?,?)
               ON CONFLICT(token) DO UPDATE SET access=excluded.access,
               refresh=excluded.refresh,expires=excluded.expires""",
            (session, access, refresh, now + lifetime),
        )

    def access(self, db, session):
        query = "SELECT access,refresh,expires FROM cloud_sessions WHERE token=?"
        now = time.time()
        tokens = db.execute(query, (session["token"],)).fetchone()
        if tokens is not None and tokens["expires"] > now + 30:
            return tokens["access"]
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        tokens = db.execute(query, (session["token"],)).fetchone()
        if tokens is None:
            raise AuthError(401, "Sua sessão terminou. Entre novamente.")
        if tokens["expires"] <= now + 30:
            new_tokens = self.auth.refresh(tokens["refresh"], session["user"])
            self.remember_session(db, session["token"], new_tokens, now)
            # A rotação precisa sobreviver a uma falha posterior da API de carteiras.
            db.commit()
            return new_tokens[0]
        return tokens["access"]

    def ensure_wallet(self, token, prefs):
        self.call(self.wallets, token, {"on_conflict": "owner_id"},
                  method="POST", payload={"prefs": prefs}, prefer="resolution=ignore-duplicates,return=minimal")

    def snapshot(self, token, owner):
        rows = self.call(self.wallets, token, {"owner_id": "eq." + owner, "select": "prefs"})
        if not rows:
            raise AuthError(503, "Não encontramos a carteira de teste desta conta.")
        return rows[0]["prefs"]

    def save(self, token, owner, revision, prefs):
        return bool(self.call(
            self.wallets, token,
            {"owner_id": "eq." + owner, "prefs->>revision": "eq." + revision, "select": "owner_id"},
            method="PATCH", payload={"prefs": prefs}, prefer="return=representation",
        ))

    def history(self, token, owner):
        rows = self.call(self.versions, token, {
            "owner_id": "eq." + owner, "select": "id,created_at", "order": "created_at.desc,id.desc", "limit": "20",
        })
        return [
            {"id": row["id"], "created": dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).timestamp(),
             "reason": "Antes de uma alteração na carteira de teste"}
            for row in rows
        ]

    def old_snapshot(self, token, owner, version):
        rows = self.call(self.versions, token, {"owner_id": "eq." + owner, "id": "eq." + version, "select": "prefs"})
        return rows[0]["prefs"] if rows else None
