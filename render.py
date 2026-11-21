#!/usr/bin/env python3
"""Vẽ dashboard lịch + todo cho Kindle Paperwhite 3 (1072x1448, xám).
Máy khác: đặt DASH_W / DASH_H đúng điểm ảnh màn hình (vd Paperwhite 11th gen: 1236 x 1648).

Dữ liệu thật (dùng trong GitHub Actions):
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN  (biến môi trường)
    python render.py --out _site/dashboard.png

Xem trước bằng dữ liệu mẫu:
    python render.py --sample sample.json --out preview.png
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- cấu hình
# điểm ảnh thật của màn Kindle — mặc định Paperwhite 3 (đời 7): 1072 x 1448
PW, PH = int(os.environ.get("DASH_W") or 1072), int(os.environ.get("DASH_H") or 1448)
# Phóng to toàn bộ bố cục (chữ + khoảng cách). 1.0 = cỡ gốc, 1.3 = to hơn 30%.
SCALE = float(os.environ.get("DASH_SCALE") or "1.05")
W, H = round(PW / SCALE), round(PH / SCALE)   # kích thước "logic" dùng khi bố trí
TZ = ZoneInfo(os.environ.get("DASH_TZ", "Asia/Ho_Chi_Minh"))
# Bỏ qua các lịch có tên trong danh sách này (phân tách bằng dấu phẩy)
# Bố cục (biến DASH_LAYOUT):
#   daydu  = ngày + thời tiết/AQI gọn ở đầu, Claude to (Tuần → Phiên 5 giờ | Fable), việc, lịch (mặc định)
#   lich   = ngày + thời tiết to ở đầu, Claude 2 thanh nhỏ
#   claude = bỏ đầu trang, mục Claude to ở trên cùng
TITLE = os.environ.get("DASH_TITLE") or "Claude"   # tiêu đề bố cục "claude"
LAYOUT = (os.environ.get("DASH_LAYOUT") or "daydu").strip().lower()
SKIP_CALENDARS = {s.strip() for s in os.environ.get("DASH_SKIP_CALENDARS", "").split(",") if s.strip()}

FONT_DIR = Path(__file__).parent / "fonts"
BLACK, DARK, MID, LIGHT, PALE, WHITE = 0, 60, 120, 180, 225, 255
MARGIN = round(72 / SCALE ** 0.5)   # lề tăng ít hơn chữ để không phí chỗ

THU = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for p in (FONT_DIR / f"Inter-{weight}.otf",
              Path(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if weight in ('Bold', 'SemiBold') else ''}.ttf")):
        if p.exists():
            return ImageFont.truetype(str(p), round(size * SCALE))
    return ImageFont.load_default(round(size * SCALE))


class ScaledDraw:
    """Vẽ theo toạ độ logic, tự nhân SCALE sang điểm ảnh thật (chữ vẫn nét căng)."""

    def __init__(self, img):
        self._img = img
        self._d = ImageDraw.Draw(img)

    @staticmethod
    def _xy(v):
        if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)):
            return [(x * SCALE, y * SCALE) for x, y in v]
        return [c * SCALE for c in v]

    @staticmethod
    def _kw(kw):
        for k in ("width", "radius"):
            if k in kw:
                kw[k] = max(1, round(kw[k] * SCALE))
        return kw

    def textlength(self, text, font):
        return self._d.textlength(text, font=font) / SCALE

    def text(self, xy, text, **kw):
        self._d.text((xy[0] * SCALE, xy[1] * SCALE), text, **kw)

    def line(self, xy, **kw):
        self._d.line(self._xy(xy), **self._kw(kw))

    def polygon(self, xy, **kw):
        self._d.polygon(self._xy(xy), **self._kw(kw))

    def ellipse(self, xy, **kw):
        self._d.ellipse(self._xy(xy), **self._kw(kw))

    def rounded_rectangle(self, xy, **kw):
        self._d.rounded_rectangle(self._xy(xy), **self._kw(kw))


# ---------------------------------------------------------------- dữ liệu
@dataclass
class Event:
    title: str
    start: datetime | None  # None = cả ngày
    end: datetime | None
    location: str = ""
    calendar: str = ""

    @property
    def all_day(self) -> bool:
        return self.start is None


@dataclass
class Task:
    title: str
    due: date | None
    list_name: str = ""
    notes: str = ""


def _google_session():
    import requests

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


def _get_all(s, url, params=None):
    params = dict(params or {})
    while True:
        r = s.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        yield from data.get("items", [])
        if not data.get("nextPageToken"):
            return
        params["pageToken"] = data["nextPageToken"]


def fetch_google(today: date) -> tuple[list[Event], list[Task]]:
    s = _google_session()
    t0 = datetime.combine(today, time.min, TZ)
    t1 = t0 + timedelta(days=2)

    events: list[Event] = []
    for cal in _get_all(s, "https://www.googleapis.com/calendar/v3/users/me/calendarList"):
        name = cal.get("summaryOverride") or cal.get("summary", "")
        if name in SKIP_CALENDARS or cal.get("selected") is False:
            continue
        for e in _get_all(s, f"https://www.googleapis.com/calendar/v3/calendars/{cal['id']}/events", {
            "timeMin": t0.isoformat(), "timeMax": t1.isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": 100,
        }):
            if e.get("status") == "cancelled":
                continue
            if any(a.get("self") and a.get("responseStatus") == "declined" for a in e.get("attendees", [])):
                continue
            st, en = e.get("start", {}), e.get("end", {})
            if "dateTime" in st:
                start = datetime.fromisoformat(st["dateTime"]).astimezone(TZ)
                end = datetime.fromisoformat(en["dateTime"]).astimezone(TZ)
                events.append(Event(e.get("summary", "(Không tiêu đề)"), start, end, e.get("location", ""), name))
            else:
                d0, d1 = date.fromisoformat(st["date"]), date.fromisoformat(en["date"])
                # mỗi ngày của sự kiện cả ngày -> ghi lại ngày bắt đầu bằng end=None, start=None
                for i in range((d1 - d0).days):
                    d = d0 + timedelta(days=i)
                    if today <= d <= today + timedelta(days=1):
                        ev = Event(e.get("summary", "(Không tiêu đề)"), None, None, e.get("location", ""), name)
                        ev.__dict__["day"] = d
                        events.append(ev)

    tasks: list[Task] = []
    for tl in _get_all(s, "https://tasks.googleapis.com/tasks/v1/users/@me/lists"):
        for t in _get_all(s, f"https://tasks.googleapis.com/tasks/v1/lists/{tl['id']}/tasks", {
            "showCompleted": "false", "showHidden": "false", "maxResults": 100,
        }):
            if not t.get("title", "").strip():
                continue
            due = date.fromisoformat(t["due"][:10]) if t.get("due") else None
            tasks.append(Task(t["title"].strip(), due, tl.get("title", ""), t.get("notes", "")))
    return events, tasks


def parse_payload(data: dict, today: date) -> tuple[list[Event], list[Task]]:
    """Đọc JSON từ Google Apps Script (apps_script.gs)."""
    events: list[Event] = []
    for e in data.get("events", []):
        name = e.get("calendar", "")
        if name in SKIP_CALENDARS:
            continue
        if e.get("allDay"):
            d0 = date.fromisoformat(e["startDate"])
            d1 = date.fromisoformat(e.get("endDate") or e["startDate"])
            if d1 <= d0:
                d1 = d0 + timedelta(days=1)
            d = d0
            while d < d1:
                if today <= d <= today + timedelta(days=1):
                    ev = Event(e["title"], None, None, e.get("location", ""), name)
                    ev.__dict__["day"] = d
                    events.append(ev)
                d += timedelta(days=1)
        else:
            start = datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone(TZ)
            end = datetime.fromisoformat(e["end"].replace("Z", "+00:00")).astimezone(TZ)
            events.append(Event(e["title"], start, end, e.get("location", ""), name))
    tasks = [Task(t["title"], date.fromisoformat(t["due"]) if t.get("due") else None,
                  t.get("list", ""), t.get("notes", "")) for t in data.get("tasks", [])]
    return events, tasks


def fetch_appscript(url: str, today: date) -> tuple[list[Event], list[Task]]:
    import requests

    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise SystemExit(f"Apps Script báo lỗi: {data['error']} (kiểm tra token trong DATA_URL)")
    global CLAUDE_USAGE, CLAUDE_TASKS
    CLAUDE_USAGE = data.get("claude")
    CLAUDE_TASKS = data.get("claude_tasks")
    # chỉ in số lượng, không in nội dung (log GitHub Actions của repo công khai ai cũng xem được)
    print("Claude Code:", len((CLAUDE_TASKS or {}).get("items") or []), "phiên")
    if CLAUDE_USAGE:
        fb = _find_fable(CLAUDE_USAGE)
        print("Fable:", f"{fb.get('utilization')}%" if fb else "không thấy trong số liệu")
    return parse_payload(data, today)


# ---------------------------------------------------------------- mức dùng Claude
CLAUDE_TASKS: dict | None = None   # {"fetched_at", "items": [{"title", "result", "project", "at"}]} — từ mac/recent_tasks.js
CLAUDE_USAGE: dict | None = None   # {"five_hour": {"utilization", "resets_at"}, "seven_day": {...}, "fetched_at"}
THU_NGAN = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def _reset_label(iso: str | None, now: datetime) -> str:
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return ""
    if t.date() == now.date():
        return f"đặt lại {t:%H:%M}"
    return f"đặt lại {THU_NGAN[t.weekday()]} {t:%H:%M}"


def draw_claude(d, y: int, usage: dict, now: datetime) -> int:
    """Hai thanh: phiên 5 giờ + giới hạn tuần. Trả về y mới."""
    f_lab, f_pct, f_small = font("Bold", 24), font("Bold", 30), font("Regular", 22)
    d.text((MARGIN, y), "CLAUDE", font=f_lab, fill=BLACK)
    fetched = usage.get("fetched_at")
    if fetched:
        try:
            ft = datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(TZ)
            age = (now - ft).total_seconds() / 3600
            if age > 2:
                note = f"số liệu cũ, lúc {ft:%H:%M %d/%m}"
                d.text((W - MARGIN - d.textlength(note, font=f_small), y + 2), note, font=f_small, fill=MID)
        except ValueError:
            pass
    y += 38
    gap = 40
    col_w = (W - 2 * MARGIN - gap) / 2
    for i, (key, name) in enumerate((("five_hour", "Phiên hiện tại"), ("seven_day", "Tuần này"))):
        x0 = MARGIN + i * (col_w + gap)
        v = (usage.get(key) or {})
        pct = v.get("utilization")
        pct_txt = "--" if pct is None else f"{round(pct)}%"
        d.text((x0, y), name, font=font("Medium", 24), fill=DARK)
        d.text((x0 + col_w - d.textlength(pct_txt, font=f_pct), y - 4), pct_txt, font=f_pct, fill=BLACK)
        by = y + 38
        d.rounded_rectangle([x0, by, x0 + col_w, by + 16], radius=8, outline=BLACK, width=2)
        if pct:
            fill_w = max(16, col_w * min(pct, 100) / 100)
            d.rounded_rectangle([x0, by, x0 + fill_w, by + 16], radius=8, fill=BLACK)
        d.text((x0, by + 24), _reset_label(v.get("resets_at"), now), font=f_small, fill=MID)
    return y + 92


def _remaining(iso: str | None, now: datetime) -> tuple[str, datetime | None]:
    """→ ("còn 2 giờ 05 phút", thời điểm đặt lại)"""
    if not iso:
        return "", None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return "", None
    mins = max(0, int((t - now).total_seconds() // 60))
    days, rem = divmod(mins, 1440)
    hrs, m = divmod(rem, 60)
    if days:
        txt = f"còn {days} ngày {hrs} giờ"
    elif hrs:
        txt = f"còn {hrs} giờ {m:02d} phút"
    else:
        txt = f"còn {m} phút"
    return txt, t


def draw_claude_big(d, y: int, usage: dict | None, now: datetime) -> int:
    """Bố cục claude: Tuần này 1 khối rất to (số % gấp đôi) + hàng nhỏ Phiên 5 giờ | Fable."""
    # dòng tiêu đề: [logo.png nếu có trong repo] + TITLE
    x = MARGIN
    logo_path = next((p for p in Path(__file__).parent.iterdir() if p.name.lower() == "logo.png"), None)
    if logo_path:
        try:
            lg = Image.open(logo_path).convert("RGBA")
            lh = round(52 * SCALE)
            lg = lg.resize((max(1, round(lg.width * lh / lg.height)), lh), Image.LANCZOS)
            bg = Image.new("RGBA", lg.size, (255, 255, 255, 255))
            bg.alpha_composite(lg)
            d._img.paste(bg.convert("L"), (round(x * SCALE), round((y - 4) * SCALE)))
            x += lg.width / SCALE + 16
        except Exception as e:
            print("Không đọc được logo.png:", e)
    d.text((x, y + 22), TITLE, font=font("Bold", 42), fill=BLACK, anchor="lm")
    note, stale = "", False
    if usage and usage.get("fetched_at"):
        try:
            ft = datetime.fromisoformat(usage["fetched_at"].replace("Z", "+00:00")).astimezone(TZ)
            stale = (now - ft).total_seconds() > 7200
            note = (f"SỐ LIỆU CŨ · {ft:%H:%M %d/%m}" if stale else f"số liệu lúc {ft:%H:%M}")
        except ValueError:
            pass
    if note:
        fn = font("SemiBold" if stale else "Regular", 24)
        d.text((W - MARGIN - d.textlength(note, font=fn), y + 22), note, font=fn, fill=BLACK if stale else MID, anchor="lm")
    y += 12
    y += 48
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=BLACK, width=6)
    y += 26
    if not usage:
        d.text((MARGIN, y), "Chưa có số liệu từ Mac mini.", font=font("Regular", 32), fill=MID)
        return y + 70

    week = usage.get("seven_day") or {}
    y = _claude_block(d, y, "Tuần này", week, now, timedelta(days=7), big=True)
    y += 4
    # hàng nhỏ 2 cột: Phiên 5 giờ | Fable
    gap = 44
    col_w = (W - 2 * MARGIN - gap) / 2
    fable = _find_fable(usage)
    _claude_mini(d, MARGIN, y, col_w, "Phiên 5 giờ", usage.get("five_hour") or {}, now)
    _claude_mini(d, MARGIN + col_w + gap, y, col_w, "Fable", fable, now,
                 empty="chưa có số liệu Fable")
    return y + 140


def _find_fable(usage: dict) -> dict | None:
    """Tìm mức dùng Fable. API đặt nó trong danh sách "limits" (kind weekly_scoped,
    scope.model.display_name = "Fable"); Apps Script gửi kèm bản thô trong trường "raw"."""
    key = os.environ.get("DASH_FABLE_KEY", "").strip()
    if key and isinstance(usage.get(key), dict):
        return usage[key]
    limits = usage.get("limits")
    if limits is None and usage.get("raw"):
        try:
            limits = json.loads(usage["raw"]).get("limits")
        except (ValueError, AttributeError):
            limits = None
    for lim in limits or []:
        if not isinstance(lim, dict):
            continue
        scope = lim.get("scope") or {}
        name = ((scope.get("model") or {}).get("display_name") or "") if isinstance(scope, dict) else ""
        if "fable" in name.lower():
            return {"utilization": lim.get("percent"), "resets_at": lim.get("resets_at")}
    for k, v in usage.items():
        if isinstance(v, dict) and ("fable" in k.lower() or "mythos" in k.lower()):
            return v
    return None


def _pct_text(d, x, y, pct, fp):
    """Vẽ số % với các chữ số rộng bằng nhau (thẳng cột). y = tâm dọc."""
    pct_txt = "--" if pct is None else f"{round(pct):02d}%"
    cell = max(d.textlength(c, font=fp) for c in "0123456789")
    for c in pct_txt:
        cw = d.textlength(c, font=fp)
        if c.isdigit():
            d.text((x + (cell - cw) / 2, y), c, font=fp, fill=BLACK, anchor="lm")
            x += cell
        else:
            d.text((x, y), c, font=fp, fill=BLACK, anchor="lm")
            x += cw
    return x


def _status(pct):
    return ("Thoải mái" if pct < 50 else "Vừa phải" if pct < 80
            else "Sắp chạm giới hạn" if pct < 100 else "Đã hết, chờ đặt lại")


def _claude_block(d, y, name, v, now, span, big=False, k=1.0, alert=""):
    """Khối to: số % rất to bên trái; bên phải tên + trạng thái + đặt lại; dưới là thanh dày toàn chiều ngang.
    k = hệ số thu nhỏ khối · alert = chữ cảnh báo thay cho trạng thái (vd số liệu cũ)."""
    pct = v.get("utilization")
    left, reset_at = _remaining(v.get("resets_at"), now)
    elapsed = min(max(1 - (reset_at - now) / span, 0), 1) if reset_at else None
    fp = font("Bold", 208 * k)
    x_end = _pct_text(d, MARGIN - 8 * k, y + 84 * k, pct, fp)
    rx = x_end + 34 * k
    d.text((rx, y + 14 * k), name.upper(), font=font("Bold", max(28, 34 * k)), fill=BLACK)
    if alert or pct is not None:
        status = alert or _status(pct)
        fs = font("SemiBold", max(24, 32 * k))
        if alert or pct >= 80:   # cảnh báo: chữ trắng trên nền đen
            status = fit(d, status, fs, W - MARGIN - rx - 32 * k)
            sw = d.textlength(status, font=fs)
            d.rounded_rectangle([rx, y + 60 * k, rx + sw + 32 * k, y + 106 * k], radius=23 * k, fill=BLACK)
            d.text((rx + 16 * k, y + 83 * k), status, font=fs, fill=WHITE, anchor="lm")
        else:
            d.text((rx, y + 83 * k), status, font=fs, fill=DARK, anchor="lm")
    fi = font("Medium", max(22, 26 * k))
    if reset_at:
        when = f"{reset_at:%H:%M}" if reset_at.date() == now.date() else f"{THU_NGAN[reset_at.weekday()]} {reset_at:%H:%M}"
        d.text((rx, y + 124 * k), f"đặt lại {when}", font=fi, fill=DARK, anchor="lm")
        d.text((rx, y + 158 * k), left, font=fi, fill=DARK, anchor="lm")
    y += 182 * k
    # thanh dày toàn chiều ngang
    bx0, bx1 = MARGIN, W - MARGIN
    bar_w = bx1 - bx0
    bh = round(50 * k)
    d.rounded_rectangle([bx0, y, bx1, y + bh], radius=bh // 2, outline=BLACK, width=5)
    for q in (0.25, 0.5, 0.75):
        x = bx0 + bar_w * q
        d.line([(x, y + bh * .26), (x, y + bh * .74)], fill=LIGHT, width=3)
    if pct:
        fw = max(bh, bar_w * min(pct, 100) / 100)
        d.rounded_rectangle([bx0, y, bx0 + fw, y + bh], radius=bh // 2, fill=BLACK)
    ty = y + bh + 6
    if elapsed is not None:   # ▲ thời gian đã trôi: phần đen nằm trái ▲ = đang dùng chậm hơn thời gian
        mx = bx0 + bar_w * elapsed
        d.polygon([(mx, ty), (mx - 13, ty + 18), (mx + 13, ty + 18)], fill=BLACK)
        cap = f"đã trôi {round(elapsed * 100)}% thời gian"
        fc = font("Regular", 22)
        cw = d.textlength(cap, font=fc)
        cx = mx + 20 if mx + 20 + cw <= bx1 else mx - 20 - cw
        d.text((cx, ty - 1), cap, font=fc, fill=MID)
    return ty + 34


def _claude_fetched(usage, now):
    """→ (thời điểm lấy số liệu Claude, đã cũ quá 2 giờ chưa)"""
    try:
        ft = datetime.fromisoformat(usage["fetched_at"].replace("Z", "+00:00")).astimezone(TZ)
        return ft, (now - ft).total_seconds() > 7200
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, False


def draw_claude_full(d, y, usage, now, name="Claude · tuần này"):
    """Bố cục đầy đủ: Tuần này to nhất ở trên; hàng dưới Phiên 5 giờ | Fable. Trả về y mới."""
    if not usage:
        f = font("Regular", 26)
        for ln in wrap(d, "Chưa có số liệu mức dùng. Chạy mac/install.sh trên máy Mac đã đăng nhập Claude Code (Phần 5 README).", f, W - 2 * MARGIN, 2):
            d.text((MARGIN, y), ln, font=f, fill=MID)
            y += 36
        return y + 10
    ft, stale = _claude_fetched(usage, now)
    alert = f"SỐ LIỆU CŨ · {ft:%H:%M %d/%m}" if stale else ""
    y = _claude_block(d, y, name, usage.get("seven_day") or {}, now, timedelta(days=7), k=0.8, alert=alert)
    y += 2
    gap = 44
    col_w = (W - 2 * MARGIN - gap) / 2
    _claude_mini(d, MARGIN, y, col_w, "Phiên 5 giờ", usage.get("five_hour") or {}, now)
    _claude_mini(d, MARGIN + col_w + gap, y, col_w, "Fable", _find_fable(usage), now, empty="chưa có số liệu Fable")
    return y + 122


def draw_header_compact(d, y, today, weather):
    """Đầu trang gọn: trái = thứ, ngày, âm lịch · phải = nhiệt độ, mô tả, mưa, AQI. Trả về y mới."""
    d.text((MARGIN, y - 6), THU[today.weekday()], font=font("Bold", 60), fill=BLACK)
    d.text((MARGIN, y + 70), f"{today.day} tháng {today.month}, {today.year}", font=font("SemiBold", 30), fill=DARK)
    try:
        from lunar import solar_to_lunar, year_name
        ld, lm, ly, leap = solar_to_lunar(today.day, today.month, today.year)
        d.text((MARGIN, y + 112), f"Âm lịch {ld}/{lm}{' nhuận' if leap else ''} · năm {year_name(ly)}",
               font=font("Regular", 24), fill=MID)
    except Exception as e:
        print("Không tính được âm lịch:", e)
    right = W - MARGIN
    if weather:
        ft = font("Bold", 72)
        t = f"{round(weather.temp)}°"
        tw = d.textlength(t, font=ft)
        d.text((right - tw, y - 12), t, font=ft, fill=BLACK)
        draw_icon(d, weather.icon, int(right - tw - 62), y + 32, 44)
        l1 = f"{weather.desc} · {round(weather.tmin)}–{round(weather.tmax)}° · mưa {weather.rain}%"
        fw = font("Medium", 26)
        d.text((right - d.textlength(l1, font=fw), y + 72), l1, font=fw, fill=DARK)
        if weather.aqi is not None:
            l2 = f"AQI {weather.aqi} · {aqi_label(weather.aqi)}"
            fa = font("SemiBold", 26)
            aw = d.textlength(l2, font=fa)
            if weather.aqi > 100:   # không khí kém trở lên: chữ trắng nền đen cho dễ thấy
                d.rounded_rectangle([right - aw - 28, y + 106, right, y + 144], radius=19, fill=BLACK)
                d.text((right - aw - 14, y + 125), l2, font=fa, fill=WHITE, anchor="lm")
            else:
                d.text((right - aw, y + 125), l2, font=fa, fill=DARK, anchor="lm")
    else:
        d.text((right - d.textlength("Chưa có thời tiết", font=font("Regular", 24)), y + 72), "Chưa có thời tiết",
               font=font("Regular", 24), fill=MID)
    y += 156
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=BLACK, width=6)
    return y + 24


def _claude_mini(d, x0, y, w, name, v, now, empty=""):
    """Khối nhỏ trong 1 cột: tên + % · thanh mỏng · đặt lại."""
    v = v or {}
    pct = v.get("utilization")
    d.text((x0, y), name, font=font("SemiBold", 30), fill=DARK)
    fp = font("Bold", 44)
    pct_txt = "--" if pct is None else f"{round(pct)}%"
    d.text((x0 + w - d.textlength(pct_txt, font=fp), y - 8), pct_txt, font=fp, fill=BLACK)
    by, bh = y + 50, 22
    d.rounded_rectangle([x0, by, x0 + w, by + bh], radius=bh // 2, outline=BLACK, width=3)
    if pct:
        fw = max(bh, w * min(pct, 100) / 100)
        d.rounded_rectangle([x0, by, x0 + fw, by + bh], radius=bh // 2, fill=BLACK)
    left, reset_at = _remaining(v.get("resets_at"), now)
    if reset_at:
        when = f"{reset_at:%H:%M}" if reset_at.date() == now.date() else f"{THU_NGAN[reset_at.weekday()]} {reset_at:%H:%M}"
        cap = f"đặt lại {when} · {left}"
    else:
        cap = empty if pct is None else ""
    fc = font("Regular", 22)
    d.text((x0, by + bh + 10), fit(d, cap, fc, w), font=fc, fill=MID)


def _claude_foot(now):
    ft, _ = _claude_fetched(CLAUDE_USAGE, now) if CLAUDE_USAGE else (None, False)
    return f" · Claude lúc {ft:%H:%M}" if ft and LAYOUT not in ("lich", "claude") else ""


def load_sample(path: str, today: date) -> tuple[list[Event], list[Task]]:
    """Mẫu JSON: giờ dạng "HH:MM" tính theo hôm nay, "+1 HH:MM" là ngày mai; due là số ngày lệch."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def parse(v):
        off = 0
        if v.startswith("+"):
            o, v = v.split(" ", 1)
            off = int(o)
        hh, mm = map(int, v.split(":"))
        return datetime.combine(today + timedelta(days=off), time(hh, mm), TZ)

    events = []
    for e in data.get("events", []):
        if "day" in e:
            ev = Event(e["title"], None, None, e.get("location", ""))
            ev.__dict__["day"] = today + timedelta(days=e["day"])
        else:
            ev = Event(e["title"], parse(e["start"]), parse(e["end"]), e.get("location", ""))
        events.append(ev)
    tasks = [Task(t["title"], today + timedelta(days=t["due"]) if t.get("due") is not None else None,
                  t.get("list", "")) for t in data.get("tasks", [])]
    return events, tasks


