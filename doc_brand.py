import re
from curl_cffi import requests

_CFB = {}
_NFL = {}
_NBA = {}

def load_branding():
    if _CFB and _NFL and _NBA:
        return
    host = "site." + "api." + "espn." + "com"
    cdn = "a." + "espncdn." + "com"
    sources = [
        (_CFB, "ncaa", f"https://{host}/apis/site/v2/sports/football/college-football/teams?limit=1000"),
        (_NFL, "nfl", f"https://{host}/apis/site/v2/sports/football/nfl/teams?limit=50"),
        (_NBA, "nba", f"https://{host}/apis/site/v2/sports/basketball/nba/teams?limit=50")
    ]
    for target_db, lg, url in sources:
        try:
            data = requests.get(url, impersonate="chrome", timeout=15).json()
            sp = next(iter(data.get("sports", list())), {})
            le = next(iter(sp.get("leagues", list())), {})
            for item in le.get("teams", list()):
                t = item.get("team", {})
                clr = str(t.get("color", "F1F5F9")).strip().lstrip("#")
                if len(clr) != 6:
                    clr = "F1F5F9"
                tid = str(t.get("id", "")).strip()
                ab = str(t.get("abbreviation", "")).strip().lower()
                code = tid if lg == "ncaa" else ab
                light_logo = f"https://{cdn}/combiner/i?img=/i/teamlogos/{lg}/500/{code}.png&w=64&h=64"
                dark_logo = f"https://{cdn}/combiner/i?img=/i/teamlogos/{lg}/500-dark/{code}.png&w=64&h=64"
                for k in (t.get("shortDisplayName"), t.get("location"), t.get("displayName"), t.get("name")):
                    if k:
                        ck = str(k).strip().lower()
                        if ck not in target_db:
                            target_db[ck] = (clr, light_logo, dark_logo)
                if lg in ("nfl", "nba") and ab:
                    target_db[ab] = (clr, light_logo, dark_logo)
        except Exception as err:
            print("Branding error:", err)
    print(f"Loaded {len(_CFB)} CFB, {len(_NFL)} NFL & {len(_NBA)} NBA keys.")

def team_style(raw, is_nfl=False, league=None):
    load_branding()
    if league == "nba":
        db = _NBA
    elif league == "nfl" or is_nfl:
        db = _NFL
    else:
        db = _CFB
    key = re.sub(r"^#\d+\s+", "", str(raw).strip()).lower()
    hx, light_logo, dark_logo = db.get(key) or db.get(re.sub(r"\s*\(.*?\)", "", key).strip()) or ("F1F5F9", "", "")
    r, g, b = int(hx[:2], 16) / 255.0, int(hx[2:4], 16) / 255.0, int(hx[4:6], 16) / 255.0
    is_dark_bg = (0.299 * r + 0.587 * g + 0.114 * b) < 0.55
    fg = {"red": 1.0, "green": 1.0, "blue": 1.0} if is_dark_bg else {"red": 0.12, "green": 0.16, "blue": 0.22}
    return {"red": r, "green": g, "blue": b}, fg, (dark_logo if is_dark_bg else light_logo)
