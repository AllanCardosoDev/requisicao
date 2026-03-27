import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import os
import time
import tempfile
import base64
from pathlib import Path

# Selenium imports (instale: pip install selenium webdriver-manager)
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_DISPONIVEL = True
except ImportError:
    SELENIUM_DISPONIVEL = False


# ============================================================
# FUNÇÕES DE SCRAPING - SISGAT
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
            span_projeto_id = h3_element.find('span', style=lambda s: s and 'font-size:2rem; color:red;' in s)
            if span_projeto_id:
                detalhes['numero_processo'] = span_projeto_id.get_text(strip=True)

        detalhes['usuario_solicitante']          = extract_detail('Usuário Solicitante')
        detalhes['servidor_dat_gerou_boleto']    = extract_detail('Servidor DAT que gerou o boleto')
        if 'numero_processo' not in detalhes or not detalhes['numero_processo']:
            detalhes['numero_processo']          = extract_detail('Nº do Processo')

        detalhes['razao_social']                 = extract_detail('Razão Social / Nome Fantasia do Cliente')
        detalhes['cpf_cnpj']                     = extract_detail('CPF/CNPJ')
        detalhes['telefone']                     = extract_detail('Telefone')
        detalhes['email']                        = extract_detail('Email')
        detalhes['tipo_taxa_solicitada']         = extract_detail('Tipo de Taxa Solicitada')
        detalhes['protecao_requerida']           = extract_detail('Proteção Requerida')
        detalhes['cep']                          = extract_detail('CEP')
        detalhes['endereco']                     = extract_detail('Endereço')
        detalhes['meu_numero']                   = extract_detail('Meu Número')
        detalhes['mensagem']                     = extract_detail('Mensagem')
        detalhes['area_edificada']               = extract_detail('Area Edificada')
        detalhes['valor']                        = extract_detail('Valor')
        detalhes['status']                       = extract_detail('Status')
        detalhes['data_solicitacao_boleto']      = extract_detail('Data da Solicitação do Boleto')
        detalhes['data_ultima_edicao_boleto']    = extract_detail('Data da Última Edição do Boleto')

        boleto_texto, boleto_href = extract_boleto_link('Boleto')
        detalhes['boleto_anexado_texto'] = boleto_texto
        detalhes['boleto_anexado_href']  = boleto_href

        if detalhes.get('valor'):
            detalhes['valor'] = detalhes['valor'].replace('R$', '').replace('.', '').replace(',', '.').strip()
        if detalhes.get('cpf_cnpj'):
            detalhes['cpf_cnpj'] = re.sub(r'\D', '', detalhes['cpf_cnpj'])
        if detalhes.get('area_edificada'):
            detalhes['area_edificada'] = detalhes['area_edificada'].replace(' m²', '').replace(',', '.').strip()

        detalhes['nome_pagador']             = detalhes.get('razao_social')
        detalhes['cnpj_pagador']             = detalhes.get('cpf_cnpj')
        detalhes['endereco_completo_pagador'] = detalhes.get('endereco')

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
# FUNÇÕES BRADESCO - GERAÇÃO DE BOLETO VIA SELENIUM
# ============================================================

