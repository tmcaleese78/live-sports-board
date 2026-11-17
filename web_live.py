import os
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Flask, jsonify, redirect, render_template, request

app = Flask(__name__)
HOST = "site." + "api." + "espn." + "com"
_CACHE = {"ts": 0.0, "data": None}
_ROSTER_CACHE = {}

@app.before_request
def upgrade_to_https():
    if request.headers.get("X-Forwarded-Proto") == "http":
        return redirect(f"https://{request.host}{request.full_path.rstrip('?')}", code=301)

def fetch_json(url, timeout=6):
    try:
        return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout).json()
    except Exception:
        return {}

def clean_hex(val, fallback):
    s = str(val or "").strip().lstrip("#")
    return f"#{s}" if len(s) == 6 else fallback

def get_roster(sport_path, tid):
    key = f"{sport_path}:{tid}"
    if key in _ROSTER_CACHE:
        return _ROSTER_CACHE[key]
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/teams/{tid}/roster", timeout=5)
    out = list()
    for grp in data.get("athletes", list()):
        if isinstance(grp, dict) and "items" in grp:
            items = grp.get("items", list())
        else:
            items = [grp]
        for a in items:
            if isinstance(a, dict) and a.get("displayName"):
                out.append({"name": a["displayName"], "pos": a.get("position", {}).get("abbreviation", "")})
    if out:
        _ROSTER_CACHE[key] = out
    return out