def event_day(e: Event) -> date:
    return e.__dict__.get("day") if e.all_day else e.start.date()


# ---------------------------------------------------------------- vẽ
def fit(d: ImageDraw.ImageDraw, text: str, f, max_w: int) -> str:
    if d.textlength(text, font=f) <= max_w:
        return text
    while text and d.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(d, text, f, max_w, max_lines=2):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit(d, lines[-1] + " …", f, max_w)
    return [fit(d, l, f, max_w) for l in lines]


# ---------------------------------------------------------------- thời tiết
LAT = float(os.environ.get("DASH_LAT", "21.0285"))   # mặc định: Hà Nội — đặt DASH_LAT/DASH_LON cho thành phố của bạn
LON = float(os.environ.get("DASH_LON", "105.8542"))

WMO = {0: ("Trời quang", "sun"), 1: ("Nắng nhẹ", "sun"), 2: ("Có mây", "partly"), 3: ("Nhiều mây", "cloud"),
       45: ("Sương mù", "fog"), 48: ("Sương mù", "fog"), 51: ("Mưa phùn", "rain"), 53: ("Mưa phùn", "rain"),
       55: ("Mưa phùn", "rain"), 61: ("Mưa nhỏ", "rain"), 63: ("Mưa vừa", "rain"), 65: ("Mưa to", "rain"),
       80: ("Mưa rào", "rain"), 81: ("Mưa rào", "rain"), 82: ("Mưa rất to", "rain"),
       95: ("Dông", "storm"), 96: ("Dông, mưa đá", "storm"), 99: ("Dông, mưa đá", "storm")}


