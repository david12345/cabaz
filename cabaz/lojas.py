"""Leitura de resultados de pesquisa dos supermercados online portugueses.

Cada loja devolve uma lista de `Oferta` com preço de venda e preço por
unidade normalizado (€/kg, €/L ou €/un).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class Oferta:
    loja: str
    pid: str
    nome: str
    preco: float  # preço de venda (€)
    preco_unidade: float | None  # €/unidade normalizada
    unidade: str | None  # "kg", "L" ou "un"
    url: str
    promocao: bool = False


def normalizar(texto: str) -> str:
    """minúsculas, sem acentos, espaços simples."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("-", " ")
    return re.sub(r"\s+", " ", t).strip()


def _num(texto: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", (texto or "").replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None


_UNIDADES = {
    "kg": ("kg", 1), "kgr": ("kg", 1), "g": ("kg", 1000), "gr": ("kg", 1000),
    "l": ("L", 1), "lt": ("L", 1), "ltr": ("L", 1), "cl": ("L", 100), "ml": ("L", 1000),
    "un": ("un", 1), "unid": ("un", 1), "uni": ("un", 1), "unidade": ("un", 1),
    "dz": ("un", 1 / 12), "duzia": ("un", 1 / 12),
}


def preco_por_unidade(texto: str) -> tuple[float | None, str | None]:
    """'0,90€/lt' -> (0.90, 'L'); '12,50 €/Kg' -> (12.5, 'kg'); '2,40€/dz' -> (0.2, 'un')."""
    t = normalizar(texto).replace(" ", "")
    m = re.search(r"(\d+(?:[.,]\d+)?)€?/(kgr?|gr?|ltr?|l|cl|ml|dz|duzia|unidade|unid|uni|un)", t)
    if not m:
        return None, None
    valor = float(m.group(1).replace(",", "."))
    unidade = _UNIDADES.get(m.group(2))
    if not unidade:
        return None, None
    nome, fator = unidade
    # fator: quantas unidades de origem cabem numa unidade normalizada
    return round(valor * fator, 4), nome


def quantidade_embalagem(nome: str) -> tuple[float | None, str | None]:
    """Quantidade total na embalagem a partir do nome.

    'emb. 6 x 1 lt' -> (6, 'L'); '500 gr' -> (0.5, 'kg'); '6X1L' -> (6, 'L');
    'emb. 12 un' -> (12, 'un'); 'dúzia' -> (12, 'un').
    """
    t = normalizar(nome)
    m = re.search(r"(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*(kg|gr?|lt?|cl|ml)\b", t)
    mult = 1.0
    if m:
        mult = float(m.group(1))
        valor, uni = m.group(2), m.group(3)
    else:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|gr?|lt?|cl|ml|un|unid|uni)\b", t)
        if not m:
            return (12.0, "un") if "duzia" in t else (None, None)
        valor, uni = m.group(1), m.group(2)
    nome_un, fator = _UNIDADES[uni]
    return round(mult * float(valor.replace(",", ".")) / fator, 4), nome_un


class Bloqueado(RuntimeError):
    """A loja recusou o pedido (HTTP 403/429): bloqueio anti-robô, normalmente pelo
    endereço IP. Repetir do mesmo IP não ajuda, por isso não se tenta de novo."""


class Loja:
    nome = ""
    base = ""
    # Loja parcial: não tem o catálogo completo online. Aparece nas tabelas e na
    # evolução por produto, mas fica fora dos totais do cabaz, do "melhor preço"
    # e do alerta de cobertura.
    parcial = False

    def __init__(self, sessao: requests.Session | None = None, pausa: float = 1.5):
        self.s = sessao or requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
        self.pausa = pausa

    def url_pesquisa(self, termo: str) -> str:
        raise NotImplementedError

    def interpretar(self, html: str) -> list[Oferta]:
        raise NotImplementedError

    def pesquisar(self, termo: str, tentativas: int = 3) -> list[Oferta]:
        url = self.url_pesquisa(termo)
        erro: Exception | None = None
        for i in range(tentativas):
            try:
                r = self.s.get(url, timeout=40)
                if r.status_code in (403, 429):
                    raise Bloqueado(f"{self.nome}: bloqueado (HTTP {r.status_code}) em '{termo}'")
                r.raise_for_status()
                time.sleep(self.pausa)
                ofertas = self.interpretar(r.text)
                for o in ofertas:  # completar €/unidade a partir da embalagem
                    if o.preco_unidade is None:
                        q, un = quantidade_embalagem(o.nome)
                        if q:
                            o.preco_unidade, o.unidade = round(o.preco / q, 4), un
                return ofertas
            except Bloqueado:
                raise
            except Exception as e:  # rede ou HTML inesperado
                erro = e
                time.sleep(3 * (i + 1))
        raise RuntimeError(f"{self.nome}: falhou '{termo}': {erro}")


