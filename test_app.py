import unittest
import json
import os
import io
from app import app, init_db

class TestStockPOS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from database import DB_PATH
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        init_db()

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_01_create_product_and_margin(self):
        # Création d'un produit avec achat=5000, transport=500, vente=7500, stock=20
        # Coût = 5500, Marge = 2000 FCFA
        data = {
            'name': 'Huile Dinor 5 Litres',
            'category': 'Forte rotation',
            'purchase_price': '5000',
            'transport_cost': '500',
            'sale_price': '7500',
            'stock_quantity': '20',
            'initial_stock': '20',
            'alert_threshold_percent': '20',
            'barcode': '123456789012'
        }
        res = self.client.post('/api/products', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.data)
        self.assertTrue(res_json.get('success'))
        self.assertIn('product_id', res_json)
        self.__class__.prod_id = res_json['product_id']

    def test_02_get_products_and_check_margins(self):
        res = self.client.get('/api/products')
        self.assertEqual(res.status_code, 200)
        prods = json.loads(res.data)
        self.assertTrue(len(prods) > 0)
        prod = [p for p in prods if p['id'] == self.__class__.prod_id][0]
        self.assertEqual(prod['cost_price'], 5500.0)
        self.assertEqual(prod['margin'], 2000.0)
        self.assertEqual(prod['stock_quantity'], 20)

    def test_03_customer_creation(self):
        data = {
            'name': 'Kouamé Jean-Luc',
            'phone': '0707123456',
            'notes': 'Grossiste Marcory'
        }
        res = self.client.post('/api/customers', data=json.dumps(data), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.data)
        self.assertTrue(res_json.get('success'))
        self.__class__.cust_id = res_json['customer_id']

    def test_04_create_sale(self):
        # Vente de 5 bidons d'huile à 7500 = 37 500 FCFA
        # Stock restant doit être 20 - 5 = 15
        sale_data = {
            'items': [{'product_id': self.__class__.prod_id, 'quantity': 5}],
            'payment_method': 'Espèces',
            'amount_received': 40000,
            'discount': 0,
            'customer_id': self.__class__.cust_id,
            'receipt_type': 'thermal'
        }
        res = self.client.post('/api/sales', data=json.dumps(sale_data), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.data)
        self.assertTrue(res_json.get('success'))
        self.assertEqual(res_json['total_amount'], 37500.0)
        self.__class__.sale_id = res_json['sale_id']

        # Vérification décrémentation stock
        res_p = self.client.get('/api/products')
        prod = [p for p in json.loads(res_p.data) if p['id'] == self.__class__.prod_id][0]
        self.assertEqual(prod['stock_quantity'], 15)

    def test_05_receipt_rendering(self):
        # Test ticket thermique
        res_th = self.client.get(f'/api/sales/{self.__class__.sale_id}/receipt?format=thermal')
        self.assertEqual(res_th.status_code, 200)
        self.assertIn(b'37 500', res_th.data)

        # Test facture A4 avec papier en-tête
        res_a4 = self.client.get(f'/api/sales/{self.__class__.sale_id}/receipt?format=a4')
        self.assertEqual(res_a4.status_code, 200)
        self.assertIn(b'37 500', res_a4.data)
        self.assertIn(b'Kouam\xc3\xa9 Jean-Luc', res_a4.data)

    def test_06_stock_alert_trigger(self):
        # Vendre encore 12 unités pour que le stock devienne 3 / 20 = 15% (en-dessous de 20%)
        sale_data = {
            'items': [{'product_id': self.__class__.prod_id, 'quantity': 12}],
            'payment_method': 'Mobile Money',
            'amount_received': 90000,
            'discount': 0,
            'customer_id': None,
            'receipt_type': 'thermal'
        }
        res = self.client.post('/api/sales', data=json.dumps(sale_data), content_type='application/json')
        self.assertEqual(res.status_code, 200)

        # Vérifier l'alerte
        res_alerts = self.client.get('/api/alerts')
        alerts = json.loads(res_alerts.data)
        alert_ids = [p['id'] for p in alerts]
        self.assertIn(self.__class__.prod_id, alert_ids)

    def test_07_restock_endpoint(self):
        # Ravitailler de 10 unités
        res = self.client.post(f'/api/products/{self.__class__.prod_id}/restock', data=json.dumps({'quantity': 10}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        res_p = self.client.get('/api/products')
        prod = [p for p in json.loads(res_p.data) if p['id'] == self.__class__.prod_id][0]
        self.assertEqual(prod['stock_quantity'], 13)

    def test_08_cancel_sale_with_reason(self):
        # Annuler la 1ère vente (5 unités) avec motif obligatoire
        # Sans motif -> Doit échouer avec code 400
        fail_res = self.client.post(f'/api/sales/{self.__class__.sale_id}/cancel', data=json.dumps({'reason': ''}), content_type='application/json')
        self.assertEqual(fail_res.status_code, 400)

        # Avec motif -> Doit réussir et restituer les 5 unités
        ok_res = self.client.post(f'/api/sales/{self.__class__.sale_id}/cancel', data=json.dumps({'reason': 'Erreur saisie caissier'}), content_type='application/json')
        self.assertEqual(ok_res.status_code, 200)

        # Vérifier réintégration du stock : 13 + 5 = 18
        res_p = self.client.get('/api/products')
        prod = [p for p in json.loads(res_p.data) if p['id'] == self.__class__.prod_id][0]
        self.assertEqual(prod['stock_quantity'], 18)

    def test_09_daily_closing(self):
        # Clôture du jour
        res = self.client.get('/api/closing/today')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue('total_revenue' in data)

        close_res = self.client.post('/api/closing/close', data=json.dumps({'notes': 'Test clôture'}), content_type='application/json')
        self.assertEqual(close_res.status_code, 200)

    def test_10_auto_rotation_burst_detection(self):
        # 1. Création d'un produit avec catégorie 'Auto' (nouveau produit)
        prod_data = {
            'name': 'Savon BF 250g',
            'category': 'Auto',
            'purchase_price': '200',
            'transport_cost': '25',
            'sale_price': '350',
            'stock_quantity': '100',
            'initial_stock': '100',
            'barcode': '7788990011'
        }
        res = self.client.post('/api/products', data=prod_data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        new_prod_id = json.loads(res.data)['product_id']

        # Vérifier qu'initialement, sans vente, il est en observation ('Nouveau')
        res_prods = self.client.get('/api/products')
        prod = [p for p in json.loads(res_prods.data) if p['id'] == new_prod_id][0]
        self.assertEqual(prod['category'], 'Nouveau')
        self.assertTrue(prod['is_auto'])

        # 2. Vendre le produit 5 fois dans la journée (intensité / pic journalier)
        for _ in range(5):
            sale_data = {
                'items': [{'product_id': new_prod_id, 'quantity': 2}],
                'payment_method': 'Espèces',
                'amount_received': 700,
                'discount': 0,
                'customer_id': None,
                'receipt_type': 'thermal'
            }
            s_res = self.client.post('/api/sales', data=json.dumps(sale_data), content_type='application/json')
            self.assertEqual(s_res.status_code, 200)

        # 3. Vérifier que le logiciel l'a AUTOMATIQUEMENT promu en 'Forte rotation' !
        res_prods_after = self.client.get('/api/products')
        prod_after = [p for p in json.loads(res_prods_after.data) if p['id'] == new_prod_id][0]
        self.assertEqual(prod_after['category'], 'Forte rotation')
        self.assertEqual(prod_after['alert_threshold_percent'], 20)
        self.assertIn('Pic de vente', prod_after['rotation_reason'])

    def test_11_auto_classify_all_endpoint(self):
        # Basculer tous les produits en mode automatique
        res = self.client.post('/api/products/auto-classify-all')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get('success'))

        # Tous les produits doivent être en mode auto
        res_prods = self.client.get('/api/products')
        prods = json.loads(res_prods.data)
        for p in prods:
            self.assertTrue(p['is_auto'])

    def test_12_restock_uses_selected_unit_conversion(self):
        units = json.dumps([
            {'name': 'Pièce', 'conversion_factor': 1, 'sale_price': 100},
            {'name': 'Paquet', 'conversion_factor': 6, 'sale_price': 600},
            {'name': 'Carton', 'conversion_factor': 24, 'sale_price': 2400},
        ])
        data = {
            'name': 'Produit conditionné',
            'purchase_price': '50',
            'sale_price': '100',
            'stock_quantity': '10',
            'initial_stock': '10',
            'units_json': units,
        }
        create_res = self.client.post('/api/products', data=data, content_type='multipart/form-data')
        self.assertEqual(create_res.status_code, 200)
        product_id = create_res.get_json()['product_id']

        products = self.client.get('/api/products').get_json()
        product = next(p for p in products if p['id'] == product_id)
        self.assertEqual([unit['name'] for unit in product['units']], ['Pièce', 'Paquet', 'Carton'])

        restock_res = self.client.post(
            f'/api/products/{product_id}/restock',
            data=json.dumps({'quantity': 2, 'unit_name': 'Carton'}),
            content_type='application/json'
        )
        self.assertEqual(restock_res.status_code, 200)
        self.assertEqual(restock_res.get_json()['added_stock'], 48)

        products = self.client.get('/api/products').get_json()
        product = next(p for p in products if p['id'] == product_id)
        self.assertEqual(product['stock_quantity'], 58)

    def test_13_fixed_price_per_piece(self):
        data = {
            'name': 'Produit prix négocié',
            'purchase_price': '100',
            'sale_price': '550',
            'stock_quantity': '10',
            'initial_stock': '10',
        }
        create_res = self.client.post('/api/products', data=data, content_type='multipart/form-data')
        self.assertEqual(create_res.status_code, 200)
        product_id = create_res.get_json()['product_id']

        sale_res = self.client.post(
            '/api/sales',
            data=json.dumps({
                'items': [{
                    'product_id': product_id,
                    'quantity': 3,
                    'discount_type': 'fixed_price',
                    'discount': 50,
                }],
                'payment_method': 'Espèces',
                'amount_received': 1500,
                'discount': 0,
                'receipt_type': 'thermal',
            }),
            content_type='application/json',
        )
        self.assertEqual(sale_res.status_code, 200, sale_res.get_json())
        sale = sale_res.get_json()
        self.assertEqual(sale['subtotal'], 1650.0)
        self.assertEqual(sale['total_amount'], 1500.0)
        self.assertEqual(sale['item_discount'], 150.0)

if __name__ == '__main__':
    unittest.main()