@dataclass
class Weather:
    temp: float
    code: int
    tmin: float
    tmax: float
    rain: int            # % khả năng mưa
    aqi: int | None = None

    @property
    def desc(self):
        return WMO.get(self.code, ("", "cloud"))[0]

    @property
    def icon(self):
        return WMO.get(self.code, ("", "cloud"))[1]


def fetch_weather() -> Weather | None:
    import requests
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "timezone": str(TZ), "forecast_days": 1,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        }, timeout=20).json()
        w = Weather(r["current"]["temperature_2m"], r["current"]["weather_code"],
                    r["daily"]["temperature_2m_min"][0], r["daily"]["temperature_2m_max"][0],
                    r["daily"]["precipitation_probability_max"][0] or 0)
    except Exception as e:  # thời tiết lỗi thì vẫn vẽ phần còn lại
        print("Không lấy được thời tiết:", e)
        return None
    try:
        a = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality", params={
            "latitude": LAT, "longitude": LON, "current": "us_aqi"}, timeout=20).json()
        w.aqi = round(a["current"]["us_aqi"])
    except Exception:
        pass
    return w


def aqi_label(v):
    for lim, name in ((50, "Tốt"), (100, "Trung bình"), (150, "Kém"), (200, "Xấu"), (300, "Rất xấu")):
        if v <= lim:
            return name
    return "Nguy hại"


