"""Várias execuções por dia: recolher só o que falta, desistir de lojas bloqueadas
e verificar só o que cada execução trouxe."""
import unittest

from cabaz.agente import ja_recolhidos, recolher
from cabaz.lojas import Bloqueado, Oferta
from cabaz.verificacao import verificar_execucao

PRODUTOS = [{"nome": f"P{i}", "procura": f"p{i}", "incluir": [], "excluir": [], "fixo": {},
             "unidade": "kg", "quantidade": 1} for i in range(5)]


def linha(data, prod, loja, pu=1.0, pid="1"):
    return {"data": data, "produto": prod, "loja": loja, "pid": pid, "nome_loja": "x",
            "preco_unidade": str(pu), "unidade": "kg", "url": ""}


class ClienteFalso:
    def __init__(self, bloqueia=False):
        self.bloqueia, self.pedidos = bloqueia, 0

    def pesquisar(self, termo):
        self.pedidos += 1
        if self.bloqueia:
            raise Bloqueado("bloqueado")
        return [Oferta("x", "1", termo, 1.0, 1.0, "kg", "")]


class TestRecolher(unittest.TestCase):
    def test_desiste_de_loja_bloqueada(self):
        ok, mau = ClienteFalso(), ClienteFalso(bloqueia=True)
        linhas, falhas = recolher(PRODUTOS, ["a", "b"], "2026-11-21", clientes={"a": ok, "b": mau})
        self.assertEqual(len(linhas), 5)
        self.assertEqual(mau.pedidos, 2)  # desiste ao fim de 2 bloqueios seguidos
        self.assertEqual(len(falhas), 1)
        self.assertIn("bloqueou", falhas[0])

    def test_salta_o_que_ja_tem(self):
        c = ClienteFalso()
        linhas, _ = recolher(PRODUTOS, ["a"], "2026-11-21", ja_tem={("P0", "a"), ("P1", "a")}, clientes={"a": c})
        self.assertEqual(sorted(l["produto"] for l in linhas), ["P2", "P3", "P4"])
        self.assertEqual(c.pedidos, 3)


class TestJaRecolhidos(unittest.TestCase):
    def test_so_conta_o_proprio_dia(self):
        hist = [linha("2026-11-21", "P0", "continente"), linha("2026-11-20", "P2", "continente")]
        self.assertEqual(ja_recolhidos(hist, "2026-11-21"), {("P0", "continente")})


class TestVerificarExecucao(unittest.TestCase):
    LOJAS = ["continente", "auchan"]

    def dia(self, data, lojas, pu=1.0):
        return [linha(data, p["nome"], l, pu) for p in PRODUTOS for l in lojas]

    def test_dia_incompleto_e_so_aviso(self):
        hist = self.dia("2026-11-20", self.LOJAS) + self.dia("2026-11-21", ["auchan"])
        reg = {"data": "2026-11-21", "novos": [[p["nome"], "auchan"] for p in PRODUTOS], "fechar": "2026-11-20"}
        r = verificar_execucao(hist, PRODUTOS, self.LOJAS, reg)
        self.assertEqual(r.criticos, [])  # o dia 20 estava completo
        self.assertTrue(any("ainda incompleta" in a for a in r.avisos))

    def test_dia_anterior_incompleto_e_critico(self):
        hist = self.dia("2026-11-20", ["auchan"]) + self.dia("2026-11-21", self.LOJAS)
        reg = {"data": "2026-11-21", "novos": [[p["nome"], l] for p in PRODUTOS for l in self.LOJAS],
               "fechar": "2026-11-20"}
        r = verificar_execucao(hist, PRODUTOS, self.LOJAS, reg)
        self.assertTrue(r.criticos)
        self.assertTrue(all(c.startswith("O dia 2026-11-20 terminou incompleto") for c in r.criticos))

    def test_so_alerta_variacoes_dos_precos_novos(self):
        hist = self.dia("2026-11-20", self.LOJAS) + self.dia("2026-11-21", self.LOJAS, pu=2.0)
        reg = {"data": "2026-11-21", "novos": [["P0", "continente"]], "fechar": None}
        r = verificar_execucao(hist, PRODUTOS, self.LOJAS, reg)
        self.assertEqual([(s["produto"], s["loja_id"]) for s in r.suspeitos], [("P0", "continente")])

    def test_execucao_sem_novidades_nao_alerta(self):
        hist = self.dia("2026-11-20", self.LOJAS) + self.dia("2026-11-21", ["auchan"], pu=2.0)
        r = verificar_execucao(hist, PRODUTOS, self.LOJAS, {"data": "2026-11-21", "novos": [], "fechar": None})
        self.assertEqual((r.criticos, r.avisos, r.suspeitos), ([], [], []))


if __name__ == "__main__":
    unittest.main()
