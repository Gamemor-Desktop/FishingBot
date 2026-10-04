# FishingBot

Versao empacotada como aplicativo Windows (`FishingBot.exe`) do bot de pesca
do FiveM: detecta a janela do jogo automaticamente, se adapta a resolucao e
escala do Windows, calibra sozinho e mostra uma interface simples com
Iniciar/Parar. Baseado na mesma logica de reconhecimento visual do projeto
`fivem_fishing_bot` (script), mas sem coordenadas fixas.

Repositorio: https://github.com/Gamemor-Desktop/FishingBot (privado)

## Como conseguir o projeto

O `FishingBot.exe` **nao** fica versionado no git (esta no `.gitignore`, ja
que e um binario gerado e pesado). Pra conseguir o codigo:

```bat
git clone https://github.com/Gamemor-Desktop/FishingBot.git
```

Depois, ou compile o `.exe` voce mesmo (secao "Como compilar" abaixo) ou
rode direto do codigo-fonte com Python. Nao ha releases publicadas com o
`.exe` pronto no momento -- se precisar distribuir o executavel pra alguem
que nao vai compilar, gere localmente com `build.bat` e envie o arquivo por
fora do git.

## Como rodar (usuario final, ja com o .exe pronto)

1. Abra o FiveM (janela ou borderless windowed -- fullscreen exclusivo pode
   impedir a captura de tela de outros programas).
2. Dê dois cliques em `FishingBot.exe`.
3. A janela mostra "Procurando FiveM..." -> "Detectando janela..." ->
   "Calibrando..." -> "Aguardando pesca...". Quando chegar em "Aguardando
   pesca...", clique em **INICIAR**.
4. Va pescar. O bot assume a partir do momento em que voce usa a vara.
5. Quando o peixe for capturado, o bot **para** e mostra "Peixe capturado!
   Pegue e corte o peixe manualmente. Pressione ENTER quando estiver pronto
   para pescar novamente." O bot apita e o botao **CONTINUAR** fica ativo.
   Essa etapa (pegar o peixe no chao e corta-lo) nao
   e automatizada -- faca-a normalmente no jogo e, quando terminar, aperte
   **ENTER** (ou clique em CONTINUAR) pra o bot lançar a vara de novo, depois
   de uma folga de ~1,5 s. O ENTER so tem efeito nesse
   momento especifico; apertado em qualquer outra hora (durante o minigame,
   por exemplo) e ignorado, de proposito, pra nao atrapalhar a automacao.
6. **F10** (tecla de emergencia) para tudo na hora, mesmo com o jogo em foco.
   **PARAR** interrompe a automacao e solta qualquer tecla que estivesse
   sendo segurada, na hora -- inclusive se estiver parado esperando o ENTER
   da etapa manual.

Nao precisa instalar Python nem nada -- o `.exe` e autocontido.

## Aviso importante

Isto e um bot de automacao/macro para um jogo online multiplayer. A maioria
dos servidores de FiveM (principalmente os de roleplay, onde pesca costuma
estar ligada a economia do servidor) proibe macro/automacao nas regras e
pode banir contas que usarem isso. Leia as regras do seu servidor antes de
usar. Rode com `FishingBot.exe --dry-run` (veja abaixo) pra testar sem
apertar nenhuma tecla de verdade.

## Como compilar o .exe (desenvolvedor)

Requer Python 3.11+ instalado no Windows (so pra gerar o .exe -- quem for
so *usar* o programa nao precisa de Python).

```bat
build.bat
```

Isso cria um ambiente virtual, instala as dependencias e gera
`FishingBot.exe` na pasta do projeto via PyInstaller. Rodar de novo reusa o
venv (mais rapido).

Pra rodar direto do codigo-fonte sem compilar (desenvolvimento/depuracao):

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py --dry-run
```

## Arquitetura

```
main.py                    ponto de entrada (DPI awareness + argumentos + GUI)
fishingbot/
  app_state.py              estado compartilhado entre a UI e o controlador (thread-safe)
  window_detect.py          localizar a janela do FiveM, DPI awareness, client area
  regions.py                regioes do minigame como FRACOES da janela (nao pixels fixos)
  config_store.py           config.json (so overrides), migracao, validacao, padroes
  stats.py                  resultado de cada lance + estatisticas da sessao
  depth_reader.py           leitura da PROFUNDIDADE e do prompt do E (modelos de digitos, sem OCR)
  capture_health.py         tela preta/congelada, regioes dentro da tela
  diagnostics.py            pacote de diagnostico quando o bot se desliga sozinho
  panic.py                  tecla de emergencia global (F10)
  single_instance.py        impede abrir duas instancias
  vision.py                 captura de tela + deteccao de cor (OpenCV + mss)
  input_sim.py              simulacao de teclado (pydirectinput)
  fishing_logic.py          as fases do minigame (fisgar, timing, puxar)
  manual_control.py         listener global da tecla ENTER (confirmacao da etapa manual)
  controller.py             a maquina de estados do aplicativo, numa thread de fundo
  gui.py                    interface Tkinter (poll no estado compartilhado)
