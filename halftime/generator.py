"""Synthetic football match generator.

Produces a realistic-looking event stream (passes, shots, tackles,
interceptions, pressures, fouls, sprints, possession changes) for a fictional
match. Every coordinate is in the acting team's attacking frame: the pitch is
105 x 68 and x always grows towards the goal that team is attacking, the same
convention most event providers use after normalisation.

A match can carry a scripted tactical storyline (for example the away side
switching to a high press at minute 25) so the agents have something real to
find and explain.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

PITCH_X = 105.0
PITCH_Y = 68.0

POSITIONS = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"]

# Which positions tend to have the ball in each third of the pitch.
ZONE_WEIGHTS = {
    "def": {"GK": 2, "RB": 3, "CB": 5, "LB": 3, "DM": 3, "CM": 1},
    "mid": {"RB": 2, "LB": 2, "DM": 4, "CM": 5, "RW": 2, "LW": 2, "ST": 1},
    "att": {"CM": 2, "RW": 4, "LW": 4, "ST": 5, "RB": 1, "LB": 1},
}


@dataclass
class TeamStyle:
    """How a team plays; tuned per side to create a tactical storyline."""

    pass_skill: float = 0.86  # base pass completion before pressure / length
    press: float = 0.35  # how often they press the ball carrier (0-1)
    directness: float = 0.4  # 0 = patient short passing, 1 = long and forward
    finishing: float = 1.0  # multiplier on xG when deciding goals


@dataclass
class Team:
    """A side's squad and style, with optional mid-match style changes."""

    name: str
    short: str
    players: list[dict]
    style: TeamStyle
    # minute -> new style, applied from that minute on
    style_changes: dict[int, TeamStyle] = field(default_factory=dict)

    def style_at(self, minute: int) -> TeamStyle:
        """Return the style in force at a given minute."""
        style = self.style
        for start in sorted(self.style_changes):
            if minute >= start:
                style = self.style_changes[start]
        return style


HOME_NAMES = [
    "Okafor",
    "Reyes",
    "Lindqvist",
    "Mensah",
    "Doyle",
    "Haddad",
    "Navarro",
    "Kowalski",
    "Silva",
    "Brennan",
    "Adeyemi",
]
AWAY_NAMES = [
    "Varga",
    "Tanaka",
    "Moreau",
    "Osei",
    "Quinn",
    "Petrov",
    "Lucero",
    "Asante",
    "Ferreira",
    "Novak",
    "Duarte",
]


def _squad(names: list[str], prefix: str) -> list[dict]:
    return [
        {
            "id": f"{prefix}{i + 1}",
            "name": name,
            "position": pos,
            "number": i + 1,
            "top_speed_kmh": round(
                29
                + (3.5 if pos in ("RW", "LW", "ST", "RB", "LB") else 0)
                + (sum(map(ord, name)) % 20) / 10,
                1,
            ),
        }
        for i, (name, pos) in enumerate(zip(names, POSITIONS, strict=True))
    ]


def default_teams() -> tuple[Team, Team]:
    """Home side keeps the ball; away side flips to a high press at 25'."""
    home = Team(
        "Riverside FC",
        "RIV",
        _squad(HOME_NAMES, "H"),
        TeamStyle(pass_skill=0.88, press=0.30, directness=0.30),
    )
    away = Team(
        "Northgate United",
        "NGU",
        _squad(AWAY_NAMES, "A"),
        TeamStyle(pass_skill=0.85, press=0.25, directness=0.45),
        style_changes={
            25: TeamStyle(pass_skill=0.85, press=0.80, directness=0.50)
        },
    )
    return home, away


def shot_xg(x: float, y: float) -> float:
    """Simple distance/angle expected-goals model (attacking frame)."""
    dx = PITCH_X - x
    dy = abs(PITCH_Y / 2 - y)
    dist = math.hypot(dx, dy)
    # Angle subtended by the 7.32 m goal mouth.
    a = math.atan2(7.32 * dx, dx * dx + dy * dy - (7.32 / 2) ** 2)
    if a < 0:
        a += math.pi
    logit = -0.40 - 0.128 * dist + 1.5 * a
    return round(1 / (1 + math.exp(-logit)), 3)


