# Cabaz — monitor diário de preços de alimentos base

Agente que, todos os dias, **pesquisa** os supermercados online portugueses
(Continente, Pingo Doce e Auchan), escolhe em cada um a opção mais barata de
cada produto dos cabazes e **monitoriza** a evolução do custo dos cabazes e de cada produto.

- 📊 **Relatório do dia:** [`RELATORIO.md`](RELATORIO.md)
- 📈 **Página interativa:** [`docs/index.html`](docs/index.html) — evolução do cabaz e
  **evolução por produto** (escolha o produto na lista ou clique no nome na tabela;
  o endereço `…/#Bacalhau` abre diretamente esse produto) (ative o GitHub Pages em
  *Settings → Pages → Branch: main, pasta `/docs`* para o ver online)
- 🗃️ **Histórico completo:** [`data/precos.csv`](data/precos.csv)

## Cabazes

São analisados em separado, cada um com totais, página e relatório próprios:

| Cabaz | Produtos | Página | Relatório |
|---|---|---|---|
| **Cabaz de alimentos base** | 27 alimentos essenciais | [`docs/index.html`](docs/index.html) | [`RELATORIO.md`](RELATORIO.md) |
| **Cabaz extra** | 18 produtos: álcool etílico 96%, gin Gordon's, sabonete Feno, iogurte grego natural, iogurte grego natural Oikos (4×110 g), salmão fumado, Becel sabor a manteiga, courgete, abóbora, alho francês, brócolos, couve-flor, nabos, salsa, coentros, framboesas, ervilhas congeladas, nozes | [`docs/extra.html`](docs/extra.html) | [`RELATORIO-extra.md`](RELATORIO-extra.md) |

Para criar outro cabaz: acrescente-o em `[cabazes]` no `cabaz.toml` (ex.: `limpeza = "Cabaz de limpeza"`)
e indique `cabaz = "limpeza"` nos respetivos `[[produto]]`. A página fica em `docs/limpeza.html`.

Notas sobre o cabaz extra:
- **Álcool etílico:** nenhuma loja vende a 98%; segue-se o de 96%.
- **Becel:** é um creme vegetal para barrar; segue-se a versão "sabor a manteiga".
- **Oikos natural:** nenhuma loja vende o de 200 g; segue-se o pack 4×110 g (440 g), à venda nas três.
- **Nozes:** as lojas não indicam a origem online, por isso não é possível garantir "nacionais"
  (exclui-se o miolo do Chile). No Pingo Doce só há miolo de marca premium.
- **Brócolos e couve-flor no Continente:** fixados os frescos (`fixo`), porque as embalagens
  de 1 kg / 750 g são congeladas.
- **Abóbora:** a variedade mais barata varia de loja para loja (inteira, manteiga, butternut).

## Lojas

| Loja | Fonte | Cobertura |
|---|---|---|
| Continente, Pingo Doce, Auchan | Pesquisa da loja online | Cabaz completo |
| Lidl | — | **Não incluído**: não vende alimentação online e o site só mostra preço dos produtos em promoção da semana (6–12 dos 27), com resultados pouco fiáveis (ex.: "cebola" devolvia um hambúrguer com cebola). Testado de 16 a 21/11/2026 e retirado. |
| Mercadona | — | **Não incluída**: não tem loja online em Portugal (a de Espanha tem preços espanhóis) e o site mercadona.pt bloqueia acessos automáticos. |

## Como funciona

1. `cabaz.toml` define o cabaz: para cada produto, o termo de pesquisa, palavras
   que o nome tem de conter / não pode conter, e a unidade de comparação (kg, L ou un).
2. `cabaz/lojas.py` pesquisa cada loja e lê preço, preço por unidade e promoções.
   Produtos vendidos ao peso (fruta, carne, peixe) são lidos em €/kg.
3. `cabaz/agente.py` escolhe a opção mais barata por kg/L/unidade que cumpre os
   critérios e acrescenta uma linha por produto e loja a `data/precos.csv`
   (correr duas vezes no mesmo dia substitui os valores desse dia).