```

A interface roda na thread principal (Tkinter exige isso). Toda a deteccao/
calibracao/automacao roda numa thread separada (`Controller`), e as duas se
comunicam por um `SharedState` protegido por lock -- a GUI nunca trava
esperando a visao computacional, e a automacao nunca trava esperando a UI
redesenhar.

### Por que fracoes em vez de coordenadas fixas

Cada regiao do minigame (ex: a linha "PEIXE" do painel de puxar) foi
calibrada uma vez, ao vivo, numa tela 1920x1080, e guardada como fracao da
largura/altura da janela do jogo (`regions.py`). Pra qualquer resolucao
diferente, a gente so multiplica de novo: `x = janela.left + fracao_x *
janela.largura`. Isso funciona porque a interface do FiveM (NUI, baseada em
CEF/HTML) escala proporcionalmente com o tamanho da janela -- os elementos
ficam ancorados nos mesmos cantos relativos independente da resolucao. Se
isso nao bater 100% num caso especifico (proporcao de tela muito incomum,
UI customizada por algum resource do servidor), os valores em
`regions.DEFAULT_FRACTIONS` podem ser ajustados manualmente.

### DPI / escala do Windows

`window_detect.setup_dpi_awareness()` roda logo no inicio do `main.py` e
marca o proprio processo como "per-monitor DPI aware". Isso faz o Windows
parar de mentir sobre o tamanho/posicao da janela (o que aconteceria se o
processo nao fosse DPI-aware e a escala do Windows fosse diferente de
100%), entao `GetClientRect`/`ClientToScreen` retornam pixels FISICOS reais
-- o mesmo espaco de coordenadas que o `mss` usa pra capturar a tela e que
o `pydirectinput` usa pra simular teclado. Na pratica isso elimina a
necessidade de fazer contas de escala manualmente: 100%, 125%, 150% etc.
todos caem nas mesmas coordenadas fisicas.

### Deteccao da janela

`window_detect.find_fivem_window()` enumera as janelas visiveis do sistema
e procura pelo PROCESSO cujo executavel contenha "gtaprocess" (o processo
real do jogo dentro do FiveM, ex: `FiveM_b3751_GTAProcess.exe` -- o numero
de build muda a cada versao, por isso o match e por substring) **ou** pela
classe de janela `grcWindow` (a do GTA V; cobre o caso do processo nao ser
legivel). O **titulo da janela nao conta**: qualquer aba de navegador pode
ter "FiveM" no titulo e o bot manda teclas pra janela que achar. Entre
candidatas, fica com a de maior area (evita pegar alguma janela auxiliar
pequena).

### Seguranca (o que impede o bot de causar dano)

- **Guarda de foco** (`input_sim.py`): toda tecla enviada passa por uma
  checagem de que o FiveM esta em primeiro plano. Se nao estiver (alt-tab,
  outro app), **nada e enviado**, as teclas seguradas sao soltas e o bot para
  com o aviso "O FiveM perdeu o foco". Ao apertar INICIAR o bot tenta trazer o
  jogo pra frente e, se o Windows recusar, espera ate 20 s voce clicar nele.
- **Tecla de emergencia** (`panic.py`, padrao **F10**, configuravel em
  `keybinds.panic_key`): funciona em qualquer estado, com o jogo em foco. Para
  o bot, solta todas as teclas e deixa o estado "Parado por seguranca" na tela
  ate voce apertar INICIAR de novo. Se o hook global nao puder ser registrado
  (jogo rodando como administrador), a interface avisa e o botao PARAR continua
  valendo.
- **Watchdog da janela** (a cada 0,1 s, durante o lance): o FiveM **se
  minimiza sozinho ao perder o foco** (basta clicar no bot) e, ao restaurar,
  passa por tamanhos transitorios (1904x1042 -> 1920x1081 -> 1920x1080). Isso
  **pausa** o lance: solta as teclas, nao captura a tela, nao gasta timeout, e
  ele continua de onde parou quando o jogo volta (`PAUSADO` na interface).
  Passando de `safety.pause_timeout_seconds` (120 s) o bot para. So **aborta**
  se a janela deixar de existir ou ficar de verdade com outro
  tamanho/posicao (diferencas de ate 4 px sao ignoradas); ai recalibra.
  Apertar INICIAR com o jogo minimizado restaura ele sozinho.
- **Espera manual a prova de reinicio**: se o laco reiniciar enquanto voce
  ainda corta o peixe, o bot volta a esperar o ENTER em vez de lancar a vara.
- **Supervisor**: qualquer erro inesperado e logado com traceback em
  `fishingbot.log`, solta as teclas e leva o bot ao estado de erro (antes a
  thread morria em silencio e a tela continuava dizendo "Aguardando pesca...").
- **Fechar o app** espera o controlador soltar as teclas; ha tambem `atexit` e
  hooks de excecao nao tratada como ultima rede de seguranca.
- **Instancia unica**: abrir um segundo `FishingBot.exe` mostra um aviso e sai.

### Anti-falha (o que impede o bot de repetir o mesmo erro)

- **Resultado de cada lance** (`stats.py`): capturado, sem mordida, nao fisgou
  a tempo, painel de puxar nao apareceu, timeout ao puxar ou erro de captura.
  A interface e o log mostram o resumo da sessao (lances, capturas, % de
  sucesso, falhas seguidas); o detalhe por motivo vai no log e no diagnostico.
- **Disjuntor**: `safety.max_consecutive_failures` (padrao **5**) lances
  seguidos sem nenhuma captura desligam o bot, mostram o motivo e salvam um
  **pacote de diagnostico** em `%LOCALAPPDATA%\FishingBot\diagnostics\<data>`
  (motivo, ultimas linhas do log, janela inteira e cada regiao de
  reconhecimento naquele instante; so os 10 mais recentes ficam). Entre
  falhas, o bot espera cada vez mais (0,5 s, 1 s, 2 s... ate 5 s).
- **Monitor de saude** (thread propria, 1x/s): tela **preta** por 3 s
  (tipico de FiveM em tela cheia exclusiva) ou imagem **congelada** por 15 s
  desligam o bot com mensagem. Sem **nenhuma captura** por 15 min
  (`safety.progress_timeout_minutes`) tambem; a espera do ENTER nao conta.
- **Regioes validadas**: antes de pescar, se alguma regiao de captura cai fora
  da tela (janela parcialmente fora do monitor), o bot recusa e avisa -- o
  `mss` nao da erro nesse caso, devolve preto.
- **Fim da puxada**: o painel "PEIXE / Calmo / Puxando forte" e confirmado
  pelo **texto branco** (independe do fundo, ja que a caixa e translucida):
  sem texto nao ha painel (corrige "Parar de pescar" lido como Calmo e madeira
  lida como Puxando forte), e texto branco sobre fundo escuro sem vermelho e
  "Calmo" mesmo sobre fundo claro. Alem disso a puxada so pode ser dada como
  concluida depois de `timings.pull_min_seconds` (8 s): em log real a maioria
  das "capturas" terminava 0-5 s depois do ESPACO (puxadas de verdade duram
  30-200 s), com o peixe ainda na linha.
- **Aviso de "ainda sem mordida"**: se passar `timings.cast_confirm_seconds`
  (45 s) sem mordida, a interface avisa para conferir se a pesca comecou (vara
  nao equipada, menu/inventario aberto, longe do local), em vez de esperar 90 s
  em silencio. So informa: nao cancela o lance. (O aviso "X Parar de pescar"
  aparece junto da mordida, nao logo apos o lance; num teste real a mordida
  levou ~16 s, por isso o prazo e longo.)
- **Fisgada por forma e brilho** (`vision.read_hook`): a bolinha vermelha e um
  disco compacto e *brilhante*; a roupa do personagem tem o mesmo matiz mas e
  bem mais escura e irregular. Antes, so a proporcao de pixels vermelhos
  decidia, e o ruido da roupa (ate 0,023) era maior que a propria bolinha
  (~0,006). Medido em 123 capturas reais, a regra nova acha 4/4 bolinhas e 0
  falsos. O ESPACO exige 2 frames seguidos de peixe alinhado
  (`hit_confirm_frames`).

### Maquina de estados

`controller.py` implementa exatamente o fluxo pedido:

```
INICIALIZANDO -> PROCURANDO_FIVEM -> DETECTANDO_JANELA -> CALIBRANDO
    -> AGUARDANDO_MINIGAME -> AUTOMACAO -> CAPTURA_CONCLUIDA
    -> AGUARDANDO_CONFIRMACAO_MANUAL -> (volta pra AGUARDANDO_MINIGAME)
