'use strict';
/*
 * Generates a clean, readable website from record_*.json files:
 *   - index.html                 : table of contents
 *   - record_<n>.html            : one page per record, linked from the index
 *
 * Formatting rules:
 *   - Bold quoted segments first (handles nested quotes via depth tracking),
 *     so multi-line quoted blocks stay bold across all their lines.
 *   - Then split on line breaks (\n) so every original line break is honored
 *     as a <br>. Output uses LF line endings.
 *   - Merge consecutive same-bold segments into one <strong> (quotes never
 *     fragment mid-run). Escape HTML metacharacters defensively (source is
 *     already clean).
 */

const fs = require('fs');
const path = require('path');

const DIR = process.cwd();
const RECORD_GLOB = /^record_\d+\.json$/;

function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/*
 * Bold quoted text. Walks the string char-by-char and toggles bold on each
 * double-quote. Nested quotes (quote inside quotes) are handled naturally:
 * bold only "closes" when a quote returns to the previous level.
 */
function splitQuotes(s) {
  const out = [];
  let bold = false;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '"') { bold = !bold; out.push({ text: '"', bold }); }
    else {
      // Scan forward to the next quote (exclusive). Stop on the quote so the
      // for-loop's i++ lands on it and toggles bold on the next iteration.
      let j = i;
      while (j < s.length && s[j] !== '"') j++;
      out.push({ text: s.slice(i, j), bold });
      i = j - 1; // next loop iteration processes the quote at j
    }
  }
  return out;
}

/*
 * Render the full content. Bold quoted segments first (so multi-line quoted
 * blocks stay bold across all lines), merge consecutive same-bold segments,
 * then split on \n so every original line break becomes a <br>.
 */
function renderContent(content) {
  const merged = [];
  for (const seg of splitQuotes(escapeHtml(content))) {
    const last = merged[merged.length - 1];
    if (last && last.bold === seg.bold) {
      last.text += seg.text;
    } else {
      merged.push(seg);
    }
  }
  const bolded = merged
    .map((seg) => (seg.bold ? '<strong class="q">' + seg.text + '</strong>' : seg.text))
    .join('');
  const lines = bolded.split('\n');
  return lines.map((line, i) => (i === 0 ? line : '<br>' + line)).join('');
}

function metaBlock(rec, title) {
  const author = rec.author || 'Unknown author';
  const chapter = rec.chapter || '\u2014';
  const filePath = rec.file_path || '\u2014';
  const wordCount = (contentWords(rec.content)).toLocaleString();
  const lineCount = rec.content.split('\n').length.toLocaleString();
  return '    <header class="meta">' +
    '<p class="meta-author">' + escapeHtml(author) + '</p>' +
    '<p class="meta-title">' + escapeHtml(title) + '</p>' +
    (rec.chapter ? '<p class="meta-chapter">' + escapeHtml(rec.chapter) + '</p>' : '') +
    '<dl class="meta-detail">' +
    '<dt>File</dt><dd>' + escapeHtml(filePath) + '</dd>' +
    '<dt>Words</dt><dd>' + wordCount + '</dd>' +
    '<dt>Lines</dt><dd>' + lineCount + '</dd>' +
    '</dl>' +
    '</header>';
}

function contentWords(text) {
  const m = text.match(/[A-Za-z0-9]+/g);
  return m ? m.length : 0;
}

function recordHtml(rec, num) {
  const title = rec.title || ('Untitled (' + num + ')');
  return '<!DOCTYPE html>\n' +
    '<html lang="en">\n' +
    '<head>\n' +
    '<meta charset="utf-8">\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
    '<title>' + escapeHtml(title) + ' \u00b7 ' + escapeHtml(rec.author || '') + '</title>\n' +
    '<link rel="stylesheet" href="style.css">\n' +
    '</head>\n' +
    '<body>\n' +
    '<main class="record">\n' +
    '<a class="back" href="index.html">\u2190 Back to contents</a>\n' +
    '<article>\n' +
    metaBlock(rec, title) +
    '<h1 class="story-title">' + escapeHtml(title) + '</h1>\n' +
    '<div class="story-body">' + renderContent(rec.content) + '</div>\n' +
    '</article>\n' +
    '</main>\n' +
    '<footer class="footer">\n' +
    '  <span>' + escapeHtml(rec.author || '') + '</span> \u00b7 <span>' + escapeHtml(rec.chapter || '') + '</span> \u00b7 <span>record ' + num + '</span>\n' +
    '</footer>\n' +
    '</body>\n' +
    '</html>\n';
}

function indexHtml(records) {
  const rows = records
    .map(
      (r) => '      <li>\n' +
        '        <a class="toc-link" href="' + r.html + '">' + escapeHtml(r.title) + '</a>\n' +
        '        <span class="toc-by">' + escapeHtml(r.author) + '</span>\n' +
        '        <span class="toc-chap">' + escapeHtml(r.chapter) + '</span>\n' +
        '      </li>'
    )
    .join('\n');

  const count = records.length.toLocaleString();
  const totalWords = records.reduce((n, r) => n + contentWords(r.content), 0).toLocaleString();

  return '<!DOCTYPE html>\n' +
    '<html lang="en">\n' +
    '<head>\n' +
    '<meta charset="utf-8">\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
    '<title>Contents</title>\n' +
    '<link rel="stylesheet" href="style.css">\n' +
    '</head>\n' +
    '<body>\n' +
    '<main class="home">\n' +
    '<h1 class="home-title">Tiff &middot; Stories</h1>\n' +
    '<p class="home-sub">' + count + ' stories \u00b7 ' + totalWords + ' words</p>\n' +
    '<nav class="toc">\n' + rows + '\n' +
    '</nav>\n' +
    '</main>\n' +
    '<footer class="footer">\n' +
    '  <span>Table of contents</span>\n' +
    '</footer>\n' +
    '</body>\n' +
    '</html>\n';
}

function main() {
  const files = fs
    .readdirSync(DIR)
    .filter((f) => RECORD_GLOB.test(f))
    .sort((a, b) => a.localeCompare(b));

  if (files.length === 0) {
    console.error('No record_*.json files found.');
    process.exit(1);
  }

  const records = [];
  for (const file of files) {
    const rec = JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));
    rec.html = file.replace(/\.json$/, '.html');
    rec.num = rec.idx != null ? rec.idx : Number(file.match(/\d+/)[0]);
    records.push(rec);
  }

  for (const rec of records) {
    const html = recordHtml(rec, rec.num);
    fs.writeFileSync(path.join(DIR, rec.html), html, 'utf8');
    console.log('wrote ' + rec.html + '  (' + contentWords(rec.content).toLocaleString() + ' words)');
  }

  const index = indexHtml(records);
  fs.writeFileSync(path.join(DIR, 'index.html'), index, 'utf8');
  console.log('wrote index.html  (' + records.length + ' entries)');
}

main();
