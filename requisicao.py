import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import base64
import time
import io

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
            span_projeto_id = h3_element.find('span', style=lambda s: s and 'font-size:2rem; color:red;' in s)
            if span_projeto_id:
                detalhes['numero_processo'] = span_projeto_id.get_text(strip=True)

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

        detalhes['nome_pagador']              = detalhes.get('razao_social')
        detalhes['cnpj_pagador']              = detalhes.get('cpf_cnpj')
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
# FUNÇÕES BRADESCO — SOMENTE REQUESTS
# ============================================================

BRADESCO_URL_BASE = "https://www.ne2.bradesconetempresa.b.br"
BRADESCO_LOGIN_URL = f"{BRADESCO_URL_BASE}/ibpjlogin/login.jsf"


def extrair_campos_hidden(soup: BeautifulSoup) -> dict:
    """
    Extrai todos os campos <input type="hidden"> de uma página JSF.
    Isso captura ViewState, j_id tokens e quaisquer outros campos obrigatórios.
    """
    campos = {}
    for inp in soup.find_all('input', {'type': 'hidden'}):
        nome = inp.get('name') or inp.get('id')
        valor = inp.get('value', '')
        if nome:
            campos[nome] = valor
    return campos


def extrair_action_form(soup: BeautifulSoup, form_id: str = None) -> str | None:
    """
    Retorna o atributo 'action' do formulário JSF principal.
    Se form_id for fornecido, busca o form por ID; caso contrário, pega o primeiro form.
    """
    if form_id:
        form = soup.find('form', {'id': form_id})
    else:
        form = soup.find('form')

    if form and form.get('action'):
        action = form['action']
        if action.startswith('/'):
            return f"{BRADESCO_URL_BASE}{action}"
        return action
    return None


def montar_headers_bradesco(referer: str = None) -> dict:
    """Headers que simulam um navegador real para evitar bloqueios básicos."""
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    if referer:
        headers['Referer'] = referer
    return headers


def login_bradesco(
    login: str,
    senha: str,
    log_fn=None
) -> tuple[requests.Session | None, str, BeautifulSoup | None]:
    """
    Realiza o login no Bradesco Net Empresa via POST puro.
    Retorna (session, mensagem, soup_pos_login).

    O fluxo JSF exige:
      1. GET na página de login para capturar ViewState e demais hidden fields.
      2. POST com os campos do formulário preenchidos.
    """
    session = requests.Session()

    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        log("🌐 Acessando página de login do Bradesco...")
        resp_get = session.get(
            BRADESCO_LOGIN_URL,
            headers=montar_headers_bradesco(),
            timeout=30
        )
        resp_get.raise_for_status()

        soup_login = BeautifulSoup(resp_get.text, 'html.parser')

        # Extrai todos os campos hidden (ViewState, j_id, etc.)
        campos_hidden = extrair_campos_hidden(soup_login)
        log(f"🔑 Campos hidden capturados: {list(campos_hidden.keys())}")

        # Identifica o ID dos campos de usuário e senha no HTML
        # O Bradesco JSF costuma usar IDs como 'form:username' ou 'j_username'
        campo_usuario_el = (
            soup_login.find('input', {'name': re.compile(r'usuario|username|login|cpf', re.I)})
            or soup_login.find('input', {'id': re.compile(r'usuario|username|login|cpf', re.I)})
        )
        campo_senha_el = (
            soup_login.find('input', {'name': re.compile(r'senha|password|pwd', re.I)})
            or soup_login.find('input', {'id': re.compile(r'senha|password|pwd', re.I)})
        )

        nome_campo_usuario = campo_usuario_el.get('name') or campo_usuario_el.get('id') if campo_usuario_el else 'j_username'
        nome_campo_senha   = campo_senha_el.get('name')   or campo_senha_el.get('id')   if campo_senha_el   else 'j_password'

        log(f"📝 Campo usuário identificado: '{nome_campo_usuario}' | Campo senha: '{nome_campo_senha}'")

        # Monta o payload completo: campos hidden + credenciais + botão de submit
        payload = {**campos_hidden}
        payload[nome_campo_usuario] = login
        payload[nome_campo_senha]   = senha

        # Botão de submit — captura o name/value se existir
        btn_submit = soup_login.find('input', {'type': 'submit'})
        if btn_submit:
            btn_name  = btn_submit.get('name')
            btn_value = btn_submit.get('value', 'Entrar')
            if btn_name:
                payload[btn_name] = btn_value

        # URL de action do form
        action_url = extrair_action_form(soup_login) or BRADESCO_LOGIN_URL

        log(f"📤 Enviando credenciais para: {action_url}")
        resp_post = session.post(
            action_url,
            data=payload,
            headers=montar_headers_bradesco(referer=BRADESCO_LOGIN_URL),
            allow_redirects=True,
            timeout=30
        )
        resp_post.raise_for_status()

        soup_pos = BeautifulSoup(resp_post.text, 'html.parser')
        url_final = resp_post.url.lower()

        # Verifica se ainda está na tela de login (falha)
        if "login" in url_final or "erro" in url_final:
            return None, "❌ Falha no login. Bradesco redirecionou de volta ao login.", None

        # Verifica mensagens de erro na página
        erros = soup_pos.find_all(string=re.compile(r'inválid|erro|incorret|bloqueado', re.I))
        if erros:
            msgs = [e.strip() for e in erros if e.strip()]
            return None, f"❌ Erro retornado pelo Bradesco: {msgs[0] if msgs else 'Credencial inválida.'}", None

        log("✅ Login no Bradesco realizado com sucesso.")
        return session, "Login bem-sucedido!", soup_pos

    except requests.exceptions.RequestException as e:
        return None, f"❌ Erro de requisição no login Bradesco: {e}", None
    except Exception as e:
        return None, f"❌ Erro inesperado no login Bradesco: {e}", None


