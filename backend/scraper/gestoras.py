"""
Scraper de relatórios gerenciais para os 16 fundos da carteira.

Estratégias:
  1. relatoriosfiis.com.br  → obtém IDs FNET → download FNET (base64)
     Funciona para todos os fundos que publicam via B3/CVM.
  2. Valora direct           → PDF binário direto do WordPress
     Usado para VGHF11 e VGIA11 como primary (fallback p/ relatoriosfiis).

FNET retorna o PDF como string JSON base64 — é necessário decodificar.
"""

import requests
import os
import re
import sys
import base64
import io
from datetime import datetime, timedelta
from urllib.parse import quote
from bs4 import BeautifulSoup

if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

HEADERS_PDF = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.9",
}

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

# Fundos com URL direta nas gestoras (sem FNET)
GESTORAS_DIRETAS = {
    "VGHF11": "valora",
    "VGIA11": "valora",
}


# ──────────────────────────────────────────────
# Estratégia 1: relatoriosfiis.com.br + FNET
# ──────────────────────────────────────────────

def _get_fnet_ids(ticker: str, meses: int = 3) -> list[tuple[str, str]]:
    """
    Scraping de relatoriosfiis.com.br/{ticker}.
    Retorna lista de (doc_id, label) para os `meses` relatórios mais recentes.
    """
    url = f"https://www.relatoriosfiis.com.br/{ticker}"
    try:
        r = requests.get(url, headers=HEADERS_HTML, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"    [ERRO relatoriosfiis] {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    ids = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"downloadDocumento\?id=(\d+)", href)
        if m:
            doc_id = m.group(1)
            label = a.get_text(strip=True) or doc_id
            if (doc_id, label) not in ids:
                ids.append((doc_id, label))
    return ids[:meses]


def _baixar_fnet_id(doc_id: str, pasta: str, nome: str, tentativas: int = 3) -> str | None:
    """
    Baixa PDF do FNET pelo ID. FNET retorna JSON com PDF em base64.
    Salva o arquivo decodificado em `pasta/nome`.
    """
    caminho = os.path.join(pasta, nome)
    if os.path.exists(caminho):
        print(f"    [SKIP] Já existe: {nome}")
        return caminho

    url = f"https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id={doc_id}"
    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.get(url, headers=HEADERS_PDF, timeout=60)
            r.raise_for_status()

            conteudo = r.content
            # FNET retorna JSON string base64: "JVBERi0xLjc..."
            if conteudo[:1] == b'"':
                b64_str = conteudo.decode("utf-8").strip().strip('"')
                conteudo = base64.b64decode(b64_str)

            if conteudo[:4] != b"%PDF":
                print(f"    [AVISO] Resposta inesperada para id={doc_id}: {conteudo[:20]}")
                return None

            os.makedirs(pasta, exist_ok=True)
            with open(caminho, "wb") as f:
                f.write(conteudo)
            print(f"    [OK] {nome} ({len(conteudo)//1024} KB)")
            return caminho

        except requests.exceptions.Timeout:
            if tentativa < tentativas:
                print(f"    [TIMEOUT tentativa {tentativa}/{tentativas}] id={doc_id}, retentando...")
            else:
                print(f"    [TIMEOUT] id={doc_id} falhou após {tentativas} tentativas")
        except Exception as e:
            print(f"    [ERRO FNET id={doc_id}] {e}")
            return None

    return None


def _baixar_via_relatoriosfiis(ticker: str, pasta: str, meses: int = 3) -> list[str]:
    """Obtém IDs via relatoriosfiis.com.br e baixa os PDFs do FNET."""
    ids = _get_fnet_ids(ticker, meses)
    if not ids:
        print(f"    [AVISO] Nenhum ID FNET encontrado para {ticker}")
        return []

    print(f"    Encontrados {len(ids)} IDs FNET para {ticker}")
    baixados = []
    for i, (doc_id, label) in enumerate(ids):
        # Gerar nome legível para o arquivo
        nome = f"{ticker}_{doc_id}.pdf"
        caminho = _baixar_fnet_id(doc_id, pasta, nome)
        if caminho:
            baixados.append(caminho)

    return baixados


# ──────────────────────────────────────────────
# Estratégia 2: Valora (WordPress, URL direta)
# ──────────────────────────────────────────────

def _baixar_valora(ticker: str, pasta: str, meses: int = 3) -> list[str]:
    """
    Valora: valorainvest.com.br/wp-content/uploads/YYYY/MM/
    Arquivo: Relatorio-de-Gestao-{TICKER}-{Mes}{YY}.pdf
    Ex: Relatorio-de-Gestao-VGHF11-Janeiro26.pdf (publicado em fev/26)
    Note: Valora usa "Marco" sem cedilha nas URLs.
    """
    agora = datetime.now()
    baixados = []

    for delta in range(1, meses + 3):
        ref = agora - timedelta(days=30 * delta)
        ano = ref.year
        mes_num = ref.month
        mes_nome = MESES_PT[mes_num]  # já sem cedilha (Marco, não Março)
        ano_curto = str(ano)[-2:]

        pub = agora - timedelta(days=30 * (delta - 1))
        pub_ano = pub.year
        pub_mes = str(pub.month).zfill(2)

        nome_arquivo = f"Relatorio-de-Gestao-{ticker}-{mes_nome}{ano_curto}.pdf"
        url = (
            f"https://valorainvest.com.br/wp-content/uploads/"
            f"{pub_ano}/{pub_mes}/{nome_arquivo}"
        )
        nome_local = f"{ticker}_{ano}-{str(mes_num).zfill(2)}.pdf"
        caminho_local = os.path.join(pasta, nome_local)

        if os.path.exists(caminho_local):
            print(f"    [SKIP] Já existe: {nome_local}")
            baixados.append(caminho_local)
            if len(baixados) >= meses:
                break
            continue

        print(f"    Tentando Valora: {url}")
        try:
            r = requests.get(url, headers=HEADERS_PDF, timeout=25)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                os.makedirs(pasta, exist_ok=True)
                with open(caminho_local, "wb") as f:
                    f.write(r.content)
                print(f"    [OK] {nome_local} ({len(r.content)//1024} KB)")
                baixados.append(caminho_local)
                if len(baixados) >= meses:
                    break
            elif r.status_code == 404:
                pass  # continua tentando mês anterior
            else:
                print(f"    [AVISO] HTTP {r.status_code} para {url}")
        except Exception as e:
            print(f"    [ERRO] {e}")

    return baixados


# ──────────────────────────────────────────────
# Ponto de entrada principal
# ──────────────────────────────────────────────

def baixar_relatorios_gestora(ticker: str, pasta_base: str, meses: int = 3) -> list[str]:
    """
    Baixa relatórios gerenciais para o ticker.
    Retorna lista de caminhos dos PDFs salvos.
    """
    pasta = os.path.join(pasta_base, ticker.lower())

    estrategia = GESTORAS_DIRETAS.get(ticker, "relatoriosfiis")
    print(f"  [{ticker}] Estrategia: {estrategia}")

    if estrategia == "valora":
        baixados = _baixar_valora(ticker, pasta, meses)
        # Fallback para relatoriosfiis se Valora não tiver o mais recente
        if len(baixados) < meses:
            extras = _baixar_via_relatoriosfiis(ticker, pasta, meses - len(baixados))
            baixados += extras
        return baixados

    return _baixar_via_relatoriosfiis(ticker, pasta, meses)


def scrape_todos(tickers: list[str], pasta_base: str, meses: int = 3) -> dict:
    """Baixa relatórios para lista de tickers. Retorna dict ticker -> [caminhos]."""
    resultados = {}
    for ticker in tickers:
        print(f"\n{'='*50}")
        print(f"[{ticker}] Buscando relatorios gerenciais")
        print(f"{'='*50}")
        caminhos = baixar_relatorios_gestora(ticker, pasta_base, meses)
        resultados[ticker] = caminhos
        status = f"OK ({len(caminhos)} PDF)" if caminhos else "FALHOU"
        print(f"  [{ticker}] {status}")
    return resultados


if __name__ == "__main__":
    pasta_dados = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "dados"
    )
    tickers_teste = sys.argv[1:] if len(sys.argv) > 1 else [
        "VGHF11", "KNSC11", "DEVA11", "MXRF11", "RBRY11"
    ]
    print(f"Testando download para: {tickers_teste}")
    resultados = scrape_todos(tickers_teste, pasta_dados, meses=2)

    print("\n\nRESUMO:")
    for ticker, pdfs in resultados.items():
        status = "OK" if pdfs else "FALHOU"
        print(f"  {ticker}: [{status}] {len(pdfs)} PDF(s)")
