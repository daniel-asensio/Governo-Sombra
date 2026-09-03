"""Protecção por palavra-passe (HTTP Basic) quando a aplicação está na internet.

Activa-se definindo GS_PASSWORD. O utilizador pode ser qualquer um (por omissão
"admin"); só a palavra-passe conta. Os browsers guardam-na, por isso só pede uma vez
por aparelho.
"""

from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..config import definicoes


class AutenticacaoBasica(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        senha = definicoes.password
        if not senha or request.url.path in ("/saude", "/manifest.json") or request.url.path.startswith("/static/"):
            return await call_next(request)
        cab = request.headers.get("authorization", "")
        if cab.lower().startswith("basic "):
            try:
                _, _, fornecida = base64.b64decode(cab[6:]).decode("utf-8").partition(":")
            except Exception:
                fornecida = ""
            if secrets.compare_digest(fornecida, senha):
                return await call_next(request)
        return Response("Acesso reservado.", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Governo Sombra", charset="UTF-8"'})
