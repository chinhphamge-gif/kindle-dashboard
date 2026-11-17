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
  PropertiesService.getScriptProperties().setProperty('claude_usage', JSON.stringify(keep));
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

  const claudeRaw = PropertiesService.getScriptProperties().getProperty('claude_usage');
  return { generated: new Date().toISOString(), events: events, tasks: tasks, claude: claudeRaw ? JSON.parse(claudeRaw) : null };
}

/** Bấm Run hàm này trong trình soạn thảo để kiểm tra (xem kết quả ở Execution log). */
function testCollect() {
  Logger.log(JSON.stringify(collect_(), null, 2));
}
