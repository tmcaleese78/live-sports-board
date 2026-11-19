import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Flask, jsonify, redirect, render_template, request

app = Flask(__name__)
HOST = "site." + "api." + "espn." + "com"
_CACHE = {"ts": 0.0, "data": None}
_ROSTER_CACHE = {}
_PLAYER_CACHE = {}
_SEASON_CACHE = {}
_PROJ_CACHE = {}

@app.route("/api/projections/<lg>")
def api_projections(lg):
    lg_u = lg.upper()
    if lg_u not in ("NFL", "NBA"):
        return jsonify({"error": "Invalid league"}), 400
    now = time.time()
    if lg_u in _PROJ_CACHE and (now - _PROJ_CACHE[lg_u]["ts"]) < 900:
        return jsonify(_PROJ_CACHE[lg_u]["data"])

    payload = get_live_payload(fast=False)
    games = payload.get("games", {}).get(lg_u, [])
    players = payload.get("players", {}).get(lg_u, [])

    opp_map = {}
    for g in games:
        aw, hm = g.get("away", ""), g.get("home", "")
        st = g.get("status", "")
        if aw and hm:
            opp_map[aw] = f"@ {hm} ({st})"
            opp_map[hm] = f"vs {aw} ({st})"

    # Fetch ESPN public fantasy projections (statSourceId=1 = projections)
    esp_sport = "ffl" if lg_u == "NFL" else "fba"
    season_yr = 2026
    proj_url = f"https://espn.com{esp_sport}/seasons/{season_yr}/segments/0/leaguedefaults/3?view=kona_player_info"
    filt = json.dumps({
        "players": {
            "filterStatsForSourceIds": {"value": [1]},
            "sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": f"10{season_yr}"},
            "limit": 250,
            "offset": 0
        }
    })
       proj_by_name = {}
    try:
        r = requests.get(
            proj_url,
            headers={"User-Agent": "Mozilla/5.0", "x-fantasy-filter": filt},
            timeout=7
        )
        pdata = r.json() if r.ok else {}
        for entry in pdata.get("players", []):
            pl = entry.get("player", {})
            nm = pl.get("fullName", "").lower().strip()
            if not nm:
                continue
            st_list = [s for s in pl.get("stats", []) if s.get("statSourceId") == 1]
            wk = next((s for s in st_list if s.get("statSplitTypeId") == 1 and s.get("stats")), None)
            chosen = wk or next((s for s in st_list if s.get("stats")), None)
            if chosen:
                proj_by_name[nm] = chosen.get("stats", {})
    except Exception:
        pass

    out = []
    for p in players:
        tm = p.get("team", "")
        if opp_map and tm not in opp_map:
            continue
        nm = p.get("name", "")
        pos = p.get("pos", "")
        if lg_u == "NFL" and pos not in ("QB", "RB", "WR", "TE"):
            continue
        raw_s = proj_by_name.get(nm.lower().strip(), {})
        if not raw_s:
            continue
        if lg_u == "NFL":
            # ESPN FFL stat IDs: 3=PassYds, 4=PassTD, 24=RushYds, 25=RushTD, 42=RecYds, 43=RecTD, 53=Rec
            py = round(float(raw_s.get("3", 0)), 1)
            ptd = round(float(raw_s.get("4", 0)), 1)
            ry = round(float(raw_s.get("24", 0)), 1)
            rtd = round(float(raw_s.get("25", 0)), 1)
            rec = round(float(raw_s.get("53", 0)), 1)
            recy = round(float(raw_s.get("42", 0)), 1)
            rectd = round(float(raw_s.get("43", 0)), 1)
            if (py + ry + recy + rec) <= 0:
                continue
            stats = {
                "PASS YDS": py, "PASS TD": ptd, "RUSH YDS": ry, "RUSH TD": rtd,
                "REC": rec, "REC YDS": recy, "REC TD": rectd, "SCRIM YDS": round(ry + recy, 1)
            }
        else:
            # ESPN FBA stat IDs: 0=PTS, 6=REB, 3=AST, 17=3PM, 2=STL, 1=BLK
            pts = round(float(raw_s.get("0", 0)), 1)
            reb = round(float(raw_s.get("6", 0)), 1)
            ast = round(float(raw_s.get("3", 0)), 1)
            tpm = round(float(raw_s.get("17", 0)), 1)
            stl = round(float(raw_s.get("2", 0)), 1)
            blk = round(float(raw_s.get("1", 0)), 1)
            if (pts + reb + ast) <= 0:
                continue
            stats = {
                "PTS": pts, "REB": reb, "AST": ast, "3PM": tpm,
                "STL": stl, "BLK": blk, "PRA": round(pts + reb + ast, 1)
            }
        out.append({
            "id": p.get("id", ""),
            "name": nm,
            "team": tm,
            "pos": pos,
            "opp": opp_map.get(tm, ""),
            "bg": p.get("bg", "#1e293b"),
            "logo": p.get("logo", ""),
            "stats": stats
        })

    res_obj = {"league": lg_u, "players": out}
    _PROJ_CACHE[lg_u] = {"ts": now, "data": res_obj}
    return jsonify(res_obj)

