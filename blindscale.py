#!/usr/bin/env python3
"""Blindscale's Lair — a blind ASCII dungeon.

An 8×8 lair. Walls stay unseen until you strike them. Blindscale sleeps on
the nest, which is also where the treasure starts. You came in by a stairwell
you choose, and that is the one chamber where the dragon will not strike.

Movement is WASD or the arrow keys. Carrying the treasure halves whatever
stride the dragon's fire has left you. The steps still left this turn are
shown as a count and a bar. Easy keeps T? and D? sense flags for you.
Normal lets you place them after a roar, a breadth warning, or a burn,
and remove them on a quiet step. Each D? chases from its own square.
A burn leaves a glowing D* on that chamber for two steps. Within one
chamber of the dragon, diagonals included, you feel its breadth. After
a burn, the dragon's return spills
gold one chamber north, south, east, and west of the nest. That gold
stays unseen until you walk into the chamber, and the nest itself
stays hidden.
"""

from __future__ import annotations

import argparse
import random
import re
import select
import sys
from typing import Iterable

SIZE = 8
WAKE_DISTANCE = 3
WALL_ODDS = 0.80
ENDURANCE = 3
BURN_MARK_STEPS = 2
# An 8×8 lair has 112 inner edges. A connected lair needs 63 passages,
# so 49 is the most walls that still leave every chamber reachable.
# Easy opens passages until exactly 25 walls remain.
WALL_COUNTS = {"easy": 25}
DIFFICULTIES = ("easy", "normal")

WALL = "wall"
OPEN = "open"
UNKNOWN = "unknown"

Coord = tuple[int, int]

# (delta row, delta col). North is up, toward row 1.
# Keys are internal directions. Players type WASD or the arrow keys.
DELTA: dict[str, Coord] = {
    "n": (-1, 0),
    "s": (1, 0),
    "e": (0, 1),
    "w": (0, -1),
}
DIR_NAME = {"n": "north", "s": "south", "e": "east", "w": "west"}
WORDS = {
    "w": "n",
    "north": "n",
    "up": "n",
    "s": "s",
    "south": "s",
    "down": "s",
    "d": "e",
    "east": "e",
    "right": "e",
    "a": "w",
    "west": "w",
    "left": "w",
    ".": "end",
    "end": "end",
    "wait": "end",
    "stay": "end",
    "q": "q",
    "quit": "q",
    "exit": "q",
    "?": "?",
    "help": "?",
    "look": "look",
    "map": "look",
}

HSEG = {WALL: "---", OPEN: "   ", UNKNOWN: "..."}
VSEG = {WALL: "|", OPEN: " ", UNKNOWN: ":"}

HELP = """\
Blindscale's Lair

The lair is an 8 by 8 grid. A1 is the north-west corner and H8 is the
south-east. North is up. You can see the squares. You cannot see the
walls, Blindscale's Nest, or Blindscale until the lair tells you.

Choose a difficulty, then a stairwell. Easy lays 25 walls, and
every chamber can be reached. Normal keeps the seeded odds, so the
wall count changes with the seed. The stairwell is where you entered
the lair, and Blindscale will not attack you inside it. Find the
treasure and carry it back to the stairwell.

Move with WASD or the arrow keys. W is north, A west, S south, D east.
You may cross 8 chambers. Striking a wall ends the turn at once.
Blindscale's fire shortens your stride — 8, then 6, then 4. The third
attack kills you. The treasure is heavy: while you carry it, that
stride is cut in half (8 becomes 4, 6 becomes 3, 4 becomes 2).

Blindscale sleeps on the nest, with the treasure, until you are three
or fewer steps away, counting north, south, east, and west only. You
hear the roar when you are within three chambers of the treasure. After
your turn the dragon flies one chamber toward you, through walls, and
may cut a corner. Return to the stairwell and it turns back toward the
nest.

You may snatch the treasure without being burned only when Blindscale
is in the nest with it and you take it from that room. Step into any
other chamber the dragon occupies and you are burned at once. That
includes a room where a dropped treasure and Blindscale are together.

Sense flags help you narrow the treasure room and the dragon:

  mt E4   possible treasure room (T?)
  md E4   dragon guess (D?)

In the terminal, press m, then t or d, then name a chamber. Repeat mt
or md on the same chamber to clear that flag. Easy maintains
both sets for you. In normal, when Blindscale first roars you may place
many T? but only one D? until your next step or end. Each D? steps
toward you on its own. Every D? vanishes when you are burned.

The treasure room stays hidden until you walk into it (T), or until
your roar D? was on the true starting chamber and the first burn
proves it (T).

After Blindscale has burned you, its return to the nest spills gold
one chamber north, south, east, and west. You see g only after you
walk into that chamber. The gold does not mark the nest itself.

The chamber where the fire hit you glows as D* for two of your steps.
Dropped treasure shows as t once the glow fades.

Come within one chamber of Blindscale — north, south, east, west, or
on a diagonal — and the lair tells you:

  You can almost feel Blindscale's breadth and sense that it is one chamber away!

The map records only what you have learned:

  ...  and  :   an edge you have not tried
  ---  and  |   a wall you struck
  a gap         a passage you walked
  .             a chamber you have entered
  @ you    $ you, carrying the treasure    S the stairwell
  T treasure room, once found    t treasure sitting there
  T? possible treasure room    D? your dragon guess
  g gold, once you enter that splash
  D Blindscale, once found    * you and Blindscale
  D* Blindscale burned you (glows; fades after two steps)

Commands
  w a s d     step (also the arrow keys)
  m           mark: then t for T? or d for D?, then name a chamber
  mt E4       toggle T? (same as m, t, E4 in line mode)
  md E4       toggle D? (same as m, d, E4 in line mode)
  . or space  end the turn early (also: end, wait, enter)
  ?           this help
  q           quit

Name the stairwell as D4, or d4.
"""


