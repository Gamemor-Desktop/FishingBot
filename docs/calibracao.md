# Calibracao: de onde vem cada numero

Os valores de deteccao (`fishingbot/regions.py`) e os tempos
(`fishingbot/config_store.py`) foram ajustados com capturas reais do jogo
(`--debug`). Este documento guarda **por que** cada um e como e, pra nao se
perder em comentarios no meio do codigo. Cada decisao tem a data e a evidencia.

Os testes em `tests/` usam as proprias capturas como fixtures
(`tests/fixtures/`), entao mexer em qualquer limiar abaixo e validado contra elas.

## Regioes (fracoes da janela)

Medidas em 1920x1080 e guardadas como fracao da janela (`DEFAULT_FRACTIONS`),
pra funcionar em qualquer resolucao.

- `hook_zone` (756,528 252x108): bolinha vermelha + peixinho da fase de mordida.
  Estimada a partir de screenshots do usuario.
- `pulling_state` (24,528 270x43): linha "PEIXE" (Calmo / Puxando forte).
  **Recalibrada em 14/09/2026** a partir de screenshot real: a caixa com borda
  vermelha vai de x=24..293, y=528..570; a calibracao anterior (16,403 208x33)
  estava ~125 px mais alta que a caixa real, por isso o bot nunca via o painel
  de verdade e so dava match por coincidencia.
- (removida) `distance_ocr` (95,322 70x30): numero de distancia da linha "LINHA",
  pra um OCR opcional que nunca foi usado; saiu na limpeza da Fase 4.

## Fisgada (`hook_zone`)

**03/10/2026.** Antes a deteccao era so "proporcao de pixels vermelho-laranja"
com limiar absoluto. A roupa do personagem (hoodie listrado) tem as mesmas cores
e gera 0,005-0,023 de ruido, **maior que a propria bolinha (~0,006)**, entao a
mordida "era detectada" por coincidencia e o ESPACO disparava sem peixe. Em
123 capturas reais, so 4 tinham a bolinha.

O que separa as duas coisas:

| | bolinha / peixe | roupa |
|---|---|---|
| brilho (V no HSV) | ~221-231 | <= 173 |
| forma | disco compacto 14x14 (area ~155-165, preenchimento >= 0,79) | manchas finas/irregulares (preenchimento <= 0,65) |

Regra atual: mascara com V >= 200 + checagem de forma da bolinha
(`vision.read_hook`). Nas 123 capturas: **4/4 bolinhas, 0/119 falsos**; ruido
restante <= 0,001 de proporcao, contra 0,0054 (so bolinha) e 0,0255 (bolinha +
peixe). `hit_min_ratio = 0,014` fica no meio. As areas escalam com o quadrado da
largura da regiao (`vision.HOOK_REF_WIDTH`).

Confirmado em pescaria real (04/10/2026): fisgada com `ratio=0,0238`.

## Painel de puxar: "Calmo" (`pulling_gray`)

- **14/09/2026:** a caixa **nao** e cinza neutro, e um azul-marinho escuro
  (fundo RGB ~(19..25, 23..30, 30..35) -> H ~106-109 no OpenCV; borda RGB
  ~(26..27, 46..47, 71..72) -> H ~106, S ~160). O range antigo (S ate 60)
  cortava praticamente toda a caixa real (S real ~90-162): so batia ~1% da area.
