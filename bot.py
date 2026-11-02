import json, os, re, time, urllib.request

API_URL = "https://information-b.vercel.app/api/memo"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = "state.json"
UA = {"User-Agent": "shukkin-bot/1.0"}
DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2})$")
TIME_RE = re.compile(r"^(\d{1,2}時半?)〜$")
CUP_RE = re.compile(r"[A-Z]")
MARKS = "★○☆◎●"
FULL = "🈵"


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def post(text):
    chunk = ""
    for line in text.split("\n") + [None]:
        if line is None or len(chunk) + len(line) > 1900:
            if chunk.strip():
                body = json.dumps({"content": chunk}).encode("utf-8")
                headers = dict(UA, **{"Content-Type": "application/json"})
                req = urllib.request.Request(WEBHOOK, data=body, headers=headers, method="POST")
                urllib.request.urlopen(req, timeout=20)
            chunk = ""
        if line is not None:
            chunk += line + "\n"


def parse(content):
    date, start, members = None, "", {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if date is None:
            m = DATE_RE.match(line)
            if m:
                date = m.group(1)
            continue
        if "待ち時間" in line or "ご予約" in line:
            break
        m = TIME_RE.match(line)
        if m:
            start = m.group(1)
            continue
        tokens = line.split()
        name = tokens[0].lstrip(MARKS)
        mark = tokens[0][: len(tokens[0]) - len(name)]
        if len(tokens) >= 3 and tokens[1].isdigit() and name:
            rest = tokens[2:]
            end = next((t for t in rest if t.startswith("〜")), "")
            spec = [tokens[1] + "cm"] + [t for t in rest if CUP_RE.fullmatch(t)]
            tags = [t for t in rest if not t.startswith("〜") and not CUP_RE.fullmatch(t)]
            members[name] = {
                "start": start,
                "end": end.lstrip("〜"),
                "spec": " / ".join(spec),
                "mark": mark,
                "tags": " ".join(tags),
            }
    return date, members


def fmt(name, m):
    s = f"・{m.get('mark', '')}{name}（{m['spec']}）{m['start']}〜{m['end']}"
    if m.get("tags"):
        s += " " + m["tags"]
    return s


def main():
    data = get_json(API_URL)
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    if data.get("updated_at") == state.get("updated_at"):
        return
    date, members = parse(data.get("content", ""))
    if date is None or not members:
        return
    old = state.get("members", {})
    msgs = []
    if date != state.get("date"):
        msgs.append(f"🟢 {date} 本日の出勤メンバー（{len(members)}名）")
        msgs += [fmt(n, m) for n, m in members.items()]
    else:
        for n in members:
            if n not in old:
                msgs.append("🚨 新規出勤エントリー\n" + fmt(n, members[n]) + "\n")
                continue
            was = FULL in old[n].get("tags", "")
            now = FULL in members[n].get("tags", "")
            if now and not was:
                msgs.append("🈵 満枠になりました\n" + fmt(n, members[n]) + "\n")
            elif was and not now:
                msgs.append("🈳 満枠が解除されました\n" + fmt(n, members[n]) + "\n")
        for n in old:
            if n not in members:
                msgs.append("⚠️ 出勤リストから外れました\n" + fmt(n, old[n]) + "\n")
    if msgs:
        post("\n".join(msgs))
    state = {"updated_at": data.get("updated_at"), "date": date, "members": members}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


for i in range(5):
    try:
        main()
    except Exception as e:
        print("error:", e)
    if i < 4:
        time.sleep(60)
