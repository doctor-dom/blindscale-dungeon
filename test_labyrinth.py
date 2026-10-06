"""Rules and blindness tests for Blindscale's Lair."""

from __future__ import annotations

import copy
import re
import subprocess
import sys
import unittest

from blindscale import (
    OPEN,
    SIZE,
    UNKNOWN,
    WALL,
    Game,
    _VT_ARROWS,
    _WIN_ARROWS,
    _command_from_char,
    _mark_command_from_kind_and_cell,
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
            self.assertEqual(game.difficulty, "normal")

    def test_easy_has_25_walls_and_every_chamber_is_reachable(self) -> None:
        for seed in range(15):
            game = Game(seed=seed, difficulty="easy")
            again = Game(seed=seed, difficulty="easy")
            self.assertEqual(wall_count(game), 25)
            self.assertEqual(game.h_wall, again.h_wall)
            self.assertEqual(game.v_wall, again.v_wall)
            reached = {(0, 0)}
            queue = [(0, 0)]
            while queue:
                cell = queue.pop()
                for _name, nxt in neighbors(game, cell, set()):
                    if nxt not in reached:
                        reached.add(nxt)
                        queue.append(nxt)
            self.assertEqual(len(reached), SIZE * SIZE, f"easy seed {seed} is split")

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
        self.assertTrue(any("echoing roar" in m for m in second))
        self.assertTrue(any("three chambers of the treasure" in m for m in second))
        self.assertTrue(any(m.startswith("[roar]") for m in second))
        self.assertEqual(game.dragon, (0, 5))
        self.assertFalse(game.dragon_visible)
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("D", blob)
        self.assertNotIn(fmt_coord(game.treasure_room), game.render())
        self.assertIn("awake, unseen", game.render())

    def test_first_roar_counts_cardinal_steps_only(self) -> None:
        """Three chambers means north, south, east, and west. A diagonal is not a shortcut."""
        game = Game(seed=36)
        game.command("A1")
        open_all(game)
        game.treasure_room = (4, 4)
        game.chest = (4, 4)
        game.dragon = (4, 4)
        game.awake = False
        game.pos = (1, 0)
        game.steps_taken = 0
        game.moves_left = 8
        # (1, 1) is three diagonal steps from the nest, and six cardinal steps.
        far = game.command("d")
        self.assertEqual(game.pos, (1, 1))
        self.assertEqual(manhattan(game.pos, game.treasure_room), 6)
        self.assertEqual(chebyshev(game.pos, game.treasure_room), 3)
        self.assertFalse(game.awake)
        self.assertFalse(any(m.startswith("[roar]") for m in far))

        game.pos = (2, 1)
        game.steps_taken = 0
        game.moves_left = 8
        # (2, 2) is two diagonal steps from the nest, and four cardinal steps.
        still = game.command("d")
        self.assertEqual(manhattan(game.pos, game.treasure_room), 4)
        self.assertFalse(game.awake)
        self.assertFalse(any(m.startswith("[roar]") for m in still))

        game.pos = (4, 0)
        game.steps_taken = 0
        game.moves_left = 8
        # (4, 1) is three chambers due west of the nest.
        heard = game.command("d")
        self.assertEqual(game.pos, (4, 1))
        self.assertEqual(manhattan(game.pos, game.treasure_room), 3)
        self.assertTrue(game.awake)
        self.assertTrue(any(m.startswith("[roar]") for m in heard))

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
        # The live dragon hides. The burn itself stays as a glowing D* until you step.
        self.assertIn("D*", blob)
        self.assertNotIn("D", blob.replace("D*", ""))

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
        self.assertIn("D*", "\n".join(grid_rows(game.render())))

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
        self.assertIn("T", blob)
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
        # The burn glow covers the drop until it fades.
        self.assertIn("D*", blob)
        self.assertNotIn("t", blob)
        game.burn_at = None
        game.dragon = (7, 7)
        game.dragon_visible = False
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("t", blob)
        game.dragon = (2, 2)
        game.dragon_visible = True
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
                rows = (
                    "\n".join(grid_rows(game.render()))
                    .replace("D?", "")
                    .replace("T?", "")
                    .replace("D*", "")
                )
                if not game.dragon_visible:
                    self.assertNotIn("D", rows.replace("D?", "").replace("D*", ""))
                    self.assertNotIn("*", rows)
                if not game.chest_known:
                    self.assertNotIn("t", rows)
                    self.assertNotIn("$", rows)
                if not game.treasure_room_known and not game.nest_marked:
                    self.assertNotIn("T", rows.replace("T?", ""))
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
            [sys.executable, "blindscale.py", "--seed", "1"],
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


    def test_mark_command_from_kind_and_cell(self) -> None:
        self.assertEqual(_mark_command_from_kind_and_cell("t", "e4"), "mt e4")
        self.assertEqual(_mark_command_from_kind_and_cell("d", "E4"), "md e4")
        self.assertIsNone(_mark_command_from_kind_and_cell("t", "  "))

    def test_single_keys_map_to_moves_on_windows_and_unix(self) -> None:
        self.assertEqual(_command_from_char("w"), "w")
        self.assertEqual(_command_from_char("W"), "w")
        self.assertEqual(_command_from_char("a"), "a")
        self.assertEqual(_command_from_char("S"), "s")
        self.assertEqual(_command_from_char("d"), "d")
        self.assertEqual(_command_from_char("m"), "m")
        self.assertEqual(_command_from_char("Q"), "q")
        self.assertEqual(_command_from_char("?"), "?")
        self.assertEqual(_command_from_char("."), "end")
        self.assertEqual(_command_from_char(" "), "end")
        self.assertEqual(_command_from_char("\r"), "end")
        self.assertEqual(_command_from_char("x"), "")
        self.assertEqual(_WIN_ARROWS["H"], "w")
        self.assertEqual(_WIN_ARROWS["P"], "s")
        self.assertEqual(_WIN_ARROWS["K"], "a")
        self.assertEqual(_WIN_ARROWS["M"], "d")
        self.assertEqual(_VT_ARROWS["\x1b[A"], "w")
        self.assertEqual(_VT_ARROWS["\x1b[B"], "s")
        self.assertEqual(_VT_ARROWS["\x1b[C"], "d")
        self.assertEqual(_VT_ARROWS["\x1b[D"], "a")
        with self.assertRaises(KeyboardInterrupt):
            _command_from_char("\x03")

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

    def test_dragon_tokens_chase_on_their_own(self) -> None:
        game = Game(seed=15)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.pos = (0, 2)
        game.awake = True
        game.moves_left = 8
        game.command("md d4")
        game.command("end")
        self.assertEqual(game.dragon, (0, 4))
        self.assertIn((2, 2), game.dragon_tokens)
        self.assertNotIn((3, 2), game.dragon_tokens)
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("D?", blob)
        self.assertIn("D? placed: 1", game.render())

    def test_burn_clears_dragon_tokens(self) -> None:
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
        game.command("md e4")
        messages = game.command("d")
        self.assertTrue(game.dragon_visible)
        self.assertEqual(game.dragon_tokens, set())
        self.assertTrue(any(m.startswith("[fire]") for m in messages))
        self.assertNotIn("D?", "\n".join(grid_rows(game.render())))
        self.assertEqual(game.endurance, 2)

    def test_easy_spawns_treasure_guesses_at_the_roar(self) -> None:
        game = Game(seed=50, difficulty="easy")
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.pos = (0, 0)
        game.moves_left = 8
        game.command("d")
        game.command("d")
        game.command("d")
        self.assertTrue(game.awake)
        self.assertIn(game.treasure_room, game.treasure_room_guesses)
        self.assertGreater(len(game.treasure_room_guesses), 1)
        self.assertGreater(len(game.dragon_tokens), 0)
        self.assertIn("T?", "\n".join(grid_rows(game.render())))

    def test_roar_allows_only_one_dragon_token(self) -> None:
        game = Game(seed=51)
        game.command("A1")
        game.at_roar_moment = True
        first = game.command("md a1")
        second = game.command("md b1")
        self.assertTrue(any("D?" in m for m in first))
        self.assertTrue(any("only one" in m.lower() for m in second))
        self.assertEqual(len(game.dragon_tokens), 1)
        game.command("md a1")
        third = game.command("md c1")
        self.assertTrue(any("D?" in m for m in third))
        self.assertEqual(len(game.dragon_tokens), 1)

    def test_mt_md_toggle_anytime(self) -> None:
        game = Game(seed=18)
        game.command("A1")
        placed = game.command("mt e4")
        self.assertIn((3, 4), game.treasure_room_guesses)
        self.assertTrue(any("T?" in m for m in placed))
        game.command("mt e4")
        self.assertNotIn((3, 4), game.treasure_room_guesses)
        game.command("md d4")
        self.assertIn((3, 3), game.dragon_tokens)
        game.command("md d4")
        self.assertNotIn((3, 3), game.dragon_tokens)

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
        cardinal = {(3, 4), (5, 4), (4, 3), (4, 5)}
        self.assertEqual(game.gold_spill, cardinal)
        self.assertNotIn((3, 3), game.gold_spill)
        self.assertNotIn((5, 5), game.gold_spill)
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("T", blob.replace("T?", ""))
        self.assertNotIn("g", blob)
        self.assertFalse(game.gold_seen)

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
        self.assertEqual(game.pos, (4, 3))
        self.assertIn((4, 3), game.gold_seen)
        self.assertEqual(game.gold_seen, {(4, 3)})
        # Standing on the splash shows you. Step off and that room keeps g.
        game.command("a")
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("T", blob)
        self.assertEqual(blob.count("g"), 1)
        self.assertNotIn((3, 3), game.gold_seen)
        self.assertNotIn((4, 5), game.gold_seen)

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
        game.command("md c5")
        game.command("end")
        # Dragon (4, 4) toward the player at (0, 1) steps to (3, 3). C5 is (4, 2).
        self.assertEqual(game.dragon, (3, 3))
        self.assertIn((3, 1), game.dragon_tokens)
        self.assertFalse(game.dragon_visible)
        self.assertFalse(game.treasure_room_known)
        blob = "\n".join(grid_rows(game.render())).replace("D?", "")
        self.assertNotIn("D", blob.replace("D*", ""))
        self.assertNotIn("T", blob.replace("T?", ""))
        self.assertIn("D?", "\n".join(grid_rows(game.render())))

    def test_snatch_from_the_nest_does_not_burn(self) -> None:
        game = Game(seed=22)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 2)
        game.chest = (0, 2)
        game.dragon = (0, 2)
        game.awake = False
        game.pos = (0, 1)
        game.steps_taken = 0
        game.moves_left = 8
        messages = game.command("d")
        self.assertTrue(game.carrying)
        self.assertEqual(game.endurance, 3)
        self.assertEqual(game.phase, "play")
        self.assertEqual(game.pos, (0, 2))
        self.assertTrue(game.treasure_room_known)
        self.assertTrue(game.dragon_visible)
        self.assertTrue(any("snatch" in m for m in messages))
        self.assertFalse(any(m.startswith("[fire]") for m in messages))
        self.assertTrue(any("echoing roar" in m for m in messages))

    def test_snatch_that_ends_the_turn_still_spares_you_once(self) -> None:
        game = Game(seed=23)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 2)
        game.chest = (0, 2)
        game.dragon = (0, 2)
        game.awake = True
        game.pos = (0, 1)
        game.steps_taken = 3
        game.moves_left = 5
        messages = game.command("d")
        self.assertTrue(game.carrying)
        self.assertEqual(game.endurance, 3)
        self.assertEqual(game.pos, (0, 2))
        self.assertFalse(any(m.startswith("[fire]") for m in messages))
        # The next turn in the nest is an ordinary encounter.
        again = game.command("end")
        self.assertEqual(game.endurance, 2)
        self.assertFalse(game.carrying)
        self.assertEqual(game.chest, (0, 2))
        self.assertEqual(game.pos, (0, 0))
        self.assertTrue(any(m.startswith("[fire]") for m in again))

    def test_dropped_treasure_under_the_dragon_burns_on_entry(self) -> None:
        game = Game(seed=24)
        game.command("A1")
        open_all(game)
        game.treasure_room = (7, 7)
        game.chest = (0, 2)
        game.chest_known = True
        game.dragon = (0, 2)
        game.awake = True
        game.pos = (0, 1)
        game.steps_taken = 0
        game.moves_left = 8
        messages = game.command("d")
        self.assertFalse(game.carrying)
        self.assertEqual(game.chest, (0, 2))
        self.assertEqual(game.endurance, 2)
        self.assertEqual(game.pos, (0, 0))
        self.assertTrue(any(m.startswith("[fire]") for m in messages))
        self.assertFalse(any("snatch" in m or m.startswith("[chime]") for m in messages))
        self.assertTrue(any("C1" in m for m in messages))
        blob = "\n".join(grid_rows(game.render()))
        # The glowing burn covers the dropped chest until you have stepped away.
        self.assertIn("D*", blob)
        self.assertNotIn("t", blob)
        self.assertNotIn("D", blob.replace("D?", "").replace("D*", ""))
        self.assertFalse(game.dragon_visible)
        self.assertIn("Burn: glowing D* at C1", game.render())

    def test_death_reveal_marks_the_treasure_room(self) -> None:
        game = Game(seed=60)
        game.command("A1")
        game.treasure_room = (4, 4)
        game.phase = "lost"
        messages = game.reveal_treasure_room_after_death()
        self.assertTrue(any("treasure room was at" in m for m in messages))
        self.assertTrue(game.treasure_room_known)
        self.assertIn("T", "\n".join(grid_rows(game.render())))
        again = game.reveal_treasure_room_after_death()
        self.assertTrue(any("already marked" in m for m in again))

    def test_steps_remaining_are_spelled_out(self) -> None:
        game = Game(seed=30)
        game.command("A1")
        open_all(game)
        text = game.render()
        self.assertIn("Steps left 8", text)
        self.assertIn("Steps remaining: 8 steps of 8  [########]", text)
        game.command("d")
        text = game.render()
        self.assertIn("Steps left 7", text)
        self.assertIn("Steps remaining: 7 steps of 8  [#######.]", text)
        colored = game.render(color=True)
        self.assertIn("\033[1;96mSteps remaining: 7 steps of 8  [#######.]", colored)

    def test_burn_glows_then_fades_after_two_steps(self) -> None:
        game = Game(seed=31)
        game.command("A1")
        open_all(game)
        game.treasure_room = (4, 4)
        game.chest = (4, 4)
        game.dragon = (0, 2)
        game.awake = True
        game.pos = (0, 1)
        game.steps_taken = 0
        game.moves_left = 8
        messages = game.command("d")
        self.assertTrue(any(m.startswith("[fire]") for m in messages))
        self.assertEqual(game.pos, (0, 0))
        self.assertEqual(game.burn_at, (0, 2))
        self.assertEqual(game.burn_moves, 0)
        text = game.render()
        self.assertIn("D*", "\n".join(grid_rows(text)))
        self.assertNotIn("@*", "\n".join(grid_rows(text)))
        self.assertIn("Burn: glowing D* at C1 fades after 2 more steps.", text)
        self.assertIn("\033[1;5;93;41mD*", game.render(color=True))
        burned_row = grid_rows(text)[0]
        ordinary = grid_rows(Game(seed=31).render())[0]
        self.assertEqual(len(burned_row), len(ordinary))
        # Waiting is not a step, so the glow stays.
        game.command("end")
        self.assertEqual(game.burn_moves, 0)
        self.assertIn("D*", "\n".join(grid_rows(game.render())))
        # First step: the burn chamber still glows.
        game.steps_taken = 0
        game.moves_left = 8
        game.command("s")
        self.assertEqual(game.burn_moves, 1)
        blob = "\n".join(grid_rows(game.render()))
        self.assertIn("D*", blob)
        self.assertIn("Burn: glowing D* at C1 fades after 1 more step.", game.render())
        # Second step: the mark is gone.
        game.steps_taken = 0
        game.moves_left = 8
        game.command("s")
        self.assertIsNone(game.burn_at)
        blob = "\n".join(grid_rows(game.render()))
        self.assertNotIn("D*", blob)
        self.assertNotIn("Burn:", game.render())

    def test_warns_one_chamber_from_the_dragon_including_diagonals(self) -> None:
        warning = (
            "[near] You can almost feel Blindscale's breadth and sense that it is one chamber away!"
        )
        game = Game(seed=32)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 4)
        game.chest = (0, 4)
        game.dragon = (0, 4)
        game.awake = True
        game.pos = (0, 0)
        game.steps_taken = 0
        game.moves_left = 8
        game.command("d")  # B1, three chambers from the dragon
        two_away = game.command("d")  # C1, two chambers west of E1
        self.assertFalse(any(m == warning for m in two_away))
        beside = game.command("d")  # D1, orthogonally beside the dragon at E1
        self.assertIn(warning, beside)
        self.assertEqual(game.pos, (0, 3))
        self.assertEqual(game.endurance, 3)

        game = Game(seed=33)
        game.command("A1")
        open_all(game)
        game.treasure_room = (3, 3)
        game.chest = (3, 3)
        game.dragon = (2, 2)
        game.awake = True
        game.pos = (0, 0)
        game.steps_taken = 0
        game.moves_left = 8
        game.command("d")  # B1, still two away on the diagonal
        diagonal = game.command("s")  # B2, a diagonal step from C3
        self.assertEqual(game.pos, (1, 1))
        self.assertEqual(chebyshev(game.pos, game.dragon), 1)
        self.assertIn(warning, diagonal)
        self.assertEqual(game.endurance, 3)

        game = Game(seed=34)
        game.command("A1")
        open_all(game)
        game.treasure_room = (7, 7)
        game.chest = (7, 7)
        game.dragon = (0, 5)
        game.awake = True
        game.pos = (0, 4)
        game.steps_taken = 0
        game.moves_left = 8
        onto = game.command("d")
        self.assertTrue(any(m.startswith("[fire]") for m in onto))
        self.assertNotIn(warning, onto)

        game = Game(seed=35)
        game.command("A1")
        open_all(game)
        game.treasure_room = (7, 7)
        game.chest = (7, 7)
        game.dragon = (2, 3)
        game.awake = True
        game.pos = (2, 0)
        game.steps_taken = 0
        game.moves_left = 8
        still_far = game.command("end")
        self.assertEqual(game.dragon, (2, 2))
        self.assertNotIn(warning, still_far)
        approached = game.command("end")
        self.assertEqual(game.dragon, (2, 1))
        self.assertIn(warning, approached)
        self.assertEqual(game.pos, (2, 0))
        self.assertEqual(game.endurance, 3)

    def test_a_burn_marks_the_nest_when_the_starting_mark_was_true(self) -> None:
        game = Game(seed=40)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.awake = True
        game.pos = (0, 2)
        game.steps_taken = 0
        game.moves_left = 8
        game.roar_dragon_placement = (0, 5)
        game.treasure_room_guesses.add((0, 5))
        game.command("end")
        game.command("end")
        burned = game.command("end")
        self.assertTrue(any(m.startswith("[fire]") for m in burned))
        self.assertTrue(any("treasure room is marked" in m for m in burned))
        self.assertTrue(game.nest_marked)
        self.assertFalse(game.treasure_room_known)
        self.assertIn("T", "\n".join(grid_rows(game.render())))

        game = Game(seed=41)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 5)
        game.awake = True
        game.pos = (0, 2)
        game.steps_taken = 0
        game.moves_left = 8
        game.roar_dragon_placement = (7, 7)
        game.command("end")
        game.command("end")
        missed = game.command("end")
        self.assertTrue(any(m.startswith("[fire]") for m in missed))
        self.assertFalse(game.nest_marked)
        self.assertNotIn("T", "\n".join(grid_rows(game.render())).replace("T?", ""))

        game = Game(seed=42)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 5)
        game.chest = (0, 5)
        game.dragon = (0, 3)
        game.awake = True
        game.pos = (0, 1)
        game.steps_taken = 0
        game.moves_left = 8
        game.roar_dragon_placement = (0, 3)
        game.command("end")
        later = game.command("end")
        self.assertTrue(any(m.startswith("[fire]") for m in later))
        self.assertFalse(game.nest_marked)
        self.assertNotIn("T", "\n".join(grid_rows(game.render())).replace("T?", ""))


def step_back_toward_hoard(dragon, hoard):
    from blindscale import step_toward

    return step_toward(dragon, hoard)


if __name__ == "__main__":
    unittest.main()
