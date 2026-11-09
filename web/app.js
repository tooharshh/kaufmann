const $ = (selector) => document.querySelector(selector);
const ui = {excludedIds: [], config: null, auth: null, generation: 0, cart: null, products: [], selected: new Map(), category: '', minPrice: null, sortBy: 'relevance', attributeFilters: {}, minRating: null, availability: 'discoverable', filterOptionsPromise: null, offset: 0, more: false, busy: false, signup: false, review: null, exception: null, refresh: null, addressDirty: false, catalogLoading: false, catalogEpoch: 0, renderedProducts: 0, screenSeq: 0, focusedProduct: null, productCache: new Map(), cartImageLoads: new Set(), voiceActive: false, profile: null};
const money = (paise) => paise == null ? 'Unavailable' : new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 2}).format(paise / 100);
const messages = {conflict: 'Your basket changed. Please check it and try again.', address_limit: 'You can save up to five addresses.', profile_too_large: 'Your saved details are too long. Shorten an address or remove an unused one.', out_of_stock: 'There isn’t enough demo stock for that quantity.', inventory_unknown: 'Availability isn’t listed for this item.', unpriced: 'This item doesn’t have a usable listed price.', address_required: 'Save your delivery details first.', invalid_address: 'Please check your delivery details and six-digit postal code.', invalid_input: 'Please check the values and try again.', unavailable: 'The store is temporarily unavailable. Your saved basket is safe.', auth_unavailable: 'Sign-in is temporarily unavailable. Please try again.', unauthorized: 'Please sign in again.', price_changed: 'The listed price changed. Please review your basket again.', stale_token: 'This review has changed. Please review your order again.', stale_exception: 'This budget proposal has changed. Please try the change again.', review_not_delivered: 'Please wait for the full order review.', later_user_approval_required: 'Please review first, then confirm.'};

