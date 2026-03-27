import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

# --- Funções de Scraping ---

@st.cache_data(ttl=3600, hash_funcs={requests.Session: lambda _: None})
def login_sisgat(url_base, username, password):
    session = requests.Session()
    login_url = f"{url_base}/users/login"
    st.info(f"Tentando login em: {login_url}")

    try:
        login_page_response = session.get(login_url)
        login_page_response.raise_for_status()
        login_soup = BeautifulSoup(login_page_response.text, 'html.parser')

        csrf_token_input = login_soup.find('input', {'name': '_csrfToken'})
        csrf_token = csrf_token_input['value'] if csrf_token_input else None

        if csrf_token:
            st.info("CSRF Token encontrado.")
        else:
            st.warning("CSRF Token não encontrado. Prosseguindo sem ele.")

        login_data = {'username': username, 'password': password}
        if csrf_token:
            login_data['_csrfToken'] = csrf_token

        login_response = session.post(login_url, data=login_data, allow_redirects=True)
        login_response.raise_for_status()

        if "login" not in login_response.url.lower() and "Acesso não autorizado" not in login_response.text:
            st.success("Login bem-sucedido!")
            return session, "Login bem-sucedido!"
        else:
            st.error("Falha no login. Credenciais inválidas ou página inesperada.")
            return None, "Falha no login."

    except requests.exceptions.RequestException as e:
        st.error(f"Erro na requisição de login: {e}")
        return None, f"Erro na requisição de login: {e}"
    except Exception as e:
        st.error(f"Erro durante o login: {e}")
        return None, f"Erro durante o login: {e}"


@st.cache_data(ttl=600, hash_funcs={requests.Session: lambda _: None})
def obter_boletos_solicitados(session, url_base="https://sisgat.cbm.am.gov.br"):
    url_boletos = f"{url_base}/boletos-solicitados"
    st.info(f"Acessando boletos solicitados em: {url_boletos}")

    try:
        response = session.get(url_boletos)
        response.raise_for_status()

        if 'text/html' not in response.headers.get('Content-Type', ''):
            st.error("A resposta não é HTML.")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        boletos = []

        processo_header = soup.find('th', string='Nº do Processo')
        table = None
        if processo_header:
            table = processo_header.find_parent('table')

        if not table:
            st.warning("Tabela de boletos não encontrada. Verifique os seletores.")
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

    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao obter boletos solicitados: {e}")
        return []
    except Exception as e:
        st.error(f"Erro ao parsear boletos solicitados: {e}")
        return []


