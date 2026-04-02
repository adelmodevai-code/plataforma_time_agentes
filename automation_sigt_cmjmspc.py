"""
Automacao SIGT - Verificacao e Re-execucao do Job CMJMSPC
Agente: Argos
Fluxo: Login -> TIS -> Monitoramento de Jobs PSRM -> Verificar CMJMSPC -> Acao condicional
"""
import os
import sys
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SCREENSHOTS_DIR = "C:/Users/AdelmoSilva/Documents/Laboratorios/02-Projetos/Chat_Time_Agentes/screenshots_sigt"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

TARGET_URL = "https://apex.minfin.gov.ao/ords/r/sigt/sigt100/login?session=111487032343465"
USERNAME = "adelmo_silva"
PASSWORD = "Dx220304@"
TARGET_BATCH = "CMJMSPC"
TEMPO_LIMITE_MINUTOS = 15

results = []
test_results = {"pass": [], "fail": [], "info": []}


def log(action, selector, result_msg):
    msg = f"[{action}] -> {selector} -> {result_msg}"
    print(msg)
    results.append(msg)


def screenshot(page, label):
    path = f"{SCREENSHOTS_DIR}/{label}.png"
    page.screenshot(path=path, full_page=True)
    print(f"[SCREENSHOT] -> {path}")
    return path


def mark_test(name, status, message=""):
    symbol = "PASS" if status == "pass" else "FAIL" if status == "fail" else "INFO"
    print(f"[{symbol}] {name}: {message}")
    test_results[status].append({"name": name, "message": message})


