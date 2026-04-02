"""
Automacao SIGT v2 - Login, TIS > Monitoramento de Jobs PSRM
Verifica codigo batch CMJMSPC e re-executa se tempo > 15min
Agente: Argos
"""
import os
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

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

log_lines: list[str] = []


def log(action: str, selector: str, result: str) -> None:
    msg = f"[{action}] -> {selector} -> {result}"
    print(msg)
    log_lines.append(msg)


def screenshot(page, label: str) -> str:
    path = f"{SCREENSHOTS_DIR}/{label}.png"
    page.screenshot(path=path, full_page=True)
    print(f"[SCREENSHOT] -> {path}")
    return path


def parse_tempo_minutes(tempo_str: str) -> float:
    """
    Converte strings de tempo como '0hs:15 min', '1hs:00min', '0hs:5min'
    para total em minutos (float). Retorna -1 se nao conseguir parsear.
    """
    tempo_str = tempo_str.strip().lower()
    pattern = r"(\d+)\s*hs?\s*[:\s]+\s*(\d+)\s*min?"
    match = re.search(pattern, tempo_str)
    if match:
        horas = int(match.group(1))
        minutos = int(match.group(2))
        return horas * 60 + minutos
    # Tenta apenas minutos
    match2 = re.search(r"(\d+)\s*min", tempo_str)
    if match2:
        return float(match2.group(1))
    return -1.0


def wait_safe(page, timeout: int = 10000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def try_click(page, selectors: list[str], label: str) -> bool:
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=5000, state="visible")
            page.click(sel)
            log("CLICAR", sel, f"{label} clicado")
            return True
        except Exception:
            continue
    log("CLICAR", label, "ERRO - Nenhum selector funcionou")
    return False


def try_fill(page, selectors: list[str], value: str, label: str) -> bool:
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=3000, state="visible")
            page.fill(sel, value)
            log("PREENCHER", sel, label)
            return True
        except Exception:
            continue
    log("PREENCHER", label, "ERRO - Nenhum selector funcionou")
    return False


