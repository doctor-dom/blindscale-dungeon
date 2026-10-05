"""Rules and blindness tests for Blindscale's Lair."""

from __future__ import annotations

import copy
import re
import subprocess
import sys
import unittest

from labyrinth import (
    OPEN,
    SIZE,
    UNKNOWN,
    WALL,
    Game,
    chebyshev,
    fmt_coord,
    manhattan,
    parse_coord,
)


def open_all(game: Game) -> None:
    for row in game.h_wall:
        for col in range(len(row)):
            row[col] = False
    for row in game.v_wall:
        for col in range(len(row)):
            row[col] = False


def column_header(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("A") and stripped.endswith("H") and "|" not in line:
            return line
    raise AssertionError("column header missing")


def grid_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"\s+\d \|", line)]


def wall_count(game: Game) -> int:
    return sum(cell for row in game.h_wall for cell in row) + sum(
        cell for row in game.v_wall for cell in row
    )


def neighbors(game: Game, cell: tuple[int, int], blocked: set[tuple[int, int]]):
    row, col = cell
    for name, (drow, dcol) in (("w", (-1, 0)), ("s", (1, 0)), ("d", (0, 1)), ("a", (0, -1))):
        nxt = (row + drow, col + dcol)
        if not (0 <= nxt[0] < SIZE and 0 <= nxt[1] < SIZE):
            continue
        if nxt in blocked:
            continue
        if game.wall_between(cell, nxt):
            continue
        yield name, nxt


def bfs(game: Game, start, goal, blocked: set[tuple[int, int]]):
    if start == goal:
        return [start]
    queue = [start]
    came = {start: None}
    while queue:
        cell = queue.pop(0)
        for _name, nxt in neighbors(game, cell, blocked):
            if nxt in came:
                continue
            came[nxt] = cell
            if nxt == goal:
                path = [nxt]
                while path[-1] != start:
                    path.append(came[path[-1]])
                path.reverse()
                return path
            queue.append(nxt)
    return None


def direction(src, dst) -> str:
    drow, dcol = dst[0] - src[0], dst[1] - src[1]
    return {(-1, 0): "w", (1, 0): "s", (0, 1): "d", (0, -1): "a"}[(drow, dcol)]


def step_toward_goal(game: Game, goal, avoid: set[tuple[int, int]]) -> str | None:
    path = bfs(game, game.pos, goal, avoid)
    if not path or len(path) < 2:
        return None
    nxt = path[1]
    if nxt in avoid:
        return None
    if not game.awake and nxt == game.treasure_room:
        return None
    if game.awake and nxt == game.dragon:
        return None
    return direction(game.pos, nxt)


def safe_last_step(game: Game) -> str:
    """End the turn where the dragon will not land, and not in the stairwell.

    Ending in the stairwell sends the dragon back toward the nest.
    """
    best = None
    for name, nxt in neighbors(game, game.pos, set()):
        if game.awake and nxt == game.dragon:
            continue
        if not game.awake and nxt == game.treasure_room:
            continue
        cheb = chebyshev(nxt, game.dragon) if game.awake else 9
        survives = 1 if cheb >= 2 else 0
        not_stairwell = 0 if nxt == game.stairwell else 1
        away = manhattan(nxt, game.treasure_room)
        key = (survives, not_stairwell, cheb, away, name)
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else "end"


def lure_step(game: Game) -> str:
    blocked = {game.dragon} if game.awake else {game.treasure_room}
    best = None
    for row in range(SIZE):
        for col in range(SIZE):
            cell = (row, col)
            if cell in blocked or cell == game.stairwell:
                continue
            path = bfs(game, game.pos, cell, blocked)
            if not path:
                continue
            degree = sum(1 for _ in neighbors(game, cell, set()))
            key = (manhattan(cell, game.treasure_room), degree, -len(path), cell)
            if best is None or key > best[0]:
                best = (key, path)
    if best is None:
        return safe_last_step(game)
    path = best[1]
    if len(path) < 2:
        return "end"
    nxt = path[1]
    if game.awake and nxt == game.dragon:
        return safe_last_step(game)
    if game.moves_left == 1 and nxt == game.stairwell:
        return safe_last_step(game)
    return direction(game.pos, nxt)


