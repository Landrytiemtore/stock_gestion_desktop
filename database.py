import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

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

    sale_columns = {row['name'] for row in cursor.execute('PRAGMA table_info(sales)').fetchall()}
    if 'user_id' not in sale_columns:
        cursor.execute('ALTER TABLE sales ADD COLUMN user_id INTEGER REFERENCES users(id)')

    # Historique des mouvements de stock, en quantité de la plus petite unité.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        operation_type TEXT NOT NULL CHECK(operation_type IN ('IN', 'OUT')),
        quantity INTEGER NOT NULL,
        stock_before INTEGER NOT NULL,
        stock_after INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        reference TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
    )
    ''')

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

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE CHECK(name IN ('SUPER_ADMIN', 'GERANT', 'VENDEUR')),
        description TEXT NOT NULL
    )
    ''')
    cursor.executemany(
        'INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)',
        [
            ('SUPER_ADMIN', 'Accès administrateur complet'),
            ('GERANT', 'Gestion du stock, catalogue et ventes'),
            ('VENDEUR', 'Enregistrement et consultation de ses ventes'),
        ]
    )

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL
    )
    ''')
    cursor.executemany(
        'INSERT OR IGNORE INTO permissions (code, description) VALUES (?, ?)',
        [
            ('sales.create', 'Créer une vente'),
            ('sales.view_own', 'Voir ses ventes'),
            ('sales.view_all', 'Voir toutes les ventes'),
            ('sales.cancel', 'Annuler une vente'),
            ('stock.manage', 'Gérer le stock'),
            ('inventory.manage', 'Gérer les inventaires'),
            ('catalog.manage', 'Gérer le catalogue'),
            ('settings.manage', 'Gérer les paramètres'),
            ('users.manage', 'Gérer les utilisateurs'),
            ('backup.manage', 'Exporter les sauvegardes'),
        ]
    )

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS role_permissions (
        role_id INTEGER NOT NULL,
        permission_id INTEGER NOT NULL,
        PRIMARY KEY (role_id, permission_id),
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
        FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
    )
    ''')
    role_permission_codes = {
        'VENDEUR': ('sales.create', 'sales.view_own'),
        'GERANT': ('sales.create', 'sales.view_own', 'sales.view_all', 'sales.cancel',
                    'stock.manage', 'inventory.manage', 'catalog.manage', 'settings.manage'),
        'SUPER_ADMIN': ('sales.create', 'sales.view_own', 'sales.view_all', 'sales.cancel',
                        'stock.manage', 'inventory.manage', 'catalog.manage', 'settings.manage',
                        'users.manage', 'backup.manage'),
    }
    for role_name, codes in role_permission_codes.items():
        role = cursor.execute('SELECT id FROM roles WHERE name = ?', (role_name,)).fetchone()
        for code in codes:
            permission = cursor.execute('SELECT id FROM permissions WHERE code = ?', (code,)).fetchone()
            cursor.execute(
                'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)',
                (role['id'], permission['id'])
            )

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role_id INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        session_version INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (role_id) REFERENCES roles(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS security_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        target_type TEXT DEFAULT '',
        target_id INTEGER,
        details TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    admin = cursor.execute('''
        SELECT u.id FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE r.name = 'SUPER_ADMIN'
        LIMIT 1
    ''').fetchone()
    if not admin:
        role = cursor.execute("SELECT id FROM roles WHERE name = 'SUPER_ADMIN'").fetchone()
        cursor.execute('''
            INSERT INTO users
            (username, full_name, password_hash, role_id, active, must_change_password)
            VALUES (?, ?, ?, ?, 1, 1)
        ''', ('admin', 'Super Administrateur', generate_password_hash('Admin@123', method='scrypt'), role['id']))

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Base de données initialisée avec succès.")
