"""
Coleta dados estruturados (numéricos) da CVM Dados Abertos.
Fonte primária para: PL, cotas, DY, ativos/passivos.
Funciona 100% sem login ou captcha.
"""

import requests
import zipfile
import io
import csv
import os
from datetime import datetime

BASE_CVM = "https://dados.cvm.gov.br/dados"

URLS_FII = {
    "geral":        "{base}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip",
    "ativo_passivo": "{base}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip",
}

URLS_FIAGRO = {
    "mensal": "{base}/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_{anomes}.zip",
}

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _baixar_zip(url: str) -> zipfile.ZipFile | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return zipfile.ZipFile(io.BytesIO(r.content))
    except Exception as e:
        print(f"  [ERRO CVM] {url}: {e}")
        return None


def _ler_csv_zip(z: zipfile.ZipFile, nome_parcial: str) -> list[dict]:
    for name in z.namelist():
        if nome_parcial in name.lower():
            content = z.read(name).decode("latin-1")
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            return list(reader)
    return []


def buscar_informe_mensal_fii(cnpj: str, ano: int = None) -> list[dict]:
    """
    Retorna histórico de informes mensais de um FII pelo CNPJ.
    """
    if ano is None:
        ano = datetime.now().year

    url = f"{BASE_CVM}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
    z = _baixar_zip(url)
    if not z:
        return []

    rows = _ler_csv_zip(z, "geral")
    resultado = [r for r in rows if r.get("CNPJ_Fundo_Classe", "").strip() == cnpj.strip()]
    resultado.sort(key=lambda x: x.get("Data_Referencia", ""), reverse=True)
    return resultado


def buscar_ativo_passivo_fii(cnpj: str, ano: int = None) -> list[dict]:
    """
    Retorna histórico de ativos/passivos de um FII pelo CNPJ.
    """
    if ano is None:
        ano = datetime.now().year

    url = f"{BASE_CVM}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
    z = _baixar_zip(url)
    if not z:
        return []

    rows = _ler_csv_zip(z, "ativo_passivo")
    resultado = [r for r in rows if r.get("CNPJ_Fundo_Classe", "").strip() == cnpj.strip()]
    resultado.sort(key=lambda x: x.get("Data_Referencia", ""), reverse=True)
    return resultado


def buscar_informe_fiagro(cnpj: str, anomes: str = None) -> list[dict]:
    """
    Retorna informe mensal de um FIAGRO.
    anomes no formato YYYYMM (ex: '202505')
    """
    if anomes is None:
        now = datetime.now()
        anomes = now.strftime("%Y%m")
        # FIAGRO tem 1 mês de delay — usar mês anterior
        if now.month == 1:
            anomes = f"{now.year - 1}12"
        else:
            anomes = f"{now.year}{str(now.month - 1).zfill(2)}"

    url = f"{BASE_CVM}/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_{anomes}.zip"
    z = _baixar_zip(url)
    if not z:
        return []

    for name in z.namelist():
        if "fiagro" in name.lower() and name.endswith(".csv"):
            content = z.read(name).decode("latin-1")
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            rows = list(reader)
            resultado = [r for r in rows if cnpj.replace(".", "").replace("/", "").replace("-", "") in
                         r.get("CNPJ_Classe", "").replace(".", "").replace("/", "").replace("-", "")]
            return resultado
    return []


def buscar_complemento_fii(cnpj: str, ano: int = None) -> list[dict]:
    """Retorna dados do arquivo complemento (PL, DY, rentabilidade, cotistas)."""
    if ano is None:
        ano = datetime.now().year

    url = f"{BASE_CVM}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
    z = _baixar_zip(url)
    if not z:
        return []

    rows = _ler_csv_zip(z, "complemento")
    resultado = [r for r in rows if r.get("CNPJ_Fundo_Classe", "").strip() == cnpj.strip()]
    resultado.sort(key=lambda x: x.get("Data_Referencia", ""), reverse=True)
    return resultado


def extrair_indicadores_cvm(cnpj: str, tipo: str = "FII") -> dict:
    """
    Extrai os indicadores mais recentes de um fundo via CVM.
    Retorna dict com os campos principais.
    """
    ano_atual = datetime.now().year

    if tipo == "FIAGRO":
        # FIAGROs: tentar últimos 3 meses
        now = datetime.now()
        for delta in range(1, 4):
            mes = now.month - delta
            ano = now.year
            if mes <= 0:
                mes += 12
                ano -= 1
            anomes = f"{ano}{str(mes).zfill(2)}"
            rows = buscar_informe_fiagro(cnpj, anomes)
            if rows:
                r = rows[0]
                return {
                    "fonte": "CVM-FIAGRO",
                    "data_referencia": r.get("Data_Referencia", anomes),
                    "pl": r.get("Patrimonio_Liquido", ""),
                    "cotas_emitidas": r.get("Quantidade_Cotas_Emitidas", ""),
                    "valor_cota_patrimonial": r.get("Valor_Cota", ""),
                    "cotistas": r.get("Numero_Cotistas", ""),
                }
        return {}

    # FII — tenta ano atual e anterior se necessário
    for ano in [ano_atual, ano_atual - 1]:
        rows_comp = buscar_complemento_fii(cnpj, ano)
        rows_ap = buscar_ativo_passivo_fii(cnpj, ano)
        rows_geral = buscar_informe_mensal_fii(cnpj, ano)

        if rows_comp:
            c = rows_comp[0]
            ap = rows_ap[0] if rows_ap else {}
            g = rows_geral[0] if rows_geral else {}
            return {
                "fonte": "CVM-FII",
                "data_referencia": c.get("Data_Referencia", ""),
                "nome": g.get("Nome_Fundo_Classe", ""),
                "ativo_total": c.get("Valor_Ativo", ""),
                "pl": c.get("Patrimonio_Liquido", ""),
                "cotas_emitidas": c.get("Cotas_Emitidas", ""),
                "valor_cota_patrimonial": c.get("Valor_Patrimonial_Cotas", ""),
                "dy_mensal_pct": c.get("Percentual_Dividend_Yield_Mes", ""),
                "rentabilidade_mensal_pct": c.get("Percentual_Rentabilidade_Efetiva_Mes", ""),
                "rentabilidade_patrimonial_pct": c.get("Percentual_Rentabilidade_Patrimonial_Mes", ""),
                "taxa_admin_pct": c.get("Percentual_Despesas_Taxa_Administracao", ""),
                "cotistas": c.get("Total_Numero_Cotistas", ""),
                "cotistas_pf": c.get("Numero_Cotistas_Pessoa_Fisica", ""),
                "cri_cra": ap.get("CRI_CRA", ap.get("CRI", "")),
                "fii_carteira": ap.get("FII", ""),
                "total_investido": ap.get("Total_Investido", ""),
                "pl_passivo": ap.get("Total_Passivo", ""),
            }

    return {}
