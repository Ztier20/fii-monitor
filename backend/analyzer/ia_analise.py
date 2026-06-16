"""
Analisador de FIIs via Claude API.
Recebe texto extraído de relatório gerencial + dados CVM e retorna
análise estruturada em JSON — seguindo o framework do relatório DEVA11.
"""

import os
import json
import re
from anthropic import Anthropic

def _carregar_api_key() -> str:
    """Carrega ANTHROPIC_API_KEY do ambiente ou .env."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for linha in f:
                    if linha.startswith("ANTHROPIC_API_KEY="):
                        key = linha.strip().split("=", 1)[1]
                        break
    return key


PROMPT_SISTEMA = """Você é um analista sênior de fundos imobiliários (FIIs) e FIAGROs do mercado brasileiro.
Sua especialidade é análise fundamentalista profunda — vai além dos indicadores superficiais que qualquer site entrega.
Você lê relatórios gerenciais e identifica:
- Riscos ocultos que o investidor médio não percebe
- Qualidade real da carteira (não só os números publicados)
- Sustentabilidade dos dividendos (o fundo está consumindo reserva? pagando com receita real?)
- Perspectivas concretas baseadas no pipeline e nos vencimentos
- Veredicto claro: compra / manutenção / redução / venda — com tese objetiva

Contexto macroeconômico atual (junho/2026):
- CDI: ~14,75% a.a.
- IPCA 12 meses: ~4,14%
- Selic: ~14,75%
- Juros altos pressionam devedores de CRI/CRA e eleva custo de oportunidade

Responda SEMPRE em JSON válido, sem texto fora do JSON."""

PROMPT_ANALISE = """Analise o relatório gerencial abaixo do fundo {ticker} ({nome}, categoria: {categoria}).

DADOS CVM MAIS RECENTES:
{dados_cvm}

TEXTO DO RELATÓRIO GERENCIAL:
{texto_relatorio}

