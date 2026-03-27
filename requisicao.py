import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import base64
import time
import threading

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


# ============================================================
# FUNÇÕES DE SCRAPING — SISGAT
# ============================================================

@st.cache_data(ttl=3600, hash_funcs={requests.Session: lambda _: None})
def login_sisgat(url_base, username, password):
    session = requests.Session()
    login_url = f"{url_base}/users/login"

    try:
        login_page_response = session.get(login_url)
        login_page_response.raise_for_status()
        login_soup = BeautifulSoup(login_page_response.text, 'html.parser')

        csrf_token_input = login_soup.find('input', {'name': '_csrfToken'})
        csrf_token = csrf_token_input['value'] if csrf_token_input else None

        login_data = {'username': username, 'password': password}
        if csrf_token:
            login_data['_csrfToken'] = csrf_token

        login_response = session.post(login_url, data=login_data, allow_redirects=True)
        login_response.raise_for_status()

        if "login" not in login_response.url.lower() and "Acesso não autorizado" not in login_response.text:
            return session, "Login bem-sucedido!"
        else:
            return None, "Falha no login. Credenciais inválidas."

    except requests.exceptions.RequestException as e:
        return None, f"Erro na requisição de login: {e}"
    except Exception as e:
        return None, f"Erro durante o login: {e}"


@st.cache_data(ttl=600, hash_funcs={requests.Session: lambda _: None})
def obter_boletos_solicitados(session, url_base="https://sisgat.cbm.am.gov.br"):
    url_boletos = f"{url_base}/boletos-solicitados"

    try:
        response = session.get(url_boletos)
        response.raise_for_status()

        if 'text/html' not in response.headers.get('Content-Type', ''):
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        boletos = []

        processo_header = soup.find('th', string='Nº do Processo')
        table = None
        if processo_header:
            table = processo_header.find_parent('table')

        if not table:
            return []

        headers = [th.get_text(strip=True) for th in table.find('thead').find_all('th')]
        clean_headers = []
        for h in headers:
            cleaned_h = re.sub(r'[^a-zA-Z0-9_]', '', h.lower().replace(' ', '_').replace('º', ''))
            clean_headers.append(cleaned_h)

        for row in table.find('tbody').find_all('tr'):
            cols = row.find_all('td')
            if len(cols) >= len(clean_headers) - 1:
                boleto_data = {}
                for i, header in enumerate(clean_headers):
                    if i < len(cols):
                        boleto_data[header] = cols[i].get_text(strip=True)

                action_col = cols[-1]
                view_link = action_col.find('a', string='Ver')
                if view_link and 'href' in view_link.attrs:
                    match = re.search(r'/view/(\d+)', view_link['href'])
                    if match:
                        boleto_data['id_boleto'] = match.group(1)

                boletos.append(boleto_data)

        return boletos

    except Exception:
        return []


