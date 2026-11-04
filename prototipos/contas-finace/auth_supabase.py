"""Login real por OTP. Usa apenas a chave pública; não conhece códigos de e-mail."""
import base64
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path


class AuthError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def request_json(url, headers, payload=None, method="GET", limit=1_000_000):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Resposta maior que o limite")
        return json.loads(raw) if raw else None


def normalize_email(raw):
    value = str(raw or "").strip().lower()
    if len(value) > 180 or not re.fullmatch(r"[a-z0-9.!#$%&*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value) or ".." in value:
        raise AuthError(400, "Digite um e-mail válido.")
    if value.rsplit(".", 1)[-1] in ["test", "invalid", "localhost", "example"]:
        raise AuthError(400, "Use um e-mail real para receber o código de confirmação.")
    return value


def read_config(path):
    """Lê somente duas opções conhecidas. Não executa comandos de um arquivo .env."""
    names = ["FINACE_SUPABASE_URL", "FINACE_SUPABASE_PUBLISHABLE_KEY", "FINACE_EMAIL_OTP_READY"]
    config = {}
    file = Path(path)
    if file.is_file():
        for line in file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in names:
                    config[key.strip()] = value.strip().strip("\"'")
    for key in names:
        if os.environ.get(key):
            config[key] = os.environ[key]
    return config


class SupabaseAuth:
    mode = "supabase"

    def __init__(self, url="", public_key="", transport=None, otp_ready=False):
        self.url = url.rstrip("/")
        self.public_key = public_key
        self.transport = transport
        self.has_config = bool(self.url and public_key)
        self.delivery_ready = self.has_config and otp_ready
        self.configured = self.delivery_ready
        if self.has_config:
            if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", self.url):
                raise ValueError("Use a URL HTTPS de um projeto Supabase de teste.")
            if not public_key.startswith("sb_publishable_"):
                try:
                    payload = public_key.split(".")[1]
                    role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["role"]
                    if role != "anon":
                        raise ValueError()
                except (IndexError, KeyError, ValueError, TypeError):
                    raise ValueError("Use somente a chave pública publishable/anon. Chaves secretas não são aceitas.")

    @classmethod
    def from_file(cls, path):
        config = read_config(path)
        return cls(config.get("FINACE_SUPABASE_URL", ""), config.get("FINACE_SUPABASE_PUBLISHABLE_KEY", ""), otp_ready=config.get("FINACE_EMAIL_OTP_READY", "false").lower() == "true")

    def call(self, path, payload=None, access_token=None):
        if not self.has_config:
            raise AuthError(503, "O login real está preparado, mas falta conectar e configurar o Supabase e o envio de e-mail nesta prévia.")
        if self.transport:
            return self.transport(path, payload, access_token)
        headers = {"apikey": self.public_key, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        try:
            return request_json(self.url + "/auth/v1" + path, headers, payload, "GET" if payload is None else "POST") or {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise AuthError(429, "Aguarde um minuto antes de pedir outro código.")
            if path == "/verify" and e.code in [400, 401, 403, 422]:
                raise AuthError(400, "Código inválido ou expirado. Confira o e-mail ou peça um novo código.")
            if path == "/otp" and e.code in [400, 401, 403, 422]:
                raise AuthError(503, "O envio não foi liberado para este endereço. Confira a configuração de e-mail do Supabase.")
            if path == "/token?grant_type=refresh_token" and e.code in [400, 401, 403, 422]:
                raise AuthError(401, "Sua sessão terminou. Entre novamente.")
            raise AuthError(503, "O serviço de autenticação não conseguiu concluir a solicitação. Tente novamente.")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise AuthError(503, "Não foi possível conectar ao serviço de autenticação. Tente novamente.")

    def request_code(self, email, create_user=True):
        if not self.delivery_ready:
            raise AuthError(503, "O código por e-mail aguarda a configuração do remetente e do modelo de confirmação. Nenhum e-mail foi enviado.")
        self.call("/otp", {"email": email, "create_user": create_user})

    def verify_code(self, email, code, *, include_tokens=False):
        if not re.fullmatch(r"\d{6}", str(code), re.ASCII):
            raise AuthError(400, "Digite os seis números recebidos por e-mail.")
        result = self.call("/verify", {"email": email, "token": code, "type": "email"})
        access = result.get("access_token")
        if not isinstance(access, str) or not access:
            raise AuthError(401, "Não foi possível confirmar sua identidade.")
        # Obtém a identidade do servidor de autenticação, nunca de um JWT decodificado no cliente.
        user = self.call("/user", access_token=access)
        try:
            uuid.UUID(user["id"])
            if normalize_email(user["email"]) != email or not user.get("email_confirmed_at"):
                raise ValueError()
        except (KeyError, TypeError, ValueError, AuthError):
            raise AuthError(401, "O serviço não confirmou este e-mail. Peça um novo código.")
        identity = {"id": user["id"], "email": email}
        if include_tokens:
            identity["tokens"] = self.session_tokens(result)
        return identity

    @staticmethod
    def session_tokens(result):
        access, refresh, duration = (result.get(key) for key in ("access_token", "refresh_token", "expires_in"))
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise AuthError(503, "O serviço não retornou uma sessão válida.")
        if type(duration) is not int or not 0 < duration <= 86400:
            raise AuthError(503, "O serviço não informou a validade da sessão.")
        return access, refresh, duration

    def refresh(self, token, user_id):
        result = self.call("/token?grant_type=refresh_token", {"refresh_token": token})
        if not isinstance(result.get("user"), dict) or result["user"].get("id") != user_id:
            raise AuthError(401, "Sua sessão terminou. Entre novamente.")
        return self.session_tokens(result)
