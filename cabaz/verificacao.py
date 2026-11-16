"""Verificações de qualidade da recolha do dia.

Críticos (o workflow falha e o GitHub envia email):
  - cobertura abaixo do mínimo (por omissão 90% dos preços esperados);
  - uma loja sem nenhum preço no dia.

Suspeitos (abre-se uma issue no GitHub):
  - preço por kg/L que varia mais do que o limite (por omissão 30%) face à
    recolha anterior do mesmo produto na mesma loja.

Informativo (listado na issue e no relatório, mas não abre issue sozinho):
  - troca do produto escolhido (outro código de produto) face à recolha anterior.

Uso no workflow:
    python -m cabaz.verificacao --saida verificacao   # escreve issue.md e define outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
from .lojas import NOMES as LOJAS_NOMES

PADRAO = {"cobertura_minima": 0.90, "variacao_suspeita": 0.30}


@dataclass
class Resultado:
    data: str
    anterior: str | None
    esperados: int
    recolhidos: int
    criticos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    suspeitos: list[dict] = field(default_factory=list)
    trocas: list[dict] = field(default_factory=list)

    @property
    def cobertura(self) -> float:
        return self.recolhidos / self.esperados if self.esperados else 0.0


def carregar_limites(caminho: Path = RAIZ / "cabaz.toml") -> dict:
    with open(caminho, "rb") as f:
        cfg = tomllib.load(f).get("verificacao", {})
    return {**PADRAO, **cfg}


def verificar(historico: list[dict], produtos: list[dict], lojas: list[str],
              limites: dict | None = None, data: str | None = None,
              parciais: set[str] | frozenset = frozenset()) -> Resultado:
    """`parciais`: lojas sem catálogo completo online (ex.: Lidl). Contam para as
    variações, mas não para a cobertura; sem nenhum preço geram só um aviso."""
    lim = {**PADRAO, **(limites or {})}
    datas = sorted({l["data"] for l in historico})
    completas = [l for l in lojas if l not in parciais]
    if not datas:
        return Resultado(data or "", None, len(produtos) * len(completas), 0,
                         criticos=["Histórico vazio: nenhum preço recolhido."])
    data = data or datas[-1]
    anteriores = [d for d in datas if d < data]
    anterior = anteriores[-1] if anteriores else None

    nomes = [p["nome"] for p in produtos]
    hoje = {(l["produto"], l["loja"]): l for l in historico if l["data"] == data and l["produto"] in nomes}
    ontem = {(l["produto"], l["loja"]): l for l in historico if l["data"] == anterior} if anterior else {}

    r = Resultado(data, anterior, len(nomes) * len(completas),
                  sum(1 for (_, lj) in hoje if lj not in parciais))

    # --- críticos
    if r.cobertura < lim["cobertura_minima"]:
        r.criticos.append(
            f"Cobertura de {r.cobertura:.0%}: {r.recolhidos} de {r.esperados} preços "
            f"(mínimo {lim['cobertura_minima']:.0%}).")
    for loja in lojas:
        n = sum(1 for (_, lj) in hoje if lj == loja)
        if n == 0 and loja in parciais:
            r.avisos.append(f"{LOJAS_NOMES.get(loja, loja)} (loja parcial): nenhum preço recolhido. "
                            "Pode ser só uma semana sem produtos do cabaz em destaque, ou uma mudança no site.")
        elif n == 0:
            r.criticos.append(f"{LOJAS_NOMES.get(loja, loja)}: nenhum preço recolhido "
                              "(site em baixo, bloqueio ou mudança no site).")

    # --- suspeitos e trocas
    for (prod, loja), novo in sorted(hoje.items()):
        velho = ontem.get((prod, loja))
        if not velho:
            continue
        a, b = float(velho["preco_unidade"]), float(novo["preco_unidade"])
        trocou = velho["pid"] != novo["pid"]
        info = {
            "produto": prod, "loja": LOJAS_NOMES.get(loja, loja), "unidade": novo["unidade"],
            "antes": a, "depois": b, "variacao": (b / a - 1) if a else None,
            "nome_antes": velho["nome_loja"], "nome_depois": novo["nome_loja"],
            "url": novo.get("url", ""), "trocou": trocou,
        }
        if a and abs(b / a - 1) > lim["variacao_suspeita"]:
            r.suspeitos.append(info)
        elif trocou:
            r.trocas.append(info)
    r.suspeitos.sort(key=lambda s: -abs(s["variacao"] or 0))
    return r


def _eur(v: float) -> str:
    return f"{v:.2f} €".replace(".", ",")


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.0f}%".replace(".", ",")


def markdown(r: Resultado, limites: dict | None = None) -> str:
    lim = {**PADRAO, **(limites or {})}
    L = [f"Verificação da recolha de **{r.data}** "
         f"(cobertura {r.recolhidos}/{r.esperados} = {r.cobertura:.0%})"
         + (f", comparada com **{r.anterior}**." if r.anterior else "."), ""]
    if r.criticos:
        L += ["### ❌ Problemas críticos", ""] + [f"- {c}" for c in r.criticos] + [""]
    if r.avisos:
        L += ["### ℹ️ Avisos", ""] + [f"- {a}" for a in r.avisos] + [""]
    if r.suspeitos:
        L += [f"### ⚠️ Variações suspeitas (mais de {lim['variacao_suspeita']:.0%})", "",
              "| Produto | Loja | Antes | Agora | Var. | Produto escolhido |", "|---|---|---:|---:|---:|---|"]
        for s in r.suspeitos:
            escolhido = (f"{s['nome_antes']} → **{s['nome_depois']}**" if s["trocou"] else s["nome_depois"])
            if s["url"]:
                escolhido += f" ([ver]({s['url']}))"
            L.append(f"| {s['produto']} | {s['loja']} | {_eur(s['antes'])}/{s['unidade']} | "
                     f"{_eur(s['depois'])}/{s['unidade']} | {_pct(s['variacao'])} | {escolhido} |")
        L += ["", "Uma variação grande é quase sempre uma troca de produto ou um erro de leitura. "
              "Confirme no link; se o produto escolhido não for o pretendido, ajuste `incluir`/`excluir` "
              "ou fixe o produto com `fixo` em `cabaz.toml`.", ""]
    if r.trocas:
        L += ["### 🔄 Trocas de produto (sem variação suspeita)", ""]
        for t in r.trocas:
            L.append(f"- **{t['produto']}** @ {t['loja']}: {t['nome_antes']} → {t['nome_depois']} "
                     f"({_eur(t['antes'])} → {_eur(t['depois'])}/{t['unidade']}, {_pct(t['variacao'])})")
        L.append("")
    if not (r.criticos or r.avisos or r.suspeitos or r.trocas):
        L.append("✅ Sem problemas.")
    return "\n".join(L).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    from .agente import carregar_cabaz, ler_historico
    from .lojas import LOJAS, PARCIAIS

    ap = argparse.ArgumentParser(description="Verifica a qualidade da última recolha.")
    ap.add_argument("--saida", type=Path, help="pasta onde escrever issue.md e resultado.json")
    ap.add_argument("--data", help="data a verificar (por omissão a mais recente)")
    a = ap.parse_args(argv)

    limites = carregar_limites()
    r = verificar(ler_historico(), carregar_cabaz(), list(LOJAS), limites, a.data, PARCIAIS)
    texto = markdown(r, limites)
    print(texto)

    if a.saida:
        a.saida.mkdir(parents=True, exist_ok=True)
        (a.saida / "issue.md").write_text(texto, encoding="utf-8")
        (a.saida / "resultado.json").write_text(
            json.dumps({**asdict(r), "cobertura": r.cobertura}, ensure_ascii=False, indent=2), encoding="utf-8")
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"data={r.data}\n")
            f.write(f"critico={'true' if r.criticos else 'false'}\n")
            f.write(f"suspeito={'true' if (r.suspeitos or r.avisos) else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