@st.cache_data(ttl=600, hash_funcs={requests.Session: lambda _: None})
def obter_detalhes_boleto_sisgat(session, boleto_id, url_base="https://sisgat.cbm.am.gov.br"):
    url_view = f"{url_base}/boletos-solicitados/view/{boleto_id}"

    try:
        response = session.get(url_view)
        response.raise_for_status()

        if 'text/html' not in response.headers.get('Content-Type', ''):
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        detalhes = {}

        def extract_detail(label_text):
            try:
                th_element = soup.find('th', string=lambda text: text and label_text in text)
                if th_element:
                    td_element = th_element.find_next_sibling('td')
                    if td_element:
                        return td_element.get_text(strip=True)
            except Exception:
                pass
            return None

        def extract_boleto_link(label_text):
            try:
                th_element = soup.find('th', string=lambda text: text and label_text in text)
                if th_element:
                    td_element = th_element.find_next_sibling('td')
                    if td_element:
                        link_tag = td_element.find('a')
                        texto = td_element.get_text(strip=True)
                        href = link_tag['href'] if link_tag and 'href' in link_tag.attrs else None
                        return texto, href
            except Exception:
                pass
            return None, None

        h3_element = soup.find('h3', string=lambda text: text and 'Visualização de Solicitação de Boleto para o Processo Nº' in text)
        if h3_element:
            span = h3_element.find('span', style=lambda s: s and 'font-size:2rem; color:red;' in s)
            if span:
                detalhes['numero_processo'] = span.get_text(strip=True)

        detalhes['usuario_solicitante']       = extract_detail('Usuário Solicitante')
        detalhes['servidor_dat_gerou_boleto'] = extract_detail('Servidor DAT que gerou o boleto')
        if 'numero_processo' not in detalhes or not detalhes['numero_processo']:
            detalhes['numero_processo']       = extract_detail('Nº do Processo')

        detalhes['razao_social']              = extract_detail('Razão Social / Nome Fantasia do Cliente')
        detalhes['cpf_cnpj']                  = extract_detail('CPF/CNPJ')
        detalhes['telefone']                  = extract_detail('Telefone')
        detalhes['email']                     = extract_detail('Email')
        detalhes['tipo_taxa_solicitada']      = extract_detail('Tipo de Taxa Solicitada')
        detalhes['protecao_requerida']        = extract_detail('Proteção Requerida')
        detalhes['cep']                       = extract_detail('CEP')
        detalhes['endereco']                  = extract_detail('Endereço')
        detalhes['meu_numero']                = extract_detail('Meu Número')
        detalhes['mensagem']                  = extract_detail('Mensagem')
        detalhes['area_edificada']            = extract_detail('Area Edificada')
        detalhes['valor']                     = extract_detail('Valor')
        detalhes['status']                    = extract_detail('Status')
        detalhes['data_solicitacao_boleto']   = extract_detail('Data da Solicitação do Boleto')
        detalhes['data_ultima_edicao_boleto'] = extract_detail('Data da Última Edição do Boleto')

        boleto_texto, boleto_href = extract_boleto_link('Boleto')
        detalhes['boleto_anexado_texto'] = boleto_texto
        detalhes['boleto_anexado_href']  = boleto_href

        if detalhes.get('valor'):
            detalhes['valor'] = detalhes['valor'].replace('R$', '').replace('.', '').replace(',', '.').strip()
        if detalhes.get('cpf_cnpj'):
            detalhes['cpf_cnpj'] = re.sub(r'\D', '', detalhes['cpf_cnpj'])
        if detalhes.get('area_edificada'):
            detalhes['area_edificada'] = detalhes['area_edificada'].replace(' m²', '').replace(',', '.').strip()

        detalhes['nome_pagador']               = detalhes.get('razao_social')
        detalhes['cnpj_pagador']               = detalhes.get('cpf_cnpj')
        detalhes['endereco_completo_pagador']  = detalhes.get('endereco')

        if detalhes.get('numero_processo') and detalhes.get('tipo_taxa_solicitada'):
            detalhes['mensagem_boleto_para_banco'] = (
                f"Processo: {detalhes['numero_processo']}, "
                f"Tipo de Taxa: {detalhes['tipo_taxa_solicitada']}"
            )
        else:
            detalhes['mensagem_boleto_para_banco'] = detalhes.get('mensagem', 'Mensagem não disponível')

        detalhes_limpos = {k: v for k, v in detalhes.items() if v is not None and str(v).strip() != ''}
        return detalhes_limpos if detalhes_limpos else None

    except Exception as e:
        st.error(f"Erro ao parsear detalhes do boleto {boleto_id}: {e}")
        return None


# ============================================================
# AUTOMAÇÃO BRADESCO — SELENIUM (preenche e aguarda o usuário)
# ============================================================

BRADESCO_URL_BASE  = "https://www.ne2.bradesconetempresa.b.br"
BRADESCO_LOGIN_URL = f"{BRADESCO_URL_BASE}/ibpjlogin/login.jsf"


