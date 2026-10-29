"""Sports Analytics domain for BERU (AgentMD-style registry)."""
from __future__ import annotations

import math
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

MAX_OUTPUT_CHARS = 5000
HTTP_TIMEOUT = 10
SAFETY = "This is not betting advice. Statistics are descriptive, not predictive."
DESCRIPTIVE = "Descriptive statistic, not a match prediction."

_FD_BASE = "https://api.football-data.org/v4"
_FD_KEY_ENV = "FOOTBALL_DATA_API_KEY"
_FD_SOURCE = "Data source: football-data.org (free tier)"
_FD_SEARCH_CODES = ("PL", "PD", "SA", "BL1", "FL1", "CL")

_CB_BASE = "https://cricbuzz-cricket.p.rapidapi.com"
_CB_KEY_ENV = "CRICBUZZ_RAPIDAPI_KEY"
_CB_SOURCE = "Data source: Cricbuzz via RapidAPI (free tier)"

_BDL_BASE = "https://api.balldontlie.io/nba/v1"
_BDL_KEY_ENV = "BALLDONTLIE_API_KEY"
_BDL_SOURCE = "Data source: balldontlie.io (free tier)"

def _finish(body: str, extra: str = "") -> str:
    tail = "\n".join(x for x in (extra, SAFETY) if x)
    room = MAX_OUTPUT_CHARS - len(tail) - 2
    body = str(body)
    if len(body) > room:
        body = body[: max(0, room - 15)].rstrip() + "\n…[truncated]"
    return f"{body}\n{tail}"

def _missing_key(env: str, signup: str, source: str) -> str:
    return _finish(f"Not configured: set the {env} environment variable ({signup}). No request was made.", source)