Retorne um JSON com EXATAMENTE esta estrutura (preencha todos os campos — use null se não encontrar):
{{
  "ticker": "{ticker}",
  "nome": "{nome}",
  "data_referencia": "YYYY-MM ou texto do relatório",
  "categoria": "{categoria}",

  "financeiro": {{
    "pl_milhoes": null,
    "cota_patrimonial": null,
    "cota_mercado": null,
    "pvp": null,
    "distribuicao_mes": null,
    "dy_mensal_pct": null,
    "dy_12m_pct": null,
    "receita_total_mes": null,
    "despesas_mes": null,
    "reserva_lucros": null,
    "reserva_tendencia": "acumulando|consumindo|estavel|desconhecido"
  }},

  "carteira": {{
    "total_ativos": null,
    "inadimplencia_pct": null,
    "carencia_juros_pct": null,
    "em_dia_pct": null,
    "indexador_principal": "IPCA|CDI|IGPM|prefixado|misto",
    "spread_medio": null,
    "duration_anos": null,
    "concentracao_top3_pct": null
  }},

  "segmentos": {{
    "descricao": "texto livre com composição setorial",
    "lista": [
      {{"nome": "segmento", "pct": 0.0}}
    ]
  }},

  "riscos": [
    {{
      "nivel": "alto|medio|baixo",
      "categoria": "credito|liquidez|mercado|gestao|regulatorio|concentracao",
      "descricao": "descrição objetiva do risco",
      "impacto": "impacto potencial no dividendo ou PL"
    }}
  ],

  "pontos_positivos": [
    "item 1",
    "item 2"
  ],

  "perspectivas": {{
    "curto_prazo_3m": "texto",
    "medio_prazo_12m": "texto",
    "catalisadores_positivos": ["item"],
    "catalisadores_negativos": ["item"]
  }},

  "dividendo": {{
    "sustentavel": true,
    "justificativa": "por que é ou não sustentável",
    "projecao_proximos_meses": "texto com projeção"
  }},

  "valuation": {{
    "pvp_justo_estimado": null,
    "upside_downside_pct": null,
    "comentario": "texto sobre valuation relativo ao setor"
  }},

  "veredicto": {{
    "recomendacao": "COMPRA|MANUTENÇÃO|REDUÇÃO|VENDA",
    "forca": "FORTE|MODERADA|FRACA",
    "tese_principal": "1-2 frases com o argumento central",
    "para_quem": "perfil de investidor adequado",
    "preco_entrada_ideal": null,
    "stop_loss": null
  }},

  "alertas_criticos": [
    "item de atenção imediata se existir"
  ],

  "resumo_executivo": "Parágrafo de 3-5 frases com síntese completa para decisão de investimento"
}}"""


def analisar_fundo(
    ticker: str,
    nome: str,
    categoria: str,
    texto_relatorio: str,
    dados_cvm: dict,
) -> dict:
    """
    Envia o relatório para o Claude e retorna análise estruturada em dict.
    """
    api_key = _carregar_api_key()
    if not api_key:
        return {"erro": "ANTHROPIC_API_KEY não configurada"}

    client = Anthropic(api_key=api_key)

    cvm_texto = json.dumps(dados_cvm, ensure_ascii=False, indent=2) if dados_cvm else "Não disponível"

    prompt = PROMPT_ANALISE.format(
        ticker=ticker,
        nome=nome,
        categoria=categoria,
        dados_cvm=cvm_texto,
        texto_relatorio=texto_relatorio[:75000],  # safety trim
    )

    print(f"  [IA] Enviando {len(prompt):,} chars para Claude...")

    try:
        resposta = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=PROMPT_SISTEMA,
            messages=[{"role": "user", "content": prompt}],
        )

        conteudo = resposta.content[0].text.strip()

        # Extrair JSON da resposta (às vezes vem com markdown code block)
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", conteudo)
        if m:
            conteudo = m.group(1)

        analise = json.loads(conteudo)
        analise["_tokens_usados"] = {
            "input": resposta.usage.input_tokens,
            "output": resposta.usage.output_tokens,
        }
        return analise

    except json.JSONDecodeError as e:
        # Salvar resposta bruta para diagnóstico
        raw_path = os.path.join(os.path.dirname(__file__), "..", "..", "dados",
                                ticker.lower(), f"{ticker}_raw_response.txt")
        try:
            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(conteudo)
            print(f"  [DEBUG] Resposta bruta salva em: {raw_path}")
        except Exception:
            pass
        print(f"  [DEBUG] Primeiros 300 chars da resposta: {repr(conteudo[:300])}")
        return {
            "ticker": ticker,
            "erro": f"JSON inválido: {e}",
            "resposta_raw": conteudo[:500],
        }
    except Exception as e:
        return {"ticker": ticker, "erro": str(e)}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from extractor.pdf_extractor import extrair_para_fundo
    from scraper.cvm import extrair_indicadores_cvm
    from carteira import CARTEIRA

    ticker = sys.argv[1] if len(sys.argv) > 1 else "KNSC11"
    info = CARTEIRA.get(ticker, {})
    pasta_dados = os.path.join(os.path.dirname(__file__), "..", "..", "dados")

    print(f"Extraindo PDF de {ticker}...")
    extracao = extrair_para_fundo(ticker, pasta_dados)
    print(f"  {extracao['n_chars']:,} chars extraídos de {extracao['caminho_pdf']}")

    print(f"Coletando dados CVM...")
    dados_cvm = extrair_indicadores_cvm(info.get("cnpj", ""), info.get("tipo", "FII"))

    print(f"Analisando com IA...")
    analise = analisar_fundo(
        ticker=ticker,
        nome=info.get("nome", ticker),
        categoria=info.get("categoria", ""),
        texto_relatorio=extracao["texto"],
        dados_cvm=dados_cvm,
    )

    saida = os.path.join(pasta_dados, ticker.lower(), f"{ticker}_analise.json")
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(analise, f, ensure_ascii=False, indent=2)

    print(f"\nAnálise salva em: {saida}")
    print(f"\nVEREDICTO: {analise.get('veredicto', {}).get('recomendacao', 'N/A')}")
    print(f"RESUMO: {analise.get('resumo_executivo', '')[:300]}")
