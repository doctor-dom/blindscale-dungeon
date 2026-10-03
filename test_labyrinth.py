"""Rules and blindness tests for Castle Labyrinth."""

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


def grid_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"\s+\d \|", line)]


def wall_count(game: Game) -> int:
    return sum(cell for row in game.h_wall for cell in row) + sum(
        cell for row in game.v_wall for cell in row
    )


def neighbors(game: Game, cell: tuple[int, int], blocked: set[tuple[int, int]]):
    row, col = cell
    for name, (drow, dcol) in (("n", (-1, 0)), ("s", (1, 0)), ("e", (0, 1)), ("w", (0, -1))):
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
    return {(-1, 0): "n", (1, 0): "s", (0, 1): "e", (0, -1): "w"}[(drow, dcol)]


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


def flee(game: Game) -> str:
    best = None
    for name, nxt in neighbors(game, game.pos, set()):
        if game.awake and nxt == game.dragon:
            continue
        if not game.awake and nxt == game.treasure_room:
            continue
        score = (
            chebyshev(nxt, game.dragon) if game.awake else 0,
            manhattan(nxt, game.treasure_room),
            name,
        )
        if best is None or score > best[0]:
            best = (score, name)
    return best[1] if best else "end"


def lure_step(game: Game) -> str:
    blocked = {game.dragon} if game.awake else {game.treasure_room}
    best = None
    for row in range(SIZE):
        for col in range(SIZE):
            cell = (row, col)
            if cell in blocked:
                continue
            path = bfs(game, game.pos, cell, blocked)
            if not path:
                continue
            degree = sum(1 for _ in neighbors(game, cell, set()))
            key = (manhattan(cell, game.treasure_room), degree, -len(path), cell)
            if best is None or key > best[0]:
                best = (key, path)
    if best is None:
        return flee(game)
    path = best[1]
    if len(path) < 2:
        return flee(game)
    nxt = path[1]
    if game.awake and nxt == game.dragon:
        return flee(game)
    return direction(game.pos, nxt)


def rush_plan(game: Game) -> list[str] | None:
    """Omniscient dry run. Returns the commands if they win, else None."""
    if not game.awake or game.dragon == game.treasure_room and not game.carrying:
        if not game.carrying:
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
        if sim.secret in avoid and sim.pos != sim.secret:
            avoid.discard(sim.secret)
        cmd = step_toward_goal(sim, sim.secret, avoid - {sim.secret})
        if cmd is None:
            cmd = step_toward_goal(sim, sim.secret, set())
        if cmd is None:
            return None
        # Stepping onto the dragon outside the secret room is a wound.
        nxt_row = sim.pos[0] + {"n": -1, "s": 1, "e": 0, "w": 0}[cmd]
        nxt_col = sim.pos[1] + {"n": 0, "s": 0, "e": 1, "w": -1}[cmd]
        if sim.awake and (nxt_row, nxt_col) == sim.dragon and (nxt_row, nxt_col) != sim.secret:
            return None
        commands.append(cmd)
        sim.command(cmd)
        guard += 1
        if sim.phase == "lost":
            return None
    if sim.phase == "won":
        return commands
    return None