def draw_icon(d, kind, cx, cy, s):
    """Icon thời tiết đơn giản, nét đen, hợp e-ink. s = bán kính cơ sở."""
    import math

    def sun(x, y, r):
        d.ellipse([x - r, y - r, x + r, y + r], outline=BLACK, width=6)
        for i in range(8):
            a = i * math.pi / 4
            d.line([(x + math.cos(a) * r * 1.45, y + math.sin(a) * r * 1.45),
                    (x + math.cos(a) * r * 1.9, y + math.sin(a) * r * 1.9)], fill=BLACK, width=6)

    def cloud(x, y, w, fill=WHITE):
        h = w * 0.55
        parts = [(x - w * .30, y + h * .05, w * .28), (x + w * .02, y - h * .25, w * .34), (x + w * .32, y + h * .08, w * .24)]
        for px, py, r in parts:  # viền
            d.ellipse([px - r - 6, py - r - 6, px + r + 6, py + r + 6], fill=BLACK)
        d.rounded_rectangle([x - w * .58 - 6, y - 6, x + w * .56 + 6, y + h * .45 + 6], radius=int(h * .3), fill=BLACK)
        for px, py, r in parts:
            d.ellipse([px - r, py - r, px + r, py + r], fill=fill)
        d.rounded_rectangle([x - w * .58, y, x + w * .56, y + h * .45], radius=int(h * .3), fill=fill)

    if kind == "sun":
        sun(cx, cy, s * .55)
    elif kind == "partly":
        sun(cx + s * .35, cy - s * .35, s * .42)
        cloud(cx - s * .1, cy + s * .1, s * 1.5)
    elif kind in ("cloud", "fog"):
        cloud(cx, cy - s * .1, s * 1.7)
        if kind == "fog":
            for i in range(3):
                d.line([(cx - s * .8, cy + s * .55 + i * 16), (cx + s * .8, cy + s * .55 + i * 16)], fill=BLACK, width=6)
    else:  # rain / storm
        cloud(cx, cy - s * .3, s * 1.7)
        if kind == "storm":
            d.polygon([(cx, cy + s * .25), (cx - s * .25, cy + s * .75), (cx, cy + s * .7),
                       (cx - s * .15, cy + s * 1.1), (cx + s * .3, cy + s * .55), (cx + s * .05, cy + s * .58)], fill=BLACK)
        else:
            for i in (-1, 0, 1):
                x = cx + i * s * .45
                d.line([(x + 8, cy + s * .35), (x - 8, cy + s * .8)], fill=BLACK, width=7)