def _get_json(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> Tuple[Any, Optional[str]]:
    try:
        import requests
    except ImportError:
        return None, "the 'requests' package is not installed"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "request timed out"
    except requests.exceptions.RequestException as exc:
        return None, f"network error ({type(exc).__name__})"
    except Exception as exc:
        return None, f"unexpected error ({type(exc).__name__})"
    if resp.status_code in (401, 403):
        return None, f"access denied (HTTP {resp.status_code}); check the API key"
    if resp.status_code == 404:
        return None, "not found (HTTP 404)"
    if resp.status_code == 429:
        return None, "rate limit reached (HTTP 429)"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    try:
        return resp.json(), None
    except ValueError:
        return None, "response was not valid JSON"

def _clean_text(value: Any, max_len: int = 60) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    return v if 0 < len(v) <= max_len else None

def fetch_football_standings(competition_code: str = "PL") -> str:
    try:
        key = os.getenv(_FD_KEY_ENV, "").strip()
        if not key:
            return _missing_key(_FD_KEY_ENV, "free key at football-data.org/client/register", _FD_SOURCE)
        code = (competition_code or "").strip().upper() if isinstance(competition_code, str) else ""
        if not re.fullmatch(r"[A-Z0-9]{2,5}", code):
            return _finish("Invalid competition_code. Use e.g. PL, PD, SA, BL1, FL1.", _FD_SOURCE)
        data, err = _get_json(f"{_FD_BASE}/competitions/{code}/standings", {"X-Auth-Token": key})
        if err:
            return _finish(f"Could not fetch standings for {code}: {err}.", _FD_SOURCE)
        tables = [s for s in data.get("standings", []) if s.get("type") == "TOTAL"] or data.get("standings", [])
        rows = (tables[0].get("table") if tables else None) or []
        if not rows:
            return _finish(f"No standings returned for {code}.", _FD_SOURCE)
        name = (data.get("competition") or {}).get("name", code)
        out = [f"{name} - top {min(10, len(rows))}", "Pos Team                      P   W  D  L   GD  Pts"]
        for r in rows[:10]:
            team = ((r.get("team") or {}).get("shortName") or (r.get("team") or {}).get("name") or "?")[:24]
            out.append(f"{r.get('position', '?'):>3} {team:<24} {r.get('playedGames', 0):>3} {r.get('won', 0):>3} "
                       f"{r.get('draw', 0):>2} {r.get('lost', 0):>2} {r.get('goalDifference', 0):>+4} {r.get('points', 0):>4}")
        return _finish("\n".join(out), _FD_SOURCE)
    except Exception as exc:
        return _finish(f"Standings unavailable ({type(exc).__name__}).", _FD_SOURCE)

def _find_team(name: str, key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    needle = name.casefold()
    partial: Optional[Dict[str, Any]] = None
    last_err: Optional[str] = None
    for code in _FD_SEARCH_CODES:
        data, err = _get_json(f"{_FD_BASE}/competitions/{code}/teams", {"X-Auth-Token": key})
        if err:
            last_err = err
            if "rate limit" in err or "access denied" in err:
                break
            continue
        for team in data.get("teams", []):
            names = [str(team.get(k, "")).casefold() for k in ("name", "shortName", "tla")]
            if needle in names:
                return team, None
            if partial is None and any(needle in n for n in names[:2] if n):
                partial = team
    if partial:
        return partial, None
    return None, last_err or "team not found in free-tier competitions"

def fetch_team_form(team_name: str, last_n: int = 5) -> str:
    try:
        key = os.getenv(_FD_KEY_ENV, "").strip()
        if not key:
            return _missing_key(_FD_KEY_ENV, "free key at football-data.org/client/register", _FD_SOURCE)
        name = _clean_text(team_name)
        if not name:
            return _finish("Invalid team_name (1-60 printable characters).", _FD_SOURCE)
        if isinstance(last_n, bool) or not isinstance(last_n, (int, float, str)):
            return _finish("last_n must be an integer from 1 to 10.", _FD_SOURCE)
        try:
            n = int(float(last_n))
        except (TypeError, ValueError, OverflowError):
            return _finish("last_n must be an integer from 1 to 10.", _FD_SOURCE)
        if not 1 <= n <= 10:
            return _finish("last_n must be an integer from 1 to 10.", _FD_SOURCE)
        team, err = _find_team(name, key)
        if not team:
            return _finish(f"Team '{name}' not found: {err}.", _FD_SOURCE)
        tid = team.get("id")
        data, err = _get_json(f"{_FD_BASE}/teams/{tid}/matches", {"X-Auth-Token": key}, {"status": "FINISHED", "limit": 50})
        if err:
            return _finish(f"Could not fetch matches for {team.get('name')}: {err}.", _FD_SOURCE)
        matches = sorted(data.get("matches", []), key=lambda m: m.get("utcDate", ""))[-n:]
        letters: List[str] = []
        for m in matches:
            winner = (m.get("score") or {}).get("winner")
            if winner == "DRAW":
                letters.append("D")
            elif winner in ("HOME_TEAM", "AWAY_TEAM"):
                is_home = (m.get("homeTeam") or {}).get("id") == tid
                letters.append("W" if (winner == "HOME_TEAM") == is_home else "L")
        if not letters:
            return _finish(f"No finished matches found for {team.get('name')} this season.", _FD_SOURCE)
        form = "".join(letters)
        idx = calculate_form_index(form)
        body = (f"{team.get('name')} - last {len(form)} finished matches (oldest -> newest): {form}\n"
                f"Local form index: {idx.splitlines()[0]}")
        return _finish(body, _FD_SOURCE)
    except Exception as exc:
        return _finish(f"Team form unavailable ({type(exc).__name__}).", _FD_SOURCE)

def fetch_cricket_score(match_id: str = "") -> str:
    try:
        key = os.getenv(_CB_KEY_ENV, "").strip()
        if not key:
            return _missing_key(_CB_KEY_ENV, "free RapidAPI key for the 'Cricbuzz Cricket' API", _CB_SOURCE)
        headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "cricbuzz-cricket.p.rapidapi.com"}
        mid = (match_id or "").strip() if isinstance(match_id, str) else ""
        if mid:
            if not re.fullmatch(r"\d{1,10}", mid):
                return _finish("match_id must be numeric (Cricbuzz matchId).", _CB_SOURCE)
            data, err = _get_json(f"{_CB_BASE}/mcenter/v1/{mid}", headers)
            if err:
                return _finish(f"Could not fetch match {mid}: {err}.", _CB_SOURCE)
            info = (data or {}).get("matchInfo") or data or {}
            t1, t2 = (info.get("team1") or {}).get("name", "?"), (info.get("team2") or {}).get("name", "?")
            status = info.get("status") or info.get("state") or "status unavailable"
            return _finish(f"{t1} vs {t2} (id {mid})\nStatus: {status}", _CB_SOURCE)
        data, err = _get_json(f"{_CB_BASE}/matches/v1/live", headers)
        if err:
            return _finish(f"Could not fetch live matches: {err}.", _CB_SOURCE)
        lines: List[str] = []
        for tm in (data or {}).get("typeMatches", []):
            for series in tm.get("seriesMatches", []):
                for m in (series.get("seriesAdWrapper") or {}).get("matches", []):
                    mi = m.get("matchInfo") or {}
                    t1 = (mi.get("team1") or {}).get("teamName", "?")
                    t2 = (mi.get("team2") or {}).get("teamName", "?")
                    lines.append(f"[{mi.get('matchId', '?')}] {t1} vs {t2} - {mi.get('status', 'status unavailable')}")
        if not lines:
            return _finish("No live cricket matches returned.", _CB_SOURCE)
        return _finish("Live matches (id in brackets):\n" + "\n".join(lines[:25]), _CB_SOURCE)
    except Exception as exc:
        return _finish(f"Cricket data unavailable ({type(exc).__name__}).", _CB_SOURCE)

def fetch_nba_standings() -> str:
    try:
        key = os.getenv(_BDL_KEY_ENV, "").strip()
        if not key:
            return _missing_key(_BDL_KEY_ENV, "free key at balldontlie.io", _BDL_SOURCE)
        today = date.today()
        season = today.year if today.month >= 10 else today.year - 1
        data, err = _get_json(f"{_BDL_BASE}/standings", {"Authorization": key}, {"season": season})
        if err:
            return _finish(f"Could not fetch NBA standings: {err}.", _BDL_SOURCE)
        rows = (data or {}).get("data") or []
        if not rows:
            return _finish(f"No NBA standings returned for the {season} season.", _BDL_SOURCE)
        out = [f"NBA standings, {season}-{str(season + 1)[2:]} season"]
        for conf in ("East", "West"):
            conf_rows = sorted((r for r in rows if (r.get("team") or {}).get("conference") == conf),
                               key=lambda r: r.get("conference_rank") or 99)[:8]
            out.append(f"\n{conf}ern Conference" if conf == "East" else f"\nWestern Conference")
            for r in conf_rows:
                out.append(f"{r.get('conference_rank', '?'):>2}. {(r.get('team') or {}).get('full_name', '?'):<26} "
                           f"{r.get('wins', 0)}-{r.get('losses', 0)}")
        return _finish("\n".join(out), _BDL_SOURCE)
    except Exception as exc:
        return _finish(f"NBA data unavailable ({type(exc).__name__}).", _BDL_SOURCE)

class _InputError(ValueError):
    pass

def _to_float(value: Any, name: str, lo: float = -math.inf, hi: float = math.inf) -> float:
    if isinstance(value, bool):
        raise _InputError(f"{name} must be a number")
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        raise _InputError(f"{name} must be a number")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise _InputError(f"{name} must be between {lo:g} and {hi:g}")
    return v

def _to_int(value: Any, name: str, lo: int = 0, hi: int = 100_000) -> int:
    v = _to_float(value, name, lo, hi)
    if v != int(v):
        raise _InputError(f"{name} must be a whole number")
    return int(v)

def _calc_result(body: str) -> str:
    return _finish(body, DESCRIPTIVE)

def _err(exc: Exception) -> str:
    return _finish(f"Input rejected: {exc}.", DESCRIPTIVE)

def calculate_elo_probability(elo_a: float, elo_b: float, home_advantage: float = 100.0) -> str:
    try:
        a, b = _to_float(elo_a, "elo_a", 0, 4000), _to_float(elo_b, "elo_b", 0, 4000)
        h = _to_float(home_advantage, "home_advantage", -500, 500)
    except _InputError as exc:
        return _err(exc)
    p = 1.0 / (1.0 + 10 ** (-(a + h - b) / 400.0))
    return _calc_result(f"Elo expected score for A (home advantage {h:g}): {p:.1%}; for B: {1 - p:.1%}. "
                        "Expected score counts a draw as half a win; it is not a draw-adjusted probability.")

def calculate_win_percentage(wins: int, draws: int, losses: int) -> str:
    try:
        w, d, l = _to_int(wins, "wins"), _to_int(draws, "draws"), _to_int(losses, "losses")
    except _InputError as exc:
        return _err(exc)
    n = w + d + l
    if n == 0:
        return _err(ValueError("at least one game is required"))
    rate, pts_rate = w / n, (w + 0.5 * d) / n
    cat = ("excellent" if pts_rate >= 0.75 else "good" if pts_rate >= 0.55 else
           "average" if pts_rate >= 0.40 else "poor")
    return _calc_result(f"Record {w}W-{d}D-{l}L over {n} games. Win rate: {rate:.1%}. "
                        f"Points rate (draw = 0.5): {pts_rate:.1%}. Form category: {cat}.")

def calculate_points_per_game(points: int, games: int) -> str:
    try:
        p, g = _to_int(points, "points", 0, 10_000_000), _to_int(games, "games", 1, 100_000)
    except _InputError as exc:
        return _err(exc)
    return _calc_result(f"Points per game: {p / g:.2f} ({p} points in {g} games). "
                        f"Pace over a 38-game season: {p / g * 38:.0f} points (arithmetic extrapolation only).")

def calculate_expected_goals(xg_for: float, xg_against: float, matches: int) -> str:
    try:
        xf, xa = _to_float(xg_for, "xg_for", 0, 10_000), _to_float(xg_against, "xg_against", 0, 10_000)
        n = _to_int(matches, "matches", 1, 10_000)
    except _InputError as exc:
        return _err(exc)
    return _calc_result(f"xG for: {xf / n:.2f}/match; xG against: {xa / n:.2f}/match; "
                        f"xG difference: {(xf - xa) / n:+.2f}/match over {n} matches.")

def calculate_form_index(results: str) -> str:
    if not isinstance(results, str):
        return _err(ValueError("results must be a string such as 'WWDLL'"))
    s = re.sub(r"[\s,\-]", "", results).upper()
    if not 1 <= len(s) <= 20 or re.search(r"[^WDL]", s):
        return _err(ValueError("results must be 1-20 letters from W, D, L (oldest to newest)"))
    pts = {"W": 3, "D": 1, "L": 0}
    weights = range(1, len(s) + 1)
    score = sum(pts[c] * w for c, w in zip(s, weights)) / (3 * sum(weights)) * 100
    label = "strong" if score >= 70 else "decent" if score >= 50 else "mixed" if score >= 30 else "poor"
    return _calc_result(f"Weighted form index: {score:.1f}/100 ({label}) for '{s}' (rightmost = most recent, linear weights).")

SPORTS_CALCULATORS: Dict[str, dict] = {
    "elo_probability": {
    "description": "Elo expected score for team A (home) vs team B",
    "keywords": ("elo", "rating", "win probability", "chance", "expected score",
                 "home advantage", "versus", "vs",
                 "more likely to win", "who will win", "favourite", "favorite",
                 "predict", "prediction", "odds", "match up", "head to head"),
    "func": calculate_elo_probability,
    "params": {"elo_a": "float (home team Elo)", "elo_b": "float", "home_advantage": "float, default 100"},
    },
    "win_percentage": {"description": "Win rate, points rate and form category from a W-D-L record", "keywords": ("win percentage", "win rate", "record", "wins", "draws", "losses", "win loss", "form category"), "func": calculate_win_percentage, "params": {"wins": "int", "draws": "int", "losses": "int"}},
    "points_per_game": {"description": "Points per game and season-pace extrapolation", "keywords": ("points per game", "ppg", "points", "games", "average points", "pace", "league table"), "func": calculate_points_per_game, "params": {"points": "int", "games": "int"}},
    "expected_goals": {"description": "xG for/against per match and xG difference", "keywords": ("xg", "expected goals", "goals", "attack", "defence", "defense", "chances", "per match"), "func": calculate_expected_goals, "params": {"xg_for": "float", "xg_against": "float", "matches": "int"}},
    "form_index": {"description": "Recency-weighted form score from a W/D/L string (rightmost = most recent)", "keywords": ("form", "recent form", "momentum", "streak", "last five", "wwdll", "results", "run"), "func": calculate_form_index, "params": {"results": "str of W/D/L, oldest to newest, e.g. 'WWDLL'"}},
}

SPORTS_FETCHERS: Dict[str, dict] = {
    "football_standings": {"description": "Top-10 football league table (needs FOOTBALL_DATA_API_KEY)", "keywords": ("standings", "table", "league", "premier league", "la liga", "serie a", "bundesliga", "football", "soccer", "position"), "func": fetch_football_standings, "params": {"competition_code": "str, default 'PL' (PL, PD, SA, BL1, FL1, CL)"}},
    "team_form": {"description": "Recent W/D/L results for a football team (needs FOOTBALL_DATA_API_KEY)", "keywords": ("team form", "recent results", "last matches", "last five", "how is", "doing", "football", "soccer", "form"), "func": fetch_team_form, "params": {"team_name": "str", "last_n": "int 1-10, default 5"}},
    "cricket_score": {"description": "Live cricket matches or one match status (needs CRICBUZZ_RAPIDAPI_KEY)", "keywords": ("cricket", "score", "live", "ipl", "test", "odi", "t20", "wicket", "innings", "match"), "func": fetch_cricket_score, "params": {"match_id": "str, optional Cricbuzz matchId"}},
    "nba_standings": {"description": "NBA standings by conference (needs BALLDONTLIE_API_KEY)", "keywords": ("nba", "basketball", "standings", "conference", "east", "west", "playoffs"), "func": fetch_nba_standings, "params": {}},
}

_ALL_TOOLS: Dict[str, dict] = {**SPORTS_CALCULATORS, **SPORTS_FETCHERS}
_STOP = {"the", "a", "an", "of", "is", "in", "for", "and", "to", "what", "how", "me", "my", "with", "on", "are", "do", "does"}

def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", text.casefold()) if t not in _STOP}

def suggest_sports_tools(query: str, top_k: int = 3) -> str:
    try:
        if not isinstance(query, str) or not query.strip():
            return _finish("Describe what you want to compute or look up.")
        k = max(1, min(int(top_k), 10))
        text = " " + re.sub(r"[^a-z0-9 ]+", " ", query.casefold()) + " "
        qtok = _tokens(query)
        scored: List[Tuple[float, str]] = []
        for name, spec in _ALL_TOOLS.items():
            score = 0.0
            for kw in spec["keywords"]:
                if " " in kw:
                    if f" {kw} " in text:
                        score += 2.0
                elif kw in qtok:
                    score += 1.0
            score += 0.5 * len(qtok & _tokens(spec["description"]))
            if score > 0:
                scored.append((score, name))
        if not scored:
            return _finish("No matching sports tool. Use list_sports_tools() to see what is available.")
        scored.sort(key=lambda t: (-t[0], t[1]))
        out = ["Suggested sports tools:"]
        for score, name in scored[:k]:
            spec = _ALL_TOOLS[name]
            kind = "calculator (offline)" if name in SPORTS_CALCULATORS else "fetcher (online)"
            out.append(f"- {name} [{kind}, score {score:g}]: {spec['description']}\n  params: {spec['params']}")
        return _finish("\n".join(out))
    except Exception as exc:
        return _finish(f"Suggestion unavailable ({type(exc).__name__}).")

def run_sports_tool(name: str, **params: Any) -> str:
    try:
        key = str(name).strip().casefold()
        key = key.removeprefix("calculate_")
        spec = _ALL_TOOLS.get(key)
        if spec is None:
            return _finish(f"Unknown tool '{_clean_text(str(name), 40) or '?'}'. Available: {', '.join(_ALL_TOOLS)}.")
        unknown = sorted(set(params) - set(spec["params"]))
        if unknown:
            return _finish(f"Unexpected parameter(s): {', '.join(unknown)}. Expected: {spec['params']}.")
        result = spec["func"](**params)
        return result if isinstance(result, str) else _finish(str(result))
    except TypeError:
        spec = _ALL_TOOLS.get(str(name).strip().casefold().removeprefix("calculate_"), {})
        return _finish(f"Missing or invalid parameters. Expected: {spec.get('params', {})}.")
    except Exception as exc:
        return _finish(f"Tool failed ({type(exc).__name__}).")

def list_sports_tools() -> str:
    out = ["Offline calculators:"]
    out += [f"- {n}: {s['description']}  params={s['params']}" for n, s in SPORTS_CALCULATORS.items()]
    out.append("Online fetchers (read-only, free-tier API keys):")
    out += [f"- {n}: {s['description']}  params={s['params']}" for n, s in SPORTS_FETCHERS.items()]
    return _finish("\n".join(out))

__all__ = [
    "SPORTS_CALCULATORS", "SPORTS_FETCHERS",
    "fetch_football_standings", "fetch_team_form", "fetch_cricket_score", "fetch_nba_standings",
    "calculate_elo_probability", "calculate_win_percentage", "calculate_points_per_game",
    "calculate_expected_goals", "calculate_form_index",
    "suggest_sports_tools", "run_sports_tool", "list_sports_tools",
]