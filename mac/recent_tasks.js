// Lấy các phiên Claude Code gần đây trên Mac: tên việc + tóm tắt kết quả.
// Chạy:  osascript -l JavaScript recent_tasks.js      → in ra JSON (mảng)
// Không cần cài gì thêm (JavaScript for Automation có sẵn trên macOS).
//
// Nguồn: ~/.claude/projects/<thư mục dự án>/<phiên>.jsonl (Claude Code tự ghi).
// Bỏ qua dự án: ghi mỗi dòng một đoạn đường dẫn vào ~/.kindle-dashboard-exclude
//   (vd "khach-hang" → mọi phiên có thư mục chứa "khach-hang" sẽ không hiện lên Kindle).

var MAX_TASKS = 5;          // số việc gửi lên
var MAX_FILES = 25;         // số file phiên mới nhất đem đọc
var MAX_BYTES = 40e6;       // bỏ qua file phiên quá lớn

// ---------------------------------------------------------------- làm sạch chữ
function clean(s) {
  s = String(s || '');
  s = s.replace(/```[\s\S]*?```/g, ' ');                 // khối code
  s = s.replace(/<[^>]{1,200}>/g, ' ');                  // thẻ <...>
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ');           // ảnh markdown
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');         // link markdown → chữ
  s = s.replace(/https?:\/\/\S+/g, ' ');                 // URL trần (có thể chứa token)
  s = s.replace(/[`*]+/g, '');                           // ký hiệu markdown (giữ dấu _ trong tên file)
  s = s.replace(/[#>|]+/g, ' ');
  s = s.replace(/\s+([,.;:!?])/g, '$1');
  s = s.replace(/^\s*[-•]\s+/gm, '');                    // gạch đầu dòng
  // bỏ emoji / ký tự font Inter không vẽ được (giữ tiếng Việt, dấu câu, mũi tên)
  s = s.replace(/[\uD800-\uDFFF]/g, '').replace(/[─-￿]/g, ' ');
  return s.replace(/\s+/g, ' ').trim();
}

function shorten(s, n) {
  if (s.length <= n) return s;
  var cut = s.slice(0, n);
  var sp = cut.lastIndexOf(' ');
  return (sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:–-]+$/, '') + '…';
}

// 1–2 câu đầu của kết quả, tối đa ~220 ký tự
function firstSentences(s, n) {
  // tách câu không dùng lookbehind (macOS cũ không hỗ trợ)
  var parts = s.replace(/([.!?…])\s+/g, '$1\u0000').split('\u0000');
  var out = '';
  for (var i = 0; i < parts.length; i++) {
    var next = out ? out + ' ' + parts[i] : parts[i];
    if (next.length > n && out) break;
    out = next;
    if (out.length > n * 0.55) break;
  }
  return shorten(out, n);
}

// ---------------------------------------------------------------- đọc 1 phiên
function textOf(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.filter(function (b) { return b && b.type === 'text'; })
                .map(function (b) { return b.text || ''; }).join('\n');
}

function isRealPrompt(rec) {
  if (rec.type !== 'user' || rec.isSidechain || rec.isMeta) return false;
  var c = rec.message && rec.message.content;
  if (Array.isArray(c) && c.some(function (b) { return b && b.type === 'tool_result'; })) return false;
  var t = textOf(c).trim();
  if (!t || t.charAt(0) === '<') return false;                 // <command-name>, <local-command-...>
  if (/^Caveat:|^\[Request interrupted/i.test(t)) return false;
  return true;
}

function parseSession(text, summaries) {
  var lines = text.split('\n');
  var title = '', result = '', cwd = '', at = '', uuids = [];
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    if (!ln) continue;
    var rec;
    try { rec = JSON.parse(ln); } catch (e) { continue; }
    if (rec.type === 'summary' && rec.summary && rec.leafUuid) {
      summaries[rec.leafUuid] = rec.summary;
      continue;
    }
    if (rec.uuid) uuids.push(rec.uuid);
    if (rec.cwd) cwd = rec.cwd;
    if (rec.timestamp && !rec.isSidechain) at = rec.timestamp;
    if (!title && isRealPrompt(rec)) title = textOf(rec.message.content);
    if (rec.type === 'assistant' && !rec.isSidechain && rec.message) {
      var t = textOf(rec.message.content).trim();
      if (t) result = t;
    }
  }
  return { title: title, result: result, cwd: cwd, at: at, uuids: uuids };
}

// ---------------------------------------------------------------- gom kết quả
// files: [{path, mtime(ms), size}] ; read(path) → chuỗi ; exclude: [chuỗi]
function collect(files, read, exclude) {
  files = files.filter(function (f) { return f.size > 0 && f.size < MAX_BYTES; })
               .sort(function (a, b) { return b.mtime - a.mtime; })
               .slice(0, MAX_FILES);
  var summaries = {}, sessions = [];
  files.forEach(function (f) {
    var txt;
    try { txt = read(f.path); } catch (e) { return; }
    if (!txt) return;
    var s = parseSession(txt, summaries);
    s.mtime = f.mtime;
    sessions.push(s);
  });
  var out = [];
  for (var i = 0; i < sessions.length && out.length < MAX_TASKS; i++) {
    var s = sessions[i];
    if (!s.title || !s.result) continue;
    if (/kindle-dashboard-mac/.test(s.cwd)) continue;           // phiên làm mới token của chính script này
    if (exclude.some(function (x) { return x && s.cwd.indexOf(x) !== -1; })) continue;
    var title = '';
    for (var k = s.uuids.length - 1; k >= 0 && !title; k--) title = summaries[s.uuids[k]] || '';
    title = clean(title || s.title.split('\n')[0]);
    if (!title || /^(ok|hi|test)$/i.test(title)) continue;
    var proj = s.cwd ? s.cwd.replace(/\/+$/, '').split('/').pop() : '';
    out.push({
      title: shorten(title, 90),
      result: firstSentences(clean(s.result), 220),
      project: clean(proj).slice(0, 40),
      at: s.at || new Date(s.mtime).toISOString()
    });
  }
  return out;
}

// ---------------------------------------------------------------- chạy bằng osascript (macOS)
function run() {
  ObjC.import('Foundation');
  var fm = $.NSFileManager.defaultManager;
  var home = ObjC.unwrap($.NSHomeDirectory());
  var root = home + '/.claude/projects';

  function ls(dir) {
    var a = fm.contentsOfDirectoryAtPathError(dir, null);
    return a ? ObjC.deepUnwrap(a) || [] : [];
  }
  function read(p) {
    var s = $.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null);
    return s ? ObjC.unwrap(s) : '';
  }

  var files = [];
  ls(root).forEach(function (d) {
    ls(root + '/' + d).forEach(function (f) {
      if (!/\.jsonl$/.test(f)) return;
      var p = root + '/' + d + '/' + f;
      var at = fm.attributesOfItemAtPathError(p, null);
      if (!at) return;
      var md = at.objectForKey('NSFileModificationDate');
      var sz = at.objectForKey('NSFileSize');
      files.push({ path: p, mtime: md ? md.timeIntervalSince1970 * 1000 : 0, size: sz ? Number(ObjC.unwrap(sz)) : 0 });
    });
  });

  var exclude = read(home + '/.kindle-dashboard-exclude').split('\n')
                  .map(function (x) { return x.trim(); }).filter(Boolean);
  return JSON.stringify(collect(files, read, exclude));
}

if (typeof module !== 'undefined') module.exports = { collect: collect, clean: clean, firstSentences: firstSentences };