def fmt_coord(pos: Coord) -> str:
    row, col = pos
    return f"{'ABCDEFGH'[col]}{row + 1}"


def parse_coord(text: str) -> Coord | None:
    token = re.sub(r"[\s,\-]", "", text.strip().lower())
    if not re.fullmatch(r"[a-h][1-8]", token):
        return None
    return int(token[1]) - 1, ord(token[0]) - ord("a")


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev(a: Coord, b: Coord) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def step_toward(src: Coord, dst: Coord) -> Coord:
    """One king-step toward dst, ignoring walls. Stays put when already there."""
    row, col = src
    trow, tcol = dst
    if trow != row:
        row += 1 if trow > row else -1
    if tcol != col:
        col += 1 if tcol > col else -1
    return row, col


def in_bounds(pos: Coord) -> bool:
    row, col = pos
    return 0 <= row < SIZE and 0 <= col < SIZE


def king_neighbors(pos: Coord) -> set[Coord]:
    row, col = pos
    out: set[Coord] = set()
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            if drow == 0 and dcol == 0:
                continue
            nxt = (row + drow, col + dcol)
            if in_bounds(nxt):
                out.add(nxt)
    return out


def paint(text: str, code: str, enabled: bool) -> str:
    if not enabled or not text:
        return text
    return f"\033[{code}m{text}\033[0m"


TAG_COLOR = {
    "[clear]": "2",
    "[thud]": "1",
    "[mark]": "2",
    "[edge]": "2",
    "[roar]": "1;31",
    "[chime]": "1;33",
    "[wings]": "31",
    "[fire]": "1;31",
    "[safe]": "36",
    "[still]": "31",
    "[wait]": "2",
    "[victory]": "1;33",
    "[defeat]": "1;31",
    "[no]": "2",
    "[found]": "1;33",
    "[echo]": "1;33",
    "[near]": "1;33",
}