function node(tag, className = '', text = '') { const element = document.createElement(tag); element.className = className; element.textContent = text; return element; }
function button(label, className, callback) { const element = node('button', className, label); element.type = 'button'; element.addEventListener('click', callback); return element; }
let toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 5000); }
function rupees(value) { if (!/^\d+(\.\d{1,2})?$/.test(value.trim())) throw new Error('Enter a rupee amount with at most two decimal places.'); const [whole, fraction = ''] = value.trim().split('.'); const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0')); if (!Number.isSafeInteger(amount) || amount < 0 || amount >= 10 ** 16) throw new Error('Please enter a smaller amount.'); return amount; }
function saveAuth(data, changeUser = false) { if (!data.access_token || !data.refresh_token) throw new Error('Sign-in did not return a session. Please try again.'); if (changeUser) ui.generation++; ui.auth = {access_token: data.access_token, refresh_token: data.refresh_token, expires_at: data.expires_at || Math.floor(Date.now() / 1000) + (data.expires_in || 3600), user: data.user || ui.auth?.user || {}}; sessionStorage.setItem('kaufmann-session', JSON.stringify(ui.auth)); }
function clearAuth() { window.kaufmannStopVoice?.(); ui.generation++; ui.auth = null; ui.profile = null; $('#preference-memory').replaceChildren(); $('#catalog-selection').replaceChildren(); ui.cart = null; $('#profile-form').reset(); $('#profile-address-form').reset(); $('#profile-address-list').replaceChildren(); $('#profile-current-address').replaceChildren(); ui.selected.clear(); ui.products = []; ui.excludedIds = []; ui.catalogEpoch++; ui.productCache.clear(); ui.cartImageLoads.clear(); ui.focusedProduct = null; ui.minPrice = null; ui.sortBy = 'relevance'; ui.attributeFilters = {}; ui.minRating = null; ui.availability = 'discoverable'; ui.category = ''; syncFilterControls(); $('#search-input').value = ''; $('#max-price').value = ''; document.querySelectorAll('[data-category]').forEach(tab => tab.classList.toggle('active', tab.dataset.category === '')); ui.screenSeq++; ui.review = null; ui.addressDirty = false; $('#address-form').reset(); $('#budget-input').value = ''; $('#instruction-input').value = ''; $('#result-label').textContent = ''; history.replaceState(null, '', '/'); sessionStorage.removeItem('kaufmann-session'); document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close()); renderIdentity(); renderCart(); renderProducts(); renderCompareBar(); }
async function authRequest(path, payload, token = null) { const response = await fetch(`${ui.config.supabase_url}/auth/v1/${path}`, {method: 'POST', headers: {apikey: ui.config.publishable_key, 'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})}, body: payload ? JSON.stringify(payload) : undefined, signal: AbortSignal.timeout(15000)}); const data = response.status === 204 ? {} : await response.json(); if (!response.ok) { const error = new Error(data.error_code === 'email_not_confirmed' ? 'Confirm your email before signing in.' : response.status === 429 ? 'Too many attempts. Please wait before trying again.' : 'We couldn’t sign you in. Check your details and try again.'); error.status = response.status; throw error; } return data; }
function syncAuthMode() { $('#auth-title').textContent = ui.signup ? 'Create account' : 'Sign in'; $('#auth-submit').textContent = ui.signup ? 'Create account' : 'Sign in'; $('#auth-toggle').textContent = ui.signup ? 'Already have an account? Sign in' : 'Create account'; $('#password-input').autocomplete = ui.signup ? 'new-password' : 'current-password'; $('#password-input').minLength = ui.signup ? 8 : 1; }
async function refreshAuth() { if (ui.refresh) return ui.refresh; const generation = ui.generation; const refreshToken = ui.auth?.refresh_token; if (!refreshToken) throw new Error('Please sign in.'); ui.refresh = (async () => { try { const data = await authRequest('token?grant_type=refresh_token', {refresh_token: refreshToken}); if (generation !== ui.generation) throw new Error('Session changed.'); saveAuth(data); } catch (error) { if (generation === ui.generation && [400, 401, 403].includes(error.status)) clearAuth(); throw error; } finally { ui.refresh = null; } })(); return ui.refresh; }
async function api(path, data, retry = true) { if (!ui.auth) { openAuth(); throw new Error('Sign in to continue.'); } if (ui.auth.expires_at * 1000 < Date.now() + 30000) await refreshAuth(); const generation = ui.generation; const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', headers: {Authorization: `Bearer ${ui.auth.access_token}`, ...(data !== undefined ? {'Content-Type': 'application/json'} : {})}, body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(25000)}); if (generation !== ui.generation) throw new Error('Session changed.'); if (response.status === 401 && retry) { await refreshAuth(); return api(path, data, false); } const result = await response.json(); if (result.state) { ui.cart = result.state; renderCart(); } if (response.status === 401) { clearAuth(); openAuth(); } return result; }
function assertOk(result) { if (result.status !== 'ok' && result.status !== 'not_found') throw new Error(messages[result.status] || 'We couldn’t complete that request. Please try again.'); return result; }
function renderIdentity() { document.body.classList.toggle('signed-in', !!ui.auth); $('#account-button').setAttribute('aria-label', ui.auth ? 'Your profile' : 'Sign in'); $('#logout-button').hidden = !ui.auth; $('#orders-button').hidden = !ui.auth; $('#profile-button').hidden = !ui.auth; $('#basket-button').hidden = !ui.auth; $('#welcome-panel').hidden = !!ui.auth; $('#shopper-controls').hidden = !ui.auth; renderRoute(); }
function openAuth() { if (ui.auth) return; $('#auth-error').textContent = ''; if (!$('#auth-dialog').open) $('#auth-dialog').showModal(); }
function setBusy(value) { ui.busy = value; if (window.kaufmannRenderProductGrid) renderProducts(); document.querySelectorAll('[data-mutation]').forEach(element => { element.disabled = value || element.dataset.unavailable === 'true'; }); renderCheckoutButton(); }
async function run(task) { if (ui.busy) return; setBusy(true); try { await task(); } catch (error) { if (error.message !== 'Session changed.') toast(error.name === 'TimeoutError' ? 'The response took too long. Refresh your basket before retrying.' : error.message || 'Connection interrupted. Please try again.'); } finally { setBusy(false); } }
function mutationButton(label, className, callback, unavailable = false) { const element = button(label, className, callback); element.dataset.mutation = 'true'; element.dataset.unavailable = String(unavailable); element.disabled = ui.busy || unavailable; return element; }
async function loadSession() { assertOk(await api('/api/session')); }
async function action(name, args, after = null) { const result = await api(`/api/actions/${name}`, {expected_version: ui.cart.version, ...args}); if (result.status === 'over_budget') { showException(result, after); return result; } assertOk(result); return result; }
function showException(result, after) { ui.exception = {token: result.exception_token, version: result.state.version, after}; $('#exception-description').textContent = `This change brings your basket to ${money(result.proposed_total_paise)}, above your ${money(result.state.budget_paise)} budget.`; $('#budget-dialog').showModal(); }
function imageUrls(product) { const urls = []; for (const raw of product.images || []) { try { const url = new URL(raw); if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) continue; if (url.hostname.endsWith('.flixcart.com')) url.protocol = 'https:'; if (['img5a.flixcart.com', 'img6a.flixcart.com'].includes(url.hostname) && url.pathname.startsWith('/image/')) url.hostname = 'rukminim2.flixcart.com'; if (!urls.includes(url.href)) urls.push(url.href); } catch {} } return urls; }
function image(product, className) { const img = node('img', className); img.alt = product.name; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; const urls = imageUrls(product); img.addEventListener('load', () => { img.hidden = false; }); img.addEventListener('error', () => { const next = urls.shift(); if (next) img.src = next; else img.hidden = true; }); if (urls.length) img.src = urls.shift(); else img.hidden = true; return img; }
function canAdd(product) { return product.price_paise != null && product.stock_status === 'available'; }
async function addProduct(product) {
  if (!ui.auth) return openAuth();
  await run(async () => {
    await loadSession();
    const after = async () => { navigate('/cart'); toast('Added to cart.'); };
    const result = await action('add_item', {product_id: product.id, quantity: 1}, after);
    if (result.status === 'ok') await after();
  });
}
function renderProducts(append = false) { const grid = $('#product-grid'); if (!append) { grid.replaceChildren(); ui.renderedProducts = 0; } if (!ui.auth) { $('#load-more-products').hidden = true; return; } for (const product of ui.products.slice(ui.renderedProducts)) { const card = node('article', 'product-card'); card.dataset.productId = product.id; const visual = node('div', 'product-visual'); const fallback = node('span', 'product-fallback', 'k.'); visual.append(fallback); const view = button('', '', () => run(() => showProduct(product.id))); view.setAttribute('aria-label', `View ${product.name}`); const img = image(product, ''); img.addEventListener('load', () => { fallback.hidden = true; }); img.addEventListener('error', () => { img.hidden = true; fallback.hidden = false; }); view.append(img); visual.append(view); const compare = node('label', 'compare-check'); const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = ui.selected.has(product.id); checkbox.setAttribute('aria-label', `Compare ${product.name}`); checkbox.addEventListener('change', () => { if (checkbox.checked && ui.selected.size >= 4) { checkbox.checked = false; return toast('Compare up to four finds at a time.'); } if (checkbox.checked) ui.selected.set(product.id, product); else ui.selected.delete(product.id); renderCompareBar(); }); compare.append(checkbox, document.createTextNode('Compare')); visual.append(compare); card.append(visual, node('p', 'product-category', product.category_path[0] || 'The collection')); card.append(button(product.name, 'product-name', () => run(() => showProduct(product.id)))); const bottom = node('div', 'product-bottom'); bottom.append(node('span', 'product-price', money(product.price_paise)), mutationButton('+ Add', 'add-button', () => addProduct(product), !canAdd(product))); card.append(bottom, node('p', 'product-stock', product.available_quantity == null ? 'Availability not listed' : `${product.stock_basis === 'demo' ? 'Demo stock' : 'Stock'}: ${product.available_quantity}`)); grid.append(card); } ui.renderedProducts = ui.products.length; $('#result-label').textContent = ui.products.length ? `${ui.products.length} products${ui.more ? ' loaded' : ''}` : 'No matching products'; if (ui.minPrice != null) $('#result-label').textContent += ` · From ${money(ui.minPrice)}`; if (ui.sortBy !== 'relevance') $('#result-label').textContent += ` · ${$('#sort-by').selectedOptions[0].textContent}`; for (const [key, value] of Object.entries(ui.attributeFilters)) $('#result-label').textContent += ` · ${key}: ${value}`; if (ui.minRating != null) $('#result-label').textContent += ` · ${ui.minRating}+ stars`; if (ui.availability !== 'discoverable') $('#result-label').textContent += ` · ${ui.availability.replaceAll('_',' ')}`; }
const renderProductsLegacy = renderProducts;
renderProducts = function(append = false) {
  if (!window.kaufmannRenderProductGrid) return renderProductsLegacy(append);
  const grid = $('#product-grid');
  if (!ui.auth) {
    window.kaufmannRenderProductGrid(grid, {products: [], selectedIds: []});
    $('#load-more-products').hidden = true;
    return;
  }
  window.kaufmannRenderProductGrid(grid, {
    products: ui.products,
    selectedIds: [...ui.selected.keys()],
    busy: ui.busy,
    canAdd,
    formatPrice: money,
    onOpen: id => run(() => showProduct(id)),
    onAdd: addProduct,
    onCompare: (product, checked, input) => {
      if (checked && ui.selected.size >= 4) {
        input.checked = false;
        toast('Compare up to four finds at a time.');
        return;
      }
      if (checked) ui.selected.set(product.id, product);
      else ui.selected.delete(product.id);
      renderCompareBar();
      renderProducts();
    },
  });
  ui.renderedProducts = ui.products.length;
  $('#result-label').textContent = ui.products.length ? `${ui.products.length} products${ui.more ? ' loaded' : ''}` : 'No matching products';
  if (ui.minPrice != null) $('#result-label').textContent += ` · From ${money(ui.minPrice)}`;
  if (ui.sortBy !== 'relevance') $('#result-label').textContent += ` · ${$('#sort-by').selectedOptions[0].textContent}`;
  for (const [key, value] of Object.entries(ui.attributeFilters)) $('#result-label').textContent += ` · ${key}: ${value}`;
  if (ui.minRating != null) $('#result-label').textContent += ` · ${ui.minRating}+ stars`;
  if (ui.availability !== 'discoverable') $('#result-label').textContent += ` · ${ui.availability.replaceAll('_',' ')}`;
};
window.addEventListener('kaufmann:astryx-ready', () => renderProducts());

const filterViewport = matchMedia('(max-width: 900px)');
const filterPanel = $('.catalog-filter-panel');
function placeFilterPanel() {
  const drawer = $('#catalog-filter-drawer');
  if (!filterViewport.matches && drawer.open) drawer.close();
  (filterViewport.matches ? $('#filter-drawer-content') : $('#catalog-sidebar')).append(filterPanel);
  filterPanel.open = true;
}
filterViewport.addEventListener('change', placeFilterPanel);
placeFilterPanel();
$('#open-catalog-filters').addEventListener('click', () => $('#catalog-filter-drawer').showModal());
$('#close-catalog-filters').addEventListener('click', () => $('#catalog-filter-drawer').close());
$('#apply-catalog-filters').addEventListener('click', () => $('#catalog-filter-drawer').close());

let facetNames = ['color', 'size', 'gender', 'brand', 'material', 'occasion', 'fit', 'pattern', 'sleeve', 'type'];
function selectValue(control, value) {
  value = value == null ? '' : String(value);
  if (value && !Array.from(control.options).some(option => option.value === value)) control.append(new Option(value, value));
  control.value = value;
}
function syncFilterControls() {
  document.querySelectorAll('[data-category]').forEach(tab => tab.classList.toggle('active', tab.dataset.category === ui.category));
  $('#sort-by').value = ui.sortBy;
  $('#min-price').value = ui.minPrice == null ? '' : String(ui.minPrice / 100);
  selectValue($('#filter-category'), ui.category);
  selectValue($('#filter-rating'), ui.minRating);
  $('#filter-availability').value = ui.availability;
  for (const name of facetNames) { const control = document.getElementById(`filter-${name}`); if (control) selectValue(control, ui.attributeFilters[name]); }
}
async function loadFilterOptions() {
  if (!ui.filterOptionsPromise) ui.filterOptionsPromise = (async () => {
    const result = assertOk(await api('/api/catalog/filters'));
    facetNames = Object.keys(result.filters || {}).filter(name => name.length <= 80 && (result.filters[name] || []).length);
    const container = $('#attribute-filters'); container.replaceChildren();
    for (const name of facetNames) {
      const label = node('label', '', name[0].toUpperCase() + name.slice(1));
      const control = node('select'); control.id = `filter-${name}`; control.append(new Option('Any', ''));
      for (const value of result.filters[name] || []) control.append(new Option(value, value));
      control.addEventListener('change', () => { if (control.value) ui.attributeFilters[name] = control.value; else delete ui.attributeFilters[name]; run(loadCatalog); });
      label.append(control); container.append(label);
    }
    const categories = result.categories || []; ui.categories = categories;
    for (const value of categories) if (!Array.from($('#filter-category').options).some(option => option.value === value)) $('#filter-category').append(new Option(value, value));
    syncFilterControls();
  })().catch(error => { ui.filterOptionsPromise = null; throw error; });
  await ui.filterOptionsPromise;
}
$('#sort-by').addEventListener('change', () => { ui.sortBy = $('#sort-by').value; run(loadCatalog); });
$('#min-price').addEventListener('change', () => run(async () => { ui.minPrice = $('#min-price').value.trim() ? rupees($('#min-price').value.trim()) : null; await loadCatalog(); }));
$('#filter-category').addEventListener('change', () => { ui.category = $('#filter-category').value; syncFilterControls(); run(loadCatalog); });
$('#filter-rating').addEventListener('change', () => { ui.minRating = $('#filter-rating').value ? Number($('#filter-rating').value) : null; run(loadCatalog); });
$('#filter-availability').addEventListener('change', () => { ui.availability = $('#filter-availability').value; run(loadCatalog); });
$('#clear-filters').addEventListener('click', () => { ui.attributeFilters = {}; ui.minRating = null; ui.availability = 'discoverable'; ui.minPrice = null; ui.sortBy = 'relevance'; ui.category = ''; $('#max-price').value = ''; syncFilterControls(); run(loadCatalog); });

async function loadCatalog(append = false) {
  if (!ui.auth) return openAuth();
  await loadFilterOptions();
  if (append && (ui.catalogLoading || !ui.more)) return;
  const epoch = append ? ui.catalogEpoch : ++ui.catalogEpoch;
  if (!append) { ui.products = []; ui.offset = 0; ui.more = false; renderProducts(); }
  ui.catalogLoading = true;
  $('#catalog-loading').textContent = 'Loading products…';
  $('#load-more-products').disabled = true;
  try {
    const params = new URLSearchParams({query: $('#search-input').value.trim(), category: ui.category, limit: '60', offset: String(ui.offset)});
    if (Number.isSafeInteger(ui.minPrice)) params.set('min_price_paise', String(ui.minPrice));
    params.set('sort_by', ui.sortBy);
    params.set('filters', JSON.stringify(ui.attributeFilters));
    params.set('exclude_ids', JSON.stringify(ui.excludedIds));
    params.set('availability', ui.availability);
    if (ui.minRating != null) params.set('min_rating', String(ui.minRating));
    const maximum = $('#max-price').value.trim();
    if (maximum) params.set('max_price_paise', String(rupees(maximum)));
    const result = assertOk(await api(`/api/catalog/search?${params}`));
    if (epoch !== ui.catalogEpoch) return;
    const known = new Set(ui.products.map(product => product.id));
    const incoming = result.products.filter(product => !known.has(product.id));
    incoming.forEach(product => ui.productCache.set(product.id, product));
    ui.products.push(...incoming);
    ui.offset += result.products.length;
    ui.more = result.has_more;
    renderProducts(append);
    $('#catalog-status').textContent = ui.products.length ? '' : 'No matching products.';
  } finally {
    if (epoch === ui.catalogEpoch) {
      ui.catalogLoading = false;
      $('#catalog-loading').textContent = '';
      $('#load-more-products').disabled = false;
      $('#load-more-products').hidden = !ui.more;
      requestAnimationFrame(maybeLoadMore);
    }
  }
}
function renderCheckoutButton() { $('#checkout-button').disabled = ui.busy || !ui.auth || !ui.cart?.items.length || ui.cart.total_paise == null; }
function renderCart() { renderIdentity(); const container = $('#cart-items'); container.replaceChildren(); const items = ui.cart?.items || []; $('#basket-count').textContent = String(items.reduce((sum, item) => sum + item.quantity, 0)); if (!items.length) { const empty = node('div', 'empty-cart'); empty.append(node('span', '', '◇'), node('p', '', ui.auth ? 'Your bag is waiting for something lovely.' : 'Sign in to start saving your finds.')); container.append(empty); } for (const item of items) { const row = node('div', 'cart-item'); row.dataset.productId = item.product_id; const product = ui.productCache.get(item.product_id); if (product) { const thumbnail = button('', 'cart-item-image', () => run(() => showProduct(item.product_id))); thumbnail.setAttribute('aria-label', `View ${item.name}`); thumbnail.append(image(product, '')); row.append(thumbnail); } else if (ui.auth && !ui.cartImageLoads.has(item.product_id)) { ui.cartImageLoads.add(item.product_id); api(`/api/catalog/${encodeURIComponent(item.product_id)}`).then(assertOk).then(result => { if (result.product && ui.auth) { ui.productCache.set(item.product_id, result.product); if (location.pathname === '/cart') renderCart(); } }).catch(() => {}); } const copy = node('div', 'cart-item-copy'); copy.append(button(item.name, 'cart-item-name text-button', () => run(() => showProduct(item.product_id)))); const bottom = node('div', 'cart-item-bottom'); const controls = node('div', 'quantity-control'); const minus = mutationButton('−', '', () => run(() => action('set_quantity', {product_id: item.product_id, quantity: item.quantity - 1}))); const plus = mutationButton('+', '', () => run(() => action('set_quantity', {product_id: item.product_id, quantity: item.quantity + 1}))); minus.setAttribute('aria-label', `Decrease quantity of ${item.name}`); plus.setAttribute('aria-label', `Increase quantity of ${item.name}`); controls.append(minus, node('span', '', String(item.quantity)), plus); bottom.append(controls, node('strong', '', money(item.line_total_paise))); copy.append(bottom, mutationButton('Remove', 'text-button remove-item', () => run(() => action('remove_item', {product_id: item.product_id})))); row.append(copy); container.append(row); } $('#cart-total').textContent = ui.cart ? money(ui.cart.total_paise) : '—'; $('#budget-label').textContent = ui.cart?.budget_paise != null ? `Your budget: ${money(ui.cart.budget_paise)}` : 'No budget set.'; if (!ui.addressDirty) for (const input of $('#address-form').querySelectorAll('input')) input.value = ui.cart?.address?.[input.name] || ''; const instructions = $('#instructions'); instructions.replaceChildren(); for (const instruction of ui.cart?.instructions || []) { const li = node('li', '', instruction); li.append(mutationButton('Remove', 'text-button', () => run(() => action('update_context', {remove_instruction: instruction})))); instructions.append(li); } $('#last-order-button').hidden = !ui.cart?.last_order_id; renderCheckoutButton(); }
async function showProduct(id, {notify = true} = {}) {
  const sequence = ++ui.screenSeq;
  const result = assertOk(await api(`/api/catalog/${encodeURIComponent(id)}`));
  if (sequence !== ui.screenSeq) return;
  const product = result.product;
  if (!product) throw new Error('This product is no longer listed.');
  ui.productCache.set(product.id, product);
  if (notify && !ui.voiceActive) {
    await loadSession();
    assertOk(await api('/api/actions/update_context', {expected_version: ui.cart.version, result_ids: [product.id]}));
    if (sequence !== ui.screenSeq) return;
  }
  ui.focusedProduct = product;
  const container = $('#product-detail');
  container.replaceChildren();
  const layout = node('div', 'detail-layout');
  const gallery = node('div', 'detail-gallery');
  const picture = image(product, 'detail-image');
  gallery.append(picture);
  const photos = imageUrls(product);
  if (photos.length > 1) {
    const thumbnails = node('div', 'detail-thumbnails');
    photos.forEach((url, index) => {
      const thumb = button('', 'detail-thumbnail', () => { picture.hidden = false; picture.src = url; thumbnails.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === thumb))); });
      thumb.setAttribute('aria-label', `View product image ${index + 1}`); thumb.setAttribute('aria-pressed', String(index === 0));
      const preview = node('img'); preview.src = url; preview.alt = ''; preview.loading = 'lazy'; preview.referrerPolicy = 'no-referrer'; thumb.append(preview); thumbnails.append(thumb);
    });
    gallery.append(thumbnails);
  }
  layout.append(gallery);
  const details = node('div');
  details.append(node('p', 'detail-category', product.category_path?.join(' / ') || 'The collection'), node('h1', 'product-title', product.name), node('p', 'detail-price', money(product.price_paise)), mutationButton('Add to cart', 'primary-button', () => addProduct(product), !canAdd(product)));
  const specs = node('dl', 'spec-list');
  for (const [name, values] of Object.entries(product.specifications || {})) specs.append(node('dt', '', name), node('dd', '', values.join(' · ')));
  details.append(specs);
  if (!specs.children.length) details.append(node('p', 'muted', 'No specifications are listed.'));
  details.append(node('p', 'small-note', 'Historical catalog pricing. Orders use demo inventory.'));
  layout.append(details);
  container.append(layout);
  const category = product.category_path?.[0];
  const related = ui.products.filter(item => item.id !== product.id && (!category || item.category_path?.[0] === category)).slice(0, 4);
  if (related.length) {
    const section = node('section', 'related-products');
    section.append(node('p', 'eyebrow', 'MORE TO DISCOVER'), node('h2', '', 'You might also like'));
    const grid = node('div', 'related-grid');
    for (const item of related) {
      const card = node('article', 'related-card');
      const open = button('', 'related-image', () => run(() => showProduct(item.id))); open.append(image(item, ''));
      card.append(open, node('p', 'product-category', item.category_path?.[0] || 'The collection'), button(item.name, 'product-name', () => run(() => showProduct(item.id))));
      const footer = node('div', 'product-bottom'); footer.append(node('span', 'product-price', money(item.price_paise)), mutationButton('Add', 'add-button', () => addProduct(item), !canAdd(item)));
      card.append(footer); grid.append(card);
    }
    section.append(grid); container.append(section);
  }
  navigate('/product/' + encodeURIComponent(id));
  if (notify) window.kaufmannSelectProduct?.(product.id);
}
window.kaufmannAssistantActions = {
  canAdd,
  formatPrice: money,
  openProduct: id => run(() => showProduct(id)),
  addProduct,
};
function renderCompareBar() { $('#compare-bar').hidden = !ui.selected.size || location.pathname !== '/'; $('#compare-count').textContent = `${ui.selected.size} ${ui.selected.size === 1 ? 'find' : 'finds'} selected`; $('#compare-button').disabled = ui.selected.size < 2; }
async function showComparison() { const result = assertOk(await api('/api/catalog/compare', {product_ids: [...ui.selected.keys()]})); const wrapper = $('#comparison-table'); wrapper.replaceChildren(); const scroll = node('div', 'table-scroll'); const table = node('table', 'comparison'); const head = node('tr'); head.append(node('th', '', 'Your finds')); result.products.forEach(product => { const cell = node('th'); const photo = image(product, 'comparison-image'); cell.append(photo, node('span', '', product.name)); head.append(cell); }); const thead = node('thead'); thead.append(head); table.append(thead); const tbody = node('tbody'); const prices = node('tr'); prices.append(node('td', '', 'Listed price')); result.products.forEach(product => prices.append(node('td', '', money(product.price_paise)))); tbody.append(prices); for (const attribute of result.attributes) { const row = node('tr'); row.append(node('td', '', attribute.name)); result.products.forEach(product => row.append(node('td', '', attribute.values[product.id]?.join(' · ') || 'Not listed'))); tbody.append(row); } table.append(tbody); scroll.append(table); wrapper.append(scroll); if (result.price_difference_paise != null) wrapper.append(node('p', 'muted', `Difference between lowest and highest listed price: ${money(result.price_difference_paise)}.`)); $('#compare-dialog').showModal(); }
function appendReview(container, snapshot) { container.replaceChildren(); for (const item of snapshot.items) { const row = node('div', 'review-item'); row.append(node('span', '', `${item.name} × ${item.quantity}`), node('strong', '', money(item.line_total_paise))); container.append(row); } const address = snapshot.address; const addressBox = node('div', 'review-address'); addressBox.append(node('strong', '', address.recipient), node('div', '', [address.line1, address.line2, address.city, address.state, address.postal_code, address.country].filter(Boolean).join(', '))); container.append(addressBox); const total = node('div', 'review-total'); total.append(node('span', '', 'Total'), node('strong', '', money(snapshot.total_paise))); container.append(total); }
async function startCheckout() { await loadSession(); if (!ui.cart.items.length) return; if (!ui.cart.address || ['recipient', 'line1', 'city', 'state', 'postal_code'].some(field => !ui.cart.address[field])) { $('#address-details').open = true; $('#address-details').scrollIntoView({behavior: 'smooth', block: 'center'}); $('#address-form [name=recipient]').focus(); return toast('Save your delivery details first.'); } const result = await api('/api/checkout/prepare', {expected_version: ui.cart.version}); if (result.status === 'over_budget') return showException(result, startCheckout); assertOk(result); ui.review = {token: result.pending_token, version: result.state.version, confirming: false}; const current = ui.review; appendReview($('#review-content'), result.read_back); $('#review-status').textContent = 'Preparing your review…'; $('#review-confirm').disabled = true; $('#review-confirm').textContent = 'Confirm demo order'; $('#review-cancel').disabled = false; $('#checkout-dialog').showModal(); await acknowledgeReview(current); }
async function acknowledgeReview(current) { if (ui.review !== current || current.delivered || current.acknowledging || !$('#checkout-dialog').open) return; current.acknowledging = true; try { await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); if (ui.review !== current || !$('#checkout-dialog').open) return; if (document.visibilityState !== 'visible') { $('#review-status').textContent = 'Return to this tab to review your order.'; return; } const receipt = await api('/api/checkout/rendered', {token: current.token}); if (ui.review !== current || !$('#checkout-dialog').open) return; if (receipt.status !== 'ok') { $('#review-status').textContent = messages[receipt.status] || 'The review changed. Please go back and review again.'; return; } current.delivered = true; $('#review-status').textContent = 'Please check your items and delivery details before confirming.'; $('#review-confirm').disabled = false; } catch { if (ui.review === current) $('#review-status').textContent = 'The review could not be acknowledged. Please go back and try again.'; } finally { current.acknowledging = false; } }
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && ui.review) acknowledgeReview(ui.review); });

