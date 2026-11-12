import csv
import io
import unittest
from core import load_comptar, export_adjustments, is_sem_localizacao


class CSVTests(unittest.TestCase):
    def test_original_final_is_preserved_with_warning(self):
        content=("Codigo;Descricao;Saldo;C1;C.Dif;Diferenca;Ajuste;Final;Localizacoes\n"
                 "85124;Hidratante;10;2;2;-8;0;2;A01,B01\n"
                 "51236;Produto, aroma;9;3;3;-6;0;3;B02\n").encode("utf-8-sig")
        original,work,indices=load_comptar(content)
        self.assertEqual(len(work),2)
        self.assertEqual(work.at[0,"CONT.FINAL"],2)
        rows=[{"sku":"85124","description":"Hidratante","quantity":4,"status":"Conferido"},
              {"sku":"51236","description":"Produto, aroma","quantity":3,
               "status":"Finalizado antes de conferir"}]
        csvdata=export_adjustments(rows)
        self.assertTrue(csvdata.startswith(b"\xef\xbb\xbf"))
        output=list(csv.DictReader(io.StringIO(csvdata.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(output),2)
        self.assertEqual(output[1]["QUANTIDADE"],"3")
        self.assertEqual(output[1]["STATUS"],"Finalizado antes de conferir")
        self.assertEqual(output[1]["DESC"],"Produto, aroma")
        self.assertEqual(list(output[0]), ["COD", "DESC", "QUANTIDADE", "STATUS"])
        self.assertEqual(csvdata.decode("utf-8-sig").splitlines()[0], "COD;DESC;QUANTIDADE;STATUS")

    def test_sem_localizacao_criterion(self):
        self.assertTrue(is_sem_localizacao("10", "0", "0"))
        self.assertFalse(is_sem_localizacao("0", "0", "0"))
        self.assertFalse(is_sem_localizacao("10", "1", "0"))
        self.assertFalse(is_sem_localizacao("10", "0", "1"))
        self.assertTrue(is_sem_localizacao("1.000", "0", "0"))


if __name__=="__main__":
    unittest.main()
