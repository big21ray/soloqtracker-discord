import os
import time
import requests
from urllib.parse import quote
import json
from pathlib import Path
from typing import Any


# Default players/accounts (used when no env var or file provided)

def load_players_accounts_from_env() -> dict[str, list[dict[str, str | None]]]:
    """Load PLAYERS_ACCOUNTS from environment variable or JSON file.

    Priority:
    1. `PLAYERS_ACCOUNTS_JSON` env var (JSON string)
    2. `PLAYERS_ACCOUNTS_FILE` env var (path to JSON file)
    3. `DEFAULT_PLAYERS_ACCOUNTS`
    """
    json_text = os.getenv("PLAYERS_ACCOUNTS_JSON")
    if json_text:
        try:
            return json.loads(json_text)
        except Exception as e:
            raise ValueError("Invalid JSON in PLAYERS_ACCOUNTS_JSON") from e

    file_path = os.getenv("PLAYERS_ACCOUNTS_FILE")
    if file_path:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"PLAYERS_ACCOUNTS_FILE not found: {file_path}")
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid JSON in file {file_path}") from e

    return DEFAULT_PLAYERS_ACCOUNTS


def get_ids(
    game_name: str,
    api_key: str,
    tag_line: str | None = None,
    region: str = "europe",
    retries: int = 10,
    timeout: int = 10,
    backoff: float = 1.5,
) -> dict:
    """
    Returns Riot Account-V1 payload for a Riot ID (includes 'puuid').

    If tag_line is None and game_name contains '#', splits like:
      "DX Alex Isley#21Ray" -> ("DX Alex Isley", "21Ray")
    """
    if tag_line is None and "#" in game_name:
        game_name, tag_line = game_name.split("#", 1)

    if not tag_line:
        raise ValueError("tag_line is required (or include it in game_name like 'Name#TAG').")

    game_name_enc = quote(game_name, safe="")
    tag_line_enc = quote(tag_line, safe="")

    url = (
        f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{game_name_enc}/{tag_line_enc}"
    )

    headers = {"X-Riot-Token": api_key}

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_s = float(retry_after) if retry_after else min(2 ** attempt, 60)
                time.sleep(sleep_s)
                continue

            if resp.status_code in (500, 502, 503, 504):
                time.sleep(min(backoff ** attempt, 30))
                continue

            try:
                details = resp.json()
            except ValueError:
                details = resp.text
            raise RuntimeError(f"Riot API error {resp.status_code}: {details}")

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            time.sleep(min(backoff ** attempt, 30))

    raise RuntimeError(f"Failed after {retries} attempts") from last_exc


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def hydrate_players_accounts(
    players_accounts: dict[str, list[dict[str, str]]],
    api_key: str,
    region: str = "europe",
    include_puuid: bool = True,
    cache_path: str | None = "data/riot_account_cache.json",
) -> dict[str, list[dict[str, str | None]]]:
    """Resolves Riot ID -> game_name/tag_line (+ puuid optionally) at runtime.

    Notes:
    - Nothing sensitive (API key) is ever written to disk.
    - If `cache_path` is set, results are cached to avoid extra API calls.
    - If `include_puuid=False`, the returned dict omits PUUIDs (sets them to None).
    """
    hydrated: dict[str, list[dict[str, str | None]]] = {}
    cache_file = Path(cache_path) if cache_path else None
    cache: dict[str, Any] = _load_json(cache_file) if cache_file else {}

    for player, accounts in players_accounts.items():
        hydrated[player] = []
        for account in accounts:
            account_name = account.get("account_name")
            if not account_name:
                raise ValueError(f"Missing account_name for player {player}")

            # Cache key includes region because account routing is regional (americas/europe/asia).
            cache_key = f"{region}:{account_name}"
            ids = cache.get(cache_key)
            if not isinstance(ids, dict) or not ids.get("puuid"):
                ids = get_ids(game_name=account_name, tag_line=None, api_key=api_key, region=region)
                cache[cache_key] = ids

            hydrated[player].append(
                {
                    "account_name": account_name,
                    "game_name": ids.get("gameName"),
                    "tag_line": ids.get("tagLine"),
                    "puuid": ids.get("puuid") if include_puuid else None,
                }
            )

    if cache_file:
        _save_json(cache_file, cache)
    return hydrated


def count_soloq(
    account: dict,
    api_key: str,
    days: int = 1,
) -> int:
    """Return the number of ranked SoloQ matches in the last `days` days.

    Requires `puuid` in `account` and an `api_key` argument.
    """
    puuid = account.get("puuid")
    if not puuid:
        raise ValueError("account must include 'puuid'")

    region = account.get("region", "europe")
    now = int(time.time())
    start_time = now - int(days) * 24 * 3600

    url = (
        f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
        f"{puuid}/ids?startTime={start_time}&endTime={now}&type=ranked&start=0&count=100"
    )
    headers = {"X-Riot-Token": api_key}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    match_ids = resp.json()
    return len(match_ids)

