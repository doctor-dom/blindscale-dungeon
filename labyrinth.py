#!/usr/bin/env python3
"""Blindscale's Lair — a blind ASCII dungeon.

An 8×8 lair. Walls stay unseen until you strike them. Blindscale sleeps on
the nest, which is also where the treasure starts. You came in by a stairwell
you choose, and that is the one chamber where the dragon will not strike.

Movement is WASD or the arrow keys. Carrying the treasure halves whatever
stride the dragon's fire has left you. After Blindscale wakes you may mark
a guess, shown as ?D, and that mark moves as the dragon actually moves.
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

Choose a stairwell. That chamber is where you entered the lair, and
Blindscale will not attack you inside it. Find the treasure and carry
it back to the stairwell.

Move with WASD or the arrow keys. W is north, A west, S south, D east.
You may cross 8 chambers. Striking a wall ends the turn at once.
Blindscale's fire shortens your stride — 8, then 6, then 4. The third
attack kills you. The treasure is heavy: while you carry it, that
stride is cut in half (8 becomes 4, 6 becomes 3, 4 becomes 2).

Blindscale sleeps on the nest, with the treasure, until you are three
or fewer steps away, counting north, south, east, and west only. The
wake means you are within three chambers of Blindscale's Nest. After
your turn the dragon flies one chamber toward you, through walls, and
may cut a corner. Return to the stairwell and it turns back toward the
nest. You do not see the true square until you stumble upon the dragon.

When Blindscale wakes, mark where you think the dragon is:

  mark E4

The mark is ?D. It then moves exactly as Blindscale moves. If you
stumble upon the dragon, a wrong ?D disappears and a right one becomes
the true marker, D.

The map records only what you have learned:

  ...  and  :   an edge you have not tried
  ---  and  |   a wall you struck
  a gap         a passage you walked
  .             a chamber you have entered
  @ you    $ you, carrying the treasure    S the stairwell
  T treasure sitting there    t the empty nest, once you know it
  ?D your guess    D Blindscale, once found    * you and Blindscale

Commands
  w a s d     step (also the arrow keys)
  mark E4     place or move your guess of Blindscale (also the m key)
  .           end the turn early (also: end, wait, enter, space)
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
}


class Game:
    """One lair. The player-facing map never includes unrevealed walls,
    Blindscale's Nest, or Blindscale. A ?D is only the player's guess.
    """

    def __init__(self, seed: int | None = None) -> None:
        if seed is None:
            seed = random.SystemRandom().randrange(1, 1_000_000_000)
        self.seed = seed
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
        self.dragon_mark: Coord | None = None
        self.awake = False
        self.dragon_visible = False
        self.carrying = False
        self.chest_known = False
        self.treasure_room_known = False
        self.endurance = ENDURANCE
        self.turn = 1
        self.steps_taken = 0
        self.moves_left = 0
        self.visited: set[Coord] = set()
        self.log = [
            "The grid is bare. The walls, Blindscale's Nest, and Blindscale are already set.",
            "Choose your stairwell — the chamber where you entered the lair, such as D4.",
        ]

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
        if (
            token in {"m", "mark", "guess"}
            or token.startswith("mark ")
            or token.startswith("guess ")
            or token.startswith("m ")
        ):
            if token.startswith("mark "):
                rest = token[5:].strip()
            elif token.startswith("guess "):
                rest = token[6:].strip()
            elif token.startswith("m "):
                rest = token[2:].strip()
            else:
                rest = ""
            messages = self._place_mark(rest)
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
            messages = ["[no] The lair does not understand. Try w, a, s, d, mark E4, end, or ?."]
        self._note(messages)
        return messages

    def render(self, *, color: bool = False) -> str:
        lines: list[str] = []
        title = paint("BLINDSCALE'S LAIR", "1", color)
        lines.append(title)
        lines.append(
            f"seed {self.seed} · the walls, the nest, and Blindscale stay hidden"
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
        lines.append("@ you   $ with treasure   S stairwell   T treasure   t empty nest")
        lines.append("?D your guess of Blindscale   D Blindscale, once found   * you and Blindscale")
        lines.append("")
        lines.extend(self._status(color))
        lines.append("")
        shown = self.log[-8:]
        for entry in shown:
            lines.append(self._color_message(entry, color))
        return "\n".join(lines)

    # --- generation -----------------------------------------------------

    def _generate(self) -> None:
        """Depth-first labyrinth. A spanning tree of passages is carved,
        then each unused edge is walled with WALL_ODDS. The result is
        connected, with a few loops, and every internal edge is decided.
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
                    grid[er][ec] = self.rng.random() <= WALL_ODDS
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

    # --- play ------------------------------------------------------------

    def _choose(self, token: str) -> list[str]:
        pos = parse_coord(token)
        if pos is None:
            return ["Name a stairwell from A1 to H8, for example D4."]
        self.stairwell = pos
        self.pos = pos
        self.visited.add(pos)
        far = [
            (row, col)
            for row in range(SIZE)
            for col in range(SIZE)
            if manhattan((row, col), pos) > WAKE_DISTANCE
        ]
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

    def _place_mark(self, rest: str) -> list[str]:
        if not self.awake:
            return ["[no] Blindscale is still asleep. There is nothing to mark."]
        if self.dragon_visible:
            return ["[no] You have already found Blindscale. The true marker is D."]
        if not rest:
            return ["[no] Name a chamber, such as mark E4."]
        pos = parse_coord(rest)
        if pos is None:
            return ["[no] Mark a chamber from A1 to H8, such as mark E4."]
        self.dragon_mark = pos
        return [
            f"[mark] You set ?D on {fmt_coord(pos)}. It will move as Blindscale moves."
        ]

    def _step(self, direction: str) -> list[str]:
        assert self.pos is not None
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
        messages = [f"[clear] You step {DIR_NAME[direction]} to {fmt_coord(dest)}."]
        if not self.carrying and self.chest == dest:
            self.carrying = True
            self.chest_known = True
            if dest == self.treasure_room:
                self.treasure_room_known = True
            messages.append(
                "[chime] The treasure is here. It is heavy — your stride is cut in half while you carry it."
            )
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
            messages.append(
                "[roar] Blindscale wakes. You are within three chambers of Blindscale's Nest. "
                "Mark where you think the dragon is, for example: mark E4"
            )
        if self.awake and self.dragon == self.pos:
            if self.pos != self.stairwell:
                messages.extend(self._attack())
                if self.phase == "play":
                    messages.extend(self._finish_turn())
                return messages
            messages.extend(self._reveal_true_dragon())
        if self.moves_left == 0:
            messages.extend(self._finish_turn())
        return messages

    def _end_turn(self) -> list[str]:
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
        if not safe and self.dragon == self.pos:
            return self._attack()

        messages: list[str] = []
        if safe:
            messages.append(
                "[safe] You are in the stairwell. Blindscale will not strike you here."
            )
            if not self.treasure_room_known:
                # Hide the true marker. A ?D guess keeps tracking the flight.
                self.dragon_visible = False
            target = self.treasure_room
        else:
            target = self.pos
        assert target is not None

        if self.dragon != target:
            previous = self.dragon
            self.dragon = step_toward(self.dragon, target)
            messages.extend(self._shift_mark(previous, self.dragon))
            if not safe and self.dragon == self.pos:
                messages.extend(self._attack())
                return messages
            if self.dragon_visible:
                messages.append(f"[wings] Blindscale glides to {fmt_coord(self.dragon)}.")
            elif not safe:
                messages.append("[wings] Somewhere in the dark, Blindscale flies one chamber.")
        elif safe and self.dragon_visible:
            messages.append("[still] Blindscale waits in the nest.")
        return messages

    def _shift_mark(self, previous: Coord, current: Coord) -> list[str]:
        """Move ?D by the same delta as Blindscale. Drop it if it leaves the lair."""
        if self.dragon_mark is None or self.dragon_visible:
            return []
        drow = current[0] - previous[0]
        dcol = current[1] - previous[1]
        if drow == 0 and dcol == 0:
            return []
        nxt = (self.dragon_mark[0] + drow, self.dragon_mark[1] + dcol)
        if not in_bounds(nxt):
            self.dragon_mark = None
            return ["[mark] ?D slips off the map."]
        self.dragon_mark = nxt
        return [f"[mark] ?D glides to {fmt_coord(nxt)}."]

    def _reveal_true_dragon(self) -> list[str]:
        """Replace a correct ?D with D, or wipe a wrong one, when you meet Blindscale."""
        if self.dragon_visible and self.dragon_mark is None:
            return []
        on_mark = self.dragon_mark is not None and self.dragon_mark == self.dragon
        had_mark = self.dragon_mark is not None
        self.dragon_mark = None
        self.dragon_visible = True
        if on_mark:
            return ["[found] Blindscale is on your mark. ?D becomes the true dragon."]
        if had_mark:
            return ["[found] You stumble upon Blindscale. ?D is wiped from the map."]
        return []

    def _attack(self) -> list[str]:
        assert self.pos is not None and self.stairwell is not None
        messages = self._reveal_true_dragon()
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
        if you and dragon_here:
            return "*"
        if you:
            return "$" if self.carrying else "@"
        if dragon_here:
            return "D"
        if self.dragon_mark == pos and not self.dragon_visible:
            return "?D"
        if self.chest_known and not self.carrying and self.chest == pos:
            return "T"
        if self.treasure_room_known and self.treasure_room == pos:
            return "t"
        if self.stairwell == pos:
            return "S"
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
            if glyph == "?D":
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
            "T": "1;33",
            "t": "33",
            "D": "1;31",
            "?D": "1;33",
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
            f"Chambers left {self.moves_left}"
        )
        lines.append(f"Dragon: {dragon}   Treasure: {loot}")
        if self.awake and not self.dragon_visible and self.dragon_mark is not None:
            lines.append(f"Guess: ?D at {fmt_coord(self.dragon_mark)}")
        return lines

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