@st.cache_data(ttl=600, hash_funcs={requests.Session: lambda _: None})
def obter_detalhes_boleto_sisgat(session, boleto_id, url_base="https://sisgat.cbm.am.gov.br"):
    url_view = f"{url_base}/boletos-solicitados/view/{boleto_id}"
    st.info(f"Buscando detalhes do boleto ID {boleto_id} em: {url_view}")

    try:
        response = session.get(url_view)
        response.raise_for_status()

        if 'text/html' not in response.headers.get('Content-Type', ''):
            st.error("A resposta não é HTML.")
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
            except Exception as e:
                st.warning(f"Erro ao extrair '{label_text}': {e}")
            return None

        # --- NOVO: extrai o link do boleto se estiver como <a href="..."> ---
        def extract_boleto_link(label_text):
            """
            Retorna (texto, href) do campo 'Boleto'.
            Se houver um link <a>, captura o href; caso contrário, retorna só o texto.
            """
            try:
                th_element = soup.find('th', string=lambda text: text and label_text in text)
                if th_element:
                    td_element = th_element.find_next_sibling('td')
                    if td_element:
                        link_tag = td_element.find('a')
                        texto = td_element.get_text(strip=True)
                        href = link_tag['href'] if link_tag and 'href' in link_tag.attrs else None
                        return texto, href
            except Exception as e:
                st.warning(f"Erro ao extrair link de '{label_text}': {e}")
            return None, None

        h3_element = soup.find('h3', string=lambda text: text and 'Visualização de Solicitação de Boleto para o Processo Nº' in text)
        if h3_element:
            span_projeto_id = h3_element.find('span', style=lambda s: s and 'font-size:2rem; color:red;' in s)
            if span_projeto_id:
                detalhes['numero_processo'] = span_projeto_id.get_text(strip=True)

        detalhes['usuario_solicitante'] = extract_detail('Usuário Solicitante')
        detalhes['servidor_dat_gerou_boleto'] = extract_detail('Servidor DAT que gerou o boleto')
        if 'numero_processo' not in detalhes or not detalhes['numero_processo']:
            detalhes['numero_processo'] = extract_detail('Nº do Processo')

        detalhes['razao_social_nome_fantasia_cliente'] = extract_detail('Razão Social / Nome Fantasia do Cliente')
        detalhes['cpf_cnpj'] = extract_detail('CPF/CNPJ')
        detalhes['telefone'] = extract_detail('Telefone')
        detalhes['email'] = extract_detail('Email')
        detalhes['tipo_taxa_solicitada'] = extract_detail('Tipo de Taxa Solicitada')
        detalhes['protecao_requerida'] = extract_detail('Proteção Requerida')
        detalhes['cep'] = extract_detail('CEP')
        detalhes['endereco'] = extract_detail('Endereço')
        detalhes['meu_numero'] = extract_detail('Meu Número')
        detalhes['mensagem'] = extract_detail('Mensagem')
        detalhes['area_edificada'] = extract_detail('Area Edificada')
        detalhes['valor'] = extract_detail('Valor')
        detalhes['status'] = extract_detail('Status')
        detalhes['data_solicitacao_boleto'] = extract_detail('Data da Solicitação do Boleto')
        detalhes['data_ultima_edicao_boleto'] = extract_detail('Data da Última Edição do Boleto')

        # --- Captura separada do campo Boleto (texto + link) ---
        boleto_texto, boleto_href = extract_boleto_link('Boleto')
        detalhes['boleto_anexado_texto'] = boleto_texto
        detalhes['boleto_anexado_href'] = boleto_href

        # Limpezas
        if detalhes.get('valor'):
            detalhes['valor'] = detalhes['valor'].replace('R$', '').replace('.', '').replace(',', '.').strip()
        if detalhes.get('cpf_cnpj'):
            detalhes['cpf_cnpj'] = re.sub(r'\D', '', detalhes['cpf_cnpj'])
        if detalhes.get('area_edificada'):
            detalhes['area_edificada'] = detalhes['area_edificada'].replace(' m²', '').replace(',', '.').strip()

        detalhes['nome_pagador'] = detalhes.get('razao_social_nome_fantasia_cliente')
        detalhes['cnpj_pagador'] = detalhes.get('cpf_cnpj')
        detalhes['endereco_completo_pagador'] = detalhes.get('endereco')
        if detalhes.get('numero_processo') and detalhes.get('tipo_taxa_solicitada'):
            detalhes['mensagem_boleto_para_banco'] = f"Processo: {detalhes['numero_processo']}, Tipo de Taxa: {detalhes['tipo_taxa_solicitada']}"
        else:
            detalhes['mensagem_boleto_para_banco'] = detalhes.get('mensagem', 'Mensagem não disponível')

        detalhes_limpos = {k: v for k, v in detalhes.items() if v is not None and str(v).strip() != ''}

        if not detalhes_limpos:
            st.warning("Nenhum detalhe encontrado na página de visualização.")
            return None

        return detalhes_limpos

    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao obter detalhes do boleto {boleto_id}: {e}")
        return None
    except Exception as e:
        st.error(f"Erro ao parsear detalhes do boleto {boleto_id}: {e}")
        return None


# --- Configurações do Streamlit ---
st.set_page_config(layout="wide", page_title="Consulta de Boletos SISGAT")
st.title("Consulta de Boletos SISGAT")