def criar_driver_chrome(pasta_download: str):
    """Cria uma instância do ChromeDriver configurada para download de PDF."""
    chrome_options = Options()

    # Configuração de download automático de PDF
    prefs = {
        "download.default_directory": pasta_download,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_settings.popups": 0,
        "profile.content_settings.exceptions.automatic_downloads.*.setting": 1,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # Roda visível (headless não funciona bem com Java/JSF do Bradesco)
    # Para ambiente servidor, descomente a linha abaixo:
    # chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1366,768")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        # Fallback: tenta usar o chromedriver do PATH
        driver = webdriver.Chrome(options=chrome_options)

    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def gerar_boleto_bradesco(
    login_bradesco: str,
    senha_bradesco: str,
    dados_boleto: dict,
    pasta_download: str,
    progress_callback=None
) -> tuple[bool, str, str | None]:
    """
    Tenta gerar o boleto no Bradesco Net Empresa via Selenium.

    Retorna: (sucesso: bool, mensagem: str, caminho_pdf: str | None)
    """
    if not SELENIUM_DISPONIVEL:
        return False, "Selenium não instalado. Execute: pip install selenium webdriver-manager", None

    driver = None
    BRADESCO_URL = "https://www.ne2.bradesconetempresa.b.br/ibpjlogin/login.jsf"
    wait_time = 20

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    try:
        log("🌐 Abrindo navegador...")
        driver = criar_driver_chrome(pasta_download)
        wait = WebDriverWait(driver, wait_time)

        # --- PASSO 1: ACESSO À PÁGINA DE LOGIN ---
        log("🔑 Acessando página de login do Bradesco Net Empresa...")
        driver.get(BRADESCO_URL)
        time.sleep(3)

        # --- PASSO 2: PREENCHER CREDENCIAIS ---
        log("📝 Preenchendo credenciais...")
        try:
            campo_usuario = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name*='usuario'], input[id*='usuario'], input[type='text']"))
            )
            campo_usuario.clear()
            campo_usuario.send_keys(login_bradesco)

            campo_senha = driver.find_element(By.CSS_SELECTOR, "input[name*='senha'], input[id*='senha'], input[type='password']")
            campo_senha.clear()
            campo_senha.send_keys(senha_bradesco)

            btn_entrar = driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit'], input[value*='Entrar'], input[value*='Acessar']")
            btn_entrar.click()
            time.sleep(4)

        except TimeoutException:
            return False, (
                "⚠️ Não foi possível localizar os campos de login. "
                "O Bradesco Net Empresa usa autenticação Java/certificado digital "
                "que pode bloquear automação. Acesso manual necessário."
            ), None

        # Verifica se o login foi bem-sucedido
        url_atual = driver.current_url.lower()
        page_text = driver.page_source.lower()

        if "login" in url_atual or "erro" in page_text or "inválido" in page_text:
            return False, "❌ Falha no login do Bradesco. Verifique as credenciais ou autentique manualmente.", None

        log("✅ Login realizado. Navegando para Cobrança...")

        # --- PASSO 3: NAVEGAR ATÉ COBRANÇA ---
        try:
            menu_cobranca = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'Cobrança') or contains(text(),'cobrança')]"))
            )
            menu_cobranca.click()
            time.sleep(2)

            log("📋 Acessando Emitir Boleto...")
            emitir_boleto = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'Emitir') or contains(text(),'Boleto') or contains(text(),'boleto')]"))
            )
            emitir_boleto.click()
            time.sleep(2)

        except TimeoutException:
            return False, (
                "⚠️ Não foi possível navegar até a área de Cobrança automaticamente. "
                "A estrutura de menus do Bradesco pode ter mudado ou requer interação manual."
            ), None

        log("📄 Preenchendo dados do boleto...")

        # --- PASSO 4: PREENCHER DADOS DO BOLETO ---
        campos_map = {
            # Seletores genéricos — ajuste conforme a estrutura real da página
            "pagador_nome":   ("css", "input[name*='nomePagador'], input[id*='nomePagador']"),
            "pagador_cpfcnpj":("css", "input[name*='cpfCnpj'], input[id*='cpfCnpj'], input[name*='cnpj']"),
            "pagador_end":    ("css", "input[name*='endereco'], input[id*='endereco']"),
            "valor":          ("css", "input[name*='valor'], input[id*='valor']"),
            "vencimento":     ("css", "input[name*='vencimento'], input[id*='dataVencimento']"),
            "nosso_numero":   ("css", "input[name*='nossoNumero'], input[id*='nossoNumero']"),
            "mensagem":       ("css", "input[name*='mensagem'], textarea[name*='mensagem'], input[id*='instrucao']"),
        }

        valores_campos = {
            "pagador_nome":    dados_boleto.get('nome_pagador', ''),
            "pagador_cpfcnpj": dados_boleto.get('cpf_cnpj', ''),
            "pagador_end":     dados_boleto.get('endereco', ''),
            "valor":           dados_boleto.get('valor', ''),
            "vencimento":      dados_boleto.get('vencimento', ''),
            "nosso_numero":    dados_boleto.get('meu_numero', ''),
            "mensagem":        dados_boleto.get('mensagem_boleto_para_banco', ''),
        }

        for campo_key, (tipo_seletor, seletor) in campos_map.items():
            valor = valores_campos.get(campo_key, '')
            if not valor:
                continue
            try:
                elementos = driver.find_elements(By.CSS_SELECTOR, seletor)
                if elementos:
                    elementos[0].clear()
                    elementos[0].send_keys(str(valor))
            except Exception:
                pass  # Campo não encontrado — continua sem bloquear

        log("🖱️ Confirmando emissão do boleto...")

        # --- PASSO 5: CONFIRMAR E BAIXAR ---
        try:
            btn_confirmar = wait.until(
                EC.element_to_be_clickable((By.XPATH,
                    "//input[@value='Confirmar' or @value='Emitir' or @value='Gerar'] | "
                    "//button[contains(text(),'Confirmar') or contains(text(),'Emitir')]"
                ))
            )
            btn_confirmar.click()
            time.sleep(3)

            # Aguarda o PDF aparecer na pasta de download
            log("⏳ Aguardando download do PDF...")
            pdf_path = None
            for _ in range(30):  # Aguarda até 30 segundos
                pdfs = list(Path(pasta_download).glob("*.pdf"))
                if pdfs:
                    pdf_path = str(max(pdfs, key=os.path.getmtime))
                    break
                time.sleep(1)

            if pdf_path:
                log(f"✅ Boleto gerado com sucesso: {Path(pdf_path).name}")
                return True, "Boleto gerado e baixado com sucesso!", pdf_path
            else:
                # Tenta imprimir a página como PDF via JavaScript
                log("🖨️ Tentando exportar página atual como PDF...")
                pdf_data = driver.execute_cdp_cmd(
                    "Page.printToPDF",
                    {"printBackground": True, "format": "A4"}
                )
                pdf_path = os.path.join(pasta_download, f"boleto_{dados_boleto.get('numero_processo', 'sem_numero')}.pdf")
                with open(pdf_path, 'wb') as f:
                    f.write(base64.b64decode(pdf_data['data']))
                log("✅ PDF exportado via CDP.")
                return True, "Boleto exportado como PDF com sucesso!", pdf_path

        except TimeoutException:
            return False, "⚠️ Botão de confirmação não encontrado. A emissão pode exigir etapas manuais adicionais.", None

    except Exception as e:
        return False, f"❌ Erro inesperado durante a geração do boleto: {e}", None

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def criar_link_download_pdf(caminho_pdf: str, label: str = "📥 Baixar Boleto PDF") -> None:
    """Cria um botão de download do PDF no Streamlit."""
    with open(caminho_pdf, 'rb') as f:
        dados_pdf = f.read()
    nome_arquivo = Path(caminho_pdf).name
    b64 = base64.b64encode(dados_pdf).decode()
    href = f'<a href="data:application/pdf;base64,{b64}" download="{nome_arquivo}" style="display:inline-block;padding:10px 20px;background-color:#006400;color:white;text-decoration:none;border-radius:5px;font-weight:bold;">{label}</a>'
    st.markdown(href, unsafe_allow_html=True)