class Game:
    """One lair. The player-facing map never includes unrevealed walls,
    Blindscale's Nest, or Blindscale. T? and D? are sense guesses.
    """

    def __init__(self, seed: int | None = None, difficulty: str = "normal") -> None:
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"unknown difficulty: {difficulty}")
        if seed is None:
            seed = random.SystemRandom().randrange(1, 1_000_000_000)
        self.seed = seed
        self.difficulty = difficulty
        self.rng = random.Random(seed)
        self.h_wall: list[list[bool]] = []
        self.v_wall: list[list[bool]] = []
        self.known_h = [[UNKNOWN] * SIZE for _ in range(SIZE - 1)]
        self.known_v = [[UNKNOWN] * (SIZE - 1) for _ in range(SIZE)]
        self._generate()
        self.phase = "choose"
        self.stairwell: Coord | None = None
        self.pos: Coord | None = None
        self.treasure_room: Coord | None = None
        self.chest: Coord | None = None
        self.dragon: Coord | None = None
        self.nest_marked = False
        self.treasure_room_guesses: set[Coord] = set()
        self.dragon_tokens: set[Coord] = set()
        self.quiet_sleep_steps: list[Coord] = []
        self.roar_at: Coord | None = None
        self.roar_dragon_placement: Coord | None = None
        self.at_roar_moment = False
        self.burn_count = 0
        self.death_revealed = False
        self.awake = False
        self.dragon_visible = False
        self.carrying = False
        self.chest_known = False
        self.treasure_room_known = False
        self.burned = False
        self.burn_at: Coord | None = None
        self.burn_moves = 0
        self._near_warned = False
        self.heist_grace = False
        self.gold_spill: set[Coord] = set()
        self.gold_seen: set[Coord] = set()
        self.endurance = ENDURANCE
        self.turn = 1
        self.steps_taken = 0
        self.moves_left = 0
        self.visited: set[Coord] = set()
        self.log = [
            "The grid is bare. The walls, Blindscale's Nest, and Blindscale are already set.",
            "Choose your stairwell — the chamber where you entered the lair, such as D4.",
        ]

    def reveal_treasure_room_after_death(self) -> list[str]:
        """After defeat, show where the treasure room was on the map."""
        if self.phase != "lost":
            return []
        if self.treasure_room is None:
            return ["[no] The treasure room is unknown."]
        if self.death_revealed:
            where = fmt_coord(self.treasure_room)
            return [f"[found] The treasure room is already marked on the map at {where}."]
        self.death_revealed = True
        self.treasure_room_known = True
        self.visited.add(self.treasure_room)
        where = fmt_coord(self.treasure_room)
        message = f"[found] The treasure room was at {where}. It is marked T on the map."
        self._note([message])
        return [message]

    def allowance(self) -> int:
        """Chambers you may enter this turn, before a wall.

        Fire shortens the stride to 8, then 6, then 4. The treasure
        halves whichever of those is active.
        """
        base = 2 + 2 * self.endurance
        if self.carrying:
            return base // 2
        return base

    def wall_between(self, a: Coord, b: Coord) -> bool:
        kind, row, col = self._edge(a, b)
        grid = self.h_wall if kind == "h" else self.v_wall
        return grid[row][col]

    def known_between(self, a: Coord, b: Coord) -> str:
        kind, row, col = self._edge(a, b)
        grid = self.known_h if kind == "h" else self.known_v
        return grid[row][col]

    def command(self, text: str) -> list[str]:
        self._near_warned = False
        self._near_observation = None
        token = text.strip().lower()
        if not token:
            return []
        if self.phase == "quit":
            return []
        if token in {"q", "quit", "exit"}:
            self.phase = "quit"
            messages = ["[leave] You set the miniature down and step away."]
            self._note(messages)
            return messages
        if token in {"?", "help"}:
            return []
        if self.phase == "choose":
            messages = self._choose(token)
            self._note(messages)
            return messages
        if self.phase != "play":
            messages = ["The lair is still. The game is over."]
            self._note(messages)
            return messages
        sense = self._parse_sense_command(token)
        if sense is not None:
            messages = sense
            self._note(messages)
            return messages
        action = WORDS.get(token)
        if action == "look":
            messages = ["The map shows only the marks you have already earned."]
        elif action == "end":
            messages = self._end_turn()
        elif action in DELTA:
            messages = self._step(action)
        else:
            messages = ["[no] The lair does not understand. Try w, a, s, d, mt E4, md E4, end, or ?."]
        self._note(messages)
        return messages

    def render(self, *, color: bool = False) -> str:
        lines: list[str] = []
        title = paint("BLINDSCALE'S LAIR", "1", color)
        lines.append(title)
        lines.append(
            f"seed {self.seed} · {self.difficulty} · the walls, the nest, and Blindscale stay hidden"
        )
        lines.append("")
        lines.append(self._header(color))
        lines.append(self._hline([WALL] * SIZE, color))
        for row in range(SIZE):
            lines.append(self._cell_line(row, color))
            if row < SIZE - 1:
                lines.append(self._hline(self.known_h[row], color))
        lines.append(self._hline([WALL] * SIZE, color))
        lines.append("")
        lines.append("... : untested    --- | wall    gap  passage you walked    . entered")
        lines.append("@ you   $ with treasure   S stairwell   T treasure room   t treasure   g gold you have entered")
        lines.append("T? possible treasure room   D? your dragon guess   D Blindscale, once found   * you and Blindscale")
        lines.append("D* Blindscale burned you (glows, fades after two steps)")
        lines.append("")
        lines.extend(self._status(color))
        lines.append("")
        shown = self.log[-8:]
        for entry in shown:
            lines.append(self._color_message(entry, color))
        if self.phase == "play":
            lines.append("")
            lines.append(self._steps_line(color))
        return "\n".join(lines)

    # --- generation -----------------------------------------------------

    def _generate(self) -> None:
        """Depth-first labyrinth. A spanning tree of passages is carved.

        Normal then walls each unused edge with WALL_ODDS, so the
        count follows the seed. Easy opens passages until 25 walls
        remain, and every chamber stays reachable.
        """
        h: list[list[bool | None]] = [[None] * SIZE for _ in range(SIZE - 1)]
        v: list[list[bool | None]] = [[None] * (SIZE - 1) for _ in range(SIZE)]
        offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))

        def locate(row: int, col: int, drow: int, dcol: int) -> tuple[list, int, int]:
            if drow == 1:
                return h, row, col
            if drow == -1:
                return h, row - 1, col
            if dcol == 1:
                return v, row, col
            return v, row, col - 1

        visited: set[Coord] = set()
        stack = [(self.rng.randrange(SIZE), self.rng.randrange(SIZE))]
        while stack:
            row, col = stack[-1]
            visited.add((row, col))
            for drow, dcol in offsets:
                nrow, ncol = row + drow, col + dcol
                if not in_bounds((nrow, ncol)):
                    continue
                grid, er, ec = locate(row, col, drow, dcol)
                if grid[er][ec] is None and (nrow, ncol) in visited:
                    if self.difficulty == "normal":
                        grid[er][ec] = self.rng.random() <= WALL_ODDS
                    else:
                        grid[er][ec] = True
            options: list[tuple[int, int]] = []
            for drow, dcol in offsets:
                nrow, ncol = row + drow, col + dcol
                if not in_bounds((nrow, ncol)):
                    continue
                grid, er, ec = locate(row, col, drow, dcol)
                if grid[er][ec] is None:
                    options.append((drow, dcol))
            if not options:
                stack.pop()
                continue
            drow, dcol = self.rng.choice(options)
            grid, er, ec = locate(row, col, drow, dcol)
            grid[er][ec] = False
            stack.append((row + drow, col + dcol))

        if any(cell is None for row_ in h for cell in row_) or any(
            cell is None for row_ in v for cell in row_
        ):
            raise RuntimeError("labyrinth generation left an undecided edge")
        self.h_wall = [[bool(cell) for cell in row_] for row_ in h]
        self.v_wall = [[bool(cell) for cell in row_] for row_ in v]
        if self.difficulty == "easy":
            self._retarget_walls(WALL_COUNTS["easy"])

    def _retarget_walls(self, target: int) -> None:
        """Open or seal passages until the lair holds exactly target walls."""
        passages: list[tuple[str, int, int]] = []
        blocked: list[tuple[str, int, int]] = []
        for kind, grid in (("h", self.h_wall), ("v", self.v_wall)):
            for row, cells in enumerate(grid):
                for col, wall in enumerate(cells):
                    bucket = blocked if wall else passages
                    bucket.append((kind, row, col))
        if len(blocked) > target:
            self.rng.shuffle(blocked)
            for kind, row, col in blocked[: len(blocked) - target]:
                self._set_wall(kind, row, col, False)
        elif len(blocked) < target:
            self.rng.shuffle(passages)
            for kind, row, col in passages[: target - len(blocked)]:
                self._set_wall(kind, row, col, True)

    def _set_wall(self, kind: str, row: int, col: int, wall: bool) -> None:
        grid = self.h_wall if kind == "h" else self.v_wall
        grid[row][col] = wall

    def _reachable_from(self, start: Coord) -> set[Coord]:
        reached = {start}
        queue = [start]
        while queue:
            row, col = queue.pop()
            for drow, dcol in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (row + drow, col + dcol)
                if not in_bounds(nxt) or nxt in reached:
                    continue
                if self.wall_between((row, col), nxt):
                    continue
                reached.add(nxt)
                queue.append(nxt)
        return reached

    # --- play ------------------------------------------------------------

    def _choose(self, token: str) -> list[str]:
        pos = parse_coord(token)
        if pos is None:
            return ["Name a stairwell from A1 to H8, for example D4."]
        self.stairwell = pos
        self.pos = pos
        self.visited.add(pos)
        reached = self._reachable_from(pos)
        far = [
            (row, col)
            for row in range(SIZE)
            for col in range(SIZE)
            if (row, col) in reached and manhattan((row, col), pos) > WAKE_DISTANCE
        ]
        if not far:
            far = [
                (row, col)
                for row in range(SIZE)
                for col in range(SIZE)
                if (row, col) in reached and (row, col) != pos
            ] or [pos]
        # The nest and the sleeping dragon begin in the same chamber.
        # The treasure starts there too. They separate only if you carry
        # the chest away, or drop it when Blindscale burns you.
        self.treasure_room = self.rng.choice(far)
        self.chest = self.treasure_room
        self.dragon = self.treasure_room
        self.phase = "play"
        self.steps_taken = 0
        self.moves_left = self.allowance()
        self.turn = 1
        where = fmt_coord(pos)
        self.log = []
        return [
            f"Stairwell {where}. You entered Blindscale's Lair here. The dragon will not attack you inside it.",
            "Move with w a s d or the arrow keys. A wall ends the turn.  ? for help.",
        ]

    def _parse_sense_command(self, token: str) -> list[str] | None:
        match = re.fullmatch(r"(mt|md)\s*([a-h][1-8])", token.strip().lower())
        if not match:
            return None
        kind, cell = match.group(1), match.group(2)
        if kind == "mt":
            return self._toggle_treasure_flag(cell)
        return self._toggle_dragon_flag(cell)

    def _clear_roar_moment(self) -> None:
        self.at_roar_moment = False

    def _possible_nests(self) -> set[Coord]:
        assert self.stairwell is not None
        reached = self._reachable_from(self.stairwell)
        nests = {
            pos
            for pos in reached
            if manhattan(pos, self.stairwell) > WAKE_DISTANCE
        }
        for quiet in self.quiet_sleep_steps:
            nests = {
                pos for pos in nests if manhattan(pos, quiet) > WAKE_DISTANCE
            }
        if self.roar_at is not None:
            nests = {
                pos
                for pos in nests
                if manhattan(pos, self.roar_at) <= WAKE_DISTANCE
            }
        return nests

    def _sync_easy_treasure_guesses(self) -> None:
        if self.difficulty != "easy":
            return
        self.treasure_room_guesses = self._possible_nests()

    def _spawn_easy_dragon_tokens_at_roar(self) -> None:
        if self.difficulty != "easy":
            return
        self.dragon_tokens = set(self._possible_nests())

    def _toggle_treasure_flag(self, rest: str) -> list[str]:
        if self.difficulty == "easy":
            return ["[no] Easy keeps T? flags for you."]
        pos = parse_coord(rest)
        if pos is None:
            return ["[no] Name a chamber from A1 to H8, such as mt E4."]
        if pos in self.treasure_room_guesses:
            self.treasure_room_guesses.remove(pos)
            return [f"[mark] You clear T? from {fmt_coord(pos)}."]
        self.treasure_room_guesses.add(pos)
        return [f"[mark] You set T? on {fmt_coord(pos)}."]

    def _toggle_dragon_flag(self, rest: str) -> list[str]:
        if self.difficulty == "easy":
            return ["[no] Easy keeps D? flags for you."]
        pos = parse_coord(rest)
        if pos is None:
            return ["[no] Name a chamber from A1 to H8, such as md E4."]
        if pos in self.dragon_tokens:
            self.dragon_tokens.remove(pos)
            if self.roar_dragon_placement == pos:
                self.roar_dragon_placement = None
            return [f"[mark] You clear D? from {fmt_coord(pos)}."]
        if (
            self.difficulty == "normal"
            and self.at_roar_moment
            and self.dragon_tokens
        ):
            return ["[no] You may place only one D? when Blindscale first flies."]
        self.dragon_tokens.add(pos)
        if self.difficulty == "normal" and self.at_roar_moment:
            self.roar_dragon_placement = pos
        return [f"[mark] You set D? on {fmt_coord(pos)}."]

    def _record_quiet_if_asleep(self, dest: Coord) -> None:
        if (
            self.awake
            or self.stairwell is None
            or dest == self.stairwell
            or self.treasure_room is None
        ):
            return
        if manhattan(dest, self.treasure_room) <= WAKE_DISTANCE:
            return
        self.quiet_sleep_steps.append(dest)
        self._sync_easy_treasure_guesses()

    def _on_roar(self) -> None:
        assert self.pos is not None
        self.roar_at = self.pos
        self._sync_easy_treasure_guesses()
        self._spawn_easy_dragon_tokens_at_roar()
        self.at_roar_moment = True

    def _move_dragon_tokens(self) -> list[str]:
        if not self.awake or self.pos is None or not self.dragon_tokens:
            return []
        messages: list[str] = []
        moved: set[Coord] = set()
        for pos in self.dragon_tokens:
            if self.pos == self.stairwell:
                nxt = pos
            else:
                nxt = step_toward(pos, self.pos)
            if not in_bounds(nxt):
                messages.append(f"[mark] D? slips off the map from {fmt_coord(pos)}.")
                continue
            moved.add(nxt)
            if nxt != pos:
                messages.append(f"[mark] D? glides to {fmt_coord(nxt)}.")
        self.dragon_tokens = moved
        return messages

    def _easy_filter_dragon_tokens(self, observation: str | None) -> None:
        if self.difficulty != "easy" or self.pos is None or observation is None:
            return
        self._move_dragon_tokens()
        adj = king_neighbors(self.pos)
        if observation == "breadth":
            self.dragon_tokens &= adj
        elif observation == "silence":
            self.dragon_tokens -= adj

    def _step(self, direction: str) -> list[str]:
        assert self.pos is not None
        self._clear_roar_moment()
        roar_fired = False
        drow, dcol = DELTA[direction]
        dest = (self.pos[0] + drow, self.pos[1] + dcol)
        if not in_bounds(dest):
            return ["[edge] The outer wall of the lair bars that way."]
        if self.known_between(self.pos, dest) == WALL:
            return [
                f"[mark] A wall is already marked {DIR_NAME[direction]} of {fmt_coord(self.pos)}."
            ]
        blocked = self.wall_between(self.pos, dest)
        self._reveal(self.pos, dest)
        if blocked:
            self.moves_left = 0
            messages = [
                f"[thud] A wall blocks the way {DIR_NAME[direction]} "
                f"of {fmt_coord(self.pos)}. The turn ends."
            ]
            messages.extend(self._finish_turn())
            return messages

        self.pos = dest
        self.visited.add(dest)
        self.steps_taken += 1
        self._fade_burn_mark()
        self._record_quiet_if_asleep(dest)
        if dest in self.gold_spill:
            self.gold_seen.add(dest)
        messages = [f"[clear] You step {DIR_NAME[direction]} to {fmt_coord(dest)}."]
        # The one theft Blindscale allows: the chest, the dragon, and you
        # are all in the nest. Every other shared chamber burns on entry.
        heist = (
            not self.carrying
            and self.chest == dest
            and dest == self.treasure_room
            and self.dragon == dest
        )
        dragon_here = self.dragon == dest
        in_stairwell = dest == self.stairwell
        burn_on_entry = dragon_here and not in_stairwell and not heist
        if not self.carrying and self.chest == dest and not burn_on_entry:
            self.carrying = True
            self.chest_known = True
            if dest == self.treasure_room:
                self.treasure_room_known = True
            if heist:
                messages.append(
                    "[chime] You snatch the treasure from under Blindscale. "
                    "The dragon does not burn you for this theft. "
                    "It is heavy — your stride is cut in half while you carry it."
                )
            else:
                messages.append(
                    "[chime] The treasure is here. It is heavy — your stride is cut in half while you carry it."
                )
        elif dest == self.treasure_room and not self.treasure_room_known:
            self.treasure_room_known = True
            messages.append("[found] You enter Blindscale's Nest.")
        self.moves_left = max(0, self.allowance() - self.steps_taken)
        if self.carrying and self.pos == self.stairwell:
            self.phase = "won"
            messages.append(
                "[victory] You reach the stairwell with the treasure. You can leave the lair."
            )
            return messages
        if (
            not self.awake
            and self.pos != self.stairwell
            and self.treasure_room is not None
            and manhattan(self.pos, self.treasure_room) <= WAKE_DISTANCE
        ):
            self.awake = True
            roar_fired = True
            messages.append(
                "[roar] You hear Blindscale's echoing roar and know you are within "
                "three chambers of the treasure! You can mark and track the dragon's "
                "probable location on your map as it makes chase, but there is only "
                "one way to find out if you were right..."
            )
            self._on_roar()
        if dragon_here and not in_stairwell and not heist:
            self.awake = True
            messages.extend(self._attack())
            if self.phase == "play":
                messages.extend(self._finish_turn())
            return messages
        if dragon_here and in_stairwell and self.awake:
            messages.extend(self._reveal_true_dragon())
        elif heist:
            self.heist_grace = True
            messages.extend(self._reveal_true_dragon())
        # Warn before the dragon flies, so a last step beside it is not missed.
        messages.extend(self._near_dragon())
        self._apply_near_observation()
        if self.moves_left == 0:
            messages.extend(self._finish_turn())
        return messages

    def _end_turn(self) -> list[str]:
        self._clear_roar_moment()
        messages = ["[wait] You hold still and end the turn."]
        messages.extend(self._finish_turn())
        return messages

    def _finish_turn(self) -> list[str]:
        if self.phase != "play":
            return []
        messages = self._dragon_acts()
        if self.phase != "play":
            return messages
        self.turn += 1
        self.steps_taken = 0
        self.moves_left = self.allowance()
        return messages

    def _dragon_acts(self) -> list[str]:
        if not self.awake or self.phase != "play" or self.dragon is None or self.pos is None:
            return []
        safe = self.pos == self.stairwell
        # The snatch itself is not a burn. Lingering until a later turn is.
        grace = self.heist_grace and self.pos == self.treasure_room
        self.heist_grace = False
        if not safe and self.dragon == self.pos and not grace:
            messages = self._attack()
            messages.extend(self._near_dragon())
            self._apply_near_observation()
            return messages

        messages: list[str] = []
        if safe:
            messages.append(
                "[safe] You are in the stairwell. Blindscale will not strike you here."
            )
            if not self.treasure_room_known:
                self.dragon_visible = False
            target = self.treasure_room
        else:
            target = self.pos
        assert target is not None

        messages.extend(self._near_dragon())
        if self.dragon != target:
            self.dragon = step_toward(self.dragon, target)
            messages.extend(self._move_dragon_tokens())
            if not safe and self.dragon == self.pos:
                messages.extend(self._attack())
                messages.extend(self._near_dragon())
                return messages
            if safe and self.burned and self.dragon == self.treasure_room:
                messages.extend(self._spill_gold())
            if self.dragon_visible:
                messages.append(f"[wings] Blindscale glides to {fmt_coord(self.dragon)}.")
            elif not safe:
                messages.append("[wings] Somewhere in the dark, Blindscale flies one chamber.")
        elif safe and self.dragon_visible:
            messages.append("[still] Blindscale waits in the nest.")
        messages.extend(self._near_dragon())
        self._apply_near_observation()
        return messages

    def _spill_gold(self) -> list[str]:
        """Gold falls on the four rooms beside the nest. The nest stays blank.

        A splash stays off the map until you walk into that room.
        """
        assert self.treasure_room is not None
        row, col = self.treasure_room
        for drow, dcol in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            pos = (row + drow, col + dcol)
            if in_bounds(pos):
                self.gold_spill.add(pos)
        return [
            "[echo] You hear Blindscale return to its hoard, as well as "
            "the echo of treasure down upon its impact!"
        ]

    def _reveal_true_dragon(self) -> list[str]:
        """Show Blindscale once you meet it outside the stairwell."""
        if self.dragon_visible:
            return []
        self.dragon_visible = True
        return ["[found] You stumble upon Blindscale."]

    def _remember_burn(self) -> None:
        """The strike chamber glows, then remembers where you stood."""
        assert self.pos is not None
        self.burn_at = self.pos
        self.burn_moves = 0

    def _fade_burn_mark(self) -> None:
        """Each step you take wears the burn mark down. Two steps clear it."""
        if self.burn_at is None:
            return
        self.burn_moves += 1
        if self.burn_moves >= BURN_MARK_STEPS:
            self.burn_at = None
            self.burn_moves = 0

    def _burn_glyph(self, pos: Coord) -> str | None:
        if self.burn_at != pos or self.burn_moves >= BURN_MARK_STEPS:
            return None
        return "D*"

    def _near_dragon(self) -> list[str]:
        """Warn once per command when Blindscale is a king-step away."""
        if self._near_warned or self.phase != "play":
            return []
        if self.pos is None or self.dragon is None or not self.awake:
            return []
        if chebyshev(self.pos, self.dragon) != 1:
            self._near_observation = "silence"
            return []
        self._near_warned = True
        self._near_observation = "breadth"
        return [
            "[near] You can almost feel Blindscale's breadth and sense that it is one chamber away!"
        ]

    def _apply_near_observation(self) -> None:
        if self._near_observation is None:
            return
        self._easy_filter_dragon_tokens(self._near_observation)

    def _attack(self) -> list[str]:
        assert self.pos is not None and self.stairwell is not None
        self.burned = True
        self._remember_burn()
        self.burn_count += 1
        first_burn = self.burn_count == 1
        proved_nest = (
            first_burn
            and self.roar_dragon_placement is not None
            and self.roar_dragon_placement == self.treasure_room
        )
        messages = self._reveal_true_dragon()
        self.dragon_tokens.clear()
        if proved_nest and not self.treasure_room_known:
            self.nest_marked = True
            if self.treasure_room in self.treasure_room_guesses:
                self.treasure_room_guesses.discard(self.treasure_room)
            messages.append(
                "[found] Your D? was where Blindscale started. "
                "The treasure room is marked on the map."
            )
        burn = fmt_coord(self.pos)
        dropped = False
        if self.carrying:
            self.carrying = False
            self.chest = self.pos
            self.chest_known = True
            dropped = True
        self.endurance -= 1
        if self.endurance <= 0:
            self.phase = "lost"
            message = f"[defeat] Blindscale is at {burn} and its third flame ends you."
            if dropped:
                message += " The treasure falls with you."
            messages.append(message)
            return messages
        self.pos = self.stairwell
        self.visited.add(self.stairwell)
        message = (
            f"[fire] Blindscale is at {burn} and burns you. "
            f"You are thrown back to the stairwell at {fmt_coord(self.stairwell)}. "
            f"Endurance {self.endurance}. Next turn you can cross {self.allowance()} chambers."
        )
        if dropped:
            message += " The treasure drops where you fell."
        messages.append(message)
        return messages

    def _reveal(self, a: Coord, b: Coord) -> None:
        kind, row, col = self._edge(a, b)
        blocked = self.wall_between(a, b)
        grid = self.known_h if kind == "h" else self.known_v
        grid[row][col] = WALL if blocked else OPEN

    def _edge(self, a: Coord, b: Coord) -> tuple[str, int, int]:
        (r1, c1), (r2, c2) = (a, b) if a <= b else (b, a)
        if r1 == r2 and abs(c1 - c2) == 1:
            return ("v", r1, c1)
        if c1 == c2 and abs(r1 - r2) == 1:
            return ("h", r1, c1)
        raise ValueError(f"not orthogonal neighbors: {a} {b}")

    def _note(self, messages: Iterable[str]) -> None:
        self.log.extend(messages)
        if len(self.log) > 40:
            del self.log[:-40]

    # --- drawing ---------------------------------------------------------

    def _glyph(self, row: int, col: int) -> str:
        pos = (row, col)
        dragon_here = bool(self.dragon_visible and self.dragon == pos)
        you = self.pos == pos
        burn_glyph = self._burn_glyph(pos)
        if you and dragon_here:
            if burn_glyph == "D*":
                return "D*"
            return "*"
        if you:
            return "$" if self.carrying else "@"
        if burn_glyph is not None:
            return burn_glyph
        if dragon_here:
            return "D"
        if self.chest_known and not self.carrying and self.chest == pos:
            return "t"
        if (
            self.treasure_room is not None
            and self.treasure_room == pos
            and (self.treasure_room_known or self.nest_marked)
        ):
            return "T"
        if self.stairwell == pos:
            return "S"
        if pos in self.gold_seen:
            return "g"
        if pos in self.dragon_tokens:
            return "D?"
        if pos in self.treasure_room_guesses:
            return "T?"
        if pos in self.visited:
            return "."
        return " "

    def _header(self, color: bool) -> str:
        width = 3 + 4 * SIZE + 1
        chars = [" "] * width
        for col, letter in enumerate("ABCDEFGH"):
            chars[5 + col * 4] = letter
        return paint("".join(chars).rstrip(), "1", color)

    def _hline(self, kinds: list[str], color: bool) -> str:
        parts = ["   +"]
        for kind in kinds:
            seg = HSEG[kind]
            if kind == UNKNOWN:
                seg = paint(seg, "2;90", color)
            elif kind == WALL:
                seg = paint(seg, "1", color)
            parts.append(seg)
            parts.append(paint("+", "2", color) if kind == UNKNOWN else "+")
        return "".join(parts)

    def _cell_line(self, row: int, color: bool) -> str:
        parts = [f"{row + 1:2d} ", paint("|", "1", color)]
        for col in range(SIZE):
            glyph = self._glyph(row, col)
            painted = self._paint_glyph(glyph, color)
            if len(glyph) == 2:
                # Two characters plus one space, so the cell stays three wide.
                parts.append(painted + " ")
            else:
                parts.append(" " + painted + " ")
            if col == SIZE - 1:
                parts.append(paint("|", "1", color))
            else:
                kind = self.known_v[row][col]
                seg = VSEG[kind]
                if kind == UNKNOWN:
                    seg = paint(seg, "2;90", color)
                elif kind == WALL:
                    seg = paint(seg, "1", color)
                parts.append(seg)
        return "".join(parts)

    def _paint_glyph(self, glyph: str, color: bool) -> str:
        code = {
            "@": "1;36",
            "$": "1;33",
            "S": "1;34",
            "T": "33",
            "t": "1;33",
            "D": "1;31",
            "T?": "33",
            "D?": "1;33",
            "D*": "1;5;93;41",
            "g": "1;33",
            "*": "1;35",
            ".": "2",
        }.get(glyph)
        if code is None:
            return glyph
        return paint(glyph, code, color)

    def _status(self, color: bool) -> list[str]:
        if self.phase == "choose" or self.pos is None:
            return [
                "Name your stairwell, from A1 in the north-west to H8 in the south-east.",
            ]
        where = fmt_coord(self.pos)
        if self.pos == self.stairwell:
            where += " (stairwell)"
        elif self.treasure_room_known and self.pos == self.treasure_room:
            where += " (Blindscale's Nest)"
        if self.awake:
            dragon = (
                f"marked at {fmt_coord(self.dragon)}"
                if self.dragon_visible and self.dragon is not None
                else "awake, unseen"
            )
        else:
            dragon = "asleep"
        if self.carrying:
            loot = "in your hands"
        elif (
            self.chest_known
            and self.dragon_visible
            and self.chest is not None
            and self.chest == self.dragon
        ):
            loot = f"under the dragon at {fmt_coord(self.chest)}"
        elif self.chest_known:
            loot = "marked on the map"
        else:
            loot = "hidden"
        lines = []
        if self.phase == "won":
            lines.append(paint("VICTORY. The treasure is safe in the stairwell.", "1;33", color))
        elif self.phase == "lost":
            lines.append(paint("DEFEAT. Blindscale's third attack ends you.", "1;31", color))
        lines.append(
            f"Turn {self.turn}   You {where}   Endurance {self.endurance}   "
            f"Steps left {self.moves_left}"
        )
        lines.append(f"Dragon: {dragon}   Treasure: {loot}")
        if self.difficulty == "easy":
            lines.append(
                f"Treasure rooms: {len(self.treasure_room_guesses)}   "
                f"Dragon tokens: {len(self.dragon_tokens)}"
            )
        else:
            lines.append(
                f"T? placed: {len(self.treasure_room_guesses)}   "
                f"D? placed: {len(self.dragon_tokens)}"
            )
        if self.burn_at is not None and self.burn_moves < BURN_MARK_STEPS:
            where_burn = fmt_coord(self.burn_at)
            left = BURN_MARK_STEPS - self.burn_moves
            noun = "step" if left == 1 else "steps"
            lines.append(
                paint(
                    f"Burn: glowing D* at {where_burn} fades after {left} more {noun}.",
                    "1;93;41",
                    color,
                )
            )
        return lines

    def _steps_line(self, color: bool) -> str:
        """A count and a bar for the chambers still left this turn."""
        left = self.moves_left
        total = max(self.allowance(), left)
        bar = "#" * left + "." * (total - left)
        noun = "step" if left == 1 else "steps"
        return paint(
            f"Steps remaining: {left} {noun} of {total}  [{bar}]",
            "1;96",
            color,
        )

    def _color_message(self, entry: str, color: bool) -> str:
        for tag, code in TAG_COLOR.items():
            if entry.startswith(tag):
                return paint(entry, code, color)
        return entry


