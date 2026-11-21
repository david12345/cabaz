"""Vários cabazes: filtro `comeca` e geração de um relatório/página por cabaz."""
import tempfile
import unittest
from pathlib import Path

from cabaz import relatorio
from cabaz.agente import corresponde
from cabaz.lojas import Oferta


class TestComeca(unittest.TestCase):
    produto = {"incluir": ["salsa"], "excluir": [], "unidade": "kg", "comeca": "salsa"}

    def o(self, nome):
        return Oferta("x", "1", nome, 1.0, 1.0, "kg", "")

    def test_nome_tem_de_comecar_pela_palavra(self):
        self.assertTrue(corresponde(self.o("Salsa Fresca Continente (emb. 50 gr)"), self.produto))
        self.assertTrue(corresponde(self.o("SALSA FRESCA KG PRODUTO LOCAL"), self.produto))
        self.assertFalse(corresponde(self.o("Comida Húmida para Cão Frango e Salsa"), self.produto))
        self.assertFalse(corresponde(self.o("ROTI LOMBO COM SALSA LIMÃO E BACON KG"), self.produto))


class TestGerarPorCabaz(unittest.TestCase):
    def test_um_relatorio_e_uma_pagina_por_cabaz(self):
        produtos = [
            {"nome": "Leite", "unidade": "L", "quantidade": 1, "cabaz": "base"},
            {"nome": "Gin", "unidade": "L", "quantidade": 1, "cabaz": "extra"},
        ]
        hist = [{"data": "2026-11-21", "produto": p["nome"], "loja": l, "pid": "1", "nome_loja": p["nome"],
                 "preco": "1.00", "preco_unidade": "1.0", "unidade": "L", "custo_ref": "1.0",
                 "promocao": "0", "url": ""}
                for p in produtos for l in ("continente", "pingodoce", "auchan")]
        antes = relatorio.RAIZ
        with tempfile.TemporaryDirectory() as d:
            relatorio.RAIZ = Path(d)
            try:
                relatorio.gerar(hist, produtos, ["Gin @ auchan: sem correspondência"],
                                {"base": "Cabaz base", "extra": "Cabaz extra"})
            finally:
                relatorio.RAIZ = antes
            base = (Path(d) / "RELATORIO.md").read_text()
            extra = (Path(d) / "RELATORIO-extra.md").read_text()
            self.assertTrue((Path(d) / "docs" / "index.html").exists())
            self.assertTrue((Path(d) / "docs" / "extra.html").exists())
        self.assertIn("# Cabaz base", base)
        self.assertIn("Leite", base)
        self.assertNotIn("| Gin", base)
        self.assertIn("# Cabaz extra", extra)
        self.assertIn("Gin", extra)
        self.assertNotIn("| Leite", extra)
        self.assertIn("sem correspondência", extra)   # aviso do próprio cabaz
        self.assertNotIn("sem correspondência", base)
        self.assertIn("[Cabaz extra](RELATORIO-extra.md)", base)


if __name__ == "__main__":
    unittest.main()