@app.route("/api/projections/<lg>")
def api_season(lg):
    paths = {"nfl": "football/nfl", "nba": "basketball/nba"}
    sp = paths.get(lg.lower())
    if not sp:
        return jsonify({"error": "Invalid league"}), 400
    ck = f"v4:{lg.lower()}"
    now = time.time()
    if ck in _SEASON_CACHE and (now - _SEASON_CACHE[ck]["ts"]) < 900:
        return jsonify(_SEASON_CACHE[ck]["data"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_st = pool.submit(fetch_json, f"https://{HOST}/apis/v2/sports/{sp}/standings", 6)
        f_ld = pool.submit(fetch_json, f"https://espn.com{sp}/statistics/byathlete?limit=150", 8)
        st_data = f_st.result()
        ld_data = f_ld.result()

    teams_out = []
    def walk_standings(node):
        if not isinstance(node, dict):
            return
        for entry in node.get("standings", {}).get("entries", []):
            tm = entry.get("team", {})
            st_map = {s.get("name"): s.get("displayValue", "0") for s in entry.get("stats", [])}
            teams_out.append({
                "name": tm.get("displayName", ""),
                "abbr": tm.get("abbreviation", ""),
                "bg": clean_hex(tm.get("color"), "#1e293b"),
                "logo": next((x.get("href", "") for x in tm.get("logos", [])), ""),
                "rec": st_map.get("overall") or st_map.get("record") or f"{st_map.get('wins','0')}-{st_map.get('losses','0')}",
                "pf": st_map.get("pointsFor", "0"),
                "pa": st_map.get("pointsAgainst", "0"),
                "diff": st_map.get("pointDifferential") or st_map.get("differential") or "0",
                "pct": st_map.get("winPercent", "0")
            })
        for ch in node.get("children", []):
            walk_standings(ch)

    walk_standings(st_data)
    seen_t = set()
    uniq_teams = []
    for t in teams_out:
        if t["abbr"] and t["abbr"] not in seen_t:
            seen_t.add(t["abbr"])
            uniq_teams.append(t)

    cat_specs = (
        [("passing", "YDS", "Passing Yards"), ("passing", "TD", "Passing TDs"),
         ("rushing", "YDS", "Rushing Yards"), ("rushing", "TD", "Rushing TDs"),
         ("receiving", "YDS", "Receiving Yards"), ("receiving", "REC", "Receptions")]
        if lg.lower() == "nfl" else
        [("offensive", "PTS", "Points Per Game"), ("general", "REB", "Rebounds Per Game"),
         ("offensive", "AST", "Assists Per Game"), ("offensive", "3PM", "3-Pointers Made"),
         ("defensive", "STL", "Steals Per Game"), ("defensive", "BLK", "Blocks Per Game")]
    )
    buckets = {title: [] for _, _, title in cat_specs}
    cat_meta = {}
    for c in ld_data.get("categories", []):
        cname = str(c.get("name", "")).lower()
        lbls = [str(x).upper() for x in (c.get("labels") or c.get("names") or [])]
        cat_meta[cname] = lbls

    for item in ld_data.get("athletes", []):
        ath = item.get("athlete", {})
        tm = ath.get("team") or next(iter(ath.get("teams", [])), {})
        pid = str(ath.get("id", ""))
        nm = ath.get("displayName", "")
        ab = tm.get("abbreviation", "")
        bg = clean_hex(tm.get("color"), "#1e293b")
        logo = next((x.get("href", "") for x in tm.get("logos", [])), "")
        by_cat = {}
        for c in item.get("categories", []):
            cname = str(c.get("name", "")).lower()
            by_cat[cname] = c.get("totals") or c.get("values") or []
        for cname, stat_lbl, title in cat_specs:
            lbls = cat_meta.get(cname, [])
            vals = by_cat.get(cname, [])
            if stat_lbl in lbls:
                idx = lbls.index(stat_lbl)
                if idx < len(vals):
                    raw_v = str(vals[idx]).replace(",", "")
                    try:
                        num_v = float(raw_v)
                    except ValueError:
                        num_v = 0.0
                    if num_v > 0:
                        buckets[title].append({"id": pid, "name": nm, "team": ab, "bg": bg, "logo": logo, "val": str(vals[idx]), "_num": num_v})

    leaders_out = []
    for _, _, title in cat_specs:
        rows = sorted(buckets[title], key=lambda x: x["_num"], reverse=True)[:15]
        for r in rows:
            r.pop("_num", None)
        if rows:
            leaders_out.append({"category": title, "players": rows})

    payload = {"league": lg.upper(), "teams": uniq_teams, "leaders": leaders_out}
    _SEASON_CACHE[ck] = {"ts": now, "data": payload}
    return jsonify(payload)

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
                out.append({
                    "id": str(a.get("id", "")),
                    "name": a["displayName"],
                    "pos": a.get("position", {}).get("abbreviation", "")
                })
    if out:
        _ROSTER_CACHE[key] = out
    return out

def parse_scoreboard(sport_path, lg_code, fast=False):
    sb = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard", timeout=6)
    events = list(sb.get("events", list()))
    if lg_code == "nfl" and events and all(
        ev.get("status", {}).get("type", {}).get("state") == "post" for ev in events
    ):
        wk = sb.get("week", {}).get("number")
        st_type = sb.get("season", {}).get("type")
        if wk and st_type:
            nxt = fetch_json(
                f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard?week={int(wk) + 1}&seasontype={st_type}",
                timeout=6,
            )
            events.extend(nxt.get("events", list()))
    games, players = list(), list()
    seen_p = set()
    box_tasks, roster_tasks = list(), list()
    for ev in events:
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
        if fast or lg_code not in ("nfl", "nba") or not eid:
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
    if fast:
        games.sort(key=lambda g: (g["rank"], g["date"]))
        return games, []
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
                    rec = pmap.setdefault((ab, nm), {"id": str(a.get("id", "")), "pos": a.get("position", {}).get("abbreviation", ""), "stats": {}})
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
            players.append({"id": d.get("id", ""), "name": nm, "team": ab, "pos": d["pos"], "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": d["stats"]})
    for r in rosters:
        ab, m, status, state = r["ab"], r["meta"], r["status"], r["state"]
        for p in r["rlist"]:
            nm, pos = p["name"], p["pos"]
            if (lg_code == "nfl" and pos not in ("QB", "RB", "WR", "TE")) or (ab, nm) in seen_p:
                continue
            seen_p.add((ab, nm))
            players.append({"id": p.get("id", ""), "name": nm, "team": ab, "pos": pos, "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": {}})
    games.sort(key=lambda g: (g["rank"], g["date"]))
    return games, players

def get_live_payload(fast=False):
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < 20:
        return _CACHE["data"]
    if fast and not _CACHE["data"]:
        threading.Thread(target=get_live_payload, kwargs={"fast": False}, daemon=True).start()
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_nfl = pool.submit(parse_scoreboard, "football/nfl", "nfl", True)
            f_nba = pool.submit(parse_scoreboard, "basketball/nba", "nba", True)
            f_cfb = pool.submit(parse_scoreboard, "football/college-football", "cfb", True)
            nfl_g, _ = f_nfl.result()
            nba_g, _ = f_nba.result()
            cfb_g, _ = f_cfb.result()
        return {"games": {"NFL": nfl_g, "NBA": nba_g, "CFB": cfb_g}, "players": {"NFL": [], "NBA": []}, "partial": True}
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_nfl = pool.submit(parse_scoreboard, "football/nfl", "nfl", False)
        f_nba = pool.submit(parse_scoreboard, "basketball/nba", "nba", False)
        f_cfb = pool.submit(parse_scoreboard, "football/college-football", "cfb", False)
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
_PLAYER_CACHE = {}

@app.route("/api/player/<lg>/<pid>")
def api_player(lg, pid):
    paths = {"nfl": "football/nfl", "nba": "basketball/nba"}
    sp = paths.get(lg.lower())
    if not sp or not pid:
        return jsonify({"error": "Invalid player"}), 400
    ck = f"v4:{lg.lower()}:{pid}"
    now = time.time()
    if ck in _PLAYER_CACHE and (now - _PLAYER_CACHE[ck]["ts"]) < 900:
        return jsonify(_PLAYER_CACHE[ck]["data"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_bio = pool.submit(fetch_json, f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}", 6)
        f_ov = pool.submit(fetch_json, f"https://espn.com{sp}/athletes/{pid}/overview", 6)
        f_gl = pool.submit(fetch_json, f"https://espn.com{sp}/athletes/{pid}/gamelog", 6)
        bio = f_bio.result()
        ov = f_ov.result()
        gl = f_gl.result()

    if not ov.get("statistics") and not ov.get("gamelog"):
        ov = fetch_json(f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/overview", 6) or ov
    if not gl.get("seasonTypes"):
        gl = fetch_json(f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/gamelog", 6) or gl

    ath = bio.get("athlete") or ov.get("athlete") or {}
    tm = ath.get("team", {})
    season_stats = []
    st_blk = ov.get("statistics") or bio.get("statistics") or {}
    labels = st_blk.get("labels") or st_blk.get("names") or []
    splits = st_blk.get("splits", [])
    if labels and isinstance(splits, list) and len(splits) > 0:
        first_split = splits[0] if isinstance(splits[0], dict) else {}
        vals = first_split.get("stats", [])
        season_stats = [{"label": labels[i], "val": vals[i]} for i in range(min(len(labels), len(vals)))]

    gl_src = gl if gl.get("seasonTypes") else ov.get("gamelog", {})
    gl_labels = gl_src.get("labels") or gl_src.get("names") or []
    events_map = gl_src.get("events", {})
    games_by_id = {}
    for st_type in gl_src.get("seasonTypes", []):
        for cat in st_type.get("categories", []):
            if not gl_labels:
                gl_labels = cat.get("labels") or cat.get("names") or []
            for ev in cat.get("events", []):
                eid = str(ev.get("eventId", ""))
                if not eid or eid in games_by_id:
                    continue
                meta = events_map.get(eid, {}) if isinstance(events_map, dict) else {}
                opp = meta.get("opponent", {})
                games_by_id[eid] = {
                    "date": str(meta.get("gameDate", ""))[:10],
                    "opp": opp.get("abbreviation", ""),
                    "atVs": meta.get("atVs", "vs"),
                    "result": meta.get("gameResult", ""),
                    "score": meta.get("score", ""),
                    "stats": ev.get("stats", [])
                }
    games_log = sorted(games_by_id.values(), key=lambda x: x["date"], reverse=True)

    payload = {
        "id": pid,
        "name": ath.get("displayName", ""),
        "jersey": ath.get("jersey", ""),
        "pos": ath.get("position", {}).get("abbreviation", ""),
        "headshot": ath.get("headshot", {}).get("href", ""),
        "team": tm.get("displayName", ""),
        "abbr": tm.get("abbreviation", ""),
        "bg": clean_hex(tm.get("color"), "#1e293b"),
        "logo": next((x.get("href", "") for x in tm.get("logos", [])), ""),
        "season": season_stats,
        "gamelog": {"labels": gl_labels, "games": games_log[:10]}
    }
    _PLAYER_CACHE[ck] = {"ts": now, "data": payload}
    return jsonify(payload)

@app.route("/api/live")
def api_live():
    is_fast = request.args.get("fast") == "1"
    return jsonify(get_live_payload(fast=is_fast))

threading.Thread(target=get_live_payload, kwargs={"fast": False}, daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html")

