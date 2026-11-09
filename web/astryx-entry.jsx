import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {Badge} from '@astryxdesign/core/Badge';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Theme} from '@astryxdesign/core/theme';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import {VoiceOrb} from './voice-orb.jsx';
import './astryx.css';
import './editorial.css';

const h = React.createElement;
const roots = new WeakMap();

function ProductCard({product, selected, onCompare, onOpen, onAdd, canAdd, busy, formatPrice}) {
  const sources = (product.images || []).filter(value => {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password;
    } catch {
      return false;
    }
  });
  const [imageIndex, setImageIndex] = useState(0);
  const category = product.category_path?.[0] || 'The collection';
  return h('article', {className: 'product-card', 'data-product-id': product.id},
    h(Card, {className: 'astryx-product-card', padding: 0, elevation: 'low'},
      h('div', {className: 'product-visual'},
        h('span', {className: 'product-fallback', hidden: sources.length > imageIndex}, 'k.'),
        h('button', {className: 'product-image-button', type: 'button', onClick: () => onOpen(product.id), 'aria-label': `View ${product.name}`},
          sources[imageIndex] && h('img', {src: sources[imageIndex], alt: product.name, loading: 'lazy', referrerPolicy: 'no-referrer', onError: () => setImageIndex(imageIndex + 1)})),
        h('label', {className: 'compare-check'},
          h('input', {type: 'checkbox', checked: selected, 'aria-label': `Compare ${product.name}`, onChange: event => onCompare(product, event.target.checked, event.target)}),
          'Compare')),
      h('div', {className: 'product-copy'},
        h(Badge, {label: category, variant: 'neutral'}),
        h(Button, {label: product.name, variant: 'ghost', className: 'product-name', onClick: () => onOpen(product.id)}),
        h('div', {className: 'product-bottom'},
          h('span', {className: 'product-price'}, formatPrice(product.price_paise)),
          h(Button, {label: 'Add to cart', variant: 'secondary', size: 'sm', className: 'add-button', isDisabled: busy || !canAdd(product), onClick: () => onAdd(product)})),
        h('p', {className: 'product-stock'}, product.stock_basis === 'demo' ? `Demo stock: ${product.available_quantity}` : 'Availability not listed'))));
}

function ProductGrid({products, selectedIds, onCompare, onOpen, onAdd, canAdd, busy, formatPrice}) {
  return h(Theme, {theme: neutralTheme}, products.map(product => h(ProductCard, {
    key: product.id,
    product,
    selected: selectedIds.includes(product.id),
    onCompare,
    onOpen,
    onAdd,
    canAdd,
    busy,
    formatPrice,
  })));
}

function AssistantPicks({products, onOpen, onAdd, canAdd, formatPrice}) {
  return h('section', {className: 'assistant-picks'},
    h('p', {className: 'eyebrow'}, 'A FEW THOUGHTFUL FINDS'),
    products.map(product => {
      const source = (product.images || []).find(value => {
        try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password; }
        catch { return false; }
      });
      return h(Card, {key: product.id, className: 'assistant-pick', padding: 0, elevation: 'low'},
        h('button', {className: 'assistant-pick-image', type: 'button', onClick: () => onOpen(product.id), 'aria-label': `View ${product.name}`},
          source ? h('img', {src: source, alt: product.name, loading: 'lazy', referrerPolicy: 'no-referrer'}) : h('span', {className: 'product-fallback', 'aria-hidden': true}, 'k.')),
        h('div', {className: 'assistant-pick-copy'},
          h(Badge, {label: product.category_path?.[0] || 'The collection', variant: 'neutral'}),
          h(Button, {label: product.name, variant: 'ghost', className: 'assistant-pick-name', onClick: () => onOpen(product.id)}),
          h('div', {className: 'assistant-pick-bottom'},
            h('span', {className: 'product-price'}, formatPrice(product.price_paise)),
            h(Button, {label: 'Add', variant: 'secondary', size: 'sm', className: 'add-button', isDisabled: !canAdd(product), onClick: () => onAdd(product)}))));
    }));
}

window.kaufmannRenderProductGrid = (target, props) => {
  let root = roots.get(target);
  if (!root) {
    root = createRoot(target);
    roots.set(target, root);
  }
  flushSync(() => root.render(h(ProductGrid, props)));
};
window.kaufmannRenderAssistantPicks = (target, props) => {
  let root = roots.get(target);
  if (!root) { root = createRoot(target); roots.set(target, root); }
  flushSync(() => root.render(h(Theme, {theme: neutralTheme}, h(AssistantPicks, props))));
};
const voiceRoot = createRoot(document.querySelector('#voice-orb-mount'));
flushSync(() => voiceRoot.render(h(VoiceOrb)));
window.dispatchEvent(new Event('kaufmann:astryx-ready'));
window.dispatchEvent(new Event('kaufmann:voice-orb-ready'));