def rush_plan(game: Game) -> list[str] | None:
    """Omniscient dry run. Returns the commands if they win, else None."""
    if not game.carrying and (not game.awake or game.dragon == game.treasure_room):
        return None
    sim = copy.deepcopy(game)
    commands: list[str] = []
    guard = 0
    while sim.phase == "play" and not sim.carrying and guard < 40:
        avoid = {sim.dragon} if sim.awake else {sim.treasure_room}
        cmd = step_toward_goal(sim, sim.treasure_room, avoid)
        if cmd is None:
            return None
        commands.append(cmd)
        sim.command(cmd)
        guard += 1
        if sim.phase == "lost":
            return None
    while sim.phase == "play" and sim.carrying and guard < 80:
        avoid = {sim.dragon} if sim.awake else set()
        if sim.stairwell in avoid and sim.pos != sim.stairwell:
            avoid.discard(sim.stairwell)
        cmd = step_toward_goal(sim, sim.stairwell, avoid - {sim.stairwell})
        if cmd is None:
            cmd = step_toward_goal(sim, sim.stairwell, set())
        if cmd is None:
            return None
        # Stepping onto the dragon outside the stairwell is a wound.
        drow, dcol = {"w": (-1, 0), "s": (1, 0), "d": (0, 1), "a": (0, -1)}[cmd]
        nxt_row = sim.pos[0] + drow
        nxt_col = sim.pos[1] + dcol
        if sim.awake and (nxt_row, nxt_col) == sim.dragon and (nxt_row, nxt_col) != sim.stairwell:
            return None
        commands.append(cmd)
        sim.command(cmd)
        guard += 1
        if sim.phase == "lost":
            return None
    if sim.phase == "won":
        return commands
    return None


def go_home(game: Game) -> str:
    plan = rush_plan(game)
    if plan:
        return plan[0]
    avoid = {game.dragon} if game.awake else set()
    avoid.discard(game.stairwell)
    cmd = step_toward_goal(game, game.stairwell, avoid)
    if cmd is None:
        cmd = step_toward_goal(game, game.stairwell, set())
    return cmd or "end"


def choose_action(game: Game) -> str:
    if game.phase != "play":
        return "q"
    if game.carrying:
        return go_home(game)
    if not game.awake:
        cmd = step_toward_goal(game, game.treasure_room, set())
        return cmd or "end"
    plan = rush_plan(game)
    if plan:
        return plan[0]
    # Already far from the hoard: stop wandering and let the dragon chase.
    if (
        manhattan(game.pos, game.treasure_room) >= 6
        and chebyshev(game.dragon, game.treasure_room) <= 2
        and game.moves_left < game.allowance()
    ):
        return "end"
    if game.moves_left == 1:
        return safe_last_step(game)
    return lure_step(game)