def criar_driver():
    """
    Cria o ChromeDriver em modo VISÍVEL para que o usuário
    possa acompanhar e finalizar a emissão manualmente.
    """
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def preencher_campo(driver, wait, seletores: list[tuple], valor: str, log_fn=None):
    """
    Tenta preencher um campo usando uma lista de seletores (By, valor).
    Para cada seletor, tenta localizar e preencher. Ignora se não encontrar.
    """
    for by, seletor in seletores:
        try:
            el = wait.until(EC.presence_of_element_located((by, seletor)))
            el.click()
            el.clear()
            el.send_keys(str(valor))
            if log_fn:
                log_fn(f"   ✅ Preenchido '{seletor}' com '{str(valor)[:40]}'")
            return True
        except Exception:
            continue
    if log_fn:
        log_fn(f"   ⚠️  Campo não encontrado para valor '{str(valor)[:40]}' — pulando.")
    return False


def preencher_select(driver, wait, seletores: list[tuple], valor: str, log_fn=None):
    """Seleciona uma opção em um <select> pelo texto visível ou valor."""
    for by, seletor in seletores:
        try:
            el = wait.until(EC.presence_of_element_located((by, seletor)))
            sel = Select(el)
            try:
                sel.select_by_visible_text(valor)
            except Exception:
                sel.select_by_value(valor)
            if log_fn:
                log_fn(f"   ✅ Select '{seletor}' → '{valor}'")
            return True
        except Exception:
            continue
    return False