# ---------------------------------------------------------------- vẽ
def section_title(d, y, text, right=""):
    f = font("Bold", 28)
    d.text((MARGIN, y), text.upper(), font=f, fill=BLACK)
    if right:
        fr = font("Medium", 26)
        d.text((W - MARGIN - d.textlength(right, font=fr), y + 2), right, font=fr, fill=MID)
    d.line([(MARGIN, y + 44), (W - MARGIN, y + 44)], fill=BLACK, width=3)
    return y + 62


def hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def due_tag(t: Task, today: date):
    if not t.due:
        return ""
    if t.due < today:
        return "Quá hạn"
    if t.due == today:
        return "Hôm nay"
    if t.due == today + timedelta(days=1):
        return "Ngày mai"
    return f"{t.due.day}/{t.due.month}"



# ================================================================ BỐ CỤC "claude": mức dùng + việc gần đây + danh ngôn
# Danh ngôn đổi mỗi ngày. Muốn dùng câu riêng: tạo file quotes.txt trong repo, mỗi dòng "Câu nói | Tác giả".
QUOTES = [
    ("Hành trình vạn dặm bắt đầu từ một bước chân.", "Lão Tử, Đạo Đức Kinh"),
    ("Không có việc gì khó, chỉ sợ lòng không bền. Đào núi và lấp biển, quyết chí ắt làm nên.", "Hồ Chí Minh, 1951"),
    ("Học mà không nghĩ thì mờ mịt, nghĩ mà không học thì nguy hại.", "Khổng Tử, Luận Ngữ"),
    ("Có công mài sắt, có ngày nên kim.", "Tục ngữ Việt Nam"),
    ("Đời sống của pháp luật không phải là logic, mà là kinh nghiệm.", "Oliver Wendell Holmes Jr., The Common Law, 1881"),
    ("Chúng ta là những gì ta lặp đi lặp lại. Vì thế, sự xuất sắc không phải là một hành động, mà là một thói quen.", "Will Durant, diễn giải Aristotle"),
    ("Kiến tha lâu cũng đầy tổ.", "Tục ngữ Việt Nam"),
    ("Ba người cùng đi, ắt có người là thầy ta.", "Khổng Tử, Luận Ngữ"),
    ("Bất công ở bất cứ đâu là mối đe doạ đối với công lý ở mọi nơi.", "Martin Luther King Jr., Thư từ nhà tù Birmingham, 1963"),
    ("Vì lợi ích mười năm thì phải trồng cây, vì lợi ích trăm năm thì phải trồng người.", "Hồ Chí Minh, 1958"),
    ("Nước chảy đá mòn.", "Tục ngữ Việt Nam"),
    ("Công lý không chỉ phải được thực thi, mà còn phải được thấy rõ là đang được thực thi.", "Lord Hewart, R v Sussex Justices, 1924"),
    ("Một cây làm chẳng nên non, ba cây chụm lại nên hòn núi cao.", "Ca dao Việt Nam"),
    ("Biết người biết ta, trăm trận không nguy.", "Tôn Tử, Binh pháp"),
    ("Ngọc không mài không thành đồ quý; người không học không biết đạo lý.", "Lễ Ký, thiên Học Ký"),
    ("Đi một ngày đàng, học một sàng khôn.", "Tục ngữ Việt Nam"),
    ("Thất bại là mẹ thành công.", "Tục ngữ"),
    ("Có chí thì nên.", "Tục ngữ Việt Nam"),
]