async function cancelReview() { const current = ui.review; if (!current || current.confirming) return; ui.review = null; $('#checkout-dialog').close(); try { await api('/api/checkout/cancel', {token: current.token}); } catch { toast('Review closed. Please refresh your basket before continuing.'); } }
async function confirmReview() { const current = ui.review; if (!current || current.confirming || $('#review-confirm').disabled) return; current.confirming = true; $('#review-confirm').disabled = true; $('#review-cancel').disabled = true; $('#review-status').textContent = 'Saving your demo order…'; try { const result = await api('/api/checkout/confirm', {token: current.token, expected_version: current.version}); if (['unavailable', 'auth_unavailable'].includes(result.status)) throw new Error('Confirmation unavailable'); if (result.status !== 'ok') { $('#review-status').textContent = messages[result.status] || 'Please go back and review your order again.'; current.confirming = false; $('#review-cancel').disabled = false; return; } ui.review = null; $('#checkout-dialog').close(); await showOrder(result.order.id); } catch { current.confirming = false; $('#review-cancel').disabled = false; $('#review-confirm').disabled = false; $('#review-confirm').textContent = 'Check confirmation'; $('#review-status').textContent = 'We couldn’t verify the response. Check confirmation to safely retrieve or retry this same order.'; } }
async function showOrder(id) { const result = assertOk(await api(`/api/orders/${encodeURIComponent(id)}`)); if (!result.order) throw new Error('Order not found.'); const container = $('#order-content'); appendReview(container, result.order.snapshot); container.prepend(node('p', 'order-number', `Order ${result.order.id}`)); $('#order-dialog').showModal(); }

