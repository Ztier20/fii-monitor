# FII Monitor — Especificação Técnica

## Objetivo

Sistema local (notebook), automatizado, que monitora todos os FIIs listados na B3, baixa relatórios gerenciais mensais, extrai indicadores estruturados, gera análise qualitativa via IA e apresenta tudo em um dashboard web local.

---

## 1. Indicadores e pontos de análise por FII

### Financeiros
- Dividend yield (mensal e anualizado)
- P/VP (preço sobre valor patrimonial)
- Vacância física e financeira (FIIs de tijolo)
- Inadimplência
- Patrimônio líquido e variação mês a mês
- Resultado do período vs. valor distribuído (alerta se distribuição > resultado operacional)

### Carteira / Portfólio
- Concentração por ativo, inquilino ou setor
- FIIs de papel: tipo de CRI, indexador (CDI/IPCA), rating dos devedores
- FIIs de tijolo: localização, idade dos imóveis, tipo de contrato (típico/atípico)

### Eventos relevantes
- Aquisições/vendas de ativos
- Renegociações de contrato
- Emissões de cotas (captações) e diluição
- Mudanças na gestão

### Sinais de alerta (gerados automaticamente)
- Queda de receita recorrente (comparação histórica)
- Aumento de vacância (tendência)
- Distribuição "artificial" via reserva
- Alavancagem crescente

---

## 1.1 Classificação do FII (etapa prévia à análise)

Antes de aplicar o conjunto de indicadores, o sistema classifica cada FII por categoria. A classificação determina qual prompt/conjunto de campos o agente usa.

### Categorias
- **Tijolo** (lajes corporativas, logística, shoppings, galpões): foco em vacância física/financeira, localização, idade dos imóveis, tipo de contrato (típico/atípico), inquilinos
- **Papel** (CRI, recebíveis): foco em indexador (CDI/IPCA), rating dos devedores, inadimplência da carteira, duration
- **Híbrido**: combina os dois conjuntos acima, com peso proporcional à composição da carteira
- **Fundo de Fundos (FoF)**: foco na carteira de cotas de outros FIIs, diversificação por gestor/segmento, yield consolidado
- **Outros** (agro, desenvolvimento, etc.): conjunto mínimo comum + campos específicos quando identificáveis

### Fonte da classificação
- Primária: segmento informado pela B3/CVM (dado estruturado, não inferido pela IA)
- Fallback: se ausente/ambíguo, o agente identifica pelo conteúdo do relatório (ex: presença de "CRI" e "indexador" → papel)

### Impacto no pipeline
- O passo "Agente IA" (seção 5) recebe, junto com o texto do relatório, o **conjunto de indicadores e o prompt específico da categoria**
- O JSON de saída (seção 5) inclui o campo `"categoria": "tijolo|papel|hibrido|fof|outros"`
- Validação (seção 7) usa ranges diferentes por categoria (ex: vacância só é validada para tijolo/híbrido)

---

## 2. Arquitetura geral

```
┌─────────────────┐     ┌──────────────┐     ┌───────────────────┐
│  Scraper/Coletor │ --> │  Downloader  │ --> │  Extrator de texto │
│  (Fundos.NET/CVM)│     │  (PDFs)      │     │  (PyMuPDF/pdfplumber)│
└─────────────────┘     └──────────────┘     └───────────────────┘
                                                        │
                                                        v
                                              ┌───────────────────┐
                                              │   Agente de IA     │
                                              │  (Claude Agent SDK)│
                                              └───────────────────┘
                                                        │
                          ┌─────────────────────────────┼─────────────────────────┐
                          v                              v                         v
                 ┌────────────────┐           ┌──────────────────┐      ┌──────────────────┐
                 │  Code Execution │           │   Memory tool      │      │  Validação/regras │
                 │  (cálculo DY,   │           │  (histórico FII    │      │  (ranges, alertas │
                 │   P/VP etc.)    │           │   entre execuções) │      │   automáticos)    │
                 └────────────────┘           └──────────────────┘      └──────────────────┘
                          │                              │                         │
                          └──────────────────────────────┼─────────────────────────┘
                                                          v
                                                 ┌──────────────────┐
                                                 │   SQLite (banco)  │
                                                 └──────────────────┘
                                                          │
                                                          v
                                                 ┌──────────────────┐
                                                 │  Dashboard React  │
                                                 │  (localhost)      │
                                                 └──────────────────┘
```

---

## 3. Stack técnica

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Backend / orquestração | Python 3.11+ | Scraping, agendamento, integração com Agent SDK |
| Agente IA | Claude Agent SDK | Roda local, ferramentas embutidas, controle total |
| Extração de PDF | PyMuPDF / pdfplumber | Extração de texto e tabelas |
| Cálculo de indicadores | Code execution tool (via Agent SDK) | Evita alucinação numérica — IA não calcula "de cabeça" |
| Memória entre execuções | Memory tool (Agent SDK) | Histórico do FII sem reenviar tudo no prompt |
| Banco de dados | SQLite | Simples, robusto, sem servidor extra |
| Agendamento | APScheduler (cron-like, em processo Python) | Roda localmente, sem infraestrutura cloud |
| Frontend | React + Vite | Dashboard local em `localhost` |
| Fonte de dados estruturados | Portal de Dados Abertos CVM / Fundos.NET | Cotação, PL, dados oficiais para validação cruzada |