def run() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()

        # ====================================================
        # PASSO 1: Acessar URL de login
        # ====================================================
        print("\n=== PASSO 1/7: Acessando pagina de login ===")
        try:
            page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")
            wait_safe(page, 20000)
            log("NAVEGAR", TARGET_URL, "Pagina carregada")
            screenshot(page, "01-pagina-login")
        except Exception as e:
            log("NAVEGAR", TARGET_URL, f"ERRO: {e}")
            screenshot(page, "01-erro-pagina")
            browser.close()
            return

        # ====================================================
        # PASSO 2: Preencher usuario
        # ====================================================
        print("\n=== PASSO 2/7: Preenchendo credenciais ===")
        time.sleep(1)

        username_selectors = [
            "input[name='P9999_USERNAME']",
            "#P9999_USERNAME",
            "input[type='text']",
            "input[name='username']",
            "input[placeholder*='ser']",
            "input[placeholder*='User']",
            ".apex-item-text",
        ]
        password_selectors = [
            "input[name='P9999_PASSWORD']",
            "#P9999_PASSWORD",
            "input[type='password']",
            "input[name='password']",
        ]

        try_fill(page, username_selectors, USERNAME, "Usuario preenchido")
        try_fill(page, password_selectors, PASSWORD, "Senha preenchida (ocultada)")

        screenshot(page, "02-credenciais-preenchidas")

        # ====================================================
        # PASSO 3: Clicar no botao de login
        # ====================================================
        print("\n=== PASSO 3/7: Efetuando login ===")
        login_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Entrar')",
            "button:has-text('Sign In')",
            ".t-Button--hot",
            "#B73286417683535028",
        ]
        clicked = try_click(page, login_selectors, "Botao de login")
        if not clicked:
            page.keyboard.press("Enter")
            log("TECLA", "Enter", "Pressionado como fallback")

        wait_safe(page, 25000)
        time.sleep(2)

        current_url = page.url
        log("URL-ATUAL", current_url, "Apos login")
        screenshot(page, "03-pos-login")

        page_title = page.title()
        print(f"[INFO] Titulo: {page_title}")
        print(f"[INFO] URL: {current_url}")

        # Verificar se caiu em pagina de erro de login
        page_text_check = ""
        try:
            page_text_check = page.locator("body").inner_text()
        except Exception:
            pass

        if "login" in current_url.lower() or "invalid" in page_text_check.lower():
            log("AUTH", "login", "ATENCAO - Possivel falha de autenticacao detectada")
            screenshot(page, "03-erro-auth")

        # ====================================================
        # PASSO 4: Navegar para menu TIS
        # ====================================================
        print("\n=== PASSO 4/7: Procurando menu TIS ===")
        time.sleep(2)

        # Debug: listar links visiveis
        links = page.locator("a:visible").all()
        print(f"[INFO] Links visiveis na pagina: {len(links)}")
        for link in links[:50]:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 80:
                    print(f"  Link: '{texto}'")
            except Exception:
                pass

        tis_selectors = [
            "a:has-text('TIS')",
            "span:has-text('TIS')",
            "text=TIS",
            "li:has-text('TIS') > a",
            ".t-NavigationBar-item:has-text('TIS')",
            "nav a:has-text('TIS')",
            "[class*='menu'] :has-text('TIS')",
        ]

        tis_ok = try_click(page, tis_selectors, "Menu TIS")
        if tis_ok:
            wait_safe(page, 10000)
            time.sleep(2)
            screenshot(page, "04-menu-tis-aberto")
        else:
            screenshot(page, "04-menu-tis-nao-encontrado")
            # Debug de navegacao
            try:
                nav_text = page.locator("nav, [class*='nav'], [class*='menu']").first.inner_text()
                print(f"[DEBUG] Conteudo do menu:\n{nav_text[:2000]}")
            except Exception:
                pass
            try:
                body = page.locator("body").inner_text()
                print(f"[DEBUG] Texto da pagina:\n{body[:3000]}")
            except Exception:
                pass

        # ====================================================
        # PASSO 5: Clicar em Monitoramento de Jobs PSRM
        # ====================================================
        print("\n=== PASSO 5/7: Procurando Monitoramento de Jobs PSRM ===")
        time.sleep(2)

        # Debug: links apos clicar em TIS
        links2 = page.locator("a:visible").all()
        print(f"[INFO] Links apos menu TIS: {len(links2)}")
        for link in links2[:60]:
            try:
                texto = link.inner_text().strip()
                if texto and len(texto) < 120:
                    print(f"  Link: '{texto}'")
            except Exception:
                pass

        psrm_selectors = [
            "a:has-text('Monitoramento de Jobs PSRM')",
            "text=Monitoramento de Jobs PSRM",
            "a:has-text('Jobs PSRM')",
            "a:has-text('PSRM')",
            "span:has-text('Monitoramento de Jobs')",
            "li:has-text('Jobs PSRM') > a",
            "li:has-text('Monitoramento') > a",
        ]

        psrm_ok = try_click(page, psrm_selectors, "Monitoramento de Jobs PSRM")
        if psrm_ok:
            wait_safe(page, 15000)
            time.sleep(3)
            screenshot(page, "05-pagina-monitoramento-jobs")
        else:
            screenshot(page, "05-psrm-nao-encontrado")
            try:
                body = page.locator("body").inner_text()
                print(f"[DEBUG] Pagina atual:\n{body[:4000]}")
            except Exception:
                pass

        # ====================================================
        # PASSO 6: Localizar codigo batch CMJMSPC na tabela
        # ====================================================
        print(f"\n=== PASSO 6/7: Localizando batch '{TARGET_BATCH}' na tabela ===")
        time.sleep(2)

        current_url = page.url
        print(f"[INFO] URL da pagina de monitoramento: {current_url}")

        # Extrair texto completo da pagina
        page_text = ""
        try:
            page_text = page.locator("body").inner_text()
            print(f"\n[CONTEUDO DA PAGINA - primeiros 6000 chars]:\n{'='*60}")
            print(page_text[:6000])
            print("=" * 60)
        except Exception as e:
            print(f"[ERRO] Extrair texto: {e}")

        batch_encontrado = TARGET_BATCH in page_text
        print(f"\n[RESULTADO] '{TARGET_BATCH}' encontrado na pagina: {batch_encontrado}")

        if not batch_encontrado:
            log(
                "BUSCA",
                TARGET_BATCH,
                f"NAO ENCONTRADO - codigo batch '{TARGET_BATCH}' nao esta na tabela"
            )
            screenshot(page, "06-batch-nao-encontrado")
            print(f"\n[REGISTRO] O codigo batch '{TARGET_BATCH}' NAO foi encontrado na tabela.")
            print("[REGISTRO] Nenhuma acao de re-execucao sera disparada.")

            # Resumo final
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        # Batch encontrado - localizar a linha e extrair o tempo
        log("BUSCA", TARGET_BATCH, f"ENCONTRADO na pagina")

        # Tentar extrair a linha da tabela que contem CMJMSPC
        tempo_str = ""
        tempo_minutos = -1.0
        row_locator = None

        # Estrategia 1: buscar em linhas de tabela (tr)
        try:
            rows = page.locator("tr").all()
            print(f"[INFO] Total de linhas de tabela: {len(rows)}")
            for row in rows:
                try:
                    row_text = row.inner_text()
                    if TARGET_BATCH in row_text:
                        print(f"[INFO] Linha encontrada: {row_text.strip()[:300]}")
                        row_locator = row

                        # Tentar extrair coluna "Tempo" (geralmente a 4a ou 5a coluna)
                        cells = row.locator("td").all()
                        print(f"[INFO] Celulas na linha: {len(cells)}")
                        for i, cell in enumerate(cells):
                            cell_text = cell.inner_text().strip()
                            print(f"  Celula {i}: '{cell_text}'")
                            # Verificar se parece um tempo
                            if re.search(r"\d+\s*hs", cell_text, re.IGNORECASE):
                                tempo_str = cell_text
                                tempo_minutos = parse_tempo_minutes(tempo_str)
                                print(f"[INFO] Tempo encontrado: '{tempo_str}' = {tempo_minutos} min")
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"[AVISO] Erro ao buscar em tr: {e}")

        # Estrategia 2: se nao achou tempo em tr, buscar em divs/spans
        if not tempo_str:
            try:
                elements_with_hs = page.locator("td, span, div").filter(
                    has_text=re.compile(r"\d+hs", re.IGNORECASE)
                ).all()
                print(f"[INFO] Elementos com padrao de tempo: {len(elements_with_hs)}")
                for el in elements_with_hs[:10]:
                    try:
                        el_text = el.inner_text().strip()
                        print(f"  Tempo potencial: '{el_text}'")
                    except Exception:
                        pass
            except Exception as e:
                print(f"[AVISO] Erro busca alternativa tempo: {e}")

        screenshot(page, "06-batch-encontrado")

        # ====================================================
        # PASSO 7: Verificar tempo e executar acao
        # ====================================================
        print(f"\n=== PASSO 7/7: Avaliando tempo do job '{TARGET_BATCH}' ===")

        if tempo_str:
            print(f"[INFO] Tempo extraido: '{tempo_str}' ({tempo_minutos} minutos)")
        else:
            print(f"[AVISO] Nao foi possivel extrair o tempo automaticamente.")
            print(f"[AVISO] Verifique o screenshot '06-batch-encontrado.png' para confirmar o valor.")

        LIMITE_MINUTOS = 15

        if tempo_minutos < 0:
            log(
                "TEMPO",
                TARGET_BATCH,
                f"Nao foi possivel extrair o tempo - verificacao manual necessaria"
            )
            screenshot(page, "07-tempo-nao-extraido")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        if tempo_minutos > LIMITE_MINUTOS:
            log(
                "TEMPO",
                TARGET_BATCH,
                f"ACIMA DO LIMITE: {tempo_str} ({tempo_minutos} min) > {LIMITE_MINUTOS} min - "
                "Re-execucao necessaria"
            )
            print(f"\n[ACAO] Tempo acima do limite. Procurando botao de engrenagem na linha...")

            # Clicar na engrenagem da linha do CMJMSPC
            gear_selectors = []
            if row_locator is not None:
                gear_selectors = [
                    "button[title*='engren']",
                    "button[aria-label*='engren']",
                    "span.fa-cog",
                    "a[class*='cog']",
                    "button[class*='cog']",
                    ".fa-cog",
                    "button[title*='Action']",
                    "button[title*='acao']",
                    "a[class*='gear']",
                ]
                gear_clicked = False
                for sel in gear_selectors:
                    try:
                        gear_btn = row_locator.locator(sel).first
                        gear_btn.wait_for(timeout=3000, state="visible")
                        gear_btn.click()
                        log("CLICAR", sel, "Engrenagem clicada na linha do CMJMSPC")
                        gear_clicked = True
                        break
                    except Exception:
                        continue

                if not gear_clicked:
                    # Tentar clicar em qualquer botao/link na linha
                    try:
                        btn = row_locator.locator("button, a[href]").first
                        btn.click()
                        log("CLICAR", "botao-na-linha", "Botao generico clicado na linha")
                        gear_clicked = True
                    except Exception:
                        pass

                if not gear_clicked:
                    log(
                        "CLICAR",
                        "engrenagem",
                        "ERRO - Botao de engrenagem nao encontrado na linha"
                    )
                    screenshot(page, "07-erro-engrenagem-nao-encontrada")
                    _print_summary()
                    time.sleep(5)
                    browser.close()
                    return
            else:
                # Linha nao foi capturada como locator - buscar engrenagem globalmente
                # proxima a CMJMSPC no DOM
                gear_global = [
                    "button:near(:text('CMJMSPC'))",
                    "a:near(:text('CMJMSPC'))",
                ]
                gear_clicked = False
                for sel in gear_global:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.click(sel)
                        log("CLICAR", sel, "Engrenagem clicada (busca global)")
                        gear_clicked = True
                        break
                    except Exception:
                        continue

                if not gear_clicked:
                    log(
                        "CLICAR",
                        "engrenagem-global",
                        "ERRO - Nao foi possivel clicar na engrenagem"
                    )
                    screenshot(page, "07-erro-sem-engrenagem")
                    _print_summary()
                    time.sleep(5)
                    browser.close()
                    return

            wait_safe(page, 5000)
            time.sleep(1)
            screenshot(page, "07-popup-apos-engrenagem")

            # Clicar em Re-executar no popup
            reexec_selectors = [
                "button:has-text('Re-executar')",
                "a:has-text('Re-executar')",
                "text=Re-executar",
                "button:has-text('Reexecutar')",
                "button:has-text('Re executar')",
                "[class*='button']:has-text('Re-executar')",
            ]
            reexec_ok = try_click(page, reexec_selectors, "Re-executar")

            if reexec_ok:
                wait_safe(page, 5000)
                time.sleep(1)

                # Confirmar dialogo se existir
                try:
                    page.on("dialog", lambda d: d.accept())
                except Exception:
                    pass

                # Tentar accept em dialog nativo do browser
                try:
                    page.wait_for_selector(
                        "button:has-text('OK'), button:has-text('Sim'), button:has-text('Confirmar')",
                        timeout=3000
                    )
                    try_click(
                        page,
                        [
                            "button:has-text('OK')",
                            "button:has-text('Sim')",
                            "button:has-text('Confirmar')",
                        ],
                        "Confirmacao de re-execucao"
                    )
                except Exception:
                    pass

                wait_safe(page, 8000)
                time.sleep(2)
                screenshot(page, "07-resultado-reexecucao")
                log(
                    "RESULTADO",
                    TARGET_BATCH,
                    f"Re-execucao disparada com sucesso. Tempo era: {tempo_str}"
                )
                print(
                    f"\n[RESULTADO FINAL] Job '{TARGET_BATCH}' RE-EXECUTADO."
                    f" Tempo estava: {tempo_str} ({tempo_minutos} min > {LIMITE_MINUTOS} min)"
                )
            else:
                screenshot(page, "07-erro-reexecutar-nao-encontrado")
                log("RESULTADO", "Re-executar", "ERRO - Botao Re-executar nao encontrado no popup")

        else:
            log(
                "TEMPO",
                TARGET_BATCH,
                f"DENTRO DO LIMITE: {tempo_str} ({tempo_minutos} min) <= {LIMITE_MINUTOS} min - "
                "Nenhuma acao necessaria"
            )
            screenshot(page, "07-job-dentro-do-tempo")
            print(
                f"\n[RESULTADO FINAL] Job '{TARGET_BATCH}' esta DENTRO DO TEMPO ESPERADO."
                f" Tempo: {tempo_str} ({tempo_minutos} min) - limite: {LIMITE_MINUTOS} min."
                f" Nenhuma acao tomada."
            )

        _print_summary()
        time.sleep(5)
        browser.close()


def _print_summary() -> None:
    print(f"\n\n{'='*60}")
    print("RESUMO DA EXECUCAO ARGOS:")
    print(f"{'='*60}")
    for line in log_lines:
        print(line)
    print(f"\nScreenshots salvos em: {SCREENSHOTS_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run()
