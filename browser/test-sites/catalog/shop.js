// ダミーのショップ。商品は静的定義、カートは localStorage に保存する。
const PRODUCTS = [
  { id: 'p1', name: 'エスプレッソ豆 200g', price: 1280, stock: 12, category: 'コーヒー' },
  { id: 'p2', name: 'ドリップバッグ 10個入', price: 980, stock: 5, category: 'コーヒー' },
  { id: 'p3', name: 'ステンレスタンブラー', price: 2480, stock: 0, category: '雑貨' },
  { id: 'p4', name: '手挽きミル', price: 5980, stock: 3, category: '器具' },
  { id: 'p5', name: 'ペーパーフィルター 100枚', price: 480, stock: 40, category: '器具' },
];

const CART_KEY = 'demo-cart';
const cart = {
  read() { try { return JSON.parse(localStorage.getItem(CART_KEY)) || {}; } catch { return {}; } },
  write(c) { localStorage.setItem(CART_KEY, JSON.stringify(c)); },
  add(id, qty = 1) { const c = cart.read(); c[id] = (c[id] || 0) + qty; cart.write(c); },
  remove(id) { const c = cart.read(); delete c[id]; cart.write(c); },
  clear() { localStorage.removeItem(CART_KEY); },
  count() { return Object.values(cart.read()).reduce((a, b) => a + b, 0); },
  lines() {
    const c = cart.read();
    return Object.entries(c).map(([id, qty]) => {
      const p = PRODUCTS.find(p => p.id === id);
      return { ...p, qty, subtotal: p.price * qty };
    });
  },
  total() { return cart.lines().reduce((a, l) => a + l.subtotal, 0); },
};

const yen = n => n.toLocaleString('ja-JP') + ' 円';

function renderCartBadge() {
  const badge = document.getElementById('cart-count');
  if (badge) badge.textContent = String(cart.count());
}