# ============================================================
# CONFIGURAÇÃO DO STREAMLIT
# ============================================================

st.set_page_config(layout="wide", page_title="SISGAT + Bradesco — Gestão de Boletos")
st.title("🔥 SISGAT — Gestão de Boletos CBM/AM")

SISGAT_URL_BASE = "https://sisgat.cbm.am.gov.br"

# ============================================================
# BARRA LATERAL — LOGIN SISGAT + BRADESCO
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
    st.caption("Usadas apenas para geração de boletos não anexados.")
    bradesco_login = st.text_input("Login Bradesco", value="mpps00033")
    bradesco_senha = st.text_input("Senha Bradesco", type="password", value="832cbmam")
    st.session_state['bradesco_login'] = bradesco_login
    st.session_state['bradesco_senha'] = bradesco_senha

    st.markdown("---")

    # Seletor de processos
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
            process_number_match = re.match(r'(\d+)', selected_process_display)
            if process_number_match:
                selected_process_number = process_number_match.group(1)
                for p in st.session_state['processos_listados']:
                    if p.get('n_do_processo') == selected_process_number:
                        selected_process = p
                        break

        st.session_state['selected_process'] = selected_process

    elif 'login_status' in st.session_state and st.session_state['login_status'] == "Login bem-sucedido!":
        st.warning("Nenhum processo encontrado.")


