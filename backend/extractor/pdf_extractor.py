"""
Extrator de texto de relatórios gerenciais de FIIs.
Usa pdfplumber para extrair texto e tabelas dos PDFs.
Limita o conteúdo enviado à IA para evitar exceder tokens.
"""

import os
import re
import pdfplumber

MAX_CHARS = 80_000   # ~20k tokens — suficiente para relatórios de 15-20 págs
MAX_PAGES = 30


def extrair_texto_pdf(caminho_pdf: str, max_chars: int = MAX_CHARS) -> str:
    """
    Extrai texto de um PDF usando pdfplumber.
    Retorna string com o texto de todas as páginas (até MAX_PAGES).
    Limita a max_chars para controlar uso de tokens.
    """
    texto_total = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            n_paginas = min(len(pdf.pages), MAX_PAGES)
            for i, page in enumerate(pdf.pages[:n_paginas]):
                texto = page.extract_text()
                if texto:
                    texto_total.append(f"--- Página {i+1} ---\n{texto}")

                # Extrair tabelas como texto formatado
                tabelas = page.extract_tables()
                for tabela in tabelas:
                    linhas_tab = []
                    for linha in tabela:
                        celulas = [str(c or "").strip() for c in linha]
                        linhas_tab.append(" | ".join(celulas))
                    if linhas_tab:
                        texto_total.append("TABELA:\n" + "\n".join(linhas_tab))

    except Exception as e:
        return f"[ERRO ao extrair PDF: {e}]"

    resultado = "\n\n".join(texto_total)
    if len(resultado) > max_chars:
        resultado = resultado[:max_chars] + "\n\n[... texto truncado para caber no limite de tokens ...]"

    return resultado


def encontrar_pdf_mais_recente(pasta_ticker: str) -> str | None:
    """
    Dado o diretório de um ticker (ex: dados/deva11/),
    retorna o caminho do PDF mais recentemente modificado.
    """
    if not os.path.isdir(pasta_ticker):
        return None

    pdfs = [
        os.path.join(pasta_ticker, f)
        for f in os.listdir(pasta_ticker)
        if f.lower().endswith(".pdf")
    ]
    if not pdfs:
        return None

    return max(pdfs, key=os.path.getmtime)


def extrair_para_fundo(ticker: str, pasta_dados: str) -> dict:
    """
    Extrai texto do PDF mais recente de um fundo.
    Retorna dict com ticker, caminho_pdf, texto, n_chars.
    """
    pasta = os.path.join(pasta_dados, ticker.lower())
    pdf = encontrar_pdf_mais_recente(pasta)

    if not pdf:
        return {
            "ticker": ticker,
            "caminho_pdf": None,
            "texto": "",
            "n_chars": 0,
            "erro": "Nenhum PDF encontrado",
        }

    texto = extrair_texto_pdf(pdf)
    return {
        "ticker": ticker,
        "caminho_pdf": pdf,
        "texto": texto,
        "n_chars": len(texto),
        "erro": None,
    }


if __name__ == "__main__":
    import sys
    pasta = os.path.join(os.path.dirname(__file__), "..", "..", "dados")
    ticker = sys.argv[1] if len(sys.argv) > 1 else "DEVA11"
    resultado = extrair_para_fundo(ticker, pasta)
    print(f"[{ticker}] PDF: {resultado['caminho_pdf']}")
    print(f"[{ticker}] Chars extraídos: {resultado['n_chars']}")
    if resultado["texto"]:
        print("\n--- Amostra (primeiros 1000 chars) ---")
        print(resultado["texto"][:1000])
