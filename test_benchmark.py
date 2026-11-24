"""End-to-end acceptance test for the mandatory internship benchmark.
Run: python -m unittest test_benchmark.py
"""
import os, tempfile, unittest
import app as sf

class BenchmarkFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=sf.DB; sf.DB=os.path.join(self.tmp.name,'test.db'); sf.init_db(); self.client=sf.app.test_client()
    def tearDown(self):
        sf.DB=self.old; self.tmp.cleanup()
    def login(self,user,password): self.client.post('/login',data={'username':user,'password':password})
    def test_pdf_benchmark_flow(self):
        self.login('admin','admin123')
        self.assertEqual(self.client.post('/api/purchase',json={'material_id':1,'qty':60,'rate':45,'reference':'PO-2026-001'}).status_code,200)
        run=self.client.post('/api/production',json={'batches':1,'actual_packets':188,'damaged_pouches':6,'cartons_used':9,'labour':1200,'utilities':600,'actuals':{'1':40,'2':10.5,'3':1.2,'4':188,'5':9}})
        self.assertEqual(run.status_code,200,run.json); self.assertEqual(run.json['yield_variance'],-6.0); self.assertEqual(run.json['cost_per_packet'],31.14)
        self.client.get('/logout'); self.login('salesa','sales123')
        a=self.client.post('/api/orders',json={'customer_id':1,'lines':[{'product_id':1,'qty':150}],'client_key':'a'}).json['id']
        self.client.get('/logout'); self.login('admin','admin123')
        invoice=self.client.post(f'/api/orders/{a}/approve',json={}).json
        self.assertEqual(invoice['total'],7875.0); self.client.post(f'/api/orders/{a}/dispatch',json={})
        inv=self.client.get('/api/invoices').json[0]
        self.assertEqual(self.client.post('/api/payment',json={'invoice_id':inv['id'],'amount':4000}).status_code,200)
        self.client.get('/logout'); self.login('salesb','sales123')
        b=self.client.post('/api/orders',json={'customer_id':2,'lines':[{'product_id':1,'qty':120}],'client_key':'b'}).json['id']
        self.client.get('/logout'); self.login('admin','admin123')
        shortage=self.client.post(f'/api/orders/{b}/approve',json={})
        self.assertEqual(shortage.status_code,409); self.assertEqual(shortage.json['shortages'][0]['shortage'],32)
        self.assertEqual(self.client.get(f'/invoice/{inv["id"]}.pdf').status_code,200)
        stock=self.client.get('/api/stock').json
        byname={x['name']:x['balance'] for x in stock['materials']}
        self.assertEqual(byname['Flour'],120); self.assertEqual(byname['Cooking oil'],19.5); self.assertEqual(byname['200 g pouch'],306)
        self.assertEqual(stock['finished'][0]['balance'],88)

if __name__=='__main__': unittest.main()
