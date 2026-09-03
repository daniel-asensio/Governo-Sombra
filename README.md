# Governo Sombra

Observatório da administração pública portuguesa com um governo sombra.

A ideia: num dia normal passam-se dezenas de coisas na Assembleia da República, no Conselho de Ministros, no Diário da República, nas direções-gerais, institutos e reguladores que nunca chegam às notícias. Esta aplicação recolhe tudo isso das fontes oficiais, organiza-o por ministério e secretaria de Estado, diz-te o que te afecta directamente e dá-te um gabinete paralelo para comentar o que o Governo faz e propor alternativas.

## O que faz

- **Catálogo do Estado** (`data/estado.yaml`): órgãos de soberania, Governo, 17 ministérios, secretarias de Estado e mais de 150 organismos (direções-gerais, institutos, reguladores, empresas públicas, forças de segurança, tribunais). Cada entidade tem página própria com a sua actividade e a árvore de dependências.
- **Recolha automática** de fontes oficiais (RSS, páginas HTML com selectores configuráveis, Diário da República, dados abertos da Assembleia). Cada item fica ligado à entidade e ao ministério responsável. Recolha manual, por linha de comandos, ou periódica com agendador.
- **Classificação automática**: tipo de documento (legislação, despacho, Conselho de Ministros, iniciativa legislativa, consulta pública, concurso, nomeação, estatística, alerta, acórdão…), perfis afectados, região, ministério por tema e uma pontuação de relevância. Pesquisa de texto integral em tudo.
- **"Afecta-me"**: escolhes perfis (contribuinte, inquilino, trabalhador independente, utente do SNS, pais, jovem, imigrante, agricultor, funcionário público…), regiões, entidades a seguir e palavras-chave. A página inicial, o RSS pessoal e o resumo diário mostram primeiro o que te toca.
- **Alertas**: listas de vigilância por palavras, entidades e tipos; os itens correspondentes ficam marcados com 🔔.
- **Calendário do cidadão**: IRS, IMI, IUC, declarações trimestrais, candidaturas ao ensino superior, PAC, actualização de pensões e rendas, Conselho de Ministros semanal, plenários.
- **Governo sombra**: um ministro sombra por ministério, com programa de prioridades. Sobre qualquer item (ou tema) publicas posições: apoio, crítica, alternativa, pergunta ao Governo, proposta própria, com avaliação de -2 a +2. Balanço agregado do gabinete.
- **Resumo diário** em Markdown (`var/digests/`), com envio por email opcional.
- **Resumos com IA** (opcional, Claude): explicação em linguagem corrente, "porque importa" e perfis afectados.
- **API JSON** (`/api/itens`, `/api/para-ti`, `/api/entidades`, `/api/fontes`, `/api/posicoes`) e **RSS pessoal** (`/rss.xml`).