def _read_line(prompt: str) -> str | None:
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return None
    if line == "":
        return None
    return line


# Second byte of a Windows console arrow. These letters are what command()
# expects: w north, a west, s south, d east.
_WIN_ARROWS = {"H": "w", "P": "s", "M": "d", "K": "a"}
_VT_ARROWS = {"\x1b[A": "w", "\x1b[B": "s", "\x1b[C": "d", "\x1b[D": "a"}


def _command_from_char(char: str) -> str:
    """Map one typed character to a command. Empty means ignore it."""
    if char == "\x03":
        raise KeyboardInterrupt
    if char in "\r\n. ":
        return "end"
    folded = char.lower()
    if folded in {"w", "a", "s", "d", "m", "q"}:
        return folded
    if char == "?":
        return "?"
    return ""


def _read_tty_char(*, map_arrows: bool = True) -> str | None:
    """One character from the terminal, without waiting for Enter."""
    if sys.platform == "win32":
        try:
            return _read_tty_char_windows(map_arrows=map_arrows)
        except OSError:
            line = _read_line("")
            if line is None:
                return None
            return line[:1].lower() if line else None
    return _read_tty_char_posix(map_arrows=map_arrows)


def _read_tty_char_windows(*, map_arrows: bool = True) -> str | None:
    import msvcrt

    char = msvcrt.getwch()
    if char in ("\x00", "\xe0"):
        if not map_arrows:
            return ""
        return _WIN_ARROWS.get(msvcrt.getwch(), "")
    if char == "\x1b":
        if not map_arrows:
            return ""
        sequence = char
        for _ in range(2):
            if not msvcrt.kbhit():
                break
            sequence += msvcrt.getwch()
        return _VT_ARROWS.get(sequence, "")
    if char == "\x03":
        raise KeyboardInterrupt
    return char.lower()


