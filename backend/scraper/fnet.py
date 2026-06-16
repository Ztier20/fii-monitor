"""
Scraper do Fundos.NET (B3) para download de relatórios gerenciais.
Busca por CNPJ, lista os documentos disponíveis e baixa os PDFs.
"""

import requests
import os
import time
import json
from datetime import datetime

BASE_URL = "https://fnet.bmfbovespa.com.br/fnet/publico"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/abrirGerenciadorDocumentosCVM",
}

# Tipo de documento 14 = Relatório Gerencial
# Tipo de documento 41 = Informe Mensal
TIPO_DOC = {
    "relatorio_gerencial": 14,
    "informe_mensal": 41,
    "informe_trimestral": 12,
}


def buscar_documentos(cnpj: str, tipo: str = "relatorio_gerencial", meses: int = 6) -> list:
    """
    Busca documentos de um fundo no Fundos.NET por CNPJ.
    Retorna lista de dicts com id, nome, data, url_download.
    """
    cnpj_limpo = cnpj.replace(".", "").replace("/", "").replace("-", "")
    id_tipo = TIPO_DOC.get(tipo, 14)

    url = f"{BASE_URL}/pesquisarGerenciadorDocumentosCVM"
    params = {
        "d": 1,
        "tipoFundo": 1,
        "cnpj": cnpj,
        "idCategoriaDocumento": 0,
        "idTipoDocumento": id_tipo,
        "dataInicial": "",
        "dataFinal": "",
        "_": int(time.time() * 1000),
    }

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        dados = r.json()
    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT] Fundos.NET não respondeu para CNPJ {cnpj}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"  [ERRO] Fundos.NET: {e}")
        return []
    except json.JSONDecodeError:
        print(f"  [ERRO] Resposta não é JSON para CNPJ {cnpj}")
        return []

    documentos = []
    itens = dados.get("data", dados.get("aaData", []))

    for item in itens[:meses]:
        doc_id = item.get("id") or item.get("idDocumento") or item.get("0")
        nome = item.get("descricaoTipoDocumento") or item.get("nomeDocumento") or item.get("4", "")
        data_entrega = item.get("dataEntrega") or item.get("dataReferencia") or item.get("3", "")
        competencia = item.get("dataReferencia") or item.get("2", "")

        if doc_id:
            documentos.append({
                "id": doc_id,
                "nome": nome,
                "data_entrega": data_entrega,
                "competencia": competencia,
                "url_download": f"{BASE_URL}/downloadDocumento?id={doc_id}",
                "url_visualizar": f"{BASE_URL}/exibirDocumento?id={doc_id}&cvm=true",
            })

    return documentos


def baixar_pdf(doc: dict, pasta_destino: str) -> str | None:
    """
    Baixa o PDF de um documento e salva em pasta_destino.
    Retorna o caminho do arquivo salvo ou None se falhar.
    """
    os.makedirs(pasta_destino, exist_ok=True)

    competencia = doc.get("competencia", "sem-data")
    if competencia:
        try:
            dt = datetime.strptime(competencia[:10], "%Y-%m-%d")
            competencia = dt.strftime("%Y-%m")
        except Exception:
            competencia = str(competencia)[:7]

    nome_arquivo = f"{competencia}_relatorio.pdf"
    caminho = os.path.join(pasta_destino, nome_arquivo)

    if os.path.exists(caminho):
        print(f"  [SKIP] Já existe: {nome_arquivo}")
        return caminho

    try:
        r = requests.get(doc["url_download"], headers=HEADERS, timeout=60, stream=True)
        r.raise_for_status()

        with open(caminho, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        tamanho = os.path.getsize(caminho) / 1024
        print(f"  [OK] {nome_arquivo} ({tamanho:.0f} KB)")
        return caminho

    except Exception as e:
        print(f"  [ERRO] Download {doc['id']}: {e}")
        if os.path.exists(caminho):
            os.remove(caminho)
        return None


def scrape_fundo(ticker: str, cnpj: str, pasta_base: str, meses: int = 6) -> list:
    """
    Pipeline completo para um fundo: busca documentos e baixa PDFs.
    Retorna lista de caminhos dos PDFs baixados.
    """
    print(f"\n[{ticker}] Buscando relatórios gerenciais ({cnpj})...")

    pasta_fundo = os.path.join(pasta_base, ticker.lower())
    documentos = buscar_documentos(cnpj, tipo="relatorio_gerencial", meses=meses)

    if not documentos:
        print(f"  [AVISO] Nenhum documento encontrado. Tentando informe mensal...")
        documentos = buscar_documentos(cnpj, tipo="informe_mensal", meses=meses)

    if not documentos:
        print(f"  [FALHOU] Sem documentos para {ticker}")
        return []

    print(f"  Encontrados {len(documentos)} documentos")

    baixados = []
    for doc in documentos:
        caminho = baixar_pdf(doc, pasta_fundo)
        if caminho:
            baixados.append(caminho)
        time.sleep(1)

    return baixados