SISGAT_URL_BASE = "https://sisgat.cbm.am.gov.br"

# --- Barra Lateral ---
with st.sidebar:
    st.header("Acesso ao SISGAT")
    username = st.text_input("Usuário", value="ALLAN_ATD")
    password = st.text_input("Senha", type="password", value="123456")

    if st.button("Fazer Login e Carregar Processos"):
        login_sisgat.clear()
        obter_boletos_solicitados.clear()
        obter_detalhes_boleto_sisgat.clear()

        st.session_state['session'], st.session_state['login_status'] = login_sisgat(SISGAT_URL_BASE, username, password)
        if st.session_state['session']:
            st.session_state['processos_listados'] = obter_boletos_solicitados(st.session_state['session'], SISGAT_URL_BASE)
        else:
            st.session_state['processos_listados'] = []

    if 'processos_listados' in st.session_state and st.session_state['processos_listados']:
        st.subheader("Selecione um Processo")

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
        st.warning("Nenhum processo encontrado após o login.")


# --- Área Principal ---
st.header("Detalhes do Processo/Boleto Selecionado")

if 'selected_process' in st.session_state and st.session_state['selected_process']:
    processo_para_detalhes = st.session_state['selected_process']
    processo_id = processo_para_detalhes.get('id_boleto')

    if processo_id and 'session' in st.session_state and st.session_state['session']:
        st.subheader(f"Processo Nº: {processo_para_detalhes.get('n_do_processo', 'N/A')}")
        st.write(f"**Cliente:** {processo_para_detalhes.get('cliente', 'N/A')}")
        st.write(f"**Tipo de Taxa:** {processo_para_detalhes.get('tipo_de_taxa', 'N/A')}")
        st.write(f"**Status:** {processo_para_detalhes.get('status', 'N/A')}")

        st.markdown("---")

        detalhes_completos = obter_detalhes_boleto_sisgat(st.session_state['session'], processo_id, SISGAT_URL_BASE)

        if detalhes_completos:

            # --- INDICADOR DE BOLETO ANEXADO ---
            st.subheader("📎 Situação do Boleto")

            boleto_texto = detalhes_completos.get('boleto_anexado_texto')
            boleto_href = detalhes_completos.get('boleto_anexado_href')

            # Considera anexado se há texto não vazio e diferente de traço/vazio padrão
            boleto_vazio = not boleto_texto or boleto_texto.strip() in ('', '-', 'N/A', 'Não informado')

            if boleto_vazio:
                st.error("❌ Boleto NÃO anexado — nenhum arquivo foi vinculado a este processo.")
            else:
                st.success("✅ Boleto ANEXADO ao processo.")
                if boleto_href:
                    # Monta URL absoluta se o href for relativo
                    url_download = boleto_href if boleto_href.startswith('http') else f"{SISGAT_URL_BASE}{boleto_href}"
                    st.markdown(f"[📄 Clique aqui para visualizar/baixar o boleto]({url_download})")
                else:
                    st.write(f"Conteúdo do campo Boleto: {boleto_texto}")

            st.markdown("---")

            # --- DEMAIS DETALHES ---
            st.subheader("Detalhes Completos")

            # Campos internos de controle que não precisam aparecer na tabela de detalhes
            campos_ocultos = {'boleto_anexado_texto', 'boleto_anexado_href'}

            for key, value in detalhes_completos.items():
                if key in campos_ocultos:
                    continue
                st.write(f"**{key.replace('_', ' ').title()}:** {value}")
        else:
            st.warning(f"Não foi possível carregar os detalhes para o Processo/Boleto ID: {processo_id}.")
    else:
        st.warning("Selecione um processo válido na barra lateral para ver os detalhes.")

elif 'login_status' in st.session_state and st.session_state['login_status'] != "Login bem-sucedido!":
    st.error("Por favor, faça o login na barra lateral para carregar os processos.")
else:
    st.info("Faça o login na barra lateral e selecione um processo para visualizar os detalhes.")
