// ================= GEST-STOCK POS - LOGIQUE FRONT-END =================

let state = {
  products: [],
  filteredProducts: [],
  customers: [],
  sales: [],
  alerts: [],
  cart: [],
  selectedCustomer: null,
  activeCategory: 'all',
  settings: {
    currency: 'FCFA',
    default_receipt_format: 'thermal',
    company_name: 'GEST-STOCK POS'
  }
};

function getCartItemDiscount(item) {
    const value = Math.max(0, parseFloat(item.discount_value) || 0);
    if (item.discount_type === 'percent') {
      return Math.min(item.subtotal, item.subtotal * Math.min(100, value) / 100);
    }
    if (item.discount_type === 'fixed_price') {
      return Math.min(item.subtotal, value * item.quantity);
    }
    return Math.min(item.subtotal, value);
  }

  function getCartItemNet(item) {
    if (item.discount_type === 'fixed_price') {
      const value = Math.max(0, parseFloat(item.discount_value) || 0);
      const discount = Math.min(item.subtotal, value * item.quantity);
      return Math.max(0, item.subtotal - discount);
    }
    return Math.max(0, item.subtotal - getCartItemDiscount(item));
  }

  function getCartTotals() {
    const subtotal = state.cart.reduce((sum, it) => sum + it.subtotal, 0);
    const itemDiscount = state.cart.reduce((sum, it) => sum + getCartItemDiscount(it), 0);
    const globalType = document.getElementById('cart-discount-type')?.value || 'amount';
    const globalValue = Math.max(0, parseFloat(document.getElementById('cart-discount-input')?.value) || 0);
    const afterItems = Math.max(0, subtotal - itemDiscount);
    const globalDiscount = globalType === 'percent'
      ? afterItems * Math.min(100, globalValue) / 100
      : Math.min(afterItems, globalValue);
    return { subtotal, itemDiscount, globalDiscount, total: Math.max(0, afterItems - globalDiscount) };
  }

function updateItemDiscount(productId, field, value, unitId = null) {
  const item = state.cart.find(it => it.product_id === productId && Number(it.unit_id) === Number(unitId));
  if (!item) return;
  if (field === 'type') {
    item.discount_type = value;
    if (value === 'fixed_price' && (!item.discount_value || item.discount_value === 0)) {
      item.discount_value = 0;
    }
  } else {
    item.discount_value = parseFloat(value) || 0;
  }
  renderCart();
}

// --- INITIALISATION AU CHARGEMENT DE LA PAGE ---
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  loadProducts();
  loadCustomers();
  loadAlerts();
});

// Formatage FCFA (ex: 15 000 FCFA)
function formatMoney(amount) {
  if (amount === undefined || amount === null || isNaN(amount)) amount = 0;
  return Math.round(amount).toLocaleString('fr-FR').replace(/\s/g, ' ') + ' ' + (state.settings.currency || 'FCFA');
}

// --- NAVIGATION ENTRE VUES ---
function switchView(viewName) {
  document.querySelectorAll('.view-panel').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.odoo-nav-btn').forEach(btn => btn.classList.remove('active'));

  const targetView = document.getElementById(`view-view-${viewName}`) || document.getElementById(`view-${viewName}`);
  if (targetView) targetView.classList.add('active');

  const navBtns = document.querySelectorAll('.odoo-nav-btn');
  navBtns.forEach(btn => {
    if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(viewName)) {
      btn.classList.add('active');
    }
  });

  // Rafraîchir les données de la vue activée
  if (viewName === 'pos') {
    renderPosProducts();
    updateCartTotals();
  } else if (viewName === 'products') {
    loadProductsTable();
  } else if (viewName === 'sales') {
    loadSalesTable();
  } else if (viewName === 'alerts') {
    loadAlertsView();
  } else if (viewName === 'customers') {
    loadCustomersTable();
  } else if (viewName === 'closing') {
    loadClosingData();
  }
}

// --- GESTION DU CATALOGUE & DES PRODUITS ---
async function loadProducts() {
  try {
    const res = await fetch('/api/products');
    state.products = await res.json();
    state.filteredProducts = [...state.products];
    renderPosProducts();
    loadAlerts();
  } catch (err) {
    console.error('Erreur chargement produits:', err);
  }
}

function setPosCategory(category, btnElement) {
  state.activeCategory = category;
  document.querySelectorAll('.cat-chip').forEach(el => el.classList.remove('active'));
  if (btnElement) btnElement.classList.add('active');
  filterPosProducts();
}

function filterPosProducts() {
  const query = (document.getElementById('pos-search-input').value || '').toLowerCase().trim();
  state.filteredProducts = state.products.filter(p => {
    let matchCat = false;
    if (state.activeCategory === 'all') {
      matchCat = true;
    } else if (state.activeCategory === 'Forte rotation') {
      matchCat = (p.category === 'Forte rotation');
    } else if (state.activeCategory === 'Faible rotation') {
      matchCat = (p.category === 'Faible rotation');
    } else if (state.activeCategory === 'Standard') {
      matchCat = (p.category === 'Standard' || p.category === 'Nouveau' || p.category === 'Auto');
    } else {
      matchCat = (p.category === state.activeCategory);
    }
    const matchQuery = !query || p.name.toLowerCase().includes(query) || (p.barcode && p.barcode.toLowerCase().includes(query));
    return matchCat && matchQuery;
  });
  renderPosProducts();
}