def choose_action(game: Game) -> str:
    if game.phase != "play":
        return "q"
    if game.carrying or game.awake:
        plan = rush_plan(game)
        if plan:
            return plan[0]
    if game.awake and not game.carrying:
        if chebyshev(game.pos, game.dragon) <= 2 or game.moves_left == 1:
            return flee(game)
        return lure_step(game)
    cmd = step_toward_goal(game, game.treasure_room, set())
    return cmd or "end"


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
            self.assertGreater(manhattan(game.secret, game.treasure_room), 3)
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
        lines = game.render().splitlines()
        header = next(line for line in lines if "B" in line and "H" in line and "A" in line)
        row = grid_rows(game.render())[0]
        self.assertEqual(header.index("A"), row.index("@"))
        game = Game(seed=1)
        game.command("h8")
        header = next(
            line for line in game.render().splitlines() if line.strip().startswith("A") or "H" in line
        )
        # The letter row is the one whose stripped form is mostly letters.
        header = next(
            line
            for line in game.render().splitlines()
            if "A" in line and "H" in line and "---" not in line and "|" not in line
        )
        row = grid_rows(game.render())[-1]
        self.assertEqual(header.index("H"), row.index("@"))

    def test_wall_ends_the_turn_and_is_remembered(self) -> None:
        game = Game(seed=3)
        game.command("A1")
        game.v_wall[0][0] = True
        messages = game.command("e")
        self.assertTrue(any(m.startswith("[thud]") for m in messages))
        self.assertEqual(game.pos, (0, 0))
        self.assertEqual(game.known_v[0][0], WALL)
        self.assertEqual(game.turn, 2)
        self.assertEqual(game.moves_left, 8)
        self.assertIn("|", grid_rows(game.render())[0])
        again = game.command("e")
        self.assertTrue(any(m.startswith("[mark]") for m in again))
        self.assertEqual(game.turn, 2)
        self.assertEqual(game.moves_left, 8)
        self.assertEqual(game.pos, (0, 0))

    def test_open_passage_is_remembered_and_edge_is_not_a_turn(self) -> None:
        game = Game(seed=4)
        game.command("A1")
        game.v_wall[0][0] = False
        messages = game.command("e")
        self.assertTrue(any(m.startswith("[clear]") for m in messages))
        self.assertEqual(game.pos, (0, 1))
        self.assertEqual(game.known_v[0][0], OPEN)
        self.assertEqual(game.moves_left, 7)
        self.assertIn(".", "\n".join(grid_rows(game.render())))
        held = game.command("n")
        self.assertTrue(any(m.startswith("[edge]") for m in held))
        self.assertEqual(game.pos, (0, 1))
        self.assertEqual(game.moves_left, 7)

    def test_secret_marker_remains_after_you_leave(self) -> None:
        game = Game(seed=5)
        game.command("D4")
        game.v_wall[3][3] = False
        game.command("e")
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
        first = game.command("e")  # B1, distance 4
        self.assertFalse(game.awake)
        self.assertFalse(any(m.startswith("[roar]") for m in first))
        self.assertEqual(game.dragon, (0, 5))
        second = game.command("e")  # C1, distance 3
        self.assertTrue(game.awake)
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
        # Safe in the secret room, hoard unknown: the dragon leaves and the marker comes off.
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
            self.assertEqual(game.pos, game.secret)
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
            game.command("e")
        self.assertTrue(game.carrying)
        self.assertTrue(game.treasure_room_known)
        self.assertEqual(game.pos, (0, 5))
        # Five steps were spent before the burden applies, so the turn ended.
        self.assertEqual(game.steps_taken, 0)
        self.assertEqual(game.allowance(), 4)
        self.assertIn("$", "\n".join(grid_rows(game.render())))
        self.assertIn("t", "\n".join(grid_rows(game.render())))
        while game.phase == "play":
            game.command("w")
        self.assertEqual(game.phase, "won")
        self.assertEqual(game.pos, game.secret)
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
        game.command("e")
        game.command("e")
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
        self.assertIn("T", blob)
        self.assertIn("t", blob)

    def test_manual_chase_can_be_won(self) -> None:
        game = Game(seed=12)
        game.command("A1")
        open_all(game)
        game.treasure_room = (0, 3)
        game.chest = (0, 3)
        game.dragon = (7, 7)
        game.awake = True
        for _ in range(3):
            game.command("e")
        self.assertTrue(game.carrying)
        while game.phase == "play":
            game.command("w")
            self.assertGreater(game.endurance, 0)
        self.assertEqual(game.phase, "won")

    def test_full_maze_is_winnable_without_leaking_the_blind_map(self) -> None:
        for seed in range(8):
            game = Game(seed=seed)
            game.command("A1")
            for _ in range(2500):
                if game.phase != "play":
                    break
                rows = "\n".join(grid_rows(game.render()))
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
            input="D4\nn\nq\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CASTLE LABYRINTH", completed.stdout)
        self.assertIn("Secret room D4", completed.stdout)
        self.assertNotIn(hidden, completed.stdout)
        self.assertNotIn("Treasure room at", completed.stdout)


def step_back_toward_hoard(dragon, hoard):
    from labyrinth import step_toward

    return step_toward(dragon, hoard)


if __name__ == "__main__":
    unittest.main()
