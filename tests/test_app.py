"""Execute com: python -m unittest discover -s tests -v"""
import csv
import io
import tempfile
import unittest
from pathlib import Path

from app import app, db, initialize_database

SAMPLE = ("Codigo;Descricao;Saldo;C1;C.Dif;Diferenca;Ajuste;Final;Localizacoes\r\n"
          "100;Sabonete;5;3;3;-2;0;3;A01,B01\r\n"
          "101;Perfume;9;8;8;-1;0;8;B02\r\n"
          "102;Shampoo;6;0;0;-6;0;0;\r\n"
          "103;Creme;11;11;11;0;0;11;D01\r\n"
          "104;Batom;8;7;7;-1;0;7;E01\r\n"
          ";;39;;;;;;\r\n").encode("utf-8-sig")


class AppTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        app.config.update(TESTING=True, DB_PATH=str(Path(self.dir.name) / "test.sqlite3"))
        with app.app_context():
            initialize_database()
        self.admin = app.test_client()
        response = self.admin.post("/criar", data={
            "loja": "Loja Teste", "celulares": "3", "arquivo": (io.BytesIO(SAMPLE), "ajustes.csv")
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        self.code = response.location.rsplit("/", 1)[-1]

    def tearDown(self):
        self.dir.cleanup()

    def worker(self, slot):
        client=app.test_client()
        response=client.post(f"/entrar/{self.code}",
                             data={"operador":f"Operador {slot}", "celular":str(slot)})
        self.assertEqual(response.status_code,302)
        return client

    def products(self, slot):
        with app.app_context():
            return [dict(r) for r in db().execute(
                "SELECT * FROM products WHERE code=? AND slot=? ORDER BY source_index",
                (self.code,slot)).fetchall()]

    def test_split_and_search_and_previous(self):
        self.assertEqual([len(self.products(s)) for s in (1,2,3)],[2,2,1])
        w=self.worker(1)
        first,second=self.products(1)
        page=w.get(f"/contar/{self.code}?item={second['id']}")
        self.assertEqual(page.status_code,200)
        self.assertIn(b'SKU anterior',page.data)
        w.post(f"/contar/{self.code}/produto/{first['id']}",data={"quantidade":"4"})
        self.assertIn(b'100',w.get(f"/contar/{self.code}?status=conferidos").data)
        self.assertIn(b'103',w.get(f"/contar/{self.code}?status=pendentes").data)
        self.assertIn(b'100',w.get(f"/contar/{self.code}?q=100").data)
        self.assertIn(b'4',w.get(f"/contar/{self.code}?item={first['id']}").data)

    def test_filter_sem_localizacao_and_migration(self):
        # SKU 102 tinha saldo, mas não foi encontrado em C1 ou C.Dif.
        w = self.worker(3)
        page = w.get(f"/contar/{self.code}?status=sem_localizacao")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"<strong>102</strong>", page.data)
        self.assertIn(b"Sem localiza", page.data)
        self.assertNotIn(b"<strong>103</strong>", page.data)
        # Simula um banco v3.0 sem campos de Saldo/C1/C.Dif preenchidos.
        with app.app_context():
            db().execute("""UPDATE products SET saldo_comptar=NULL,
                c1_comptar=NULL, cdif_comptar=NULL WHERE code=?""", (self.code,))
            db().commit()
            initialize_database()
            restored = db().execute("""SELECT saldo_comptar,c1_comptar,cdif_comptar
                FROM products WHERE code=? AND sku='102'""", (self.code,)).fetchone()
            self.assertEqual(list(restored), ["6", "0", "0"])
        self.assertIn(b"102", w.get(f"/contar/{self.code}?status=sem_localizacao").data)

    def test_early_finish_retains_original_quantity_with_status(self):
        workers=[self.worker(i) for i in (1,2,3)]
        one=self.products(1)
        workers[0].post(f"/contar/{self.code}/produto/{one[0]['id']}",data={"quantidade":"4"})
        # Even an explicit finish POST is blocked until warning is acknowledged.
        workers[0].post(f"/contar/{self.code}/finalizar")
        with app.app_context():
            ph=db().execute("SELECT finished_at FROM phones WHERE code=? AND slot=1",(self.code,)).fetchone()
            self.assertIsNone(ph["finished_at"])
        workers[0].post(f"/contar/{self.code}/finalizar",data={"confirmar_antecipado":"sim"})
        self.assertEqual(self.admin.get(f"/gestao/{self.code}/baixar").status_code,409)
        # Remaining phones can also end early, making their last original quantities explicit.
        for other in workers[1:]:
            other.post(f"/contar/{self.code}/finalizar",data={"confirmar_antecipado":"sim"})
        downloaded=self.admin.get(f"/gestao/{self.code}/baixar")
        self.assertEqual(downloaded.status_code,200)
        records=list(csv.DictReader(io.StringIO(downloaded.data.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(list(records[0]),["COD","DESC","QUANTIDADE","STATUS"])
        by_code={r["COD"]:r for r in records}
        self.assertEqual(by_code["100"]["QUANTIDADE"],"4")
        self.assertEqual(by_code["100"]["STATUS"],"Conferido")
        self.assertEqual(by_code["101"]["QUANTIDADE"],"8")
        self.assertEqual(by_code["101"]["STATUS"],"Finalizado antes de conferir")
        self.assertEqual(by_code["104"]["QUANTIDADE"],"7")
        pdf=self.admin.get(f"/gestao/{self.code}/relatorio.pdf")
        self.assertEqual(pdf.status_code,200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        operators=self.admin.get(f"/gestao/{self.code}/operadores.csv")
        self.assertEqual(operators.status_code,200)
        self.assertIn(b'100',operators.data)
        operator_rows = list(csv.DictReader(io.StringIO(operators.data.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(operator_rows), 3)
        self.assertEqual(operator_rows[0]["OPERADOR"], "Operador 1")
        self.assertEqual(operator_rows[0]["CELULAR"], "1")
        self.assertIn("FINALIZAÇÃO", operator_rows[0])
        self.assertIn("SITUAÇÃO", operator_rows[0])
        with app.app_context():
            p=db().execute("SELECT reviewed_at FROM products WHERE code=? AND sku='101'",(self.code,)).fetchone()
            self.assertIsNone(p["reviewed_at"])

    def test_full_finish_and_reopen(self):
        workers=[self.worker(i) for i in (1,2,3)]
        for slot, client in enumerate(workers,1):
            for p in self.products(slot):
                client.post(f"/contar/{self.code}/produto/{p['id']}",
                            data={"quantidade":str(p['final_count'])})
            client.post(f"/contar/{self.code}/finalizar")
        stats=self.admin.get(f"/api/{self.code}/status").json
        self.assertEqual(stats["pending"],0)
        self.assertEqual(stats["finished"],3)
        self.assertTrue(stats["ready"])
        self.admin.post(f"/gestao/{self.code}/reabrir/1")
        self.assertEqual(self.admin.get(f"/gestao/{self.code}/baixar").status_code,409)
        p=self.products(1)[0]
        workers[0].post(f"/contar/{self.code}/produto/{p['id']}",data={"quantidade":"0"})
        workers[0].post(f"/contar/{self.code}/finalizar")
        self.assertEqual(self.admin.get(f"/gestao/{self.code}/baixar").status_code,200)

    def test_permissions(self):
        client=self.worker(1)
        item=self.products(2)[0]
        self.assertEqual(client.post(f"/contar/{self.code}/produto/{item['id']}",
                          data={"quantidade":"99"}).status_code,404)
        self.assertEqual(client.get(f"/gestao/{self.code}/baixar").status_code,403)
        self.assertEqual(client.get(f"/gestao/{self.code}/relatorio.pdf").status_code,403)

    # Regressões: a contagem deve seguir a sequência do filtro ativo.

    def test_pending_filter_keeps_selection_through_details_and_save(self):
        worker = self.worker(1)
        first, second = self.products(1)
        listing = worker.get(f"/contar/{self.code}?status=pendentes")
        self.assertIn(f"item={first['id']}&amp;status=pendentes".encode(), listing.data)
        detail = worker.get(f"/contar/{self.code}?item={first['id']}&status=pendentes")
        self.assertIn(b'SKU 1 DE 2 NO FILTRO', detail.data)
        self.assertIn(f"item={second['id']}&amp;status=pendentes".encode(), detail.data)
        saved = worker.post(
            f"/contar/{self.code}/produto/{first['id']}",
            data={"quantidade": "12", "status": "pendentes", "q": ""},
        )
        self.assertEqual(saved.status_code, 302)
        self.assertIn(f"item={second['id']}", saved.location)
        self.assertIn("status=pendentes", saved.location)
        subsequent = worker.get(saved.location)
        self.assertIn(b'SKU 1 DE 1 NO FILTRO', subsequent.data)
        self.assertIn(b'Sabonete', worker.get(f"/contar/{self.code}?status=conferidos").data)
        saved_last = worker.post(
            f"/contar/{self.code}/produto/{second['id']}",
            data={"quantidade": "11", "status": "pendentes", "q": ""},
        )
        self.assertIn("status=pendentes", saved_last.location)
        self.assertNotIn("item=", saved_last.location)
        self.assertIn(b'Nenhum SKU encontrado para esse filtro', worker.get(saved_last.location).data)

    def test_no_location_filter_keeps_selection_and_previous_next(self):
        worker = self.worker(1)
        first, second = self.products(1)
        # Ambos itens do celular 1 satisfazem Saldo > 0 e C1/C.Dif = 0.
        with app.app_context():
            db().execute("""UPDATE products SET c1_comptar='0', cdif_comptar='0'
                         WHERE code=? AND slot=1""", (self.code,))
            db().commit()
        listing = worker.get(f"/contar/{self.code}?status=sem_localizacao")
        self.assertIn(f"item={first['id']}&amp;status=sem_localizacao".encode(), listing.data)
        detail = worker.get(f"/contar/{self.code}?item={first['id']}&status=sem_localizacao")
        self.assertIn(b'SKU 1 DE 2 NO FILTRO', detail.data)
        self.assertIn(f"item={second['id']}&amp;status=sem_localizacao".encode(), detail.data)
        followed = worker.get(f"/contar/{self.code}?item={second['id']}&status=sem_localizacao")
        self.assertIn(f"item={first['id']}&amp;status=sem_localizacao".encode(), followed.data)
        saved = worker.post(
            f"/contar/{self.code}/produto/{first['id']}",
            data={"quantidade": "6", "status": "sem_localizacao", "q": ""},
        )
        self.assertIn(f"item={second['id']}", saved.location)
        self.assertIn("status=sem_localizacao", saved.location)

    def test_search_and_reviewed_filter_persist(self):
        worker = self.worker(1)
        first, second = self.products(1)
        for item in (first, second):
            worker.post(f"/contar/{self.code}/produto/{item['id']}",
                        data={"quantidade": "9"})
        listing = worker.get(f"/contar/{self.code}?status=conferidos&q=Sabonete")
        self.assertIn(f"item={first['id']}&amp;status=conferidos&amp;q=Sabonete".encode(), listing.data)
        detail = worker.get(f"/contar/{self.code}?item={first['id']}&status=conferidos&q=Sabonete")
        self.assertIn(b'Filtro ativo:', detail.data)
        self.assertIn(b'Sabonete', detail.data)
        changed = worker.post(
            f"/contar/{self.code}/produto/{first['id']}",
            data={"quantidade": "8", "status": "conferidos", "q": "Sabonete"},
        )
        self.assertIn("status=conferidos", changed.location)
        self.assertIn("q=Sabonete", changed.location)
        self.assertNotIn("item=", changed.location)


if __name__ == "__main__":
    unittest.main()
