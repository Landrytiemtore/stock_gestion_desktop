import os
import sys
import shutil
import sqlite3
import json
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, session, g, make_response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from secrets import token_urlsafe
from PIL import Image
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from database import get_db_connection, init_db, DB_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
RECEIPTS_DIR = os.path.join(BASE_DIR, 'recus')
DATA_DIR = os.path.join(BASE_DIR, 'data')

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(RECEIPTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOADS_DIR
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max
app.config['SECRET_KEY'] = os.environ.get('POS_SESSION_SECRET', token_urlsafe(48))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def audit_action(action, target_type='', target_id=None, details=''):
    if not getattr(g, 'user', None):
        return
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO security_audit_log (user_id, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (g.user['id'], action, target_type, target_id, details, request.remote_addr or ''))
    conn.commit()
    conn.close()

@app.before_request
def load_authenticated_user():
    g.user = None
    user_id = session.get('user_id')
    session_version = session.get('session_version')
    if not user_id:
        return
    conn = get_db_connection()
    user = conn.execute('''
        SELECT u.*, r.name AS role_name
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = ? AND u.active = 1
    ''', (user_id,)).fetchone()
    conn.close()
    if user and int(user['session_version']) == session_version:
        g.user = user
    else:
        session.clear()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return jsonify({'error': 'Authentification requise.'}), 401
        return view(*args, **kwargs)
    return wrapped

def permission_required(*permissions):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return jsonify({'error': 'Authentification requise.'}), 401
            conn = get_db_connection()
            granted = conn.execute('''
                SELECT COUNT(*)
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                JOIN roles r ON r.id = rp.role_id
                WHERE r.name = ? AND p.code IN ({})
            '''.format(','.join('?' * len(permissions))),
                (g.user['role_name'], *permissions)).fetchone()[0]
            conn.close()
            if not granted:
                return jsonify({'error': 'Accès refusé.'}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator

@app.before_request
def protect_mutating_requests():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    public_paths = {'/api/auth/login'}
    if request.path in public_paths:
        return
    origin = request.headers.get('Origin')
    if origin:
        allowed_origins = {
            'http://127.0.0.1:5055',
            'http://localhost:5055',
        }
        if origin.rstrip('/') not in allowed_origins:
            return jsonify({'error': 'Origine de requête non autorisée.'}), 403

# Calcul de l'état du stock
def compute_stock_status(stock_qty, initial_stock, threshold_pct):
    if stock_qty <= 0:
        return 'out', 'Rupture de stock'
    ref_stock = initial_stock if initial_stock > 0 else stock_qty
    current_pct = (stock_qty / ref_stock) * 100
    if current_pct <= threshold_pct:
        return 'alert', f'Stock faible ({int(current_pct)}%)'
    return 'normal', 'Stock suffisant'

# ================= MOTEUR DE DÉTECTION DE ROTATION DU STOCK =================
def get_products_sales_metrics(conn):
    """
    Calcule pour chaque produit les métriques réelles de vente :
    - active_days_30d : nombre de jours distincts de vente sur les 30 derniers jours
    - total_qty_30d   : total d'unités vendues sur les 30 derniers jours
    - total_qty_7d    : total d'unités vendues sur les 7 derniers jours (vélocité récente)
    - tx_count_7d     : nombre de passages en caisse sur les 7 derniers jours
    - max_day_qty     : volume maximal vendu en un seul jour (sur les 30j)
    - max_day_tx      : nombre maximal de transactions en un seul jour (sur les 30j)
    """
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            si.product_id,
            date(s.created_at) as sale_day,
            SUM(si.quantity) as day_qty,
            COUNT(si.id) as day_tx
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE s.status = 'COMPLETED'
          AND s.created_at >= datetime('now', '-30 days')
        GROUP BY si.product_id, date(s.created_at)
    ''')
    rows = cursor.fetchall()

    metrics = {}
    seven_days_ago_str = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    for r in rows:
        pid = r['product_id']
        sday = str(r['sale_day'])
        qty = int(r['day_qty'] or 0)
        tx = int(r['day_tx'] or 0)

        if pid not in metrics:
            metrics[pid] = {
                'active_days_30d': 0,
                'total_qty_30d': 0,
                'total_qty_7d': 0,
                'tx_count_7d': 0,
                'max_day_qty': 0,
                'max_day_tx': 0,
            }

        metrics[pid]['active_days_30d'] += 1
        metrics[pid]['total_qty_30d'] += qty

        if sday >= seven_days_ago_str:
            metrics[pid]['total_qty_7d'] += qty
            metrics[pid]['tx_count_7d'] += tx

        if qty > metrics[pid]['max_day_qty']:
            metrics[pid]['max_day_qty'] = qty
        if tx > metrics[pid]['max_day_tx']:
            metrics[pid]['max_day_tx'] = tx

    return metrics


def evaluate_product_rotation(product_row, metrics_dict):
    """
    Détermine automatiquement la rotation d'un article selon un double moteur :
    1. Intensité / Débit récent :
       - Vendu >= 5 fois ou >= 5 unités dans une seule journée
       - OU >= 15 unités vendues sur les 7 derniers jours
       - OU >= 8 transactions sur les 7 derniers jours
    2. Fréquence régulière mensuelle :
       - Vendu >= 10 jours distincts sur les 30 derniers jours
       - OU >= 30 unités vendues sur les 30 derniers jours
    3. Nouveau produit :
       - Créé depuis <= 15 jours sans avoir encore de gros volume
    4. Faible rotation (produit dormant / lent) :
       - Produit de plus de 15 jours avec <= 2 jours de vente et <= 4 unités vendues sur 30 jours
    5. Standard :
       - Ventes intermédiaires régulières
    """
    pid = product_row['id']
    m = metrics_dict.get(pid, {
        'active_days_30d': 0,
        'total_qty_30d': 0,
        'total_qty_7d': 0,
        'tx_count_7d': 0,
        'max_day_qty': 0,
        'max_day_tx': 0,
    })

    created_str = product_row.get('created_at')
    days_old = 0
    if created_str:
        try:
            created_dt = datetime.strptime(str(created_str).split('.')[0], '%Y-%m-%d %H:%M:%S')
            days_old = max(0, (datetime.now() - created_dt).days)
        except Exception:
            days_old = 0

    # Moteur 1 : Intensité / Débit rapide (Pics journaliers ou semaine)
    is_burst = (
        m['max_day_tx'] >= 5 or 
        m['max_day_qty'] >= 5 or 
        m['total_qty_7d'] >= 15 or 
        m['tx_count_7d'] >= 8
    )

    # Moteur 2 : Fréquence régulière mensuelle
    is_frequent = (
        m['active_days_30d'] >= 10 or 
        m['total_qty_30d'] >= 30
    )

    if is_burst or is_frequent:
        rotation_status = 'Forte rotation'
        recommended_threshold = 20
        if m['max_day_tx'] >= 5 or m['max_day_qty'] >= 5:
            reason = f"Pic de vente : jusqu'à {max(m['max_day_qty'], m['max_day_tx'])} ventes en 1 journée"
        elif m['total_qty_7d'] >= 15:
            reason = f"Forte cadence : {m['total_qty_7d']} unités vendues ces 7 derniers jours"
        elif m['tx_count_7d'] >= 8:
            reason = f"Débit rapide : {m['tx_count_7d']} passages en caisse ces 7 derniers jours"
        elif m['active_days_30d'] >= 10:
            reason = f"Grande régularité : vendu {m['active_days_30d']} jours sur les 30 derniers jours"
        else:
            reason = f"Gros volume mensuel : {m['total_qty_30d']} unités vendues ce mois"
    elif days_old <= 15 and m['total_qty_30d'] == 0:
        rotation_status = 'Nouveau'
        recommended_threshold = 15
        reason = f"Nouveau produit (créé il y a {days_old}j - en observation)"
    elif days_old > 15 and m['active_days_30d'] <= 2 and m['total_qty_30d'] <= 4:
        rotation_status = 'Faible rotation'
        recommended_threshold = 10
        if m['total_qty_30d'] == 0:
            reason = "Aucune vente enregistrée sur les 30 derniers jours"
        else:
            reason = f"Faible demande : {m['total_qty_30d']} unité(s) vendue(s) sur {m['active_days_30d']} jour(s)"
    else:
        rotation_status = 'Standard'
        recommended_threshold = 15
        reason = f"Rotation standard ({m['total_qty_30d']} unités sur {m['active_days_30d']} jours)"

    raw_category = product_row.get('category') or 'Auto'
    is_auto = (raw_category in ('Auto', '', None))

    # Catégorie effective
    effective_category = rotation_status if is_auto else raw_category

    # Seuil d'alerte : si mode auto, aligner dynamiquement sur le seuil recommandé
    stored_threshold = product_row.get('alert_threshold_percent')
    if is_auto:
        effective_threshold = recommended_threshold
    else:
        effective_threshold = stored_threshold or recommended_threshold

    return {
        'rotation_status': rotation_status,
        'effective_category': effective_category,
        'raw_category': raw_category,
        'is_auto': is_auto,
        'rotation_reason': reason if is_auto else f"Catégorie fixée manuellement ({reason})",
        'recommended_threshold': recommended_threshold,
        'effective_threshold': effective_threshold,
        'metrics': m,
        'days_old': days_old
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ================= AUTHENTIFICATION & UTILISATEURS =================
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()
    if not username or not password:
        return jsonify({'error': 'Nom d’utilisateur et mot de passe obligatoires.'}), 400
    conn = get_db_connection()
    user = conn.execute('''
        SELECT u.*, r.name AS role_name
        FROM users u JOIN roles r ON r.id = u.role_id
        WHERE u.username = ? AND u.active = 1
    ''', (username,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Identifiants incorrects.'}), 401
    session.clear()
    session.permanent = True
    session['user_id'] = user['id']
    session['session_version'] = user['session_version']
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'full_name': user['full_name'],
            'role': user['role_name'],
            'must_change_password': bool(user['must_change_password']),
        }
    })

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    response = make_response(jsonify({'success': True}))
    response.delete_cookie('session', path='/')
    return response

@app.route('/api/auth/me')
@login_required
def current_user():
    return jsonify({
        'id': g.user['id'],
        'username': g.user['username'],
        'full_name': g.user['full_name'],
        'role': g.user['role_name'],
        'must_change_password': bool(g.user['must_change_password']),
    })

@app.route('/api/users', methods=['GET'])
@permission_required('users.manage')
def get_users():
    conn = get_db_connection()
    users = conn.execute('''
        SELECT u.id, u.username, u.full_name, r.name AS role, u.active,
               u.must_change_password, u.created_at
        FROM users u JOIN roles r ON r.id = u.role_id
        ORDER BY u.full_name
    ''').fetchall()
    conn.close()
    return jsonify([dict(user) for user in users])

@app.route('/api/users', methods=['POST'])
@permission_required('users.manage')
def create_user():
    data = request.get_json(force=True)
    username = str(data.get('username', '')).strip()
    full_name = str(data.get('full_name', '')).strip()
    password = str(data.get('password', '')).strip()
    role = str(data.get('role', '')).upper()
    if not username or not full_name or len(password) < 8:
        return jsonify({'error': 'Nom, utilisateur et mot de passe de 8 caractères minimum requis.'}), 400
    if role not in ('SUPER_ADMIN', 'GERANT', 'VENDEUR'):
        return jsonify({'error': 'Rôle invalide.'}), 400
    conn = get_db_connection()
    role_row = conn.execute('SELECT id FROM roles WHERE name = ?', (role,)).fetchone()
    try:
        cursor = conn.execute('''
            INSERT INTO users (username, full_name, password_hash, role_id, must_change_password)
            VALUES (?, ?, ?, ?, 1)
        ''', (username, full_name, generate_password_hash(password, method='scrypt'), role_row['id']))
        user_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ce nom d’utilisateur existe déjà.'}), 400
    conn.close()
    audit_action('USER_CREATED', 'user', user_id, username)
    return jsonify({'success': True, 'user_id': user_id})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@permission_required('users.manage')
def delete_user(user_id):
    if g.user['role_name'] != 'SUPER_ADMIN':
        return jsonify({'error': 'Seul le Super Admin peut supprimer un utilisateur.'}), 403
    if user_id == g.user['id']:
        return jsonify({'error': 'Vous ne pouvez pas supprimer votre propre compte.'}), 400

    conn = get_db_connection()
    user = conn.execute('''
        SELECT u.*, r.name AS role_name
        FROM users u JOIN roles r ON r.id = u.role_id
        WHERE u.id = ?
    ''', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'Utilisateur introuvable.'}), 404

    if user['role_name'] == 'SUPER_ADMIN':
        active_admins = conn.execute('''
            SELECT COUNT(*) FROM users u
            JOIN roles r ON r.id = u.role_id
            WHERE r.name = 'SUPER_ADMIN' AND u.active = 1
        ''').fetchone()[0]
        if active_admins <= 1:
            conn.close()
            return jsonify({'error': 'Impossible de supprimer le dernier Super Admin.'}), 400

    conn.execute(
        'UPDATE users SET active = 0, session_version = session_version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (user_id,)
    )
    conn.commit()
    conn.close()
    audit_action('USER_DELETED', 'user', user_id, user['username'])
    return jsonify({'success': True})

# ================= PRODUITS =================
def parse_product_units(raw_units, sale_price):
    try:
        units = json.loads(raw_units) if raw_units else []
    except (TypeError, json.JSONDecodeError):
        raise ValueError("Le format des conditionnements est invalide.")

    if not isinstance(units, list):
        raise ValueError("Les conditionnements doivent être une liste.")

    normalized = []
    seen_names = set()
    for index, unit in enumerate(units):
        name = str(unit.get('name', '')).strip()
        try:
            factor = int(unit.get('conversion_factor', 0))
            price = float(unit.get('sale_price', sale_price))
        except (TypeError, ValueError):
            raise ValueError("Facteur de conversion et prix invalides.")
        if not name or factor <= 0 or price < 0:
            raise ValueError("Chaque conditionnement doit avoir un nom, un facteur positif et un prix valide.")
        key = name.casefold()
        if key in seen_names:
            raise ValueError(f"Le conditionnement '{name}' est défini plusieurs fois.")
        seen_names.add(key)
        normalized.append({
            'name': name,
            'conversion_factor': factor,
            'sale_price': price,
            'is_base': 1 if index == 0 else int(bool(unit.get('is_base'))),
        })

    if not normalized:
        normalized.append({'name': 'Pièce', 'conversion_factor': 1, 'sale_price': float(sale_price), 'is_base': 1})

    normalized[0]['is_base'] = 1
    normalized[0]['conversion_factor'] = 1
    for unit in normalized[1:]:
        unit['is_base'] = 0
    return normalized

def sync_product_units(conn, product_id, sale_price, raw_units=None, commit=True):
    units = parse_product_units(raw_units, sale_price) if raw_units is not None else [{
        'name': 'Pièce',
        'conversion_factor': 1,
        'sale_price': float(sale_price),
        'is_base': 1,
    }]
    conn.execute('DELETE FROM product_units WHERE product_id = ?', (product_id,))
    for unit in units:
        conn.execute(
            'INSERT INTO product_units (product_id, name, conversion_factor, sale_price, is_base) VALUES (?, ?, ?, ?, ?)',
            (product_id, unit['name'], unit['conversion_factor'], unit['sale_price'], unit['is_base'])
        )
    if commit:
        conn.commit()

@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    conn = get_db_connection()
    products_db = conn.execute('SELECT * FROM products ORDER BY name ASC').fetchall()
    metrics = get_products_sales_metrics(conn)

    products = []
    for row in products_db:
        p = dict(row)
        eval_res = evaluate_product_rotation(p, metrics)
        
        p['category'] = eval_res['effective_category']
        p['raw_category'] = eval_res['raw_category']
        p['rotation_status'] = eval_res['rotation_status']
        p['rotation_reason'] = eval_res['rotation_reason']
        p['rotation_metrics'] = eval_res['metrics']
        p['is_auto'] = eval_res['is_auto']
        p['alert_threshold_percent'] = eval_res['effective_threshold']

        status_key, status_label = compute_stock_status(p['stock_quantity'], p['initial_stock'], eval_res['effective_threshold'])
        p['status_key'] = status_key
        p['status_label'] = status_label
        p['margin'] = p['sale_price'] - p['cost_price']
        p['margin_percent'] = round((p['margin'] / p['cost_price'] * 100), 1) if p['cost_price'] > 0 else 0
        units = conn.execute(
            'SELECT id, name, conversion_factor, sale_price, is_base FROM product_units WHERE product_id = ? ORDER BY is_base DESC, id ASC',
            (p['id'],)
        ).fetchall()
        p['units'] = [dict(unit) for unit in units]
        products.append(p)
    conn.close()
    return jsonify(products)

PRODUCT_IMPORT_COLUMNS = [
    'nom', 'categorie', 'prix_achat', 'frais_transport', 'prix_vente',
    'stock_initial', 'seuil_alerte', 'code_barres',
    'conditionnement_1', 'pieces_par_conditionnement_1', 'prix_vente_1',
    'conditionnement_2', 'pieces_par_conditionnement_2', 'prix_vente_2',
    'conditionnement_3', 'pieces_par_conditionnement_3', 'prix_vente_3'
]


def parse_excel_product_units(value, sale_price):
    units = [{
        'name': 'Pièce',
        'conversion_factor': 1,
        'sale_price': sale_price,
        'is_base': 1,
    }]
    names = set()
    for number in range(1, 4):
        unit_name = str(value(f'conditionnement_{number}', '')).strip()
        if not unit_name:
            continue
        if unit_name.casefold() in ('piece', 'pièce') or unit_name.casefold() in names:
            raise ValueError(f'Conditionnement invalide sur la colonne {number}.')
        factor = int(float(value(f'pieces_par_conditionnement_{number}', 0) or 0))
        unit_sale_price = float(value(f'prix_vente_{number}', 0) or 0)
        if factor <= 0 or unit_sale_price < 0:
            raise ValueError(f'Facteur ou prix invalide pour le conditionnement {number}.')
        names.add(unit_name.casefold())
        units.append({
            'name': unit_name,
            'conversion_factor': factor,
            'sale_price': unit_sale_price,
            'is_base': 0,
        })
    return units


@app.route('/api/products/import/template', methods=['GET'])
@login_required
def download_product_import_template():
    if g.user['role_name'] != 'SUPER_ADMIN':
        return jsonify({'error': 'Import réservé au Super Admin.'}), 403

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Produits'
    sheet.append(PRODUCT_IMPORT_COLUMNS)
    sheet.append(['Huile Dinor 5L', 'Standard', 4500, 500, 6000, 10, 20, '123456789',
                  'Paquet', 6, 6500, 'Carton', 24, 24000, '', '', ''])
    for column in sheet.columns:
        column[0].font = Font(bold=True)
        sheet.column_dimensions[column[0].column_letter].width = 18

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='modele_import_produits.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.route('/api/products/import/preview', methods=['POST'])
@login_required
def preview_product_import():
    if g.user['role_name'] != 'SUPER_ADMIN':
        return jsonify({'error': 'Import réservé au Super Admin.'}), 403

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename.lower().endswith('.xlsx'):
        return jsonify({'error': 'Sélectionnez un fichier Excel (.xlsx).'}), 400
    if uploaded.content_length and uploaded.content_length > 5 * 1024 * 1024:
        return jsonify({'error': 'La taille maximale autorisée est de 5 Mo.'}), 400

    try:
        workbook = load_workbook(io.BytesIO(uploaded.read()), read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    except Exception:
        return jsonify({'error': 'Le fichier Excel est illisible ou invalide.'}), 400

    if not rows:
        return jsonify({'error': 'La feuille Excel est vide.'}), 400
    headers = [str(value).strip().lower() if value is not None else '' for value in rows[0]]
    missing = [column for column in PRODUCT_IMPORT_COLUMNS[:1] if column not in headers]
    if missing:
        return jsonify({'error': 'Colonne obligatoire manquante : nom.'}), 400

    preview = []
    errors = []
    indexes = {header: index for index, header in enumerate(headers)}
    conn = get_db_connection()
    existing_barcodes = {
        row['barcode'] for row in conn.execute(
            "SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''"
        ).fetchall()
    }
    conn.close()
    seen_barcodes = set()

    for line_number, row in enumerate(rows[1:], start=2):
        if not any(value not in (None, '') for value in row):
            continue

        def value(column, default=0):
            index = indexes.get(column)
            return row[index] if index is not None and index < len(row) else default

        name = str(value('nom', '')).strip()
        if not name:
            errors.append({'line': line_number, 'error': 'Le nom est obligatoire.'})
            continue
        try:
            purchase_price = max(0, float(value('prix_achat', 0) or 0))
            transport_cost = max(0, float(value('frais_transport', 0) or 0))
            sale_price = max(0, float(value('prix_vente', 0) or 0))
            stock_initial = max(0, int(float(value('stock_initial', 0) or 0)))
            threshold = min(100, max(1, int(float(value('seuil_alerte', 20) or 20))))
        except (TypeError, ValueError):
            errors.append({'line': line_number, 'error': 'Une valeur numérique est invalide.'})
            continue
        try:
            units = parse_excel_product_units(value, sale_price)
        except (TypeError, ValueError):
            errors.append({'line': line_number, 'error': 'Conditionnement, facteur ou prix invalide.'})
            continue

        barcode = str(value('code_barres', '')).strip()
        if barcode and (barcode in existing_barcodes or barcode in seen_barcodes):
            errors.append({'line': line_number, 'error': 'Ce code-barres existe déjà.'})
            continue
        if barcode:
            seen_barcodes.add(barcode)

        preview.append({
            'name': name,
            'category': str(value('categorie', 'Standard')).strip() or 'Standard',
            'purchase_price': purchase_price,
            'transport_cost': transport_cost,
            'sale_price': sale_price,
            'stock_quantity': stock_initial,
            'initial_stock': stock_initial,
            'alert_threshold_percent': threshold,
            'barcode': barcode,
            'units': units,
        })

    return jsonify({'products': preview, 'errors': errors, 'valid_count': len(preview)})


@app.route('/api/products/import', methods=['POST'])
@login_required
def import_products():
    if g.user['role_name'] != 'SUPER_ADMIN':
        return jsonify({'error': 'Import réservé au Super Admin.'}), 403

    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename.lower().endswith('.xlsx'):
        return jsonify({'error': 'Sélectionnez un fichier Excel (.xlsx).'}), 400
    try:
        workbook = load_workbook(io.BytesIO(uploaded.read()), read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
    except Exception:
        return jsonify({'error': 'Le fichier Excel est illisible ou invalide.'}), 400
    if not rows:
        return jsonify({'error': 'La feuille Excel est vide.'}), 400

    headers = [str(value).strip().lower() if value is not None else '' for value in rows[0]]
    indexes = {header: index for index, header in enumerate(headers)}
    if 'nom' not in indexes:
        return jsonify({'error': 'Colonne obligatoire manquante : nom.'}), 400

    conn = get_db_connection()
    imported = 0
    errors = []
    seen_barcodes = {
        row['barcode'] for row in conn.execute(
            "SELECT barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''"
        ).fetchall()
    }
    try:
        for line_number, row in enumerate(rows[1:], start=2):
            if not any(value not in (None, '') for value in row):
                continue

            def value(column, default=0):
                index = indexes.get(column)
                return row[index] if index is not None and index < len(row) else default

            name = str(value('nom', '')).strip()
            barcode = str(value('code_barres', '')).strip()
            try:
                purchase_price = max(0, float(value('prix_achat', 0) or 0))
                transport_cost = max(0, float(value('frais_transport', 0) or 0))
                sale_price = max(0, float(value('prix_vente', 0) or 0))
                stock_quantity = max(0, int(float(value('stock_initial', 0) or 0)))
                threshold = min(100, max(1, int(float(value('seuil_alerte', 20) or 20))))
            except (TypeError, ValueError):
                errors.append({'line': line_number, 'error': 'Une valeur numérique est invalide.'})
                continue
            try:
                units = parse_excel_product_units(value, sale_price)
            except (TypeError, ValueError):
                errors.append({'line': line_number, 'error': 'Conditionnement, facteur ou prix invalide.'})
                continue
            if not name:
                errors.append({'line': line_number, 'error': 'Le nom est obligatoire.'})
                continue
            if barcode and barcode in seen_barcodes:
                errors.append({'line': line_number, 'error': 'Ce code-barres existe déjà.'})
                continue

            category = str(value('categorie', 'Standard')).strip() or 'Standard'
            cursor = conn.execute('''
                INSERT INTO products (
                    name, category, purchase_price, transport_cost, cost_price, sale_price,
                    stock_quantity, initial_stock, alert_threshold_percent, barcode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                name, category, purchase_price, transport_cost, purchase_price + transport_cost,
                sale_price, stock_quantity, stock_quantity, threshold, barcode
            ))
            sync_product_units(conn, cursor.lastrowid, sale_price, json.dumps(units), commit=False)
            if barcode:
                seen_barcodes.add(barcode)
            imported += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        return jsonify({'error': f"Échec de l'importation : {exc}"}), 500
    conn.close()
    return jsonify({'imported': imported, 'errors': errors})


@app.route('/api/products', methods=['POST'])
@permission_required('catalog.manage')
def add_product():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Le nom du produit est obligatoire.'}), 400

    category = request.form.get('category', 'Auto')
    purchase_price = float(request.form.get('purchase_price', 0))
    transport_cost = float(request.form.get('transport_cost', 0))
    cost_price = purchase_price + transport_cost
    raw_units = request.form.get('units_json')
    sale_price = float(request.form.get('sale_price', 0))
    if raw_units:
        sale_price = parse_product_units(raw_units, sale_price)[0]['sale_price']
    stock_quantity = int(request.form.get('stock_quantity', 0))
    initial_stock = int(request.form.get('initial_stock', stock_quantity))
    if initial_stock <= 0:
        initial_stock = stock_quantity

    custom_threshold = request.form.get('alert_threshold_percent')
    if custom_threshold:
        alert_threshold_percent = int(custom_threshold)
    else:
        if category == 'Forte rotation':
            alert_threshold_percent = 20
        elif category == 'Faible rotation':
            alert_threshold_percent = 10
        else:
            alert_threshold_percent = 20

    barcode = request.form.get('barcode', '').strip()
    image_path = ''

    # Traitement image
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            fname = f"prod_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            file.save(fpath)

            # Optimisation & redimensionnement avec PIL si image matricielle
            if ext in {'jpg', 'jpeg', 'png', 'webp'}:
                try:
                    with Image.open(fpath) as img:
                        img.thumbnail((600, 600))
                        img.save(fpath, optimize=True, quality=85)
                except Exception as e:
                    print("Erreur optimisation image:", e)

            image_path = f"/uploads/{fname}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO products (name, category, purchase_price, transport_cost, cost_price, sale_price, stock_quantity, initial_stock, alert_threshold_percent, image_path, barcode)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, category, purchase_price, transport_cost, cost_price, sale_price, stock_quantity, initial_stock, alert_threshold_percent, image_path, barcode))
    conn.commit()
    prod_id = cursor.lastrowid
    try:
        sync_product_units(conn, prod_id, sale_price, request.form.get('units_json'))
    except ValueError as exc:
        conn.rollback()
        conn.execute('DELETE FROM products WHERE id = ?', (prod_id,))
        conn.commit()
        conn.close()
        return jsonify({'error': str(exc)}), 400
    conn.close()

    return jsonify({'success': True, 'product_id': prod_id, 'message': 'Produit créé avec succès.'})

@app.route('/api/products/auto-classify-all', methods=['POST'])
@permission_required('catalog.manage')
def auto_classify_all_products():
    conn = get_db_connection()
    conn.execute("UPDATE products SET category = 'Auto'")
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Tous les produits sont maintenant en mode rotation automatique basée sur les ventes réelles.'})

@app.route('/api/products/<int:id>', methods=['PUT', 'POST'])
@permission_required('catalog.manage')
def update_product(id):
    conn = get_db_connection()
    existing = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'error': 'Produit introuvable.'}), 404

    name = request.form.get('name', existing['name']).strip()
    category = request.form.get('category', existing['category'])
    purchase_price = float(request.form.get('purchase_price', existing['purchase_price']))
    transport_cost = float(request.form.get('transport_cost', existing['transport_cost']))
    cost_price = purchase_price + transport_cost
    sale_price = float(request.form.get('sale_price', existing['sale_price']))
    raw_units = request.form.get('units_json')
    if raw_units:
        sale_price = parse_product_units(raw_units, sale_price)[0]['sale_price']
    stock_quantity = int(request.form.get('stock_quantity', existing['stock_quantity']))
    initial_stock = int(request.form.get('initial_stock', existing['initial_stock']))
    alert_threshold_percent = int(request.form.get('alert_threshold_percent', existing['alert_threshold_percent']))
    barcode = request.form.get('barcode', existing['barcode']).strip()
    image_path = existing['image_path']

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            fname = f"prod_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            file.save(fpath)
            if ext in {'jpg', 'jpeg', 'png', 'webp'}:
                try:
                    with Image.open(fpath) as img:
                        img.thumbnail((600, 600))
                        img.save(fpath, optimize=True, quality=85)
                except Exception as e:
                    print("Erreur thumbnail:", e)
            image_path = f"/uploads/{fname}"

    conn.execute('''
    UPDATE products SET
        name = ?, category = ?, purchase_price = ?, transport_cost = ?,
        cost_price = ?, sale_price = ?, stock_quantity = ?, initial_stock = ?,
        alert_threshold_percent = ?, image_path = ?, barcode = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (name, category, purchase_price, transport_cost, cost_price, sale_price, stock_quantity, initial_stock, alert_threshold_percent, image_path, barcode, id))
    try:
        sync_product_units(conn, id, sale_price, request.form.get('units_json'))
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(exc)}), 400
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Produit mis à jour.'})

@app.route('/api/products/<int:id>/restock', methods=['POST'])
@permission_required('stock.manage')
def restock_product(id):
    data = request.get_json(force=True)
    qty = int(data.get('quantity', 0))
    if qty <= 0:
        return jsonify({'error': 'Quantité invalide.'}), 400

    conn = get_db_connection()
    prod = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    if not prod:
        conn.close()
        return jsonify({'error': 'Produit introuvable.'}), 404

    unit_name = str(data.get('unit_name', 'Pièce')).strip() or 'Pièce'
    unit = conn.execute(
        'SELECT conversion_factor FROM product_units WHERE product_id = ? AND name = ? COLLATE NOCASE',
        (id, unit_name)
    ).fetchone()
    if not unit:
        conn.close()
        return jsonify({'error': 'Unité de ravitaillement invalide pour ce produit.'}), 400

    conversion_factor = int(unit['conversion_factor'])
    if conversion_factor <= 0:
        conn.close()
        return jsonify({'error': 'Facteur de conversion invalide.'}), 400

    added_stock = qty * conversion_factor
    new_stock = prod['stock_quantity'] + added_stock
    new_initial = max(prod['initial_stock'], new_stock)
    conn.execute('UPDATE products SET stock_quantity = ?, initial_stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (new_stock, new_initial, id))
    conn.execute('''
        INSERT INTO stock_movements
        (product_id, operation_type, quantity, stock_before, stock_after, reason, reference)
        VALUES (?, 'IN', ?, ?, ?, ?, ?)
    ''', (id, added_stock, prod['stock_quantity'], new_stock, f"Achat en {unit_name}", f"RAV-{datetime.now().strftime('%Y%m%d%H%M%S')}"))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'new_stock': new_stock,
        'added_stock': added_stock,
        'message': f"Ravitaillement effectué (+{added_stock} pièce(s))."
    })

@app.route('/api/stock/movements', methods=['GET'])
@permission_required('inventory.manage')
def get_stock_movements():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT m.*, p.name AS product_name
        FROM stock_movements m
        JOIN products p ON p.id = m.product_id
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT 500
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/api/stock/movements', methods=['POST'])
@permission_required('inventory.manage')
def add_stock_movement():
    data = request.get_json(force=True)
    product_id = data.get('product_id')
    operation_type = str(data.get('operation_type', '')).upper()
    quantity = int(data.get('quantity', 0))
    reason = str(data.get('reason', '')).strip()

    if operation_type not in ('IN', 'OUT'):
        return jsonify({'error': "Le type d'opération doit être Entrée ou Sortie."}), 400
    if quantity <= 0:
        return jsonify({'error': 'La quantité doit être supérieure à zéro.'}), 400

    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        conn.close()
        return jsonify({'error': 'Produit introuvable.'}), 404

    stock_before = product['stock_quantity']
    stock_after = stock_before + quantity if operation_type == 'IN' else stock_before - quantity
    if stock_after < 0:
        conn.close()
        return jsonify({'error': 'Le stock ne peut pas devenir négatif.'}), 400

    conn.execute(
        'UPDATE products SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (stock_after, product_id)
    )
    conn.execute('''
        INSERT INTO stock_movements
        (product_id, operation_type, quantity, stock_before, stock_after, reason, reference)
        VALUES (?, ?, ?, ?, ?, ?, 'AJUSTEMENT')
    ''', (product_id, operation_type, quantity, stock_before, stock_after, reason))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'stock_before': stock_before, 'stock_after': stock_after})

@app.route('/api/products/<int:id>', methods=['DELETE'])
@permission_required('catalog.manage')
def delete_product(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM products WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Produit supprimé.'})

# ================= CLIENTS =================
@app.route('/api/customers', methods=['GET'])
@login_required
def get_customers():
    conn = get_db_connection()
    customers = conn.execute('SELECT * FROM customers ORDER BY total_spent DESC, name ASC').fetchall()
    conn.close()
    return jsonify([dict(c) for c in customers])

@app.route('/api/customers', methods=['POST'])
@permission_required('catalog.manage')
def add_customer():
    data = request.get_json(force=True)
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    notes = data.get('notes', '').strip()

    if not name or not phone:
        return jsonify({'error': 'Le nom et le numéro de téléphone sont requis.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO customers (name, phone, notes) VALUES (?, ?, ?)', (name, phone, notes))
        conn.commit()
        cust_id = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'customer_id': cust_id, 'name': name, 'phone': phone})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Un client avec ce numéro de téléphone existe déjà.'}), 400

# ================= VENTES & CAISSE (POS) =================
@app.route('/api/sales', methods=['POST'])
@permission_required('sales.create')
def create_sale():
    data = request.get_json(force=True)
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'Le panier est vide.'}), 400

    payment_method = data.get('payment_method', 'Espèces')
    amount_received = float(data.get('amount_received', 0))
    global_discount_type = str(data.get('discount_type', 'amount')).lower()
    if global_discount_type != 'amount':
        global_discount_type = 'amount'
    requested_global_discount = max(0.0, float(data.get('discount', 0) or 0))
    customer_id = data.get('customer_id')
    receipt_type = data.get('receipt_type', 'thermal')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Récupérer client
        customer_name = 'Client Passant'
        customer_phone = ''
        if customer_id:
            c = cursor.execute('SELECT * FROM customers WHERE id = ?', (customer_id,)).fetchone()
            if c:
                customer_name = c['name']
                customer_phone = c['phone']

        subtotal = 0.0
        total_cost = 0.0
        processed_items = []

        # Vérification et décrémentation des stocks
        for item in items:
            pid = item['product_id']
            qty = int(item['quantity'])
            if qty <= 0:
                continue

            prod = cursor.execute('SELECT * FROM products WHERE id = ?', (pid,)).fetchone()
            if not prod:
                raise ValueError(f"Produit ID {pid} introuvable.")

            unit_id = item.get('unit_id')
            if unit_id:
                unit = cursor.execute(
                    'SELECT * FROM product_units WHERE id = ? AND product_id = ?',
                    (unit_id, pid)
                ).fetchone()
            else:
                unit = cursor.execute(
                    'SELECT * FROM product_units WHERE product_id = ? AND is_base = 1 LIMIT 1',
                    (pid,)
                ).fetchone()
            if not unit:
                raise ValueError(f"Conditionnement invalide pour '{prod['name']}'.")

            base_qty = qty * int(unit['conversion_factor'])
            if prod['stock_quantity'] < base_qty:
                raise ValueError(f"Stock insuffisant pour '{prod['name']}'. Disponible: {prod['stock_quantity']}, Demandé: {base_qty}")

            unit_price = float(unit['sale_price'])
            line_subtotal = unit_price * qty
            line_cost = prod['cost_price'] * base_qty
            line_discount_type = str(item.get('discount_type', 'fixed_price')).lower()
            if line_discount_type not in ('amount', 'percent', 'fixed_price'):
                line_discount_type = 'fixed_price'
            requested_line_discount = max(0.0, float(item.get('discount', 0) or 0))
            if line_discount_type == 'percent':
                line_discount_type = 'amount'
                line_discount = min(requested_line_discount, line_subtotal)
            elif line_discount_type == 'fixed_price':
                line_discount = min(requested_line_discount * qty, line_subtotal)
                line_net = max(0.0, line_subtotal - line_discount)
            else:
                line_discount = min(requested_line_discount, line_subtotal)

            if line_discount_type != 'fixed_price':
                line_net = max(0.0, line_subtotal - line_discount)
            line_profit = line_net - line_cost

            subtotal += line_subtotal
            total_cost += line_cost

            # Décrémenter stock
            cursor.execute('UPDATE products SET stock_quantity = stock_quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (base_qty, pid))

            processed_items.append({
                'product_id': pid,
                'product_name': prod['name'],
                'unit_cost': prod['cost_price'],
                'unit_price': unit_price,
                'quantity': qty,
                'unit_name': unit['name'],
                'unit_factor': int(unit['conversion_factor']),
                'base_quantity': base_qty,
                'subtotal': line_subtotal,
                'discount': line_discount,
                'net_total': line_net,
                'profit': line_profit
            })

        if global_discount_type == 'percent':
            if requested_global_discount > 100:
                raise ValueError("La remise globale ne peut dépasser 100 %.")
            discount = sum(it['net_total'] for it in processed_items) * requested_global_discount / 100
        else:
            discount = min(requested_global_discount, sum(it['net_total'] for it in processed_items))

        total_amount = max(0.0, sum(it['net_total'] for it in processed_items) - discount)
        total_item_discounts = sum(it['discount'] for it in processed_items)
        recorded_discount = total_item_discounts + discount
        profit = total_amount - total_cost

        if amount_received < total_amount and payment_method == 'Espèces':
            amount_received = total_amount  # Valeur par défaut
        change_returned = max(0.0, amount_received - total_amount) if payment_method == 'Espèces' else 0.0

        # Génération du code de vente unique
        today_str = datetime.now().strftime('%Y%m%d')
        cursor.execute("SELECT COUNT(*) FROM sales WHERE sale_code LIKE ?", (f"VTE-{today_str}-%",))
        count_today = cursor.fetchone()[0] + 1
        sale_code = f"VTE-{today_str}-{count_today:04d}"

        # Insertion de la vente
        cursor.execute('''
        INSERT INTO sales (sale_code, customer_id, customer_name, customer_phone, subtotal, discount, total_amount, total_cost, profit, payment_method, amount_received, change_returned, receipt_type, status, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?)
        ''', (sale_code, customer_id, customer_name, customer_phone, subtotal, recorded_discount, total_amount, total_cost, profit, payment_method, amount_received, change_returned, receipt_type, g.user['id']))

        sale_id = cursor.lastrowid

        # Insertion des lignes
        for it in processed_items:
            cursor.execute('''
            INSERT INTO sale_items (sale_id, product_id, product_name, unit_cost, unit_price, quantity, unit_name, unit_factor, subtotal, discount, profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (sale_id, it['product_id'], it['product_name'], it['unit_cost'], it['unit_price'], it['quantity'], it['unit_name'], it['unit_factor'], it['net_total'], it['discount'], it['profit']))
            stock_after = cursor.execute(
                'SELECT stock_quantity FROM products WHERE id = ?', (it['product_id'],)
            ).fetchone()[0]
            cursor.execute('''
                INSERT INTO stock_movements
                (product_id, operation_type, quantity, stock_before, stock_after, reason, reference)
                VALUES (?, 'OUT', ?, ?, ?, 'VENTE', ?)
            ''', (
                it['product_id'],
                it['base_quantity'],
                stock_after + it['base_quantity'],
                stock_after,
                sale_code
            ))

        # Mise à jour cumul client
        if customer_id:
            cursor.execute('''
            UPDATE customers SET
                total_spent = total_spent + ?,
                orders_count = orders_count + 1
            WHERE id = ?
            ''', (total_amount, customer_id))

        conn.commit()

        # Sauvegarde automatique du reçu sur le disque
        try:
            settings_row = cursor.execute('SELECT * FROM settings WHERE id = 1').fetchone()
            settings = dict(settings_row) if settings_row else {}
            sale_dict = {
                'id': sale_id,
                'sale_code': sale_code,
                'customer_name': customer_name,
                'customer_phone': customer_phone,
                'subtotal': subtotal,
                'discount': recorded_discount,
                'item_discount': total_item_discounts,
                'global_discount': discount,
                'total_amount': total_amount,
                'payment_method': payment_method,
                'amount_received': amount_received,
                'change_returned': change_returned,
                'created_at': datetime.now().strftime('%d/%m/%Y %H:%M')
            }
            tmpl_name = 'receipt_thermal.html' if receipt_type == 'thermal' else 'receipt_a4.html'
            rendered_html = render_template(tmpl_name, sale=sale_dict, items=processed_items, settings=settings)
            receipt_file = os.path.join(RECEIPTS_DIR, f"{sale_code}.html")
            with open(receipt_file, 'w', encoding='utf-8') as rf:
                rf.write(rendered_html)
        except Exception as e:
            print("Erreur sauvegarde locale du reçu:", e)

        conn.close()
        return jsonify({
            'success': True,
            'sale_id': sale_id,
            'sale_code': sale_code,
            'subtotal': subtotal,
            'item_discount': total_item_discounts,
            'total_amount': total_amount,
            'receipt_url': f"/api/sales/{sale_id}/receipt?format={receipt_type}"
        })

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 400

# ================= HISTORIQUE & JOURNAL DES VENTES =================
@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    conn = get_db_connection()
    if g.user['role_name'] == 'VENDEUR':
        sales_db = conn.execute(
            '''SELECT sales.*, u.full_name AS seller_name, u.username AS seller_username
               FROM sales LEFT JOIN users u ON u.id = sales.user_id
               WHERE sales.user_id = ? ORDER BY sales.id DESC LIMIT 200''',
            (g.user['id'],)
        ).fetchall()
    else:
        sales_db = conn.execute(
            '''SELECT sales.*, u.full_name AS seller_name, u.username AS seller_username
               FROM sales LEFT JOIN users u ON u.id = sales.user_id
               ORDER BY sales.id DESC LIMIT 200'''
        ).fetchall()

    sales = []
    for s in sales_db:
        sale_dict = dict(s)
        items_db = conn.execute('SELECT * FROM sale_items WHERE sale_id = ?', (sale_dict['id'],)).fetchall()
        sale_dict['items'] = [dict(it) for it in items_db]
        sales.append(sale_dict)

    conn.close()
    return jsonify(sales)

@app.route('/api/sales/<int:id>/receipt')
@login_required
def view_receipt(id):
    fmt = request.args.get('format', 'thermal')
    conn = get_db_connection()
    sale = conn.execute('SELECT * FROM sales WHERE id = ?', (id,)).fetchone()
    if not sale:
        conn.close()
        return "Reçu non trouvé", 404
    if g.user['role_name'] == 'VENDEUR' and sale['user_id'] != g.user['id']:
        conn.close()
        return "Accès refusé", 403

    items = conn.execute('SELECT * FROM sale_items WHERE sale_id = ?', (id,)).fetchall()
    settings = conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
    conn.close()

    tmpl = 'receipt_thermal.html' if fmt == 'thermal' else 'receipt_a4.html'
    return render_template(tmpl, sale=dict(sale), items=[dict(i) for i in items], settings=dict(settings))

@app.route('/api/sales/<int:id>/cancel', methods=['POST'])
@permission_required('sales.cancel')
def cancel_sale(id):
    data = request.get_json(force=True)
    reason = data.get('reason', '').strip()
    if not reason:
        return jsonify({'error': 'Le motif d\'annulation est strictement obligatoire.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    sale = cursor.execute('SELECT * FROM sales WHERE id = ?', (id,)).fetchone()
    if not sale:
        conn.close()
        return jsonify({'error': 'Vente non trouvée.'}), 404

    if sale['status'] == 'CANCELLED':
        conn.close()
        return jsonify({'error': 'Cette vente a déjà été annulée.'}), 400

    # Restituer le stock de chaque article
    items = cursor.execute('SELECT * FROM sale_items WHERE sale_id = ?', (id,)).fetchall()
    for item in items:
        restored = item['quantity'] * item['unit_factor']
        stock_before = cursor.execute(
            'SELECT stock_quantity FROM products WHERE id = ?', (item['product_id'],)
        ).fetchone()[0]
        cursor.execute(
            'UPDATE products SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (restored, item['product_id'])
        )
        cursor.execute('''
            INSERT INTO stock_movements
            (product_id, operation_type, quantity, stock_before, stock_after, reason, reference)
            VALUES (?, 'IN', ?, ?, ?, ?, ?)
        ''', (
            item['product_id'], restored, stock_before, stock_before + restored,
            'ANNULATION DE VENTE', sale['sale_code']
        ))

    # Si rattaché à un client, déduire du cumul
    if sale['customer_id']:
        cursor.execute('''
        UPDATE customers SET
            total_spent = max(0, total_spent - ?),
            orders_count = max(0, orders_count - 1)
        WHERE id = ?
        ''', (sale['total_amount'], sale['customer_id']))

    # Marquer vente annulée
    cursor.execute('''
    UPDATE sales SET
        status = 'CANCELLED',
        cancellation_reason = ?,
        cancelled_at = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (reason, id))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Vente annulée avec succès et stocks réintégrés.'})

# ================= CLÔTURE DE CAISSE (RAPPORT Z) =================
@app.route('/api/closing/today', methods=['GET'])
@permission_required('settings.manage')
def get_today_closing():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()

    summary = conn.execute('''
    SELECT 
        COUNT(*) as total_sales_count,
        COALESCE(SUM(CASE WHEN payment_method = 'Espèces' THEN total_amount ELSE 0 END), 0) as total_cash,
        COALESCE(SUM(CASE WHEN payment_method != 'Espèces' THEN total_amount ELSE 0 END), 0) as total_momo,
        COALESCE(SUM(total_amount), 0) as total_revenue,
        COALESCE(SUM(total_cost), 0) as total_cost,
        COALESCE(SUM(profit), 0) as total_profit
    FROM sales
    WHERE DATE(created_at) = DATE(?) AND status = 'COMPLETED'
    ''', (today,)).fetchone()

    # Vérifier si déjà clôturé aujourd'hui
    existing_closing = conn.execute('SELECT * FROM daily_closings WHERE closing_date = ?', (today,)).fetchone()
    conn.close()

    res = dict(summary)
    res['today_date'] = datetime.now().strftime('%d/%m/%Y')
    res['is_already_closed'] = existing_closing is not None
    if existing_closing:
        res['closed_at'] = existing_closing['closed_at']
    return jsonify(res)

@app.route('/api/closing/close', methods=['POST'])
@permission_required('settings.manage')
def save_daily_closing():
    today = datetime.now().strftime('%Y-%m-%d')
    data = request.get_json(force=True) if request.data else {}
    notes = data.get('notes', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    summary = cursor.execute('''
    SELECT 
        COUNT(*) as total_sales_count,
        COALESCE(SUM(CASE WHEN payment_method = 'Espèces' THEN total_amount ELSE 0 END), 0) as total_cash,
        COALESCE(SUM(CASE WHEN payment_method != 'Espèces' THEN total_amount ELSE 0 END), 0) as total_momo,
        COALESCE(SUM(total_amount), 0) as total_revenue,
        COALESCE(SUM(total_cost), 0) as total_cost,
        COALESCE(SUM(profit), 0) as total_profit
    FROM sales
    WHERE DATE(created_at) = DATE(?) AND status = 'COMPLETED'
    ''', (today,)).fetchone()

    cursor.execute('''
    INSERT INTO daily_closings (closing_date, total_sales_count, total_cash, total_mobile_money, total_revenue, total_cost, total_profit, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(closing_date) DO UPDATE SET
        total_sales_count=excluded.total_sales_count,
        total_cash=excluded.total_cash,
        total_mobile_money=excluded.total_mobile_money,
        total_revenue=excluded.total_revenue,
        total_cost=excluded.total_cost,
        total_profit=excluded.total_profit,
        closed_at=CURRENT_TIMESTAMP,
        notes=excluded.notes
    ''', (today, summary['total_sales_count'], summary['total_cash'], summary['total_momo'], summary['total_revenue'], summary['total_cost'], summary['total_profit'], notes))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Clôture de caisse du jour validée et enregistrée !'})

# ================= ALERTES DE STOCK =================
@app.route('/api/alerts', methods=['GET'])
@permission_required('stock.manage')
def get_alerts():
    conn = get_db_connection()
    products_db = conn.execute('SELECT * FROM products ORDER BY stock_quantity ASC').fetchall()
    metrics = get_products_sales_metrics(conn)
    conn.close()

    alerts = []
    for row in products_db:
        p = dict(row)
        eval_res = evaluate_product_rotation(p, metrics)
        p['category'] = eval_res['effective_category']
        p['raw_category'] = eval_res['raw_category']
        p['rotation_status'] = eval_res['rotation_status']
        p['rotation_reason'] = eval_res['rotation_reason']
        p['is_auto'] = eval_res['is_auto']
        p['alert_threshold_percent'] = eval_res['effective_threshold']

        status_key, status_label = compute_stock_status(p['stock_quantity'], p['initial_stock'], eval_res['effective_threshold'])
        if status_key in ('alert', 'out'):
            p['status_key'] = status_key
            p['status_label'] = status_label
            alerts.append(p)

    return jsonify(alerts)

# ================= PARAMÈTRES BOUTIQUE & PAPIER À EN-TÊTE =================
@app.route('/api/settings', methods=['GET'])
@permission_required('settings.manage')
def get_settings():
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})

@app.route('/api/settings', methods=['POST'])
@permission_required('settings.manage')
def update_settings():
    company_name = request.form.get('company_name', '').strip()
    company_slogan = request.form.get('company_slogan', '').strip()
    company_phone = request.form.get('company_phone', '').strip()
    company_address = request.form.get('company_address', '').strip()
    company_nif_rccm = request.form.get('company_nif_rccm', '').strip()
    receipt_footer = request.form.get('receipt_footer', '').strip()
    currency = request.form.get('currency', 'FCFA').strip()
    default_receipt_format = request.form.get('default_receipt_format', 'thermal').strip()

    conn = get_db_connection()
    existing = conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
    company_logo = existing['company_logo'] if existing else ''

    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            fname = f"logo_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            file.save(fpath)
            company_logo = f"/uploads/{fname}"

    conn.execute('''
    UPDATE settings SET
        company_name = ?, company_slogan = ?, company_phone = ?,
        company_address = ?, company_nif_rccm = ?, receipt_footer = ?,
        currency = ?, default_receipt_format = ?, company_logo = ?
    WHERE id = 1
    ''', (company_name, company_slogan, company_phone, company_address, company_nif_rccm, receipt_footer, currency, default_receipt_format, company_logo))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Paramètres de l\'en-tête enregistrés.'})

# ================= SAUVEGARDE LOCALE =================
@app.route('/api/backup/export', methods=['GET'])
@permission_required('backup.manage')
def export_backup():
    backup_filename = f"backup_pos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(DATA_DIR, backup_filename)
    try:
        shutil.copyfile(DB_PATH, backup_path)
        return send_from_directory(DATA_DIR, backup_filename, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ================= DÉMARRAGE DU LOGICIEL DESKTOP =================
def run_desktop():
    init_db()

    # Si argument --browser, exécuter le serveur web Flask classique
    if '--browser' in sys.argv:
        import webbrowser
        port = 5055
        webbrowser.open(f'http://127.0.0.1:{port}')
        app.run(host='127.0.0.1', port=port, debug=False)
        return

    # Mode Desktop natif avec PyWebView
    try:
        import webview
        # Démarrer Flask dans un thread séparé
        import threading
        port = 5055

        def start_flask():
            app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        # Fenêtre Desktop Odoo Style
        window = webview.create_window(
            title='GEST-STOCK POS | Logiciel de Caisse & Stock',
            url=f'http://127.0.0.1:{port}',
            width=1280,
            height=820,
            min_size=(1024, 680),
            confirm_close=True
        )
        webview.start()
    except Exception as e:
        print("Erreur pywebview, passage en mode navigateur:", e)
        import webbrowser
        port = 5055
        webbrowser.open(f'http://127.0.0.1:{port}')
        app.run(host='127.0.0.1', port=port, debug=False)

if __name__ == '__main__':
    run_desktop()