def _read_tty_char_posix(*, map_arrows: bool = True) -> str | None:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
        if not char:
            return None
        if char == "\x1b":
            if not map_arrows:
                return ""
            sequence = char
            for _ in range(2):
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not ready:
                    break
                sequence += sys.stdin.read(1)
            return _VT_ARROWS.get(sequence, "")
        if char == "\x03":
            raise KeyboardInterrupt
        return char.lower()
    except KeyboardInterrupt:
        raise
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key() -> str | None:
    """One command from a terminal: WASD, arrows, m, q, ?, or end-the-turn."""
    char = _read_tty_char(map_arrows=True)
    if char is None:
        return None
    if char == "":
        return ""
    if char == "?":
        return "?"
    return _command_from_char(char)


def _mark_command_from_kind_and_cell(kind: str, cell: str) -> str | None:
    token = cell.strip().lower()
    if not token:
        return None
    if kind == "t":
        return f"mt {token}"
    if kind == "d":
        return f"md {token}"
    return None


def _read_mark_command_interactive() -> str | None:
    """After m: read t or d one key at a time, then the chamber on a line."""
    sys.stdout.write("Mark treasure T? (t) or dragon D? (d). q cancels.\n")
    sys.stdout.flush()
    while True:
        sys.stdout.write("t/d> ")
        sys.stdout.flush()
        kind = _read_tty_char(map_arrows=False)
        if kind is None:
            return None
        if kind in {"", "\r", "\n"}:
            continue
        if kind == "q":
            return None
        if kind in {"t", "d"}:
            break
        sys.stdout.write("[no] Press t, d, or q.\n")
        sys.stdout.flush()
    line = _read_line("Chamber> ")
    if line is None:
        return None
    cmd = _mark_command_from_kind_and_cell(kind, line)
    if cmd is None:
        sys.stdout.write("[no] Name a chamber from A1 to H8.\n")
        sys.stdout.flush()
    return cmd