def parse_scoreboard(sport_path, lg_code):
    sb = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard", timeout=6)
    games, players = list(), list()
    seen_p = set()
    box_tasks, roster_tasks = list(), list()
    for ev in sb.get("events", list()):
        eid = ev.get("id", "")
        comp = next(iter(ev.get("competitions", list())), {})
        comps = comp.get("competitors", list())
        if len(comps) < 2:
            continue
        first_c = next(iter(comps), {})
        last_c = next(reversed(comps), {})
        home = next((c for c in comps if c.get("homeAway") == "home"), first_c)
        away = next((c for c in comps if c.get("homeAway") != "home"), last_c)
        st_obj = ev.get("status", {}).get("type", {})
        state = st_obj.get("state", "pre")
        status = "Final" if state == "post" else st_obj.get("shortDetail", "Scheduled")
        a_tm, h_tm = away.get("team", {}), home.get("team", {})
        a_name = a_tm.get("abbreviation") or a_tm.get("shortDisplayName", "") if lg_code != "cfb" else a_tm.get("shortDisplayName", a_tm.get("displayName", ""))
        h_name = h_tm.get("abbreviation") or h_tm.get("shortDisplayName", "") if lg_code != "cfb" else h_tm.get("shortDisplayName", h_tm.get("displayName", ""))
        a_full = a_tm.get("displayName", a_name)
        h_full = h_tm.get("displayName", h_name)
        a_rec = next((r.get("summary", "") for r in away.get("records", list()) if r.get("type") == "total"), "")
        h_rec = next((r.get("summary", "") for r in home.get("records", list()) if r.get("type") == "total"), "")
        bcasts = [n for b in comp.get("broadcasts", list()) for n in b.get("names", list()) if n]
        tv = next(iter(bcasts), "")
        odds_obj = next(iter(comp.get("odds", list())), {})
        odds_txt = str(odds_obj.get("details", "") or "")
        ou = odds_obj.get("overUnder", "")
        if ou:
            odds_txt = f"{odds_txt} | O/U {ou}".strip(" |")
        poss_id = str(comp.get("situation", {}).get("possession", ""))
        bg0 = clean_hex(a_tm.get("color"), "#1e293b")
        bg1 = clean_hex(h_tm.get("color"), "#0f172a")
        lg0 = a_tm.get("logo") or next((x.get("href", "") for x in a_tm.get("logos", list())), "")
        lg1 = h_tm.get("logo") or next((x.get("href", "") for x in h_tm.get("logos", list())), "")
        sort_rank = 0 if state == "in" else (1 if state == "pre" else 2)
        games.append({
            "rank": sort_rank, "date": str(ev.get("date", "")),
            "id": eid, "league": lg_code.upper(), "state": state, "status": status,
            "tv": tv, "odds": odds_txt,
            "away": a_name, "away_full": a_full, "arec": a_rec, "ascore": str(away.get("score", "0")), "aposs": (poss_id == str(away.get("id", "")) and state == "in"),
            "home": h_name, "home_full": h_full, "hrec": h_rec, "hscore": str(home.get("score", "0")), "hposs": (poss_id == str(home.get("id", "")) and state == "in"),
            "bg0": bg0, "fg0": "#ffffff", "lg0": lg0,
            "bg1": bg1, "fg1": "#ffffff", "lg1": lg1
        })
        if lg_code not in ("nfl", "nba") or not eid:
            continue
        team_meta = {}
        for c in comps:
            t = c.get("team", {})
            ab = t.get("abbreviation", "")
            meta = {"bg": clean_hex(t.get("color"), "#1e293b"), "logo": t.get("logo") or next((x.get("href", "") for x in t.get("logos", list())), ""), "tid": t.get("id", "")}
            team_meta[ab] = meta
            roster_tasks.append({"ab": ab, "meta": meta, "status": status, "state": state})
        if state != "pre":
            box_tasks.append({"eid": eid, "team_meta": team_meta, "status": status, "state": state})
        if lg_code == "nba" and not roster_tasks:
        tms = fetch_json(f"https://{HOST}/apis/site/v2/sports/basketball/nba/teams", timeout=5)
        for sp_t in tms.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
            t = sp_t.get("team", {})
            ab = t.get("abbreviation", "")
            meta = {"bg": clean_hex(t.get("color"), "#1e293b"), "logo": t.get("logo") or next((x.get("href", "") for x in t.get("logos", [])), ""), "tid": t.get("id", "")}
            roster_tasks.append({"ab": ab, "meta": meta, "status": "Off Day", "state": "pre"})

    with ThreadPoolExecutor(max_workers=12) as pool:
        boxes = list(pool.map(lambda t: {"box": fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/summary?event={t['eid']}", timeout=6), "meta": t["team_meta"], "status": t["status"], "state": t["state"]}, box_tasks))
        rosters = list(pool.map(lambda r: {"ab": r["ab"], "meta": r["meta"], "rlist": get_roster(sport_path, r["meta"]["tid"]), "status": r["status"], "state": r["state"]}, roster_tasks))
    for item in boxes:
        box, team_meta, status, state = item["box"], item["meta"], item["status"], item["state"]
        pmap = {}
        for tg in box.get("boxscore", {}).get("players", list()):
            ab = tg.get("team", {}).get("abbreviation", "")
            for cat in tg.get("statistics", list()):
                cname = cat.get("name", "").lower()
                im = {str(x).upper(): i for i, x in enumerate(cat.get("labels", list()))}
                for ath in cat.get("athletes", list()):
                    a = ath.get("athlete", {})
                    nm = a.get("displayName", "")
                    if not nm:
                        continue
                    rec = pmap.setdefault((ab, nm), {"pos": a.get("position", {}).get("abbreviation", ""), "stats": {}})
                    st = ath.get("stats", list())
                    gv = lambda k: float(st[im[k]]) if (k in im and im[k] < len(st) and str(st[im[k]]).replace(".","",1).isdigit()) else 0.0
                    if lg_code == "nfl":
                        if cname == "passing":
                            ca = str(st[im["C/ATT"]]).split("/") if ("C/ATT" in im and im["C/ATT"] < len(st)) else ["0"]
                            rec["stats"]["COMP"] = float(next(iter(ca), 0))
                            rec["stats"]["PASS YDS"] = gv("YDS")
                            rec["stats"]["PASS TD"] = gv("TD")
                        elif cname == "rushing":
                            rec["stats"]["CAR"] = gv("CAR")
                            rec["stats"]["RUSH YDS"] = gv("YDS")
                            rec["stats"]["RUSH TD"] = gv("TD")
                        elif cname == "receiving":
                            rec["stats"]["REC"] = gv("REC")
                            rec["stats"]["TGTS"] = gv("TGTS")
                            rec["stats"]["REC YDS"] = gv("YDS")
                            rec["stats"]["REC TD"] = gv("TD")
                    else:
                        pts, reb, ast = gv("PTS"), gv("REB"), gv("AST")
                        p3 = str(st[im["3PT"]]).split("-") if ("3PT" in im and im["3PT"] < len(st)) else ["0"]
                        rec["stats"].update({"PTS": pts, "REB": reb, "AST": ast, "3PM": float(next(iter(p3), 0)),
                                             "STL": gv("STL"), "BLK": gv("BLK"), "PRA": pts + reb + ast,
                                             "PR": pts + reb, "PA": pts + ast, "RA": reb + ast})
        for (ab, nm), d in pmap.items():
            if (ab, nm) in seen_p:
                continue
            seen_p.add((ab, nm))
            if lg_code == "nfl":
                d["stats"]["SCRIM YDS"] = d["stats"].get("RUSH YDS", 0.0) + d["stats"].get("REC YDS", 0.0)
            m = team_meta.get(ab, {"bg": "#1e293b", "logo": ""})
            players.append({"name": nm, "team": ab, "pos": d["pos"], "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": d["stats"]})
    for r in rosters:
        ab, m, status, state = r["ab"], r["meta"], r["status"], r["state"]
        for p in r["rlist"]:
            nm, pos = p["name"], p["pos"]
            if (lg_code == "nfl" and pos not in ("QB", "RB", "WR", "TE")) or (ab, nm) in seen_p:
                continue
            seen_p.add((ab, nm))
            players.append({"name": nm, "team": ab, "pos": pos, "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": {}})
    games.sort(key=lambda g: (g["rank"], g["date"]))
    return games, players

def get_live_payload():
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < 15:
        return _CACHE["data"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_nfl = pool.submit(parse_scoreboard, "football/nfl", "nfl")
        f_nba = pool.submit(parse_scoreboard, "basketball/nba", "nba")
        f_cfb = pool.submit(parse_scoreboard, "football/college-football", "cfb")
        nfl_g, nfl_p = f_nfl.result()
        nba_g, nba_p = f_nba.result()
        cfb_g, _ = f_cfb.result()
    payload = {"games": {"NFL": nfl_g, "NBA": nba_g, "CFB": cfb_g}, "players": {"NFL": nfl_p, "NBA": nba_p}}
    _CACHE["ts"], _CACHE["data"] = now, payload
    return payload
@app.route("/api/boxscore/<lg>/<eid>")
def api_boxscore(lg, eid):
    paths = {"nfl": "football/nfl", "nba": "basketball/nba", "cfb": "football/college-football"}
    sp = paths.get(lg.lower())
    if not sp:
        return jsonify({"error": "Invalid league"}), 400
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sp}/summary?event={eid}", timeout=8)
    hdr = next(iter(data.get("header", {}).get("competitions", list())), {})
    teams = list()
    for c in hdr.get("competitors", list()):
        t = c.get("team", {})
        ls = [str(x.get("displayValue", "-")) for x in c.get("linescores", list())]
        teams.append({
            "name": t.get("displayName", t.get("shortDisplayName", "")),
            "abbr": t.get("abbreviation", ""),
            "logo": next((x.get("href", "") for x in t.get("logos", list())), t.get("logo", "")),
            "score": str(c.get("score", "0")),
            "lines": ls,
            "homeAway": c.get("homeAway", "")
        })
    teams.sort(key=lambda x: 0 if x["homeAway"] == "away" else 1)
    team_stats = list()
    for tg in data.get("boxscore", {}).get("teams", list()):
        ab = tg.get("team", {}).get("abbreviation", "")
        st = [{"label": s.get("label", ""), "val": s.get("displayValue", "")} for s in tg.get("statistics", list())]
        team_stats.append({"abbr": ab, "stats": st})
    player_groups = list()
    for tg in data.get("boxscore", {}).get("players", list()):
        t_name = tg.get("team", {}).get("displayName", "")
        cats = list()
        for cat in tg.get("statistics", list()):
            labels = list(cat.get("labels", list()))
            rows = list()
            for ath in cat.get("athletes", list()):
                nm = ath.get("athlete", {}).get("displayName", "")
                if nm:
                    rows.append({"name": nm, "stats": list(ath.get("stats", list()))})
            if rows:
                cats.append({"name": cat.get("text") or cat.get("name", ""), "labels": labels, "rows": rows})
        if cats:
            player_groups.append({"team": t_name, "cats": cats})
    st_txt = hdr.get("status", {}).get("type", {}).get("shortDetail", "")
    return jsonify({"status": st_txt, "teams": teams, "team_stats": team_stats, "players": player_groups})

@app.route("/api/live")
def api_live():
    return jsonify(get_live_payload())

@app.route("/")
def index():
    return render_template("index.html")

