"""Gera RELATORIO.md e docs/index.html a partir do histórico de preços."""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOJAS_NOMES = {"continente": "Continente", "pingodoce": "Pingo Doce", "auchan": "Auchan"}
UNID_REF = {"kg": "kg", "L": "L", "un": "un"}


def _eur(v: float | None) -> str:
    return "—" if v is None else f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(novo: float | None, velho: float | None) -> float | None:
    if novo is None or not velho:
        return None
    return (novo / velho - 1) * 100


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return "—"
    if abs(p) < 0.05:
        return "= 0,0%"
    seta = "▲" if p > 0 else "▼"
    return f"{seta} {p:+.1f}%".replace(".", ",")


def series(historico: list[dict], produtos: list[dict]):
    """Custos por (produto, loja) ao longo das datas, com o último valor conhecido
    propagado para dias em que a recolha falhou."""
    ordem = [p["nome"] for p in produtos]
    datas = sorted({l["data"] for l in historico})
    lojas = [l for l in LOJAS_NOMES if any(h["loja"] == l for h in historico)]
    bruto: dict[tuple, dict] = {}
    for l in historico:
        bruto[(l["data"], l["produto"], l["loja"])] = l
    custo: dict[str, dict[tuple, float]] = {}
    real: dict[str, dict[tuple, dict]] = {}
    ultimo: dict[tuple, float] = {}
    for d in datas:
        custo[d], real[d] = {}, {}
        for prod in ordem:
            for loja in lojas:
                linha = bruto.get((d, prod, loja))
                if linha:
                    ultimo[(prod, loja)] = float(linha["custo_ref"])
                    real[d][(prod, loja)] = linha
                if (prod, loja) in ultimo:
                    custo[d][(prod, loja)] = ultimo[(prod, loja)]
    return ordem, datas, lojas, custo, real


def totais(ordem, datas, lojas, custo):
    """Total do cabaz por loja e 'melhor preço' (mínimo entre lojas) por data.

    Só conta um total de loja quando essa loja tem preço para todos os produtos;
    o 'melhor cabaz' usa os produtos com preço em pelo menos uma loja."""
    por_loja = {loja: [] for loja in lojas}
    melhor = []
    for d in datas:
        c = custo[d]
        for loja in lojas:
            vals = [c.get((p, loja)) for p in ordem]
            por_loja[loja].append(round(sum(vals), 2) if all(v is not None for v in vals) else None)
        mins = [min((c[(p, l)] for l in lojas if (p, l) in c), default=None) for p in ordem]
        mins = [m for m in mins if m is not None]
        melhor.append(round(sum(mins), 2) if mins else None)
    return por_loja, melhor


def _valor_em(datas, valores, alvo: str):
    """Valor na última data <= alvo."""
    res = None
    for d, v in zip(datas, valores):
        if d <= alvo and v is not None:
            res = v
    return res


