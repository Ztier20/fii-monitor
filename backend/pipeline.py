"""
Pipeline completo de análise FII Monitor.
Para cada fundo da carteira:
  1. Extrai texto do PDF mais recente
  2. Coleta dados CVM
  3. Analisa via Claude API
  4. Salva JSON de análise

Uso:
  python pipeline.py              -> todos os fundos
  python pipeline.py DEVA11 KNSC11 -> fundos específicos
  python pipeline.py --resumo     -> exibe resumo das análises salvas (sem rodar IA)
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from carteira import CARTEIRA
from extractor.pdf_extractor import extrair_para_fundo
from scraper.cvm import extrair_indicadores_cvm
from analyzer.ia_analise import analisar_fundo

PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dados")
PASTA_ANALISES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analises")

os.makedirs(PASTA_ANALISES, exist_ok=True)

COR = {
    "COMPRA": "✅",
    "MANUTENÇÃO": "🟡",
    "REDUÇÃO": "🟠",
    "VENDA": "🔴",
}


def analisar_ticker(ticker: str) -> dict:
    info = CARTEIRA[ticker]
    print(f"\n{'='*60}")
    print(f"[{ticker}] {info['nome']}")
    print(f"{'='*60}")

    # 1. Extrair PDF
    extracao = extrair_para_fundo(ticker, PASTA_DADOS)
    if not extracao["texto"]:
        print(f"  [ERRO] Sem texto extraído: {extracao.get('erro', 'desconhecido')}")
        return {"ticker": ticker, "erro": "sem_pdf"}
    print(f"  [OK] PDF: {os.path.basename(extracao['caminho_pdf'])} — {extracao['n_chars']:,} chars")

    # 2. Dados CVM
    dados_cvm = extrair_indicadores_cvm(info["cnpj"], tipo=info["tipo"])
    if dados_cvm:
        print(f"  [OK] CVM: ref={dados_cvm.get('data_referencia','')} | PL={dados_cvm.get('pl','')}")
    else:
        print(f"  [AVISO] CVM: sem dados")

    # 3. Análise IA
    analise = analisar_fundo(
        ticker=ticker,
        nome=info["nome"],
        categoria=info["categoria"],
        texto_relatorio=extracao["texto"],
        dados_cvm=dados_cvm,
    )

    if "erro" in analise:
        print(f"  [ERRO] IA: {analise['erro']}")
        return analise

    tokens = analise.get("_tokens_usados", {})
    print(f"  [OK] IA: {tokens.get('input',0):,} in / {tokens.get('output',0):,} out tokens")

    veredicto = analise.get("veredicto", {})
    rec = veredicto.get("recomendacao", "N/A")
    print(f"  [VEREDICTO] {COR.get(rec, '❓')} {rec} — {veredicto.get('tese_principal','')[:80]}")

    # Salvar JSON
    caminho_json = os.path.join(PASTA_ANALISES, f"{ticker}_analise.json")
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(analise, f, ensure_ascii=False, indent=2)
    print(f"  [SALVO] {caminho_json}")

    return analise


def exibir_resumo():
    """Lê JSONs de análise já salvos e exibe painel resumido."""
    jsons = [f for f in os.listdir(PASTA_ANALISES) if f.endswith("_analise.json")]
    if not jsons:
        print("Nenhuma análise salva ainda. Rode pipeline.py primeiro.")
        return

    analises = []
    for nome_arquivo in sorted(jsons):
        caminho = os.path.join(PASTA_ANALISES, nome_arquivo)
        with open(caminho, encoding="utf-8") as f:
            analises.append(json.load(f))

    print(f"\n{'='*80}")
    print("PAINEL FII MONITOR — RESUMO DAS ANÁLISES")
    print(f"{'='*80}")
    print(f"{'Ticker':<10} {'Rec.':<12} {'DY Mensal':<12} {'P/VP':<8} {'Risco':<8} Tese")
    print("-"*80)

    for a in analises:
        ticker = a.get("ticker", "?")
        veredicto = a.get("veredicto", {})
        financeiro = a.get("financeiro", {})
        riscos = a.get("riscos", [])

        rec = veredicto.get("recomendacao", "N/A")
        emoji = COR.get(rec, "❓")
        dy = financeiro.get("dy_mensal_pct")
        pvp = financeiro.get("pvp")
        risco_alto = sum(1 for r in riscos if r.get("nivel") == "alto")
        tese = veredicto.get("tese_principal", "")[:50]

        dy_str = f"{dy}%" if dy else "N/A"
        pvp_str = f"{pvp:.2f}x" if pvp else "N/A"

        print(f"{ticker:<10} {emoji}{rec:<10} {dy_str:<12} {pvp_str:<8} {'⚠️'*risco_alto:<8} {tese}")

    print(f"\nTotal: {len(analises)} fundos analisados")
    print(f"{'='*80}")

    # Resumo por recomendação
    por_rec = {}
    for a in analises:
        r = a.get("veredicto", {}).get("recomendacao", "N/A")
        por_rec.setdefault(r, []).append(a.get("ticker", "?"))

    for rec, tickers in sorted(por_rec.items()):
        print(f"  {COR.get(rec,'❓')} {rec}: {', '.join(tickers)}")


def main():
    args = sys.argv[1:]

    if "--resumo" in args:
        exibir_resumo()
        return

    tickers_filtro = [a for a in args if not a.startswith("--")]
    if tickers_filtro:
        carteira = {t: CARTEIRA[t] for t in tickers_filtro if t in CARTEIRA}
        invalidos = [t for t in tickers_filtro if t not in CARTEIRA]
        if invalidos:
            print(f"Tickers inválidos: {invalidos}")
    else:
        carteira = CARTEIRA

    print(f"\nFII Monitor — Pipeline de Análise IA")
    print(f"Fundos: {list(carteira.keys())}")
    print(f"Início: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    resultados = {}
    for ticker in carteira:
        resultados[ticker] = analisar_ticker(ticker)

    # Resumo final
    ok = sum(1 for r in resultados.values() if "erro" not in r)
    erros = sum(1 for r in resultados.values() if "erro" in r)

    print(f"\n{'='*60}")
    print(f"PIPELINE CONCLUÍDO: {ok} OK / {erros} erros")
    print(f"{'='*60}")

    if ok > 0:
        print("\nRESUMO DE VEREDICTOS:")
        for ticker, analise in resultados.items():
            if "erro" not in analise:
                rec = analise.get("veredicto", {}).get("recomendacao", "N/A")
                print(f"  {COR.get(rec,'❓')} {ticker}: {rec}")

        print(f"\nPara ver o painel completo: python pipeline.py --resumo")

    # Log
    log_path = os.path.join(
        os.path.dirname(PASTA_ANALISES),
        "logs",
        f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        meta = {
            "timestamp": datetime.now().isoformat(),
            "fundos": list(carteira.keys()),
            "ok": ok,
            "erros": erros,
        }
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