let editingAddress = null;
async function loadProfile() {
  const result = assertOk(await api('/api/profile'));
  ui.profile = result.profile;
  await loadSession();
  renderProfile();
  await loadMemoryControls();
}
function addressText(address) { return [address.recipient, address.line1, address.line2, address.city, address.state, address.postal_code].filter(Boolean).join(', '); }
function renderProfile() {
  if (!ui.profile) return;
  for (const field of ['name','phone','contact_email']) $('#profile-form').elements[field].value = ui.profile[field] || '';
  $('#profile-login-email').value = ui.profile.login_email || ui.auth?.user.email || '';
  const current = $('#profile-current-address'); current.replaceChildren();
  current.append(node('strong', '', 'Current checkout address'), node('p', '', ui.cart?.address ? addressText(ui.cart.address) : 'No delivery address selected.'));
  if (ui.cart?.address?.recipient) current.append(button('Save current address', 'text-button', () => editSavedAddress(null, ui.cart.address)));
  const list = $('#profile-address-list'); list.replaceChildren();
  if (!ui.profile.addresses.length) list.append(node('p', 'muted', 'No saved addresses yet.'));
  for (const entry of ui.profile.addresses) {
    const card = node('article', 'saved-address');
    card.append(node('strong', '', entry.label + (entry.id === ui.profile.default_address_id ? ' · Default' : '')), node('p', '', addressText(entry.address)));
    const controls = node('div', 'button-row');
    controls.append(button('Edit', 'text-button', () => editSavedAddress(entry)), button('Use for checkout', 'text-button', () => run(async () => { await loadSession(); assertOk(await action('set_address', {patch: entry.address})); renderProfile(); toast('Checkout address updated.'); })));
    if (entry.id !== ui.profile.default_address_id) controls.append(button('Set default', 'text-button', () => run(() => saveProfile('default_address', {id:entry.id}))));
    controls.append(button('Remove', 'text-button', () => { if (confirm('Remove this saved address? Your checkout address and past orders will stay unchanged.')) run(() => saveProfile('delete_address', {id:entry.id})); }));
    card.append(controls); list.append(card);
  }
}
async function saveProfile(operation, data) {
  const result = await api('/api/profile', {operation, data, revision: ui.profile.revision});
  if (result.status === 'conflict') { ui.profile = result.profile; renderProfile(); throw new Error('Your profile changed elsewhere. Check the latest details and try again.'); }
  assertOk(result); ui.profile = result.profile; renderProfile(); toast('Profile saved.');
}
function editSavedAddress(entry = null, initial = null) {
  editingAddress = entry;
  const form = $('#profile-address-form'); form.reset();
  form.elements.label.value = entry?.label || 'Home';
  const address = entry?.address || initial || {};
  for (const field of ['recipient','line1','line2','city','state','postal_code']) form.elements[field].value = address[field] || '';
  $('#profile-address-title').textContent = entry ? 'Edit address' : 'Add address';
  $('#profile-address-dialog').showModal();
}
$('#profile-button').addEventListener('click', () => run(async () => { navigate('/profile'); await loadProfile(); }));
$('#profile-orders').addEventListener('click', () => run(async () => { navigate('/orders'); await loadOrders(); }));
$('#profile-add-address').addEventListener('click', () => editSavedAddress());
$('#profile-address-cancel').addEventListener('click', () => $('#profile-address-dialog').close());
$('#profile-form').addEventListener('submit', event => { event.preventDefault(); run(() => saveProfile('details', Object.fromEntries(new FormData(event.target)))); });
$('#profile-cancel').addEventListener('click', () => { if (ui.profile) renderProfile(); });
$('#profile-address-form').addEventListener('submit', event => { event.preventDefault(); run(async () => {
  const data = Object.fromEntries(new FormData(event.target)); const label = data.label; delete data.label;
  const patch = Object.fromEntries(Object.entries(data).filter(([key,value]) => !editingAddress || value !== (editingAddress.address[key] || '')));
  if (!Object.keys(patch).length) patch.country = 'IN';
  await saveProfile('save_address', {id:editingAddress?.id || null, label, patch});
  $('#profile-address-dialog').close();
}); });