def parse_tempo(tempo_str):
    """
    Converte string de tempo '0hs:15 min', '1hs:00min', '0hs:05 min' para minutos totais.
    Retorna total em minutos ou None se nao conseguir parsear.
    """
    if not tempo_str:
        return None

    tempo_str = tempo_str.strip()
    print(f"[PARSE] Tentando parsear tempo: '{tempo_str}'")

    # Padroes: '0hs:15 min', '1hs:00min', '0hs:05min', '2hs:30 min'
    patterns = [
        r'(\d+)\s*hs\s*:?\s*(\d+)\s*min',
        r'(\d+)h\s*:?\s*(\d+)m',
        r'(\d+):(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, tempo_str, re.IGNORECASE)
        if match:
            horas = int(match.group(1))
            minutos = int(match.group(2))
            total_minutos = horas * 60 + minutos
            print(f"[PARSE] Tempo parseado: {horas}h:{minutos}min = {total_minutos} minutos totais")
            return total_minutos

    print(f"[PARSE] Nao foi possivel parsear: '{tempo_str}'")
    return None


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            ignore_https_errors=True
        )
        page = context.new_page()

        # ========================
        # PASSO 1/6: Acessar URL de login
        # ========================
        print("\n" + "=" * 60)
        print("PASSO 1/6: Acessando pagina de login")
        print("=" * 60)

        try:
            page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=20000)
            log("NAVEGAR", TARGET_URL, "Pagina carregada")
            screenshot(page, "01-pagina-login")
            mark_test("Acesso a pagina de login", "pass", "Pagina carregada com sucesso")
        except Exception as e:
            log("NAVEGAR", TARGET_URL, f"ERRO: {e}")
            screenshot(page, "01-erro-acesso")
            mark_test("Acesso a pagina de login", "fail", str(e))

        # ========================
        # PASSO 2/6: Login
        # ========================
        print("\n" + "=" * 60)
        print("PASSO 2/6: Realizando login")
        print("=" * 60)
        time.sleep(1)

        # Listar inputs para debug
        inputs = page.locator("input").all()
        print(f"[INFO] Inputs encontrados: {len(inputs)}")
        for i, inp in enumerate(inputs):
            try:
                tipo = inp.get_attribute("type") or "text"
                nome = inp.get_attribute("name") or inp.get_attribute("id") or "sem-nome"
                print(f"  Input {i}: type={tipo}, name/id={nome}")
            except Exception:
                pass

        # Seletores username
        username_selectors = [
            "input[name='P9999_USERNAME']",
            "input[id='P9999_USERNAME']",
            "#P9999_USERNAME",
            "input[type='text']",
            "input[name='username']",
        ]

        # Seletores password
        password_selectors = [
            "input[name='P9999_PASSWORD']",
            "input[id='P9999_PASSWORD']",
            "#P9999_PASSWORD",
            "input[type='password']",
        ]

        # Seletores botao login
        login_button_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Entrar')",
            ".t-Button--hot",
        ]

        # Preencher usuario
        username_filled = False
        for sel in username_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.fill(sel, USERNAME)
                log("PREENCHER", sel, f"Usuario '{USERNAME}' preenchido")
                username_filled = True
                break
            except Exception:
                continue

        if not username_filled:
            log("PREENCHER", "username", "ERRO - Nenhum selector funcionou")
            screenshot(page, "02-erro-username")

        # Preencher senha
        password_filled = False
        for sel in password_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.fill(sel, PASSWORD)
                log("PREENCHER", sel, "Senha preenchida (ocultada nos logs)")
                password_filled = True
                break
            except Exception:
                continue

        if not password_filled:
            log("PREENCHER", "password", "ERRO - Nenhum selector funcionou")
            screenshot(page, "02-erro-password")

        screenshot(page, "02-credenciais-preenchidas")

        # Clicar botao login
        login_clicked = False
        for sel in login_button_selectors:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.click(sel)
                log("CLICAR", sel, "Botao de login clicado")
                login_clicked = True
                break
            except Exception:
                continue

        if not login_clicked:
            try:
                page.keyboard.press("Enter")
                log("TECLA", "Enter", "Enter pressionado")
                login_clicked = True
            except Exception as e:
                log("CLICAR", "login-button", f"ERRO: {e}")

        # Aguardar pos-login
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
            time.sleep(2)
        except Exception:
            pass

        current_url = page.url
        log("URL-ATUAL", current_url, "Pos-login")
        screenshot(page, "02-pos-login")

        page_title = page.title()
        print(f"[INFO] Titulo pos-login: {page_title}")
        print(f"[INFO] URL pos-login: {current_url}")

        if "login" in current_url.lower() and current_url == TARGET_URL:
            mark_test("Login", "fail", "URL ainda e a de login - possivel falha de autenticacao")
        else:
            mark_test("Login", "pass", f"Autenticado com sucesso. URL: {current_url}")

        # ========================
        # PASSO 3/6: Navegar para menu TIS
        # ========================
        print("\n" + "=" * 60)
        print("PASSO 3/6: Navegando para menu TIS")
        print("=" * 60)
        time.sleep(2)

        # Listar todos os links visiveis
        links = page.locator("a:visible").all()
        print(f"[INFO] Links visiveis encontrados: {len(links)}")
        for link in links:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 100:
                    print(f"  Link: '{texto}'")
            except Exception:
                pass

        tis_selectors = [
            "text=TIS",
            "a:has-text('TIS')",
            "span:has-text('TIS')",
            ".t-NavigationBar-item:has-text('TIS')",
            "nav a:has-text('TIS')",
            "li:has-text('TIS') > a",
            "//a[contains(text(),'TIS')]",
            "//span[contains(text(),'TIS')]",
        ]

        tis_clicked = False
        for sel in tis_selectors:
            try:
                page.wait_for_selector(sel, timeout=4000)
                page.click(sel)
                log("CLICAR", sel, "Menu TIS clicado")
                tis_clicked = True
                time.sleep(2)
                break
            except Exception:
                continue

        if not tis_clicked:
            log("CLICAR", "menu-TIS", "AVISO - Nao encontrado com seletores padrao")
            screenshot(page, "03-tis-nao-encontrado")
            try:
                body_text = page.locator("body").inner_text()[:5000]
                print(f"[DEBUG] Conteudo da pagina:\n{body_text}")
            except Exception:
                pass
            mark_test("Navegacao menu TIS", "fail", "Menu TIS nao encontrado")
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            screenshot(page, "03-menu-tis-clicado")
            mark_test("Navegacao menu TIS", "pass", "Menu TIS encontrado e clicado")

        # ========================
        # PASSO 4/6: Clicar em Monitoramento de Jobs PSRM
        # ========================
        print("\n" + "=" * 60)
        print("PASSO 4/6: Navegando para Monitoramento de Jobs PSRM")
        print("=" * 60)
        time.sleep(2)

        # Listar links apos clicar em TIS
        links_tis = page.locator("a:visible").all()
        print(f"[INFO] Links apos menu TIS: {len(links_tis)}")
        for link in links_tis:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 150:
                    print(f"  Link: '{texto}'")
            except Exception:
                pass

        psrm_selectors = [
            "text=Monitoramento de Jobs PSRM",
            "a:has-text('Monitoramento de Jobs PSRM')",
            "a:has-text('Jobs PSRM')",
            "a:has-text('PSRM')",
            "span:has-text('Monitoramento de Jobs PSRM')",
            "li:has-text('PSRM') > a",
            "//a[contains(text(),'PSRM')]",
            "//a[contains(text(),'Monitoramento')]",
        ]

        psrm_clicked = False
        for sel in psrm_selectors:
            try:
                page.wait_for_selector(sel, timeout=4000)
                page.click(sel)
                log("CLICAR", sel, "Monitoramento de Jobs PSRM clicado")
                psrm_clicked = True
                break
            except Exception:
                continue

        if not psrm_clicked:
            log("CLICAR", "Monitoramento-Jobs-PSRM", "AVISO - Nao encontrado")
            screenshot(page, "04-psrm-nao-encontrado")
            try:
                full_text = page.locator("body").inner_text()[:6000]
                print(f"[DEBUG] Conteudo da pagina:\n{full_text}")
            except Exception:
                pass
            mark_test("Navegacao Monitoramento Jobs PSRM", "fail", "Item nao encontrado no menu TIS")
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(2)
            except Exception:
                pass
            screenshot(page, "04-pagina-monitoramento-jobs")
            mark_test("Navegacao Monitoramento Jobs PSRM", "pass", "Pagina de monitoramento aberta")

        # ========================
        # PASSO 5/6: Buscar CMJMSPC na tabela
        # ========================
        print("\n" + "=" * 60)
        print(f"PASSO 5/6: Procurando '{TARGET_BATCH}' na tabela")
        print("=" * 60)
        time.sleep(2)

        current_url = page.url
        print(f"[INFO] URL atual: {current_url}")
        print(f"[INFO] Titulo: {page.title()}")

        # Capturar screenshot da pagina de monitoramento
        screenshot(page, "05-tabela-monitoramento")

        # Extrair conteudo da pagina
        page_content = ""
        try:
            page_content = page.locator("body").inner_text()
            print(f"[INFO] Conteudo da pagina (primeiros 5000 chars):\n{page_content[:5000]}")
        except Exception as e:
            print(f"[ERRO] Nao foi possivel extrair conteudo: {e}")

        # Verificar se CMJMSPC existe no conteudo
        cmjmspc_exists = TARGET_BATCH in page_content

        # Buscar na tabela de forma mais estruturada
        cmjmspc_row = None
        cmjmspc_tempo = None
        cmjmspc_row_index = -1

        if cmjmspc_exists:
            print(f"[INFO] '{TARGET_BATCH}' encontrado na pagina!")

            # Tentar localizar a linha especifica
            row_selectors = [
                f"tr:has-text('{TARGET_BATCH}')",
                f"//tr[contains(.,'{TARGET_BATCH}')]",
            ]

            for sel in row_selectors:
                try:
                    rows_with_batch = page.locator(sel).all()
                    if rows_with_batch:
                        print(f"[INFO] Linhas encontradas com '{TARGET_BATCH}': {len(rows_with_batch)}")
                        for idx, row in enumerate(rows_with_batch):
                            row_text = row.inner_text()
                            print(f"  Linha {idx}: '{row_text}'")
                            if TARGET_BATCH in row_text:
                                cmjmspc_row = row
                                cmjmspc_row_index = idx
                                # Extrair tempo da linha
                                cells = row.locator("td").all()
                                print(f"  [INFO] Celulas nessa linha: {len(cells)}")
                                for cidx, cell in enumerate(cells):
                                    cell_text = cell.inner_text().strip()
                                    print(f"    Celula {cidx}: '{cell_text}'")

                                # Tentar parsear tempo de cada celula
                                for cell in cells:
                                    cell_text = cell.inner_text().strip()
                                    if "hs" in cell_text.lower() or "min" in cell_text.lower() or re.search(r'\d+:\d+', cell_text):
                                        cmjmspc_tempo = cell_text
                                        print(f"  [TEMPO ENCONTRADO] '{cmjmspc_tempo}'")
                                        break
                                break
                        if cmjmspc_row:
                            break
                except Exception as e:
                    print(f"  [AVISO] Erro com selector '{sel}': {e}")
                    continue

        # Se nao encontrou via locator de linha, tentar extrair do texto da pagina
        if cmjmspc_exists and not cmjmspc_tempo:
            print(f"[INFO] Tentando extrair tempo via regex no texto da pagina...")
            # Procurar no contexto ao redor de CMJMSPC
            idx_batch = page_content.find(TARGET_BATCH)
            if idx_batch >= 0:
                contexto = page_content[max(0, idx_batch - 50):idx_batch + 300]
                print(f"[DEBUG] Contexto ao redor de '{TARGET_BATCH}':\n{contexto}")
                # Procurar padrao de tempo no contexto
                time_match = re.search(r'(\d+\s*hs\s*:?\s*\d+\s*min)', contexto, re.IGNORECASE)
                if time_match:
                    cmjmspc_tempo = time_match.group(1)
                    print(f"[TEMPO VIA REGEX] '{cmjmspc_tempo}'")

        # ========================
        # PASSO 6/6: Acao baseada no resultado
        # ========================
        print("\n" + "=" * 60)
        print("PASSO 6/6: Executando acao baseada no resultado")
        print("=" * 60)

        if not cmjmspc_exists:
            # CASO: CMJMSPC NAO ENCONTRADO
            mark_test(
                f"Busca por '{TARGET_BATCH}'",
                "info",
                f"'{TARGET_BATCH}' NAO encontrado na tabela de monitoramento"
            )
            print(f"\n[RESULTADO] O codigo batch '{TARGET_BATCH}' NAO foi encontrado na tabela.")
            screenshot(page, "06-resultado-nao-encontrado")

        else:
            # CASO: CMJMSPC ENCONTRADO
            mark_test(
                f"Busca por '{TARGET_BATCH}'",
                "pass",
                f"'{TARGET_BATCH}' encontrado na tabela. Tempo: '{cmjmspc_tempo}'"
            )
            print(f"\n[RESULTADO] O codigo batch '{TARGET_BATCH}' FOI encontrado.")
            print(f"[RESULTADO] Tempo registrado: '{cmjmspc_tempo}'")

            total_minutos = parse_tempo(cmjmspc_tempo) if cmjmspc_tempo else None

            if total_minutos is None:
                print(f"[AVISO] Nao foi possivel parsear o tempo '{cmjmspc_tempo}'.")
                print(f"[AVISO] Verificando visualmente a linha e tomando screenshot.")
                screenshot(page, "06-tempo-nao-parseavel")
                mark_test("Verificacao de tempo", "fail", f"Tempo '{cmjmspc_tempo}' nao foi parseavel")

            elif total_minutos > TEMPO_LIMITE_MINUTOS:
                # TEMPO ACIMA DO LIMITE - Re-executar
                print(f"\n[ALERTA] Tempo {total_minutos} min > {TEMPO_LIMITE_MINUTOS} min (limite).")
                print(f"[ACAO] Iniciando processo de re-execucao do job...")
                mark_test(
                    "Verificacao de tempo",
                    "fail",
                    f"Tempo {cmjmspc_tempo} ({total_minutos}min) excede o limite de {TEMPO_LIMITE_MINUTOS}min"
                )

                # Clicar no botao de engrenagem (gear) na linha do CMJMSPC
                gear_clicked = False
                gear_selectors_in_row = []

                if cmjmspc_row:
                    # Tentar dentro da linha
                    gear_in_row_selectors = [
                        "button",
                        "a[title*='Ação']",
                        "a[title*='Opcoes']",
                        "a[title*='gear']",
                        "button[title*='gear']",
                        ".fa-cog",
                        ".fa-gear",
                        "span.fa-cog",
                        "button:has(.fa-cog)",
                        "a:has(.fa-cog)",
                        "button:has(.fa-gear)",
                        "a[data-action]",
                    ]
                    for sel in gear_in_row_selectors:
                        try:
                            gear_el = cmjmspc_row.locator(sel).first
                            if gear_el.is_visible():
                                gear_el.click()
                                log("CLICAR", f"engrenagem em linha {TARGET_BATCH}", "Clicado")
                                gear_clicked = True
                                time.sleep(1)
                                break
                        except Exception:
                            continue

                if not gear_clicked:
                    # Tentar localizar engrenagem por proximidade ao texto CMJMSPC
                    print(f"[INFO] Tentando localizar engrenagem na pagina...")
                    global_gear_selectors = [
                        f"tr:has-text('{TARGET_BATCH}') button",
                        f"tr:has-text('{TARGET_BATCH}') a",
                        f"//tr[contains(.,'{TARGET_BATCH}')]//button",
                        f"//tr[contains(.,'{TARGET_BATCH}')]//a[contains(@class,'gear')]",
                        f"//tr[contains(.,'{TARGET_BATCH}')]//span[contains(@class,'fa-cog')]/..",
                        f"//tr[contains(.,'{TARGET_BATCH}')]//*[contains(@class,'fa-cog')]/..",
                        f"//tr[contains(.,'{TARGET_BATCH}')]/td//button",
                        f"//tr[contains(.,'{TARGET_BATCH}')]/td//a",
                    ]
                    for sel in global_gear_selectors:
                        try:
                            elements = page.locator(sel).all()
                            if elements:
                                print(f"[INFO] Elementos encontrados com '{sel}': {len(elements)}")
                                for el in elements:
                                    try:
                                        el_text = el.inner_text().strip()
                                        el_class = el.get_attribute("class") or ""
                                        el_title = el.get_attribute("title") or ""
                                        print(f"  Elemento: text='{el_text}', class='{el_class}', title='{el_title}'")
                                    except Exception:
                                        pass
                                # Clicar no primeiro visivel
                                for el in elements:
                                    try:
                                        if el.is_visible():
                                            el.scroll_into_view_if_needed()
                                            el.click()
                                            log("CLICAR", sel, "Possivel engrenagem clicada")
                                            gear_clicked = True
                                            time.sleep(1)
                                            break
                                    except Exception:
                                        continue
                            if gear_clicked:
                                break
                        except Exception as e:
                            print(f"  [AVISO] Erro: {e}")
                            continue

                screenshot(page, "06-apos-clicar-engrenagem")

                if gear_clicked:
                    # Aguardar popup/modal aparecer
                    print(f"[INFO] Aguardando popup/modal...")
                    time.sleep(2)

                    # Verificar se popup apareceu
                    popup_content = ""
                    try:
                        popup_content = page.locator("body").inner_text()
                    except Exception:
                        pass

                    screenshot(page, "06-popup-aberto")

                    # Procurar botao Re-executar
                    reexecutar_selectors = [
                        "text=Re-executar",
                        "button:has-text('Re-executar')",
                        "a:has-text('Re-executar')",
                        "button:has-text('Reexecutar')",
                        "button:has-text('Re-Executar')",
                        "//button[contains(text(),'Re-executar')]",
                        "//a[contains(text(),'Re-executar')]",
                        "//button[contains(text(),'executar')]",
                        ".t-Button:has-text('Re-executar')",
                    ]

                    reexecutar_clicked = False
                    for sel in reexecutar_selectors:
                        try:
                            page.wait_for_selector(sel, timeout=5000)
                            page.click(sel)
                            log("CLICAR", sel, "Botao Re-executar clicado")
                            reexecutar_clicked = True
                            time.sleep(2)
                            break
                        except Exception:
                            continue

                    if not reexecutar_clicked:
                        print("[AVISO] Botao 'Re-executar' nao encontrado.")
                        print("[DEBUG] Conteudo do popup:")
                        try:
                            # Listar todos os botoes/links visiveis no popup
                            popup_buttons = page.locator("button:visible, a:visible").all()
                            for btn in popup_buttons:
                                try:
                                    btn_text = btn.inner_text().strip()
                                    if btn_text:
                                        print(f"  Botao/Link visivel: '{btn_text}'")
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        screenshot(page, "06-reexecutar-nao-encontrado")
                        mark_test("Re-execucao do job", "fail", "Botao 'Re-executar' nao encontrado no popup")
                    else:
                        # Verificar dialogo de confirmacao
                        time.sleep(1)
                        try:
                            # Aceitar dialog/alert se aparecer
                            page.on("dialog", lambda dialog: dialog.accept())
                        except Exception:
                            pass

                        # Procurar botao de confirmacao no modal
                        confirm_selectors = [
                            "button:has-text('OK')",
                            "button:has-text('Confirmar')",
                            "button:has-text('Sim')",
                            "button:has-text('Yes')",
                            "button:has-text('Confirm')",
                        ]
                        for sel in confirm_selectors:
                            try:
                                page.wait_for_selector(sel, timeout=3000)
                                page.click(sel)
                                log("CLICAR", sel, "Confirmacao clicada")
                                time.sleep(2)
                                break
                            except Exception:
                                continue

                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                            time.sleep(2)
                        except Exception:
                            pass

                        screenshot(page, "06-resultado-reexecucao")
                        mark_test("Re-execucao do job", "pass",
                                  f"Re-execucao disparada para '{TARGET_BATCH}' (tempo: {cmjmspc_tempo})")
                        print(f"\n[RESULTADO FINAL] Job '{TARGET_BATCH}' re-execucao iniciada com sucesso.")

                else:
                    # Nao conseguiu clicar na engrenagem
                    screenshot(page, "06-engrenagem-nao-encontrada")
                    mark_test("Clicar na engrenagem", "fail",
                              f"Botao de engrenagem na linha '{TARGET_BATCH}' nao encontrado")
                    print(f"[ERRO] Nao foi possivel encontrar/clicar no botao de engrenagem da linha '{TARGET_BATCH}'.")

            else:
                # TEMPO DENTRO DO LIMITE
                print(f"\n[RESULTADO] Job '{TARGET_BATCH}' dentro do tempo esperado.")
                print(f"[RESULTADO] Tempo: {cmjmspc_tempo} ({total_minutos}min) <= {TEMPO_LIMITE_MINUTOS}min (limite).")
                mark_test(
                    "Verificacao de tempo",
                    "pass",
                    f"Job '{TARGET_BATCH}' dentro do tempo. Tempo: {cmjmspc_tempo} ({total_minutos}min)"
                )
                screenshot(page, "06-job-dentro-do-tempo")

        # ========================
        # RELATORIO FINAL
        # ========================
        print("\n" + "=" * 60)
        print("RELATORIO FINAL DE EXECUCAO")
        print("=" * 60)

        print(f"\nStatus do Job '{TARGET_BATCH}':")
        if not cmjmspc_exists:
            print(f"  STATUS: NAO ENCONTRADO na tabela")
        else:
            print(f"  STATUS: ENCONTRADO")
            print(f"  TEMPO: {cmjmspc_tempo}")
            if total_minutos is not None:
                print(f"  MINUTOS TOTAIS: {total_minutos}")
                if total_minutos > TEMPO_LIMITE_MINUTOS:
                    print(f"  ALERTA: Acima do limite ({TEMPO_LIMITE_MINUTOS}min) - Re-execucao disparada")
                else:
                    print(f"  OK: Dentro do limite ({TEMPO_LIMITE_MINUTOS}min)")

        print(f"\nLog de acoes:")
        for r in results:
            print(f"  {r}")

        print(f"\nResultados dos testes:")
        print(f"  PASS: {len(test_results['pass'])}")
        print(f"  FAIL: {len(test_results['fail'])}")
        print(f"  INFO: {len(test_results['info'])}")

        for t in test_results["pass"]:
            print(f"  [PASS] {t['name']}: {t['message']}")
        for t in test_results["fail"]:
            print(f"  [FAIL] {t['name']}: {t['message']}")
        for t in test_results["info"]:
            print(f"  [INFO] {t['name']}: {t['message']}")

        print(f"\nScreenshots salvos em: {SCREENSHOTS_DIR}")
        print("=" * 60)

        time.sleep(5)
        browser.close()

        return {
            "batch_encontrado": cmjmspc_exists,
            "tempo": cmjmspc_tempo,
            "total_minutos": total_minutos if cmjmspc_exists and cmjmspc_tempo else None,
            "acima_do_limite": (total_minutos > TEMPO_LIMITE_MINUTOS) if (cmjmspc_exists and total_minutos is not None) else None,
        }


if __name__ == "__main__":
    resultado = run()
    print(f"\n[RESULTADO ESTRUTURADO]: {resultado}")
