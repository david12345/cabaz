# Cabaz — monitor diário de preços de alimentos base

Agente que, todos os dias, **pesquisa** os supermercados online portugueses
(Continente, Pingo Doce, Auchan e Lidl), escolhe em cada um a opção mais barata de
27 alimentos essenciais e **monitoriza** a evolução do custo do cabaz e de cada produto.

- 📊 **Relatório do dia:** [`RELATORIO.md`](RELATORIO.md)
- 📈 **Página interativa:** [`docs/index.html`](docs/index.html) — evolução do cabaz e
  **evolução por produto** (escolha o produto na lista ou clique no nome na tabela;
  o endereço `…/#Bacalhau` abre diretamente esse produto) (ative o GitHub Pages em
  *Settings → Pages → Branch: main, pasta `/docs`* para o ver online)
- 🗃️ **Histórico completo:** [`data/precos.csv`](data/precos.csv)

## Lojas

| Loja | Fonte | Cobertura |
|---|---|---|
| Continente, Pingo Doce, Auchan | Pesquisa da loja online | Cabaz completo |
| Lidl | API de pesquisa de lidl.pt | **Parcial**: o Lidl não vende alimentação online, e o site só mostra preço dos produtos em destaque/promoção da semana (na semana de 16/11, 6 dos 27). Aparece nas tabelas e na evolução por produto, mas **não entra nos totais nem no "melhor preço"**, nem no alerta de cobertura. |
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
| Faltam mais de 10% dos preços, ou uma loja não devolveu nenhum | ❌ O workflow fica vermelho (o GitHub envia email) e é aberta uma issue. Os preços recolhidos são gravados à mesma. |
| Um preço por kg/L varia mais de 30% face à recolha anterior | ⚠️ É aberta uma issue `Alertas do cabaz: AAAA-MM-DD` (o GitHub envia email). |
| A loja passou a ter outro produto como o mais barato | 🔄 Listado na issue e no relatório, mas sozinho não abre issue. |

Os alertas aparecem também no `RELATORIO.md` e na página. Os limites ajustam-se em
`cabaz.toml`, na secção `[verificacao]`. Para receber os emails das issues, o repositório
tem de estar em *Watch → All activity* (ou *Custom → Issues*).

Para verificar à mão a última recolha: `python -m cabaz.verificacao`.

## Execução automática

O workflow [`.github/workflows/cabaz-diario.yml`](.github/workflows/cabaz-diario.yml)
corre todos os dias às 08:17 UTC, faz a recolha e grava o resultado no repositório.
Pode também ser lançado à mão em *Actions → Cabaz diário → Run workflow*.

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