def get_current_elo(account: dict, api_key: str) -> str:
    """Return the current ranked tier/division for the given account.

    Requires `puuid` in `account` and an `api_key` argument.
    """
    puuid = account.get("puuid")
    if not puuid:
        raise ValueError("account must include 'puuid'")

    region = account.get("region", "europe")
    platform_map = {"europe": "euw1", "americas": "na1", "asia": "kr"}
    platform = platform_map.get(region, "euw1")

    headers = {"X-Riot-Token": api_key}

    # Get summoner id by puuid
    url = f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    print(resp.json())
    entries = resp.json()

    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            tier = entry.get("tier")
            rank = entry.get("rank")
            lp = entry.get("leaguePoints")
            return f"{tier} {rank} - {lp} LP"
    return "Unranked"

import re

TIERS = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
    "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
TIER_RANK = {t: i for i, t in enumerate(TIERS)}
DIV_MAP = {"V": 0, "IV": 1, "III": 2, "II": 3, "I": 4}


def _parse_elo(s: str) -> tuple[int, int, int]:
    """Return (tier_rank, division_value, lp). Unranked -> (-1,-1,-1)."""
    if not s:
        return -1, -1, -1
    su = s.upper().strip()
    if "UNRANKED" in su:
        return -1, -1, -1

    # lp
    m = re.search(r"\((\d+)\s*LP\)", su)
    lp = int(m.group(1)) if m else 0

    # tier
    tier_rank = -1
    for t in TIERS:
        if t in su:
            tier_rank = TIER_RANK[t]
            break
    if tier_rank == -1:
        return -1, -1, -1

    # divisions: Master+ don't have divisions so treat them above Diamond I
    if tier_rank >= TIER_RANK["MASTER"]:
        division_value = 5
    else:
        mdiv = re.search(r"\b(I|II|III|IV|V)\b", su)
        division_value = DIV_MAP.get(mdiv.group(1), 0) if mdiv else 0

    return tier_rank, division_value, lp


def max_elo(acc_elos: list[str]) -> str | None:
    """Return the highest elo string from acc_elos (or None if none valid)."""
    parsed = []
    for s in acc_elos:
        key = _parse_elo(s)
        if key[0] >= 0:
            parsed.append((key, s))
    if not parsed:
        return None
    # tuple compare: higher tier_rank, then higher division_value, then higher LP
    best = max(parsed, key=lambda x: (x[0][0], x[0][1], x[0][2]))
    return best[1]

from datetime import datetime
import pytz

def format_players_report(rows: list[dict]) -> str:
    """
    rows = list of dicts with keys:
      'Player','Games24','Games7','LastGame','Elo','Main','Emoji'
    Returns a single string with a fixed-width table.
    """
    headers = ["Player", "Games 24 Hours", "Games 7 days", "Last Game", "Current Elo", "Main Account", "Reha happy"]
    cols = ["Player", "Games24", "Games7", "LastGame", "Elo", "Main", "Emoji"]

    # compute column widths
    widths = []
    for h, c in zip(headers, cols):
        maxw = len(h)
        for r in rows:
            v = str(r.get(c, "")) if r.get(c, "") is not None else ""
            maxw = max(maxw, len(v))
        widths.append(maxw)

    # format header
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep_line = "  ".join("-" * w for w in widths)

    # format rows
    row_lines = []
    for r in rows:
        vals = [
            str(r.get("Player", "")).ljust(widths[0]),
            str(r.get("Games24", "")).rjust(widths[1]),
            str(r.get("Games7", "")).rjust(widths[2]),
            str(r.get("LastGame", "")).ljust(widths[3]),
            str(r.get("Elo", "")).ljust(widths[4]),
            str(r.get("Main", "")).ljust(widths[5]),
            str(r.get("Emoji", "")).ljust(widths[6]),
        ]
        row_lines.append("  ".join(vals))

    lines = [header_line, sep_line] + row_lines
    return "\n".join(lines)

def _format_ts_ms(ms: int, tz_name: str = "Europe/Paris") -> str:
    if not ms:
        return "No games"
    tz = pytz.timezone(tz_name)
    dt = datetime.fromtimestamp(ms / 1000, tz)
    return dt.strftime("%d %b - %H:%M")