def _read_key_line() -> str | None:
    """Line mode, for a terminal that cannot deliver one key at a time."""
    line = _read_line("> ")
    if line is None:
        return None
    token = line.strip().lower()
    if token == "":
        return "end"
    if token in {"?", "help"}:
        return "?"
    if token in {"m", "mark"}:
        return "m"
    return token


def _show_help(interactive: bool) -> None:
    sys.stdout.write("\n" + HELP + "\n")
    if interactive:
        sys.stdout.write("Press any key to return to the lair.")
        sys.stdout.flush()
        _read_key()
        sys.stdout.write("\n")
    sys.stdout.flush()


def _draw(game: Game, interactive: bool) -> None:
    if interactive:
        sys.stdout.write("\033[H\033[2J")
    sys.stdout.write(game.render(color=interactive))
    sys.stdout.write("\n")
    if game.phase == "play" and interactive:
        sys.stdout.write(
            "\nw a s d or arrows    m then t/d to mark    space or . end turn    ? help    q quit\n"
        )
    sys.stdout.flush()


def _ask_difficulty() -> str | None:
    sys.stdout.write(
        "Difficulty: easy (25 walls), normal (seeded odds).\n"
    )
    sys.stdout.flush()
    while True:
        line = _read_line("Difficulty> ")
        if line is None:
            return None
        token = line.strip().lower()
        aliases = {
            "e": "easy",
            "easy": "easy",
            "n": "normal",
            "normal": "normal",
        }
        if token in aliases:
            return aliases[token]
        sys.stdout.write("Choose easy or normal.\n")
        sys.stdout.flush()


