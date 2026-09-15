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
   para pescar novamente." Essa etapa (pegar o peixe no chao e corta-lo) nao
   e automatizada -- faca-a normalmente no jogo e, quando terminar, aperte
   **ENTER** pra o bot lançar a vara de novo. O ENTER so tem efeito nesse
   momento especifico; apertado em qualquer outra hora (durante o minigame,
   por exemplo) e ignorado, de proposito, pra nao atrapalhar a automacao.
6. **PARAR** interrompe a automacao e solta qualquer tecla que estivesse
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
  config_store.py           persistencia em %LOCALAPPDATA%\FishingBot\config.json
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
de build muda a cada versao, por isso o match e por substring). Se por
algum motivo isso nao bater, cai pra um fallback por titulo da janela
contendo "fivem". Entre candidatas, fica com a de maior area (evita pegar
alguma janela auxiliar pequena).

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

Criado automaticamente na primeira execucao. Guarda:

- `last_window` / `last_dpi_scale` / `last_calibrated_at` — so informativo,
  usado pra decidir quando vale a pena regravar o arquivo (a recalibracao
  em si acontece toda vez que a janela muda, isso so evita escrever no
  disco a cada frame).
- `keybinds` — teclas usadas (`use_item_key`, `space_key`, `pull_key`,
  `release_key`). Editavel se o seu servidor usar binds diferentes.
- `timings` — timeouts de cada fase em segundos.
- `fractions_override` — pra ajuste fino manual das regioes do minigame,
  caso a deteccao padrao (`regions.DEFAULT_FRACTIONS`) nao bata certinho no
  seu caso. Formato: `{"hook_zone": {"fx": 0.39, "fy": 0.49, "fw": 0.13,
  "fh": 0.10}}` (mesmas chaves de `regions.py`).

O programa nunca depende de nada especifico da maquina onde foi
desenvolvido -- tudo isso e recalculado a partir da janela real do jogo em
cada execucao.

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