- **15/09/2026:** depois que a caixa some de vez (peixe fora d'agua), a regiao
  fica so com o **fundo** azul-marinho do jogo (V ~51-68, S ~145-223), que
  batia **tambem** com o range antigo (V ate 100, S ate 200), dando ratio=1,0
  igual a caixa de verdade. O bot nunca via a leitura cair e ficava segurando a
  tecla por dezenas de segundos (49 s seguidos num log real). A caixa real tem
  V mediano ~33 e S mediano ~116; apertar **V <= 48 e S <= 140** corta o fundo e
  ainda cobre ~88% da caixa.

## Painel de puxar: "Puxando forte" (`pulling_red`)

- Fundo marrom-avermelhado escuro RGB ~(31..85, 25..41, 34..44), borda RGB
  ~(145..158, 54..58, 47..51). No HSV (0-179) isso cai perto de H=135-179
  (vinho, do lado do "wrap" com H=0), longe da faixa antiga (H=0-25).
- **15/09/2026:** a **mesma** caixa pode renderizar com H perto de 0 (media ~8,
  sessao com luz ambiente mais clara) em vez de perto de 179 (media ~161, luz
  mais escura). Uma faixa so cobre um lado; com H~8 o ratio ficava 0 o tempo
  todo e o painel "nunca aparecia". Como H e circular, sao **duas faixas**
  (`vision.hsv_mask_multi`). Validado em 4 capturas reais (ratio 0,77-0,92).

## Painel de puxar: texto branco (`pulling_text`)

**03/10/2026.** A caixa e **translucida**: a cor muda com o cenario atras. O
texto branco nao muda. Em 103 capturas reais o painel tem texto branco na
metade direita em 3,5%-10% da area (27% sobre fundo claro), cercado de fundo
escuro; "Parar de pescar" (texto vermelho), agua, madeira e fundo cinza tem
~0%; a cerca branca tem 9%-59% mas **sem** fundo escuro em volta
(`near_dark` 0,14-0,22).

Usos (`fishing_logic.classify_pull_state`):

- sem texto (< `min_ratio`) nao ha painel, mesmo que a cor "bata" (eliminou
  "Parar de pescar" sobre agua escura lido como Calmo e a madeira lida como
  Puxando forte);
- "Calmo" translucido sobre fundo marrom/claro, que a cor nao pega: texto +
  fundo escuro em volta + nenhum vermelho = Calmo. **Antes isso fazia o bot
  declarar "peixe capturado" 1-3 s depois do ESPACO, com o peixe ainda na
  linha** (a maioria das ~40 "capturas" antigas durava 0-5 s; puxadas reais
  duram 30-200 s).

Validado na pescaria real de 04/10/2026: 108 frames de uma puxada de 1 min 49 s,
85 Calmo, 21 Puxando forte, 2 sem painel (primeiro e ultimo frame), 0 perdas.

## Aviso "X Parar de pescar" (`stop_prompt`)

Texto vermelho vivo + o "X" branco da tecla, a esquerda. Em 18 capturas
rotuladas (4 com o aviso, 4 fundos): vermelho 0,030-0,039 e branco do X 0,0063
em todas; "Puxando forte" tem vermelho (0,045) sem o X; a cerca tem branco (0,61)
sem vermelho.

**Aparece junto da mordida** (~1 s antes da bolinha, ~16 s depois do lance num
teste real), **nao** logo apos lancar. Por isso o alerta "ainda sem mordida" so
dispara aos 45 s (`cast_confirm_seconds`); um prazo curto dava alarme falso em
toda pescaria normal.

## Tempos (`timings`)

- `end_confirm_seconds` (1,2): quantos **segundos seguidos** o painel precisa
  ficar ausente pra a puxada ser dada como terminada. E tempo real, nao
  contagem de frames: contar frames (ex: 15 leituras sem match) depende da
  velocidade do loop e podia passar em bem menos de 1 s, declarando "painel
  sumiu" por uma unica leitura ruim (flicker), quase junto com o ESPACO. Se
  ainda acontecer, aumente (1,5 ou 2,0).
- `pull_panel_first_appear_timeout_seconds` (6,0): quanto esperar o painel
  aparecer pela **primeira** vez depois do ESPACO. Separado do anterior (que
  detecta o painel **sumindo**). **Subido de 3,0 pra 6,0 em 15/09/2026:** logo
  apos o ESPACO o jogo mostra por um tempo "X Parar de pescar" na mesma regiao
  onde depois aparece "Calmo"/"Puxando forte", e as vezes isso ficava mais de
  3 s antes de trocar; com 3,0 o bot desistia com o peixe ja fisgado.
- `pull_min_seconds` (8,0): a puxada nao pode ser dada como concluida antes
  disso (ver "texto branco" acima).
- `after_confirm_delay_seconds` (1,5): folga entre o ENTER e a tecla da vara; o
  personagem ainda pode estar na animacao de cortar o peixe.
- `cast_confirm_seconds` (45): ver "Aviso X Parar de pescar".
- `hit_min_ratio`, `hit_confirm_frames`: ver "Fisgada".

## Anti-falha (`safety`)

- `max_consecutive_failures` (5): lances seguidos sem captura que desligam o
  bot e salvam o pacote de diagnostico. O normal de uma pesca sem sorte e falhar
  1-2 vezes.
- `progress_timeout_minutes` (15): sem nenhuma captura/retomada por esse tempo o
  bot para; a espera do ENTER nao conta.
- `retry_backoff_*`: espera entre lances que falharam, `base * 2^(falhas-1)`,
  limitada a `max`.
- `black_screen_seconds` (3), `frozen_screen_seconds` (15): tela preta ou imagem
  identica por esse tempo e erro.
- `pause_timeout_seconds` (120): FiveM minimizado/sem foco pausa o ciclo; passando
  disso o bot para.

## Profundidade (travar a linha)

**04/10/2026**, a partir de uma gravacao do HUD feita pelo usuario
(`tools/capture_hud.py`; a gravacao bruta foi perdida, as 53 fixtures
rotuladas que sairam dela estao em `tests/fixtures/{depth,prompt,linha}`).

**Como e no jogo.** Depois do lance o HUD passa por ARREMESSANDO (profundidade
`-`), AFUNDANDO (a profundidade sobe sozinha **~2 m/s**: 0 m em 22,15 s, 2 m em
22,65 s, 3 m, 4 m...; aparece o prompt **"[E] Parar nesta profundidade"**),
ESPERANDO (`4 m (fundo)` quando chega ao fundo; o prompt do E some, aparece
"[X] Parar de pescar") e FISGADO (linha "PEIXE" + W/S/X). Apertar **E** durante o
AFUNDANDO trava a linha na profundidade atual.

**Geometria (1920x1080, caixas de 270x43 px em x=24).** O HUD e uma coluna de
caixas que troca de conteudo conforme a fase:

| linha | y | AFUNDANDO / ESPERANDO | FISGADO |
|---|---|---|---|
| 1 | ~424 | LINHA `18,5 /181 m` | LINHA |
| 2 | **477** | **PROFUNDIDADE `3 m`** (regiao `depth_row`) | PROFUNDIDADE |
| 3 | 528 | `[E] Parar nesta profundidade` / `[X] Parar de pescar` | PEIXE `Calmo` |

A linha 3 e a regiao `pulling_state`: o mesmo lugar muda de conteudo.
**Erro corrigido:** a primeira gravacao usou a regiao `pulling_state` achando que
era a da profundidade; so o quadro maior do HUD mostrou que a PROFUNDIDADE e a
linha 2.

**Leitura (sem OCR externo).** Fonte monoespacada de tamanho fixo: digitos
~9x14 px, passo de 11,5-13,5 px entre centros, `m` ~10x10 a ~22,5 px do ultimo
digito. Cada digito e comparado com um modelo 12x18 (distancia media <= 0,20 e
margem >= 0,03 sobre o 2o). Os modelos vem do numero grande do **LINHA** (mesma
fonte, ~7% maior, traz 0-9) + da caixa PROFUNDIDADE. Teste fora da amostra:
modelos feitos so com o LINHA leem **14/14** caixas PROFUNDIDADE que nunca viram
(margem minima 0,043).

**Prompt do E.** Texto identico em todo o jogo, comparado por pixels brancos
contra um modelo: positivos 1,00/1,00 (recall/precisao), melhor negativo
(painel "Puxando forte") 0,54; limiar 0,85.

**Limites conhecidos (nao validados):**

- Leituras reais de **0 a 27 m** (gravacoes de 04/10/2026, agua rasa e funda).
  **3 digitos (100+) so foram testados com imagens sintetizadas** (digitos reais
  colados): nao ha gravacao real de 100 m ou mais.
- Resolucao: validado em **1920x1080** (50/50). Em outras escalas (1,1x a 2x,
  reamostradas) 46-50 de 50 sao lidas e **nenhuma e lida errada**; abaixo de 1080p
  a leitura piora (0,85x: 12/14; 0,667x: 0/14) -- sempre "nao li", nunca um
  numero errado, e o bot nao aperta E. **Consequencia:** se o digito exato do alvo
  nao for legivel, o bot trava no proximo valor legivel (ex.: alvo 8, trava em 9).
- Nao se sabe se bites acontecem durante o AFUNDANDO; por seguranca a mordida tem
  prioridade sobre a trava.

**Gravacao em agua funda (04/10/2026 01:03).** Validacao FORA DA AMOSTRA: com os
modelos feitos so da gravacao rasa e do LINHA, o leitor produziu uma **escada
perfeita 0, 1, 2, ..., 27** (cada inteiro uma vez, na ordem, 189 quadros com
numero, **0 saltos ou retrocessos**), incluindo 7, 8, 9 e todos os numeros de 2
digitos; conferido a olho em 10 instantes. O prompt do E foi detectado de 10,8 s a
21,4 s e sumiu quando o E foi apertado; nenhum falso positivo (tela de outro
programa, "X Parar de pescar", "-" do arremesso). Margens: a minima foi 0,031 (nos
digitos '8' e '18') -- perto do limite 0,03 --; acrescentar 41 recortes dessa
gravacao como fixtures e regerar os modelos subiu a minima para **0,050**.

Observado nessa gravacao: a profundidade sobe **~2,5 m/s** (1 m a cada ~0,4 s);
existe uma fase **PREPARANDO** (LINHA `0,0 /200 m`) antes do ARREMESSANDO; depois
do E o HUD vai a ESPERANDO com a profundidade travada (`27 m`, **sem** o
`(fundo)`) e o prompt "[X] Parar de pescar".

## Comportamentos do jogo observados

- O FiveM **se minimiza sozinho ao perder o foco** (basta clicar no bot) e, ao
  restaurar, passa por tamanhos transitorios (1904x1042 -> 1920x1081 ->
  1920x1080). Por isso isso e pausa, e diferencas de ate 4 px sao ignoradas.
- A classe da janela do jogo e `grcWindow`, e o processo e `*GTAProcess*`; o
  titulo muda com o servidor e nao serve pra identificar.