# ============================================================
# ÁREA PRINCIPAL
# ============================================================

if 'selected_process' in st.session_state and st.session_state['selected_process']:
    processo = st.session_state['selected_process']
    processo_id = processo.get('id_boleto')

    if processo_id and 'session' in st.session_state and st.session_state['session']:

        # Cabeçalho do processo
        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.metric("Nº do Processo", processo.get('n_do_processo', 'N/A'))
        with col_info2:
            st.metric("Cliente", processo.get('cliente', 'N/A'))
        with col_info3:
            st.metric("Tipo de Taxa", processo.get('tipo_de_taxa', 'N/A'))

        st.markdown("---")

        # Carrega detalhes completos
        with st.spinner("Carregando detalhes do processo..."):
            detalhes = obter_detalhes_boleto_sisgat(
                st.session_state['session'], processo_id, SISGAT_URL_BASE
            )

        if detalhes:

            # ========================================
            # BLOCO PRINCIPAL — STATUS DO BOLETO
            # ========================================
            st.subheader("📎 Status do Boleto no SISGAT")

            boleto_texto = detalhes.get('boleto_anexado_texto')
            boleto_href  = detalhes.get('boleto_anexado_href')
            boleto_vazio = not boleto_texto or boleto_texto.strip() in ('', '-', 'N/A', 'Não informado', 'Nenhum')

            if not boleto_vazio:
                # ---- BOLETO JÁ ANEXADO ----
                st.success("✅ **Boleto já está anexado no SISGAT.** Não é necessário gerar um novo.")

                col_b1, col_b2 = st.columns([2, 1])
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
                            f'background-color:#1a6e1a;color:white;text-decoration:none;'
                            f'border-radius:5px;font-weight:bold;">📄 Abrir Boleto</a>',
                            unsafe_allow_html=True
                        )

            else:
                # ---- BOLETO NÃO ANEXADO ----
                st.error("❌ **Boleto NÃO está anexado no SISGAT.**")

                st.warning(
                    "Este processo ainda não possui boleto vinculado. "
                    "Você pode gerar o boleto diretamente pelo Bradesco Net Empresa abaixo."
                )

                # Data de vencimento para o boleto
                st.markdown("#### ⚙️ Configurações para Emissão")
                col_cfg1, col_cfg2 = st.columns(2)
                with col_cfg1:
                    data_vencimento = st.date_input(
                        "Data de Vencimento do Boleto",
                        key="data_vencimento_boleto"
                    )
                with col_cfg2:
                    valor_exibido = detalhes.get('valor', 'Não informado')
                    st.text_input("Valor (R$)", value=valor_exibido, disabled=True)

                # Resumo dos dados que serão inseridos no boleto
                with st.expander("📋 Dados que serão preenchidos no boleto", expanded=True):
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.write(f"**Pagador:** {detalhes.get('nome_pagador', 'N/A')}")
                        st.write(f"**CPF/CNPJ:** {detalhes.get('cpf_cnpj', 'N/A')}")
                        st.write(f"**Endereço:** {detalhes.get('endereco', 'N/A')}")
                    with col_d2:
                        st.write(f"**Processo:** {detalhes.get('numero_processo', 'N/A')}")
                        st.write(f"**Tipo de Taxa:** {detalhes.get('tipo_taxa_solicitada', 'N/A')}")
                        st.write(f"**Meu Número:** {detalhes.get('meu_numero', 'N/A')}")
                    st.write(f"**Mensagem:** {detalhes.get('mensagem_boleto_para_banco', 'N/A')}")

                # Aviso sobre limitações do Bradesco
                if not SELENIUM_DISPONIVEL:
                    st.error(
                        "⚠️ Selenium não está instalado. Para habilitar a geração automática, "
                        "execute no terminal: `pip install selenium webdriver-manager`"
                    )
                else:
                    st.info(
                        "ℹ️ A geração abrirá o Chrome automaticamente para acessar o Bradesco Net Empresa. "
                        "Mantenha o navegador visível durante o processo."
                    )

                    if st.button("🏦 Gerar Boleto no Bradesco", type="primary", use_container_width=True):
                        pasta_temp = tempfile.mkdtemp()
                        log_area = st.empty()
                        logs = []

                        def atualizar_log(msg):
                            logs.append(msg)
                            log_area.markdown("\n\n".join(logs))

                        dados_para_boleto = {
                            **detalhes,
                            "vencimento": data_vencimento.strftime("%d/%m/%Y") if data_vencimento else "",
                        }

                        with st.spinner("Gerando boleto no Bradesco..."):
                            sucesso, mensagem, caminho_pdf = gerar_boleto_bradesco(
                                login_bradesco=st.session_state.get('bradesco_login', ''),
                                senha_bradesco=st.session_state.get('bradesco_senha', ''),
                                dados_boleto=dados_para_boleto,
                                pasta_download=pasta_temp,
                                progress_callback=atualizar_log,
                            )

                        st.markdown("---")
                        if sucesso and caminho_pdf:
                            st.success(mensagem)
                            st.balloons()
                            criar_link_download_pdf(caminho_pdf, "📥 Baixar Boleto PDF")
                            st.session_state['ultimo_pdf_gerado'] = caminho_pdf
                        else:
                            st.error(mensagem)
                            st.markdown(
                                "**Recomendação:** Acesse manualmente o "
                                "[Bradesco Net Empresa](https://www.ne2.bradesconetempresa.b.br/ibpjlogin/login.jsf) "
                                "para emitir o boleto."
                            )

            st.markdown("---")

            # ========================================
            # DETALHES COMPLETOS DO PROCESSO
            # ========================================
            with st.expander("🗂️ Detalhes Completos do Processo", expanded=False):
                campos_ocultos = {'boleto_anexado_texto', 'boleto_anexado_href'}
                col_e1, col_e2 = st.columns(2)
                items = [(k, v) for k, v in detalhes.items() if k not in campos_ocultos]
                metade = len(items) // 2
                with col_e1:
                    for key, value in items[:metade]:
                        st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                with col_e2:
                    for key, value in items[metade:]:
                        st.write(f"**{key.replace('_', ' ').title()}:** {value}")

        else:
            st.warning(f"Não foi possível carregar os detalhes para o Processo ID: {processo_id}.")

    else:
        st.warning("Selecione um processo válido na barra lateral.")

elif 'login_status' in st.session_state and st.session_state.get('login_status') != "Login bem-sucedido!":
    st.error("Por favor, faça o login na barra lateral para carregar os processos.")
else:
    st.info("👈 Faça o login na barra lateral e selecione um processo para começar.")