class Continente(Loja):
    nome = "continente"
    base = "https://www.continente.pt"

    def url_pesquisa(self, termo):
        return f"{self.base}/pesquisa/?q={quote_plus(termo)}&pmin=0.01&sz=48"

    def interpretar(self, html):
        sopa = BeautifulSoup(html, "lxml")
        ofertas = []
        for tile in sopa.select(".product-tile[data-product-tile-impression]"):
            try:
                info = json.loads(tile["data-product-tile-impression"])
            except (ValueError, KeyError):
                continue
            preco = _num(str(info.get("price")))
            if not preco:
                continue
            prim = tile.select_one(".pwc-tile--price-primary")
            sec = tile.select_one(".pwc-tile--price-secondary")
            pu, un = preco_por_unidade(prim.get_text(" ", strip=True) if prim else "")
            if un in ("kg", "L"):  # vendido ao peso: o preço principal já é €/kg
                pu = preco
            else:
                pu, un = preco_por_unidade(sec.get_text(" ", strip=True) if sec else "")
            emb = tile.select_one(".pwc-tile--quantity")
            nome = info.get("name", "")
            if emb:
                nome = f"{nome} ({emb.get_text(' ', strip=True)})"
            link = tile.select_one("a[href*='/produto/']")
            ofertas.append(Oferta(
                loja=self.nome, pid=str(info.get("id")), nome=nome, preco=preco,
                preco_unidade=pu, unidade=un,
                url=urljoin(self.base, link["href"]) if link else "",
                promocao=bool(tile.select_one(".ct-product-tile-badge--promotional, .pwc-discount-amount")),
            ))
        return ofertas


class Auchan(Loja):
    nome = "auchan"
    base = "https://www.auchan.pt"

    def url_pesquisa(self, termo):
        return f"{self.base}/pt/pesquisa?q={quote_plus(termo)}&sz=48"

    def interpretar(self, html):
        sopa = BeautifulSoup(html, "lxml")
        ofertas = []
        for tile in sopa.select(".product-tile[data-gtm]"):
            try:
                info = json.loads(tile["data-gtm"])
            except (ValueError, KeyError):
                continue
            preco = _num(str(info.get("price")))
            if not preco:
                continue
            prim = tile.select_one(".auc-product-tile__prices .price, .price")
            _, un = preco_por_unidade(prim.get_text(" ", strip=True) if prim else "")
            if un in ("kg", "L"):  # vendido ao peso: o preço já é €/kg
                pu = preco
            else:
                pu_el = tile.select_one(".auc-measures--price-per-unit")
                pu, un = preco_por_unidade(pu_el.get_text(" ", strip=True) if pu_el else "")
            url = ""
            try:
                url = json.loads(tile.get("data-urls", "{}")).get("absoluteProductUrl", "")
            except ValueError:
                pass
            ofertas.append(Oferta(
                loja=self.nome, pid=str(info.get("id")), nome=info.get("name", ""),
                preco=preco, preco_unidade=pu, unidade=un, url=url,
                promocao=bool(tile.select_one(".auc-price__stricked")),
            ))
        return ofertas


