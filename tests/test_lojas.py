import unittest

from cabaz.agente import corresponde
from cabaz.lojas import Oferta, preco_por_unidade, quantidade_embalagem


class TestUnidades(unittest.TestCase):
    def test_preco_por_unidade(self):
        self.assertEqual(preco_por_unidade("0,90€/lt"), (0.9, "L"))
        self.assertEqual(preco_por_unidade("0.85 €/Lt"), (0.85, "L"))
        self.assertEqual(preco_por_unidade("2 ,49€/kg"), (2.49, "kg"))
        self.assertEqual(preco_por_unidade("21,99 € /Kg Promoção"), (21.99, "kg"))
        self.assertEqual(preco_por_unidade("2,40€/dz"), (0.2, "un"))
        self.assertEqual(preco_por_unidade("sem preço"), (None, None))

    def test_quantidade_embalagem(self):
        self.assertEqual(quantidade_embalagem("Leite (emb. 6 x 1 lt)"), (6.0, "L"))
        self.assertEqual(quantidade_embalagem("LEITE UHT AUCHAN 6X1L"), (6.0, "L"))
        self.assertEqual(quantidade_embalagem("Manteiga (emb. 250 gr)"), (0.25, "kg"))
        self.assertEqual(quantidade_embalagem("Ovos (emb. 12 un)"), (12.0, "un"))
        self.assertEqual(quantidade_embalagem("Ovos de Solo Classe M (12 Un)"), (12.0, "un"))
        self.assertEqual(quantidade_embalagem("Pão"), (None, None))


class TestCorrespondencia(unittest.TestCase):
    produto = {"incluir": ["acucar", "branco"], "excluir": ["pasta", "stick", "sem "], "unidade": "kg"}

    def o(self, nome, unidade="kg"):
        return Oferta("x", "1", nome, 1.0, 1.0, unidade, "")

    def test_filtros(self):
        self.assertTrue(corresponde(self.o("AÇÚCAR AUCHAN BRANCO GRANULADO 1KG"), self.produto))
        self.assertFalse(corresponde(self.o("PASTA DE AÇUCAR BRANCO 250G"), self.produto))
        self.assertFalse(corresponde(self.o("AÇUCAR BRANCO EM STICKS 200G"), self.produto))
        self.assertFalse(corresponde(self.o("Açúcar branco", unidade="L"), self.produto))



class TestNomes(unittest.TestCase):
    def test_hifen_no_nome(self):
        produto = {"incluir": ["leite", "meio gordo"], "excluir": [], "unidade": "L"}
        self.assertTrue(corresponde(Oferta("x", "1", "MIMOSA Leite Meio-gordo", 1.0, 0.86, "L", ""), produto))


if __name__ == "__main__":
    unittest.main()