def _mirror(x: float, y: float) -> tuple[float, float]:
    return PITCH_X - x, PITCH_Y - y


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class _Sim:
    def __init__(self, home: Team, away: Team, seed: int):
        self.rng = random.Random(seed)
        self.teams = {"home": home, "away": away}
        self.events: list[dict] = []
        self.clock = 0.0  # seconds since kick-off of the current half
        self.half = 1
        self.score = {"home": 0, "away": 0}

    # -- helpers -----------------------------------------------------------
    def minute(self) -> int:
        return int(self.clock // 60) + (45 if self.half == 2 else 0)

    def other(self, side: str) -> str:
        return "away" if side == "home" else "home"

    def pick_player(
        self, side: str, x: float, exclude: str | None = None
    ) -> dict:
        zone = "def" if x < 35 else "mid" if x < 70 else "att"
        weights = ZONE_WEIGHTS[zone]
        pool = [
            p
            for p in self.teams[side].players
            if p["position"] in weights and p["id"] != exclude
        ]
        return self.rng.choices(
            pool, weights=[weights[p["position"]] for p in pool]
        )[0]

    def emit(
        self,
        side: str,
        player: dict | None,
        etype: str,
        x: float,
        y: float,
        **extra,
    ) -> dict:
        total = self.clock + (45 * 60 if self.half == 2 else 0)
        ev = {
            "id": len(self.events) + 1,
            "half": self.half,
            "minute": self.minute(),
            "second": int(self.clock % 60),
            "t": round(total, 1),
            "team": side,
            "team_name": self.teams[side].name,
            "player_id": player["id"] if player else None,
            "player": player["name"] if player else None,
            "type": etype,
            "x": round(x, 1),
            "y": round(y, 1),
        }
        ev.update(extra)
        self.events.append(ev)
        return ev

    # -- simulation ----------------------------------------------------------
    def run_half(self, kickoff_side: str, length_s: float):
        side, x, y = kickoff_side, 52.5, 34.0
        while self.clock < length_s:
            side, x, y = self.possession(side, x, y)

    def possession(
        self, side: str, x: float, y: float
    ) -> tuple[str, float, float]:
        rng = self.rng
        opp = self.other(side)
        carrier = self.pick_player(side, x)
        for _ in range(40):
            if self.clock >= 45 * 60:
                return side, x, y
            minute = self.minute()
            style = self.teams[side].style_at(minute)
            opp_style = self.teams[opp].style_at(minute)

            # Opponent pressure: likelier the deeper the ball is in our half.
            zone_factor = (
                1.25 - x / PITCH_X
            )  # 1.25 at own goal, 0.25 at theirs
            pressured = rng.random() < opp_style.press * zone_factor * 0.9
            if pressured:
                px, py = _mirror(x, y)
                presser = self.pick_player(opp, px)
                self.emit(
                    opp, presser, "pressure", px, py, on_player=carrier["name"]
                )
                self.clock += 1

            # Shoot?
            central = abs(y - PITCH_Y / 2) < 18
            if (
                x > 75
                and central
                and rng.random() < 0.07 + (0.10 if x > 94 else 0)
            ):
                return self.shot(side, carrier, x, y, pressured)

            # Crowded final third: defenders step in even without a press.
            if x > 80 and rng.random() < 0.10:
                return self.turnover(side, carrier, x, y, kind="tackle")

            # Lost the ball to a tackle under pressure.
            if pressured and rng.random() < 0.06 + 0.10 * opp_style.press:
                return self.turnover(side, carrier, x, y, kind="tackle")

            # Pass.
            fwd = rng.gauss(3 + 10 * style.directness, 9)
            lat = rng.gauss(0, 12)
            ex = _clamp(x + fwd, 2, PITCH_X - 1)
            ey = _clamp(y + lat, 1, PITCH_Y - 1)
            length = math.hypot(ex - x, ey - y)
            p_ok = (
                style.pass_skill
                - 0.003 * max(0, length - 12)
                - (0.14 if pressured else 0)
                - 0.25 * max(0, (ex - 70) / 35)
            )
            ok = rng.random() < _clamp(p_ok, 0.3, 0.97)
            speed = round(_clamp(rng.gauss(32 + length * 1.3, 6), 18, 110), 1)
            receiver = (
                self.pick_player(side, ex, exclude=carrier["id"])
                if ok
                else None
            )
            self.emit(
                side,
                carrier,
                "pass",
                x,
                y,
                end_x=round(ex, 1),
                end_y=round(ey, 1),
                outcome="complete" if ok else "incomplete",
                receiver=receiver["name"] if receiver else None,
                length_m=round(length, 1),
                ball_speed_kmh=speed,
                under_pressure=pressured,
            )
            self.clock += rng.uniform(1.8, 3.6)
            if not ok:
                return self.turnover(side, None, ex, ey, kind="interception")

            # A long forward pass to a wide player or striker sometimes
            # triggers a sprint.
            if (
                receiver
                and ex - x > 18
                and receiver["position"] in ("RW", "LW", "ST", "RB", "LB")
            ):
                top = receiver["top_speed_kmh"]
                self.emit(
                    side,
                    receiver,
                    "sprint",
                    ex,
                    ey,
                    speed_kmh=round(
                        _clamp(rng.gauss(top - 1.5, 1.2), 24, top), 1
                    ),
                    distance_m=round(rng.uniform(15, 40), 1),
                )
            carrier, x, y = receiver, ex, ey

            if rng.random() < 0.012:
                fx, fy = _mirror(x, y)
                self.emit(
                    opp,
                    self.pick_player(opp, fx),
                    "foul",
                    fx,
                    fy,
                    on_player=carrier["name"],
                )
                self.clock += rng.uniform(15, 35)
        return side, x, y

    def turnover(
        self, side: str, loser: dict | None, x: float, y: float, kind: str
    ):
        opp = self.other(side)
        ox, oy = _mirror(x, y)
        winner = self.pick_player(opp, ox)
        self.emit(
            opp,
            winner,
            kind,
            ox,
            oy,
            outcome="won",
            from_player=loser["name"] if loser else None,
        )
        self.emit(opp, None, "possession_change", ox, oy, from_team=side)
        self.clock += self.rng.uniform(1.0, 2.5)
        return opp, ox, oy

    def shot(
        self, side: str, shooter: dict, x: float, y: float, pressured: bool
    ):
        rng = self.rng
        xg = shot_xg(x, y)
        if pressured:
            xg = round(xg * 0.8, 3)
        style = self.teams[side].style_at(self.minute())
        r = rng.random()
        if r < xg * style.finishing:
            outcome = "goal"
        elif r < 0.55:
            outcome = "saved"
        elif r < 0.75:
            outcome = "blocked"
        else:
            outcome = "off_target"
        speed = round(_clamp(rng.gauss(92, 14), 55, 130), 1)
        self.emit(
            side,
            shooter,
            "shot",
            x,
            y,
            xg=xg,
            outcome=outcome,
            shot_speed_kmh=speed,
            under_pressure=pressured,
        )
        self.clock += (
            rng.uniform(20, 45) if outcome != "goal" else rng.uniform(50, 80)
        )
        opp = self.other(side)
        if outcome == "goal":
            self.score[side] += 1
            self.emit(side, shooter, "goal", x, y, score=dict(self.score))
            return opp, 52.5, 34.0
        if outcome == "blocked":
            return opp, *_mirror(x, y)
        self.emit(opp, None, "possession_change", 6.0, 34.0, from_team=side)
        return opp, 6.0, 34.0


def generate_match(
    seed: int = 7, home: Team | None = None, away: Team | None = None
) -> dict:
    """Simulate a full 90-minute match; return metadata and the events."""
    if home is None or away is None:
        home, away = default_teams()
    sim = _Sim(home, away, seed)
    sim.run_half("home", 45 * 60)
    sim.half, sim.clock = 2, 0.0
    sim.run_half("away", 45 * 60)
    return {
        "match_id": f"synthetic-{seed}",
        "seed": seed,
        "competition": "Synthetic League",
        "venue": "Riverside Park",
        "pitch": {
            "length_m": PITCH_X,
            "width_m": PITCH_Y,
            "frame": (
                "attacking: x grows towards the goal the acting team attacks"
            ),
        },
        "teams": {
            side: {"name": t.name, "short": t.short, "players": t.players}
            for side, t in sim.teams.items()
        },
        "final_score": sim.score,
        "events": sim.events,
    }