class PingoDoce(Loja):
    nome = "pingodoce"
    base = "https://www.pingodoce.pt"

    def url_pesquisa(self, termo):
        return (f"{self.base}/on/demandware.store/Sites-pingo-doce-Site/default/"
                f"Search-Show?q={quote_plus(termo)}&sz=48")

    def interpretar(self, html):
        sopa = BeautifulSoup(html, "lxml")
        ofertas = []
        for prod in sopa.select("div.product[data-pid]"):
            preco_el = prod.select_one(".product-price")
            preco = _num(preco_el.get_text(" ", strip=True)) if preco_el else None
            if not preco:
                continue
            nome_el = prod.select_one(".product-name-link a, .pdp-link a, a.link") or prod.select_one("a:not(.product-tile-image-link)")
            nome = nome_el.get_text(" ", strip=True) if nome_el else ""
            marca = prod.select_one(".product-brand-name, .product-brand")
            unid = prod.select_one(".product-unit")
            pu, un = preco_por_unidade(preco_el.get_text(" ", strip=True))
            if un in ("kg", "L"):  # vendido ao peso: o preço já é €/kg
                pu = preco
            else:
                pu, un = (None, None)
            if unid and pu is None:
                txt = unid.get_text(" ", strip=True)
                pu, un = preco_por_unidade(txt)
                qtd = re.match(r"\s*(\d+[.,]\d+)\s*un\b", normalizar(txt))
                if un == "un" and qtd:  # '0.4 Un | 17,45 €/Un' = embalagem ao peso (kg)
                    un = "kg"
            partes = [nome]
            if marca:
                partes.append(marca.get_text(" ", strip=True))
            if unid:
                extra = re.sub(r"\s*\d+[.,]?\d*\s*€.*$", "", unid.get_text(" ", strip=True).split("|")[0]).strip()
                if extra:
                    partes.append(f"({extra})")
            link = prod.select_one("a[href]")
            ofertas.append(Oferta(
                loja=self.nome, pid=prod["data-pid"], nome=" ".join(partes),
                preco=preco, preco_unidade=pu, unidade=un,
                url=urljoin(self.base, link["href"]) if link else "",
                promocao=bool(prod.select_one(".strike-through, .promo-message")),
            ))
        return ofertas


class Lidl(Loja):
    """Lidl Portugal: não tem loja online de alimentação. A API de pesquisa do
    site só devolve produtos em destaque (folheto/promoções da semana) e alguns
    permanentes, por isso a cobertura do cabaz é parcial e varia de semana para semana."""

    nome = "lidl"
    base = "https://www.lidl.pt"
    parcial = True

    def url_pesquisa(self, termo):
        return (f"{self.base}/q/api/search?q={quote_plus(termo)}"
                "&assortment=PT&locale=pt_PT&version=v2.0.0&fetchsize=48")

    def interpretar(self, html):
        try:
            dados = json.loads(html)
        except ValueError:
            return []
        ofertas = []
        for item in dados.get("items", []):
            g = (item.get("gridbox") or {}).get("data") or {}
            pr = g.get("price") or {}
            preco = pr.get("price")
            if not preco:
                continue
            emb = (pr.get("packaging") or {}).get("text") or ""
            base = (pr.get("basePrice") or {}).get("text") or ""  # "1 kg = 9,98"
            pu, un = None, None
            m = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(kg|g|l|ml|un)\w*\s*=\s*(\d+(?:[.,]\d+)?)", normalizar(base))
            if m and m.group(2) in _UNIDADES:
                nome_un, fator = _UNIDADES[m.group(2)]
                qtd = float((m.group(1) or "1").replace(",", ".")) / fator
                pu, un = round(float(m.group(3).replace(",", ".")) / qtd, 4), nome_un
            elif re.search(r"\b(por|ao) kg\b|/\s*kg|^kg$", normalizar(emb)):
                pu, un = float(preco), "kg"
            titulo = g.get("fullTitle") or g.get("title") or ""
            ofertas.append(Oferta(
                loja=self.nome, pid=str(g.get("productId") or g.get("erpNumber") or item.get("code")),
                nome=f"{titulo} ({emb})" if emb else titulo, preco=float(preco),
                preco_unidade=pu, unidade=un,
                url=urljoin(self.base, g.get("canonicalUrl") or ""),
                promocao=bool((pr.get("discount") or {}).get("showDiscount")),
            ))
        return ofertas


LOJAS = {c.nome: c for c in (Continente, PingoDoce, Auchan, Lidl)}
PARCIAIS = {n for n, c in LOJAS.items() if c.parcial}
NOMES = {"continente": "Continente", "pingodoce": "Pingo Doce", "auchan": "Auchan", "lidl": "Lidl"}
