"""Mini-browser invisível (Chromium via Playwright) para sites que só mostram
conteúdo depois de correr JavaScript, como o Diário da República (OutSystems)
e algumas páginas do Parlamento.

Usa-se pouco e com cuidado: cada página rendida custa uns 200 MB de memória
durante alguns segundos. Imagens, fontes e vídeos são bloqueados.
"""

from __future__ import annotations

import logging
import os

from .base import ErroFonte

log = logging.getLogger("governo_sombra.ingest")

RECURSOS_BLOQUEADOS = {"image", "media", "font", "stylesheet"}


def disponivel() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def clicar_texto(padrao: str):
    """Devolve uma acção que clica no primeiro elemento cujo texto corresponde ao padrão (regex), se existir."""
    import re

    def accao(page):
        try:
            alvo = page.get_by_text(re.compile(padrao, re.I)).first
            if alvo.count() and alvo.is_visible():
                alvo.click()
                page.wait_for_timeout(2500)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
        except Exception as e:  # pragma: no cover - depende do site
            log.info("clique em %r falhou: %s", padrao, str(e)[:120])

    return accao


def observar(url: str, *, esperar: str | None = None, esperar_texto: str | None = None, timeout_s: float = 150, tempo_extra_ms: int = 2500, padrao_ligacoes: str | None = None, accoes=None) -> dict:
    """Rende a página e devolve o que um humano veria: texto, número de ligações, amostra de ligações.

    Nunca falha por timeout da espera: se o que se esperava não aparecer, devolve o
    que houver com `esperou: False`, para o diagnóstico mostrar o estado real.
    """
    import re

    from bs4 import BeautifulSoup

    resultado: dict = {"url": url, "esperou": True}

    def _tolerante(page):
        return None

    try:
        html = renderizar(url, esperar=esperar, esperar_texto=esperar_texto, timeout_s=timeout_s, tempo_extra_ms=tempo_extra_ms, accoes=accoes)
    except ErroFonte as e:
        if "não carregou a tempo" not in str(e):
            raise
        resultado["esperou"] = False
        resultado["aviso"] = str(e)[:200]
        html = renderizar(url, timeout_s=timeout_s, tempo_extra_ms=max(tempo_extra_ms, 6000), accoes=accoes)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    texto = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    ligacoes = [(a.get_text(" ", strip=True)[:80], a["href"]) for a in soup.select("a[href]")]
    resultado.update({"html": html, "texto": texto[:1500], "n_ligacoes": len(ligacoes), "amostra": ligacoes[:60]})
    if padrao_ligacoes:
        rx = re.compile(padrao_ligacoes, re.I)
        resultado["interessantes"] = [(tx, h) for tx, h in ligacoes if rx.search(h) or rx.search(tx)][:25]
    return resultado


import contextlib
import time


@contextlib.contextmanager
def _um_browser_de_cada_vez(espera_max_s: float = 600):
    """Só um Chromium de cada vez em toda a máquina (vários processos partilham o ficheiro de lock)."""
    import fcntl
    from pathlib import Path

    from ..config import DIR_VAR

    DIR_VAR.mkdir(parents=True, exist_ok=True)
    caminho = Path(os.environ.get("GS_LOCK_NAVEGADOR") or (DIR_VAR / "navegador.lock"))
    with open(caminho, "w") as f:
        inicio = time.time()
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - inicio > espera_max_s:
                    raise ErroFonte("outro mini-browser está a correr há demasiado tempo; tenta mais tarde")
                time.sleep(2)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def renderizar(url: str, *, esperar: str | None = None, esperar_texto: str | None = None, timeout_s: float = 90, tempo_extra_ms: int = 1500, accoes=None) -> str:
    """Abre o URL num Chromium invisível e devolve o HTML depois do JavaScript correr.

    `esperar`: selector CSS que deve aparecer; `esperar_texto`: texto que deve
    aparecer na página; `accoes(page)`: função opcional para clicar/navegar.
    Só corre um browser de cada vez na máquina (ver _um_browser_de_cada_vez).
    """
    with _um_browser_de_cada_vez():
        return _renderizar(url, esperar=esperar, esperar_texto=esperar_texto, timeout_s=timeout_s, tempo_extra_ms=tempo_extra_ms, accoes=accoes)


def _renderizar(url: str, *, esperar: str | None = None, esperar_texto: str | None = None, timeout_s: float = 90, tempo_extra_ms: int = 1500, accoes=None) -> str:
    if not disponivel():
        raise ErroFonte("Esta fonte precisa do mini-browser (Playwright/Chromium). Instala com: pip install playwright && playwright install --with-deps chromium")
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import TimeoutError as TimeoutPlaywright
    from playwright.sync_api import sync_playwright

    executavel = os.environ.get("GS_CHROMIUM") or None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executavel, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process", "--no-zygote", "--renderer-process-limit=1"])
            try:
                ctx = browser.new_context(locale="pt-PT", viewport={"width": 1280, "height": 1600}, user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 GovernoSombra/0.1")
                page = ctx.new_page()
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in RECURSOS_BLOQUEADOS else route.continue_())
                page.set_default_timeout(timeout_s * 1000)
                page.goto(url, wait_until="domcontentloaded")
                if esperar:
                    page.wait_for_selector(esperar)
                if esperar_texto:
                    page.wait_for_function("t => document.body && document.body.innerText.includes(t)", arg=esperar_texto)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except TimeoutPlaywright:
                    pass
                if accoes is not None:
                    accoes(page)
                page.wait_for_timeout(tempo_extra_ms)
                return page.content()
            finally:
                browser.close()
    except TimeoutPlaywright as e:
        raise ErroFonte(f"o site não carregou a tempo no mini-browser: {str(e).splitlines()[0][:200]}") from e
    except ErroPlaywright as e:
        raise ErroFonte(f"mini-browser: {str(e).splitlines()[0][:200]}") from e