def _read_key() -> str | None:
    """One command from a terminal: WASD, arrows, m, q, ?, or end-the-turn."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x1b":
            sequence = char
            for _ in range(2):
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not ready:
                    break
                sequence += sys.stdin.read(1)
            # These letters are what command() expects: w north, a west, s south, d east.
            arrows = {"\x1b[A": "w", "\x1b[B": "s", "\x1b[C": "d", "\x1b[D": "a"}
            return arrows.get(sequence, "")
        if char in "\r\n. ":
            return "end"
        if char in {"w", "W"}:
            return "w"
        if char in {"a", "A"}:
            return "a"
        if char in {"s", "S"}:
            return "s"
        if char in {"d", "D"}:
            return "d"
        if char in {"m", "M"}:
            return "m"
        if char in {"q", "Q"}:
            return "q"
        if char == "?":
            return "?"
        return ""
    except KeyboardInterrupt:
        raise
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
        sys.stdout.write("\nw a s d or arrows    m mark    . end turn    ? help    q quit\n")
    sys.stdout.flush()


def play(seed: int | None = None) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    while True:
        game = Game(seed=seed)
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
                        line = _read_line("Mark chamber> ")
                        if line is None:
                            return 0
                        game.command(f"mark {line}")
                    else:
                        game.command(action)
                else:
                    line = _read_line(f"{game.moves_left} left> ")
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
        answer = _read_line("Again? [y/n] ")
        if answer is None or not answer.strip().lower().startswith("y"):
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
    args = parser.parse_args(argv)
    try:
        return play(args.seed)
    except KeyboardInterrupt:
        sys.stdout.write("\nYou step away from the lair.\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
