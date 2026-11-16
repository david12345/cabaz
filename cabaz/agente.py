"""Agente diário: recolhe os preços do cabaz e atualiza o histórico e o relatório.

Uso:
    python -m cabaz.agente              # recolhe hoje + gera relatório
    python -m cabaz.agente --so-relatorio
    python -m cabaz.agente --lojas continente auchan --produtos leite
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
import sys
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

from .lojas import LOJAS, Oferta, normalizar
from . import relatorio

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "cabaz.toml"
CSV = RAIZ / "data" / "precos.csv"
CAMPOS = ["data", "produto", "loja", "pid", "nome_loja", "preco", "preco_unidade",
          "unidade", "quantidade_ref", "custo_ref", "promocao", "url"]

log = logging.getLogger("cabaz")


def carregar_cabaz(caminho: Path = CONFIG) -> list[dict]:
    with open(caminho, "rb") as f:
        produtos = tomllib.load(f)["produto"]
    for p in produtos:
        p.setdefault("incluir", [])
        p.setdefault("excluir", [])
        p.setdefault("fixo", {})
        p.setdefault("quantidade", 12 if p["unidade"] == "un" else 1)
    return produtos


def _contem(nome: str, termo: str) -> bool:
    """Termo aparece no início de uma palavra (permite prefixos como 'congelad')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalizar(termo)), nome) is not None


def corresponde(oferta: Oferta, produto: dict) -> bool:
    nome = normalizar(oferta.nome)
    return (
        all(_contem(nome, t) for t in produto["incluir"])
        and not any(_contem(nome, t) for t in produto["excluir"])
        and oferta.unidade == produto["unidade"]
        and oferta.preco_unidade
        and oferta.preco_unidade > 0
    )


def escolher(ofertas: list[Oferta], produto: dict, loja: str) -> Oferta | None:
    pid_fixo = str(produto["fixo"].get(loja, "")) or None
    if pid_fixo:
        for o in ofertas:
            if o.pid == pid_fixo:
                return o
        return None
    validas = [o for o in ofertas if corresponde(o, produto)]
    return min(validas, key=lambda o: (o.preco_unidade, o.preco), default=None)


def recolher(produtos: list[dict], lojas: list[str], data: str) -> tuple[list[dict], list[str]]:
    linhas, falhas = [], []
    clientes = {n: LOJAS[n]() for n in lojas}
    for p in produtos:
        for nome_loja, cliente in clientes.items():
            pid_fixo = str(p["fixo"].get(nome_loja, "")) or None
            try:
                ofertas = cliente.pesquisar(p["procura"])
                o = escolher(ofertas, p, nome_loja)
                if o is None and pid_fixo:  # produto fixo fora dos resultados: pesquisar pelo código
                    o = escolher(cliente.pesquisar(pid_fixo), p, nome_loja)
            except Exception as e:
                log.warning("%s", e)
                falhas.append(f"{p['nome']} @ {nome_loja}: erro ({e.__class__.__name__})")
                continue
            if o is None:
                log.warning("sem correspondência: %s @ %s", p["nome"], nome_loja)
                falhas.append(f"{p['nome']} @ {nome_loja}: sem correspondência")
                continue
            log.info("%-26s %-10s %6.2f€ %7.2f€/%-2s %s", p["nome"], nome_loja, o.preco,
                     o.preco_unidade, o.unidade, o.nome)
            linhas.append({
                "data": data, "produto": p["nome"], "loja": nome_loja, "pid": o.pid,
                "nome_loja": o.nome, "preco": f"{o.preco:.2f}",
                "preco_unidade": f"{o.preco_unidade:.4f}", "unidade": o.unidade,
                "quantidade_ref": p["quantidade"],
                "custo_ref": f"{o.preco_unidade * p['quantidade']:.4f}",
                "promocao": int(o.promocao), "url": o.url,
            })
    return linhas, falhas


def ler_historico(caminho: Path = CSV) -> list[dict]:
    if not caminho.exists():
        return []
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def gravar_historico(novas: list[dict], caminho: Path = CSV) -> None:
    """Substitui as linhas do mesmo dia/produto/loja (execução idempotente)."""
    chaves = {(l["data"], l["produto"], l["loja"]) for l in novas}
    antigas = [l for l in ler_historico(caminho) if (l["data"], l["produto"], l["loja"]) not in chaves]
    todas = sorted(antigas + novas, key=lambda l: (l["data"], l["produto"], l["loja"]))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        w.writeheader()
        w.writerows(todas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lojas", nargs="+", default=list(LOJAS), choices=list(LOJAS))
    ap.add_argument("--produtos", nargs="+", help="filtrar produtos (texto no nome)")
    ap.add_argument("--data", help="data a registar (AAAA-MM-DD); por omissão hoje em Lisboa")
    ap.add_argument("--so-relatorio", action="store_true", help="não recolhe, só regenera o relatório")
    ap.add_argument("--sem-gravar", action="store_true", help="recolhe e mostra, sem gravar")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = a.data or dt.datetime.now(ZoneInfo("Europe/Lisbon")).date().isoformat()
    falhas: list[str] = []
    if not a.so_relatorio:
        produtos = carregar_cabaz()
        if a.produtos:
            filtros = [normalizar(x) for x in a.produtos]
            produtos = [p for p in produtos if any(f in normalizar(p["nome"]) for f in filtros)]
        linhas, falhas = recolher(produtos, a.lojas, data)
        total = len(produtos) * len(a.lojas)
        log.info("\n%d/%d preços recolhidos.", len(linhas), total)
        if a.sem_gravar:
            return 0
        if not linhas:
            log.error("Nenhum preço recolhido — histórico não alterado.")
            return 1
        gravar_historico(linhas)

    relatorio.gerar(ler_historico(), carregar_cabaz(), falhas)
    log.info("Relatório atualizado: RELATORIO.md, docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
