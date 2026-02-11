#!/usr/bin/env python3
"""Tipsklub 2025 - Year in Review Dashboard Generator.

Fetches betting data from a public Google Sheet, computes stats,
generates Chart.js visualizations + roast award cards,
and outputs a single standalone HTML file.

Unit of analysis: WEEKS (players take turns betting each week).
"""

import csv
import io
import json
import random
import urllib.request
from datetime import datetime

import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1E_9toayPqOFvC1XrAv31iLHTIlNc_6Z0ZZPw1SKYyMw/"
    "gviz/tq?tqx=out:csv&sheet=Data"
)

PLAYER_COLORS = {
    "Bjørn": "#d97706",
    "Nikolaj": "#2563eb",
    "Nixon": "#16a34a",
    "Jonas": "#9333ea",
    "Gustav": "#dc2626",
}

PLAYER_ORDER = ["Bjørn", "Nikolaj", "Nixon", "Jonas", "Gustav"]

DANISH_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "Maj", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]

DANISH_WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]


# ── 1. Data Fetching & Parsing ──────────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    """Fetch CSV from Google Sheets and parse into DataFrame."""
    print("Fetching data from Google Sheets...")
    req = urllib.request.Request(SHEET_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    header = rows[0]
    data = rows[1:]

    df = pd.DataFrame(data, columns=header)
    df.columns = df.columns.str.strip()
    df = df.loc[:, df.columns != ""]
    df = df.dropna(how="all").reset_index(drop=True)
    df = df[df.iloc[:, 0].astype(str).str.strip() != ""].reset_index(drop=True)

    print(f"  Columns: {list(df.columns)}")
    print(f"  Total rows: {len(df)}")

    for col in ["Indsats", "Gik Hjem", "Odds", "Gevinst", "Profit"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_danish_number)

    if "Dato" in df.columns:
        df["Dato"] = pd.to_datetime(df["Dato"], format="%d/%m/%Y", errors="coerce")

    df = df[df["Dato"].dt.year == 2025].copy()
    df = df.sort_values("Dato").reset_index(drop=True)

    print(f"  2025 rows: {len(df)}")
    print(f"  Players: {sorted(df['Spiller'].unique())}")
    return df


def parse_danish_number(s: str) -> float:
    if not isinstance(s, str) or s.strip() == "":
        return 0.0
    s = s.strip().replace(" ", "").replace("kr", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def aggregate_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate individual bets into weekly results per player."""
    iso = df["Dato"].dt.isocalendar()
    df = df.copy()
    df["ISOWeek"] = iso["week"].astype(int)
    df["ISOYear"] = iso["year"].astype(int)
    df["WeekKey"] = df["ISOYear"].astype(str) + "-W" + df["ISOWeek"].astype(str).str.zfill(2)

    weekly = df.groupby(["WeekKey", "Spiller"]).agg(
        Bets=("Profit", "count"),
        Profit=("Profit", "sum"),
        Staked=("Indsats", "sum"),
        AvgOdds=("Odds", "mean"),
        FirstDate=("Dato", "min"),
    ).reset_index()

    weekly = weekly.sort_values("FirstDate").reset_index(drop=True)
    weekly["Month"] = weekly["FirstDate"].dt.month
    print(f"  Weekly turns: {len(weekly)}")
    return weekly


# ── 2. Stats Computation ────────────────────────────────────────────────────

def compute_player_stats(weekly: pd.DataFrame, df_bets: pd.DataFrame) -> pd.DataFrame:
    stats = []
    for player in PLAYER_ORDER:
        pw = weekly[weekly["Spiller"] == player].copy()
        pb = df_bets[df_bets["Spiller"] == player].copy()
        if pw.empty:
            continue
        winning = pw[pw["Profit"] > 0]
        losing = pw[pw["Profit"] < 0]
        win_streak, loss_streak = compute_streaks(pw)
        stats.append({
            "Spiller": player,
            "Weeks": len(pw),
            "Bets": len(pb),
            "Winning Weeks": len(winning),
            "Losing Weeks": len(losing),
            "Win Rate": len(winning) / len(pw) * 100,
            "Total Staked": pw["Staked"].sum(),
            "Total Profit": pw["Profit"].sum(),
            "ROI": pw["Profit"].sum() / pw["Staked"].sum() * 100,
            "Avg Odds": pb["Odds"].mean(),
            "Best Week": pw["Profit"].max(),
            "Worst Week": pw["Profit"].min(),
            "Win Streak": win_streak,
            "Loss Streak": loss_streak,
        })
    return pd.DataFrame(stats)


def compute_streaks(pw: pd.DataFrame) -> tuple[int, int]:
    max_win = max_loss = cur_win = cur_loss = 0
    for p in pw["Profit"]:
        if p > 0:
            cur_win += 1
            cur_loss = 0
            max_win = max(max_win, cur_win)
        elif p < 0:
            cur_loss += 1
            cur_win = 0
            max_loss = max(max_loss, cur_loss)
        else:
            cur_win = cur_loss = 0
    return max_win, max_loss


# ── 3. Chart Data (JSON for Chart.js) ──────────────────────────────────────

def chart1_cumulative_data(weekly: pd.DataFrame) -> str:
    """Cumulative P/L over time — line chart data."""
    datasets = []
    for player in PLAYER_ORDER:
        pw = weekly[weekly["Spiller"] == player].sort_values("FirstDate")
        if pw.empty:
            continue
        cum = pw["Profit"].cumsum()
        datasets.append({
            "label": player,
            "data": [{"x": d.strftime("%Y-%m-%d"), "y": round(v, 0)}
                     for d, v in zip(pw["FirstDate"], cum)],
            "borderColor": PLAYER_COLORS[player],
            "backgroundColor": PLAYER_COLORS[player],
            "borderWidth": 3,
            "pointRadius": 5,
            "pointHoverRadius": 7,
            "tension": 0.15,
            "fill": False,
        })
    return json.dumps(datasets)


def chart2_leaderboard_data(stats: pd.DataFrame) -> str:
    """Leaderboard — horizontal bar data."""
    sorted_stats = stats.sort_values("Total Profit", ascending=True)
    return json.dumps({
        "labels": sorted_stats["Spiller"].tolist(),
        "data": [round(v, 0) for v in sorted_stats["Total Profit"]],
        "colors": [PLAYER_COLORS[p] for p in sorted_stats["Spiller"]],
    })


def chart3_winrate_data(stats: pd.DataFrame) -> str:
    """Win rate — bar chart data."""
    sorted_stats = stats.sort_values("Win Rate", ascending=False)
    return json.dumps({
        "labels": sorted_stats["Spiller"].tolist(),
        "data": [round(v, 1) for v in sorted_stats["Win Rate"]],
        "colors": [PLAYER_COLORS[p] for p in sorted_stats["Spiller"]],
        "weeks": sorted_stats["Weeks"].tolist(),
        "winning": sorted_stats["Winning Weeks"].tolist(),
    })


def chart4_monthly_data(weekly: pd.DataFrame) -> str:
    """Monthly profit — grouped bar data."""
    months_with_data = sorted(weekly["Month"].unique())
    labels = [DANISH_MONTHS[m - 1] for m in months_with_data]

    datasets = []
    for player in PLAYER_ORDER:
        pw = weekly[weekly["Spiller"] == player]
        monthly = pw.groupby("Month")["Profit"].sum()
        vals = [round(monthly.get(m, 0.0), 0) for m in months_with_data]
        datasets.append({
            "label": player,
            "data": vals,
            "backgroundColor": PLAYER_COLORS[player],
        })
    return json.dumps({"labels": labels, "datasets": datasets})


def chart5_league_data(df_bets: pd.DataFrame) -> str:
    """Bets by league — horizontal bar."""
    df_leagues = df_bets.copy()
    df_leagues["Liga"] = df_leagues["Liga"].fillna("").astype(str)
    df_leagues["Liga"] = df_leagues["Liga"].str.split(",")
    df_leagues = df_leagues.explode("Liga")
    df_leagues["Liga"] = df_leagues["Liga"].str.strip()
    df_leagues = df_leagues[df_leagues["Liga"] != ""]

    league_stats = df_leagues.groupby("Liga").agg(
        Bets=("Profit", "count"),
        Profit=("Profit", "sum"),
    ).reset_index().sort_values("Bets", ascending=True)

    # Top 10 leagues
    league_stats = league_stats.tail(10)

    colors = ["#16a34a" if p >= 0 else "#dc2626" for p in league_stats["Profit"]]

    return json.dumps({
        "labels": league_stats["Liga"].tolist(),
        "bets": league_stats["Bets"].tolist(),
        "profit": [round(v, 0) for v in league_stats["Profit"]],
        "colors": colors,
    })


def chart6_odds_data(df_bets: pd.DataFrame) -> str:
    """Odds per player — scatter + avg bar overlay."""
    datasets = []
    for player in PLAYER_ORDER:
        odds = df_bets[df_bets["Spiller"] == player]["Odds"].tolist()
        datasets.append({
            "player": player,
            "odds": [round(o, 2) for o in odds],
            "avg": round(sum(odds) / len(odds), 2) if odds else 0,
            "min": round(min(odds), 2) if odds else 0,
            "max": round(max(odds), 2) if odds else 0,
            "color": PLAYER_COLORS[player],
        })
    return json.dumps(datasets)


def chart7_weekday_data(df_bets: pd.DataFrame) -> str:
    """Day-of-week bet counts per player."""
    df = df_bets.copy()
    df["Weekday"] = df["Dato"].dt.dayofweek

    matrix = []
    for pi, player in enumerate(PLAYER_ORDER):
        pdf = df[df["Spiller"] == player]
        counts = pdf["Weekday"].value_counts()
        for d in range(7):
            count = int(counts.get(d, 0))
            if count > 0:
                matrix.append({"x": d, "y": pi, "v": count})
    return json.dumps({
        "data": matrix,
        "players": PLAYER_ORDER,
        "days": DANISH_WEEKDAYS,
    })


def chart8_best_worst_data(weekly: pd.DataFrame) -> str:
    """Best & worst weeks — horizontal bar."""
    top = weekly.nlargest(5, "Profit")
    bottom = weekly.nsmallest(5, "Profit")
    combined = pd.concat([bottom, top]).reset_index(drop=True)

    return json.dumps({
        "labels": [f"{r['Spiller']} ({r['FirstDate'].strftime('%d/%m')})"
                   for _, r in combined.iterrows()],
        "data": [round(r["Profit"], 0) for _, r in combined.iterrows()],
        "colors": [PLAYER_COLORS[r["Spiller"]] for _, r in combined.iterrows()],
    })


# ── 4. Award Cards ──────────────────────────────────────────────────────────

def generate_award_cards(stats: pd.DataFrame, weekly: pd.DataFrame) -> str:
    awards = []

    best = stats.loc[stats["Total Profit"].idxmax()]
    awards.append(card("💰", "Årets Pengemaskine", best["Spiller"],
                       f'+{best["Total Profit"]:,.0f} kr profit',
                       "Pengene printer bare. Resten kan lære noget."))

    worst = stats.loc[stats["Total Profit"].idxmin()]
    awards.append(card("🪦", "Bundskraberen", worst["Spiller"],
                       f'{worst["Total Profit"]:,.0f} kr profit',
                       "Nogen skal jo finansiere de andres gevinster."))

    streak_best = stats.loc[stats["Win Streak"].idxmax()]
    awards.append(card("🔥", "Den Vilde Stribe", streak_best["Spiller"],
                       f'{streak_best["Win Streak"]:.0f} vindende uger i træk',
                       "Uhyggeligt. Ringede bookmakerne?"))

    odds_high = stats.loc[stats["Avg Odds"].idxmax()]
    awards.append(card("🎰", "Odds-Junkie", odds_high["Spiller"],
                       f'Gns. odds: {odds_high["Avg Odds"]:.2f}',
                       "Go big or go home. Mest go home."))

    odds_low = stats.loc[stats["Avg Odds"].idxmin()]
    awards.append(card("🐌", "Sikansen", odds_low["Spiller"],
                       f'Gns. odds: {odds_low["Avg Odds"]:.2f}',
                       "Spænding? Nej tak. Sikkerhed først."))

    roi_best = stats.loc[stats["ROI"].idxmax()]
    awards.append(card("📈", "ROI-Kongen", roi_best["Spiller"],
                       f'{roi_best["ROI"]:+.1f}% afkast',
                       "Krone for krone den bedste investering."))

    best_week = weekly.loc[weekly["Profit"].idxmax()]
    awards.append(card("🎯", "Ugens Helt", best_week["Spiller"],
                       f'+{best_week["Profit"]:,.0f} kr på én uge',
                       f'Uge {best_week["WeekKey"]} var magisk.'))

    worst_week = weekly.loc[weekly["Profit"].idxmin()]
    awards.append(card("💀", "Sorteper", worst_week["Spiller"],
                       f'{worst_week["Profit"]:,.0f} kr på én uge',
                       f'Uge {worst_week["WeekKey"]} var brutal.'))

    return "\n".join(awards)


def card(emoji: str, title: str, player: str, stat: str, subtitle: str) -> str:
    color = PLAYER_COLORS[player]
    return f"""<div class="award-card" style="border-top: 3px solid {color};">
        <div class="award-emoji">{emoji}</div>
        <div class="award-title">{title}</div>
        <div class="award-player" style="color: {color};">{player}</div>
        <div class="award-stat">{stat}</div>
        <div class="award-subtitle">{subtitle}</div>
    </div>"""


# ── 5. Quiz Generation ─────────────────────────────────────────────────────

def generate_quiz_questions(stats: pd.DataFrame, weekly: pd.DataFrame,
                            df_bets: pd.DataFrame, chart_data: dict) -> str:
    """Build JSON quiz questions from computed stats. Each question has
    question text, 4 options, correct index, and chart config for reveal."""
    questions = []

    # Helper: shuffle options, return (options_list, correct_index)
    def make_options(correct: str, wrong: list[str]) -> tuple[list[str], int]:
        opts = [correct] + wrong
        random.shuffle(opts)
        return opts, opts.index(correct)

    # Q1: Most profit
    best = stats.loc[stats["Total Profit"].idxmax()]
    others = [p for p in PLAYER_ORDER if p != best["Spiller"]]
    random.shuffle(others)
    opts, ci = make_options(best["Spiller"], others)
    questions.append({
        "question": "Hvem endte med mest profit i 2025?",
        "options": opts, "correct": ci,
        "reveal": f'{best["Spiller"]} med {best["Total Profit"]:+,.0f} kr',
        "chartId": "leaderboard",
    })

    # Q2: Highest win rate
    wr_best = stats.loc[stats["Win Rate"].idxmax()]
    others = [p for p in PLAYER_ORDER if p != wr_best["Spiller"]]
    random.shuffle(others)
    opts, ci = make_options(wr_best["Spiller"], others)
    questions.append({
        "question": "Hvem havde den højeste win rate (vindende uger)?",
        "options": opts, "correct": ci,
        "reveal": f'{wr_best["Spiller"]} med {wr_best["Win Rate"]:.1f}%',
        "chartId": "winrate",
    })

    # Q3: Highest average odds
    odds_high = stats.loc[stats["Avg Odds"].idxmax()]
    others = [p for p in PLAYER_ORDER if p != odds_high["Spiller"]]
    random.shuffle(others)
    opts, ci = make_options(odds_high["Spiller"], others)
    questions.append({
        "question": "Hvem havde de højeste gennemsnitlige odds?",
        "options": opts, "correct": ci,
        "reveal": f'{odds_high["Spiller"]} med gns. odds {odds_high["Avg Odds"]:.2f}',
        "chartId": "odds",
    })

    # Q4: Total club profit (numeric range options)
    club_profit = round(stats["Total Profit"].sum(), 0)
    correct_str = f'{club_profit:+,.0f} kr'
    # Generate plausible wrong answers
    offsets = [-2000, -800, +1500]
    random.shuffle(offsets)
    wrong = [f'{club_profit + o:+,.0f} kr' for o in offsets[:3]]
    opts, ci = make_options(correct_str, wrong)
    questions.append({
        "question": "Hvad var klubbens samlede profit i 2025?",
        "options": opts, "correct": ci,
        "reveal": f'Klubben endte på {correct_str}',
        "chartId": "quickstats",
    })

    # Q5: Best month for the club
    monthly = weekly.copy()
    month_totals = monthly.groupby("Month")["Profit"].sum()
    best_month_num = int(month_totals.idxmax())
    best_month_name = DANISH_MONTHS[best_month_num - 1]
    all_months = [DANISH_MONTHS[int(m) - 1] for m in month_totals.index]
    other_months = [m for m in all_months if m != best_month_name]
    random.shuffle(other_months)
    opts, ci = make_options(best_month_name, other_months[:3])
    questions.append({
        "question": "Hvilken måned var bedst for klubben?",
        "options": opts, "correct": ci,
        "reveal": f'{best_month_name} med {month_totals.max():+,.0f} kr profit',
        "chartId": "monthly",
    })

    # Q6: Most bet-on league
    df_leagues = df_bets.copy()
    df_leagues["Liga"] = df_leagues["Liga"].fillna("").astype(str).str.split(",")
    df_leagues = df_leagues.explode("Liga")
    df_leagues["Liga"] = df_leagues["Liga"].str.strip()
    df_leagues = df_leagues[df_leagues["Liga"] != ""]
    league_counts = df_leagues["Liga"].value_counts()
    top_league = league_counts.index[0]
    other_leagues = list(league_counts.index[1:4])
    opts, ci = make_options(top_league, other_leagues)
    questions.append({
        "question": "Hvilken liga spillede vi mest på?",
        "options": opts, "correct": ci,
        "reveal": f'{top_league} med {league_counts.iloc[0]} bets',
        "chartId": "leagues",
    })

    # Q7: Best single week
    best_week_row = weekly.loc[weekly["Profit"].idxmax()]
    best_week_player = best_week_row["Spiller"]
    others = [p for p in PLAYER_ORDER if p != best_week_player]
    random.shuffle(others)
    opts, ci = make_options(best_week_player, others)
    questions.append({
        "question": "Hvem havde den bedste enkeluge?",
        "options": opts, "correct": ci,
        "reveal": f'{best_week_player} med {best_week_row["Profit"]:+,.0f} kr',
        "chartId": "bigweeks",
    })

    # Q8: Longest winning streak
    streak_best = stats.loc[stats["Win Streak"].idxmax()]
    others = [p for p in PLAYER_ORDER if p != streak_best["Spiller"]]
    random.shuffle(others)
    opts, ci = make_options(streak_best["Spiller"], others)
    questions.append({
        "question": "Hvem havde den længste vindende stribe?",
        "options": opts, "correct": ci,
        "reveal": f'{streak_best["Spiller"]} med {streak_best["Win Streak"]:.0f} uger i træk',
        "chartId": "cumulative",
    })

    return json.dumps(questions, ensure_ascii=False)


def generate_quiz_html(quiz_json: str, chart_data: dict,
                       stats: pd.DataFrame, weekly: pd.DataFrame,
                       df_bets: pd.DataFrame) -> str:
    """Build a standalone quiz HTML file with PeerJS for multiplayer."""
    total_weeks = len(weekly)
    total_bets = len(df_bets)
    total_staked = df_bets["Indsats"].sum()
    club_profit = df_bets["Profit"].sum()

    # Quick stats for Q4 reveal
    quick_stats_json = json.dumps({
        "weeks": int(total_weeks),
        "bets": int(total_bets),
        "staked": round(total_staked, 0),
        "profit": round(club_profit, 0),
    })

    return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Tipsklub 2025 - Quiz</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script src="https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
*{{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: #0f172a;
    color: #f1f5f9;
    font-family: 'Inter', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    min-height: 100dvh;
    overflow-x: hidden;
}}
.screen {{ display:none; min-height:100dvh; padding:20px; }}
.screen.active {{ display:flex; flex-direction:column; align-items:center; justify-content:center; }}

/* Landing */
.landing-title {{ font-size:2rem; font-weight:900; text-align:center; margin-bottom:8px; }}
.landing-sub {{ color:#94a3b8; text-align:center; margin-bottom:32px; }}
.btn {{ display:block; width:100%; max-width:320px; padding:16px; border:none; border-radius:12px;
        font-family:inherit; font-size:1.1rem; font-weight:700; cursor:pointer;
        transition:transform .1s, opacity .1s; margin:6px auto; }}
.btn:active {{ transform:scale(0.97); opacity:.9; }}
.btn-host {{ background:#2563eb; color:#fff; }}
.btn-join {{ background:#16a34a; color:#fff; }}
.btn-reveal {{ background:#d97706; color:#fff; }}
.btn-next {{ background:#2563eb; color:#fff; }}
.btn-disabled {{ background:#334155; color:#64748b; pointer-events:none; }}

/* Host lobby */
.room-code {{ font-size:3rem; font-weight:900; letter-spacing:.3em; color:#2563eb;
              background:#1e293b; border-radius:16px; padding:16px 32px; margin:16px 0; text-align:center; }}
#qrCanvas {{ margin:12px auto; display:block; border-radius:12px; background:#fff; padding:8px; }}
.player-list {{ width:100%; max-width:320px; margin:16px 0; }}
.player-chip {{ background:#1e293b; border-radius:8px; padding:10px 16px; margin:4px 0;
                font-weight:600; display:flex; align-items:center; gap:8px; }}
.player-dot {{ width:10px; height:10px; border-radius:50%; }}

/* Join */
.input {{ width:100%; max-width:320px; padding:14px 16px; border:2px solid #334155; border-radius:12px;
          background:#1e293b; color:#f1f5f9; font-family:inherit; font-size:1rem; font-weight:600;
          text-align:center; margin:6px auto; display:block; }}
.input::placeholder {{ color:#64748b; }}
.input:focus {{ outline:none; border-color:#2563eb; }}
.input.code {{ font-size:1.8rem; letter-spacing:.3em; text-transform:uppercase; }}
.waiting {{ color:#94a3b8; font-size:1rem; margin-top:16px; }}
.waiting .dot {{ animation:blink 1.4s infinite; }}
@keyframes blink {{ 0%,100%{{ opacity:.2; }} 50%{{ opacity:1; }} }}

/* Question (Host) */
.q-num {{ font-size:.8rem; color:#64748b; text-transform:uppercase; letter-spacing:.1em; margin-bottom:8px; }}
.q-text {{ font-size:1.3rem; font-weight:700; text-align:center; margin-bottom:24px; line-height:1.4; }}
.host-options {{ width:100%; max-width:400px; }}
.host-opt {{ background:#1e293b; border-radius:10px; padding:12px 16px; margin:6px 0;
             display:flex; justify-content:space-between; align-items:center; font-weight:600; }}
.host-opt .count {{ background:#334155; border-radius:6px; padding:4px 10px; font-size:.9rem; min-width:30px; text-align:center; }}
.host-opt.correct {{ background:#16a34a33; border:2px solid #16a34a; }}
.host-opt.wrong {{ background:#dc262633; border:2px solid #dc2626; opacity:.6; }}
.vote-names {{ font-size:.7rem; color:#94a3b8; margin-top:4px; }}

/* Question (Player) */
.answer-btn {{ display:block; width:100%; max-width:400px; padding:18px 16px; margin:6px auto;
               border:2px solid #334155; border-radius:12px; background:#1e293b; color:#f1f5f9;
               font-family:inherit; font-size:1rem; font-weight:600; cursor:pointer;
               transition:transform .1s, border-color .15s; }}
.answer-btn:active {{ transform:scale(0.97); }}
.answer-btn.selected {{ border-color:#2563eb; background:#2563eb22; }}
.answer-btn.correct-pick {{ border-color:#16a34a; background:#16a34a33; }}
.answer-btn.wrong-pick {{ border-color:#dc2626; background:#dc262633; }}
.answer-btn:disabled {{ cursor:default; opacity:.7; }}

/* Feedback */
.feedback {{ font-size:1.5rem; font-weight:900; text-align:center; margin:16px 0; }}
.feedback.right {{ color:#16a34a; }}
.feedback.wrong {{ color:#dc2626; }}
.score-display {{ color:#94a3b8; font-size:1rem; text-align:center; }}

/* Chart reveal */
.chart-container {{ width:100%; max-width:500px; background:#fff; border-radius:12px;
                    padding:16px; margin:16px 0; }}
.chart-container canvas {{ width:100%!important; }}
.reveal-text {{ font-size:1rem; font-weight:600; color:#94a3b8; text-align:center; margin:8px 0; }}

/* Quick stats reveal */
.qs-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; width:100%; max-width:400px; margin:16px 0; }}
.qs-item {{ background:#1e293b; border-radius:12px; padding:16px; text-align:center; }}
.qs-item .val {{ font-size:1.4rem; font-weight:700; color:#2563eb; }}
.qs-item .lbl {{ font-size:.7rem; color:#64748b; text-transform:uppercase; margin-top:4px; }}

/* Scoreboard */
.scoreboard {{ width:100%; max-width:400px; margin:16px 0; }}
.sb-row {{ display:flex; align-items:center; padding:14px 16px; margin:4px 0;
           background:#1e293b; border-radius:10px; }}
.sb-rank {{ font-size:1.5rem; font-weight:900; width:36px; text-align:center; }}
.sb-rank.gold {{ color:#fbbf24; }}
.sb-rank.silver {{ color:#94a3b8; }}
.sb-rank.bronze {{ color:#cd7f32; }}
.sb-name {{ flex:1; font-weight:700; font-size:1.1rem; margin-left:12px; }}
.sb-score {{ font-weight:700; font-size:1.1rem; color:#2563eb; }}
.sb-correct {{ font-size:.75rem; color:#64748b; margin-left:4px; }}

/* Status bar */
.status-bar {{ position:fixed; top:0; left:0; right:0; background:#1e293b; border-bottom:1px solid #334155;
               padding:8px 16px; display:flex; justify-content:space-between; align-items:center;
               font-size:.75rem; color:#94a3b8; z-index:100; }}
.status-bar .room {{ font-weight:700; color:#2563eb; }}

/* Error */
.error {{ color:#dc2626; font-size:.85rem; text-align:center; margin:8px 0; }}

@media(max-width:400px) {{
    .landing-title {{ font-size:1.5rem; }}
    .q-text {{ font-size:1.1rem; }}
    .room-code {{ font-size:2.2rem; padding:12px 20px; }}
}}
</style>
</head>
<body>

<!-- Screen: Landing -->
<div id="screenLanding" class="screen active">
    <div class="landing-title">Tipsklub 2025</div>
    <div class="landing-sub">Interaktiv Quiz</div>
    <button class="btn btn-host" onclick="startHost()">Vaert (Host)</button>
    <button class="btn btn-join" onclick="showJoin()">Deltag (Join)</button>
</div>

<!-- Screen: Host Lobby -->
<div id="screenHostLobby" class="screen">
    <div class="q-num">Del denne kode</div>
    <div class="room-code" id="roomCodeDisplay"></div>
    <canvas id="qrCanvas" width="180" height="180"></canvas>
    <div class="q-num" style="margin-top:12px;">Spillere</div>
    <div class="player-list" id="playerList"></div>
    <button class="btn btn-host" id="btnStartQuiz" onclick="hostStartQuiz()">Start Quiz</button>
</div>

<!-- Screen: Join -->
<div id="screenJoin" class="screen">
    <div class="q-text">Indtast kode</div>
    <input class="input code" id="inputCode" maxlength="4" placeholder="ABCD" autocomplete="off" autocapitalize="characters">
    <input class="input" id="inputName" placeholder="Dit navn" autocomplete="off">
    <button class="btn btn-join" onclick="joinRoom()">Tilslut</button>
    <div class="error" id="joinError"></div>
</div>

<!-- Screen: Player Waiting -->
<div id="screenPlayerWait" class="screen">
    <div class="q-text">Du er med!</div>
    <div class="waiting">Venter på at quizzen starter<span class="dot">...</span></div>
</div>

<!-- Screen: Host Question -->
<div id="screenHostQ" class="screen">
    <div class="status-bar">
        <span>Kode: <span class="room" id="statusRoom"></span></span>
        <span id="statusQ"></span>
    </div>
    <div style="margin-top:48px;width:100%;max-width:500px;">
        <div class="q-num" id="hostQNum"></div>
        <div class="q-text" id="hostQText"></div>
        <div class="host-options" id="hostOptions"></div>
        <div style="text-align:center;margin-top:12px;color:#64748b;font-size:.85rem;" id="hostVoteCount"></div>
        <button class="btn btn-reveal" id="btnReveal" onclick="hostReveal()" style="margin-top:16px;">Vis Svar</button>
    </div>
</div>

<!-- Screen: Host Reveal -->
<div id="screenHostReveal" class="screen">
    <div class="status-bar">
        <span>Kode: <span class="room" id="statusRoom2"></span></span>
        <span id="statusQ2"></span>
    </div>
    <div style="margin-top:48px;width:100%;max-width:500px;display:flex;flex-direction:column;align-items:center;">
        <div class="reveal-text" id="revealText"></div>
        <div class="chart-container" id="chartRevealContainer">
            <canvas id="chartReveal" height="200"></canvas>
        </div>
        <div class="qs-grid" id="quickStatsReveal" style="display:none;"></div>
        <button class="btn btn-next" id="btnNext" onclick="hostNextQuestion()" style="margin-top:16px;">Naeste Spørgsmål</button>
    </div>
</div>

<!-- Screen: Player Question -->
<div id="screenPlayerQ" class="screen">
    <div style="width:100%;max-width:400px;">
        <div class="q-num" id="playerQNum"></div>
        <div class="q-text" id="playerQText"></div>
        <div id="playerOptions"></div>
    </div>
</div>

<!-- Screen: Player Feedback -->
<div id="screenPlayerFeedback" class="screen">
    <div class="feedback" id="playerFeedback"></div>
    <div class="score-display" id="playerScore"></div>
    <div class="waiting" style="margin-top:24px;">Venter på naeste spørgsmål<span class="dot">...</span></div>
</div>

<!-- Screen: Final Scoreboard -->
<div id="screenScoreboard" class="screen">
    <div class="landing-title" style="margin-bottom:24px;">Resultater</div>
    <div class="scoreboard" id="scoreboard"></div>
    <button class="btn btn-host" onclick="location.reload()" style="margin-top:24px;">Spil Igen</button>
</div>

<script>
// ── Data (embedded at build time) ──
const QUESTIONS = {quiz_json};
const CHART_DATA = {{
    cumulative: {chart_data['cumulative']},
    leaderboard: {chart_data['leaderboard']},
    winrate: {chart_data['winrate']},
    monthly: {chart_data['monthly']},
    leagues: {chart_data['leagues']},
    odds: {chart_data['odds']},
    bigweeks: {chart_data['bigweeks']},
}};
const QUICK_STATS = {quick_stats_json};
const PLAYER_COLORS = {json.dumps(PLAYER_COLORS)};

// ── QR Code ──
function drawQR(canvas, text) {{
    const qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    const modules = qr.getModuleCount();
    const cellSize = Math.floor(180 / modules);
    const size = cellSize * modules;
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);
    for (let r = 0; r < modules; r++) {{
        for (let c = 0; c < modules; c++) {{
            ctx.fillStyle = qr.isDark(r, c) ? '#1e293b' : '#fff';
            ctx.fillRect(c * cellSize, r * cellSize, cellSize, cellSize);
        }}
    }}
}}

// ── State ──
let mode = ''; // 'host' or 'player'
let peer = null;
let connections = []; // host: array of DataConnection
let hostConn = null; // player: DataConnection to host
let roomCode = '';
let players = {{}}; // host: {{connId: {{name, score, answered, correct_count}}}}
let currentQ = 0;
let votes = {{}}; // host: {{optionIndex: [playerNames]}}
let myAnswer = -1;
let myScore = 0;
let myCorrectCount = 0;
let answerOrder = []; // host: tracks order of correct answers for speed bonus
let revealChart = null;

// ── Screen management ──
function showScreen(id) {{
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}}

// ── ICE config (STUN for same-network WebRTC) ──
const ICE_CONFIG = {{
    iceServers: [
        {{ urls: 'stun:stun.l.google.com:19302' }},
        {{ urls: 'stun:stun1.l.google.com:19302' }},
    ]
}};

// ── HOST ──
function startHost() {{
    mode = 'host';
    roomCode = genCode();
    document.getElementById('roomCodeDisplay').textContent = roomCode;
    const peerId = 'tipsklub-' + roomCode.toLowerCase();

    peer = new Peer(peerId, {{ debug: 2, config: ICE_CONFIG }});
    peer.on('open', (id) => {{
        console.log('Host peer open:', id);
        const url = location.href.split('?')[0] + '?room=' + roomCode;
        drawQR(document.getElementById('qrCanvas'), url);
        showScreen('screenHostLobby');
    }});
    peer.on('error', (err) => {{
        console.error('Host peer error:', err.type, err);
        if (err.type === 'unavailable-id') {{
            roomCode = genCode();
            document.getElementById('roomCodeDisplay').textContent = roomCode;
            peer.destroy();
            startHost();
        }}
    }});
    peer.on('connection', (conn) => {{
        conn.on('open', () => {{
            connections.push(conn);
            conn.on('data', (data) => handleHostMessage(conn, data));
            conn.on('close', () => {{
                connections = connections.filter(c => c !== conn);
                delete players[conn.connectionId];
                updatePlayerList();
            }});
        }});
    }});
}}

function genCode() {{
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
    let code = '';
    for (let i = 0; i < 4; i++) code += chars[Math.floor(Math.random() * chars.length)];
    return code;
}}

function handleHostMessage(conn, data) {{
    if (data.type === 'join') {{
        players[conn.connectionId] = {{ name: data.name, score: 0, answered: false, correct_count: 0 }};
        updatePlayerList();
        conn.send({{ type: 'joined', name: data.name }});
    }}
    if (data.type === 'answer') {{
        const p = players[conn.connectionId];
        if (!p || p.answered) return;
        p.answered = true;
        const optIdx = data.option;
        if (!votes[optIdx]) votes[optIdx] = [];
        votes[optIdx].push(p.name);

        // Track correct answer order for speed bonus
        const q = QUESTIONS[currentQ];
        if (optIdx === q.correct) {{
            answerOrder.push(conn.connectionId);
        }}

        updateHostVotes();
    }}
}}

function updatePlayerList() {{
    const list = document.getElementById('playerList');
    const names = Object.values(players).map(p => p.name);
    list.innerHTML = names.map(n => {{
        const color = PLAYER_COLORS[n] || '#2563eb';
        return `<div class="player-chip"><div class="player-dot" style="background:${{color}}"></div>${{n}}</div>`;
    }}).join('');
}}

function updateHostVotes() {{
    const q = QUESTIONS[currentQ];
    const totalPlayers = Object.keys(players).length;
    const totalVotes = Object.values(votes).reduce((s, arr) => s + arr.length, 0);

    q.options.forEach((opt, i) => {{
        const count = (votes[i] || []).length;
        const el = document.getElementById('hostOpt' + i);
        if (el) {{
            el.querySelector('.count').textContent = count;
        }}
    }});
    document.getElementById('hostVoteCount').textContent = totalVotes + ' / ' + totalPlayers + ' har svaret';
}}

function hostStartQuiz() {{
    currentQ = 0;
    hostSendQuestion();
}}

function hostSendQuestion() {{
    const q = QUESTIONS[currentQ];
    votes = {{}};
    answerOrder = [];
    Object.values(players).forEach(p => p.answered = false);

    // Update host screen
    document.getElementById('statusRoom').textContent = roomCode;
    document.getElementById('statusQ').textContent = (currentQ + 1) + ' / ' + QUESTIONS.length;
    document.getElementById('hostQNum').textContent = 'Spørgsmål ' + (currentQ + 1) + ' af ' + QUESTIONS.length;
    document.getElementById('hostQText').textContent = q.question;

    let optsHtml = '';
    q.options.forEach((opt, i) => {{
        optsHtml += `<div class="host-opt" id="hostOpt${{i}}"><span>${{opt}}</span><span class="count">0</span></div>`;
    }});
    document.getElementById('hostOptions').innerHTML = optsHtml;
    document.getElementById('hostVoteCount').textContent = '0 / ' + Object.keys(players).length + ' har svaret';
    document.getElementById('btnReveal').classList.remove('btn-disabled');

    showScreen('screenHostQ');

    // Send to players
    const msg = {{ type: 'question', index: currentQ, question: q.question, options: q.options }};
    connections.forEach(c => c.send(msg));
}}

function hostReveal() {{
    const q = QUESTIONS[currentQ];
    document.getElementById('btnReveal').classList.add('btn-disabled');

    // Highlight correct/wrong on host options
    q.options.forEach((opt, i) => {{
        const el = document.getElementById('hostOpt' + i);
        if (i === q.correct) {{
            el.classList.add('correct');
            const names = votes[i] || [];
            if (names.length > 0) {{
                el.innerHTML += `<div class="vote-names">${{names.join(', ')}}</div>`;
            }}
        }} else {{
            el.classList.add('wrong');
        }}
    }});

    // Calculate scores
    Object.entries(players).forEach(([connId, p]) => {{
        // Find which option this player voted for
        let playerVote = -1;
        Object.entries(votes).forEach(([optIdx, names]) => {{
            if (names.includes(p.name)) playerVote = parseInt(optIdx);
        }});
        if (playerVote === q.correct) {{
            p.score += 100;
            p.correct_count += 1;
            // Speed bonus: first correct answer
            if (answerOrder.length > 0 && answerOrder[0] === connId) {{
                p.score += 50;
            }}
        }}
    }});

    // Send reveal to players
    const scores = {{}};
    Object.values(players).forEach(p => {{ scores[p.name] = p.score; }});
    const msg = {{ type: 'reveal', correct: q.correct, reveal: q.reveal, scores }};
    connections.forEach(c => c.send(msg));

    // Show reveal screen with chart after a short delay
    setTimeout(() => {{
        showRevealScreen(q);
    }}, 1500);
}}

function showRevealScreen(q) {{
    document.getElementById('statusRoom2').textContent = roomCode;
    document.getElementById('statusQ2').textContent = (currentQ + 1) + ' / ' + QUESTIONS.length;
    document.getElementById('revealText').textContent = q.reveal;

    const chartContainer = document.getElementById('chartRevealContainer');
    const qsContainer = document.getElementById('quickStatsReveal');

    // Destroy previous chart
    if (revealChart) {{ revealChart.destroy(); revealChart = null; }}

    if (q.chartId === 'quickstats') {{
        chartContainer.style.display = 'none';
        qsContainer.style.display = 'grid';
        const qs = QUICK_STATS;
        const profitColor = qs.profit >= 0 ? '#16a34a' : '#dc2626';
        qsContainer.innerHTML = `
            <div class="qs-item"><div class="val">${{qs.weeks}}</div><div class="lbl">Uger spillet</div></div>
            <div class="qs-item"><div class="val">${{qs.bets}}</div><div class="lbl">Bets i alt</div></div>
            <div class="qs-item"><div class="val">${{qs.staked.toLocaleString('da-DK')}}</div><div class="lbl">Satset (kr)</div></div>
            <div class="qs-item"><div class="val" style="color:${{profitColor}}">${{qs.profit >= 0 ? '+' : ''}}${{qs.profit.toLocaleString('da-DK')}}</div><div class="lbl">Klub Profit</div></div>
        `;
    }} else {{
        chartContainer.style.display = 'block';
        qsContainer.style.display = 'none';

        // Replace canvas (Chart.js reuse quirk)
        const oldCanvas = document.getElementById('chartReveal');
        const newCanvas = document.createElement('canvas');
        newCanvas.id = 'chartReveal';
        newCanvas.height = 200;
        oldCanvas.parentNode.replaceChild(newCanvas, oldCanvas);

        revealChart = renderChart(newCanvas, q.chartId);
    }}

    // Button text
    const btnNext = document.getElementById('btnNext');
    if (currentQ >= QUESTIONS.length - 1) {{
        btnNext.textContent = 'Vis Scoreboard';
    }} else {{
        btnNext.textContent = 'Naeste Spørgsmål';
    }}

    showScreen('screenHostReveal');
}}

function renderChart(canvas, chartId) {{
    const ctx = canvas;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.color = '#475569';

    if (chartId === 'leaderboard') {{
        const d = CHART_DATA.leaderboard;
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels: d.labels, datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}] }},
            options: {{ indexAxis:'y', responsive:true,
                plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ label: c => c.parsed.x.toLocaleString('da-DK')+' kr' }} }} }},
                scales:{{ x:{{ grid:{{ color:'#f1f5f9' }}, ticks:{{ callback: v=>v+' kr' }} }}, y:{{ grid:{{ display:false }} }} }}
            }}
        }});
    }}
    if (chartId === 'winrate') {{
        const d = CHART_DATA.winrate;
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels: d.labels, datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}] }},
            options: {{ responsive:true,
                plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ label: (c) => {{
                    const idx=c.dataIndex; return c.parsed.y+'% ('+d.winning[idx]+'/'+d.weeks[idx]+' uger)';
                }} }} }} }},
                scales:{{ y:{{ max:100, grid:{{ color:'#f1f5f9' }}, ticks:{{ callback: v=>v+'%' }} }}, x:{{ grid:{{ display:false }} }} }}
            }}
        }});
    }}
    if (chartId === 'odds') {{
        const d = CHART_DATA.odds;
        const labels = d.map(p=>p.player);
        const avgs = d.map(p=>p.avg);
        const colors = d.map(p=>p.color);
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels, datasets: [{{ label:'Gns.', data:avgs, backgroundColor:colors, borderRadius:4 }}] }},
            options: {{ responsive:true,
                scales:{{ y:{{ grid:{{ color:'#f1f5f9' }}, title:{{ display:true, text:'Odds' }} }}, x:{{ grid:{{ display:false }} }} }},
                plugins:{{ legend:{{ display:false }} }}
            }}
        }});
    }}
    if (chartId === 'monthly') {{
        const d = CHART_DATA.monthly;
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels: d.labels, datasets: d.datasets.map(ds => ({{ ...ds, borderRadius: 2 }})) }},
            options: {{ responsive:true,
                plugins:{{ tooltip:{{ callbacks:{{ label: c => c.dataset.label+': '+c.parsed.y.toLocaleString('da-DK')+' kr' }} }} }},
                scales:{{ y:{{ grid:{{ color:'#f1f5f9' }}, ticks:{{ callback: v=>v+' kr' }} }}, x:{{ grid:{{ display:false }} }} }}
            }}
        }});
    }}
    if (chartId === 'leagues') {{
        const d = CHART_DATA.leagues;
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels: d.labels, datasets: [{{ data: d.bets, backgroundColor: d.colors, borderRadius: 4 }}] }},
            options: {{ indexAxis:'y', responsive:true,
                plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ label: c => {{
                    const idx=c.dataIndex; return c.parsed.x+' bets | '+d.profit[idx].toLocaleString('da-DK')+' kr profit';
                }} }} }} }},
                scales:{{ x:{{ grid:{{ color:'#f1f5f9' }}, title:{{ display:true, text:'Antal bets' }} }}, y:{{ grid:{{ display:false }} }} }}
            }}
        }});
    }}
    if (chartId === 'bigweeks') {{
        const d = CHART_DATA.bigweeks;
        return new Chart(ctx, {{
            type: 'bar',
            data: {{ labels: d.labels, datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}] }},
            options: {{ indexAxis:'y', responsive:true,
                plugins:{{ legend:{{ display:false }}, tooltip:{{ callbacks:{{ label: c => c.parsed.x.toLocaleString('da-DK')+' kr' }} }} }},
                scales:{{ x:{{ grid:{{ color:'#f1f5f9' }}, ticks:{{ callback: v=>v+' kr' }} }}, y:{{ grid:{{ display:false }} }} }}
            }}
        }});
    }}
    if (chartId === 'cumulative') {{
        const datasets = CHART_DATA.cumulative;
        return new Chart(ctx, {{
            type: 'line',
            data: {{ datasets }},
            options: {{ responsive:true, interaction:{{ mode:'index', intersect:false }},
                scales: {{
                    x: {{ type:'time', time:{{ unit:'month', displayFormats:{{ month:'MMM' }} }}, grid:{{ color:'#f1f5f9' }} }},
                    y: {{ grid:{{ color:'#f1f5f9' }}, ticks:{{ callback: v=>v+' kr' }} }}
                }},
                plugins:{{ tooltip:{{ callbacks:{{ label: c => c.dataset.label+': '+c.parsed.y.toLocaleString('da-DK')+' kr' }} }} }}
            }}
        }});
    }}
    return null;
}}

function hostNextQuestion() {{
    currentQ++;
    if (currentQ >= QUESTIONS.length) {{
        showFinalScoreboard();
    }} else {{
        hostSendQuestion();
    }}
}}

function showFinalScoreboard() {{
    const sorted = Object.values(players).sort((a, b) => b.score - a.score);
    const rankIcons = ['gold', 'silver', 'bronze'];
    const rankEmoji = ['1', '2', '3'];

    let html = '';
    sorted.forEach((p, i) => {{
        const rankClass = i < 3 ? rankIcons[i] : '';
        const rank = i < 3 ? rankEmoji[i] : (i + 1);
        const color = PLAYER_COLORS[p.name] || '#2563eb';
        html += `<div class="sb-row">
            <div class="sb-rank ${{rankClass}}">${{rank}}</div>
            <div class="sb-name" style="color:${{color}}">${{p.name}}</div>
            <div><span class="sb-score">${{p.score}} pts</span><span class="sb-correct">${{p.correct_count}}/${{QUESTIONS.length}}</span></div>
        </div>`;
    }});
    document.getElementById('scoreboard').innerHTML = html;

    // Send to players
    const scoresArr = sorted.map(p => ({{ name: p.name, score: p.score, correct: p.correct_count }}));
    connections.forEach(c => c.send({{ type: 'scoreboard', scores: scoresArr }}));

    showScreen('screenScoreboard');
}}

// ── PLAYER ──
function showJoin() {{
    // Check URL params for pre-filled room code
    const params = new URLSearchParams(location.search);
    const urlRoom = params.get('room');
    if (urlRoom) {{
        document.getElementById('inputCode').value = urlRoom.toUpperCase();
    }}
    showScreen('screenJoin');
}}

function joinRoom() {{
    const code = document.getElementById('inputCode').value.trim().toUpperCase();
    const name = document.getElementById('inputName').value.trim();
    const errEl = document.getElementById('joinError');

    if (!code || code.length !== 4) {{ errEl.textContent = 'Indtast en 4-bogstavs kode'; return; }}
    if (!name) {{ errEl.textContent = 'Indtast dit navn'; return; }}
    errEl.textContent = '';

    mode = 'player';
    roomCode = code;
    const peerId = 'tipsklub-' + code.toLowerCase();

    errEl.textContent = '';
    errEl.style.color = '#94a3b8';
    errEl.textContent = 'Forbinder...';

    peer = new Peer({{ debug: 2, config: ICE_CONFIG }});
    peer.on('open', (myId) => {{
        console.log('Player peer open:', myId, '-> connecting to:', peerId);
        errEl.textContent = 'Forbundet til server, finder vært...';
        hostConn = peer.connect(peerId, {{ reliable: true, serialization: 'json' }});
        hostConn.on('open', () => {{
            console.log('Connection to host open!');
            errEl.textContent = '';
            errEl.style.color = '';
            hostConn.send({{ type: 'join', name }});
            hostConn.on('data', (data) => handlePlayerMessage(data, name));
        }});
        hostConn.on('error', (err) => {{
            errEl.style.color = '';
            errEl.textContent = 'Forbindelse fejlede: ' + (err.type || err);
            console.error('Connection error:', err);
        }});
        hostConn.on('close', () => {{
            console.log('Connection to host closed');
        }});
    }});
    peer.on('error', (err) => {{
        errEl.style.color = '';
        console.error('Peer error:', err.type, err);
        if (err.type === 'peer-unavailable') {{
            errEl.textContent = 'Vært ikke fundet. Tjek koden og at vært er online.';
        }} else {{
            errEl.textContent = 'Forbindelsesfejl: ' + err.type;
        }}
    }});
    peer.on('disconnected', () => {{
        console.log('Peer disconnected from signaling server');
    }});

    // Timeout for connection
    setTimeout(() => {{
        if (!hostConn || !hostConn.open) {{
            if (errEl.textContent.includes('Forbinder') || errEl.textContent.includes('finder')) {{
                errEl.style.color = '';
                errEl.textContent = 'Timeout. Tjek koden og prøv igen.';
            }}
        }}
    }}, 10000);
}}

function handlePlayerMessage(data, myName) {{
    if (data.type === 'joined') {{
        showScreen('screenPlayerWait');
    }}
    if (data.type === 'question') {{
        myAnswer = -1;
        document.getElementById('playerQNum').textContent = 'Spørgsmål ' + (data.index + 1) + ' af ' + QUESTIONS.length;
        document.getElementById('playerQText').textContent = data.question;
        let html = '';
        data.options.forEach((opt, i) => {{
            html += `<button class="answer-btn" id="ansBtn${{i}}" onclick="playerAnswer(${{i}})">${{opt}}</button>`;
        }});
        document.getElementById('playerOptions').innerHTML = html;
        showScreen('screenPlayerQ');
    }}
    if (data.type === 'reveal') {{
        const q = data;
        // Show feedback
        const wasCorrect = myAnswer === q.correct;
        const fb = document.getElementById('playerFeedback');
        if (myAnswer === -1) {{
            fb.textContent = 'Ikke svaret!';
            fb.className = 'feedback wrong';
        }} else if (wasCorrect) {{
            fb.textContent = 'Rigtigt!';
            fb.className = 'feedback right';
        }} else {{
            fb.textContent = 'Forkert!';
            fb.className = 'feedback wrong';
        }}

        // Highlight answers
        if (myAnswer >= 0) {{
            const myBtn = document.getElementById('ansBtn' + myAnswer);
            if (myBtn) {{
                myBtn.classList.add(wasCorrect ? 'correct-pick' : 'wrong-pick');
            }}
        }}

        myScore = q.scores[myName] || 0;
        myCorrectCount = wasCorrect ? (myCorrectCount + 1) : myCorrectCount;
        document.getElementById('playerScore').textContent = myScore + ' point';

        showScreen('screenPlayerFeedback');
    }}
    if (data.type === 'scoreboard') {{
        const sorted = data.scores;
        const rankIcons = ['gold', 'silver', 'bronze'];
        const rankEmoji = ['1', '2', '3'];
        let html = '';
        sorted.forEach((p, i) => {{
            const rankClass = i < 3 ? rankIcons[i] : '';
            const rank = i < 3 ? rankEmoji[i] : (i + 1);
            const color = PLAYER_COLORS[p.name] || '#2563eb';
            const highlight = p.name === myName ? 'border:2px solid #2563eb;' : '';
            html += `<div class="sb-row" style="${{highlight}}">
                <div class="sb-rank ${{rankClass}}">${{rank}}</div>
                <div class="sb-name" style="color:${{color}}">${{p.name}}</div>
                <div><span class="sb-score">${{p.score}} pts</span><span class="sb-correct">${{p.correct}}/${{QUESTIONS.length}}</span></div>
            </div>`;
        }});
        document.getElementById('scoreboard').innerHTML = html;
        showScreen('screenScoreboard');
    }}
}}

function playerAnswer(idx) {{
    if (myAnswer !== -1) return; // Already answered
    myAnswer = idx;

    // Highlight selected
    document.querySelectorAll('.answer-btn').forEach(b => b.disabled = true);
    document.getElementById('ansBtn' + idx).classList.add('selected');

    // Send to host
    hostConn.send({{ type: 'answer', option: idx }});
}}

// ── Auto-join from URL param ──
(function() {{
    const params = new URLSearchParams(location.search);
    if (params.get('room')) {{
        setTimeout(() => showJoin(), 100);
    }}
}})();

let myName = '';
</script>
</body>
</html>"""


# ── 6. HTML Assembly ────────────────────────────────────────────────────────

def build_html(chart_data: dict, awards_html: str, stats: pd.DataFrame,
               weekly: pd.DataFrame, df_bets: pd.DataFrame) -> str:
    total_weeks = len(weekly)
    total_bets = len(df_bets)
    total_staked = df_bets["Indsats"].sum()
    club_profit = df_bets["Profit"].sum()
    profit_class = "positive" if club_profit >= 0 else "negative"

    return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tipsklub 2025 - Årets Overblik</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
*{{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: #f1f5f9;
    color: #1e293b;
    font-family: 'Inter', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
}}
.container {{ max-width:800px; margin:0 auto; padding:16px; }}

.header {{ text-align:center; padding:32px 0 16px; }}
.header h1 {{ font-size:1.8rem; font-weight:900; }}
.header .sub {{ color:#64748b; font-size:0.85rem; margin-top:4px; }}

.quick-stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0 24px; }}
.qs {{ background:#fff; border-radius:12px; padding:14px 8px; text-align:center;
       border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
.qs .val {{ font-size:1.3rem; font-weight:700; }}
.qs .lbl {{ font-size:.6rem; color:#64748b; text-transform:uppercase; letter-spacing:.06em; margin-top:2px; }}
.positive {{ color:#16a34a; }}
.negative {{ color:#dc2626; }}

.card {{ background:#fff; border-radius:12px; padding:16px; margin:20px 0;
         border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
.card h2 {{ font-size:1rem; font-weight:700; margin-bottom:12px; }}
.card canvas {{ width:100%!important; }}

.section-title {{ font-size:1rem; font-weight:700; margin:28px 0 12px 4px; }}

.awards-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin:20px 0; }}
.award-card {{ background:#fff; border-radius:12px; padding:14px 10px; text-align:center;
               border:1px solid #e2e8f0; box-shadow:0 1px 2px rgba(0,0,0,.04); }}
.award-emoji {{ font-size:1.8rem; margin-bottom:6px; }}
.award-title {{ font-size:.65rem; text-transform:uppercase; letter-spacing:.08em; color:#64748b; font-weight:600; }}
.award-player {{ font-size:1.1rem; font-weight:900; margin:4px 0; }}
.award-stat {{ font-size:.85rem; font-weight:600; }}
.award-subtitle {{ font-size:.7rem; color:#64748b; font-style:italic; margin-top:4px; }}

.heatmap {{ display:grid; grid-template-columns:auto repeat(7,1fr); gap:2px; font-size:.75rem; }}
.hm-label {{ display:flex; align-items:center; padding:4px 8px 4px 0; font-weight:600; text-align:right; }}
.hm-header {{ text-align:center; padding:4px; font-weight:600; color:#64748b; }}
.hm-cell {{ text-align:center; padding:8px 4px; border-radius:6px; font-weight:600; }}

.footer {{ text-align:center; padding:24px 0; color:#94a3b8; font-size:.7rem; }}

@media(max-width:500px) {{
    .header h1 {{ font-size:1.4rem; }}
    .quick-stats {{ grid-template-columns:repeat(2,1fr); }}
    .qs .val {{ font-size:1.1rem; }}
    .awards-grid {{ gap:8px; }}
    .award-card {{ padding:10px 6px; }}
    .award-player {{ font-size:.95rem; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Tipsklub 2025</h1>
        <div class="sub">Årets Overblik &middot; {total_weeks} uger &middot; {total_bets} bets &middot; 5 spillere</div>
    </div>

    <div class="quick-stats">
        <div class="qs"><div class="val">{total_weeks}</div><div class="lbl">Uger spillet</div></div>
        <div class="qs"><div class="val">{total_bets}</div><div class="lbl">Bets i alt</div></div>
        <div class="qs"><div class="val">{total_staked:,.0f}</div><div class="lbl">Satset (kr)</div></div>
        <div class="qs"><div class="val {profit_class}">{club_profit:+,.0f}</div><div class="lbl">Klub Profit</div></div>
    </div>

    <div class="card">
        <h2>Kumulativ Profit/Tab</h2>
        <canvas id="chartCumulative" height="220"></canvas>
    </div>

    <div class="card">
        <h2>Leaderboard</h2>
        <canvas id="chartLeaderboard" height="160"></canvas>
    </div>

    <div class="section-title">Årets Priser</div>
    <div class="awards-grid">
        {awards_html}
    </div>

    <div class="section-title">Detaljer</div>

    <div class="card">
        <h2>Vindende Uger (%)</h2>
        <canvas id="chartWinrate" height="180"></canvas>
    </div>

    <div class="card">
        <h2>Månedlig Profit</h2>
        <canvas id="chartMonthly" height="200"></canvas>
    </div>

    <div class="card">
        <h2>Top 10 Ligaer</h2>
        <canvas id="chartLeagues" height="220"></canvas>
    </div>

    <div class="card">
        <h2>Odds-Appetit (gns. / min / max)</h2>
        <canvas id="chartOdds" height="180"></canvas>
    </div>

    <div class="card">
        <h2>Hvornår Spiller De?</h2>
        <div id="heatmapContainer"></div>
    </div>

    <div class="card">
        <h2>Bedste &amp; Værste Uger</h2>
        <canvas id="chartBigweeks" height="220"></canvas>
    </div>

    <div class="footer">Tipsklub 2025 &middot; Genereret {datetime.now().strftime('%d/%m/%Y')}</div>
</div>

<script>
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.color = '#475569';

// ── Chart 1: Cumulative P/L ──
(function() {{
    const datasets = {chart_data['cumulative']};
    new Chart(document.getElementById('chartCumulative'), {{
        type: 'line',
        data: {{ datasets }},
        options: {{
            responsive: true,
            interaction: {{ mode: 'index', intersect: false }},
            scales: {{
                x: {{
                    type: 'time',
                    time: {{ unit: 'month', displayFormats: {{ month: 'MMM' }} }},
                    grid: {{ color: '#f1f5f9' }}
                }},
                y: {{
                    grid: {{ color: '#f1f5f9' }},
                    ticks: {{ callback: v => v + ' kr' }}
                }}
            }},
            plugins: {{
                tooltip: {{
                    callbacks: {{
                        label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toLocaleString('da-DK') + ' kr'
                    }}
                }}
            }}
        }}
    }});
}})();

// ── Chart 2: Leaderboard ──
(function() {{
    const d = {chart_data['leaderboard']};
    new Chart(document.getElementById('chartLeaderboard'), {{
        type: 'bar',
        data: {{
            labels: d.labels,
            datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                    callbacks: {{ label: ctx => ctx.parsed.x.toLocaleString('da-DK') + ' kr' }}
                }}
            }},
            scales: {{
                x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + ' kr' }} }},
                y: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}})();

// ── Chart 3: Win Rate ──
(function() {{
    const d = {chart_data['winrate']};
    new Chart(document.getElementById('chartWinrate'), {{
        type: 'bar',
        data: {{
            labels: d.labels,
            datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                    callbacks: {{
                        label: (ctx, i) => {{
                            const idx = ctx.dataIndex;
                            return ctx.parsed.y + '% (' + d.winning[idx] + '/' + d.weeks[idx] + ' uger)';
                        }}
                    }}
                }}
            }},
            scales: {{
                y: {{ max: 100, grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + '%' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}})();

// ── Chart 4: Monthly Profit ──
(function() {{
    const d = {chart_data['monthly']};
    new Chart(document.getElementById('chartMonthly'), {{
        type: 'bar',
        data: {{
            labels: d.labels,
            datasets: d.datasets.map(ds => ({{ ...ds, borderRadius: 2 }}))
        }},
        options: {{
            responsive: true,
            plugins: {{
                tooltip: {{
                    callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toLocaleString('da-DK') + ' kr' }}
                }}
            }},
            scales: {{
                y: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + ' kr' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}})();

// ── Chart 5: Leagues ──
(function() {{
    const d = {chart_data['leagues']};
    new Chart(document.getElementById('chartLeagues'), {{
        type: 'bar',
        data: {{
            labels: d.labels,
            datasets: [{{ data: d.bets, backgroundColor: d.colors, borderRadius: 4 }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                    callbacks: {{
                        label: ctx => {{
                            const idx = ctx.dataIndex;
                            return ctx.parsed.x + ' bets | ' + d.profit[idx].toLocaleString('da-DK') + ' kr profit';
                        }}
                    }}
                }}
            }},
            scales: {{
                x: {{ grid: {{ color: '#f1f5f9' }}, title: {{ display: true, text: 'Antal bets' }} }},
                y: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}})();

// ── Chart 6: Odds ──
(function() {{
    const d = {chart_data['odds']};
    const labels = d.map(p => p.player);
    const avgs = d.map(p => p.avg);
    const mins = d.map(p => p.min);
    const maxs = d.map(p => p.max);
    const colors = d.map(p => p.color);

    new Chart(document.getElementById('chartOdds'), {{
        type: 'bar',
        data: {{
            labels: labels,
            datasets: [
                {{ label: 'Min', data: mins, backgroundColor: colors.map(c => c + '33'), borderRadius: 4 }},
                {{ label: 'Gns.', data: avgs, backgroundColor: colors, borderRadius: 4 }},
                {{ label: 'Max', data: maxs.map((mx,i) => mx - avgs[i]),
                   backgroundColor: colors.map(c => c + '55'), borderRadius: 4 }}
            ]
        }},
        options: {{
            responsive: true,
            scales: {{
                y: {{ grid: {{ color: '#f1f5f9' }}, title: {{ display: true, text: 'Odds' }} }},
                x: {{ grid: {{ display: false }}, stacked: false }}
            }},
            plugins: {{
                tooltip: {{
                    callbacks: {{
                        label: ctx => {{
                            const idx = ctx.dataIndex;
                            return `${{d[idx].player}}: min ${{d[idx].min}}, gns. ${{d[idx].avg}}, max ${{d[idx].max}}`;
                        }}
                    }}
                }}
            }}
        }}
    }});
}})();

// ── Chart 7: Weekday Heatmap (HTML) ──
(function() {{
    const d = {chart_data['weekday']};
    const maxVal = Math.max(...d.data.map(c => c.v));
    let html = '<div class="heatmap">';
    html += '<div></div>';
    d.days.forEach(day => {{ html += '<div class="hm-header">' + day + '</div>'; }});
    d.players.forEach((player, pi) => {{
        html += '<div class="hm-label">' + player + '</div>';
        for (let di = 0; di < 7; di++) {{
            const cell = d.data.find(c => c.x === di && c.y === pi);
            const v = cell ? cell.v : 0;
            const intensity = maxVal > 0 ? v / maxVal : 0;
            const bg = v === 0 ? '#f8fafc'
                : `rgba(37, 99, 235, ${{0.12 + intensity * 0.68}})`;
            const fg = intensity > 0.5 ? '#fff' : '#1e293b';
            html += `<div class="hm-cell" style="background:${{bg}};color:${{fg}}">${{v || ''}}</div>`;
        }}
    }});
    html += '</div>';
    document.getElementById('heatmapContainer').innerHTML = html;
}})();

// ── Chart 8: Best & Worst Weeks ──
(function() {{
    const d = {chart_data['bigweeks']};
    new Chart(document.getElementById('chartBigweeks'), {{
        type: 'bar',
        data: {{
            labels: d.labels,
            datasets: [{{ data: d.data, backgroundColor: d.colors, borderRadius: 4 }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{
                    callbacks: {{ label: ctx => ctx.parsed.x.toLocaleString('da-DK') + ' kr' }}
                }}
            }},
            scales: {{
                x: {{ grid: {{ color: '#f1f5f9' }}, ticks: {{ callback: v => v + ' kr' }} }},
                y: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}})();
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    df_bets = fetch_data()
    weekly = aggregate_weekly(df_bets)
    stats = compute_player_stats(weekly, df_bets)

    print("\n── 2025 Player Stats (weekly) ──")
    for _, row in stats.iterrows():
        print(
            f"  {row['Spiller']:10s}  "
            f"Weeks: {row['Weeks']:2.0f}  "
            f"W/L: {row['Winning Weeks']:.0f}/{row['Losing Weeks']:.0f}  "
            f"Profit: {row['Total Profit']:+8,.0f} kr  "
            f"WR: {row['Win Rate']:4.1f}%  "
            f"ROI: {row['ROI']:+.1f}%  "
            f"Streak: W{row['Win Streak']:.0f}/L{row['Loss Streak']:.0f}"
        )

    print("\nGenerating charts...")
    chart_data = {
        "cumulative": chart1_cumulative_data(weekly),
        "leaderboard": chart2_leaderboard_data(stats),
        "winrate": chart3_winrate_data(stats),
        "monthly": chart4_monthly_data(weekly),
        "leagues": chart5_league_data(df_bets),
        "odds": chart6_odds_data(df_bets),
        "weekday": chart7_weekday_data(df_bets),
        "bigweeks": chart8_best_worst_data(weekly),
    }

    print("Generating award cards...")
    awards_html = generate_award_cards(stats, weekly)

    print("Assembling HTML...")
    html = build_html(chart_data, awards_html, stats, weekly, df_bets)

    output_path = "tipsklub_2025.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Dashboard: {output_path} ({len(html) / 1024:.0f} KB)")

    print("Generating quiz...")
    quiz_json = generate_quiz_questions(stats, weekly, df_bets, chart_data)
    quiz_html = generate_quiz_html(quiz_json, chart_data, stats, weekly, df_bets)

    quiz_path = "tipsklub_quiz.html"
    with open(quiz_path, "w", encoding="utf-8") as f:
        f.write(quiz_html)

    print(f"  Quiz: {quiz_path} ({len(quiz_html) / 1024:.0f} KB)")
    print("\nDone!")


if __name__ == "__main__":
    main()
