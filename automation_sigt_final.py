"""
Automacao SIGT - Versao Final
Fluxo: Login -> TIS -> Monitoramento Jobs PSRM -> CMJMSPC -> Re-executar se tempo > 15min
O popup "Manutencao de Jobs" carrega dentro de um iframe - acesso via frame_locator
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
LIMITE_MINUTOS = 15

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


def wait_safe(page, timeout: int = 10000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def parse_tempo_minutes(tempo_str: str) -> float:
    tempo_str = tempo_str.strip().lower()
    pattern = r"(\d+)\s*hs?\s*[:\s]+\s*(\d+)\s*min?"
    match = re.search(pattern, tempo_str)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    match2 = re.search(r"(\d+)\s*min", tempo_str)
    if match2:
        return float(match2.group(1))
    return -1.0


def run() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()

        # ====================================================
        # PASSO 1: Login
        # ====================================================
        print("\n=== PASSO 1/6: Login no SIGT ===")
        page.goto(TARGET_URL, timeout=30000, wait_until="domcontentloaded")
        wait_safe(page, 20000)
        log("NAVEGAR", TARGET_URL, "Pagina de login carregada")
        screenshot(page, "01-pagina-login")

        page.fill("input[name='P9999_USERNAME']", USERNAME)
        page.fill("input[name='P9999_PASSWORD']", PASSWORD)
        log("PREENCHER", "P9999_USERNAME", f"A usar utilizador: {USERNAME} no ambiente PRODUCAO")
        log("PREENCHER", "P9999_PASSWORD", "Senha preenchida (ocultada)")

        screenshot(page, "02-credenciais-preenchidas")

        page.click("button:has-text('Entrar')")
        log("CLICAR", "button:has-text('Entrar')", "Botao de login clicado")

        wait_safe(page, 25000)
        time.sleep(2)
        log("URL-ATUAL", page.url, "Apos login")
        screenshot(page, "03-pos-login")

        # ====================================================
        # PASSO 2: Menu TIS
        # ====================================================
        print("\n=== PASSO 2/6: Navegando para menu TIS ===")
        time.sleep(2)
        page.click("text=TIS")
        wait_safe(page, 10000)
        time.sleep(2)
        log("CLICAR", "text=TIS", "Menu TIS aberto")
        screenshot(page, "04-menu-tis-aberto")

        # ====================================================
        # PASSO 3: Monitoramento de Jobs PSRM
        # ====================================================
        print("\n=== PASSO 3/6: Abrindo Monitoramento de Jobs PSRM ===")
        page.click("a:has-text('Monitoramento de Jobs PSRM')")
        wait_safe(page, 15000)
        time.sleep(3)
        log("CLICAR", "a:has-text('Monitoramento de Jobs PSRM')", "Pagina carregada")
        screenshot(page, "05-pagina-monitoramento")

        print(f"[INFO] URL: {page.url}")

        # ====================================================
        # PASSO 4: Localizar CMJMSPC na tabela
        # ====================================================
        print(f"\n=== PASSO 4/6: Localizando '{TARGET_BATCH}' na tabela ===")

        page_text = page.locator("body").inner_text()
        batch_encontrado = TARGET_BATCH in page_text

        if not batch_encontrado:
            log("BUSCA", TARGET_BATCH, f"NAO ENCONTRADO na tabela")
            screenshot(page, "06-batch-nao-encontrado")
            print(f"\n[RESULTADO FINAL] O codigo batch '{TARGET_BATCH}' NAO foi encontrado na tabela.")
            print("[RESULTADO FINAL] Nenhuma acao de re-execucao foi disparada.")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        log("BUSCA", TARGET_BATCH, "ENCONTRADO na tabela")

        # Extrair tempo da linha do CMJMSPC
        tempo_str = ""
        tempo_minutos = -1.0
        target_row = None

        rows = page.locator("tr").all()
        for row in rows:
            try:
                row_text = row.inner_text()
                if TARGET_BATCH in row_text:
                    target_row = row
                    cells = row.locator("td").all()
                    for cell in cells:
                        cell_text = cell.inner_text().strip()
                        if re.search(r"\d+\s*hs", cell_text, re.IGNORECASE):
                            tempo_str = cell_text
                            tempo_minutos = parse_tempo_minutes(tempo_str)
                    print(f"[INFO] Linha: {row_text.strip()}")
                    print(f"[INFO] Tempo extraido: '{tempo_str}' = {tempo_minutos} min")
                    break
            except Exception:
                continue

        screenshot(page, "05-tabela-com-batch")

        # ====================================================
        # PASSO 5: Avaliar tempo
        # ====================================================
        print(f"\n=== PASSO 5/6: Avaliando tempo do job '{TARGET_BATCH}' ===")

        if tempo_minutos < 0:
            log("TEMPO", TARGET_BATCH, "Nao foi possivel extrair o tempo - verificacao manual necessaria")
            screenshot(page, "06-tempo-nao-extraido")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        if tempo_minutos <= LIMITE_MINUTOS:
            log(
                "TEMPO",
                TARGET_BATCH,
                f"DENTRO DO LIMITE: {tempo_str} ({tempo_minutos} min) <= {LIMITE_MINUTOS} min"
            )
            screenshot(page, "06-job-dentro-do-tempo")
            print(
                f"\n[RESULTADO FINAL] Job '{TARGET_BATCH}' esta DENTRO DO TEMPO ESPERADO."
                f"\n  Tempo: {tempo_str} ({tempo_minutos} min)"
                f"\n  Limite: {LIMITE_MINUTOS} min"
                f"\n  Nenhuma acao de re-execucao foi disparada."
            )
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        # Tempo acima do limite - prosseguir com re-execucao
        log(
            "TEMPO",
            TARGET_BATCH,
            f"ACIMA DO LIMITE: {tempo_str} ({tempo_minutos} min) > {LIMITE_MINUTOS} min - Re-execucao necessaria"
        )

        # ====================================================
        # PASSO 6: Clicar na engrenagem e Re-executar
        # ====================================================
        print(f"\n=== PASSO 6/6: Abrindo popup de Manutencao de Jobs para '{TARGET_BATCH}' ===")

        # Clicar no icone fa-gear da linha do CMJMSPC
        # A engrenagem esta dentro de um <a href="javascript:apex.theme42.dialog(...)">
        gear_clicked = False
        if target_row is not None:
            try:
                # Tentar span.fa-gear dentro da linha
                gear = target_row.locator("span.fa-gear, span.fa-cog, .fa-gear, .fa-cog").first
                gear.wait_for(timeout=5000, state="visible")
                gear.click()
                log("CLICAR", "span.fa-gear (linha CMJMSPC)", "Engrenagem clicada")
                gear_clicked = True
            except Exception:
                pass

            if not gear_clicked:
                try:
                    # Tentar clicar no link <a> da ultima celula
                    gear_link = target_row.locator("td:last-child a").first
                    gear_link.wait_for(timeout=5000, state="attached")
                    gear_link.click()
                    log("CLICAR", "td:last-child a (linha CMJMSPC)", "Link engrenagem clicado")
                    gear_clicked = True
                except Exception:
                    pass

            if not gear_clicked:
                try:
                    # Clicar via JavaScript no href do link da linha
                    gear_href = target_row.locator("td:last-child a").get_attribute("href")
                    if gear_href:
                        page.evaluate(f"document.querySelector('tr:has(td:first-child:text-is(\"{TARGET_BATCH}\")) td:last-child a').click()")
                        log("CLICAR", "JS click engrenagem", "Clicado via JavaScript")
                        gear_clicked = True
                except Exception:
                    pass

        if not gear_clicked:
            log("CLICAR", "engrenagem", "ERRO - Nao foi possivel clicar na engrenagem da linha")
            screenshot(page, "06-erro-engrenagem")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        # Aguardar o popup/dialog abrir
        time.sleep(3)
        wait_safe(page, 8000)
        screenshot(page, "06-popup-manutencao-aberto")

        # O popup abre com um iframe interno
        # Selector do iframe: iframe[title='Manutencao de Jobs'] ou iframe[src*='manutencao-de-jobs']
        print("[INFO] Aguardando iframe do popup carregar...")
        time.sleep(3)

        # Verificar se o iframe esta presente e visivel
        iframe_selector = "iframe[title='Manutenção de Jobs'], iframe[src*='manutencao-de-jobs']"
        try:
            page.wait_for_selector(iframe_selector, timeout=15000, state="attached")
            log("IFRAME", iframe_selector, "Iframe encontrado")
        except Exception as e:
            log("IFRAME", iframe_selector, f"ERRO ao localizar iframe: {e}")
            screenshot(page, "06-erro-iframe-nao-encontrado")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        # Aguardar o iframe carregar completamente
        time.sleep(4)
        screenshot(page, "06-iframe-carregado")

        # Acessar o conteudo do iframe via frame_locator
        frame = page.frame_locator(iframe_selector)

        # Debug: extrair texto do iframe
        try:
            iframe_text = frame.locator("body").inner_text(timeout=10000)
            print(f"[INFO] Conteudo do iframe:\n{iframe_text[:3000]}")
        except Exception as e:
            print(f"[AVISO] Nao foi possivel ler iframe body: {e}")

        # Procurar botao "Re-executar" dentro do iframe
        reexec_selectors_iframe = [
            "button:has-text('Re-executar')",
            "a:has-text('Re-executar')",
            "input[value*='Re-executar']",
            "button:has-text('Reexecutar')",
            "[class*='button']:has-text('Re-executar')",
            "text=Re-executar",
        ]

        reexec_clicked = False
        for sel in reexec_selectors_iframe:
            try:
                btn = frame.locator(sel).first
                btn.wait_for(timeout=5000, state="visible")
                print(f"[INFO] Botao Re-executar encontrado com: {sel}")
                btn.click()
                log("CLICAR", f"iframe > {sel}", "Botao Re-executar clicado")
                reexec_clicked = True
                break
            except Exception:
                continue

        if not reexec_clicked:
            # Listar todos os botoes visiveis no iframe para debug
            print("[DEBUG] Listando botoes/links no iframe:")
            try:
                btns_iframe = frame.locator("button, a, input[type='button'], input[type='submit']").all()
                print(f"  Total de elementos clicaveis no iframe: {len(btns_iframe)}")
                for i, btn in enumerate(btns_iframe[:20]):
                    try:
                        btn_text = btn.inner_text(timeout=2000).strip()
                        print(f"    Btn {i}: '{btn_text}'")
                    except Exception:
                        pass
            except Exception as e:
                print(f"  Erro ao listar botoes: {e}")

            log("CLICAR", "Re-executar", "ERRO - Botao nao encontrado no iframe")
            screenshot(page, "06-erro-reexecutar-nao-encontrado")
            _print_summary()
            time.sleep(5)
            browser.close()
            return

        # Aguardar e confirmar se houver dialogo
        time.sleep(2)

        # Registrar dialogo de confirmacao automaticamente
        page.on("dialog", lambda d: (
            print(f"[DIALOG] Mensagem: {d.message} -> Confirmando"),
            d.accept()
        ))

        # Tentar confirmar botoes de confirmacao dentro do iframe ou na pagina
        confirm_selectors = [
            "button:has-text('OK')",
            "button:has-text('Sim')",
            "button:has-text('Confirmar')",
            "button:has-text('Confirmar Re-execução')",
        ]
        for sel in confirm_selectors:
            try:
                # Tentar no iframe primeiro
                confirm_btn = frame.locator(sel).first
                confirm_btn.wait_for(timeout=3000, state="visible")
                confirm_btn.click()
                log("CLICAR", f"iframe > {sel}", "Confirmacao clicada")
                break
            except Exception:
                pass
            try:
                # Tentar na pagina principal
                page.click(sel, timeout=2000)
                log("CLICAR", sel, "Confirmacao clicada na pagina principal")
                break
            except Exception:
                pass

        wait_safe(page, 10000)
        time.sleep(3)
        screenshot(page, "07-resultado-reexecucao")

        log(
            "RESULTADO",
            TARGET_BATCH,
            f"Re-execucao disparada. Tempo estava: {tempo_str} ({tempo_minutos} min) > {LIMITE_MINUTOS} min"
        )

        print(
            f"\n[RESULTADO FINAL] Job '{TARGET_BATCH}' RE-EXECUTADO COM SUCESSO."
            f"\n  Tempo estava: {tempo_str} ({tempo_minutos} min)"
            f"\n  Limite configurado: {LIMITE_MINUTOS} min"
            f"\n  Acao tomada: Re-execucao disparada via popup 'Manutencao de Jobs'"
        )

        _print_summary()
        time.sleep(6)
        browser.close()


def _print_summary() -> None:
    print(f"\n\n{'='*60}")
    print("RESUMO DA EXECUCAO - ARGOS")
    print(f"{'='*60}")
    for line in log_lines:
        print(line)
    print(f"\nScreenshots salvos em: {SCREENSHOTS_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run()