function renderPosProducts() {
  const container = document.getElementById('pos-products-grid');
  if (!container) return;

  if (state.filteredProducts.length === 0) {
    container.innerHTML = `
      <div class="col-12 text-center text-muted py-5">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#94a3b8" stroke-width="1.5"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <p class="mt-2 mb-0">Aucun produit ne correspond.</p>
        <button class="btn btn-sm btn-link text-primary mt-1" onclick="openProductModal()">+ Créer ce produit</button>
      </div>`;
    return;
  }

  container.innerHTML = state.filteredProducts.map(p => {
    const isOut = p.stock_quantity <= 0;
    const isAlert = p.status_key === 'alert';
    const isBestSeller = (p.category === 'Forte rotation');
    const imgSrc = p.image_path || '/static/img/default_product.svg';

    let badgeClass = 'stock-normal';
    let badgeText = `${p.stock_quantity} en stock`;
    if (isOut) {
      badgeClass = 'stock-out';
      badgeText = 'Épuisé';
    } else if (isAlert) {
      badgeClass = 'stock-alert';
      badgeText = `Alerte (${p.stock_quantity})`;
    }

    const bestSellerTag = isBestSeller ? `
      <span class="badge bg-danger shadow-sm position-absolute top-0 start-0 m-2" style="font-size:0.65rem;border-radius:6px;z-index:2;letter-spacing:0.3px;">
        🔥 Best-seller
      </span>
    ` : '';

    const units = p.units && p.units.length ? p.units : [{ id: null, name: 'Pièce', conversion_factor: 1, sale_price: p.sale_price }];
    const unitOptions = units.map(unit => `<option value="${unit.id || ''}" data-factor="${unit.conversion_factor}" data-price="${unit.sale_price}">${unit.name} — ${formatMoney(unit.sale_price)}</option>`).join('');
    return `
      <div class="product-card position-relative ${isOut ? 'out-of-stock' : ''}" onclick="${isOut ? '' : `addToCart(${p.id})`}">
        ${bestSellerTag}
        <div class="product-img-wrapper">
          <img src="${imgSrc}" class="product-img" alt="${p.name}" loading="lazy">
        </div>
        <div class="product-card-body">
          <div class="product-name" title="${p.name}">${p.name}</div>
          <select class="form-select form-select-sm product-unit-select mb-2" onclick="event.stopPropagation()" onchange="event.stopPropagation()" aria-label="Unité de vente">
            ${unitOptions}
          </select>
          <div class="product-meta">
            <span class="product-price">${formatMoney(p.sale_price)}</span>
            <span class="stock-badge ${badgeClass}">${badgeText}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// --- GESTION DU PANIER & CAISSE (POS) ---
function addToCart(productId, unitId = null) {
  const product = state.products.find(p => p.id === productId);
  if (!product) return;

  if (product.stock_quantity <= 0) {
    alert("Cet article est en rupture de stock.");
    return;
  }

  const card = document.querySelector(`.product-card[onclick*="addToCart(${productId})"]`);
  const unitSelect = card ? card.querySelector('.product-unit-select') : null;
  const selectedUnitId = unitId || (unitSelect && unitSelect.value ? Number(unitSelect.value) : null);
  const units = product.units && product.units.length ? product.units : [{ id: null, name: 'Pièce', conversion_factor: 1, sale_price: product.sale_price }];
  const unit = units.find(candidate => candidate.id === selectedUnitId) || units.find(candidate => candidate.is_base) || units[0];
  const existing = state.cart.find(it => it.product_id === productId && Number(it.unit_id) === Number(unit.id));
  const cartBaseQty = state.cart
    .filter(it => it.product_id === productId)
    .reduce((sum, it) => sum + it.quantity * it.unit_factor, 0);
  if (existing) {
    const baseQty = cartBaseQty + unit.conversion_factor;
    if (baseQty > product.stock_quantity) {
      alert(`Stock maximum disponible atteint (${product.stock_quantity}).`);
      return;
    }
    existing.quantity += 1;
    existing.subtotal = existing.quantity * existing.price;
  } else {
    if (cartBaseQty + unit.conversion_factor > product.stock_quantity) {
      alert(`Stock maximum disponible atteint (${product.stock_quantity}).`);
      return;
    }
    state.cart.push({
      product_id: product.id,
      name: product.name,
      unit_id: unit.id,
      unit_name: unit.name,
      unit_factor: unit.conversion_factor,
      price: unit.sale_price,
      cost: product.cost_price,
      quantity: 1,
      max_stock: product.stock_quantity,
      subtotal: unit.sale_price,
      discount_type: 'amount',
      discount_value: 0
    });
  }

  renderCart();
}

function updateCartQty(productId, delta, unitId = null) {
  const item = state.cart.find(it => it.product_id === productId && Number(it.unit_id) === Number(unitId));
  if (!item) return;

  const newQty = item.quantity + delta;
  if (newQty <= 0) {
    removeFromCart(productId);
    return;
  }
  const otherBaseQty = state.cart
    .filter(it => it.product_id === productId && !(Number(it.unit_id) === Number(unitId)))
    .reduce((sum, it) => sum + it.quantity * it.unit_factor, 0);
  if (otherBaseQty + newQty * item.unit_factor > item.max_stock) {
    alert(`Stock maximum disponible atteint (${item.max_stock}).`);
    return;
  }

  item.quantity = newQty;
  item.subtotal = item.quantity * item.price;
  renderCart();
}

function removeFromCart(productId, unitId = null) {
  state.cart = state.cart.filter(it => !(it.product_id === productId && Number(it.unit_id) === Number(unitId)));
  renderCart();
}

function clearCart() {
  if (state.cart.length > 0 && confirm("Voulez-vous vraiment vider le panier en cours ?")) {
    state.cart = [];
    state.selectedCustomer = null;
    updateCustomerDisplay();
    renderCart();
  }
}

function renderCart() {
  const container = document.getElementById('cart-items-container');
  if (!container) return;

  if (state.cart.length === 0) {
    container.innerHTML = `
      <div class="text-center text-muted my-5">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>
        <p class="mt-2 mb-0" style="font-size:0.95rem;">Le panier est vide</p>
        <small class="text-secondary">Cliquez sur une photo de produit pour commencer la vente</small>
      </div>`;
    updateCartTotals();
    return;
  }

  container.innerHTML = state.cart.map(item => `
    <div class="cart-item">
      <div class="cart-item-info">
        <div class="cart-item-title" title="${item.name}">${item.name}</div>
        <div class="cart-item-unit">${item.unit_name} @ ${formatMoney(item.price)}</div>
      </div>
      <div class="cart-qty-ctrl">
        <span class="cart-control-label">Qté :</span>
        <div class="cart-qty-buttons">
          <button class="qty-btn" onclick="updateCartQty(${item.product_id}, -1, ${item.unit_id})" aria-label="Diminuer la quantité">-</button>
          <span class="qty-val">${item.quantity}</span>
          <button class="qty-btn" onclick="updateCartQty(${item.product_id}, 1, ${item.unit_id})" aria-label="Augmenter la quantité">+</button>
        </div>
      </div>
      <div class="cart-item-discount d-flex align-items-center gap-1">
        <span class="cart-control-label">Remise :</span>
        <select class="form-select form-select-sm" style="width:78px" onchange="updateItemDiscount(${item.product_id}, 'type', this.value, ${item.unit_id})">
          <option value="amount" ${item.discount_type === 'amount' ? 'selected' : ''}>Montant</option>
          <option value="percent" ${item.discount_type === 'percent' ? 'selected' : ''}>%</option>
          <option value="fixed_price" ${item.discount_type === 'fixed_price' ? 'selected' : ''}>Remise / pièce</option>
        </select>
        <input type="number" class="form-control form-control-sm" style="width:72px" min="0" max="${item.discount_type === 'percent' ? 100 : (item.discount_type === 'fixed_price' ? item.price : item.subtotal)}" value="${item.discount_value}" placeholder="${item.discount_type === 'fixed_price' ? 'Réduction' : 'Montant'}" aria-label="${item.discount_type === 'fixed_price' ? 'Réduction par pièce' : 'Montant de la remise'}" oninput="updateItemDiscount(${item.product_id}, 'value', this.value, ${item.unit_id})">
      </div>
      <div class="cart-item-total">${formatMoney(getCartItemNet(item))}</div>
      <button class="cart-del-btn" onclick="removeFromCart(${item.product_id}, ${item.unit_id})" title="Supprimer">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </div>
  `).join('');

  updateCartTotals();
}

function updateCartTotals() {
  const count = state.cart.reduce((sum, it) => sum + it.quantity, 0);
  const subtotal = state.cart.reduce((sum, it) => sum + it.subtotal, 0);
  const itemDiscount = state.cart.reduce((sum, it) => sum + getCartItemDiscount(it), 0);
  const globalType = document.getElementById('cart-discount-type')?.value || 'amount';
  const globalValue = Math.max(0, parseFloat(document.getElementById('cart-discount-input')?.value) || 0);
  const afterItems = Math.max(0, subtotal - itemDiscount);
  const globalDiscount = globalType === 'percent'
    ? afterItems * Math.min(100, globalValue) / 100
    : Math.min(afterItems, globalValue);
  const total = Math.max(0, afterItems - globalDiscount);

  document.getElementById('cart-items-count').innerText = count;
  document.getElementById('cart-subtotal-val').innerText = formatMoney(subtotal);
  document.getElementById('cart-total-val').innerText = formatMoney(total);

  const btnPay = document.getElementById('btn-proceed-pay');
  if (btnPay) {
    btnPay.disabled = (state.cart.length === 0);
  }
}

// --- CLIENTS AU NIVEAU DU POS ---
function updateCustomerDisplay() {
  const box = document.getElementById('cart-customer-display');
  const container = document.querySelector('.cart-customer-box');
  if (state.selectedCustomer) {
    container.classList.add('has-customer');
    box.innerHTML = `<span class="text-muted">Client :</span> <strong>${state.selectedCustomer.name}</strong> <span class="badge bg-light text-primary border ms-1">${state.selectedCustomer.phone}</span>`;
  } else {
    container.classList.remove('has-customer');
    box.innerHTML = `<span class="text-muted">Client :</span> <strong>Client Passant</strong>`;
  }
}

function openCustomerSelectModal() {
  filterPosCustomerList();
  const modal = new bootstrap.Modal(document.getElementById('customerSelectModal'));
  modal.show();
}

function filterPosCustomerList() {
  const q = (document.getElementById('cust-search-pos').value || '').toLowerCase();
  const container = document.getElementById('pos-customer-list');

  const filtered = state.customers.filter(c => c.name.toLowerCase().includes(q) || c.phone.includes(q));

  let html = `
    <button class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${!state.selectedCustomer ? 'active' : ''}" onclick="selectCustomer(null)">
      <div>
        <strong>Client Passant</strong>
        <div class="small ${!state.selectedCustomer ? 'text-light' : 'text-muted'}">Vente directe sans fiche client</div>
      </div>
      <span class="badge ${!state.selectedCustomer ? 'bg-light text-dark' : 'bg-secondary'}">Par défaut</span>
    </button>
  `;

  filtered.forEach(c => {
    const isSelected = state.selectedCustomer && state.selectedCustomer.id === c.id;
    html += `
      <button class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${isSelected ? 'active' : ''}" onclick="selectCustomer(${c.id})">
        <div>
          <strong>${c.name}</strong>
          <div class="small ${isSelected ? 'text-light' : 'text-muted'}">📞 ${c.phone}</div>
        </div>
        <div class="text-end">
          <span class="badge ${isSelected ? 'bg-light text-dark' : 'bg-primary'}">${formatMoney(c.total_spent)}</span>
          <div class="small ${isSelected ? 'text-light' : 'text-muted'}">${c.orders_count} achats</div>
        </div>
      </button>
    `;
  });

  container.innerHTML = html;
}

function selectCustomer(customerId) {
  if (customerId === null) {
    state.selectedCustomer = null;
  } else {
    state.selectedCustomer = state.customers.find(c => c.id === customerId) || null;
  }
  updateCustomerDisplay();
  bootstrap.Modal.getInstance(document.getElementById('customerSelectModal')).hide();
}

function openCustomerModalFromPos() {
  bootstrap.Modal.getInstance(document.getElementById('customerSelectModal')).hide();
  openCustomerModal();
}

// --- MODAL DE PAIEMENT & IMPRESSION ---
function openPaymentModal() {
  if (state.cart.length === 0) return;

  const total = getCartTotals().total;

  document.getElementById('pay-modal-total').innerText = formatMoney(total);

  // Par défaut, montant reçu = montant exact
  const cashInput = document.getElementById('pay-amount-received');
  cashInput.value = total;

  // Génération des boutons de raccourcis billets (ex: Total, arrondi supérieur, 5 000, 10 000, 20 000)
  generateQuickCashButtons(total);
  calculateChange();

  // Format de reçu par défaut
  if (state.settings.default_receipt_format === 'a4') {
    document.getElementById('fmt-a4').checked = true;
  } else {
    document.getElementById('fmt-thermal').checked = true;
  }

  const modal = new bootstrap.Modal(document.getElementById('paymentModal'));
  modal.show();
}

function generateQuickCashButtons(total) {
  const container = document.getElementById('quick-cash-buttons');
  const values = [total];

  // Trouver les coupures utiles en FCFA
  const bills = [1000, 2000, 5000, 10000, 20000];
  bills.forEach(b => {
    if (b > total && !values.includes(b)) {
      values.push(b);
    }
  });

  // Arrondi supérieur à 5000 ou 10000
  const rounded5k = Math.ceil(total / 5000) * 5000;
  if (rounded5k > total && !values.includes(rounded5k)) values.push(rounded5k);

  values.sort((a, b) => a - b);

  container.innerHTML = values.slice(0, 4).map(val => `
    <button type="button" class="btn btn-outline-secondary btn-sm flex-fill fw-bold" onclick="setCashAmount(${val})">
      ${val.toLocaleString('fr-FR')}
    </button>
  `).join('');
}

function setCashAmount(val) {
  document.getElementById('pay-amount-received').value = val;
  calculateChange();
}

function togglePaymentInputs() {
  const isCash = document.getElementById('pay-method-cash').checked;
  document.getElementById('cash-payment-section').style.display = isCash ? 'block' : 'none';
  if (!isCash) {
    document.getElementById('pay-amount-received').value = getCartTotals().total;
  }
}

function calculateChange() {
  const total = getCartTotals().total;
  const received = parseFloat(document.getElementById('pay-amount-received').value) || 0;
  const change = Math.max(0, received - total);

  document.getElementById('pay-change-returned').innerText = formatMoney(change);
}

async function confirmSaleAndPrint() {
  const totals = getCartTotals();
  const total = totals.total;
  const globalDiscountType = document.getElementById('cart-discount-type').value;
  const globalDiscountValue = Math.max(0, parseFloat(document.getElementById('cart-discount-input').value) || 0);

  const isCash = document.getElementById('pay-method-cash').checked;
  const paymentMethod = isCash ? 'Espèces' : 'Mobile Money';
  const amountReceived = isCash ? (parseFloat(document.getElementById('pay-amount-received').value) || total) : total;

  if (isCash && amountReceived < total) {
    alert("Le montant donné par le client est inférieur au total à payer.");
    return;
  }

  const receiptFormat = document.querySelector('input[name="receiptFormatRadio"]:checked').value;

  const salePayload = {
    items: state.cart.map(it => ({
      product_id: it.product_id,
      unit_id: it.unit_id,
      quantity: it.quantity,
      discount_type: it.discount_type,
      discount: it.discount_value
    })),
    payment_method: paymentMethod,
    amount_received: amountReceived,
    discount_type: globalDiscountType,
    discount: globalDiscountValue,
    customer_id: state.selectedCustomer ? state.selectedCustomer.id : null,
    receipt_type: receiptFormat
  };

  try {
    const res = await fetch('/api/sales', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(salePayload)
    });
    const result = await res.json();

    if (!res.ok) {
      alert("Erreur lors de la vente : " + (result.error || "Impossible d'enregistrer."));
      return;
    }

    // Fermer le modal de paiement
    bootstrap.Modal.getInstance(document.getElementById('paymentModal')).hide();

    // Vider le panier et réinitialiser
    state.cart = [];
    document.getElementById('cart-discount-input').value = 0;
    document.getElementById('cart-discount-type').value = 'amount';
    renderCart();

    // Recharger produits & clients pour mettre à jour les stocks
    await loadProducts();
    await loadCustomers();

    // Ouvrir le reçu généré dans le modal d'impression
    showReceiptModal(result.sale_id, receiptFormat);

  } catch (err) {
    console.error('Erreur vente:', err);
    alert("Une erreur de communication est survenue.");
  }
}

function showReceiptModal(saleId, format = 'thermal') {
  const iframe = document.getElementById('receipt-iframe');
  iframe.src = `/api/sales/${saleId}/receipt?format=${format}&t=${Date.now()}`;
  document.getElementById('receipt-modal-title').innerText = (format === 'thermal') ? 'Ticket de Caisse Thermique' : 'Facture A4 avec Papier à En-tête';

  const modal = new bootstrap.Modal(document.getElementById('receiptModal'));
  modal.show();
}

function printReceiptFrame() {
  const iframe = document.getElementById('receipt-iframe');
  if (iframe && iframe.contentWindow) {
    iframe.contentWindow.focus();
    iframe.contentWindow.print();
  }
}

// --- FICHE PRODUIT : CALCUL DE MARGES EN TEMPS RÉEL ---
function openProductModal(prodId = null) {
  const form = document.getElementById('product-form');
  form.reset();
  document.getElementById('prod-id').value = '';
  document.getElementById('prod-img-preview').src = '/static/img/default_product.svg';
  document.getElementById('productModalTitle').innerText = 'Ajouter un Nouveau Produit';
  document.getElementById('product-units-list').innerHTML = '';

  if (prodId) {
    const p = state.products.find(x => x.id === prodId);
    if (p) {
      document.getElementById('productModalTitle').innerText = 'Modifier le Produit';
      document.getElementById('prod-id').value = p.id;
      document.getElementById('prod-name').value = p.name;
      document.getElementById('prod-category').value = p.is_auto ? 'Auto' : (p.raw_category || p.category);
      document.getElementById('prod-barcode').value = p.barcode || '';
      document.getElementById('prod-stock').value = p.stock_quantity;
      document.getElementById('prod-threshold').value = p.alert_threshold_percent || 20;
      document.getElementById('prod-purchase-price').value = p.purchase_price;
      document.getElementById('prod-transport-cost').value = p.transport_cost;
      document.getElementById('prod-sale-price').value = p.sale_price;
      if (p.image_path) {
        document.getElementById('prod-img-preview').src = p.image_path;
      }
      renderProductUnitRows(p.units && p.units.length ? p.units : null);
    }
  } else {
    document.getElementById('prod-category').value = 'Auto';
    document.getElementById('prod-threshold').value = 20;
    renderProductUnitRows();
  }

  calculateMargins();
  const modal = new bootstrap.Modal(document.getElementById('productModal'));
  modal.show();
}

function renderProductUnitRows(units = null) {
  const container = document.getElementById('product-units-list');
  const rows = units || [{ name: 'Pièce', conversion_factor: 1, sale_price: document.getElementById('prod-sale-price').value || 0 }];
  container.innerHTML = rows.map((unit, index) => productUnitRowHtml(unit, index)).join('');
  syncBaseUnitSalePrice();
}

function productUnitRowHtml(unit = {}, index = 0) {
  const baseLocked = index === 0;
  return `
    <div class="product-unit-row row g-2 align-items-end mb-2">
      <div class="col-md-4">
        <label class="form-label small mb-1">Nom de l'unité</label>
        <input type="text" class="form-control product-unit-name" value="${unit.name || ''}" placeholder="Ex: Boîte" required>
      </div>
      <div class="col-md-3">
        <label class="form-label small mb-1">Quantité de pièces contenues</label>
        <input type="number" class="form-control product-unit-factor" value="${unit.conversion_factor || (baseLocked ? 1 : '')}" min="1" step="1" placeholder="${baseLocked ? '1' : 'Ex: 100'}" ${baseLocked ? 'readonly' : ''} required>
      </div>
      <div class="col-md-4">
        <label class="form-label small mb-1">Prix de vente</label>
        <input type="number" class="form-control product-unit-price" value="${unit.sale_price ?? 0}" min="0" step="0.01" ${baseLocked ? 'oninput="syncBaseUnitSalePrice()"' : ''} required>
      </div>
      <div class="col-md-1">
        ${baseLocked ? '' : '<button type="button" class="btn btn-outline-danger w-100" onclick="this.closest(\'.product-unit-row\').remove()" title="Supprimer">×</button>'}
      </div>
    </div>`;
}

function syncBaseUnitSalePrice() {
  const basePrice = document.querySelector('.product-unit-row .product-unit-price');
  document.getElementById('prod-sale-price').value = basePrice ? basePrice.value || 0 : 0;
  calculateMargins();
}

function addProductUnitRow() {
  const container = document.getElementById('product-units-list');
  if (!container.children.length) {
    renderProductUnitRows();
  }
  container.insertAdjacentHTML('beforeend', productUnitRowHtml({}, container.children.length));
}

function getProductUnitsPayload() {
  return [...document.querySelectorAll('.product-unit-row')].map((row, index) => ({
    name: row.querySelector('.product-unit-name').value.trim(),
    conversion_factor: index === 0 ? 1 : Number(row.querySelector('.product-unit-factor').value),
    sale_price: Number(row.querySelector('.product-unit-price').value),
    is_base: index === 0
  }));
}

function updateDefaultThreshold() {
  const cat = document.getElementById('prod-category').value;
  const thresholdInput = document.getElementById('prod-threshold');
  if (cat === 'Forte rotation') {
    thresholdInput.value = 20;
  } else if (cat === 'Faible rotation') {
    thresholdInput.value = 10;
  } else {
    thresholdInput.value = 20;
  }
}

function calculateMargins() {
  const purchase = parseFloat(document.getElementById('prod-purchase-price').value) || 0;
  const transport = parseFloat(document.getElementById('prod-transport-cost').value) || 0;
  const sale = parseFloat(document.getElementById('prod-sale-price').value) || 0;

  const cost = purchase + transport;
  const margin = sale - cost;
  const marginPct = (cost > 0) ? Math.round((margin / cost) * 100) : 0;

  document.getElementById('prod-cost-display').innerText = formatMoney(cost);
  const marginDisp = document.getElementById('prod-margin-display');
  marginDisp.innerText = formatMoney(margin);
  marginDisp.className = margin >= 0 ? 'form-control bg-white fw-bold text-success' : 'form-control bg-white fw-bold text-danger';

  const pctDisp = document.getElementById('prod-margin-pct-display');
  pctDisp.innerText = `${marginPct >= 0 ? '+' : ''}${marginPct}%`;
  pctDisp.className = marginPct >= 0 ? 'text-primary' : 'text-danger';
}

function previewProductImage(event) {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = e => {
      document.getElementById('prod-img-preview').src = e.target.result;
    };
    reader.readAsDataURL(file);
  }
}

async function saveProduct(event) {
  event.preventDefault();
  const form = document.getElementById('product-form');
  const formData = new FormData(form);
  const prodId = document.getElementById('prod-id').value;
  formData.set('units_json', JSON.stringify(getProductUnitsPayload()));

  const url = prodId ? `/api/products/${prodId}` : '/api/products';
  try {
    const res = await fetch(url, {
      method: prodId ? 'PUT' : 'POST',
      body: formData
    });
    const result = await res.json();
    if (!res.ok) {
      alert("Erreur : " + (result.error || "Impossible d'enregistrer le produit."));
      return;
    }

    bootstrap.Modal.getInstance(document.getElementById('productModal')).hide();
    await loadProducts();
    if (document.getElementById('view-products').classList.contains('active')) {
      loadProductsTable();
    }
  } catch (err) {
    console.error('Erreur enregistrement produit:', err);
  }
}

async function deleteProduct(prodId) {
  if (!confirm("Voulez-vous vraiment supprimer cet article ?")) return;
  try {
    await fetch(`/api/products/${prodId}`, { method: 'DELETE' });
    await loadProducts();
    loadProductsTable();
  } catch (err) {
    console.error(err);
  }
}

// --- TABLEAU DE GESTION DU STOCK (VUE PRODUITS) ---
function loadProductsTable() {
  const tbody = document.getElementById('products-table-body');
  if (!tbody) return;

  tbody.innerHTML = state.products.map(p => {
    const isOut = p.stock_quantity <= 0;
    const isAlert = p.status_key === 'alert';
    let badge = `<span class="badge-odoo badge-valid">Normal</span>`;
    if (isOut) badge = `<span class="badge-odoo badge-cancelled">Rupture</span>`;
    else if (isAlert) badge = `<span class="badge-odoo badge-momo">Alerte (${p.alert_threshold_percent}%)</span>`;

    let rotBadge = '';
    if (p.category === 'Forte rotation') {
      rotBadge = `<span class="badge bg-danger-subtle text-danger border border-danger-subtle fw-semibold">🔥 Forte rotation</span>`;
    } else if (p.category === 'Faible rotation') {
      rotBadge = `<span class="badge bg-secondary-subtle text-secondary border fw-normal">🐢 Faible rotation</span>`;
    } else if (p.category === 'Nouveau') {
      rotBadge = `<span class="badge bg-info-subtle text-info border border-info-subtle fw-semibold">✨ Nouveau</span>`;
    } else {
      rotBadge = `<span class="badge bg-light text-dark border">📦 Standard</span>`;
    }

    const autoTag = p.is_auto ? '<span class="badge bg-primary-subtle text-primary border border-primary-subtle ms-1" style="font-size:0.65rem;">Auto</span>' : '<span class="badge bg-light text-muted border ms-1" style="font-size:0.65rem;">Manuel</span>';
    const reasonHtml = p.rotation_reason ? `<div class="text-muted" style="font-size:0.75rem;line-height:1.2;margin-top:3px;" title="${p.rotation_reason}">${p.rotation_reason}</div>` : '';

    return `
      <tr>
        <td>
          <img src="${p.image_path || '/static/img/default_product.svg'}" style="width:40px;height:40px;object-fit:cover;border-radius:6px;border:1px solid #e2e8f0;">
        </td>
        <td><strong>${p.name}</strong></td>
        <td>
          <div class="d-flex align-items-center">${rotBadge} ${autoTag}</div>
          ${reasonHtml}
        </td>
        <td>${formatMoney(p.purchase_price)}</td>
        <td>${formatMoney(p.transport_cost)}</td>
        <td><strong>${formatMoney(p.cost_price)}</strong></td>
        <td class="text-primary fw-bold">${formatMoney(p.sale_price)}</td>
        <td class="text-success fw-bold">+${formatMoney(p.margin)} (${p.margin_percent}%)</td>
        <td><strong>${p.stock_quantity}</strong></td>
        <td>${badge}</td>
        <td style="text-align:right;">
          <button class="btn btn-sm btn-outline-success me-1" onclick="openRestockModal(${p.id}, '${p.name.replace(/'/g, "\\'")}')" title="Ajouter du stock">
            + Stock
          </button>
          <button class="btn btn-sm btn-outline-primary me-1" onclick="openProductModal(${p.id})" title="Modifier">
            Modifier
          </button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteProduct(${p.id})" title="Supprimer">
            ✕
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

async function enableAutoRotationAll() {
  if (!confirm("Voulez-vous passer tous vos produits en mode de détection automatique selon vos ventes réelles ?")) return;
  try {
    const res = await fetch('/api/products/auto-classify-all', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      await loadProducts();
      loadProductsTable();
      alert("Tous les produits sont maintenant en mode rotation automatique basée sur les ventes réelles !");
    }
  } catch (err) {
    console.error('Erreur auto-classification:', err);
    alert("Une erreur est survenue lors de la synchronisation.");
  }
}

function filterProductsTable() {
  const q = (document.getElementById('product-mgr-search').value || '').toLowerCase();
  const rows = document.querySelectorAll('#products-table-body tr');
  rows.forEach(r => {
    r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
  });
}

// --- RAVITAILLEMENT DE STOCK EXPRESS ---
function openRestockModal(prodId, prodName) {
  document.getElementById('restock-prod-id').value = prodId;
  document.getElementById('restock-prod-name').innerText = prodName;
  document.getElementById('restock-qty-input').value = 10;
  const product = state.products.find(p => Number(p.id) === Number(prodId));
  const unitSelect = document.getElementById('restock-unit-select');
  unitSelect.innerHTML = '';
  const units = product && Array.isArray(product.units) ? product.units : [{ name: 'Pièce' }];
  units.forEach(unit => {
    const option = document.createElement('option');
    option.value = unit.name;
    option.textContent = unit.name;
    unitSelect.appendChild(option);
  });
  const pieceUnit = units.find(unit => unit.name.toLocaleLowerCase('fr-FR') === 'pièce');
  unitSelect.value = pieceUnit ? pieceUnit.name : units[0].name;
  const modal = new bootstrap.Modal(document.getElementById('restockModal'));
  modal.show();
}

async function submitRestock() {
  const prodId = document.getElementById('restock-prod-id').value;
  const qty = parseInt(document.getElementById('restock-qty-input').value);
  const unitName = document.getElementById('restock-unit-select').value;
  if (isNaN(qty) || qty <= 0) {
    alert("Veuillez saisir une quantité valide.");
    return;
  }

  try {
    const res = await fetch(`/api/products/${prodId}/restock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity: qty, unit_name: unitName })
    });
    const result = await res.json();
    if (!res.ok) {
      alert("Erreur : " + result.error);
      return;
    }

    bootstrap.Modal.getInstance(document.getElementById('restockModal')).hide();
    await loadProducts();
    if (document.getElementById('view-products').classList.contains('active')) loadProductsTable();
    if (document.getElementById('view-alerts').classList.contains('active')) loadAlertsView();
  } catch (err) {
    console.error(err);
  }
}

// --- CENTRE D'ALERTES DE STOCK ---
async function loadAlerts() {
  try {
    const res = await fetch('/api/alerts');
    state.alerts = await res.json();

    const badge = document.getElementById('nav-alert-badge');
    if (badge) {
      if (state.alerts.length > 0) {
        badge.innerText = state.alerts.length;
        badge.classList.remove('d-none');
      } else {
        badge.classList.add('d-none');
      }
    }
  } catch (err) {
    console.error(err);
  }
}

function loadAlertsView() {
  loadAlerts().then(() => {
    const container = document.getElementById('alerts-cards-container');
    if (!container) return;

    if (state.alerts.length === 0) {
      container.innerHTML = `
        <div class="col-12 text-center text-muted py-5">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <h5 class="mt-3 fw-bold text-success">Tous les stocks sont à un niveau optimal !</h5>
          <p class="text-secondary">Aucun produit n'a atteint son seuil d'alerte critique.</p>
        </div>`;
      return;
    }

    container.innerHTML = state.alerts.map(p => {
      const isOut = p.stock_quantity <= 0;
      const isTop = (p.category === 'Forte rotation');
      const rotText = isTop ? '🔥 Forte rotation' : p.category;
      return `
        <div class="col-md-4 mb-3">
          <div class="card p-3 shadow-sm border-${isOut ? 'danger' : 'warning'}">
            <div class="d-flex align-items-center gap-3">
              <img src="${p.image_path || '/static/img/default_product.svg'}" style="width:65px;height:65px;object-fit:cover;border-radius:8px;border:1px solid #e2e8f0;">
              <div class="flex-grow-1 min-w-0">
                <h6 class="fw-bold mb-1 text-truncate">${p.name}</h6>
                <div class="small text-muted mb-1">Rotation : <strong>${rotText}</strong></div>
                ${p.rotation_reason ? `<div class="small text-secondary mb-1" style="font-size:0.75rem;">${p.rotation_reason}</div>` : ''}
                <div class="badge ${isOut ? 'bg-danger' : 'bg-warning text-dark'}">
                  ${isOut ? 'RUPTURE DE STOCK' : `STOCK CRITIQUE : ${p.stock_quantity} restant(s)`}
                </div>
              </div>
            </div>
            <div class="mt-3 pt-2 border-top d-flex justify-content-between align-items-center">
              <span class="small text-muted">Seuil d'alerte : ${p.alert_threshold_percent}%</span>
              <button class="btn btn-sm btn-success fw-bold" onclick="openRestockModal(${p.id}, '${p.name.replace(/'/g, "\\'")}')">
                + Ravitailler
              </button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  });
}

// --- HISTORIQUE & JOURNAL DES VENTES ---
async function loadSalesTable() {
  try {
    const res = await fetch('/api/sales');
    state.sales = await res.json();

    const tbody = document.getElementById('sales-table-body');
    if (!tbody) return;

    if (state.sales.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted">Aucune vente enregistrée pour le moment.</td></tr>`;
      return;
    }

    tbody.innerHTML = state.sales.map(s => {
      const isCancelled = s.status === 'CANCELLED';
      const isCash = s.payment_method === 'Espèces';

      return `
        <tr style="${isCancelled ? 'opacity:0.6;background:#fef2f2;' : ''}">
          <td><strong>${s.sale_code}</strong></td>
          <td>${s.created_at}</td>
          <td>${s.customer_name}${s.customer_phone ? ` <small class="text-muted">(${s.customer_phone})</small>` : ''}</td>
          <td><span class="badge-odoo ${isCash ? 'badge-cash' : 'badge-momo'}">${s.payment_method}</span></td>
          <td class="fw-bold">${formatMoney(s.total_amount)}</td>
          <td class="text-success fw-bold">${isCancelled ? '0 FCFA' : '+' + formatMoney(s.profit)}</td>
          <td>
            <span class="badge-odoo ${isCancelled ? 'badge-cancelled' : 'badge-valid'}">
              ${isCancelled ? 'Annulée' : 'Validée'}
            </span>
            ${isCancelled && s.cancellation_reason ? `<div class="small text-danger fst-italic">"${s.cancellation_reason}"</div>` : ''}
          </td>
          <td style="text-align:right;">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-outline-secondary" onclick="showReceiptModal(${s.id}, 'thermal')" title="Ticket Thermique">
                Ticket
              </button>
              <button class="btn btn-outline-secondary" onclick="showReceiptModal(${s.id}, 'a4')" title="Facture A4 avec en-tête">
                Facture A4
              </button>
              ${!isCancelled ? `
                <button class="btn btn-outline-danger" onclick="openCancelSaleModal(${s.id})" title="Annuler avec motif obligatoire">
                  Annuler
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.error(err);
  }
}

function filterSalesTable() {
  const q = (document.getElementById('sales-search-input').value || '').toLowerCase();
  const rows = document.querySelectorAll('#sales-table-body tr');
  rows.forEach(r => {
    r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
  });
}

function openCancelSaleModal(saleId) {
  document.getElementById('cancel-sale-id').value = saleId;
  document.getElementById('cancel-sale-reason').value = '';
  const modal = new bootstrap.Modal(document.getElementById('cancelSaleModal'));
  modal.show();
}

async function submitCancelSale() {
  const saleId = document.getElementById('cancel-sale-id').value;
  const reason = document.getElementById('cancel-sale-reason').value.trim();

  if (!reason) {
    alert("Le motif d'annulation est obligatoire.");
    return;
  }

  try {
    const res = await fetch(`/api/sales/${saleId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason })
    });
    const result = await res.json();
    if (!res.ok) {
      alert("Erreur : " + result.error);
      return;
    }

    bootstrap.Modal.getInstance(document.getElementById('cancelSaleModal')).hide();
    alert("Vente annulée avec succès et articles restitués au stock !");
    await loadProducts();
    await loadSalesTable();
  } catch (err) {
    console.error(err);
  }
}

// --- FICHIER CLIENTS ---
async function loadCustomers() {
  try {
    const res = await fetch('/api/customers');
    state.customers = await res.json();
    if (document.getElementById('view-customers').classList.contains('active')) {
      loadCustomersTable();
    }
  } catch (err) {
    console.error(err);
  }
}

function loadCustomersTable() {
  const tbody = document.getElementById('customers-table-body');
  if (!tbody) return;

  if (state.customers.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">Aucun client enregistré.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.customers.map(c => {
    let vipBadge = `<span class="badge bg-secondary">Client Standard</span>`;
    if (c.total_spent > 500000) {
      vipBadge = `<span class="badge bg-warning text-dark fw-bold">⭐ VIP Platine</span>`;
    } else if (c.total_spent > 150000) {
      vipBadge = `<span class="badge bg-info text-dark fw-bold">⭐ VIP Or</span>`;
    }

    return `
      <tr>
        <td><strong>${c.name}</strong></td>
        <td>📞 ${c.phone}</td>
        <td>${c.orders_count} commande(s)</td>
        <td class="fw-bold text-primary">${formatMoney(c.total_spent)}</td>
        <td>${vipBadge}</td>
        <td class="text-muted small">${c.created_at || '-'}</td>
      </tr>
    `;
  }).join('');
}

function openCustomerModal() {
  document.getElementById('customer-form').reset();
  const modal = new bootstrap.Modal(document.getElementById('customerModal'));
  modal.show();
}

async function saveCustomer(event) {
  event.preventDefault();
  const name = document.getElementById('cust-name').value.trim();
  const phone = document.getElementById('cust-phone').value.trim();
  const notes = document.getElementById('cust-notes').value.trim();

  try {
    const res = await fetch('/api/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, phone, notes })
    });
    const result = await res.json();
    if (!res.ok) {
      alert("Erreur : " + result.error);
      return;
    }

    bootstrap.Modal.getInstance(document.getElementById('customerModal')).hide();
    await loadCustomers();
    // Auto-sélectionner pour le POS
    state.selectedCustomer = { id: result.customer_id, name: result.name, phone: result.phone };
    updateCustomerDisplay();
  } catch (err) {
    console.error(err);
  }
}

// --- CLÔTURE DE CAISSE (RAPPORT Z) ---
async function loadClosingData() {
  try {
    const res = await fetch('/api/closing/today');
    const data = await res.json();

    document.getElementById('closing-cash-val').innerText = formatMoney(data.total_cash);
    document.getElementById('closing-momo-val').innerText = formatMoney(data.total_momo);
    document.getElementById('closing-rev-val').innerText = formatMoney(data.total_revenue);
    document.getElementById('closing-profit-val').innerText = formatMoney(data.total_profit);
  } catch (err) {
    console.error(err);
  }
}

async function submitDailyClosing() {
  const notes = document.getElementById('closing-notes').value.trim();
  if (!confirm("Voulez-vous valider définitivement la clôture de caisse du jour ?")) return;

  try {
    const res = await fetch('/api/closing/close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes })
    });
    const result = await res.json();
    alert(result.message || "Clôture enregistrée avec succès !");
  } catch (err) {
    console.error(err);
  }
}

function printClosingReport() {
  const cash = document.getElementById('closing-cash-val').innerText;
  const momo = document.getElementById('closing-momo-val').innerText;
  const rev = document.getElementById('closing-rev-val').innerText;
  const profit = document.getElementById('closing-profit-val').innerText;
  const notes = document.getElementById('closing-notes').value;

  const printWindow = window.open('', '_blank');
  printWindow.document.write(`
    <html>
      <head>
        <title>Rapport Z - Clôture de Caisse</title>
        <style>
          body { font-family: 'Segoe UI', monospace; padding: 25px; max-width: 600px; margin: auto; }
          h2 { text-align: center; border-bottom: 2px dashed #000; padding-bottom: 10px; }
          .row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px dashed #ccc; font-size: 15px; }
          .bold { font-weight: bold; }
        </style>
      </head>
      <body>
        <h2>RAPPORT Z - CLÔTURE DE CAISSE</h2>
        <div class="row"><span>Date :</span><span class="bold">${new Date().toLocaleString('fr-FR')}</span></div>
        <div class="row"><span>Total Espèces :</span><span class="bold">${cash}</span></div>
        <div class="row"><span>Total Mobile Money :</span><span class="bold">${momo}</span></div>
        <div class="row"><span>Chiffre d'Affaires Net :</span><span class="bold" style="font-size:18px;">${rev}</span></div>
        <div class="row"><span>Bénéfice Net Réalisé :</span><span class="bold" style="color:green;">${profit}</span></div>
        ${notes ? `<div class="row"><span>Notes :</span><span>${notes}</span></div>` : ''}
        <div style="margin-top: 40px; text-align: center; font-size: 12px;">Signé par le Responsable de Caisse</div>
      </body>
    </html>
  `);
  printWindow.document.close();
  printWindow.focus();
  printWindow.print();
}

// --- PARAMÈTRES & PAPIER À EN-TÊTE ---
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    state.settings = await res.json();

    document.getElementById('nav-brand-title').innerText = state.settings.company_name || 'GEST-STOCK POS';
    document.getElementById('set-company-name').value = state.settings.company_name || '';
    document.getElementById('set-company-slogan').value = state.settings.company_slogan || '';
    document.getElementById('set-company-phone').value = state.settings.company_phone || '';
    document.getElementById('set-company-address').value = state.settings.company_address || '';
    document.getElementById('set-company-nif').value = state.settings.company_nif_rccm || '';
    document.getElementById('set-receipt-footer').value = state.settings.receipt_footer || '';
    document.getElementById('set-receipt-fmt').value = state.settings.default_receipt_format || 'thermal';

    if (state.settings.company_logo) {
      document.getElementById('logo-preview-box').innerHTML = `
        <img src="${state.settings.company_logo}" style="max-height:50px;max-width:180px;object-fit:contain;border:1px solid #e2e8f0;padding:4px;border-radius:4px;">
      `;
    }
  } catch (err) {
    console.error(err);
  }
}

function previewLogo(event) {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = e => {
      document.getElementById('logo-preview-box').innerHTML = `
        <img src="${e.target.result}" style="max-height:50px;max-width:180px;object-fit:contain;border:1px solid #e2e8f0;padding:4px;border-radius:4px;">
      `;
    };
    reader.readAsDataURL(file);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const form = document.getElementById('settings-form');
  const formData = new FormData(form);

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      body: formData
    });
    const result = await res.json();
    alert(result.message || "Paramètres enregistrés !");
    await loadSettings();
  } catch (err) {
    console.error(err);
  }
}