class LabyrinthTests(unittest.TestCase):
    def test_parse_coord(self) -> None:
        self.assertEqual(parse_coord("A1"), (0, 0))
        self.assertEqual(parse_coord("h8"), (7, 7))
        self.assertEqual(parse_coord("d-4"), (3, 3))
        self.assertEqual(parse_coord("D 4"), (3, 3))
        self.assertIsNone(parse_coord("A9"))
        self.assertIsNone(parse_coord("north"))
        self.assertEqual(fmt_coord((0, 0)), "A1")
        self.assertEqual(fmt_coord((3, 3)), "D4")
        self.assertEqual(fmt_coord((7, 7)), "H8")

    def test_maze_is_connected_and_decidable(self) -> None:
        for seed in range(25):
            game = Game(seed=seed)
            self.assertEqual(len(game.h_wall), 7)
            self.assertEqual(len(game.v_wall), 8)
            self.assertTrue(all(isinstance(cell, bool) for row in game.h_wall for cell in row))
            reached = {(0, 0)}
            queue = [(0, 0)]
            while queue:
                cell = queue.pop()
                for _name, nxt in neighbors(game, cell, set()):
                    if nxt not in reached:
                        reached.add(nxt)
                        queue.append(nxt)
            self.assertEqual(len(reached), SIZE * SIZE, f"seed {seed} is not connected")
            count = wall_count(game)
            self.assertGreaterEqual(count, 20, f"seed {seed} walls {count}")
            self.assertLessEqual(count, 49, f"seed {seed} walls {count}")
            self.assertTrue(all(cell == UNKNOWN for row in game.known_h for cell in row))
            self.assertTrue(all(cell == UNKNOWN for row in game.known_v for cell in row))

    def test_treasure_is_far_and_dragon_starts_there(self) -> None:
        for seed in range(20):
            game = Game(seed=seed)
            game.command("D4")
            self.assertGreater(manhattan(game.stairwell, game.treasure_room), 3)
            self.assertEqual(game.dragon, game.treasure_room)
            self.assertEqual(game.chest, game.treasure_room)
            self.assertFalse(game.awake)
            self.assertFalse(game.dragon_visible)
            self.assertFalse(game.chest_known)
            self.assertFalse(game.treasure_room_known)
            self.assertEqual(game.pos, (3, 3))
            self.assertEqual(game.allowance(), 8)

    def test_opening_map_hides_layout_treasure_and_dragon(self) -> None:
        game = Game(seed=2)
        game.command("D4")
        text = game.render()
        rows = grid_rows(text)
        self.assertEqual(len(rows), 8)
        blob = "\n".join(rows)
        self.assertNotIn("D", blob)
        self.assertNotIn("T", blob)
        self.assertNotIn("t", blob)
        self.assertNotIn("*", blob)
        self.assertNotIn("$", blob)
        self.assertIn("@", blob)
        self.assertNotIn(fmt_coord(game.treasure_room), text)
        self.assertNotIn(fmt_coord(game.dragon), text)
        self.assertIn("   +...+...+...+...+...+...+...+...+", text)
        self.assertIn("+---+---+---+---+---+---+---+---+", text)
        for line in rows:
            self.assertEqual(line.count("|"), 2)
            self.assertEqual(line.count(":"), 7)
        self.assertIn("Dragon: asleep", text)
        self.assertIn("Treasure: hidden", text)

    def test_player_sits_under_the_right_column(self) -> None:
        game = Game(seed=1)
        game.command("a1")
        header = column_header(game.render())
        row = grid_rows(game.render())[0]
        self.assertEqual(header.index("A"), row.index("@"))
        game = Game(seed=1)
        game.command("h8")
        header = column_header(game.render())
        row = grid_rows(game.render())[-1]
        self.assertEqual(header.index("H"), row.index("@"))

    def test_wall_ends_the_turn_and_is_remembered(self) -> None:
        game = Game(seed=3)
        game.command("A1")
        game.v_wall[0][0] = True
        messages = game.command("d")
        self.assertTrue(any(m.startswith("[thud]") for m in messages))
        self.assertEqual(game.pos, (0, 0))
        self.assertEqual(game.known_v[0][0], WALL)
        self.assertEqual(game.turn, 2)
        self.assertEqual(game.moves_left, 8)
        self.assertIn("|", grid_rows(game.render())[0])
        again = game.command("d")
        self.assertTrue(any(m.startswith("[mark]") for m in again))
        self.assertEqual(game.turn, 2)
        self.assertEqual(game.moves_left, 8)
        self.assertEqual(game.pos, (0, 0))

    def test_open_passage_is_remembered_and_edge_is_not_a_turn(self) -> None:
        game = Game(seed=4)
        game.command("A1")
        game.v_wall[0][0] = False
        game.v_wall[0][1] = False
        messages = game.command("d")
        self.assertTrue(any(m.startswith("[clear]") for m in messages))
        self.assertEqual(game.pos, (0, 1))
        self.assertEqual(game.known_v[0][0], OPEN)
        self.assertEqual(game.moves_left, 7)
        game.command("d")
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn(".", blob)
        self.assertIn("S", blob)
        self.assertIn("@", blob)
        held = game.command("w")
        self.assertTrue(any(m.startswith("[edge]") for m in held))
        self.assertEqual(game.pos, (0, 2))
        self.assertEqual(game.moves_left, 6)

    def test_stairwell_marker_remains_after_you_leave(self) -> None:
        game = Game(seed=5)
        game.command("D4")
        game.v_wall[3][3] = False
        game.command("d")
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("S", blob)
        self.assertIn("@", blob)

    def test_dragon_wakes_at_three_and_stays_unseen(self) -> None:
        game = Game(seed=6)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.awake = False
        game.dragon_visible = False
        first = game.command("d")  # B1, distance 4
        self.assertFalse(game.awake)
        self.assertFalse(any(m.startswith("[roar]") for m in first))
        self.assertEqual(game.dragon, (0, 5))
        second = game.command("d")  # C1, distance 3
        self.assertTrue(game.awake)
        self.assertTrue(any("Blindscale's Nest" in m for m in second))
        self.assertTrue(any(m.startswith("[roar]") for m in second))
        self.assertEqual(game.dragon, (0, 5))
        self.assertFalse(game.dragon_visible)
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("D", blob)
        self.assertNotIn(fmt_coord(game.treasure_room), game.render())
        self.assertIn("awake, unseen", game.render())

    def test_dragon_flies_one_square_after_the_turn_and_hides_when_you_are_safe(self) -> None:
        game = Game(seed=7)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.awake = True
        game.pos = (0, 2)
        game.steps_taken = 0
        game.moves_left = 8
        game.command("end")
        self.assertEqual(game.dragon, (0, 4))
        self.assertFalse(game.dragon_visible)
        joined = " ".join(game.log)
        self.assertNotIn(fmt_coord((0, 4)), joined)
        game.dragon_visible = True
        game.command("end")
        self.assertEqual(game.dragon, (0, 3))
        self.assertTrue(any("glides to D1" in m for m in game.log[-4:]))
        # Burn: dragon steps onto the player, who is thrown home.
        game.command("end")
        self.assertEqual(game.pos, (0, 0))
        self.assertEqual(game.endurance, 2)
        self.assertEqual(game.allowance(), 6)
        self.assertTrue(game.dragon_visible)
        # Safe in the stairwell, nest unknown: the true marker comes off.
        burn = game.dragon
        game.command("end")
        self.assertEqual(game.dragon, step_back_toward_hoard(burn, game.treasure_room))
        self.assertFalse(game.dragon_visible)
        self.assertNotIn(fmt_coord(game.dragon), " ".join(game.log[-3:]))
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("D", blob)

    def test_three_attacks_kill_and_wounds_shorten_the_stride(self) -> None:
        game = Game(seed=8)
        game.command("A1")
        open_all(game)
        game.awake = True
        game.dragon = (4, 4)
        game.treasure_room = (7, 7)
        game.chest = (7, 7)
        for expected in (2, 1):
            game.pos = (4, 4)
            game.phase = "play"
            messages = game._attack()
            self.assertEqual(game.endurance, expected)
            self.assertEqual(game.pos, game.stairwell)
            self.assertTrue(game.dragon_visible)
            self.assertTrue(any(m.startswith("[fire]") for m in messages))
            self.assertEqual(game.allowance(), 2 + 2 * expected)
        game.pos = (4, 4)
        game.phase = "play"
        messages = game._attack()
        self.assertEqual(game.phase, "lost")
        self.assertEqual(game.endurance, 0)
        self.assertEqual(game.pos, (4, 4))
        self.assertTrue(any(m.startswith("[defeat]") for m in messages))
        self.assertIn("*", "\n".join(grid_rows(game.render())))

    def test_treasure_is_heavy_and_returning_it_wins(self) -> None:
        game = Game(seed=9)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (7, 7)
        game.awake = True
        for _ in range(5):
            game.command("d")
        self.assertTrue(game.carrying)
        self.assertTrue(game.treasure_room_known)
        self.assertEqual(game.pos, (0, 5))
        # Five steps were spent before the burden applies, so the turn ended.
        self.assertEqual(game.steps_taken, 0)
        self.assertEqual(game.allowance(), 4)
        self.assertIn("$", "\n".join(grid_rows(game.render())))
        game.command("a")
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("$", blob)
        self.assertIn("t", blob)
        while game.phase == "play":
            game.command("a")
        self.assertEqual(game.phase, "won")
        self.assertEqual(game.pos, game.stairwell)
        self.assertTrue(game.carrying)
        text = game.render()
        self.assertIn("VICTORY", text)

    def test_pickup_with_steps_to_spare_does_not_drop_the_treasure_early(self) -> None:
        game = Game(seed=10)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 2)
        game.chest = (0, 2)
        game.dragon = (7, 0)
        game.awake = True
        game.command("d")
        game.command("d")
        self.assertTrue(game.carrying)
        self.assertEqual(game.moves_left, 2)
        self.assertEqual(game.phase, "play")

    def test_attack_drops_the_treasure_on_that_square(self) -> None:
        game = Game(seed=11)
        game.command("A1")
        open_all(game)
        game.carrying = True
        game.chest_known = True
        game.treasure_room_known = True
        game.treasure_room = (7, 7)
        game.chest = (7, 7)
        game.awake = True
        game.dragon = (2, 2)
        game.pos = (2, 2)
        game.phase = "play"
        game._attack()
        self.assertFalse(game.carrying)
        self.assertEqual(game.chest, (2, 2))
        self.assertEqual(game.pos, (0, 0))
        blob = "\n".join(grid_rows(game.render()))
        # The dragon is still standing on the dropped chest, so the map shows D.
        self.assertIn("D", blob)
        self.assertIn("t", blob)
        self.assertIn("under the dragon at C3", game.render())

    def test_manual_chase_can_be_won(self) -> None:
        game = Game(seed=12)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 3)
        game.chest = (0, 3)
        game.dragon = (7, 7)
        game.awake = True
        for _ in range(3):
            game.command("d")
        self.assertTrue(game.carrying)
        while game.phase == "play":
            game.command("a")
            self.assertGreater(game.endurance, 0)
        self.assertEqual(game.phase, "won")

    def test_full_maze_is_winnable_without_leaking_the_blind_map(self) -> None:
        for seed in range(8):
            game = Game(seed=seed)
            game.command("A1")
            for _ in range(2500):
                if game.phase != "play":
                    break
                rows = "\n".join(grid_rows(game.render())).replace("?D", "")
                if not game.dragon_visible:
                    self.assertNotIn("D", rows)
                    self.assertNotIn("*", rows)
                if not game.chest_known:
                    self.assertNotIn("T", rows)
                    self.assertNotIn("$", rows)
                if not game.treasure_room_known:
                    self.assertNotIn("t", rows)
                game.command(choose_action(game))
            self.assertEqual(
                game.phase,
                "won",
                f"seed {seed} ended {game.phase} turn {game.turn} "
                f"endurance {game.endurance} you {game.pos} dragon {game.dragon} "
                f"hoard {game.treasure_room}",
            )

    def test_cli_stays_blind(self) -> None:
        probe = Game(seed=1)
        probe.command("D4")
        hidden = fmt_coord(probe.treasure_room)
        completed = subprocess.run(
            [sys.executable, "labyrinth.py", "--seed", "1"],
            input="D4\nw\nq\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("BLINDSCALE'S LAIR", completed.stdout)
        self.assertIn("Stairwell D4", completed.stdout)
        self.assertNotIn(hidden, completed.stdout)
        self.assertNotIn("Treasure room at", completed.stdout)


    def test_compass_letters_do_not_move_and_wasd_does(self) -> None:
        game = Game(seed=13)
        game.command("D4")
        open_all(game)
        game.command("n")
        game.command("e")
        self.assertEqual(game.pos, (3, 3))
        self.assertEqual(game.moves_left, 8)
        game.command("d")
        self.assertEqual(game.pos, (3, 4))
        game.command("w")
        self.assertEqual(game.pos, (2, 4))
        game.command("a")
        self.assertEqual(game.pos, (2, 3))
        game.command("s")
        self.assertEqual(game.pos, (3, 3))

    def test_carrying_halves_the_wounded_stride(self) -> None:
        game = Game(seed=14)
        game.command("A1")
        game.carrying = True
        self.assertEqual(game.allowance(), 4)
        game.endurance = 2
        self.assertEqual(game.allowance(), 3)
        game.endurance = 1
        self.assertEqual(game.allowance(), 2)
        game.carrying = False
        self.assertEqual(game.allowance(), 4)

    def test_guess_tracks_the_dragon_and_can_leave_the_map(self) -> None:
        game = Game(seed=15)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 0)
        game.awake = True
        game.pos = (7, 0)
        game.moves_left = 8
        before = game.moves_left
        messages = game.command("mark H8")
        self.assertEqual(game.dragon_mark, (7, 7))
        self.assertEqual(game.moves_left, before)
        self.assertTrue(any("?D" in m for m in messages))
        game.command("end")
        # Dragon steps south toward A8, so the guess steps south off H8.
        self.assertEqual(game.dragon, (1, 0))
        self.assertIsNone(game.dragon_mark)
        self.assertTrue(any("slips off the map" in m for m in game.log[-4:]))

        game.dragon = (0, 5)
        game.pos = (0, 2)
        game.phase = "play"
        game.command("mark D4")
        game.command("end")
        # Dragon (0,5) toward (0,2) becomes (0,4); the guess shifts west by the same delta.
        self.assertEqual(game.dragon, (0, 4))
        self.assertEqual(game.dragon_mark, (3, 2))
        self.assertIn("?D", "\n".join(grid_rows(game.render())))
        self.assertIn("Guess: ?D at C4", game.render())
        plain = game.render()
        marked = next(line for line in grid_rows(plain) if "?D" in line)
        ordinary = grid_rows(Game(seed=15).render())[0]
        self.assertEqual(len(marked), len(ordinary))

    def test_meeting_the_dragon_replaces_or_wipes_the_guess(self) -> None:
        game = Game(seed=16)
        game.command("A1")
        open_all(game)
        game.awake = True
        game.dragon = (0, 2)
        game.treasure_room = (7, 7)
        game.treasure_room_known = True
        game.chest = (7, 7)
        game.pos = (0, 1)
        game.moves_left = 8
        game.command("mark E4")
        messages = game.command("d")
        self.assertTrue(game.dragon_visible)
        self.assertIsNone(game.dragon_mark)
        self.assertTrue(any("wiped" in m for m in messages))
        self.assertNotIn("?D", "\n".join(grid_rows(game.render())))
        self.assertIn("D", "\n".join(grid_rows(game.render())))
        self.assertEqual(game.endurance, 2)

        game = Game(seed=17)
        game.command("A1")
        open_all(game)
        game.awake = True
        game.stairwell = (0, 0)
        game.pos = (0, 1)
        game.dragon = (0, 0)
        game.treasure_room = (7, 7)
        game.chest = (7, 7)
        game.moves_left = 8
        game.command("mark A1")
        messages = game.command("a")
        self.assertEqual(game.endurance, 3)
        self.assertTrue(game.dragon_visible)
        self.assertIsNone(game.dragon_mark)
        self.assertTrue(any("true dragon" in m for m in messages))
        self.assertEqual(game.pos, (0, 0))
        # Standing on Blindscale shows *, so step aside and the true D remains.
        game.command("d")
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("D", blob)
        self.assertNotIn("?D", blob)

    def test_mark_works_while_the_dragon_sleeps_and_beside_the_true_dragon(self) -> None:
        game = Game(seed=18)
        game.command("A1")
        messages = game.command("mark E4")
        self.assertFalse(game.awake)
        self.assertEqual(game.dragon_mark, (3, 4))
        self.assertEqual(game.moves_left, 8)
        self.assertTrue(any("?D" in m for m in messages))
        self.assertIn("?D", "\n".join(grid_rows(game.render())))
        game.command("end")
        self.assertEqual(game.dragon_mark, (3, 4))

        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.awake = True
        game.dragon_visible = True
        game.treasure_room_known = True
        game.pos = (7, 7)
        game.moves_left = 8
        game.command("mark C1")
        game.command("end")
        # (0, 5) toward (7, 7) steps to (1, 6). C1 is (0, 2); the same step lands on (1, 3).
        self.assertEqual(game.dragon, (1, 6))
        self.assertEqual(game.dragon_mark, (1, 3))
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("D", blob)
        self.assertIn("?D", blob)
        self.assertTrue(game.dragon_visible)

    def test_burn_spills_gold_around_a_hidden_nest(self) -> None:
        game = Game(seed=19)
        game.command("A1")
        open_all(game)
        game.treasure_room = (4, 4)
        game.chest = (4, 4)
        game.dragon = (4, 3)
        game.awake = True
        game.burned = True
        game.endurance = 2
        game.pos = (0, 0)
        game.phase = "play"
        game.moves_left = 8
        game.command("end")
        self.assertEqual(game.dragon, (4, 4))
        self.assertFalse(game.treasure_room_known)
        self.assertFalse(game.dragon_visible)
        joined = " ".join(game.log)
        self.assertIn(
            "You hear Blindscale return to its hoard, as well as the echo of treasure down upon its impact!",
            joined,
        )
        self.assertNotIn(fmt_coord(game.treasure_room), joined)
        self.assertNotIn(fmt_coord(game.treasure_room), game.render())
        ring = {
            (4 + drow, 4 + dcol)
            for drow in (-1, 0, 1)
            for dcol in (-1, 0, 1)
            if not (drow == 0 and dcol == 0)
        }
        self.assertEqual(game.gold_spill, ring)
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("t", blob)
        self.assertEqual(blob.count("g"), 8)

        game.dragon = (7, 7)
        game.dragon_visible = False
        game.chest = (0, 0)
        game.pos = (4, 3)
        game.steps_taken = 0
        game.moves_left = 8
        messages = game.command("d")
        self.assertTrue(game.treasure_room_known)
        self.assertTrue(any("Blindscale's Nest" in m for m in messages))
        game.command("a")
        self.assertIn("t", "\n".join(grid_rows(game.render())))

    def test_a_safe_return_before_any_burn_spills_nothing(self) -> None:
        game = Game(seed=20)
        game.command("A1")
        open_all(game)
        game.treasure_room = (4, 4)
        game.chest = (4, 4)
        game.dragon = (4, 3)
        game.awake = True
        game.pos = (0, 0)
        game.moves_left = 8
        game.command("end")
        self.assertEqual(game.dragon, (4, 4))
        self.assertFalse(game.gold_spill)
        self.assertNotIn("echo of treasure", " ".join(game.log))
        self.assertFalse(game.treasure_room_known)

    def test_a_mark_after_a_burn_keeps_tracking_the_hidden_dragon(self) -> None:
        game = Game(seed=21)
        game.command("A1")
        open_all(game)
        game.treasure_room = (4, 4)
        game.chest = (4, 4)
        game.dragon = (4, 4)
        game.awake = True
        game.burned = True
        game.endurance = 2
        game.dragon_visible = False
        game.pos = (0, 1)
        game.moves_left = 8
        game.command("mark C5")
        game.command("end")
        # Dragon (4, 4) toward the player at (0, 1) steps to (3, 3). C5 is (4, 2).
        self.assertEqual(game.dragon, (3, 3))
        self.assertEqual(game.dragon_mark, (3, 1))
        self.assertFalse(game.dragon_visible)
        self.assertFalse(game.treasure_room_known)
        blob = "\n".join(grid_rows(game.render())).replace("?D", "")
        self.assertNotIn("D", blob)
        self.assertNotIn("t", blob)
        self.assertIn("?D", "\n".join(grid_rows(game.render())))


def step_back_toward_hoard(dragon, hoard):
    from labyrinth import step_toward

    return step_toward(dragon, hoard)


if __name__ == "__main__":
    unittest.main()