def navegar_para_cobranca(
    session: requests.Session,
    soup_home: BeautifulSoup,
    url_atual: str,
    log_fn=None
) -> tuple[bool, str, BeautifulSoup | None, str | None]:
    """
    A partir da página inicial pós-login, localiza e acessa o menu de Cobrança.
    Retorna (sucesso, mensagem, soup_cobranca, url_cobranca).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        # Tenta encontrar link de Cobrança no menu
        link_cobranca = (
            soup_home.find('a', string=re.compile(r'cobran', re.I))
            or soup_home.find('a', href=re.compile(r'cobran', re.I))
        )

        if link_cobranca and link_cobranca.get('href'):
            href = link_cobranca['href']
            url_cobranca = href if href.startswith('http') else f"{BRADESCO_URL_BASE}{href}"
        else:
            # Fallback: tenta URL conhecida de cobrança do Bradesco Net Empresa
            url_cobranca = f"{BRADESCO_URL_BASE}/ibpjcobranca/cobranca.jsf"

        log(f"📂 Navegando para área de Cobrança: {url_cobranca}")
        resp = session.get(
            url_cobranca,
            headers=montar_headers_bradesco(referer=url_atual),
            timeout=30
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        return True, "Cobrança acessada.", soup, resp.url

    except Exception as e:
        return False, f"❌ Erro ao navegar para Cobrança: {e}", None, None


def navegar_para_emissao_boleto(
    session: requests.Session,
    soup_cobranca: BeautifulSoup,
    url_cobranca: str,
    log_fn=None
) -> tuple[bool, str, BeautifulSoup | None, str | None]:
    """
    A partir da página de Cobrança, localiza e acessa a tela de Emissão de Boleto.
    Retorna (sucesso, mensagem, soup_emissao, url_emissao).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        link_emissao = (
            soup_cobranca.find('a', string=re.compile(r'emitir|emiss|boleto', re.I))
            or soup_cobranca.find('a', href=re.compile(r'emitir|boleto|titulos', re.I))
        )

        if link_emissao and link_emissao.get('href'):
            href = link_emissao['href']
            url_emissao = href if href.startswith('http') else f"{BRADESCO_URL_BASE}{href}"
        else:
            url_emissao = f"{BRADESCO_URL_BASE}/ibpjcobranca/emissaoBoleto.jsf"

        log(f"📄 Acessando tela de emissão de boleto: {url_emissao}")
        resp = session.get(
            url_emissao,
            headers=montar_headers_bradesco(referer=url_cobranca),
            timeout=30
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        return True, "Tela de emissão acessada.", soup, resp.url

    except Exception as e:
        return False, f"❌ Erro ao acessar tela de emissão: {e}", None, None


def preencher_e_submeter_boleto(
    session: requests.Session,
    soup_emissao: BeautifulSoup,
    url_emissao: str,
    dados: dict,
    log_fn=None
) -> tuple[bool, str, bytes | None]:
    """
    Preenche os campos do formulário de emissão de boleto pelos IDs/names
    extraídos do HTML e submete. Retorna (sucesso, mensagem, bytes_pdf).

    A estratégia é:
      1. Extrair todos os campos hidden (ViewState, etc.).
      2. Mapear os campos visíveis pelos seus name/id via BeautifulSoup.
      3. Montar o payload com os dados do SISGAT.
      4. POST e verificar se a resposta é um PDF ou contém link para PDF.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        campos_hidden = extrair_campos_hidden(soup_emissao)
        log(f"🔎 Campos hidden do formulário de emissão: {list(campos_hidden.keys())}")

        # Mapeia campos visíveis do formulário pelo name (JSF usa name composto: 'formId:fieldId')
        def achar_campo(soup, *patterns):
            """Tenta localizar um input/select/textarea pelo name ou id usando padrões."""
            for pattern in patterns:
                el = (
                    soup.find('input', {'name': re.compile(pattern, re.I)})
                    or soup.find('input', {'id': re.compile(pattern, re.I)})
                    or soup.find('textarea', {'name': re.compile(pattern, re.I)})
                    or soup.find('select', {'name': re.compile(pattern, re.I)})
                )
                if el:
                    return el.get('name') or el.get('id')
            return None

        # Tenta identificar os campos no formulário JSF do Bradesco
        campo_nosso_numero   = achar_campo(soup_emissao, r'nossoNumero', r'nosso.numero', r'nroTitulo')
        campo_valor          = achar_campo(soup_emissao, r'valor', r'vlrTitulo', r'vlNominal')
        campo_vencimento     = achar_campo(soup_emissao, r'vencimento', r'dtVencimento', r'dataVenc')
        campo_nome_pagador   = achar_campo(soup_emissao, r'nomePagador', r'nome.pag', r'pagadorNome')
        campo_cpfcnpj        = achar_campo(soup_emissao, r'cpfCnpj', r'cnpj', r'cpf', r'docPagador')
        campo_endereco       = achar_campo(soup_emissao, r'endereco', r'logradouro', r'endPagador')
        campo_cep            = achar_campo(soup_emissao, r'cep', r'cepPagador')
        campo_instrucao1     = achar_campo(soup_emissao, r'instrucao1', r'instrucao', r'mensagem', r'obs')

        log("📝 Campos identificados no formulário:")
        log(f"   nosso_numero={campo_nosso_numero}, valor={campo_valor}, vencimento={campo_vencimento}")
        log(f"   nome_pagador={campo_nome_pagador}, cpf_cnpj={campo_cpfcnpj}")
        log(f"   endereco={campo_endereco}, cep={campo_cep}, instrucao={campo_instrucao1}")

        # Monta payload base com campos hidden
        payload = {**campos_hidden}

        # Insere os dados do SISGAT nos campos identificados
        mapeamento = {
            campo_nosso_numero: dados.get('meu_numero', ''),
            campo_valor:        dados.get('valor', ''),
            campo_vencimento:   dados.get('vencimento', ''),
            campo_nome_pagador: dados.get('nome_pagador', ''),
            campo_cpfcnpj:      dados.get('cpf_cnpj', ''),
            campo_endereco:     dados.get('endereco', ''),
            campo_cep:          dados.get('cep', ''),
            campo_instrucao1:   dados.get('mensagem_boleto_para_banco', ''),
        }

        for nome_campo, valor in mapeamento.items():
            if nome_campo and valor:
                payload[nome_campo] = str(valor)

        # Captura botão de submit (confirmar/emitir)
        btn = (
            soup_emissao.find('input', {'type': 'submit'})
            or soup_emissao.find('button', {'type': 'submit'})
        )
        if btn:
            btn_name  = btn.get('name')
            btn_value = btn.get('value', 'Confirmar')
            if btn_name:
                payload[btn_name] = btn_value

        action_url = extrair_action_form(soup_emissao) or url_emissao

        log(f"📤 Submetendo formulário de emissão para: {action_url}")
        resp = session.post(
            action_url,
            data=payload,
            headers=montar_headers_bradesco(referer=url_emissao),
            allow_redirects=True,
            timeout=60
        )
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '')

        # CASO 1: A resposta já é o PDF diretamente
        if 'application/pdf' in content_type:
            log("✅ Boleto PDF recebido diretamente na resposta.")
            return True, "Boleto gerado com sucesso!", resp.content

        # CASO 2: A resposta é HTML com link para o PDF
        soup_resp = BeautifulSoup(resp.text, 'html.parser')
        link_pdf = soup_resp.find('a', href=re.compile(r'\.pdf', re.I))
        if not link_pdf:
            # Tenta iframe ou embed com src de PDF
            link_pdf = (
                soup_resp.find('iframe', src=re.compile(r'\.pdf|boleto', re.I))
                or soup_resp.find('embed', src=re.compile(r'\.pdf|boleto', re.I))
            )

        if link_pdf:
            href_pdf = link_pdf.get('href') or link_pdf.get('src')
            url_pdf  = href_pdf if href_pdf.startswith('http') else f"{BRADESCO_URL_BASE}{href_pdf}"
            log(f"📎 Link de PDF encontrado, baixando: {url_pdf}")
            resp_pdf = session.get(
                url_pdf,
                headers=montar_headers_bradesco(referer=resp.url),
                timeout=60
            )
            resp_pdf.raise_for_status()
            if resp_pdf.content:
                return True, "Boleto PDF baixado com sucesso!", resp_pdf.content
            else:
                return False, "❌ Link de PDF encontrado, mas o download retornou vazio.", None

        # CASO 3: Verifica se há mensagem de sucesso na página (boleto gerado mas PDF em outra etapa)
        msg_sucesso = soup_resp.find(string=re.compile(r'sucesso|gerado|emitido|registrado', re.I))
        if msg_sucesso:
            log("⚠️ Boleto possivelmente gerado, mas PDF não foi retornado automaticamente.")
            return False, (
                "⚠️ O Bradesco confirmou a emissão, mas o PDF não foi retornado "
                "automaticamente. Pode ser necessário uma etapa adicional de confirmação "
                "ou o site exige interação com componente JSF dinâmico (AJAX)."
            ), None

        # CASO 4: Falha genérica
        log("❌ Nenhum PDF nem confirmação de sucesso encontrados na resposta.")
        return False, (
            "❌ O formulário foi submetido, mas o Bradesco não retornou o boleto. "
            "O sistema pode exigir autenticação adicional (token/certificado) "
            "ou o fluxo usa chamadas AJAX que não foram capturadas."
        ), None

    except Exception as e:
        return False, f"❌ Erro ao preencher/submeter formulário: {e}", None


def gerar_boleto_bradesco_requests(
    login: str,
    senha: str,
    dados: dict,
    log_fn=None
) -> tuple[bool, str, bytes | None]:
    """
    Orquestra todo o fluxo de geração de boleto via requests puras:
    login → cobrança → emissão → download PDF.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    # Passo 1 — Login
    session, msg_login, soup_home = login_bradesco(login, senha, log_fn=log)
    if not session:
        return False, msg_login, None

    url_home = BRADESCO_LOGIN_URL  # ponto de partida para Referer

    # Passo 2 — Cobrança
    ok, msg, soup_cobranca, url_cobranca = navegar_para_cobranca(
        session, soup_home, url_home, log_fn=log
    )
    if not ok:
        return False, msg, None

    # Passo 3 — Tela de emissão
    ok, msg, soup_emissao, url_emissao = navegar_para_emissao_boleto(
        session, soup_cobranca, url_cobranca, log_fn=log
    )
    if not ok:
        return False, msg, None

    # Passo 4 — Preenche e submete
    ok, msg, pdf_bytes = preencher_e_submeter_boleto(
        session, soup_emissao, url_emissao, dados, log_fn=log
    )
    return ok, msg, pdf_bytes


def exibir_download_pdf(pdf_bytes: bytes, nome_arquivo: str = "boleto.pdf"):
    """Renderiza botão de download do PDF no Streamlit."""
    b64 = base64.b64encode(pdf_bytes).decode()
    href = (
        f'<a href="data:application/pdf;base64,{b64}" '
        f'download="{nome_arquivo}" '
        f'style="display:inline-block;padding:10px 22px;background:#1a6e1a;'
        f'color:white;text-decoration:none;border-radius:6px;font-weight:bold;">'
        f'📥 Baixar Boleto PDF</a>'
    )
    st.markdown(href, unsafe_allow_html=True)


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
            match = re.match(r'(\d+)', selected_process_display)
            if match:
                num = match.group(1)
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
    processo = st.session_state['selected_process']
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

            # ── STATUS DO BOLETO NO SISGAT ──────────────────────────
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
                # ── BOLETO NÃO ANEXADO — GERAR VIA BRADESCO ─────────
                st.error("❌ **Boleto NÃO está anexado no SISGAT.**")
                st.warning("Preencha a data de vencimento e clique em **Gerar Boleto** para emitir via Bradesco Net Empresa.")

                col_cfg1, col_cfg2 = st.columns(2)
                with col_cfg1:
                    data_vencimento = st.date_input("📅 Data de Vencimento", key="data_venc")
                with col_cfg2:
                    st.text_input("💰 Valor (R$)", value=detalhes.get('valor', ''), disabled=True)

                with st.expander("📋 Dados que serão inseridos no boleto", expanded=True):
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

                if st.button("🏦 Gerar Boleto no Bradesco", type="primary", use_container_width=True):
                    logs_gerados = []
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

                    with st.spinner("Gerando boleto via Bradesco Net Empresa..."):
                        sucesso, mensagem, pdf_bytes = gerar_boleto_bradesco_requests(
                            login=st.session_state.get('bradesco_login', ''),
                            senha=st.session_state.get('bradesco_senha', ''),
                            dados=dados_boleto,
                            log_fn=atualizar_log,
                        )

                    st.markdown("---")
                    if sucesso and pdf_bytes:
                        st.success(mensagem)
                        st.balloons()
                        nome_pdf = f"boleto_{detalhes.get('numero_processo', processo_id)}.pdf"
                        exibir_download_pdf(pdf_bytes, nome_arquivo=nome_pdf)
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
