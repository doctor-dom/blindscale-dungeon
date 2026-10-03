#!/usr/bin/env python3
"""Castle Labyrinth — a blind ASCII dungeon.

A solo recreation of the basic game in the 1980 Mattel computer labyrinth:
an 8×8 castle, walls you cannot see until you strike them, a treasure room
that stays hidden until you enter it, and a dragon that sleeps on the hoard
until you come within three chambers.

This is the basic premise only. A second warrior, doors, and the strength
contest can be built on top of Game later.
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
DELTA: dict[str, Coord] = {
    "n": (-1, 0),
    "s": (1, 0),
    "e": (0, 1),
    "w": (0, -1),
}
DIR_NAME = {"n": "north", "s": "south", "e": "east", "w": "west"}
WORDS = {
    "n": "n",
    "north": "n",
    "up": "n",
    "s": "s",
    "south": "s",
    "down": "s",
    "e": "e",
    "east": "e",
    "right": "e",
    "w": "w",
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
Castle Labyrinth — basic solo game

The castle is an 8 by 8 grid, like a chessboard. A1 is the north-west
corner and H8 is the south-east. North is up. You can see the squares.
You cannot see the walls, the treasure room, or the dragon until the
castle tells you about them.

Pick a secret room. The dragon will not attack you inside it. Find the
treasure and carry it back there.

On your turn, step north, south, east, or west. You may cross 8 chambers.
Striking a wall ends the turn at once. The treasure is heavy: while you
carry it you can cross only 4. The dragon's fire shortens your stride
as well — 8, then 6, then 4. The third attack kills you.

The dragon sleeps on the hoard until you come within three chambers of
it (counted by orthogonal steps, diagonals included in the total). It
then wakes. After your turn it flies one chamber toward you, through
walls and on diagonals. Slip back into your secret room and it turns
toward the treasure room instead. You only learn its square once it
burns you. If it then flies off toward a hoard you have not found, you
lose sight of it.

The map records only what you have learned:

  ...  and  :   an edge you have not tried
  ---  and  |   a wall you struck
  a gap         a passage you walked
  .             a chamber you have entered
  @ you    $ you, carrying the treasure    S your secret room
  T treasure sitting there    t the empty hoard, once you know it
  D the dragon, once you can mark it    * you and the dragon together

Commands
  n s e w     step (also north, south, east, west, and the arrow keys)
  .           end the turn early (also: end, wait, enter, space)
  ?           this help
  q           quit

Name a secret room as D4, or d4.
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
}


class Game:
    """One castle. The player-facing map never includes unrevealed walls,
    the treasure room, or the dragon.
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
        self.secret: Coord | None = None
        self.pos: Coord | None = None
        self.treasure_room: Coord | None = None
        self.chest: Coord | None = None
        self.dragon: Coord | None = None
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
            "The grid is bare. The walls, the treasure room, and the dragon are already set.",
            "Choose your secret room — a chamber such as D4. North is up.",
        ]

    def allowance(self) -> int:
        """Chambers the warrior may enter this turn, before a wall."""
        if self.carrying:
            return 4
        return 2 + 2 * self.endurance

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
            messages = ["The castle is still. The game is over."]
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
            messages = ["[no] The castle does not understand. Try n, s, e, w, end, or ?."]
        self._note(messages)
        return messages

    def render(self, *, color: bool = False) -> str:
        lines: list[str] = []
        title = paint("CASTLE LABYRINTH", "1", color)
        lines.append(title)
        lines.append(
            f"seed {self.seed} · the walls, the hoard, and the dragon stay hidden"
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
        lines.append("@ you   $ with treasure   S secret room   T treasure   t empty hoard")
        lines.append("D dragon, once marked   * you and the dragon in one chamber")
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
            return ["Name a secret room from A1 to H8, for example D4."]
        self.secret = pos
        self.pos = pos
        self.visited.add(pos)
        far = [
            (row, col)
            for row in range(SIZE)
            for col in range(SIZE)
            if manhattan((row, col), pos) > WAKE_DISTANCE
        ]
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
            f"Secret room {where}. You begin there. The dragon will not attack you inside it.",
            "Step with n, s, e, w. A wall ends the turn.  ? for help.",
        ]

    def _step(self, direction: str) -> list[str]:
        assert self.pos is not None
        drow, dcol = DELTA[direction]
        dest = (self.pos[0] + drow, self.pos[1] + dcol)
        if not in_bounds(dest):
            return ["[edge] The outer wall of the castle bars that way."]
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
                "[chime] The treasure is here. It is heavy — four chambers a turn while you carry it."
            )
        self.moves_left = max(0, self.allowance() - self.steps_taken)
        if self.carrying and self.pos == self.secret:
            self.phase = "won"
            messages.append(
                "[victory] You reach your secret room with the treasure. The hoard is yours."
            )
            return messages
        if (
            not self.awake
            and self.pos != self.secret
            and self.treasure_room is not None
            and manhattan(self.pos, self.treasure_room) <= WAKE_DISTANCE
        ):
            self.awake = True
            messages.append(
                "[roar] The dragon wakes. You are within three chambers of the hoard."
            )
        if self.awake and self.dragon == self.pos and self.pos != self.secret:
            messages.extend(self._attack())
            if self.phase == "play":
                messages.extend(self._finish_turn())
            return messages
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
        safe = self.pos == self.secret
        if not safe and self.dragon == self.pos:
            return self._attack()

        messages: list[str] = []
        if safe:
            messages.append(
                "[safe] You are in your secret room. The dragon will not strike you here."
            )
            if not self.treasure_room_known:
                self.dragon_visible = False
            target = self.treasure_room
        else:
            target = self.pos
        assert target is not None

        if self.dragon != target:
            self.dragon = step_toward(self.dragon, target)
            if not safe and self.dragon == self.pos:
                messages.extend(self._attack())
                return messages
            if self.dragon_visible:
                messages.append(f"[wings] The dragon glides to {fmt_coord(self.dragon)}.")
            elif not safe:
                messages.append("[wings] Somewhere in the dark, the dragon flies one chamber.")
        elif safe and self.dragon_visible:
            messages.append("[still] The dragon waits in the treasure room.")
        return messages

    def _attack(self) -> list[str]:
        assert self.pos is not None and self.secret is not None
        self.dragon_visible = True
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
            message = f"[defeat] The dragon is at {burn} and its third flame ends you."
            if dropped:
                message += " The treasure falls with you."
            return [message]
        self.pos = self.secret
        self.visited.add(self.secret)
        message = (
            f"[fire] The dragon is at {burn} and burns you. "
            f"You are thrown back to {fmt_coord(self.secret)}. "
            f"Endurance {self.endurance}. Next turn you can cross {self.allowance()} chambers."
        )
        if dropped:
            message += " The treasure drops where you fell."
        return [message]

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
        if self.chest_known and not self.carrying and self.chest == pos:
            return "T"
        if self.treasure_room_known and self.treasure_room == pos:
            return "t"
        if self.secret == pos:
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
            parts.append(" " + self._paint_glyph(glyph, color) + " ")
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
            "*": "1;35",
            ".": "2",
        }.get(glyph)
        if code is None:
            return glyph
        return paint(glyph, code, color)

    def _status(self, color: bool) -> list[str]:
        if self.phase == "choose" or self.pos is None:
            return [
                "Name your secret room, from A1 in the north-west to H8 in the south-east.",
            ]
        where = fmt_coord(self.pos)
        if self.pos == self.secret:
            where += " (secret room)"
        elif self.treasure_room_known and self.pos == self.treasure_room:
            where += " (treasure room)"
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
        elif self.chest_known:
            loot = "marked on the map"
        else:
            loot = "hidden"
        lines = []
        if self.phase == "won":
            lines.append(paint("VICTORY. The treasure is safe in your secret room.", "1;33", color))
        elif self.phase == "lost":
            lines.append(paint("DEFEAT. The dragon's third attack ends you.", "1;31", color))
        lines.append(
            f"Turn {self.turn}   You {where}   Endurance {self.endurance}   "
            f"Chambers left {self.moves_left}"
        )
        lines.append(f"Dragon: {dragon}   Treasure: {loot}")
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
    """One command from a terminal: n/s/e/w, arrows, q, ?, or end-the-turn."""
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
            arrows = {"\x1b[A": "n", "\x1b[B": "s", "\x1b[C": "e", "\x1b[D": "w"}
            return arrows.get(sequence, "")
        if char in "\r\n. ":
            return "end"
        if char in {"n", "N"}:
            return "n"
        if char in {"s", "S"}:
            return "s"
        if char in {"e", "E"}:
            return "e"
        if char in {"w", "W"}:
            return "w"
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
        sys.stdout.write("Press any key to return to the castle.")
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
        sys.stdout.write("\nn s e w or arrows    . end turn    ? help    q quit\n")
    sys.stdout.flush()


def play(seed: int | None = None) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    while True:
        game = Game(seed=seed)
        _draw(game, interactive)
        while game.phase == "choose" or game.phase == "play":
            if game.phase == "choose":
                line = _read_line("Secret room> ")
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
                        sys.stdout.write("\nYou step away from the castle.\n")
                        return 0
                    if action is None:
                        return 0
                    if action == "":
                        continue
                    if action == "?":
                        _show_help(interactive)
                        _draw(game, interactive)
                        continue
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
        description="Castle Labyrinth: a blind ASCII dungeon with a hidden hoard and dragon."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="repeat a castle. Omit it for a new one each game.",
    )
    args = parser.parse_args(argv)
    try:
        return play(args.seed)
    except KeyboardInterrupt:
        sys.stdout.write("\nYou step away from the castle.\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
