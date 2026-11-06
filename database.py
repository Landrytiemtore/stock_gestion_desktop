import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'pos_database.db')

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table Produits
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'Auto',
        purchase_price REAL NOT NULL DEFAULT 0.0,
        transport_cost REAL NOT NULL DEFAULT 0.0,
        cost_price REAL NOT NULL DEFAULT 0.0,
        sale_price REAL NOT NULL DEFAULT 0.0,
        stock_quantity INTEGER NOT NULL DEFAULT 0,
        initial_stock INTEGER NOT NULL DEFAULT 0,
        alert_threshold_percent INTEGER DEFAULT 20,
        image_path TEXT DEFAULT '',
        barcode TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS product_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        conversion_factor INTEGER NOT NULL DEFAULT 1,
        sale_price REAL NOT NULL DEFAULT 0.0,
        is_base INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
    )
    ''')

    unit_columns = {row['name'] for row in cursor.execute('PRAGMA table_info(product_units)').fetchall()}
    if 'conversion_factor' not in unit_columns:
        cursor.execute('ALTER TABLE product_units ADD COLUMN conversion_factor INTEGER NOT NULL DEFAULT 1')
    if 'sale_price' not in unit_columns:
        cursor.execute('ALTER TABLE product_units ADD COLUMN sale_price REAL NOT NULL DEFAULT 0.0')
    if 'is_base' not in unit_columns:
        cursor.execute('ALTER TABLE product_units ADD COLUMN is_base INTEGER NOT NULL DEFAULT 0')

    for product in cursor.execute('SELECT id, name, sale_price FROM products').fetchall():
        base = cursor.execute(
            'SELECT id FROM product_units WHERE product_id = ? AND is_base = 1 LIMIT 1',
            (product['id'],)
        ).fetchone()
        if not base:
            cursor.execute(
                'INSERT INTO product_units (product_id, name, conversion_factor, sale_price, is_base) VALUES (?, ?, 1, ?, 1)',
                (product['id'], 'Pièce', product['sale_price'])
            )

    # Table Clients
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        total_spent REAL DEFAULT 0.0,
        orders_count INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Table Ventes
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_code TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT DEFAULT 'Client Passant',
        customer_phone TEXT DEFAULT '',
        subtotal REAL NOT NULL DEFAULT 0.0,
        discount REAL DEFAULT 0.0,
        total_amount REAL NOT NULL DEFAULT 0.0,
        total_cost REAL NOT NULL DEFAULT 0.0,
        profit REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT NOT NULL DEFAULT 'Espèces',
        amount_received REAL NOT NULL DEFAULT 0.0,
        change_returned REAL DEFAULT 0.0,
        receipt_type TEXT DEFAULT 'thermal',
        status TEXT DEFAULT 'COMPLETED',
        cancellation_reason TEXT DEFAULT '',
        cancelled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    )
    ''')

    # Table Lignes de vente
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        unit_cost REAL NOT NULL DEFAULT 0.0,
        unit_price REAL NOT NULL DEFAULT 0.0,
        quantity INTEGER NOT NULL DEFAULT 1,
        subtotal REAL NOT NULL DEFAULT 0.0,
        discount REAL NOT NULL DEFAULT 0.0,
        profit REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY (sale_id) REFERENCES sales (id),
        FOREIGN KEY (product_id) REFERENCES products (id)
    )
    ''')

    # Migration des bases existantes
    sale_item_columns = {row['name'] for row in cursor.execute('PRAGMA table_info(sale_items)').fetchall()}
    if 'discount' not in sale_item_columns:
        cursor.execute('ALTER TABLE sale_items ADD COLUMN discount REAL NOT NULL DEFAULT 0.0')
    if 'unit_name' not in sale_item_columns:
        cursor.execute("ALTER TABLE sale_items ADD COLUMN unit_name TEXT NOT NULL DEFAULT 'Pièce'")
    if 'unit_factor' not in sale_item_columns:
        cursor.execute('ALTER TABLE sale_items ADD COLUMN unit_factor INTEGER NOT NULL DEFAULT 1')

    # Table Clôtures Journalières (Rapport Z)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_closings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        closing_date TEXT UNIQUE NOT NULL,
        total_sales_count INTEGER DEFAULT 0,
        total_cash REAL DEFAULT 0.0,
        total_mobile_money REAL DEFAULT 0.0,
        total_revenue REAL DEFAULT 0.0,
        total_cost REAL DEFAULT 0.0,
        total_profit REAL DEFAULT 0.0,
        closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT ''
    )
    ''')

    # Table Paramètres Entreprise & Reçu
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        company_name TEXT DEFAULT 'MON COMMERCE & GESTION',
        company_slogan TEXT DEFAULT 'Vente en gros et demi-gros',
        company_phone TEXT DEFAULT '+225 07 00 00 00 00 / +221 77 000 00 00',
        company_address TEXT DEFAULT 'Marché Central, Magasin N° 42',
        company_nif_rccm TEXT DEFAULT 'RCCM: CI-ABJ-2024-B-12345 | NIF: 987654321',
        receipt_footer TEXT DEFAULT 'Merci pour votre achat ! Les articles vendus ne sont ni repris ni échangés.',
        currency TEXT DEFAULT 'FCFA',
        default_receipt_format TEXT DEFAULT 'thermal',
        company_logo TEXT DEFAULT ''
    )
    ''')

    # Insérer réglages par défaut si non existant
    cursor.execute('SELECT COUNT(*) FROM settings WHERE id = 1')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
        INSERT INTO settings (id, company_name, company_slogan, company_phone, company_address, company_nif_rccm, receipt_footer, currency, default_receipt_format, company_logo)
        VALUES (1, 'COMMERCE MODERNE', 'Vente & Distribution Directe', '+225 07 12 34 56 78', 'Avenue Principale, Boutique 12', 'RCCM: CI-ABJ-2024-B-1234 | NIF: 10293847', 'Merci pour votre confiance. Les marchandises vendues ne sont ni reprises ni échangées.', 'FCFA', 'thermal', '')
        ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Base de données initialisée avec succès.")