def play(seed: int | None = None, difficulty: str | None = None) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    while True:
        chosen = difficulty
        if chosen is None:
            if interactive:
                chosen = _ask_difficulty()
                if chosen is None:
                    return 0
            else:
                chosen = "normal"
        game = Game(seed=seed, difficulty=chosen)
        _draw(game, interactive)
        while game.phase == "choose" or game.phase == "play":
            if game.phase == "choose":
                line = _read_line("Stairwell> ")
                if line is None:
                    return 0
                if line.strip().lower() in {"?", "help"}:
                    _show_help(interactive)
                    _draw(game, interactive)
                    continue
                game.command(line)
            else:
                if interactive:
                    try:
                        action = _read_key()
                    except KeyboardInterrupt:
                        sys.stdout.write("\nYou step away from the lair.\n")
                        return 0
                    if action is None:
                        return 0
                    if action == "":
                        continue
                    if action == "?":
                        _show_help(interactive)
                        _draw(game, interactive)
                        continue
                    if action == "m":
                        mark_cmd = _read_mark_command_interactive()
                        if mark_cmd is None:
                            continue
                        game.command(mark_cmd)
                    else:
                        game.command(action)
                else:
                    line = _read_line(f"{game.moves_left} steps left> ")
                    if line is None:
                        return 0
                    if line.strip().lower() in {"?", "help"}:
                        _show_help(interactive)
                        continue
                    game.command(line)
            if game.phase == "quit":
                _draw(game, interactive)
                return 0
            _draw(game, interactive)
        while True:
            if game.phase == "lost":
                answer = _read_line("Again? [y/n] Or reveal? [r] ")
            else:
                answer = _read_line("Again? [y/n] ")
            if answer is None:
                return 0
            token = answer.strip().lower()
            if game.phase == "lost" and token.startswith("r"):
                for line in game.reveal_treasure_room_after_death():
                    sys.stdout.write(line + "\n")
                sys.stdout.flush()
                _draw(game, interactive)
                continue
            if token.startswith("y"):
                break
            return 0
        seed = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Blindscale's Lair: a blind ASCII dungeon. Blindscale sleeps on the nest."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="repeat a lair. Omit it for a new one each game.",
    )
    parser.add_argument(
        "--difficulty",
        choices=DIFFICULTIES,
        default=None,
        help="easy is 25 walls, normal keeps the seeded odds.",
    )
    args = parser.parse_args(argv)
    try:
        return play(args.seed, args.difficulty)
    except KeyboardInterrupt:
        sys.stdout.write("\nYou step away from the lair.\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
