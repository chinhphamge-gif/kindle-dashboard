/**
 * Google Apps Script: trả về lịch (hôm nay + ngày mai) và việc chưa xong trong Google Tasks dạng JSON.
 * Chạy dưới tài khoản Google của bạn — không cần Google Cloud Console.
 *
 * Cài đặt (xem README, mục 1):
 *  1. script.google.com → New project → dán toàn bộ file này.
 *  2. Không cần tự đặt TOKEN: script tự sinh một chuỗi bí mật và lưu trong Script Properties.
 *  3. Services (+) → thêm "Google Tasks API".
 *  4. Deploy → New deployment → Web app; Execute as: Me; Who has access: Anyone → Deploy, cho phép quyền.
 *  5. Dán Web app URL vào WEB_APP_URL bên dưới, Save, rồi chạy hàm showDataUrl → copy dòng DATA_URL trong Execution log → dán vào GitHub secret DATA_URL.
 */
/** Chuỗi bí mật: tự sinh ở lần gọi đầu, lưu trong Script Properties (không nằm trong mã nguồn). */
function token_() {
  const p = PropertiesService.getScriptProperties();
  let t = p.getProperty('token');
  if (!t) {
    t = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '').slice(0, 40);
    p.setProperty('token', t);
  }
  return t;
}

/** Chạy SAU khi Deploy: in DATA_URL ra Execution log để copy. Không gửi dòng này cho ai. */
function showDataUrl() {
  Logger.log('DATA_URL: ' + (WEB_APP_URL || '<Web app URL>') + '?token=' + token_());
}

/** Lỡ lộ link thì chạy hàm này để đổi chuỗi bí mật, rồi chạy lại showDataUrl. */
function resetToken() {
  PropertiesService.getScriptProperties().deleteProperty('token');
  showDataUrl();
}
const TZ = 'Asia/Ho_Chi_Minh';
// Dán Web app URL (Deploy → Manage deployments, dạng https://script.google.com/macros/s/.../exec) vào đây rồi Save.
// Không dùng ScriptApp.getService().getUrl(): trong trình soạn thảo nó trả link thử /dev, GitHub không gọi được.
const WEB_APP_URL = '';

// ---- Kích GitHub vẽ lại ảnh đúng giờ (lịch cron của GitHub hay trễ hàng giờ) ----
// Repo GitHub của dashboard, dạng 'ten-github/kindle-dashboard'.
const GH_REPO = '';
// Mấy phút kích một lần (Apps Script chỉ nhận 1, 5, 10, 15, 30).
const KICK_MINUTES = 10;

/**
 * Gọi GitHub chạy workflow update.yml. Được trigger hẹn giờ gọi tự động.
 * Cần token GitHub lưu trong Project Settings → Script Properties, tên GITHUB_TOKEN
 * (fine-grained token, chỉ repo dashboard, quyền Actions: Read and write).
 */
function kick() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token || !GH_REPO) { Logger.log('Thiếu GITHUB_TOKEN (Script Properties) hoặc GH_REPO'); return; }
  const now = new Date();
  const h = Number(Utilities.formatDate(now, TZ, 'H')), m = Number(Utilities.formatDate(now, TZ, 'm'));
  // Ban đêm 0–8 giờ Kindle chỉ làm mới 4 tiếng/lần → chỉ vẽ lúc 0h và 4h
  if (h < 8 && !((h === 0 || h === 4) && m < KICK_MINUTES)) return;
  const r = UrlFetchApp.fetch('https://api.github.com/repos/' + GH_REPO + '/actions/workflows/update.yml/dispatches', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
    payload: JSON.stringify({ ref: 'main' }),
    muteHttpExceptions: true,
  });
  if (r.getResponseCode() !== 204) {
    throw new Error('GitHub trả mã ' + r.getResponseCode() + ': ' + r.getContentText().slice(0, 200));
  }
  Logger.log('Đã kích GitHub vẽ lại ảnh');
}

/** Chạy 1 lần để bật hẹn giờ (chạy lại cũng không tạo trùng). */
function installTrigger() {
  removeTrigger();
  ScriptApp.newTrigger('kick').timeBased().everyMinutes(KICK_MINUTES).create();
  Logger.log('Đã bật hẹn giờ: ' + KICK_MINUTES + ' phút/lần');
  kick();
}

/** Tắt hẹn giờ. */
function removeTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'kick') ScriptApp.deleteTrigger(t);
  });
}

function doGet(e) {
  if (!e || !e.parameter || e.parameter.token !== token_()) {
    return ContentService.createTextOutput('{"error":"forbidden"}').setMimeType(ContentService.MimeType.JSON);
  }
  return ContentService.createTextOutput(JSON.stringify(collect_())).setMimeType(ContentService.MimeType.JSON);
}

