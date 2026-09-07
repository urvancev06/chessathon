/* Mikhail LeTal web app — Docs, README §5: docs/*.md rendered client-side. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el, esc } = LT;

  function inline(text) {
    const codes = [];
    // Code spans are parked behind a sentinel no markdown text contains, so a digit between spaces
    // in the prose ("Stage 0") is never mistaken for a placeholder.
    let out = esc(text).replace(/`([^`\n]+)`/g, (match, code) => { codes.push(`<code>${code}</code>`); return `\u0000${codes.length - 1}\u0000`; });
    out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (match, alt) => `<em>[image: ${alt}]</em>`);
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => `<a href="${/^(https?:|mailto:|#|\/)/i.test(href) ? href : '#'}" rel="noopener" target="_blank">${label}</a>`);
    out = out.replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, '<a href="$1" rel="noopener" target="_blank">$1</a>');
    out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*\w]|$)/g, '$1<em>$2</em>');
    out = out.replace(/(^|[^\w])_([^_\n]+)_(?=[^\w]|$)/g, '$1<em>$2</em>');
    return out.replace(/\u0000(\d+)\u0000/g, (match, index) => codes[Number(index)]);
  }

  /** Markdown to HTML: headings, paragraphs, emphasis, code, links, lists, tables, quotes, rules. */
  LT.renderMarkdown = function renderMarkdown(source) {
    const lines = String(source).replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let i = 0;
    const isSeparator = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-');
    const splitRow = (line) => {
      let row = line.trim();
      if (row.startsWith('|')) row = row.slice(1);
      if (row.endsWith('|')) row = row.slice(0, -1);
      return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'));
    };
    const listItem = (line) => /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    function renderList(indent) {
      const first = listItem(lines[i]);
      const ordered = /\d/.test(first[2]);
      const items = [];
      while (i < lines.length) {
        const match = listItem(lines[i]);
        if (!match || match[1].length !== indent || (/\d/.test(match[2]) !== ordered)) break;
        const item = { text: match[3], children: [] };
        i += 1;
        while (i < lines.length) {
          const line = lines[i];
          if (line.trim() === '') {
            const next = lines[i + 1];
            if (next !== undefined && /^\s+\S/.test(next) && !listItem(next)) { item.text += '\n'; i += 1; continue; }
            if (next !== undefined && listItem(next) && listItem(next)[1].length > indent) { i += 1; continue; }
            break;
          }
          const nested = listItem(line);
          if (nested && nested[1].length > indent) { item.children.push(renderList(nested[1].length)); continue; }
          if (nested) break;
          if (/^\s+\S/.test(line)) { item.text += ` ${line.trim()}`; i += 1; continue; }
          break;
        }
        items.push(item);
      }
      const tag = ordered ? 'ol' : 'ul';
      return `<${tag}>${items.map((item) => `<li>${inline(item.text.trim())}${item.children.join('')}</li>`).join('')}</${tag}>`;
    }
    while (i < lines.length) {
      const line = lines[i];
      if (line.trim() === '') { i += 1; continue; }
      const fence = /^\s*(```|~~~)\s*([\w+-]*)/.exec(line);
      if (fence) {
        const code = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { code.push(lines[i]); i += 1; }
        i += 1;
        html.push(`<pre><code${fence[2] ? ` class="lang-${esc(fence[2])}"` : ''}>${esc(code.join('\n'))}</code></pre>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
      if (heading) {
        const id = heading[2].toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
        html.push(`<h${heading[1].length} id="${esc(id)}">${inline(heading[2])}</h${heading[1].length}>`);
        i += 1;
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { html.push('<hr>'); i += 1; continue; }
      if (line.trim().startsWith('|') && i + 1 < lines.length && isSeparator(lines[i + 1])) {
        const header = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(splitRow(lines[i])); i += 1; }
        const head = header.map((cell) => `<th>${inline(cell)}</th>`).join('');
        const body = rows.map((row) => `<tr>${header.map((cell, index) => `<td>${inline(row[index] || '')}</td>`).join('')}</tr>`).join('');
        html.push(`<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
        continue;
      }
      if (line.startsWith('>')) {
        const quote = [];
        while (i < lines.length && lines[i].startsWith('>')) { quote.push(lines[i].replace(/^>\s?/, '')); i += 1; }
        html.push(`<blockquote>${LT.renderMarkdown(quote.join('\n'))}</blockquote>`);
        continue;
      }
      if (listItem(line)) { html.push(renderList(listItem(line)[1].length)); continue; }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() !== '' && !/^(#{1,6})\s/.test(lines[i]) && !/^\s*(```|~~~)/.test(lines[i]) && !listItem(lines[i]) && !(lines[i].trim().startsWith('|') && isSeparator(lines[i + 1] || ''))) {
        paragraph.push(lines[i].trim());
        i += 1;
      }
      html.push(`<p>${inline(paragraph.join(' '))}</p>`);
    }
    return html.join('\n');
  };

  LT.screens.register('docs', {
    label: 'Docs',
    async mount(root, params) {
      const documents = await LT.api.get('/api/docs');
      if (!documents.length) {
        root.append(el('div', { class: 'empty-line' }, el('span', { text: 'No markdown files under docs/.' })));
        return () => {};
      }
      const wanted = params.get('doc');
      let current = documents.find((doc) => doc.name === wanted) || documents[0];
      const rail = el('div', { class: 'docs-rail', role: 'list' });
      const main = el('div', { class: 'docs-main md' });
      function render() {
        LT.clear(rail);
        for (const doc of documents) {
          rail.append(el('button', { type: 'button', class: `quiet${doc === current ? ' current' : ''}`, 'aria-current': doc === current ? 'page' : null, text: doc.name, onClick: () => {
            current = doc;
            history.replaceState(null, '', `#/docs?doc=${encodeURIComponent(doc.name)}`);
            render();
            main.scrollIntoView({ block: 'start' });
          } }));
        }
        main.innerHTML = LT.renderMarkdown(current.content);
        document.title = `${current.name} · Docs · Mikhail LeTal`;
      }
      render();
      root.append(el('div', { class: 'docs' }, rail, main));
      return () => {};
    },
  });
})();