let ordersOffset = 0;
let ordersGeneration = 0;
async function loadOrders(append = false) {
  const generation = ++ordersGeneration;
  const auth = ui.auth;
  const offset = append ? ordersOffset : 0;
  const result = assertOk(await api(`/api/orders?offset=${offset}`));
  if (generation !== ordersGeneration || ui.auth !== auth) return;
  const container = $('#orders-list');
  if (!append) container.replaceChildren();
  if (!result.orders.length && !append) container.append(node('p', 'empty-cart', 'No orders yet. Your confirmed orders will appear here.'));
  for (const order of result.orders) {
    const card = node('article', 'order-history-card');
    card.append(node('h2', '', `Order ${order.id.slice(0, 8)}`), node('p', 'muted', new Date(order.created_at).toLocaleString()), node('p', '', `Status: ${order.status}`));
    const details = node('div');
    appendReview(details, order.snapshot);
    card.append(details);
    container.append(card);
  }
  ordersOffset = offset + result.orders.length;
  $('#orders-more').hidden = !result.has_more;
}
$('#orders-button').addEventListener('click', () => run(async () => { navigate('/orders'); await loadOrders(); }));
$('#orders-more').addEventListener('click', () => run(() => loadOrders(true)));

function renderRoute() {
  const path = ui.auth ? location.pathname : '/';
  const cart = path === '/cart';
  const product = path.startsWith('/product/');
  const orders = path === '/orders';
  const profile = path === '/profile';
  $('#profile-page').hidden = !profile;
  $('#orders-page').hidden = !orders;
  $('.store-layout').hidden = cart || product || orders || profile;
  $('#cart-page').hidden = !cart;
  $('#product-page').hidden = !product;
  $('#compare-bar').hidden = cart || product || orders || profile || !ui.selected.size;
}
function navigate(path, replace = false) {
  ui.screenSeq++;
  if (location.pathname !== path) history[replace ? 'replaceState' : 'pushState'](null, '', path);
  renderRoute();
  window.scrollTo({top: 0, behavior: 'instant'});
}
async function restoreRoute() {
  if (!ui.auth) return;
  if (location.pathname.startsWith('/product/')) await showProduct(decodeURIComponent(location.pathname.slice(9)), {notify: false});
  else if (location.pathname === '/orders') await loadOrders();
  else if (location.pathname === '/profile') await loadProfile();
  else renderRoute();
}
function maybeLoadMore() {
  if (ui.auth && location.pathname === '/' && ui.more && !ui.catalogLoading && $('#catalog-sentinel').getBoundingClientRect().top < innerHeight + 700) loadCatalog(true).catch(error => toast(error.message));
}
async function handleAgentNavigation(event) {
  if (ui.busy && event?.type !== 'cart') return;
  if (!ui.auth || !event || (Number.isInteger(event.version) && event.version < (ui.cart?.version || 0))) return;
  if (event.type === 'sarvam_rate_limit') { toast('Due to Sarvam rate limits, I cannot respond right away. Check the screen for the action status.'); return; }
  if (event.type === 'cart') { await loadSession(); navigate('/cart'); }
  else if (event.type === 'product' && typeof event.product_id === 'string' && event.product_id.length <= 128) await showProduct(event.product_id, {notify: false});
  else if (event.type === 'catalog' && typeof event.query === 'string' && event.query.length <= 200 && typeof event.category === 'string' && event.category.length <= 100) {
    ui.excludedIds = Array.isArray(event.exclude_ids) ? event.exclude_ids.filter(id => typeof id === 'string' && id.length <= 128).slice(0, 200) : [];
    $('#search-input').value = event.query;
    ui.category = event.category;
    ui.minPrice = Number.isSafeInteger(event.min_price_paise) && event.min_price_paise >= 0 ? event.min_price_paise : null;
    ui.sortBy = ['price_asc','price_desc','rating_desc','newest'].includes(event.sort_by) ? event.sort_by : 'relevance';
    ui.attributeFilters = {};
    for (const name of facetNames) if (typeof event.filters?.[name] === 'string' && event.filters[name].length <= 100) ui.attributeFilters[name] = event.filters[name];
    ui.minRating = typeof event.min_rating === 'number' && event.min_rating >= 0 && event.min_rating <= 5 ? event.min_rating : null;
    ui.availability = ['all','available','out_of_stock','unknown'].includes(event.availability) ? event.availability : 'discoverable';
    syncFilterControls();
    $('#max-price').value = Number.isSafeInteger(event.max_price_paise) ? String(event.max_price_paise / 100) : '';
    document.querySelectorAll('[data-category]').forEach(tab => tab.classList.toggle('active', tab.dataset.category === ui.category));
    navigate('/');
    await loadCatalog();
    const targetOffset = Number.isSafeInteger(event.offset) && event.offset >= 0 ? Math.min(event.offset, 100000) : 0;
    while (ui.offset <= targetOffset && ui.more) await loadCatalog(true);
    if (typeof event.focus_product_id === 'string') [...document.querySelectorAll('.product-card')].find(card => card.dataset.productId === event.focus_product_id)?.scrollIntoView({behavior: 'smooth', block: 'center'});
    window.dispatchEvent(new CustomEvent('kaufmann:voice-products', {detail: {products: ui.products.slice(0, 4)}}));
  }
}
document.querySelectorAll('a.brand').forEach(link => link.addEventListener('click', event => { if (ui.auth) { event.preventDefault(); navigate('/'); maybeLoadMore(); } }));
document.querySelectorAll('[data-browse-products]').forEach(element => element.addEventListener('click', () => { navigate('/'); maybeLoadMore(); }));
$('#load-more-products').addEventListener('click', () => loadCatalog(true).catch(error => toast(error.message)));
new IntersectionObserver(maybeLoadMore, {rootMargin: '700px'}).observe($('#catalog-sentinel'));
window.addEventListener('popstate', () => { ui.screenSeq++; renderRoute(); restoreRoute().catch(error => toast(error.message)); });