def get_last_game_time(account: dict, api_key: str) -> str:
    puuid = account.get("puuid")
    region = account.get("region", "europe")
    if not puuid:
        return "No games"
    url_ids = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1"
    resp = requests.get(url_ids, headers={"X-Riot-Token": api_key}, timeout=10)
    resp.raise_for_status()
    ids = resp.json()
    if not ids:
        return "No games"
    match_id = ids[0]
    url_match = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    resp = requests.get(url_match, headers={"X-Riot-Token": api_key}, timeout=10)
    resp.raise_for_status()
    match = resp.json()
    # match['info']['gameStartTimestamp'] is ms since epoch
    ms = match.get("info", {}).get("gameStartTimestamp")
    return _format_ts_ms(ms)

def build_player_rows(players_accounts: dict, global_api_key: str) -> list[dict]:
    """
    players_accounts: structure like PLAYERS_ACCOUNTS
    global_api_key: recommended key for Riot API (you may use account['api_key'] if per-account)
    Returns rows list for format_players_report().
    """
    rows = []
    for player, accounts in players_accounts.items():
        games_24 = 0
        games_7 = 0
        last_game_ts_ms = 0
        acc_elos = []
        main_account = accounts[0].get("account_name", "")
        emoji = "💀"  # or map per-player

        for acc in accounts:
            api_key = global_api_key if global_api_key else acc.get("api_key")
            # counts
            try:
                games_24 += count_soloq(acc, api_key=api_key, days=1)
                games_7 += count_soloq(acc, api_key=api_key, days=7)
            except Exception:
                pass
            # last game: prefer newest timestamp
            try:
                # get last game id and then timestamp (use helper)
                puuid = acc.get("puuid")
                if puuid:
                    url_ids = f"https://{acc.get('region','europe')}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1"
                    r = requests.get(url_ids, headers={"X-Riot-Token": api_key}, timeout=10)
                    r.raise_for_status()
                    ids = r.json()
                    if ids:
                        mid = ids[0]
                        r2 = requests.get(f"https://{acc.get('region','europe')}.api.riotgames.com/lol/match/v5/matches/{mid}", headers={"X-Riot-Token": api_key}, timeout=10)
                        r2.raise_for_status()
                        ms = r2.json().get("info", {}).get("gameStartTimestamp", 0)
                        if ms and ms > last_game_ts_ms:
                            last_game_ts_ms = ms
            except Exception:
                pass

            # elo
            try:
                elo = get_current_elo(acc, api_key=api_key)
                if elo:
                    acc_elos.append(elo)
            except Exception:
                pass

        last_game_str = _format_ts_ms(last_game_ts_ms) if last_game_ts_ms else "No games"
        best_elo = max_elo(acc_elos) if acc_elos else "Unranked"

        rows.append({
            "Player": player,
            "Games24": games_24,
            "Games7": games_7,
            "LastGame": last_game_str,
            "Elo": best_elo,
            "Main": main_account,
            "Emoji": emoji,
        })
    return rows


def build_players_embed(rows: list[dict], title: str = "SoloQ Report"):
    """Build a discord.Embed where each column is an inline field.

    - `rows` is the list produced by `build_player_rows()`.
    - Returns a `discord.Embed` object (imported inside the function).
    """
    # import discord here to keep module lightweight if not used
    import discord

    def _col_join(key: str) -> str:
        return "\n".join(str(r.get(key, "")) for r in rows) or "-"

    def _truncate(s: str, limit: int = 1000) -> str:
        if len(s) <= limit:
            return s
        return s[: limit - 3] + "..."

    embed = discord.Embed(title=title)

    # Prepare column text
    col_player = _truncate(_col_join("Player"))
    col_24 = _truncate(_col_join("Games24"))
    col_7 = _truncate(_col_join("Games7"))
    col_last = _truncate(_col_join("LastGame"))
    col_elo = _truncate(_col_join("Elo"))
    col_main = _truncate(_col_join("Main"))
    col_emoji = _truncate(_col_join("Emoji"))

    # Add fields in two rows of three inline fields to avoid excessive wrapping:
    # Row 1: Player | 24h | 7d
    embed.add_field(name="Player", value=col_player, inline=True)
    embed.add_field(name="24h", value=col_24, inline=True)
    embed.add_field(name="7d", value=col_7, inline=True)

    # Row 2: Last Game | Elo | Main Account
    embed.add_field(name="Last Game", value=col_last, inline=True)
    embed.add_field(name="Elo", value=col_elo, inline=True)
    embed.add_field(name="Main Account", value=col_main, inline=True)

    # Emoji column: place as its own field so it appears below (keeps alignment)
    embed.add_field(name="Reha happy", value=col_emoji or "-", inline=False)

    return embed