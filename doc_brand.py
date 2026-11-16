import re
import requests

CDN = "https://" + "a." + "espncdn." + "com/combiner/i?img=/i/teamlogos"

NFL_META = {
    "ari": ("97233F", "ari"), "atl": ("A71930", "atl"), "bal": ("241773", "bal"), "buf": ("00338D", "buf"),
    "car": ("0085CA", "car"), "chi": ("0B162A", "chi"), "cin": ("FB4F14", "cin"), "cle": ("311D00", "cle"),
    "dal": ("003594", "dal"), "den": ("FB4F14", "den"), "det": ("0076B6", "det"), "gb": ("203731", "gb"),
    "hou": ("03202F", "hou"), "ind": ("002C5F", "ind"), "jax": ("006778", "jax"), "kc": ("E31837", "kc"),
    "lv": ("000000", "lv"), "lac": ("0080C6", "lac"), "lar": ("003594", "lar"), "mia": ("008E97", "mia"),
    "min": ("4F2683", "min"), "ne": ("002244", "ne"), "no": ("D3BC8D", "no"), "nyg": ("0B2265", "nyg"),
    "nyj": ("125740", "nyj"), "phi": ("004C54", "phi"), "pit": ("FFB612", "pit"), "sf": ("AA0000", "sf"),
    "sea": ("002244", "sea"), "tb": ("D50A0A", "tb"), "ten": ("0C2340", "ten"), "wsh": ("5A1414", "wsh"),
    "was": ("5A1414", "wsh")
}

NBA_META = {
    "atl": ("E03A3E", "atl"), "bos": ("007A33", "bos"), "bkn": ("000000", "bkn"), "cha": ("1D1160", "cha"),
    "chi": ("CE1141", "chi"), "cle": ("860038", "cle"), "dal": ("00538C", "dal"), "den": ("0E2240", "den"),
    "det": ("C8102E", "det"), "gs": ("1D428A", "gs"), "gsw": ("1D428A", "gs"), "hou": ("CE1141", "hou"),
    "ind": ("002D62", "ind"), "lac": ("C8102E", "lac"), "lal": ("552583", "lal"), "mem": ("5D76A9", "mem"),
    "mia": ("98002E", "mia"), "mil": ("00471B", "mil"), "min": ("0C2340", "min"), "no": ("0C2340", "no"),
    "nop": ("0C2340", "no"), "ny": ("006BB6", "ny"), "nyk": ("006BB6", "ny"), "okc": ("007AC1", "okc"),
    "orl": ("0077C0", "orl"), "phi": ("006BB6", "phi"), "phx": ("1D1160", "phx"), "por": ("E03A3E", "por"),
    "sac": ("5A2D81", "sac"), "sa": ("C4CED4", "sa"), "sas": ("C4CED4", "sa"), "tor": ("CE1141", "tor"),
    "utah": ("002B5C", "utah"), "uta": ("002B5C", "utah"), "wsh": ("002B5C", "wsh"), "was": ("002B5C", "wsh")
}

_CFB = {}
_TRIED_CFB = False

def load_cfb():
    global _TRIED_CFB
    if _TRIED_CFB: return
    _TRIED_CFB = True
    try:
        host = "site." + "api." + "espn." + "com"
        data = requests.get(f"https://{host}/apis/site/v2/sports/football/college-football/teams?limit=1000", timeout=8).json()
        le = next(iter(next(iter(data.get("sports", list())), {}).get("leagues", list())), {})
        for item in le.get("teams", list()):
            t = item.get("team", {})
            clr = str(t.get("color", "F1F5F9")).strip().lstrip("#")
            if len(clr) != 6: clr = "F1F5F9"
            tid = str(t.get("id", "")).strip()
            for k in (t.get("shortDisplayName"), t.get("location"), t.get("displayName"), t.get("name")):
                if k: _CFB[str(k).strip().lower()] = (clr, tid)
    except Exception:
        pass

def team_style(raw, is_nfl=False, league=None):
    key = re.sub(r"^#\d+\s+", "", str(raw).strip()).lower()
    lg = "nba" if league == "nba" else ("nfl" if (league == "nfl" or is_nfl) else "ncaa")
    if lg in ("nfl", "nba"):
        db = NFL_META if lg == "nfl" else NBA_META
        hx, code = db.get(key, ("F1F5F9", ""))
    else:
        load_cfb()
        hx, code = _CFB.get(key) or _CFB.get(re.sub(r"\s*\(.*?\)", "", key).strip()) or ("F1F5F9", "")
    r, g, b = int(hx[:2], 16) / 255.0, int(hx[2:4], 16) / 255.0, int(hx[4:6], 16) / 255.0
    is_dark = (0.299 * r + 0.587 * g + 0.114 * b) < 0.55
    fg = {"red": 1.0, "green": 1.0, "blue": 1.0} if is_dark else {"red": 0.12, "green": 0.16, "blue": 0.22}
    folder = "500-dark" if is_dark else "500"
    logo = f"{CDN}/{lg}/{folder}/{code}.png&w=64&h=64" if code else ""
    return {"red": r, "green": g, "blue": b}, fg, logo