4. `cabaz/relatorio.py` calcula:
   - custo do cabaz por loja e ao **melhor preço** (loja mais barata em cada produto);
   - variações vs ontem, 7 dias, 30 dias e início do registo;
   - maiores subidas/descidas do dia por produto e loja.

O custo de referência de cada produto é o preço por kg ou litro (ovos: dúzia).
Se uma loja falhar num dia, usa-se o último preço conhecido e a falha aparece nos avisos.

## Verificação automática (alertas)

Depois de cada recolha, `cabaz/verificacao.py` confere a qualidade dos dados:

| Situação | O que acontece |
|---|---|
| Durante o dia faltam preços (ex.: uma loja bloqueou o servidor) | ℹ️ Só aviso no registo da execução: a execução seguinte tenta outra vez o que falta. |
| Um dia **terminou** com mais de 10% dos preços em falta, ou com uma loja sem nenhum | ❌ Na primeira execução do dia seguinte, o workflow fica vermelho (o GitHub envia email) e é aberta uma issue. |
| Um preço por kg/L varia mais de 30% face à recolha anterior | ⚠️ É aberta uma issue `Alertas do cabaz: AAAA-MM-DD` (só para os preços recolhidos nessa execução, para não repetir alertas). |
| A loja passou a ter outro produto como o mais barato | 🔄 Listado na issue e no relatório, mas sozinho não abre issue. |

Os alertas aparecem também no `RELATORIO.md` e na página. Os limites ajustam-se em
`cabaz.toml`, na secção `[verificacao]`. Para receber os emails das issues, o repositório
tem de estar em *Watch → All activity* (ou *Custom → Issues*).

Para verificar à mão a última recolha: `python -m cabaz.verificacao`.

## Execução automática

O workflow [`.github/workflows/cabaz-diario.yml`](.github/workflows/cabaz-diario.yml)
está agendado **três vezes por dia** (08:17, 13:47 e 19:17 UTC; o GitHub costuma atrasar
as execuções várias horas). A primeira execução do dia recolhe tudo; as seguintes só o que
faltar — por exemplo, quando uma loja bloqueou o endereço IP do servidor anterior (cada
execução corre noutro servidor). Se não faltar nada, terminam em segundos sem commit.

Se uma loja recusar duas pesquisas seguidas (HTTP 403/429), o agente desiste dessa loja
nessa execução, em vez de gastar minutos a insistir do mesmo IP.

Pode também ser lançado à mão em *Actions → Cabaz diário → Run workflow*; por omissão
recolhe só o que falta hoje, ou tudo outra vez se marcar *completa*.

## Uso local

```bash
pip install -r requirements.txt
python -m cabaz.agente                         # recolhe hoje e gera o relatório
python -m cabaz.agente --sem-gravar            # só mostra o que encontraria
python -m cabaz.agente --produtos leite ovos --lojas auchan --sem-gravar
python -m cabaz.agente --so-relatorio          # regenera o relatório a partir do CSV
python -m unittest discover -s tests
```

## Ajustar o cabaz

Edite `cabaz.toml`. Para seguir sempre **o mesmo produto** numa loja (em vez do
mais barato), fixe o código que aparece na coluna `pid` do CSV:

```toml
fixo = { continente = "4421406", auchan = "3010402", pingodoce = "48150" }
```

Se um produto começar a dar "sem correspondência", corra
`python -m cabaz.agente --produtos <nome> --sem-gravar` e ajuste `incluir`/`excluir`.

## Limitações

- Os preços são os da loja online, que podem diferir das lojas físicas.
- Os sites podem mudar o HTML; nesse caso os testes continuam a passar mas a recolha
  mostra falhas nos avisos e o parser da loja em `cabaz/lojas.py` tem de ser atualizado.
- Escolher sempre o mais barato mede o custo mínimo do cabaz; uma troca de produto
  (ex.: nova marca branca) aparece como variação de preço. Use `fixo` se preferir
  acompanhar produtos concretos.
