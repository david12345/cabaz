import unittest

from cabaz.verificacao import markdown, verificar

PRODUTOS = [{"nome": f"P{i}"} for i in range(10)]
LOJAS = ["continente", "pingodoce", "auchan"]


def linha(data, prod, loja, pu, pid="1", nome="Produto"):
    return {"data": data, "produto": prod, "loja": loja, "pid": pid, "nome_loja": nome,
            "preco_unidade": str(pu), "unidade": "kg", "url": ""}


def dia(data, pu=1.0, sem=()):
    return [linha(data, p["nome"], l, pu) for p in PRODUTOS for l in LOJAS if (p["nome"], l) not in sem]


class TestVerificacao(unittest.TestCase):
    def test_dia_normal(self):
        r = verificar(dia("2026-11-16") + dia("2026-11-17", 1.05), PRODUTOS, LOJAS)
        self.assertEqual((r.criticos, r.suspeitos, r.trocas), ([], [], []))
        self.assertEqual(r.anterior, "2026-11-16")
        self.assertIn("Sem problemas", markdown(r))

    def test_loja_sem_precos_e_critico(self):
        sem = {(p["nome"], "auchan") for p in PRODUTOS}
        r = verificar(dia("2026-11-17", sem=sem), PRODUTOS, LOJAS)
        self.assertTrue(any("Auchan" in c for c in r.criticos))
        self.assertTrue(any("Cobertura" in c for c in r.criticos))

    def test_cobertura_baixa_e_critica(self):
        sem = {("P0", "continente"), ("P1", "pingodoce"), ("P2", "auchan"), ("P3", "auchan")}  # 26/30 = 87%
        r = verificar(dia("2026-11-17", sem=sem), PRODUTOS, LOJAS)
        self.assertEqual(len(r.criticos), 1)
        self.assertIn("26 de 30", r.criticos[0])

    def test_cobertura_no_limite_nao_e_critica(self):
        sem = {("P0", "continente"), ("P1", "pingodoce"), ("P2", "auchan")}  # 27/30 = 90%
        self.assertEqual(verificar(dia("2026-11-17", sem=sem), PRODUTOS, LOJAS).criticos, [])

    def test_salto_de_preco_e_suspeito(self):
        hoje = dia("2026-11-17")
        hoje[0] = linha("2026-11-17", "P0", "continente", 1.5)  # +50%
        hoje[1] = linha("2026-11-17", "P0", "pingodoce", 0.6)   # -40%
        hoje[2] = linha("2026-11-17", "P0", "auchan", 1.25)     # +25%, abaixo do limite
        r = verificar(dia("2026-11-16") + hoje, PRODUTOS, LOJAS)
        self.assertEqual([(s["loja"], round(s["variacao"], 2)) for s in r.suspeitos],
                         [("Continente", 0.5), ("Pingo Doce", -0.4)])
        self.assertEqual(r.criticos, [])

    def test_limite_configuravel(self):
        hoje = dia("2026-11-17")
        hoje[0] = linha("2026-11-17", "P0", "continente", 1.25)
        r = verificar(dia("2026-11-16") + hoje, PRODUTOS, LOJAS, {"variacao_suspeita": 0.2})
        self.assertEqual(len(r.suspeitos), 1)

    def test_troca_de_produto(self):
        hoje = dia("2026-11-17")
        hoje[0] = linha("2026-11-17", "P0", "continente", 1.02, pid="2", nome="Outra marca")
        hoje[1] = linha("2026-11-17", "P0", "pingodoce", 2.0, pid="9", nome="Polpa")
        r = verificar(dia("2026-11-16") + hoje, PRODUTOS, LOJAS)
        self.assertEqual([t["nome_depois"] for t in r.trocas], ["Outra marca"])
        self.assertTrue(r.suspeitos[0]["trocou"])
        self.assertIn("**Polpa**", markdown(r))

    def test_compara_com_ultima_recolha_mesmo_com_dias_em_falta(self):
        r = verificar(dia("2026-11-10") + dia("2026-11-17", 2.0), PRODUTOS, LOJAS)
        self.assertEqual(r.anterior, "2026-11-10")
        self.assertEqual(len(r.suspeitos), 30)

    def test_primeiro_dia_sem_comparacao(self):
        r = verificar(dia("2026-11-16"), PRODUTOS, LOJAS)
        self.assertIsNone(r.anterior)
        self.assertEqual((r.criticos, r.suspeitos), ([], []))


if __name__ == "__main__":
    unittest.main()


class TestLojaParcial(unittest.TestCase):
    LOJAS4 = LOJAS + ["lidl"]

    def test_parcial_nao_conta_para_cobertura(self):
        poucos = [linha("2026-11-17", "P0", "lidl", 1.0)]
        r = verificar(dia("2026-11-17") + poucos, PRODUTOS, self.LOJAS4, parciais={"lidl"})
        self.assertEqual((r.recolhidos, r.esperados, r.criticos, r.avisos), (30, 30, [], []))

    def test_parcial_sem_precos_e_so_aviso(self):
        r = verificar(dia("2026-11-17"), PRODUTOS, self.LOJAS4, parciais={"lidl"})
        self.assertEqual(r.criticos, [])
        self.assertEqual(len(r.avisos), 1)
        self.assertIn("Lidl", r.avisos[0])

    def test_parcial_entra_nas_variacoes(self):
        ontem = dia("2026-11-16") + [linha("2026-11-16", "P0", "lidl", 1.0)]
        hoje = dia("2026-11-17") + [linha("2026-11-17", "P0", "lidl", 2.0)]
        r = verificar(ontem + hoje, PRODUTOS, self.LOJAS4, parciais={"lidl"})
        self.assertEqual([s["loja"] for s in r.suspeitos], ["Lidl"])
