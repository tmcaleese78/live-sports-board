import os
import time
import requests
from flask import Flask, jsonify, render_template
import doc_brand

app = Flask(__name__)
HOST = "site." + "api." + "espn." + "com"
_CACHE = {"ts": 0.0, "data": None}
_ROSTER_CACHE = {}

def rgb_css(c):
    return f"rgb({int(c['red']*255)},{int(c['green']*255)},{int(c['blue']*255)})"

def fetch_json(url, timeout=10):
    try:
        return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout).json()
    except Exception:
        return {}

def get_roster(sport_path, tid):
    key = (sport_path, tid)
    if key in _ROSTER_CACHE:
        return _ROSTER_CACHE[key]
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/teams/{tid}/roster", timeout=8)
    out = list()
    for grp in data.get("athletes", list()):
        items = grp.get("items", list()) if isinstance(grp, dict) else [grp]
        for a in items:
            if isinstance(a, dict) and a.get("displayName"):
                out.append((a["displayName"], a.get("position", {}).get("abbreviation", "")))
    if out:
        _ROSTER_CACHE[key] = out
    return out

def parse_scoreboard(sport_path, lg_code):
    sb = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard")
    games, players = list(), list()
    seen_p = set()
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
        bg0, fg0, lg0 = doc_brand.team_style(a_name, league=lg_code)
        bg1, fg1, lg1 = doc_brand.team_style(h_name, league=lg_code)
        sort_rank = 0 if state == "in" else (1 if state == "pre" else 2)
        games.append({
            "rank": sort_rank, "date": str(ev.get("date", "")),
            "id": eid, "league": lg_code.upper(), "state": state, "status": status,
            "tv": tv, "odds": odds_txt,
            "away": a_name, "away_full": a_full, "arec": a_rec, "ascore": str(away.get("score", "0")), "aposs": (poss_id == str(away.get("id", "")) and state == "in"),
            "home": h_name, "home_full": h_full, "hrec": h_rec, "hscore": str(home.get("score", "0")), "hposs": (poss_id == str(home.get("id", "")) and state == "in"),
            "bg0": rgb_css(bg0), "fg0": rgb_css(fg0), "lg0": lg0,
            "bg1": rgb_css(bg1), "fg1": rgb_css(fg1), "lg1": lg1
        })
        if lg_code not in ("nfl", "nba") or not eid:
            continue
        box = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/summary?event={eid}") if state != "pre" else {}
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
            bg, _, logo = doc_brand.team_style(ab, league=lg_code)
            players.append({"name": nm, "team": ab, "pos": d["pos"], "league": lg_code.upper(), "status": status, "state": state, "bg": rgb_css(bg), "logo": logo, "stats": d["stats"]})
        for c in comps:
            t = c.get("team", {})
            ab, tid = t.get("abbreviation", ""), t.get("id", "")
            for nm, pos in get_roster(sport_path, tid):
                if (lg_code == "nfl" and pos not in ("QB", "RB", "WR", "TE")) or (ab, nm) in seen_p:
                    continue
                seen_p.add((ab, nm))
                bg, _, logo = doc_brand.team_style(ab, league=lg_code)
                players.append({"name": nm, "team": ab, "pos": pos, "league": lg_code.upper(), "status": status, "state": state, "bg": rgb_css(bg), "logo": logo, "stats": {}})
    games.sort(key=lambda g: (g["rank"], g["date"]))
    return games, players

def get_live_payload():
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < 15:
        return _CACHE["data"]
    nfl_g, nfl_p = parse_scoreboard("football/nfl", "nfl")
    nba_g, nba_p = parse_scoreboard("basketball/nba", "nba")
    cfb_g, _ = parse_scoreboard("football/college-football", "cfb")
    payload = {"games": {"NFL": nfl_g, "NBA": nba_g, "CFB": cfb_g}, "players": {"NFL": nfl_p, "NBA": nba_p}}
    _CACHE["ts"], _CACHE["data"] = now, payload
    return payload

@app.route("/api/live")
def api_live():
    return jsonify(get_live_payload())

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
