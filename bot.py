import json, os, re, time, urllib.request
from datetime import datetime, timezone, timedelta

API_BASE = "https://information-b.vercel.app/api/memo"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
ROSTER_WEBHOOK = os.environ.get("ROSTER_WEBHOOK_URL", "")
STATE_FILE = "state.json"
ROSTER_FILE = "roster.json"
UA = {"User-Agent": "shukkin-bot/1.0", "Cache-Control": "no-cache"}
DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2})$")
TIME_RE = re.compile(r"^(\d{1,2}時半?)〜$")
CUP_RE = re.compile(r"[A-Z]")
MARKS = "★○☆◎●"
FULL = "🈵"
JST = timezone(timedelta(hours=9))
RANK = {"★": 0, "☆": 1, "○": 2}
NEW_RE = re.compile(r"^(\d{1,2}時半?)〜(ラスト|\d{1,2}時半?)[、,]\s*(.+)$")


def get_json():
    url = API_BASE + "?v=" + str(int(time.time() * 1000))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def send(hook, text):
    chunk = ""
    for line in text.split("\n") + [None]:
        if line is None or len(chunk) + len(line) > 1900:
            if chunk.strip():
                body = json.dumps({"content": chunk}).encode("utf-8")
                headers = dict(UA, **{"Content-Type": "application/json"})
                req = urllib.request.Request(hook, data=body, headers=headers, method="POST")
                urllib.request.urlopen(req, timeout=20)
            chunk = ""
        if line is not None:
            chunk += line + "\n"


def hhmm(t):
    m = re.match(r"(\d{1,2})時(半?)", t or "")
    if not m:
        return t or ""
    return f"{int(m.group(1))}:{'30' if m.group(2) else '00'}"


def spec_of(tokens):
    nums = [t for t in tokens if t.isdigit()]
    cups = [t for t in tokens if CUP_RE.fullmatch(t)]
    parts = []
    if nums:
        parts.append(nums[0] + "cm")
    parts += cups
    return " / ".join(parts)


def parse_newcomers(content):
    news = {}
    grab = False
    for raw in content.splitlines():
        line = raw.strip()
        if "新人情報" in line:
            grab = True
            continue
        if grab:
            if DATE_RE.match(line):
                break
            m = NEW_RE.match(line)
            if m:
                start = hhmm(m.group(1))
                end = "ラスト" if m.group(2) == "ラスト" else hhmm(m.group(2))
                rest = m.group(3).split()
                name = rest[0]
                sp = spec_of(rest[1:])
                news[name] = {"spec": sp, "hours": f"{start} 〜 {end}"}
    return news


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


def hours(m):
    s, e = hhmm(m["start"]), hhmm(m["end"])
    if not e:
        h = re.match(r"\d+", m["start"] or "")
        if h and int(h.group()) >= 18:
            e = "ラスト"
    return f"{s} 〜 {e}".rstrip()


def spec(m):
    s = m["spec"]
    if m.get("tags"):
        s += " / " + " / ".join(m["tags"].split())
    return s


def news_msg(emoji, title, name):
    return f"{emoji} **【速報】{title}**\nキャスト名：{name}\n"


def date_key(d):
    try:
        mm, dd = d.split("/")
        return (int(mm), int(dd))
    except Exception:
        return (0, 0)


def post_roster(roster):
    def key(item):
        n, r = item
        mm, dd = date_key(r.get("last", ""))
        return (RANK.get(r.get("mark", "")[:1], 3), -mm, -dd, n)
    lines = [f"📋 **キャスト名簿**（全{len(roster)}名）\n"]
    for n, r in sorted(roster.items(), key=key):
        mark = r.get("mark", "")
        lines.append(f"{mark}{n}（{r.get('spec', '')}）初:{r['first']}　最終:{r['last']}")
    send(ROSTER_WEBHOOK, "\n".join(lines))


def recalc(r):
    days = sorted(r.get("dates", []), key=date_key)
    if days:
        r["first"] = days[0]
        r["last"] = days[-1]
    r["days"] = len(days)


def update_roster(today, members, removed):
    try:
        with open(ROSTER_FILE, encoding="utf-8") as f:
            roster = json.load(f)
    except FileNotFoundError:
        roster = {}
    changed = False
    for n, m in members.items():
        if n not in roster:
            roster[n] = {"first": today, "last": today, "days": 1,
                         "dates": [today], "mark": m.get("mark", ""), "spec": m["spec"]}
            changed = True
        else:
            r = roster[n]
            r.setdefault("dates", [r.get("first", today), r.get("last", today)])
            if r.get("mark") != m.get("mark", "") or r.get("spec") != m["spec"]:
                changed = True
            r["mark"], r["spec"] = m.get("mark", ""), m["spec"]
            if today not in r["dates"]:
                r["dates"].append(today)
                recalc(r)
                changed = True
    for n in removed:
        if n in roster:
            r = roster[n]
            r.setdefault("dates", [])
            if today in r["dates"]:
                r["dates"].remove(today)
                recalc(r)
                changed = True
    with open(ROSTER_FILE, "w", encoding="utf-8") as f:
        json.dump(roster, f, ensure_ascii=False, indent=2)
    if changed and ROSTER_WEBHOOK:
        post_roster(roster)


def main():
    data = get_json()
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    if data.get("updated_at") == state.get("updated_at"):
        return
    content = data.get("content", "")
    date, members = parse(content)
    newcomers = parse_newcomers(content)
    if date is None or not members:
        return
    today = datetime.now(JST).strftime("%-m/%-d")
    old = state.get("members", {})
    removed = [n for n in old if n not in members]
    update_roster(today, members, removed)
    old_new = state.get("newcomers", {})
    msgs = []
    if date != state.get("date"):
        msgs.append(f"🟢 **【速報】本日の出勤メンバー**（{date}・{len(members)}名）\n")
        for n, m in members.items():
            msgs.append(f"{m.get('mark', '')}{n}（{spec(m)}）{hours(m)}")
        if newcomers:
            msgs.append("")
            for n, nm in newcomers.items():
                msgs.append(f"🆕 {n}（{nm['spec']}）{nm['hours']}")
    else:
        for n in members:
            if n not in old:
                msgs.append(news_msg("🚨", "出勤検知", n))
                continue
            was = FULL in old[n].get("tags", "")
            now = FULL in members[n].get("tags", "")
            if now and not was:
                msgs.append(news_msg("🈵", "満枠", n))
            elif was and not now:
                msgs.append(news_msg("🈳", "満枠解除", n))
        for n in removed:
            msgs.append(news_msg("⚠️", "出勤取り消し", n))
        for n, nm in newcomers.items():
            if n not in old_new:
                msgs.append(f"🆕 **【速報】新人情報**\n{n}（{nm['spec']}）{nm['hours']}\n")
    if msgs:
        send(WEBHOOK, "\n".join(msgs))
    state = {"updated_at": data.get("updated_at"), "date": date,
             "members": members, "newcomers": newcomers}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


for i in range(5):
    try:
        main()
    except Exception as e:
        print("error:", e)
    if i < 4:
        time.sleep(60)
