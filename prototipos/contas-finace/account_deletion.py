"""Exclusão da própria identidade, autorizada por uma confirmação recente."""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import uuid

from auth_supabase import AuthError, request_json

PROOF_SECONDS = 300


class AccountDeletion:
    def __init__(self, auth):
        self.auth = auth
        self.secret = os.environ.get("FINACE_SUPABASE_SECRET_KEY", "")
        secret_is_private = self.secret.startswith("sb_secret_")
        if self.secret.startswith("eyJ"):
            try:
                payload = self.secret.split(".")[1]
                secret_is_private = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role") == "service_role"
            except (ValueError, IndexError, TypeError):
                secret_is_private = False
        self.available = bool(
            secret_is_private and auth.has_config and os.environ.get("FINACE_ACCOUNT_DELETION_READY") == "true"
        )

    def require_available(self):
        if not self.available:
            raise AuthError(503, "A exclusão de conta aguarda a configuração do servidor.")

    def proof(self, owner, refresh_token):
        self.require_available()
        payload = json.dumps({"owner": str(uuid.UUID(owner)),
                              "session": hashlib.sha256(refresh_token.encode()).hexdigest(),
                              "expires": int(time.time()) + PROOF_SECONDS}, sort_keys=True)
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        signature = hmac.new(self.secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        return encoded + "." + signature

    def validate(self, proof, owner, refresh_token):
        self.require_available()
        try:
            encoded, signature = proof.split(".")
            expected = hmac.new(self.secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            valid = (hmac.compare_digest(signature, expected)
                     and payload["owner"] == owner
                     and payload["session"] == hashlib.sha256(refresh_token.encode()).hexdigest()
                     and time.time() < payload["expires"] <= time.time() + PROOF_SECONDS)
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            raise AuthError(403, "Confirme sua identidade novamente antes de excluir a conta.")

    def delete(self, owner):
        self.require_available()
        owner = str(uuid.UUID(owner))
        headers = {"apikey": self.secret, "Content-Type": "application/json"}
        if self.secret.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + self.secret
        try:
            request_json(self.auth.url + "/auth/v1/admin/users/" + owner, headers,
                         {"should_soft_delete": False}, "DELETE")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise AuthError(503, "A exclusão não foi concluída. Tente novamente.") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise AuthError(503, "Não foi possível confirmar a exclusão. Tente novamente.") from None
