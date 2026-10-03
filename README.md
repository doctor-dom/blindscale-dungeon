# Castle Labyrinth

A solo ASCII dungeon in the spirit of the 1980 Mattel computer labyrinth. The castle is an 8×8 grid. Each game it builds a new maze, hides the treasure room, and sets a dragon to sleep on the hoard. You can see the squares you stand on. You cannot see the walls, the hoard, or the dragon until the castle tells you.

This is the basic game: one warrior, solid walls, and the run back to your secret room. Later additions can build on it.

## Play

```bash
python3 labyrinth.py
```

Repeat a castle:

```bash
python3 labyrinth.py --seed 4921
```

At the prompt, name a secret room such as `D4`. `A1` is the north-west corner and `H8` is the south-east. North is up. That room is the one place the dragon will not attack you.

In a terminal, press `n` `s` `e` `w` or the arrow keys. You do not need Enter for each step. `.` ends the turn early, `?` shows the rules, and `q` quits. Piped input can use whole words (`north`, `end`, `quit`) one command per line.

## Rules

- You may cross 8 chambers on a turn. A wall ends the turn, and the wall stays marked.
- The treasure is heavy. While you carry it, the limit is 4 chambers.
- The dragon sleeps until you come within three steps of the hoard, counting north, south, east, and west. It then flies one chamber after each of your turns, through walls and cutting corners, toward you.
- Its fire throws you back to your secret room. Your stride becomes 6, then 4. The third attack kills you. A treasure you were carrying drops on the square where you fell.
- Hide in your secret room and the dragon turns back toward the treasure room. You only get to mark the dragon after it burns you. If it flies off toward a hoard you have never found, you lose sight of it.
- Win by carrying the treasure into your secret room.

The map keeps three kinds of edge. In this corner, B2 was the secret room, the step north of it struck a wall, and the step east was open:

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

`@` is you, `$` is you with the treasure, `S` is your secret room. `T`, `t`, and `D` appear only after you have a reason to mark them.

## Tests

```bash
python3 -m unittest test_labyrinth.py
```