---

## 4. Divisão de responsabilidades (IA vs. código determinístico)

Esta é a parte mais importante para reduzir erros:

| Tarefa | Quem faz | Por quê |
|---|---|---|
| Extrair valores numéricos (DY, P/VP, PL, vacância) | Regex/parsing estruturado do PDF + Code Execution tool | Números vêm de extração/cálculo determinístico, não de "leitura" da IA |
| Calcular fórmulas (DY anualizado, variação %) | Code Execution tool | Elimina erro de conta |
| Localizar texto livre (eventos, resumo qualitativo) | Agente IA (Claude) | Tarefa de linguagem natural, onde IA é forte |
| Comparar com mês anterior / detectar tendência | Memory tool + Code Execution | Histórico estruturado, não "lembrança" da IA |
| Validar se valores estão em ranges plausíveis | Código (regras fixas) | Ex: vacância entre 0-100%, P/VP > 0 |
| Decidir se algo é "alerta" | Regras de negócio fixas no código + IA sinaliza contexto | Threshold definido por você, não pela IA |

---

## 5. Fluxo de execução (pipeline mensal)

1. **Scraper** roda (agendado via APScheduler) → consulta lista de FIIs ativos na B3/CVM
2. Para cada FII: verifica se há relatório gerencial novo desde a última execução
3. **Downloader** baixa o PDF → salva em `/dados/{ticker}/{ano-mes}.pdf`
4. **Extrator** extrai texto e tabelas do PDF
5. **Agente IA** (Claude Agent SDK) recebe:
   - Texto extraído do relatório
   - Histórico do FII (via Memory tool)
   - Lista de indicadores e fórmulas (prompt fixo + glossário de referência)
   - Acesso ao Code Execution tool para calcular indicadores
6. Agente retorna JSON estruturado:
   ```json
   {
     "ticker": "XPLG11",
     "data_relatorio": "2026-05",
     "indicadores": {
       "dividend_yield_mensal": 0.0085,
       "p_vp": 0.94,
       "vacancia_fisica": 0.12,
       "vacancia_financeira": 0.10,
       "inadimplencia": 0.02,
       "pl": 1500000000
     },
     "eventos": ["Aquisição de novo galpão em Cajamar"],
     "alertas": ["Vacância subiu de 8% para 12% em 2 meses"],
     "resumo": "..."
   }
   ```
7. **Validação automática**: ranges plausíveis, comparação com Fundos.NET (validação cruzada)
8. Se algo está fora do esperado → marca `status: revisão` em vez de salvar como `ok`
9. Salva no **SQLite** (histórico por FII/mês)
10. **Dashboard** lê do SQLite e exibe

---

## 6. Mecanismos da Anthropic utilizados

- **Claude Agent SDK**: framework que roda localmente, com ferramentas embutidas (leitura de arquivos, execução de comandos), ideal para rodar no notebook sob agendamento
- **Tool Use (Messages API)**: define as ferramentas customizadas do projeto (scraper, banco, validação)
- **Code Execution tool**: cálculo determinístico de indicadores financeiros — sem alucinação numérica
- **Memory tool**: persistência de histórico do FII entre execuções, sem precisar reenviar tudo no prompt
- **Web Search tool** (opcional): conferir cotação/notícia recente no momento da análise

---

## 7. Robustez e tratamento de erros

- Logs detalhados por etapa (scraping, download, extração, IA, validação)
- Retry automático em falhas de rede (scraper/downloader)
- Campos não identificados → `null`, nunca inventados
- Validação cruzada: indicadores extraídos vs. dados estruturados do Fundos.NET
- Status por execução: `ok` / `revisão` / `erro`
- Fila de revisão manual no dashboard para itens marcados como `revisão`

---

## 8. Estrutura de pastas sugerida

```
fii-monitor/
├── backend/
│   ├── scraper/          # coleta lista de FIIs e relatórios novos
│   ├── downloader/        # download de PDFs
│   ├── extractor/          # extração de texto/tabelas
│   ├── agent/              # integração Claude Agent SDK
│   ├── validation/         # regras de validação e ranges
│   ├── scheduler.py        # APScheduler
│   └── db/                 # SQLite + models
├── frontend/
│   └── (React + Vite)
├── dados/
│   └── {ticker}/{ano-mes}.pdf
└── docs/
    └── glossario-referencia.md   # contexto financeiro para o prompt
```

---

## 9. Próximos passos sugeridos para implementação

1. Setup do projeto (estrutura de pastas, ambiente Python + Node)
2. Scraper inicial (lista de FIIs + identificação de relatórios novos via Fundos.NET)
3. Pipeline de download + extração de texto (testar com 2-3 FIIs primeiro)
4. Agente IA com prompt fixo + glossário de referência + few-shot examples
5. Validação cruzada e regras de alerta
6. Banco SQLite e schema
7. Dashboard React (listagem, filtros, histórico por indicador)
8. Agendamento (APScheduler) e logs
