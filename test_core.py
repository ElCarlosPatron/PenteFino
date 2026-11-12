import unittest
from pathlib import Path
from core import load_comptar, export_comptar

class CoreTests(unittest.TestCase):
    def test_roundtrip(self):
        raw = ("Codigo;Descricao;Saldo;C1;C.Dif;Diferenca;Ajuste;Final;Localizacoes\r\n"
               "001;Produto A;10;8;8;-2;0;8;A1,A2\r\n"
               ";Total: 1 itens;10;;;;;;\r\n").encode()
        original, work, indices = load_comptar(raw)
        self.assertEqual(len(work), 1)
        self.assertEqual(work.at[0, "CONT.FINAL"], 8)
        work.at[0, "CONT.FINAL"] = 9
        work.at[0, "Conferido"] = True
        output = export_comptar(original, work, indices).decode("utf-8-sig")
        self.assertIn("Localizacoes;CONT.FINAL", output)
        self.assertIn("001;Produto A;10;8;8;-2;0;8;A1,A2;9", output)
        self.assertIn(";Total: 1 itens;10;;;;;;;", output)
    def test_block_pending(self):
        raw = b"Codigo;Descricao;Saldo;C1;C.Dif;Diferenca;Ajuste;Final;Localizacoes\n1;A;1;1;1;0;0;1;L1\n"
        o,w,idx = load_comptar(raw)
        with self.assertRaises(ValueError): export_comptar(o,w,idx)

if __name__ == '__main__': unittest.main()