def abrir_bradesco_e_preencher(
    login: str,
    senha: str,
    dados: dict,
    log_fn=None
) -> tuple[bool, str]:
    """
    Abre o Chrome, loga no Bradesco Net Empresa, navega até
    Cobrança > Emitir Boleto e preenche todos os campos com
    os dados do SISGAT.

    O navegador permanece ABERTO para o usuário revisar e
    clicar em Confirmar/Emitir manualmente.

    Retorna (sucesso, mensagem).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    driver = None

    try:
        log("🌐 Abrindo Chrome...")
        driver = criar_driver()
        wait   = WebDriverWait(driver, 25)

        # ── PASSO 1: LOGIN ──────────────────────────────────────────
        log(f"🔑 Acessando {BRADESCO_LOGIN_URL}")
        driver.get(BRADESCO_LOGIN_URL)
        time.sleep(2)

        log("📝 Preenchendo credenciais...")

        # Seletores possíveis para campo de usuário e senha
        # O Bradesco Net Empresa JSF usa IDs como 'form:j_id_...' que variam —
        # por isso fornecemos múltiplas alternativas em ordem de prioridade.
        preencher_campo(driver, wait, [
            (By.CSS_SELECTOR, "input[name*='usuario']"),
            (By.CSS_SELECTOR, "input[name*='login']"),
            (By.CSS_SELECTOR, "input[name*='cpf']"),
            (By.CSS_SELECTOR, "input[id*='usuario']"),
            (By.CSS_SELECTOR, "input[id*='login']"),
            (By.XPATH,        "//input[@type='text'][1]"),
        ], login, log_fn=log)

        preencher_campo(driver, wait, [
            (By.CSS_SELECTOR, "input[name*='senha']"),
            (By.CSS_SELECTOR, "input[name*='password']"),
            (By.CSS_SELECTOR, "input[name*='pwd']"),
            (By.CSS_SELECTOR, "input[id*='senha']"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ], senha, log_fn=log)

        # Clica no botão de entrar
        log("🖱️  Clicando em Entrar...")
        try:
            btn = wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//input[@type='submit'] | //button[@type='submit'] | "
                "//input[contains(@value,'Entrar')] | //input[contains(@value,'Acessar')]"
            )))
            btn.click()
        except TimeoutException:
            log("⚠️  Botão de submit não encontrado via XPath padrão — tentando JS click...")
            driver.execute_script(
                "document.querySelector('input[type=submit], button[type=submit]').click()"
            )

        time.sleep(3)

        # Verifica se ainda está no login
        if "login" in driver.current_url.lower():
            return False, (
                "❌ Login falhou. Verifique as credenciais ou se o site "
                "exige certificado digital / token físico."
            )

        log("✅ Login realizado. Página atual: " + driver.current_url)

        # ── PASSO 2: NAVEGAR ATÉ COBRANÇA ──────────────────────────
        log("📂 Procurando menu de Cobrança...")
        try:
            menu_cob = wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//*[contains(text(),'Cobrança') or contains(text(),'cobrança') "
                "or contains(text(),'COBRANÇA')]"
            )))
            menu_cob.click()
            time.sleep(2)
            log("✅ Menu Cobrança clicado.")
        except TimeoutException:
            log("⚠️  Menu Cobrança não encontrado automaticamente.")
            log("    Tentando URL direta: /ibpjcobranca/cobranca.jsf")
            driver.get(f"{BRADESCO_URL_BASE}/ibpjcobranca/cobranca.jsf")
            time.sleep(2)

        # ── PASSO 3: NAVEGAR ATÉ EMITIR BOLETO ─────────────────────
        log("📄 Procurando opção Emitir Boleto...")
        try:
            emitir = wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//*[contains(text(),'Emitir') or contains(text(),'emitir') "
                "or contains(text(),'Boleto') or contains(text(),'boleto') "
                "or contains(text(),'Título') or contains(text(),'título')]"
            )))
            emitir.click()
            time.sleep(2)
            log("✅ Tela de emissão acessada.")
        except TimeoutException:
            log("⚠️  Link de emissão não encontrado. Tentando URL direta...")
            driver.get(f"{BRADESCO_URL_BASE}/ibpjcobranca/emissaoBoleto.jsf")
            time.sleep(2)

        log(f"📍 Página atual: {driver.current_url}")

        # ── PASSO 4: PREENCHER DADOS DO BOLETO ─────────────────────
        log("✏️  Preenchendo dados do boleto...")

        # Nosso Número / Meu Número
        if dados.get('meu_numero'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='nossoNumero']"),
                (By.CSS_SELECTOR, "input[id*='nossoNumero']"),
                (By.CSS_SELECTOR, "input[name*='nroTitulo']"),
                (By.CSS_SELECTOR, "input[name*='meuNumero']"),
                (By.CSS_SELECTOR, "input[id*='meuNumero']"),
            ], dados['meu_numero'], log_fn=log)

        # Valor
        if dados.get('valor'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='valor']"),
                (By.CSS_SELECTOR, "input[id*='valor']"),
                (By.CSS_SELECTOR, "input[name*='vlrTitulo']"),
                (By.CSS_SELECTOR, "input[name*='vlNominal']"),
            ], dados['valor'], log_fn=log)

        # Data de Vencimento
        if dados.get('vencimento'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='vencimento']"),
                (By.CSS_SELECTOR, "input[id*='vencimento']"),
                (By.CSS_SELECTOR, "input[name*='dtVencimento']"),
                (By.CSS_SELECTOR, "input[name*='dataVenc']"),
            ], dados['vencimento'], log_fn=log)

        # Nome do Pagador
        if dados.get('nome_pagador'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='nomePagador']"),
                (By.CSS_SELECTOR, "input[id*='nomePagador']"),
                (By.CSS_SELECTOR, "input[name*='nome']"),
                (By.CSS_SELECTOR, "input[id*='nomePag']"),
            ], dados['nome_pagador'], log_fn=log)

        # CPF / CNPJ
        if dados.get('cpf_cnpj'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='cpfCnpj']"),
                (By.CSS_SELECTOR, "input[id*='cpfCnpj']"),
                (By.CSS_SELECTOR, "input[name*='cnpj']"),
                (By.CSS_SELECTOR, "input[name*='cpf']"),
                (By.CSS_SELECTOR, "input[id*='docPagador']"),
            ], dados['cpf_cnpj'], log_fn=log)

        # Endereço
        if dados.get('endereco'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='endereco']"),
                (By.CSS_SELECTOR, "input[id*='endereco']"),
                (By.CSS_SELECTOR, "input[name*='logradouro']"),
                (By.CSS_SELECTOR, "input[name*='endPagador']"),
            ], dados['endereco'], log_fn=log)

        # CEP
        if dados.get('cep'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='cep']"),
                (By.CSS_SELECTOR, "input[id*='cep']"),
                (By.CSS_SELECTOR, "input[name*='cepPagador']"),
            ], dados['cep'], log_fn=log)

        # Instrução / Mensagem
        if dados.get('mensagem_boleto_para_banco'):
            preencher_campo(driver, WebDriverWait(driver, 10), [
                (By.CSS_SELECTOR, "input[name*='instrucao']"),
                (By.CSS_SELECTOR, "textarea[name*='instrucao']"),
                (By.CSS_SELECTOR, "input[id*='instrucao']"),
                (By.CSS_SELECTOR, "input[name*='mensagem']"),
                (By.CSS_SELECTOR, "textarea[name*='mensagem']"),
                (By.CSS_SELECTOR, "input[name*='obs']"),
            ], dados['mensagem_boleto_para_banco'], log_fn=log)

        # Espera visual para o usuário ver o preenchimento
        time.sleep(1)

        log("")
        log("━" * 50)
        log("✅ DADOS PREENCHIDOS COM SUCESSO!")
        log("━" * 50)
        log("👉 O navegador está aberto e aguardando.")
        log("   Revise os campos, ajuste se necessário")
        log("   e clique em CONFIRMAR / EMITIR no site.")
        log("━" * 50)

        # O driver permanece aberto — NÃO chama driver.quit()
        # O processo Streamlit mantém a referência para não fechar o Chrome
        st.session_state['driver_aberto'] = driver
        return True, "Navegador aberto com os dados preenchidos. Confirme a emissão no Chrome."

    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        return False, f"❌ Erro durante a automação: {e}"


# ============================================================
# CONFIGURAÇÃO DO STREAMLIT
# ============================================================

st.set_page_config(layout="wide", page_title="SISGAT + Bradesco — Gestão de Boletos")
st.title("🔥 SISGAT — Gestão de Boletos CBM/AM")

SISGAT_URL_BASE = "https://sisgat.cbm.am.gov.br"

# ============================================================
# BARRA LATERAL
# ============================================================

with st.sidebar:
    st.header("🔐 Acesso ao SISGAT")
    username = st.text_input("Usuário SISGAT", value="ALLAN_ATD")
    password = st.text_input("Senha SISGAT", type="password", value="123456")

    if st.button("🚀 Fazer Login e Carregar Processos"):
        login_sisgat.clear()
        obter_boletos_solicitados.clear()
        obter_detalhes_boleto_sisgat.clear()

        with st.spinner("Autenticando no SISGAT..."):
            st.session_state['session'], st.session_state['login_status'] = login_sisgat(
                SISGAT_URL_BASE, username, password
            )

        if st.session_state['session']:
            with st.spinner("Carregando processos..."):
                st.session_state['processos_listados'] = obter_boletos_solicitados(
                    st.session_state['session'], SISGAT_URL_BASE
                )
            total = len(st.session_state['processos_listados'])
            st.success(f"✅ {total} processo(s) carregado(s).")
        else:
            st.session_state['processos_listados'] = []
            st.error(st.session_state['login_status'])

    st.markdown("---")
    st.header("🏦 Credenciais Bradesco")
    st.caption("Usadas apenas quando o boleto não está anexado no SISGAT.")
    bradesco_login = st.text_input("Login Bradesco", value="mpps00033")
    bradesco_senha = st.text_input("Senha Bradesco", type="password", value="832cbmam")
    st.session_state['bradesco_login'] = bradesco_login
    st.session_state['bradesco_senha'] = bradesco_senha

    st.markdown("---")

    if 'processos_listados' in st.session_state and st.session_state['processos_listados']:
        st.subheader("📋 Selecione um Processo")

        processo_options = ["Selecione um processo..."] + [
            f"{p.get('n_do_processo', 'N/A')} - {p.get('cliente', 'N/A')} - {p.get('tipo_de_taxa', 'N/A')}"
            for p in st.session_state['processos_listados']
        ]

        selected_process_display = st.selectbox(
            "Processos Disponíveis",
            processo_options,
            key="selected_process_display"
        )

        selected_process = None
        if selected_process_display != "Selecione um processo...":
            m = re.match(r'(\d+)', selected_process_display)
            if m:
                num = m.group(1)
                for p in st.session_state['processos_listados']:
                    if p.get('n_do_processo') == num:
                        selected_process = p
                        break

        st.session_state['selected_process'] = selected_process

    elif 'login_status' in st.session_state and st.session_state['login_status'] == "Login bem-sucedido!":
        st.warning("Nenhum processo encontrado.")


# ============================================================
# ÁREA PRINCIPAL
# ============================================================

if 'selected_process' in st.session_state and st.session_state['selected_process']:
    processo   = st.session_state['selected_process']
    processo_id = processo.get('id_boleto')

    if processo_id and 'session' in st.session_state and st.session_state['session']:

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Nº do Processo", processo.get('n_do_processo', 'N/A'))
        with col2:
            st.metric("Cliente", processo.get('cliente', 'N/A'))
        with col3:
            st.metric("Tipo de Taxa", processo.get('tipo_de_taxa', 'N/A'))

        st.markdown("---")

        with st.spinner("Carregando detalhes do processo..."):
            detalhes = obter_detalhes_boleto_sisgat(
                st.session_state['session'], processo_id, SISGAT_URL_BASE
            )

        if detalhes:

            # ── STATUS DO BOLETO ────────────────────────────────────
            st.subheader("📎 Status do Boleto no SISGAT")

            boleto_texto = detalhes.get('boleto_anexado_texto')
            boleto_href  = detalhes.get('boleto_anexado_href')
            boleto_vazio = not boleto_texto or boleto_texto.strip() in ('', '-', 'N/A', 'Não informado', 'Nenhum')

            if not boleto_vazio:
                # ── BOLETO JÁ ANEXADO ───────────────────────────────
                st.success("✅ **Boleto já está anexado no SISGAT.** Não é necessário gerar um novo.")
                col_b1, col_b2 = st.columns([3, 1])
                with col_b1:
                    st.info(f"Arquivo identificado: **{boleto_texto}**")
                with col_b2:
                    if boleto_href:
                        url_download = (
                            boleto_href if boleto_href.startswith('http')
                            else f"{SISGAT_URL_BASE}{boleto_href}"
                        )
                        st.markdown(
                            f'<a href="{url_download}" target="_blank" '
                            f'style="display:inline-block;padding:8px 16px;'
                            f'background:#1a6e1a;color:white;text-decoration:none;'
                            f'border-radius:5px;font-weight:bold;">📄 Abrir Boleto</a>',
                            unsafe_allow_html=True
                        )

            else:
                # ── BOLETO NÃO ANEXADO — ABRIR BRADESCO ────────────
                st.error("❌ **Boleto NÃO está anexado no SISGAT.**")
                st.warning(
                    "Clique no botão abaixo para abrir o Bradesco Net Empresa "
                    "com todos os dados já preenchidos. Após revisar, clique em "
                    "**Confirmar/Emitir** diretamente no navegador."
                )

                col_cfg1, col_cfg2 = st.columns(2)
                with col_cfg1:
                    data_vencimento = st.date_input("📅 Data de Vencimento", key="data_venc")
                with col_cfg2:
                    st.text_input("💰 Valor (R$)", value=detalhes.get('valor', ''), disabled=True)

                with st.expander("📋 Dados que serão preenchidos no boleto", expanded=True):
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.write(f"**Pagador:** {detalhes.get('nome_pagador', 'N/A')}")
                        st.write(f"**CPF/CNPJ:** {detalhes.get('cpf_cnpj', 'N/A')}")
                        st.write(f"**Endereço:** {detalhes.get('endereco', 'N/A')}")
                        st.write(f"**CEP:** {detalhes.get('cep', 'N/A')}")
                    with col_d2:
                        st.write(f"**Processo:** {detalhes.get('numero_processo', 'N/A')}")
                        st.write(f"**Tipo de Taxa:** {detalhes.get('tipo_taxa_solicitada', 'N/A')}")
                        st.write(f"**Meu Número:** {detalhes.get('meu_numero', 'N/A')}")
                        st.write(f"**Mensagem:** {detalhes.get('mensagem_boleto_para_banco', 'N/A')}")

                if st.button("🏦 Abrir Bradesco e Preencher Dados", type="primary", use_container_width=True):

                    # Fecha driver anterior se ainda estiver aberto
                    if 'driver_aberto' in st.session_state and st.session_state['driver_aberto']:
                        try:
                            st.session_state['driver_aberto'].quit()
                        except Exception:
                            pass
                        st.session_state['driver_aberto'] = None

                    logs_gerados  = []
                    log_placeholder = st.empty()

                    def atualizar_log(msg):
                        logs_gerados.append(msg)
                        log_placeholder.markdown(
                            "<br>".join(logs_gerados),
                            unsafe_allow_html=True
                        )

                    dados_boleto = {
                        **detalhes,
                        "vencimento": data_vencimento.strftime("%d/%m/%Y"),
                    }

                    with st.spinner("Abrindo navegador e preenchendo dados..."):
                        sucesso, mensagem = abrir_bradesco_e_preencher(
                            login=st.session_state.get('bradesco_login', ''),
                            senha=st.session_state.get('bradesco_senha', ''),
                            dados=dados_boleto,
                            log_fn=atualizar_log,
                        )

                    st.markdown("---")
                    if sucesso:
                        st.success(mensagem)
                        st.info(
                            "🖥️ O Chrome está aberto com os dados preenchidos. "
                            "Revise as informações e clique em **Confirmar / Emitir** no site do Bradesco."
                        )
                    else:
                        st.error(mensagem)
                        st.markdown(
                            "**Acesso manual:** "
                            "[Bradesco Net Empresa ↗](https://www.ne2.bradesconetempresa.b.br/ibpjlogin/login.jsf)"
                        )

            st.markdown("---")

            # ── DETALHES COMPLETOS ──────────────────────────────────
            with st.expander("🗂️ Detalhes Completos do Processo", expanded=False):
                campos_ocultos = {'boleto_anexado_texto', 'boleto_anexado_href'}
                items = [(k, v) for k, v in detalhes.items() if k not in campos_ocultos]
                col_e1, col_e2 = st.columns(2)
                metade = len(items) // 2
                with col_e1:
                    for k, v in items[:metade]:
                        st.write(f"**{k.replace('_', ' ').title()}:** {v}")
                with col_e2:
                    for k, v in items[metade:]:
                        st.write(f"**{k.replace('_', ' ').title()}:** {v}")

        else:
            st.warning(f"Não foi possível carregar os detalhes para o Processo ID: {processo_id}.")

    else:
        st.warning("Selecione um processo válido na barra lateral.")

elif 'login_status' in st.session_state and st.session_state.get('login_status') != "Login bem-sucedido!":
    st.error("Por favor, faça o login na barra lateral para carregar os processos.")
else:
    st.info("👈 Faça o login na barra lateral e selecione um processo para começar.")
