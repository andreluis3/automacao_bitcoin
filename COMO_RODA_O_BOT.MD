# ₿ Automação Bitcoin — Bot de trade BTC/BRL com painel web

Bot de trade para BTC/BRL que roda em **simulação** (dinheiro fictício) ou **real** (Binance), com um painel web em Django para controlar e acompanhar tudo em tempo real.

> ⚠️ **Aviso:** o bot opera dinheiro de verdade no modo REAL. Use apenas valores que você aceita perder. O resultado atual em simulação é **negativo** (veja a seção [Por que o lucro está ruim](#7-por-que-o-lucro-está-ruim)).

---

## 1. Como o código está rodando

O projeto tem duas camadas que conversam entre si:

```
Navegador (index.html + Plotly)
      │  a cada 1 s: GET /api/state/        │  cliques: POST /api/action/
      ▼                                     ▼
Django (dashboard/views.py)  ── ponte fina, sem lógica de trading
      │
      ▼
BotController (v_1.0/interface/bot_controller.py)  ← cérebro de orquestração
      │
      ├── BTCPriceFeed (core/valorbtc.py)           → preço ao vivo (websocket ou REST)
      └── TradingEngine (core/trading_engine.py)    → decide e executa
              ├── StrategyEngine (core/strategy_engine.py) → EMAs, regime, sinal
              └── RiskManager    (core/risk_manager.py)    → stop, take, trailing, tamanho
```

O Django **não decide nada de trading**. Ele só cria um `BotController` (uma vez por processo) e expõe os métodos dele como API JSON. É o mesmo controller que a interface antiga em Tkinter usava.

---

## 2. Como rodar (`manage.py`)

### Estrutura de pastas esperada

```
automacao_bitcoin/
├── manage.py
├── requirements.txt
├── .env                      ← BINANCE_API_KEY e BINANCE_API_SECRET (opcional)
├── config/
│   ├── __init__.py
│   ├── settings.py
│   └── urls.py               ← só diz "tudo vai para o dashboard"
├── dashboard/
│   ├── __init__.py
│   ├── urls.py               ← rotas: /, api/state/, api/action/, api/download-logs/
│   ├── views.py              ← ponte Django ↔ BotController
│   └── templates/
│       └── dashboard/
│           └── index.html    ← a página (HTML + CSS + JS)
└── v_1.0/                    ← o bot (core/, interface/, database/, api/ ...)
```

> O `index.html` **precisa** estar em `dashboard/templates/dashboard/`. Se estiver direto em `dashboard/`, aparece o erro `TemplateDoesNotExist`.

### Passo a passo

```bash
# 1. entre na raiz do projeto (onde está o manage.py)
cd automacao_bitcoin

# 2. crie e ative o ambiente virtual (só na primeira vez criar)
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# 3. instale as dependências
pip install -r requirements.txt

# 4. rode o servidor
python manage.py runserver --noreload
```

Abra **http://127.0.0.1:8000/** no navegador.

### Por que `--noreload`?

O `runserver` normal cria **dois processos** (um que observa arquivos e outro que atende). Com o bot isso duplicaria o feed de preço e o `BotController`. `--noreload` roda um processo só. Se você editar o código, pare (Ctrl+C) e rode de novo.

### Chaves da Binance (opcional)

Coloque no `.env` da raiz (ou de `v_1.0/`):

```
BINANCE_API_KEY=sua_chave
BINANCE_API_SECRET=seu_segredo
```

O `settings.py` lê esse arquivo sozinho. **Sem chaves, só a simulação funciona** (o modo REAL é bloqueado).

### Problemas comuns

| Erro | Causa | Solução |
|---|---|---|
| `TemplateDoesNotExist: dashboard/index.html` | `index.html` na pasta errada | Mover para `dashboard/templates/dashboard/` |
| `ModuleNotFoundError: core` / `interface` | Pasta `v_1.0` não está ao lado do `manage.py` | Ajustar `BOT_ROOT` em `config/settings.py` |
| Bolinha vermelha no topo | Servidor sem acesso à Binance **ou** navegador sem conexão com o Django | Ver o terminal do servidor |
| Preço não aparece | Sem internet / API bloqueada | O feed cai para simulação apenas se estiver no modo SIMULAÇÃO |

### Segurança

O painel controla o modo REAL e **não tem login**. O `ALLOWED_HOSTS` está limitado a `127.0.0.1`/`localhost`. **Não exponha na rede** sem antes adicionar autenticação.

---

## 3. Quem faz o quê (arquivo por arquivo)

| Arquivo | Responsabilidade |
|---|---|
| `interface/bot_controller.py` | **Orquestrador.** Inicia/para o bot, cria o engine conforme o modo e o perfil, recebe cada tick do feed e o entrega ao engine, registra trades no banco, gera o *snapshot* que a tela consome e exporta o ZIP de logs. **Não calcula indicador nem decide compra/venda.** |
| `core/valorbtc.py` | `BTCPriceFeed`: obtém o preço BTC/BRL (websocket da Binance, com fallback REST; em simulação pode usar preço simulado) e chama o controller a cada tick. |
| `core/strategy_engine.py` | **Cérebro da estratégia.** Calcula EMA 9/21/38, ATR, Bandas de Bollinger, classifica o regime (tendência/lateral) e devolve o sinal `buy`, `sell` ou `none` com o motivo. |
| `core/trading_engine.py` | **Executor.** A cada preço: atualiza a estratégia, checa pausas (drawdown, 5 perdas), pede o sinal, aplica filtro anti-overtrading, calcula o tamanho da posição, abre/fecha e mantém as métricas (win rate, profit factor, Sharpe, equity). Contém os adaptadores de execução: `SimulationExecutionAdapter` (saldo fictício) e `BinanceExecutionAdapter` (ordens reais). |
| `core/risk_manager.py` | Stop loss, take profit, **trailing stop**, tamanho de posição e `scale_position` (aumentar posição). |
| `interface/config_store.py` | Lê/salva `v_1.0/config/config.json` (fonte única de configuração). |
| `database/` | SQLite: trades, sessões, taxas, performance diária e `trade_logs`. |
| `api/market_data.py` | Consulta preços (BTCUSDT, BTCBRL, USDTBRL) para o cabeçalho da tela. |
| `core/bot_logger.py`, `core/logger.py` | Logs em arquivo (decisões, ordens, resultados, erros, estado) dentro de `v_1.0/logs/`. |
| `dashboard/views.py` | Cria o `BotController` e expõe `/api/state/` (estado), `/api/action/` (iniciar, parar, modo…) e `/api/download-logs/`. |
| `dashboard/templates/dashboard/index.html` | Interface: 3 telas (Trading, Performance, Registro Mensal), gráficos Plotly e console de logs. |

> `interface/main_window.py`, `trading_tab.py` etc. são da interface **antiga em Tkinter** e não são usados pelo painel web.

---

## 4. Como o bot funciona (visão de um tick)

O preço chega **cerca de 1 vez por segundo**. Para cada tick, o `TradingEngine.on_price()` faz, em ordem:

1. Atualiza a estratégia com o novo preço (recalcula EMAs, ATR, Bollinger).
2. **Pausas:** se estiver pausado por 5 perdas seguidas (30 min) ou por drawdown, para aqui.
3. Pede ao `StrategyEngine` o sinal (`buy` / `sell` / `none`).
4. **Com posição aberta:** atualiza trailing, checa stop/take, checa sinal de venda, avalia aumentar a posição.
5. **Sem posição:** se o sinal não for `buy`, registra em "Quase-Trades" o motivo do bloqueio; se for `buy`, passa pelo filtro anti-overtrading, calcula o tamanho e compra.

> ⚠️ **Detalhe importante:** as médias móveis são calculadas **por tick, não por candle**. Uma EMA 9 é, na prática, a média ponderada dos últimos ~9 segundos; a EMA 21, dos últimos ~21 segundos; a EMA 38, de ~38 segundos. Isso é um horizonte extremamente curto e é a chave para entender o resultado atual.

---

## 5. A estratégia de médias móveis

### Indicadores

- **EMA 9** (rápida), **EMA 21** (média), **EMA 38** (lenta / filtro macro)
- **Slope da EMA 9**: variação da EMA 9 nos últimos 8 ticks (positivo = subindo)
- **ATR(14)**: volatilidade; usado como "portão" (as EMAs precisam estar separadas por pelo menos 20% do ATR)
- **Bollinger (20, 2σ)**: usado para detectar compressão (squeeze)
- Aquecimento: o bot só opera depois de **38 ticks** acumulados (mensagem `aquecendo 32/38`).

### Regime de mercado (camada 1)

No modo **AUTO** o bot classifica o mercado a cada tick:

| Regime | Condição |
|---|---|
| `lateral` | EMA 9 e EMA 21 quase coladas (< 0,01%) **ou** EMA 38 quase parada |
| `tendencia_forte` | EMA 9 > EMA 21 > EMA 38 (ou o inverso) |
| `tendencia_fraca` | Só 2 de 3 alinhadas |

Nos modos **TENDÊNCIA** e **LATERAL** da tela, o regime é forçado em vez de detectado.

### Como o bot COMPRA

Só compra com **posição fechada** e, em regime de tendência, se **todos** os filtros passarem:

1. **Distância:** `|EMA9 − EMA21| / EMA21 ≥ 0,02%`
2. **Slope** da EMA 9 **positivo**
3. **ATR gate:** `|EMA9 − EMA21| ≥ 20% do ATR`
4. **Volume** atual ≥ 70% da média dos últimos 20 ticks
5. **EMA 9 > EMA 21** (cascata mínima)

Passando os filtros, o motivo da entrada é um destes (do mais ao menos prioritário):

| Motivo | Quando |
|---|---|
| `breakout_squeeze_entrada` | Bollinger comprimido (< 0,5% do preço) + aceleração do slope |
| `pullback_tendencia_entrada` | Preço recuou até 0,1% da EMA 9 com tendência de alta |
| `tendencia_cascata_completa_agressiva` | EMA 9 > 21 > 38 no modo agressivo (**sem esperar cruzamento**) |
| `cascata_2_3_agressiva` | Só EMA 9 > EMA 21, modo agressivo |

Depois, o `TradingEngine` ainda aplica o **filtro anti-overtrading**: mínimo de **60 s** entre trades (Agressivo) e máximo de **15 entradas por hora**. Se bloquear, aparece `filtro_overtrading`.

**Tamanho da posição:** `capital × alocação inicial` (Agressivo: 40%; Conservador: 20%), multiplicado pela força do sinal:

| Força do sinal | Multiplicador |
|---|---|
| ≥ 0,8 | 1,5× |
| ≥ 0,6 | 1,2× |
| ≥ 0,4 | 1,0× |
| < 0,4 | 0,7× |
| Breakout | 0,6× (posição reduzida) |

Nunca usa mais de 95% do saldo livre. Exemplo com R$ 300 no Agressivo e sinal fraco: 300 × 40% × 0,7 = **R$ 84**.

### Como o bot VENDE

Com posição aberta, a saída acontece pelo **primeiro** destes que ocorrer, nesta ordem de checagem:

1. **Stop loss (SL):** preço cai `1,5%` (Agressivo) / `1,0%` (Conservador) abaixo da entrada
2. **Take profit (TP):** preço sobe `4,0%` (Agressivo) / `2,5%` (Conservador) acima da entrada
3. **Trailing stop:** depois que o lucro passa de `0,5%` (Agressivo), o stop passa a seguir a máxima, `0,5%` abaixo dela
4. **Sinal de saída da estratégia (`SIGNAL_EXIT`)**, qualquer um de:
   - EMA 9 cruza **para baixo** da EMA 21 (`crossover_baixa_ema9_ema21`)
   - Cascata de baixa completa (EMA 9 < 21 < 38)
   - Slope negativo **e** EMA 9 abaixo da EMA 21

O bot também pode **aumentar a posição** (scale-in) em `tendencia_forte` quando EMA 9 > 21 e slope positivo, respeitando o máximo de 65% do capital.

### Proteções

- **5 perdas seguidas** → pausa de 30 minutos
- **Drawdown** ≥ limite (padrão 12%) → bot para de operar
- **Perdas ≥ 3 seguidas** → reduz o risco por trade (modo defensivo)
- **Acumulação** (opcional): 30% de cada lucro vai para uma reserva segura que não é arriscada

---

## 6. O que cada botão do painel faz

| Controle | Método do `BotController` |
|---|---|
| INICIAR | `start_bot()` — cria o engine, inicia o feed, abre uma sessão no banco |
| PARAR | `stop_bot()` — encerra a sessão e para o feed |
| SIMULAÇÃO / REAL | `set_mode()` (bloqueado enquanto o bot roda; REAL pede confirmação) |
| TENDÊNCIA / LATERAL / AUTO | `set_trading_mode()` |
| Perfil | `apply_profile()` (Agressivo / Conservador) |
| Acumulação | `set_accumulation_mode()` |
| Download Logs | `download_logs_report()` — ZIP com todos os logs + relatório da sessão + CSV de trades |

O console de logs da tela mostra tudo que o controller passa pelo `log_callback` (feed, entradas, stop/take, início/parada), e o painel busca o estado novo a cada 1 segundo.

---

## 7. Por que o lucro está ruim

Você percebeu que o bot parece "seguro demais". Olhando o código e as telas, há **duas causas diferentes**, e só uma delas é segurança:

### (a) O bot realmente opera pouco — filtros em excesso

Na tela de Performance havia **48 sinais filtrados e 0 executados** (`Cross: 0 | Filtrados: 48 | Executados: 0`). Os bloqueios mais comuns nos logs: `slope_negativo`, `dist_insuficiente`, `bollinger_banda_zero`, `filtro_overtrading` e `aquecendo`. São muitos filtros em cima de um sinal que já é curto.

Além disso, o tamanho da posição é modesto (28% a 60% do capital por entrada) e há trava de 60 s entre trades.

### (b) Quando entra, perde — e isso **não** é por excesso de segurança

Esta é a causa principal. Nos seus registros, trades com **entrada e saída no mesmo preço** (ex.: `434238.00 → 434238.00`) deram `lucro −0.1679`. Isso é exatamente a taxa da Binance: R$ 84 × 0,1% na compra + 0,1% na venda = R$ 0,168.

Ou seja: **cada trade precisa render mais de ~0,2% só para empatar.** O problema é que:

1. **EMAs de 9 e 21 *ticks* (~9 e ~21 segundos)** reagem a ruído, não a tendência. BTC se move frações de 0,01% em segundos, bem abaixo do 0,2% de custo.
2. **O TP de 4% e o SL de 1,5% quase nunca são atingidos.** Em segundos o preço não anda isso. Na prática, quem decide a saída é o `SIGNAL_EXIT` (cruzamento das EMAs), e ele dispara quase sempre com o preço perto da entrada, então o trade fecha com **prejuízo = taxas**.
3. **Entrada e saída usam o mesmo critério curto** (cruzamento das mesmas médias). O bot entra quando a EMA 9 passa da 21 e sai quando volta, em questão de segundos.
4. **A simulação é otimista:** executa no preço exato do tick, sem spread nem slippage. Em REAL o resultado seria ainda pior.

> Por isso, **afrouxar os filtros sozinho provavelmente piora o resultado**: mais trades pequenos = mais taxas pagas. O gargalo é a relação entre o horizonte do sinal (segundos) e o custo por trade (~0,2%).

### Caminhos para melhorar (a validar com backtest antes de usar dinheiro real)

1. **Usar candles de 1 min ou 5 min** (ou EMAs com períodos bem maiores) em vez de ticks, para o sinal refletir movimento real.
2. **Exigir ganho mínimo antes de aceitar saída por sinal**, por exemplo só sair por `SIGNAL_EXIT` se o lucro bruto cobrir as taxas (> ~0,25%); caso contrário, deixar o SL/trailing decidirem.
3. **Aproximar o TP/SL da volatilidade real** (ex.: múltiplos do ATR) em vez de 4% / 1,5% fixos.
4. **Reduzir a frequência** (aumentar o tempo mínimo entre trades) em vez de afrouxar filtros.
5. **Registrar spread/slippage na simulação** para o resultado simulado ser realista.
6. **Fazer backtest** com histórico de candles da Binance antes de qualquer ajuste ir para o modo REAL.

Nada disso garante lucro, e estratégias de curtíssimo prazo costumam ser difíceis de manter lucrativas depois das taxas.

---

## 8. Endpoints da API (usados pelo painel)

| Método | URL | Função |
|---|---|---|
| GET | `/` | Página do painel |
| GET | `/api/state/?since=N&full=1` | Estado completo (preço, equity, métricas, logs novos). `full=1` inclui históricos e registro diário |
| POST | `/api/action/` | `{"action": "start" \| "stop" \| "mode" \| "trading_mode" \| "profile" \| "accumulate", "value": ...}` |
| GET | `/api/download-logs/` | ZIP com todos os logs |

Os POSTs usam proteção CSRF do Django (o token vem do cookie `csrftoken`).

---

## 9. Configuração (`v_1.0/config/config.json`)

| Chave | Significado |
|---|---|
| `capital_total` / `saldo_inicial` | Capital inicial (R$) |
| `modo` | `simulacao` ou `real` |
| `trading_mode` | `auto`, `tendencia` ou `lateral` |
| `perfil` | `Agressivo` ou `Conservador` |
| `binance_fee` | Taxa por operação (0,001 = 0,1%) |
| `drawdown` | Limite de drawdown que pausa o bot (%) |
| `acumular_saldo` | Reserva 30% dos lucros |

> Os valores de `stop` e `take` do arquivo são **sobrescritos pelo perfil** escolhido (`set_risk_profile` roda depois de criar o engine). Para mudar stop/take de verdade, ajuste os presets em `core/trading_engine.py`.

---

## 10. Licença / aviso

Projeto de estudo. Não é recomendação financeira. Trading de criptomoedas envolve risco alto de perda.