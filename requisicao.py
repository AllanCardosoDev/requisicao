import os
import re
import json
import time
from datetime import datetime, date, timedelta

import requests
from bs4 import BeautifulSoup
import streamlit as st


# ============================================================
# CONFIGURAÇÕES — BRADESCO API
# ============================================================

BRADESCO_CLIENT_ID     = "seu_client_id_aqui"
BRADESCO_CLIENT_SECRET = "seu_client_secret_aqui"

# Dados do beneficiário (sua organização no Bradesco)
BRADESCO_CNPJ_RAIZ     = 999999999   # nuCPFCNPJ  — raiz sem filial/dígito
BRADESCO_CNPJ_FILIAL   = 1           # filialCPFCNPJ
BRADESCO_CNPJ_CTRL     = 99          # ctrlCPFCNPJ
BRADESCO_PRODUTO       = 9           # 9 = Cobrança Escritural
BRADESCO_NEGOCIACAO    = 28560000000222652  # agência(4) + zeros(7) + conta(7)

# URLs
BRADESCO_URL_TOKEN    = "https://proxy.api.prebanco.com.br/auth/server/v1.1/token"
BRADESCO_BASE_SANDBOX = "https://openapisandbox.prebanco.com.br"
BRADESCO_BASE_PROD    = "https://openapi.bradesco.com.br"
BRADESCO_BASE         = BRADESCO_BASE_SANDBOX   # ← trocar para PROD quando homologar

BRADESCO_URL_REGISTRO = f"{BRADESCO_BASE}/boleto/cobranca-registro/v1/cobranca"
BRADESCO_URL_CONSULTA = f"{BRADESCO_BASE}/boleto/cobranca-consulta/v1/consultar"
BRADESCO_URL_BAIXA    = f"{BRADESCO_BASE}/boleto/cobranca-baixa/v1/baixar"


# ============================================================
# FUNÇÕES — BRADESCO API
# ============================================================

def bradesco_obter_token() -> str | None:
    """Obtém token OAuth 2.0 do Bradesco."""
    try:
        response = requests.post(
            BRADESCO_URL_TOKEN,
            data={
                "grant_type":    "client_credentials",
                "client_id":     BRADESCO_CLIENT_ID,
                "client_secret": BRADESCO_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        return None
    except Exception:
        return None


def _bradesco_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


def bradesco_registrar_boleto(token: str, detalhes: dict, data_vencimento: date) -> dict:
    """
    Monta e envia o boleto para a API do Bradesco.
    Retorna o JSON de resposta.
    """
    hoje    = datetime.today().strftime("%d.%m.%Y")
    vencto  = data_vencimento.strftime("%d.%m.%Y")

    # ── Separar lógica de CPF x CNPJ ────────────────────────
    cpf_cnpj_raw = re.sub(r"\D", "", detalhes.get("cpf_cnpj", ""))
    if len(cpf_cnpj_raw) <= 11:
        tipo_doc   = 1   # CPF
    else:
        tipo_doc   = 2   # CNPJ

    # ── Valor ────────────────────────────────────────────────
    valor_str = (
        detalhes.get("valor", "0")
        .replace("R$", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    try:
        valor = float(valor_str)
    except ValueError:
        valor = 0.0

    # ── Endereço ─────────────────────────────────────────────
    endereco_raw

