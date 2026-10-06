# Blindscale's Lair

A solo ASCII dungeon in the spirit of the 1980 Mattel computer labyrinth. The lair is an 8×8 grid. Each game it builds a new maze, hides Blindscale's Nest, and sets Blindscale to sleep on the treasure. You can see the squares you stand on. You cannot see the walls, the nest, or the dragon until the lair tells you.

You choose a difficulty, then the stairwell. Easy builds exactly 25 walls, and every chamber can be reached. Normal keeps the original seeded maze, where each unused passage is walled at random and the count changes with the seed. The stairwell is where you entered the lair, and it is the one place Blindscale will not attack you.

## Play

```bash
python3 blindscale.py
```

Repeat a lair, and pick the difficulty up front:

```bash
python3 blindscale.py --seed 4921 --difficulty normal
```

In a terminal the game asks for the difficulty when you leave that flag off. At the next prompt, name a stairwell such as `D4`. `A1` is the north-west corner and `H8` is the south-east. North is up.

In a terminal, press `w` `a` `s` `d` or the arrow keys. `W` is north, `A` west, `S` south, `D` east. You do not need Enter for each step. **Space** or `.` ends the turn early. To mark: press **`m`**, then **`t`** (treasure `T?`) or **`d`** (dragon `D?`), then type a chamber such as `E4` and Enter. Piped input can still use one line per command (`mt E4`, `md E4`, `end`, `quit`).

## Sense flags (`mt` / `md`)

- **`mt E4`** — toggle **`T?`** (possible treasure room) on that chamber. Run the same command again to clear it.
- **`md E4`** — toggle **`D?`** (dragon guess) on that chamber. Same toggle to clear.

**Easy** maintains **`T?`** and **`D?`** for you; these commands are ignored.

**Normal** — you may **`mt`** / **`md`** at any time. When Blindscale **first roars**, you may place **many `T?`** but **only one `D?`** until your next step or `end`. That roar **`D?`** is remembered: if it was on the true starting chamber, the **first burn** can mark the treasure room as **`T`**. After the roar moment, you may place more **`D?`** tokens freely. Each **`D?`** chases you from its own cell; every **`D?`** vanishes when you are burned.

## Rules

- You may cross 8 chambers on a turn. A wall ends the turn, and the wall stays marked.
- Blindscale's fire shortens that stride to 6, then 4. The third attack kills you.
- The treasure is heavy. While you carry it, the stride you have left is cut in half: 8 becomes 4, 6 becomes 3, and 4 becomes 2.
- Blindscale sleeps on the nest, with the treasure, until you come within three chambers of that nest, counting north, south, east, and west. The roar tells you that you are within three chambers of the treasure. After each of your turns the dragon flies one chamber toward you, through walls, and may cut a corner.
- You can snatch the treasure without being burned only by taking it in the nest while Blindscale is in that same room. Enter any other chamber the dragon occupies and you are burned at once, including a room where dropped treasure and the dragon are together.
- Its fire throws you back to the stairwell. A treasure you were carrying drops on the square where you fell. The chamber glows as `D*` for two of your steps. Dropped treasure then shows as `t`.
- Within one chamber of Blindscale — straight on or diagonal — the lair warns you: "You can almost feel Blindscale's breadth and sense that it is one chamber away!"
- Hide in the stairwell and Blindscale turns back toward the nest. If you have never entered the nest, the true dragon marker hides again. The treasure room stays blank until you walk into it (`T`), unless your roar **`D?`** was on the true starting chamber and the first burn proves it (`T`).
- After Blindscale burns you, its return to the nest spills gold one chamber north, south, east, and west. The map shows `g` only after you enter that chamber. The treasure room itself is not revealed by gold.
- Win by carrying the treasure into the stairwell.
- On defeat, **`Again? [y/n] Or reveal? [r]`** lets you show the true treasure room on the map before starting over.

The map keeps three kinds of edge. In this corner, B2 was the stairwell, the step north of it struck a wall, and the step east was open:

```
     A   B   C
   +---+---+---+
 1 |   :   :   |
   +...+---+...+
 2 |   : S   @ |
   +...+...+...+
```

```
...  and  :    not tried yet
---  and  |    a wall you struck
a gap          a passage you have walked
```

`@` is you, `$` is you with the treasure, `S` is the stairwell. `T` is the treasure room once found, `t` is treasure sitting in a chamber, `T?` is a possible treasure room, `D?` is your dragon guess, `g` is gold you have walked into, and `D` is Blindscale once you have met the dragon. `D*` glows where Blindscale burned you and fades after two steps. The status ends with the steps still left this turn, as a count and a bar.

## Tests

```bash
python3 -m unittest test_labyrinth.py
```
