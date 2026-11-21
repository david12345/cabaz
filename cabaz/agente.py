"""Agente diário: recolhe os preços do cabaz e atualiza o histórico e o relatório.

Uso:
    python -m cabaz.agente              # recolhe hoje + gera relatório
    python -m cabaz.agente --so-relatorio
    python -m cabaz.agente --lojas continente auchan --produtos leite
    python -m cabaz.agente --so-em-falta   # só o que ainda falta hoje (repetições no mesmo dia)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import logging
import re
import sys
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

from .lojas import LOJAS, Bloqueado, Oferta, normalizar
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
        p.setdefault("cabaz", "base")
        p.setdefault("quantidade", 12 if p["unidade"] == "un" else 1)
    return produtos


def carregar_cabazes(caminho: Path = CONFIG) -> dict[str, str]:
    """id -> título dos cabazes, pela ordem do ficheiro (o primeiro é o principal)."""
    with open(caminho, "rb") as f:
        return tomllib.load(f).get("cabazes") or {"base": "Cabaz de alimentos base"}


def _contem(nome: str, termo: str) -> bool:
    """Termo aparece no início de uma palavra (permite prefixos como 'congelad')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalizar(termo)), nome) is not None


def corresponde(oferta: Oferta, produto: dict) -> bool:
    nome = normalizar(oferta.nome)
    return (
        all(_contem(nome, t) for t in produto["incluir"])
        and (not produto.get("comeca") or nome.startswith(normalizar(produto["comeca"])))
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


BLOQUEIOS_PARA_DESISTIR = 2


def recolher(produtos: list[dict], lojas: list[str], data: str,
             ja_tem: set[tuple[str, str]] = frozenset(),
             clientes: dict | None = None) -> tuple[list[dict], list[str]]:
    """Recolhe os preços. `ja_tem`: pares (produto, loja) a saltar (já recolhidos hoje).

    Se uma loja bloquear (403/429) duas pesquisas seguidas, desiste-se dessa loja
    nesta execução: do mesmo IP continuaria bloqueada e só se perderia tempo."""
    linhas, falhas = [], []
    clientes = clientes or {n: LOJAS[n]() for n in lojas}
    bloqueios = {n: 0 for n in clientes}
    desistiu: set[str] = set()
    for p in produtos:
        for nome_loja, cliente in clientes.items():
            if (p["nome"], nome_loja) in ja_tem or nome_loja in desistiu:
                continue
            pid_fixo = str(p["fixo"].get(nome_loja, "")) or None
            try:
                ofertas = cliente.pesquisar(p["procura"])
                o = escolher(ofertas, p, nome_loja)
                if o is None and pid_fixo:  # produto fixo fora dos resultados: pesquisar pelo código
                    o = escolher(cliente.pesquisar(pid_fixo), p, nome_loja)
                bloqueios[nome_loja] = 0
            except Bloqueado as e:
                log.warning("%s", e)
                bloqueios[nome_loja] += 1
                if bloqueios[nome_loja] >= BLOQUEIOS_PARA_DESISTIR:
                    desistiu.add(nome_loja)
                    log.warning("%s: %d bloqueios seguidos — loja ignorada nesta execução.",
                                nome_loja, BLOQUEIOS_PARA_DESISTIR)
                    falhas.append(f"{nome_loja}: bloqueou o acesso (HTTP 403/429); "
                                  "nova tentativa na próxima execução")
                continue
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


def ja_recolhidos(historico: list[dict], data: str) -> set[tuple[str, str]]:
    """Pares (produto, loja) que já têm preço em `data` e não é preciso recolher outra vez."""
    return {(l["produto"], l["loja"]) for l in historico if l["data"] == data}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lojas", nargs="+", default=list(LOJAS), choices=list(LOJAS))
    ap.add_argument("--produtos", nargs="+", help="filtrar produtos (texto no nome)")
    ap.add_argument("--data", help="data a registar (AAAA-MM-DD); por omissão hoje em Lisboa")
    ap.add_argument("--so-relatorio", action="store_true", help="não recolhe, só regenera o relatório")
    ap.add_argument("--sem-gravar", action="store_true", help="recolhe e mostra, sem gravar")
    ap.add_argument("--so-em-falta", action="store_true",
                    help="recolhe só o que ainda não tem preço hoje (para várias execuções por dia)")
    ap.add_argument("--registo", type=Path,
                    help="ficheiro JSON onde registar o que foi recolhido (usado pela verificação)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = a.data or dt.datetime.now(ZoneInfo("Europe/Lisbon")).date().isoformat()
    falhas: list[str] = []
    if not a.so_relatorio:
        produtos = carregar_cabaz()
        if a.produtos:
            filtros = [normalizar(x) for x in a.produtos]
            produtos = [p for p in produtos if any(f in normalizar(p["nome"]) for f in filtros)]
        historico = ler_historico()
        primeira = not any(l["data"] == data for l in historico)
        ja_tem = ja_recolhidos(historico, data) if a.so_em_falta else set()
        pedidos = [(p["nome"], l) for p in produtos for l in a.lojas if (p["nome"], l) not in ja_tem]
        if not pedidos:
            log.info("Recolha de %s já completa — nada a fazer.", data)
            _registar(a.registo, data, [], None)
            return 0
        if ja_tem:
            log.info("A recolher só o que falta em %s: %d pares.\n", data, len(pedidos))
        linhas, falhas = recolher(produtos, a.lojas, data, ja_tem)
        log.info("\n%d/%d preços recolhidos.", len(linhas), len(pedidos))
        if a.sem_gravar:
            return 0
        if not linhas:
            log.error("Nenhum preço recolhido — histórico não alterado.")
            return 1
        gravar_historico(linhas)
        # primeira recolha do dia: o dia anterior com dados fica "fechado" e é verificado
        anteriores = sorted({l["data"] for l in historico if l["data"] < data})
        fechar = anteriores[-1] if primeira and anteriores else None
        _registar(a.registo, data, [(l["produto"], l["loja"]) for l in linhas], fechar)

    relatorio.gerar(ler_historico(), carregar_cabaz(), falhas, carregar_cabazes())
    log.info("Relatórios atualizados: RELATORIO*.md, docs/*.html")
    return 0


def _registar(caminho: Path | None, data: str, novos: list[tuple[str, str]], fechar: str | None) -> None:
    if caminho:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps({"data": data, "novos": novos, "fechar": fechar},
                                      ensure_ascii=False), encoding="utf-8")
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"novos={len(novos)}\n")


if __name__ == "__main__":
    sys.exit(main())