def quote_of_day(today: date) -> tuple[str, str]:
    qs = QUOTES
    custom = Path(__file__).parent / "quotes.txt"
    if custom.exists():
        rows = [l.split("|", 1) for l in custom.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        rows = [(a.strip(), b.strip()) for a, b in (r if len(r) == 2 else (r[0], "") for r in rows) if a.strip()]
        qs = rows or qs
    return qs[today.toordinal() % len(qs)]


def _ago(iso: str | None, now: datetime) -> str:
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return ""
    mins = int((now - t).total_seconds() // 60)
    if mins < 1:
        return "vừa xong"
    if mins < 60:
        return f"{mins} phút trước"
    if t.date() == now.date():
        return f"{mins // 60} giờ trước"
    if t.date() == now.date() - timedelta(days=1):
        return f"hôm qua {t:%H:%M}"
    if (now.date() - t.date()).days < 7:
        return f"{THU_NGAN[t.weekday()]} {t:%H:%M}"
    return f"{t.day}/{t.month}"


def _rect(d, x0, y0, x1, y1, fill):
    d.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=fill)


def _label(d, y, text, right=""):
    """Nhãn mục nhỏ, chữ in hoa xám + vạch mảnh. Trả về y mới."""
    f = font("Bold", 22)
    d.text((MARGIN, y), text.upper(), font=f, fill=MID)
    if right:
        fr = font("Regular", 22)
        d.text((W - MARGIN - d.textlength(right, font=fr), y), right, font=fr, fill=MID)
    d.line([(MARGIN, y + 36), (W - MARGIN, y + 36)], fill=PALE, width=2)
    return y + 54


def _draw_quote(d, y_bottom, today):
    """Khung danh ngôn ghim ở đáy (nền xám nhạt, vạch đen bên trái). Trả về y đỉnh khung."""
    text, author = quote_of_day(today)
    x0, x1 = MARGIN, W - MARGIN
    tx, pad = x0 + 40, 30
    fq = font("Medium", 30)
    lines = wrap(d, f"“{text}”", fq, x1 - pad - tx, max_lines=4)
    h = 60 + len(lines) * 43 + (44 if author else 6) + 18
    y0 = y_bottom - h
    d.rounded_rectangle([x0, y0, x1, y_bottom], radius=16, fill=236)
    _rect(d, x0 + 16, y0 + 22, x0 + 22, y_bottom - 22, BLACK)
    d.text((tx, y0 + 22), "DANH NGÔN HÔM NAY", font=font("Bold", 20), fill=MID)
    y = y0 + 58
    for ln in lines:
        d.text((tx, y), ln, font=fq, fill=BLACK)
        y += 43
    if author:
        fa = font("SemiBold", 22)
        a = fit(d, "— " + author, fa, x1 - pad - tx)
        d.text((x1 - pad - d.textlength(a, font=fa), y + 10), a, font=fa, fill=DARK)
    return y0


def _draw_tasks(d, y, limit, now):
    """Danh sách phiên Claude Code gần đây. Mỗi mục: tên việc (đậm, 1 dòng) · thời gian + dự án · 1–2 dòng kết quả."""
    data = CLAUDE_TASKS or {}
    items = data.get("items") or []
    right = ""
    try:
        ft = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00")).astimezone(TZ)
        right = (f"SỐ LIỆU CŨ · {ft:%H:%M %d/%m}" if (now - ft).total_seconds() > 7200 else f"{len(items)} phiên gần nhất")
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    y = _label(d, y, "Việc gần đây · Claude Code", right)
    if not items:
        f = font("Regular", 26)
        msg = ("Chưa có phiên Claude Code nào được gửi lên." if CLAUDE_TASKS else
               "Chưa có dữ liệu. Chạy mac/install.sh trên Mac để gửi các phiên Claude Code lên đây.")
        for ln in wrap(d, msg, f, W - 2 * MARGIN, 3):
            d.text((MARGIN, y), ln, font=f, fill=MID)
            y += 36
        return y
    ft_title, fm, fr = font("SemiBold", 29), font("Medium", 21), font("Regular", 24)
    tx = MARGIN + 24
    tw = W - MARGIN - tx
    TITLE_H, META_H, LINE_H, GAP = 40, 30, 32, 24
    more_h = 34

    def height(n):
        return TITLE_H + META_H + n * LINE_H

    # bố trí trước: ưu tiên hiện nhiều việc; thiếu chỗ thì rút kết quả còn 1 dòng (từ việc cũ nhất trở lên)
    wrapped = [wrap(d, it.get("result") or "", fr, tw, 2) if it.get("result") else [] for it in items]
    avail = limit - y

    def total(k, lines):
        t = sum(height(len(lines[i])) for i in range(k)) + GAP * max(0, k - 1)
        return t + (more_h + GAP if k < len(items) else 0)

    k = len(items)
    while k > 1:
        lines = [list(w) for w in wrapped]
        for i in range(k - 1, -1, -1):
            if total(k, lines) <= avail:
                break
            lines[i] = lines[i][:1]
        if total(k, lines) <= avail:
            break
        k -= 1
    else:
        lines = [list(w) for w in wrapped]
        if total(1, lines) > avail:
            lines[0] = lines[0][:1]
    if k == 1 and total(1, lines) > avail:
        lines[0] = lines[0][:1]

    for i in range(k):
        it = items[i]
        h = height(len(lines[i]))
        _rect(d, MARGIN, y + 6, MARGIN + 6, y + h - 4, BLACK if i == 0 else LIGHT)
        d.text((tx, y), fit(d, it.get("title") or "(không tên)", ft_title, tw), font=ft_title, fill=BLACK)
        meta = " · ".join(x for x in (_ago(it.get("at"), now), it.get("project") or "") if x)
        d.text((tx, y + TITLE_H), fit(d, meta, fm, tw), font=fm, fill=MID)
        yy = y + TITLE_H + META_H
        for ln in lines[i]:
            d.text((tx, yy), ln, font=fr, fill=DARK)
            yy += LINE_H
        y += h
        if i < k - 1:
            d.line([(tx, y + GAP / 2), (W - MARGIN, y + GAP / 2)], fill=PALE, width=2)
        y += GAP
    if k < len(items):
        d.text((tx, y), f"+ {len(items) - k} phiên khác", font=fm, fill=MID)
        y += more_h
    return y


def render_claude_screen(now: datetime) -> Image.Image:
    today = now.date()
    img = Image.new("L", (PW, PH), WHITE)
    d = ScaledDraw(img)

    # ---- đầu trang: dải đen
    hb = 92
    _rect(d, 0, 0, W, hb, BLACK)
    d.text((MARGIN, hb / 2), TITLE.upper(), font=font("Bold", 40), fill=WHITE, anchor="lm")
    dt = f"{THU[today.weekday()]}, {today.day}/{today.month}"
    d.text((W - MARGIN, hb / 2), dt, font=font("SemiBold", 30), fill=WHITE, anchor="rm")

    # ---- mức sử dụng
    y = hb + 28
    ft, stale = _claude_fetched(CLAUDE_USAGE, now) if CLAUDE_USAGE else (None, False)
    y = _label(d, y, "Mức sử dụng", f"số liệu lúc {ft:%H:%M}" if ft and not stale else "")
    y = draw_claude_full(d, y + 4, CLAUDE_USAGE, now, name="Tuần này")
    y += 16

    # ---- chân trang + danh ngôn (ghim đáy), việc gần đây lấp phần giữa
    footer_y = H - 50
    q_top = _draw_quote(d, footer_y - 20, today)
    _draw_tasks(d, y, q_top - 24, now)

    d.line([(MARGIN, footer_y), (W - MARGIN, footer_y)], fill=LIGHT, width=2)
    d.text((MARGIN, footer_y + 12), f"Cập nhật {now:%H:%M %d/%m}", font=font("Regular", 22), fill=MID)
    return img


def render(events: list[Event], tasks: list[Task], now: datetime, weather: Weather | None = None) -> Image.Image:
    if LAYOUT == "claude":
        return render_claude_screen(now)
    from lunar import solar_to_lunar, year_name

    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    img = Image.new("L", (PW, PH), WHITE)
    d = ScaledDraw(img)
    f_sub = font("Regular", 28)

    if LAYOUT not in ("lich", "claude"):
        # ============ BỐ CỤC ĐẦY ĐỦ: đầu trang gọn (ngày + thời tiết + AQI) → Claude to → việc → lịch
        y = draw_header_compact(d, 36, today, weather)
        y = draw_claude_full(d, y, CLAUDE_USAGE, now)
        d.line([(MARGIN, y - 14), (W - MARGIN, y - 14)], fill=PALE, width=2)
        y += 10
    elif LAYOUT == "claude":
        # ============ BỐ CỤC CLAUDE: không có đầu trang, Claude to ở trên cùng
        y = draw_claude_big(d, 40, CLAUDE_USAGE, now)
        d.line([(MARGIN, y - 20), (W - MARGIN, y - 20)], fill=PALE, width=2)
        y += 14
    else:
        # ============ HEADER: ngày + âm lịch | thời tiết
        y = 56
        d.text((MARGIN, y), THU[today.weekday()], font=font("Bold", 88), fill=BLACK)
        d.text((MARGIN, y + 112), f"{today.day} tháng {today.month}, {today.year}", font=font("SemiBold", 38), fill=DARK)
        ld, lm, ly, leap = solar_to_lunar(today.day, today.month, today.year)
        lunar_txt = f"Âm lịch {ld}/{lm}{' nhuận' if leap else ''} · năm {year_name(ly)}"
        d.text((MARGIN, y + 164), lunar_txt, font=f_sub, fill=MID)

        if weather:
            right = W - MARGIN
            ft = font("Bold", 96)
            t = f"{round(weather.temp)}°"
            tw = d.textlength(t, font=ft)
            d.text((right - tw, y - 6), t, font=ft, fill=BLACK)
            draw_icon(d, weather.icon, int(right - tw - 85), y + 52, 62)
            l1 = f"{weather.desc} · {round(weather.tmin)}–{round(weather.tmax)}°"
            l2 = f"Mưa {weather.rain}%" + (f" · AQI {weather.aqi} {aqi_label(weather.aqi)}" if weather.aqi is not None else "")
            fw = font("Medium", 28)
            d.text((right - d.textlength(l1, font=fw), y + 124), l1, font=fw, fill=DARK)
            d.text((right - d.textlength(l2, font=f_sub), y + 164), l2, font=f_sub, fill=MID)
        y += 222
        d.line([(MARGIN, y), (W - MARGIN, y)], fill=BLACK, width=6)
        y += 32

        # ============ MỨC DÙNG CLAUDE (nếu Mac mini có gửi số liệu)
        if CLAUDE_USAGE:
            y = draw_claude(d, y, CLAUDE_USAGE, now)
            d.line([(MARGIN, y), (W - MARGIN, y)], fill=PALE, width=2)
            y += 28

    ev_today = sorted([e for e in events if event_day(e) == today], key=lambda e: (not e.all_day, e.start or now))
    ev_tom = sorted([e for e in events if event_day(e) == tomorrow], key=lambda e: (not e.all_day, e.start or now))
    timed = [e for e in ev_today if not e.all_day]
    nxt = next((e for e in timed if e.end > now), None)

    # ============ THẺ "TIẾP THEO" (nền đen, nổi bật trên e-ink)
    if nxt and LAYOUT in ("lich", "claude"):
        live = nxt.start <= now
        has_loc = bool(nxt.location)
        ch = 150 if has_loc else 118
        d.rounded_rectangle([MARGIN, y, W - MARGIN, y + ch], radius=18, fill=BLACK)
        label = ("ĐANG DIỄN RA" if live else "TIẾP THEO") + f" · {hm(nxt.start)}–{hm(nxt.end)}"
        d.text((MARGIN + 32, y + 18), label, font=font("SemiBold", 26), fill=PALE)
        d.text((MARGIN + 32, y + 52), fit(d, nxt.title, font("Bold", 44), W - 2 * MARGIN - 64),
               font=font("Bold", 44), fill=WHITE)
        if has_loc:
            d.text((MARGIN + 32, y + 106), fit(d, "@ " + nxt.location, f_sub, W - 2 * MARGIN - 64), font=f_sub, fill=PALE)
        y += ch + 34

    # ---- tính trước khối dưới cùng (lịch hôm nay + ngày mai) để todo lấp phần giữa
    footer_y = H - 64
    compact = LAYOUT not in ("lich", "claude")   # bố cục đầy đủ: hàng việc thấp hơn để hiện được nhiều việc
    task_h = 52 if compact else 66
    min_todo = 62 + (4 if compact else 3) * (task_h + 6) if tasks else 140   # luôn chừa chỗ cho ít nhất 3–4 việc
    cal_max, tom_max = 6, 3

    def _bottom_h(cm, tm):
        cr = min(len(ev_today), cm) or 1
        tr = min(len(ev_tom), tm) or 1
        return (62 + 46 * cr + (36 if len(ev_today) > cm else 0) + 26) + (62 + 44 * tr) + 16

    # thiếu chỗ cho todo → bớt dòng lịch (ngày mai trước, rồi hôm nay)
    while footer_y - _bottom_h(cal_max, tom_max) - y < min_todo and (tom_max > 1 or cal_max > 1):
        if tom_max > 1:
            tom_max -= 1
        else:
            cal_max -= 1
    bottom_y = footer_y - _bottom_h(cal_max, tom_max)

    # ============ VIỆC CẦN LÀM (khu vực chính)
    tasks_open = sorted(tasks, key=lambda t: (t.due is None, t.due or date.max, t.title.lower()))
    overdue = sum(1 for t in tasks_open if t.due and t.due < today)
    due_today = sum(1 for t in tasks_open if t.due == today)
    right = f"{len(tasks_open)} việc" + (f" · {overdue} quá hạn" if overdue else "") + \
        (f" · {due_today} hôm nay" if due_today else "")
    y = section_title(d, y, "Việc cần làm", right if tasks_open else "")
    f_task, box = font("Medium", 32), 36   # mỗi việc đúng 1 dòng, dài thì cắt "…"
    if not tasks_open:
        d.text((MARGIN, y + 6), "Không còn việc nào. Tuyệt vời!", font=font("Regular", 36), fill=MID)
        y += 70
    for i, t in enumerate(tasks_open):
        tag = due_tag(t, today)
        f_tag = font("SemiBold", 22)
        tag_w = int(d.textlength(tag, font=f_tag)) + 28 if tag else 0
        text_w = W - 2 * MARGIN - box - 24 - (tag_w + 20 if tag else 0)
        line = fit(d, t.title, f_task, text_w)
        limit = bottom_y - (16 if i == len(tasks_open) - 1 else 44)  # chừa chỗ cho "+ N việc nữa"
        row_h = task_h
        if y + row_h > limit:
            d.text((MARGIN, y + 4), f"+ {len(tasks_open) - i} việc nữa", font=f_sub, fill=MID)
            y += 44
            break
        d.rounded_rectangle([MARGIN, y + 4, MARGIN + box, y + 4 + box], radius=8, outline=BLACK, width=4)
        d.text((MARGIN + box + 24, y + 22), line, font=f_task, fill=BLACK, anchor="lm")
        if tag:
            x1, x0 = W - MARGIN, W - MARGIN - tag_w
            if tag in ("Quá hạn", "Hôm nay"):
                d.rounded_rectangle([x0, y + 4, x1, y + 40], radius=18, fill=BLACK)
                d.text(((x0 + x1) / 2, y + 22), tag, font=f_tag, fill=WHITE, anchor="mm")
            else:
                d.rounded_rectangle([x0, y + 4, x1, y + 40], radius=18, outline=MID, width=2)
                d.text(((x0 + x1) / 2, y + 22), tag, font=f_tag, fill=DARK, anchor="mm")
        y += row_h
        d.line([(MARGIN + box + 28, y - 8), (W - MARGIN, y - 8)], fill=PALE, width=2)
        y += 6

    # ============ LỊCH HÔM NAY (gọn, ghim phía dưới)
    y = bottom_y
    y = section_title(d, y, "Lịch hôm nay", f"{len(ev_today)} sự kiện" if ev_today else "")
    time_w = 250
    f_ev, f_evb = font("Regular", 32), font("SemiBold", 32)
    if not ev_today:
        d.text((MARGIN, y), "Không có sự kiện nào.", font=f_ev, fill=MID)
        y += 46
    shown = list(ev_today)
    while len(shown) > cal_max:   # thiếu chỗ: bỏ sự kiện đã qua trước, rồi tới cuối danh sách
        past_i = next((k for k, x in enumerate(shown) if not x.all_day and x.end <= now), None)
        shown.pop(past_i if past_i is not None else -1)
    for i, e in enumerate(shown):
        past = (not e.all_day) and e.end <= now
        is_next = e is nxt
        col = LIGHT if past else BLACK
        tf = f_evb if is_next else f_ev
        when = "Cả ngày" if e.all_day else f"{hm(e.start)}–{hm(e.end)}"
        d.text((MARGIN, y), when, font=font("Medium", 28), fill=LIGHT if past else DARK)
        d.text((MARGIN + time_w, y - 2), fit(d, e.title, tf, W - 2 * MARGIN - time_w), font=tf, fill=col)
        if past:  # gạch ngang sự kiện đã qua
            tw = min(d.textlength(fit(d, e.title, tf, W - 2 * MARGIN - time_w), font=tf), W - 2 * MARGIN - time_w)
            d.line([(MARGIN + time_w, y + 20), (MARGIN + time_w + tw, y + 20)], fill=LIGHT, width=2)
        y += 46
    if len(ev_today) > len(shown):
        d.text((MARGIN, y), f"+ {len(ev_today) - len(shown)} sự kiện khác", font=f_sub, fill=MID)
        y += 36
    y += 26

    # ============ NGÀY MAI
    y = section_title(d, y, "Ngày mai · " + THU[tomorrow.weekday()],
                      f"{len(ev_tom)} sự kiện" if len(ev_tom) > tom_max else "")
    if not ev_tom:
        d.text((MARGIN, y), "Chưa có lịch.", font=f_ev, fill=MID)
    for e in ev_tom[:tom_max]:
        d.text((MARGIN, y), "Cả ngày" if e.all_day else hm(e.start), font=font("Medium", 28), fill=DARK)
        d.text((MARGIN + time_w, y - 2), fit(d, e.title, f_ev, W - 2 * MARGIN - time_w), font=f_ev, fill=DARK)
        y += 44

    # ============ FOOTER
    d.line([(MARGIN, footer_y), (W - MARGIN, footer_y)], fill=LIGHT, width=2)
    d.text((MARGIN, footer_y + 16), (f"{THU[today.weekday()]} {today.day}/{today.month} · " if LAYOUT == "claude" else "") + f"Cập nhật {now.strftime('%H:%M %d/%m')}" + _claude_foot(now), font=font("Regular", 24), fill=MID)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site/dashboard.png")
    ap.add_argument("--sample", help="file JSON dữ liệu mẫu (không gọi Google)")
    ap.add_argument("--layout", help="daydu | lich | claude (mặc định lấy từ DASH_LAYOUT)")
    ap.add_argument("--now", help="giả lập thời điểm, vd 2026-11-03T10:30")
    args = ap.parse_args()

    global LAYOUT
    if args.layout:
        LAYOUT = args.layout.strip().lower()
    now = datetime.fromisoformat(args.now).replace(tzinfo=TZ) if args.now else datetime.now(TZ)
    if args.sample:
        events, tasks = load_sample(args.sample, now.date())
        sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
        w = sample.get("weather")
        weather = Weather(**w) if w else None
        global CLAUDE_USAGE, CLAUDE_TASKS
        CLAUDE_USAGE = sample.get("claude")
        CLAUDE_TASKS = sample.get("claude_tasks")
    else:
        if os.environ.get("DATA_URL"):
            events, tasks = fetch_appscript(os.environ["DATA_URL"], now.date())
        else:
            events, tasks = fetch_google(now.date())
        weather = fetch_weather()
    img = render(events, tasks, now, weather)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    print(f"Đã lưu {out} ({len(events)} sự kiện, {len(tasks)} việc, thời tiết: {'có' if weather else 'không'})")


if __name__ == "__main__":
    main()
