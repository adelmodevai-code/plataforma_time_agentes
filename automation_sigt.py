"""
Automacao SIGT - Login e Navegacao para Monitoramento de Jobs PSRM
Agente: Argos
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SCREENSHOTS_DIR = "C:/Users/AdelmoSilva/Documents/Laboratorios/02-Projetos/Chat_Time_Agentes/screenshots_sigt"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

TARGET_URL = "https://apex.minfin.gov.ao/ords/r/sigt/sigt100/login?session=111487032343465"
USERNAME = "adelmo_silva"
PASSWORD = "Dx220304@"

results = []

def log(action, selector, result):
    msg = f"[{action}] -> {selector} -> {result}"
    print(msg)
    results.append(msg)

def screenshot(page, label):
    path = f"{SCREENSHOTS_DIR}/{label}.png"
    page.screenshot(path=path, full_page=True)
    print(f"[SCREENSHOT] -> {path}")
    return path

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True
        )
        page = context.new_page()

        # ========================
        # PASSO 1: Acessar URL de login
        # ========================
        print("\n=== PASSO 1/7: Acessando pagina de login ===")
        try:
            page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=20000)
            log("NAVEGAR", TARGET_URL, "Pagina carregada")
            screenshot(page, "01-pagina-login")
        except Exception as e:
            log("NAVEGAR", TARGET_URL, f"ERRO: {e}")
            screenshot(page, "01-erro-login-page")

        # ========================
        # PASSO 2: Identificar campos de login
        # ========================
        print("\n=== PASSO 2/7: Identificando campos de login ===")
        time.sleep(1)

        # Listar inputs visiveis para debug
        inputs = page.locator("input").all()
        print(f"[INFO] Inputs encontrados na pagina: {len(inputs)}")
        for i, inp in enumerate(inputs):
            try:
                tipo = inp.get_attribute("type") or "text"
                nome = inp.get_attribute("name") or inp.get_attribute("id") or "sem-nome"
                print(f"  Input {i}: type={tipo}, name/id={nome}")
            except:
                pass

        # ========================
        # PASSO 3: Preencher credenciais
        # ========================
        print("\n=== PASSO 3/7: Preenchendo credenciais ===")

        # Tentativa com seletores comuns do Oracle APEX
        username_selectors = [
            "input[name='P9999_USERNAME']",
            "input[id='P9999_USERNAME']",
            "input[type='text']",
            "#P9999_USERNAME",
            "input[name='username']",
            "input[placeholder*='usu']",
            "input[placeholder*='User']",
            ".apex-item-text:first-of-type",
        ]

        password_selectors = [
            "input[name='P9999_PASSWORD']",
            "input[id='P9999_PASSWORD']",
            "input[type='password']",
            "#P9999_PASSWORD",
            "input[name='password']",
        ]

        login_button_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Entrar')",
            "button:has-text('Sign In')",
            "#B73286417683535028",
            ".t-Button--hot",
        ]

        # Preencher usuario
        username_filled = False
        for sel in username_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.fill(sel, USERNAME)
                log("PREENCHER", sel, f"Usuario preenchido")
                username_filled = True
                break
            except:
                continue

        if not username_filled:
            log("PREENCHER", "username", "ERRO - Nenhum selector funcionou")
            screenshot(page, "03-erro-username")

        # Preencher senha
        password_filled = False
        for sel in password_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.fill(sel, PASSWORD)
                log("PREENCHER", sel, "Senha preenchida (ocultada nos logs)")
                password_filled = True
                break
            except:
                continue

        if not password_filled:
            log("PREENCHER", "password", "ERRO - Nenhum selector funcionou")
            screenshot(page, "03-erro-password")

        screenshot(page, "03-credenciais-preenchidas")

        # ========================
        # PASSO 4: Clicar no botao de login
        # ========================
        print("\n=== PASSO 4/7: Clicando no botao de login ===")

        login_clicked = False
        for sel in login_button_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.click(sel)
                log("CLICAR", sel, "Botao de login clicado")
                login_clicked = True
                break
            except:
                continue

        if not login_clicked:
            # Tenta pressionar Enter no campo de senha
            try:
                page.keyboard.press("Enter")
                log("TECLA", "Enter", "Tecla Enter pressionada")
                login_clicked = True
            except Exception as e:
                log("CLICAR", "login-button", f"ERRO: {e}")

        # Aguardar navegacao apos login
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
            time.sleep(2)
        except:
            pass

        current_url = page.url
        log("URL-ATUAL", current_url, "Pos-login")
        screenshot(page, "04-pos-login")

        # Verificar se login foi bem sucedido
        page_title = page.title()
        print(f"[INFO] Titulo da pagina apos login: {page_title}")
        print(f"[INFO] URL apos login: {current_url}")

        # ========================
        # PASSO 5: Navegar para menu TIS
        # ========================
        print("\n=== PASSO 5/7: Procurando menu TIS ===")
        time.sleep(2)

        # Listar todos os links/menus visiveis
        links = page.locator("a").all()
        print(f"[INFO] Total de links encontrados: {len(links)}")
        tis_found = False
        for link in links:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 100:
                    print(f"  Link: '{texto}'")
                    if "TIS" in texto.upper():
                        print(f"  >> ENCONTRADO MENU TIS: '{texto}'")
                        tis_found = True
            except:
                pass

        # Seletores para menu TIS
        tis_selectors = [
            "text=TIS",
            "a:has-text('TIS')",
            "li:has-text('TIS')",
            "span:has-text('TIS')",
            ".t-NavigationBar-item:has-text('TIS')",
            "nav a:has-text('TIS')",
        ]

        tis_clicked = False
        for sel in tis_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                page.click(sel)
                log("CLICAR", sel, "Menu TIS clicado")
                tis_clicked = True
                time.sleep(2)
                break
            except:
                continue

        if not tis_clicked:
            log("CLICAR", "menu-TIS", "AVISO - Menu TIS nao encontrado com seletores padrao")
            screenshot(page, "05-menu-nao-encontrado")

            # Tira screenshot e lista o HTML do nav para debug
            nav_html = ""
            try:
                nav_html = page.locator("nav").inner_html()[:2000]
                print(f"[DEBUG] HTML do nav:\n{nav_html}")
            except:
                pass

            try:
                body_text = page.locator("body").inner_text()[:3000]
                print(f"[DEBUG] Texto da pagina (primeiros 3000 chars):\n{body_text}")
            except:
                pass
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            screenshot(page, "05-menu-tis-clicado")

        # ========================
        # PASSO 6: Navegar para Monitoramento de Jobs PSRM
        # ========================
        print("\n=== PASSO 6/7: Procurando Monitoramento de Jobs PSRM ===")
        time.sleep(2)

        # Listar links apos clicar em TIS
        links_after = page.locator("a").all()
        print(f"[INFO] Links apos menu TIS: {len(links_after)}")
        for link in links_after:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 150:
                    print(f"  Link: '{texto}'")
            except:
                pass

        psrm_selectors = [
            "text=Monitoramento de Jobs PSRM",
            "a:has-text('Monitoramento de Jobs PSRM')",
            "a:has-text('Jobs PSRM')",
            "a:has-text('PSRM')",
            "li:has-text('Monitoramento')",
            "span:has-text('Jobs PSRM')",
        ]

        psrm_clicked = False
        for sel in psrm_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                page.click(sel)
                log("CLICAR", sel, "Monitoramento de Jobs PSRM clicado")
                psrm_clicked = True
                break
            except:
                continue

        if not psrm_clicked:
            log("CLICAR", "Monitoramento-Jobs-PSRM", "AVISO - Item nao encontrado com seletores padrao")
            screenshot(page, "06-psrm-nao-encontrado")

            # Listar todo o texto da pagina para debug
            try:
                full_text = page.locator("body").inner_text()
                print(f"[DEBUG] Texto completo da pagina:\n{full_text[:5000]}")
            except:
                pass
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(2)
            except:
                pass
            screenshot(page, "06-pagina-monitoramento-jobs")

        # ========================
        # PASSO 7: Extrair informacoes da pagina de Monitoramento
        # ========================
        print("\n=== PASSO 7/7: Extraindo informacoes da pagina ===")
        time.sleep(2)

        current_url = page.url
        page_title = page.title()
        print(f"[INFO] URL atual: {current_url}")
        print(f"[INFO] Titulo: {page_title}")

        # Capturar screenshot final completo
        screenshot(page, "07-pagina-final-completa")

        # Extrair texto completo da pagina
        try:
            full_page_text = page.locator("body").inner_text()
            print(f"\n[CONTEUDO DA PAGINA]:\n{'='*60}")
            print(full_page_text[:8000])
            print('='*60)
        except Exception as e:
            print(f"[ERRO] Nao foi possivel extrair texto: {e}")

        # Verificar tabelas
        tables = page.locator("table").all()
        print(f"\n[INFO] Tabelas encontradas: {len(tables)}")
        for i, table in enumerate(tables):
            try:
                table_text = table.inner_text()
                print(f"\n[TABELA {i+1}]:\n{table_text[:3000]}")
            except:
                pass

        # Verificar cabecalhos de colunas (th)
        headers = page.locator("th").all()
        print(f"\n[INFO] Cabecalhos de colunas encontrados: {len(headers)}")
        for h in headers:
            try:
                print(f"  Coluna: '{h.inner_text().strip()}'")
            except:
                pass

        # Verificar filtros/inputs visiveis
        inputs_final = page.locator("input:visible").all()
        print(f"\n[INFO] Campos de filtro/input visiveis: {len(inputs_final)}")
        for inp in inputs_final:
            try:
                placeholder = inp.get_attribute("placeholder") or ""
                name = inp.get_attribute("name") or inp.get_attribute("id") or ""
                tipo = inp.get_attribute("type") or "text"
                if tipo not in ["hidden"]:
                    print(f"  Input: type={tipo}, name/id={name}, placeholder='{placeholder}'")
            except:
                pass

        # Verificar selects/dropdowns
        selects = page.locator("select:visible").all()
        print(f"\n[INFO] Dropdowns/selects visiveis: {len(selects)}")
        for sel_el in selects:
            try:
                name = sel_el.get_attribute("name") or sel_el.get_attribute("id") or ""
                print(f"  Select: name/id={name}")
            except:
                pass

        # Verificar headings
        headings = page.locator("h1, h2, h3, h4").all()
        print(f"\n[INFO] Titulos/headings encontrados: {len(headings)}")
        for h in headings:
            try:
                print(f"  Heading: '{h.inner_text().strip()}'")
            except:
                pass

        # Screenshot final
        screenshot(page, "07-resultado-final")

        print(f"\n\n{'='*60}")
        print("RESUMO DA EXECUCAO:")
        print(f"{'='*60}")
        for r in results:
            print(r)
        print(f"\nScreenshots salvos em: {SCREENSHOTS_DIR}")
        print(f"{'='*60}")

        # Manter browser aberto por 5 segundos para visualizacao
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    run()