## Começar

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m governo_sombra init      # cria a base de dados (SQLite em var/)
python -m governo_sombra seed      # carrega entidades, fontes, calendário e governo sombra
python -m governo_sombra ingest    # recolhe todas as fontes activas
python -m governo_sombra serve     # http://127.0.0.1:8000
```

Sem rede, ou para experimentar já:

```bash
python -m governo_sombra ingest --fixtures tests/fixtures
```

Outros comandos:

```bash
python -m governo_sombra ingest --fonte sns-noticias   # só uma fonte
python -m governo_sombra descobrir --aplicar           # detecta feeds RSS nos sites das entidades e adiciona-os
python -m governo_sombra reclassificar                 # reaplica regras e alertas ao histórico
python -m governo_sombra digest --email                # resumo diário (email se GS_SMTP_* estiver definido)
python -m governo_sombra resumir --limite 20           # resumos com IA (requer ANTHROPIC_API_KEY)
python -m governo_sombra estado                        # imprime a árvore do Estado
```

Recolha periódica: define `GS_SCHEDULER=1` (e opcionalmente `GS_INGEST_INTERVAL_MIN`) antes de `serve`. O agendador recolhe a cada hora e gera o resumo diário às 07:30. Em alternativa usa `cron` com `python -m governo_sombra ingest`.

Configuração em `.env` (ver `.env.example`).

## Pôr online (PC, tablet e telemóvel)

A aplicação é um site: corre num servidor e abre-se em qualquer aparelho no browser. No telemóvel e tablet, "Adicionar ao ecrã principal" instala-a como aplicação. Define sempre `GS_PASSWORD` quando estiver na internet.

**Fly.io** (cerca de 2 a 5 EUR por mês, servidores em Madrid):

```bash
fly launch --copy-config --no-deploy   # cria a app a partir de fly.toml
fly volumes create dados --size 1 --region mad
fly secrets set GS_PASSWORD='uma-senha-forte'
fly deploy
fly open
```

**Railway**: cria um projecto a partir do repositório GitHub, adiciona um volume montado em `/data`, define a variável `GS_PASSWORD` e faz deploy. O `railway.json` já indica o Dockerfile.

**Servidor próprio, VPS ou Raspberry Pi** (com Docker):

```bash
GS_PASSWORD='uma-senha-forte' docker compose up -d
```

Em qualquer dos casos a recolha corre sozinha todas as horas (`GS_SCHEDULER=1` no Dockerfile) e o resumo diário é gerado às 07:30. Os dados ficam no volume `/data`.

## Sobre as fontes

Os URLs em `data/fontes.yaml` foram escritos a partir do conhecimento dos sites oficiais mas **não foram todos verificados a partir deste projecto** (o ambiente onde foi construído não tinha acesso à rede). Cada fonte mostra na página **Fontes** se já recolheu com sucesso ("verificada") ou o erro que deu. Para corrigir:

1. Abre a página `/fontes`, vê o erro, e altera o URL ali ou em `data/fontes.yaml`.
2. Para sites sem RSS conhecido, corre `python -m governo_sombra descobrir --entidade <id>`.
3. Para páginas HTML, ajusta `config.selectores` (item, titulo, link, data, resumo) na fonte.

Fontes que exigem passos adicionais:

- **Assembleia da República**: os dados abertos (iniciativas, agenda, votações) estão em ficheiros JSON/XML por legislatura em https://www.parlamento.pt/Cidadania/Paginas/DadosAbertos.aspx. Copia o URL do ficheiro "Iniciativas" da legislatura corrente para a fonte `ar-iniciativas`.
- **Diário da República**: o adaptador raspa o sumário do dia; se tiveres credenciais dos web services do DRE, define `config.api_url`.
- **dados.gov.pt** e **BASE** (contratos públicos) têm APIs próprias que se podem ligar como fontes `json`.

## Estrutura

```
data/                 dados de partida (YAML, editáveis)
  estado.yaml         árvore do Estado (titulares do XXV Governo; confirmar em portugal.gov.pt)
  fontes.yaml         fontes por entidade
  impacto.yaml        perfis "afecta-me", regiões e palavras-chave por ministério
  calendario.yaml     prazos do cidadão e ritmos institucionais
  governo_sombra.yaml elenco e programa do governo sombra
governo_sombra/
  ingest/             adaptadores (rss, html, dre, parlamento), runner, descoberta de feeds
  classify/           regras de classificação e resumos com IA
  web/                FastAPI + Jinja2 (páginas, API, RSS)
  digest.py           resumo diário
  scheduler.py        recolha periódica
  __main__.py         linha de comandos
tests/                testes com fixtures locais (sem rede)
```

Corre os testes com `python -m pytest`.

## Ideias para continuar

- Acompanhar cada iniciativa legislativa ao longo das fases (entrada, comissão, votação, promulgação) e avisar quando muda.
- Votações nominais por deputado e partido.
- Contratos públicos por entidade, com alertas de valores anómalos.
- Municípios e juntas de freguesia da tua zona.
- Comparar promessas do programa do Governo com o que foi feito.
- Publicar as posições do governo sombra como página pública ou newsletter.
