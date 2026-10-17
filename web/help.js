/* One help catalog powers hover/focus explanations and the input reference. */
(() => {
  'use strict';
  function description(node, catalog) {
    return catalog.paths[node.dataset.path] || catalog.ids[node.id] ||
      (node.closest('#workspaceSurveyRows') && catalog.survey[node.dataset.col || (node.hasAttribute('data-axis') ? 'axis' : '')]) ||
      catalog.layers[node.dataset.layer] || '';
  }
  function attach(root, catalog) {
    const fields = [...(root.matches?.('input,select,textarea') ? [root] : []), ...root.querySelectorAll('input,select,textarea')];
    for (const node of fields) {
      const text = description(node, catalog);
      if (!text || node.dataset.helpAttached) continue;
      node.dataset.helpAttached = 'true';
      node.title = text;
      const detail = document.createElement('span');
      detail.id = `rangelab-field-help-${++attach.sequence}`;
      detail.className = 'field-help-description';
      // Referenced hidden descriptions stay out of wrapping-label names.
      detail.hidden = true;
      detail.textContent = text;
      node.after(detail);
      const existing = node.getAttribute('aria-describedby');
      node.setAttribute('aria-describedby', [existing, detail.id].filter(Boolean).join(' '));
    }
  }
  attach.sequence = 0;
  async function init() {
    const response = await fetch('/input-help.json');
    if (!response.ok) throw Error('Input help unavailable');
    const catalog = await response.json();
    attach(document, catalog);
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType === 1) attach(node, catalog);
    }))).observe(document.body, {childList:true, subtree:true});
    const tip = document.createElement('div');
    tip.className = 'field-help-tooltip'; tip.hidden = true; tip.setAttribute('aria-hidden','true');
    document.body.append(tip);
    let active;
    function show(event) {
      const node = event.target;
      if (!node.matches?.('input,select,textarea')) return;
      const text = description(node, catalog); if (!text) return;
      active = node; tip.textContent = text; tip.hidden = false;
      const rect = node.getBoundingClientRect(), width = tip.offsetWidth, height = tip.offsetHeight;
      tip.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - width - 8))}px`;
      tip.style.top = `${Math.max(8, Math.min(rect.bottom + 6, innerHeight - height - 8))}px`;
    }
    const hide = () => {tip.hidden = true; active = null;};
    document.addEventListener('focusin',show);
    document.addEventListener('pointerover',show);
    document.addEventListener('focusout',hide);
    document.addEventListener('pointerout',event => {if(event.target === active) hide();});
    document.addEventListener('keydown',event => {
      if(event.key === 'Escape' && !tip.hidden) {hide(); event.stopPropagation();}
    },true);
    document.addEventListener('input',hide);
    document.addEventListener('scroll',hide,true);
    window.addEventListener('resize',hide);
  }
  window.RangeLabHelp = {description, attach};
  document.addEventListener('DOMContentLoaded', () => init().catch(error => console.warn(error.message)));
})();
