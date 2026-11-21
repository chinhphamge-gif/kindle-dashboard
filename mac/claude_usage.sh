#!/bin/bash
# Lấy mức dùng Claude (phiên 5 giờ + giới hạn tuần + Fable) và các phiên Claude Code gần đây,
# rồi gửi lên Apps Script để dashboard Kindle hiển thị.
# Chạy trên Mac mini (đã cài và đăng nhập Claude Code), launchd gọi 10 phút/lần.
# Lưu ý: endpoint này là endpoint nội bộ Claude Code dùng, chưa được Anthropic công bố — có thể đổi bất cứ lúc nào.

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.npm-global/bin:/usr/bin:/bin"
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/claude_usage.log"
URL_FILE="$HOME/.kindle-dashboard-url"   # chứa DATA_URL (link Web app + ?token=...), chmod 600
STAMP="$DIR/.last_refresh"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; }

DATA_URL="$(cat "$URL_FILE" 2>/dev/null)"
[ -n "$DATA_URL" ] || { log "Thiếu file $URL_FILE"; exit 1; }

get_token() {
  local creds
  creds="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null)"
  [ -n "$creds" ] || creds="$(cat "$HOME/.claude/.credentials.json" 2>/dev/null)"
  [ -n "$creds" ] || return 1
  osascript -l JavaScript -e 'function run(a){return JSON.parse(a[0]).claudeAiOauth.accessToken}' "$creds" 2>/dev/null
}

fetch_usage() {
  curl -s -m 20 -w '\n%{http_code}' \
    -H "Authorization: Bearer $1" \
    -H "anthropic-beta: oauth-2025-04-20" \
    -H "Content-Type: application/json" \
    "https://api.anthropic.com/api/oauth/usage"
}

# Các phiên Claude Code gần đây (tên việc + tóm tắt kết quả), xem recent_tasks.js
TASKS="$(osascript -l JavaScript "$DIR/recent_tasks.js" 2>>"$LOG")"
case "$TASKS" in \[*) ;; *) log "Không đọc được phiên Claude Code"; TASKS='[]' ;; esac

CODE=""; BODY=""
TOKEN="$(get_token)" || log "Không đọc được token Claude Code (đã đăng nhập Claude Code chưa?)"
if [ -n "$TOKEN" ]; then
  RESP="$(fetch_usage "$TOKEN")"
  CODE="${RESP##*$'\n'}"; BODY="${RESP%$'\n'*}"
fi

# Token hết hạn → chạy Claude Code 1 lệnh rất ngắn để nó tự làm mới token (tối đa 1 lần/giờ)
if [ -n "$TOKEN" ] && [ "$CODE" = "401" ]; then
  if [ ! -f "$STAMP" ] || [ $(( $(date +%s) - $(stat -f %m "$STAMP") )) -gt 3600 ]; then
    touch "$STAMP"
    log "Token hết hạn, làm mới bằng claude -p"
    claude -p "ok" --max-turns 1 >/dev/null 2>&1
    TOKEN="$(get_token)"
    RESP="$(fetch_usage "$TOKEN")"
    CODE="${RESP##*$'\n'}"; BODY="${RESP%$'\n'*}"
  fi
fi

if [ "$CODE" != "200" ]; then
  log "Lấy mức dùng thất bại (HTTP ${CODE:-không gọi được}) → chỉ gửi danh sách việc"
  BODY='{}'
fi

# gộp mức dùng + danh sách việc thành 1 JSON (Apps Script giữ nguyên mức dùng cũ nếu lần này không lấy được)
PAYLOAD="$(osascript -l JavaScript -e 'function run(a){var b={};try{b=JSON.parse(a[0])}catch(e){}b.kindle_tasks=JSON.parse(a[1]);return JSON.stringify(b)}' "$BODY" "$TASKS" 2>>"$LOG")"
[ -n "$PAYLOAD" ] || { log "Không gộp được dữ liệu"; exit 1; }

POST="$(curl -s -L -m 30 -H 'Content-Type: application/json' --data "$PAYLOAD" "$DATA_URL")"
NT="$(printf '%s' "$TASKS" | grep -o '"title"' | wc -l | tr -d ' ')"
case "$POST" in
  *'"ok":true'*) log "OK (mức dùng: HTTP $CODE, $NT việc) $(echo "$BODY" | tr -d '\n' | cut -c1-120)" ;;
  *) log "Gửi lên Apps Script lỗi: $(echo "$POST" | cut -c1-160)" ;;
esac