```

Com quedas de condicao tratadas em vez de encerrar o programa:

- Janela do FiveM some (fechou, minimizou) -> volta pra `PROCURANDO_FIVEM`.
- Janela muda de tamanho/posicao (resize, mover pra outro monitor, mudou a
  resolucao do jogo) -> volta pra `CALIBRANDO` (recalculo das regioes,
  barato -- nao precisa de nenhuma acao do usuario).
- O minigame nao aparece dentro do tempo limite, ou o painel de puxar some
  no meio -> volta direto pra `AGUARDANDO_MINIGAME`, o bot so tenta de novo
  no proximo lance (sem passar pela etapa manual, ja que nao ha peixe pra
  pegar/cortar nesse caso).

O usuario apertando **PARAR** interrompe o ciclo atual imediatamente (as
funcoes de cada fase checam isso a cada iteracao do loop, nao so no inicio)
e solta qualquer tecla que estivesse segurada -- inclusive quando o bot esta
parado em `AGUARDANDO_CONFIRMACAO_MANUAL` esperando o ENTER.

### Etapa manual entre uma pesca e outra (`AGUARDANDO_CONFIRMACAO_MANUAL`)

Depois que o peixe e capturado (`CAPTURA_CONCLUIDA`), o bot **nao** inicia
uma nova pescaria sozinho. Existem duas acoes que, por enquanto, nao sao
automatizadas: pegar o peixe no chao e corta-lo/processa-lo. Por isso o
fluxo entra em `AGUARDANDO_CONFIRMACAO_MANUAL` e fica parado ali, mostrando
claramente na interface o que fazer, ate o jogador apertar **ENTER**.

O ENTER e capturado por um hook global (`fishingbot/manual_control.py`,
biblioteca `keyboard`), entao funciona mesmo com a janela do FiveM em
primeiro plano (o normal nesse momento, ja que o jogador esta manipulando o
jogo, nao a janela do bot). O gatilho so fica "armado" durante essa espera
especifica -- um ENTER apertado em qualquer outro estado (minigame,
calibrando, etc.) e ignorado de proposito, pra um pressionamento acidental
nao interferir na automacao.

## Configuracao (`%LOCALAPPDATA%\FishingBot\config.json`)

Criado automaticamente na primeira execucao. **O arquivo guarda so o que voce
mudou** (mais `config_version` e o estado da ultima calibracao): o que nao esta
nele usa o padrao do programa, entao quando um padrao melhora ele chega a voce
sozinho. A lista completa e atual dos padroes fica em `config.reference.json`
(regravado a cada abertura, so pra consulta -- editar esse nao tem efeito;
coloque no `config.json` apenas os valores que quer trocar, ex.
`{"timings": {"bite_timeout_seconds": 60}}`).

- **Migracao:** um `config.json` de versoes antigas (que gravava todos os
  padroes) e migrado sozinho: so as suas personalizacoes sao mantidas e o
  original vira `config.json.v1.bak`.
- **Validacao:** cada valor tem tipo e faixa (ex. `max_consecutive_failures`
  inteiro de 1 a 100; um timeout negativo ou "abc" e recusado). Valor invalido
  volta ao padrao, a interface mostra um aviso e o detalhe vai pro log. Chaves
  com erro de digitacao tambem sao avisadas.
- **Arquivo ilegivel** (JSON quebrado): vira `config.json.bak` e o bot segue com
  os padroes, em vez de falhar.
- De onde vem cada numero de deteccao/tempo: [docs/calibracao.md](docs/calibracao.md).

Campos:

- `last_window` / `last_dpi_scale` / `last_calibrated_at` — so informativo,
  usado pra decidir quando vale a pena regravar o arquivo (a recalibracao
  em si acontece toda vez que a janela muda, isso so evita escrever no
  disco a cada frame).
- `keybinds` — teclas usadas (`use_item_key`, `space_key`, `pull_key`, `panic_key`,
  `release_key`). Editavel se o seu servidor usar binds diferentes.
- `timings` — timeouts de cada fase em segundos (inclui
  `after_confirm_delay_seconds`, a folga depois do ENTER, e `pull_min_seconds`).
- `safety` — limites do anti-falha: `max_consecutive_failures`,
  `progress_timeout_minutes`, `retry_backoff_base_seconds` /
  `retry_backoff_max_seconds`, `black_screen_seconds`, `frozen_screen_seconds`, `pause_timeout_seconds`.
  Valores invalidos (texto, negativo) voltam ao padrao.
- `fractions_override` — pra ajuste fino manual das regioes do minigame,
  caso a deteccao padrao (`regions.DEFAULT_FRACTIONS`) nao bata certinho no
  seu caso. Formato: `{"hook_zone": {"fx": 0.39, "fy": 0.49, "fw": 0.13,
  "fh": 0.10}}` (mesmas chaves de `regions.py`).

O programa nunca depende de nada especifico da maquina onde foi
desenvolvido -- tudo isso e recalculado a partir da janela real do jogo em
cada execucao.

## Travar a linha numa profundidade

Na janela do bot, marque **"Travar a linha em [N] m"**. Depois de lancar, o bot
acompanha a **PROFUNDIDADE** do HUD enquanto a linha afunda (sobe ~2 m/s) e
aperta a tecla **E** ("Parar nesta profundidade") quando ela chega em N. Vale a
partir do proximo lance e fica salvo (`fishing.target_depth_m` no config; vazio/
desligado = o bot nao mexe na profundidade, como antes).

Seguranca (E faz outras coisas no jogo, entao o bot e conservador):

- so aperta E com o prompt **"[E] Parar nesta profundidade"** visivel na tela;
- so aperta com a profundidade **lida com certeza**, em 2 leituras seguidas no
  alvo; leitura duvidosa, pico isolado ou HUD ilegivel = **nao aperta** (e avisa
  "a linha NAO foi travada");
- se a linha chegar ao fundo antes do alvo (`4 m (fundo)`), nao aperta nada;
- se o peixe morder enquanto afunda, a mordida tem prioridade.

Como conferir **sem risco** antes de confiar: rode `FishingBot.exe --dry-run
--debug`, clique INICIAR, e **lance a vara voce mesmo**. O bot nao envia tecla,
mas o log mostra as leituras (`depth: leitura=...`) e a decisao
(`Profundidade 5 m >= alvo 5 m -> apertaria 'e'`).

Limites: leitura validada em **1920x1080 ou maior** (em janela menor o bot avisa
e, se nao conseguir ler, nao trava). Detalhes e evidencias:
[docs/calibracao.md](docs/calibracao.md).

## Arquivos e limpeza automatica (`%LOCALAPPDATA%\FishingBot\`)

| Arquivo | O que e | Limite |
|---|---|---|
| `config.json` | so as suas personalizacoes + estado da calibracao | - |
| `config.reference.json` | padroes atuais, so consulta | regravado a cada abertura |
| `fishingbot.log` | log do bot | gira a 2 MB, guarda 3 anteriores (`.log.1` a `.3`) |
| `debug/` | PNGs do `--debug` | 7 dias **e** 100 MB (apaga os mais antigos) |
| `diagnostics/` | pacotes de quando o bot se desliga sozinho | 10 mais recentes |

## Desenvolvimento e testes

As versoes em `requirements.txt` sao **fixas** (as que os testes e o `.exe`
foram validados): atualize uma por vez e teste. Para rodar os testes e o lint:

```bat
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest
venv\Scripts\python -m pyflakes fishingbot main.py tests
```

Os testes de visao usam capturas reais do jogo (`tests/fixtures/`); de onde vem
cada limiar de deteccao esta em [docs/calibracao.md](docs/calibracao.md).

## Limitacoes conhecidas

- So Windows (usa `pywin32`/DirectInput). Não tem como rodar em outro SO.
- As fracoes de `hook_zone` (fase de fisgar) vieram de screenshots
  analisados, nao de uma calibracao 100% ao vivo como a fase de puxar --
  deve funcionar, mas se o ESPACO nunca disparar no momento certo, ajuste
  `fractions_override.hook_zone` no config.json (ou peça recalibracao).
- Nao ha (ainda) uma tela de recalibracao visual guiada pelo usuario -- a
  "recalibracao automatica" e a formula fracao->pixel recalculada a cada
  vez que a janela muda, o que cobre resolucao/escala/posicao mas nao
  cobre uma mudanca de LAYOUT da UI do jogo (ex: o servidor trocar o HUD de
  pesca por um completamente diferente).
- Nenhuma tentativa de evadir anti-cheat/deteccao de macro -- e simulacao
  de teclado padrao do Windows (pydirectinput/SendInput), igual ao projeto
  original.
