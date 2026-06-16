"""
Script principal de coleta.
Executa para todos os fundos da carteira:
  1. Dados estruturados via CVM (números)
  2. PDFs dos relatórios gerenciais via Fundos.NET

Uso:
  python coletar.py              -> coleta todos
  python coletar.py RZAG11      -> coleta apenas RZAG11
  python coletar.py --cvm-only  -> apenas dados CVM, sem baixar PDFs
"""

import sys
import os
import json
from datetime import datetime

# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from carteira import CARTEIRA
from scraper.cvm import extrair_indicadores_cvm
from scraper.gestoras import baixar_relatorios_gestora

PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dados")
PASTA_LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")

os.makedirs(PASTA_DADOS, exist_ok=True)
os.makedirs(PASTA_LOGS, exist_ok=True)


def coletar_fundo(ticker: str, info: dict, cvm_only: bool = False) -> dict:
    resultado = {
        "ticker": ticker,
        "nome": info["nome"],
        "cnpj": info["cnpj"],
        "tipo": info["tipo"],
        "categoria": info["categoria"],
        "timestamp": datetime.now().isoformat(),
        "cvm": {},
        "pdfs": [],
        "status": "ok",
        "erros": [],
    }

    # 1. Dados estruturados CVM
    print(f"\n{'='*50}")
    print(f"[{ticker}] {info['nome']}")
    print(f"{'='*50}")
    print(f"  Coletando dados CVM...")

    try:
        indicadores = extrair_indicadores_cvm(info["cnpj"], tipo=info["tipo"])
        resultado["cvm"] = indicadores
        if indicadores:
            print(f"  [OK] CVM: data_ref={indicadores.get('data_referencia', 'N/A')} | "
                  f"PL={indicadores.get('pl', 'N/A')} | "
                  f"DY={indicadores.get('dy_mensal_pct', 'N/A')}%")
        else:
            print(f"  [AVISO] CVM: sem dados encontrados para {ticker}")
            resultado["erros"].append("CVM: sem dados")
    except Exception as e:
        print(f"  [ERRO] CVM: {e}")
        resultado["erros"].append(f"CVM: {e}")

    # 2. PDFs via gestoras (relatoriosfiis.com.br + FNET)
    if not cvm_only:
        try:
            pdfs = baixar_relatorios_gestora(ticker, PASTA_DADOS, meses=3)
            resultado["pdfs"] = pdfs
            if pdfs:
                print(f"  [OK] {len(pdfs)} PDF(s) baixado(s)")
            else:
                print(f"  [AVISO] Nenhum PDF baixado para {ticker}")
                resultado["erros"].append("PDFs: sem relatórios encontrados")
        except Exception as e:
            print(f"  [ERRO] PDFs: {e}")
            resultado["erros"].append(f"PDFs: {e}")

    if resultado["erros"]:
        resultado["status"] = "parcial" if resultado["cvm"] or resultado["pdfs"] else "erro"

    return resultado


def main():
    args = sys.argv[1:]
    cvm_only = "--cvm-only" in args
    tickers_filtro = [a for a in args if not a.startswith("--")]

    if tickers_filtro:
        carteira = {t: CARTEIRA[t] for t in tickers_filtro if t in CARTEIRA}
        if not carteira:
            print(f"Ticker(s) não encontrado(s): {tickers_filtro}")
            print(f"Disponíveis: {list(CARTEIRA.keys())}")
            sys.exit(1)
    else:
        carteira = CARTEIRA

    modo = "CVM apenas" if cvm_only else "CVM + PDFs"
    print(f"\nFII Monitor — Coleta de dados ({modo})")
    print(f"Fundos: {list(carteira.keys())}")
    print(f"Início: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    resultados = {}
    for ticker, info in carteira.items():
        resultado = coletar_fundo(ticker, info, cvm_only=cvm_only)
        resultados[ticker] = resultado

    # Salvar log da coleta
    log_path = os.path.join(PASTA_LOGS, f"coleta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    # Resumo
    print(f"\n{'='*50}")
    print("RESUMO DA COLETA")
    print(f"{'='*50}")
    ok = sum(1 for r in resultados.values() if r["status"] == "ok")
    parcial = sum(1 for r in resultados.values() if r["status"] == "parcial")
    erro = sum(1 for r in resultados.values() if r["status"] == "erro")
    print(f"  OK:      {ok}")
    print(f"  Parcial: {parcial}")
    print(f"  Erro:    {erro}")
    print(f"\nLog salvo em: {log_path}")

    for ticker, r in resultados.items():
        if r["erros"]:
            print(f"  [{ticker}] {r['erros']}")


if __name__ == "__main__":
    main()