def gerar(historico: list[dict], produtos: list[dict], falhas: list[str] | None = None) -> None:
    from . import verificacao

    falhas = falhas or []
    if not historico:
        return
    ordem, datas, lojas, custo, real = series(historico, produtos)
    limites = verificacao.carregar_limites()
    verif = verificacao.verificar(historico, produtos, list(LOJAS_NOMES), limites)
    por_loja, melhor = totais(ordem, datas, lojas, custo)
    hoje = datas[-1]
    ontem = datas[-2] if len(datas) > 1 else None
    d_hoje = dt.date.fromisoformat(hoje)
    ref = {
        "ontem": ontem,
        "7 dias": (d_hoje - dt.timedelta(days=7)).isoformat(),
        "30 dias": (d_hoje - dt.timedelta(days=30)).isoformat(),
        "início": datas[0],
    }
    unid = {p["nome"]: p["unidade"] for p in produtos}
    qtd = {p["nome"]: p["quantidade"] for p in produtos}

    # variações por produto (melhor preço entre lojas)
    def melhor_prod(d, p):
        vals = [custo[d][(p, l)] for l in lojas if (p, l) in custo[d]]
        return min(vals) if vals else None

    movimentos = []
    if ontem:
        for p in ordem:
            for loja in lojas:
                a, b = custo[ontem].get((p, loja)), real[hoje].get((p, loja))
                if a and b:
                    pc = _pct(float(b["custo_ref"]), a)
                    if pc is not None and abs(pc) >= 0.05:
                        movimentos.append((pc, p, loja, a, float(b["custo_ref"]), b["nome_loja"]))
    movimentos.sort(key=lambda m: -abs(m[0]))

    # ---------- Markdown ----------
    L = [f"# Cabaz de alimentos base — {hoje}", ""]
    L.append(f"Preços recolhidos diariamente em {', '.join(LOJAS_NOMES[l] for l in lojas)}. "
             f"{len(ordem)} produtos; custo de referência = preço por kg/L (ovos: dúzia). "
             "Em cada loja escolhe-se a opção mais barata que cumpre os critérios de `cabaz.toml`.")
    L += ["", "## Custo do cabaz", "", "| | Hoje | vs ontem | vs 7 dias | vs 30 dias | vs início |", "|---|---:|---:|---:|---:|---:|"]
    linhas_tot = [("**Melhor preço** (loja mais barata em cada produto)", melhor)] + \
                 [(LOJAS_NOMES[l], por_loja[l]) for l in lojas]
    for nome, vals in linhas_tot:
        atual = vals[-1]
        cel = [_fmt_pct(_pct(atual, _valor_em(datas[:-1], vals[:-1], r))) if r else "—" for r in ref.values()]
        L.append(f"| {nome} | {_eur(atual)} | " + " | ".join(cel) + " |")
    L += ["", "> Total de loja só aparece quando a loja tem preço para todos os produtos nesse dia "
          "(falhas pontuais usam o último preço conhecido).", ""]

    L += ["## Preços de hoje", "", "| Produto | " + " | ".join(LOJAS_NOMES[l] for l in lojas) + " | Var. dia (melhor) |",
          "|---|" + "---:|" * len(lojas) + "---:|"]
    for p in ordem:
        vals = {l: real[hoje].get((p, l)) for l in lojas}
        presentes = [float(v["custo_ref"]) for v in vals.values() if v]
        mn = min(presentes) if presentes else None
        cels = []
        for l in lojas:
            v = vals[l]
            if not v:
                cels.append("—")
                continue
            c = float(v["custo_ref"])
            txt = _eur(c)
            if c == mn and len(presentes) > 1:
                txt = f"**{txt}**"
            if v.get("promocao") == "1":
                txt += " 🏷"
            cels.append(f"[{txt}]({v['url']})" if v.get("url") else txt)
        var = _fmt_pct(_pct(melhor_prod(hoje, p), melhor_prod(ontem, p))) if ontem else "—"
        rot = f"{p} (/{'dúzia' if unid[p] == 'un' and qtd[p] == 12 else UNID_REF[unid[p]]})"
        L.append(f"| {rot} | " + " | ".join(cels) + f" | {var} |")
    L += ["", "**Negrito** = mais barato; 🏷 = em promoção.", ""]

    L += ["## Maiores variações desde ontem", ""]
    if movimentos:
        L += ["| Produto | Loja | Ontem | Hoje | Var. |", "|---|---|---:|---:|---:|"]
        for pc, p, loja, a, b, nome in movimentos[:12]:
            L.append(f"| {p} — _{nome}_ | {LOJAS_NOMES[loja]} | {_eur(a)} | {_eur(b)} | {_fmt_pct(pc)} |")
    else:
        L.append("Sem variações (ou ainda só há um dia de histórico).")
    L.append("")
    L += ["## Verificação automática", "", verificacao.markdown(verif, limites)]
    if falhas:
        L += ["## Avisos da recolha", ""] + [f"- {f}" for f in falhas] + [""]
    L += ["---", f"Histórico completo: [`data/precos.csv`](data/precos.csv) · "
          f"Gráfico interativo: [`docs/index.html`](docs/index.html) · {len(datas)} dia(s) registado(s)."]
    (RAIZ / "RELATORIO.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---------- HTML ----------
    dados = {
        "hoje": hoje,
        "datas": datas,
        "lojas": [{"id": l, "nome": LOJAS_NOMES[l], "totais": por_loja[l]} for l in lojas],
        "melhor": melhor,
        "variacoes": {k: _pct(melhor[-1], _valor_em(datas[:-1], melhor[:-1], r)) if r else None for k, r in ref.items()},
        "produtos": [
            {
                "nome": p,
                "unidade": "dúzia" if unid[p] == "un" and qtd[p] == 12 else unid[p],
                "serie": [melhor_prod(d, p) for d in datas],
                "lojas": {
                    l: ({"custo": float(v["custo_ref"]), "preco": float(v["preco"]), "nome": v["nome_loja"],
                         "url": v["url"], "promo": v.get("promocao") == "1"} if (v := real[hoje].get((p, l))) else None)
                    for l in lojas
                },
            }
            for p in ordem
        ],
        "falhas": falhas,
        "alertas": verif.criticos + [
            f"{s['produto']} @ {s['loja']}: {_eur(s['antes'])} → {_eur(s['depois'])}/{s['unidade']} "
            f"({s['variacao'] * 100:+.0f}%)" + (f" — produto trocado para {s['nome_depois']}" if s["trocou"] else "")
            for s in verif.suspeitos
        ],
    }
    modelo = (Path(__file__).parent / "modelo.html").read_text(encoding="utf-8")
    html = modelo.replace("/*__DADOS__*/null", json.dumps(dados, ensure_ascii=False).replace("</", "<\\/"))
    (RAIZ / "docs").mkdir(exist_ok=True)
    (RAIZ / "docs" / "index.html").write_text(html, encoding="utf-8")