$('#basket-button').addEventListener('click', () => { if (ui.auth) { navigate('/cart'); run(loadSession); } });
$('#account-button').addEventListener('click', () => { if (ui.auth) run(async () => { navigate('/profile'); await loadProfile(); }); else openAuth(); });
$('#header-search').addEventListener('click', () => { if (location.pathname !== '/') navigate('/'); $('#search-input').focus({preventScroll: true}); $('#catalog').scrollIntoView({behavior: 'smooth', block: 'start'}); });
let scrollFrame = false;
window.addEventListener('scroll', () => { if (scrollFrame) return; scrollFrame = true; requestAnimationFrame(() => { document.body.classList.toggle('is-scrolled', window.scrollY > 12); scrollFrame = false; }); }, {passive:true});
document.querySelectorAll('[data-open-auth]').forEach(element => element.addEventListener('click', openAuth));
document.querySelectorAll('[data-close-dialog]').forEach(element => element.addEventListener('click', () => element.closest('dialog').close()));
$('#auth-toggle').addEventListener('click', () => { ui.signup = !ui.signup; syncAuthMode(); $('#auth-error').textContent = ''; });
$('#auth-form').addEventListener('submit', async event => { event.preventDefault(); $('#auth-submit').disabled = true; $('#auth-error').textContent = ''; try { const email = $('#email-input').value.trim(); const password = $('#password-input').value; const data = await authRequest(ui.signup ? `signup?redirect_to=${encodeURIComponent(location.origin)}` : 'token?grant_type=password', {email, password}); $('#password-input').value = ''; if (!data.access_token) { $('#auth-error').textContent = 'Check your email to confirm your account, then sign in here.'; return; } saveAuth(data, true); $('#auth-dialog').close(); renderIdentity(); await run(async () => { await loadSession(); await loadCatalog(); await restoreRoute(); }); } catch (error) { $('#auth-error').textContent = error.message || 'Sign-in is unavailable. Please try again.'; } finally { $('#auth-submit').disabled = false; } });
$('#logout-button').addEventListener('click', async () => { const token = ui.auth?.access_token; clearAuth(); try { await authRequest('logout?scope=local', null, token); } catch { toast('Signed out here. Remote sign-out couldn’t be verified.'); } });
$('#search-form').addEventListener('submit', event => { event.preventDefault(); ui.offset = 0; run(loadCatalog); });
document.querySelectorAll('[data-category]').forEach(element => element.addEventListener('click', () => { if (ui.busy) return; ui.category = element.dataset.category; syncFilterControls(); ui.offset = 0; document.querySelectorAll('[data-category]').forEach(tab => tab.classList.toggle('active', tab === element)); run(loadCatalog); }));
$('#max-price').addEventListener('change', () => { ui.offset = 0; run(loadCatalog); });
$('#compare-button').addEventListener('click', () => run(showComparison));
$('#clear-comparison').addEventListener('click', () => { ui.selected.clear(); renderProducts(); renderCompareBar(); });
$('#budget-form').addEventListener('submit', event => { event.preventDefault(); run(async () => { await action('set_budget', {budget_paise: rupees($('#budget-input').value)}); toast('Budget saved.'); }); });
$('#clear-budget').addEventListener('click', () => run(async () => { await action('set_budget', {budget_paise: null}); $('#budget-input').value = ''; toast('Budget cleared.'); }));
$('#address-form').addEventListener('input', () => { ui.addressDirty = true; });
$('#address-form').addEventListener('submit', event => { event.preventDefault(); run(async () => { const patch = Object.fromEntries(new FormData(event.target).entries()); patch.country = 'IN'; const result = await action('set_address', {patch}); if (result.status === 'ok') { ui.addressDirty = false; renderCart(); toast('Delivery details saved.'); } }); });
$('#instruction-form').addEventListener('submit', event => { event.preventDefault(); run(async () => { await action('update_context', {add_instruction: $('#instruction-input').value.trim()}); $('#instruction-input').value = ''; toast('Preference saved.'); }); });
$('#exception-cancel').addEventListener('click', () => { ui.exception = null; $('#budget-dialog').close(); });
$('#exception-approve').addEventListener('click', () => run(async () => { const proposal = ui.exception; if (!proposal) return; const result = assertOk(await api('/api/actions/approve_budget_exception', {token: proposal.token, expected_version: proposal.version})); if (result.status === 'ok') { ui.exception = null; $('#budget-dialog').close(); toast('Exception approved. Your budget is unchanged.'); if (proposal.after) await proposal.after(); } }));
$('#checkout-button').dataset.mutation = 'true';
$('#checkout-button').addEventListener('click', () => run(startCheckout));
$('#review-cancel').addEventListener('click', cancelReview);
$('#checkout-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelReview(); });
$('#review-confirm').addEventListener('click', confirmReview);
$('#last-order-button').addEventListener('click', () => run(() => showOrder(ui.cart.last_order_id)));
window.addEventListener('online', () => { if (ui.auth && !ui.busy && !ui.review) run(loadSession); });

async function initialize() { try { const response = await fetch('/api/config', {signal: AbortSignal.timeout(10000)}); ui.config = await response.json(); if (!response.ok) throw new Error('Sign-in configuration is unavailable. Please try again later.'); const fragment = new URLSearchParams(location.hash.slice(1)); if (fragment.has('access_token')) { const tokens = Object.fromEntries(fragment.entries()); history.replaceState(null, '', location.pathname + location.search); saveAuth({...tokens, expires_in: Number(tokens.expires_in) || 3600}, true); } else { try { ui.auth = JSON.parse(sessionStorage.getItem('kaufmann-session')); } catch { sessionStorage.removeItem('kaufmann-session'); } } renderIdentity(); renderCart(); if (ui.auth) await run(async () => { await loadSession(); await loadCatalog(); await restoreRoute(); }); } catch (error) { toast(error.message || 'The store couldn’t connect. Please refresh.'); } }
setInterval(() => { if (ui.auth && !ui.busy && !document.querySelector('dialog[open]') && document.visibilityState === 'visible') run(loadSession); }, 15000);
initialize();

async function loadMemoryControls() {
  const memory = assertOk(await api('/api/memory'));
  const list = $('#preference-memory'); list.replaceChildren();
  if (!memory.facts.length) list.append(node('p', 'muted', 'No remembered preferences.'));
  for (const fact of memory.facts) {
    const row = node('div', 'saved-address');
    const input = node('input'); input.value = fact.value; input.maxLength = 160;
    input.setAttribute('aria-label', `${fact.subject} ${fact.scope} ${fact.key}`);
    const update = operation => run(async () => {
      assertOk(await api('/api/memory', {operation, revision: memory.revision, fact: {subject: fact.subject, scope: fact.scope, key: fact.key, value: input.value}}));
      await loadMemoryControls();
    });
    row.append(node('p', '', `${fact.subject} · ${fact.scope} · ${fact.key}`), input, button('Save correction', 'text-button', () => update('remember')), button('Forget', 'text-button', () => update('forget')));
    list.append(row);
  }
  const catalogs = assertOk(await api('/api/catalog-selection'));
  const select = $('#catalog-selection'); select.replaceChildren();
  for (const catalog of catalogs.catalogs) select.append(new Option(catalog.name, catalog.id));
  select.value = catalogs.catalog_id;
}
$('#catalog-selection').addEventListener('change', () => run(async () => {
  assertOk(await api('/api/catalog-selection', {catalog_id: $('#catalog-selection').value}));
  ui.generation++; window.kaufmannStopVoice?.(); ui.review = null; $('#checkout-dialog').close();
  ui.selected.clear(); ui.productCache.clear(); ui.products = []; ui.excludedIds = []; ui.catalogEpoch++;
  ui.category = ''; ui.attributeFilters = {}; ui.minPrice = null; ui.minRating = null; ui.sortBy = 'relevance'; ui.availability = 'discoverable';
  $('#search-input').value = ''; $('#max-price').value = '';
  $('#filter-category').replaceChildren(new Option('All categories', ''));
  ui.filterOptionsPromise = null; await loadSession(); await loadFilterOptions(); await loadCatalog();
  await loadMemoryControls(); toast('Catalog changed. Reconnect voice to continue.');
}));
