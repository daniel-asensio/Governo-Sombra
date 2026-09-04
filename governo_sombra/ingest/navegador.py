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


def renderizar(url: str, *, esperar: str | None = None, esperar_texto: str | None = None, timeout_s: float = 90, tempo_extra_ms: int = 1500, accoes=None) -> str:
    """Abre o URL num Chromium invisível e devolve o HTML depois do JavaScript correr.

    `esperar`: selector CSS que deve aparecer; `esperar_texto`: texto que deve
    aparecer na página; `accoes(page)`: função opcional para clicar/navegar.
    """
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
