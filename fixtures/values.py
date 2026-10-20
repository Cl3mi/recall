"""Turn a character-class shape back into a conforming value.

shape_of reduces a value to a closed alphabet so it can leave a sealed window. This
inverts it, so the fixture's identifier columns carry the formats the real corpus uses
rather than formats we guessed. The invariant is a round trip: shape_of(from_shape(s))
must equal s, and that is what the tests assert.
"""

from __future__ import annotations

import random
import string

# Must shape back to '#': not a digit, not a letter, not whitespace, and not one of
# shape_of's preserved separators (-./:). '/' would shape to itself, so it is excluded.
_OTHER = "+(),*"


def from_shape(shape: str, rng: random.Random) -> str:
    """A value whose shape_of() is exactly `shape`."""
    out = []
    for char in shape:
        if char == "D":
            out.append(rng.choice(string.digits))
        elif char in ("A", "L"):
            out.append(rng.choice(string.ascii_uppercase))
        elif char == "a":
            out.append(rng.choice(string.ascii_lowercase))
        elif char == "_":
            out.append(" ")
        elif char == "#":
            out.append(rng.choice(_OTHER))
        else:
            out.append(char)  # -./: are kept literally by shape_of
    return "".join(out)


def pick_shape(mix: list[tuple[str, float]], rng: random.Random) -> str:
    """Choose a shape according to its measured weight."""
    shapes = [s for s, _ in mix]
    weights = [w for _, w in mix]
    return rng.choices(shapes, weights=weights, k=1)[0]
