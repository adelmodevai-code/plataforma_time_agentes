"""
Automacao SIGT - Debug da celula de acao e popup de Re-executar
Agente: Argos
"""
import os
import re
import time
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = (
    "C:/Users/AdelmoSilva/Documents/Laboratorios/"
    "02-Projetos/Chat_Time_Agentes/screenshots_sigt"
)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

TARGET_URL = (
    "https://apex.minfin.gov.ao/ords/r/sigt/sigt100/"
    "login?session=111487032343465"
)
USERNAME = "adelmo_silva"
PASSWORD = "Dx220304@"
TARGET_BATCH = "CMJMSPC"


def screenshot(page, label: str) -> str:
    path = f"{SCREENSHOTS_DIR}/{label}.png"
    page.screenshot(path=path, full_page=True)
    print(f"[SCREENSHOT] -> {path}")
    return path


def wait_safe(page, timeout: int = 10000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def run() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()

        # Login
        print("=== LOGIN ===")
        page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")
        wait_safe(page, 20000)
        page.fill("input[name='P9999_USERNAME']", USERNAME)
        page.fill("input[name='P9999_PASSWORD']", PASSWORD)
        page.click("button:has-text('Entrar')")
        wait_safe(page, 25000)
        time.sleep(2)
        print(f"URL pos-login: {page.url}")

        # TIS
        print("=== MENU TIS ===")
        time.sleep(2)
        page.click("text=TIS")
        wait_safe(page, 10000)
        time.sleep(2)

        # Monitoramento de Jobs PSRM
        print("=== MONITORAMENTO JOBS PSRM ===")
        page.click("a:has-text('Monitoramento de Jobs PSRM')")
        wait_safe(page, 15000)
        time.sleep(3)

        screenshot(page, "debug-01-pagina-monitoramento")

        # Localizar a linha do CMJMSPC
        print(f"=== LOCALIZANDO {TARGET_BATCH} ===")
        rows = page.locator("tr").all()
        target_row = None
        for row in rows:
            try:
                if TARGET_BATCH in row.inner_text():
                    target_row = row
                    print(f"Linha encontrada: {row.inner_text().strip()}")
                    break
            except Exception:
                pass

        if target_row is None:
            print(f"ERRO: {TARGET_BATCH} nao encontrado")
            browser.close()
            return

        # Inspecionar HTML completo da linha
        print("\n=== HTML DA LINHA CMJMSPC ===")
        try:
            row_html = target_row.inner_html()
            print(row_html[:5000])
        except Exception as e:
            print(f"Erro: {e}")

        # Inspecionar a ultima celula (celula de acao)
        print("\n=== CELULAS DA LINHA ===")
        cells = target_row.locator("td").all()
        for i, cell in enumerate(cells):
            try:
                cell_html = cell.inner_html()
                cell_text = cell.inner_text().strip()
                print(f"\nCelula {i} texto: '{cell_text}'")
                print(f"Celula {i} HTML: {cell_html[:1000]}")
            except Exception as e:
                print(f"Celula {i} erro: {e}")

        # Tentar localizar botoes/links dentro da linha
        print("\n=== BOTOES/LINKS NA LINHA ===")
        btns = target_row.locator("button, a, input[type='button'], input[type='submit'], span[class*='fa'], i[class*='fa']").all()
        print(f"Botoes/links encontrados na linha: {len(btns)}")
        for i, btn in enumerate(btns):
            try:
                btn_text = btn.inner_text().strip()
                btn_html = btn.outer_html()
                btn_class = btn.get_attribute("class") or ""
                btn_title = btn.get_attribute("title") or ""
                btn_type = btn.evaluate("el => el.tagName")
                print(f"  Btn {i}: tag={btn_type}, class='{btn_class}', title='{btn_title}', text='{btn_text}'")
                print(f"  HTML: {btn_html[:300]}")
            except Exception as e:
                print(f"  Btn {i} erro: {e}")

        # Verificar se ha icones de font-awesome (fa-cog, fa-gear, etc.)
        print("\n=== ICONES NA LINHA ===")
        icons = target_row.locator("[class*='fa'], [class*='icon'], [class*='gear'], [class*='cog']").all()
        print(f"Icones encontrados: {len(icons)}")
        for i, icon in enumerate(icons):
            try:
                icon_html = icon.outer_html()
                print(f"  Icone {i}: {icon_html[:200]}")
            except Exception:
                pass

        # Clicar no ultimo elemento da linha (celula de acao)
        print("\n=== TENTANDO CLICAR NA CELULA DE ACAO ===")
        try:
            # Ultima celula
            last_cell = cells[-1] if cells else None
            if last_cell:
                last_cell_html = last_cell.inner_html()
                print(f"Ultima celula HTML: {last_cell_html[:500]}")

                # Clicar em qualquer elemento clicavel
                clickables = last_cell.locator("button, a, input, span[onclick], div[onclick]").all()
                print(f"Elementos clicaveis na ultima celula: {len(clickables)}")

                if clickables:
                    print("Clicando no primeiro elemento clicavel da ultima celula...")
                    clickables[0].click()
                    time.sleep(2)
                    wait_safe(page, 5000)
                    screenshot(page, "debug-02-apos-clique-celula-acao")

                    # Listar o HTML da pagina apos o clique (popup/dialog)
                    print("\n=== HTML DO POPUP/DIALOG APOS CLIQUE ===")
                    # Verificar dialogs do browser
                    popups = page.locator("[class*='popup'], [class*='dialog'], [class*='modal'], [role='dialog']").all()
                    print(f"Popups/dialogs encontrados: {len(popups)}")
                    for i, popup in enumerate(popups):
                        try:
                            popup_html = popup.inner_html()
                            popup_visible = popup.is_visible()
                            print(f"\nPopup {i} (visivel={popup_visible}):")
                            print(popup_html[:2000])
                        except Exception as e:
                            print(f"Popup {i} erro: {e}")

                    # Verificar texto da pagina completa apos clique
                    try:
                        body_text = page.locator("body").inner_text()
                        print(f"\nTexto da pagina apos clique:\n{body_text[:3000]}")
                    except Exception:
                        pass

                    # Verificar se abriu nova janela/tab
                    print(f"\nJanelas abertas: {len(context.pages)}")
                    for i, pg in enumerate(context.pages):
                        print(f"  Janela {i}: {pg.url}")

                    # Procurar "Re-executar" na pagina toda
                    print("\n=== BUSCANDO 'Re-executar' na pagina ===")
                    try:
                        reexec_els = page.locator("*:has-text('Re-executar')").all()
                        print(f"Elementos com texto 'Re-executar': {len(reexec_els)}")
                        for i, el in enumerate(reexec_els[:5]):
                            try:
                                el_html = el.outer_html()
                                el_visible = el.is_visible()
                                print(f"  El {i} (visivel={el_visible}): {el_html[:300]}")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"Erro busca Re-executar: {e}")

        except Exception as e:
            print(f"ERRO ao clicar: {e}")

        screenshot(page, "debug-03-estado-final")
        time.sleep(8)
        browser.close()


if __name__ == "__main__":
    run()