/** Mac mini gửi mức dùng Claude lên đây (POST ?token=...), lưu lại để doGet trả kèm. */
function doPost(e) {
  if (!e || !e.parameter || e.parameter.token !== token_()) {
    return ContentService.createTextOutput('{"error":"forbidden"}').setMimeType(ContentService.MimeType.JSON);
  }
  const body = JSON.parse(e.postData.contents);
  const props = PropertiesService.getScriptProperties();
  // Danh sách phiên Claude Code gần đây (mac/recent_tasks.js) → lưu riêng
  if (Array.isArray(body.kindle_tasks)) {
    const items = body.kindle_tasks.slice(0, 8);
    let s = JSON.stringify({ fetched_at: new Date().toISOString(), items: items });
    while (s.length > 8500 && items.length) { items.pop(); s = JSON.stringify({ fetched_at: new Date().toISOString(), items: items }); }
    props.setProperty('claude_tasks', s);
  }
  delete body.kindle_tasks;
  // Giữ mọi mục có % sử dụng (five_hour, seven_day, Fable, ...) + danh sách tên mục để dò lỗi
  const keep = { fetched_at: new Date().toISOString(), bucket_keys: Object.keys(body) };
  Object.keys(body).forEach(function (k) {
    const v = body[k];
    if (v && typeof v === 'object' && typeof v.utilization === 'number') {
      keep[k] = { utilization: v.utilization, resets_at: v.resets_at || null };
    }
  });
  // Bản thô (chỉ các mục khác null): Fable nằm trong danh sách "limits" ở đây
  const raw = {};
  Object.keys(body).forEach(function (k) { if (body[k] !== null) raw[k] = body[k]; });
  keep.raw = JSON.stringify(raw).slice(0, 6000);
  // Chỉ ghi đè mức dùng khi lần này thật sự có số liệu (Mac lỗi mạng/token thì giữ số cũ, màn hình tự báo "số liệu cũ")
  if (Object.keys(keep).some(function (k) { return keep[k] && typeof keep[k].utilization === 'number'; })) {
    props.setProperty('claude_usage', JSON.stringify(keep));
  }
  return ContentService.createTextOutput('{"ok":true}').setMimeType(ContentService.MimeType.JSON);
}

function collect_() {
  const today = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');
  const start = new Date(today + 'T00:00:00+07:00');
  const end = new Date(start.getTime() + 2 * 86400000);

  const events = [];
  CalendarApp.getAllCalendars().forEach(function (cal) {
    if (cal.isHidden() || !cal.isSelected()) return;
    cal.getEvents(start, end).forEach(function (ev) {
      try {
        if (ev.getMyStatus() === CalendarApp.GuestStatus.NO) return;  // đã từ chối
      } catch (err) {}
      const o = { title: ev.getTitle() || '(Không tiêu đề)', location: ev.getLocation() || '', calendar: cal.getName() };
      if (ev.isAllDayEvent()) {
        o.allDay = true;
        o.startDate = Utilities.formatDate(ev.getAllDayStartDate(), TZ, 'yyyy-MM-dd');
        o.endDate = Utilities.formatDate(ev.getAllDayEndDate(), TZ, 'yyyy-MM-dd');
      } else {
        o.allDay = false;
        o.start = ev.getStartTime().toISOString();
        o.end = ev.getEndTime().toISOString();
      }
      events.push(o);
    });
  });

  const tasks = [];
  const lists = Tasks.Tasklists.list({ maxResults: 100 }).items || [];
  lists.forEach(function (tl) {
    let pageToken;
    do {
      const r = Tasks.Tasks.list(tl.id, { showCompleted: false, showHidden: false, maxResults: 100, pageToken: pageToken });
      (r.items || []).forEach(function (t) {
        if (t.title && t.title.trim()) {
          tasks.push({ title: t.title.trim(), due: t.due ? t.due.slice(0, 10) : null, list: tl.title, notes: t.notes || '' });
        }
      });
      pageToken = r.nextPageToken;
    } while (pageToken);
  });

  const props = PropertiesService.getScriptProperties();
  const claudeRaw = props.getProperty('claude_usage');
  const tasksRaw = props.getProperty('claude_tasks');
  return { generated: new Date().toISOString(), events: events, tasks: tasks,
           claude: claudeRaw ? JSON.parse(claudeRaw) : null,
           claude_tasks: tasksRaw ? JSON.parse(tasksRaw) : null };
}

/** Bấm Run hàm này trong trình soạn thảo để kiểm tra (xem kết quả ở Execution log). */
function testCollect() {
  Logger.log(JSON.stringify(collect_(), null, 2));
}
