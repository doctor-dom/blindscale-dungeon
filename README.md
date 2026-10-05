# Blindscale's Lair

A solo ASCII dungeon in the spirit of the 1980 Mattel computer labyrinth. The lair is an 8×8 grid. Each game it builds a new maze, hides Blindscale's Nest, and sets Blindscale to sleep on the treasure. You can see the squares you stand on. You cannot see the walls, the nest, or the dragon until the lair tells you.

You choose the stairwell. That chamber is where you entered the lair, and it is the one place Blindscale will not attack you.

## Play

```bash
python3 labyrinth.py
```

Repeat a lair:

```bash
python3 labyrinth.py --seed 4921
```

At the prompt, name a stairwell such as `D4`. `A1` is the north-west corner and `H8` is the south-east. North is up.

In a terminal, press `w` `a` `s` `d` or the arrow keys. `W` is north, `A` west, `S` south, `D` east. You do not need Enter for each step. `m` marks a guess of the dragon, `.` ends the turn early, `?` shows the rules, and `q` quits. Piped input can use whole words (`north`, `mark E4`, `end`, `quit`) one command per line.

## Rules

- You may cross 8 chambers on a turn. A wall ends the turn, and the wall stays marked.
- Blindscale's fire shortens that stride to 6, then 4. The third attack kills you.
- The treasure is heavy. While you carry it, the stride you have left is cut in half: 8 becomes 4, 6 becomes 3, and 4 becomes 2.
- Blindscale sleeps on the nest, with the treasure, until you come within three chambers of that nest, counting north, south, east, and west. The wake tells you that you are within three chambers of Blindscale's Nest. After each of your turns the dragon flies one chamber toward you, through walls, and may cut a corner.
- Its fire throws you back to the stairwell. A treasure you were carrying drops on the square where you fell.
- Hide in the stairwell and Blindscale turns back toward the nest. If you have never found the nest, the true dragon marker hides again.
- When Blindscale wakes, mark where you think the dragon is (`mark E4`, or the `m` key). The guess is `?D`. It then moves by the same step as Blindscale. Stumble on the real dragon and a wrong `?D` disappears; a correct one becomes the true marker, `D`.
- Win by carrying the treasure into the stairwell.

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

`@` is you, `$` is you with the treasure, `S` is the stairwell. `T` is treasure you have found, `t` is the empty nest, `?D` is your guess, and `D` is Blindscale once you have met the dragon.

## Tests

```bash
python3 -m unittest test_labyrinth.py
```
