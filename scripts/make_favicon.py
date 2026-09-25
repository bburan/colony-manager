"""Regenerate the favicon set from the DNA mark.

The mark mirrors the navbar brand (Font Awesome's ``fa-dna`` in Bootstrap
``$primary``): a rounded blue tile carrying a white double helix.

``favicon.svg`` is the primary icon -- every current browser prefers it and
scales it losslessly. The ``.ico`` exists for the bare ``/favicon.ico`` hit
and for pinned-tab/bookmark UIs that still ignore SVG, and its 16px frame
drops the base pairs: at that size the three rungs plus two crossings blur
into a solid blob, while the strands alone stay legible.

Run from the repo root with Pillow available::

    python scripts/make_favicon.py
"""

import pathlib

from PIL import Image, ImageDraw

STATIC = pathlib.Path(__file__).resolve().parent.parent / "src" / "colony_manager_gui" / "static"

BLUE = (13, 110, 253)  # Bootstrap $primary, matching the navbar brand
WHITE = (255, 255, 255)

GRID = 32.0  # design grid; every coordinate below is in these units
CORNER = 7.0
STRAND_WIDTH = 2.6
RUNG_WIDTH = 1.7

# Each strand is two cubic half-waves of a cosine (amplitude 6 about x=16),
# the pair mirrored so they cross twice -- the classic helix silhouette.
STRAND_A = [((22, 5), (22, 9), (10, 12), (10, 16)),
            ((10, 16), (10, 20), (22, 23), (22, 27))]
STRAND_B = [((10, 5), (10, 9), (22, 12), (22, 16)),
            ((22, 16), (22, 20), (10, 23), (10, 27))]

RUNG_YS = (7.0, 16.0, 25.0)  # base pairs, placed where the strands are widest


def _bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])


def _sample(strand, steps=60):
    points = []
    for segment in strand:
        for i in range(steps + 1):
            point = _bezier(*segment, i / steps)
            if not points or point != points[-1]:
                points.append(point)
    return points


def _x_at_y(points, y):
    """Where the sampled strand crosses a horizontal line, so rungs land on it."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    raise ValueError(f"no crossing at y={y}")


A = _sample(STRAND_A)
B = _sample(STRAND_B)
RUNGS = [(y, _x_at_y(A, y), _x_at_y(B, y)) for y in RUNG_YS]


def render(size, rungs=RUNGS, strand_width=STRAND_WIDTH):
    """Draw one frame. Pillow won't antialias strokes, so draw big and shrink."""
    scale = 8
    n = size * scale
    f = n / GRID
    image = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, n - 1, n - 1], radius=round(CORNER * f), fill=BLUE)
    for y, x_a, x_b in rungs:
        draw.line([(x_a * f, y * f), (x_b * f, y * f)], fill=WHITE,
                  width=max(1, round(RUNG_WIDTH * f)))
    for points in (A, B):
        draw.line([(x * f, y * f) for x, y in points], fill=WHITE,
                  width=max(1, round(strand_width * f)), joint="curve")
        for x, y in (points[0], points[-1]):  # round off the blunt stroke caps
            r = strand_width * f / 2
            draw.ellipse([x * f - r, y * f - r, x * f + r, y * f + r], fill=WHITE)
    return image.resize((size, size), Image.LANCZOS)


def main():
    # Save from the largest frame: Pillow's ICO writer drops any requested
    # size larger than the base image rather than upscaling it.
    frames = [render(48), render(32), render(16, rungs=(), strand_width=3.0)]
    frames[0].save(STATIC / "favicon.ico", format="ICO",
                   append_images=frames[1:],
                   sizes=[(f.width, f.height) for f in frames])
    render(180).save(STATIC / "apple-touch-icon.png")
    print(f"wrote {STATIC / 'favicon.ico'} and {STATIC / 'apple-touch-icon.png'}")
    print("favicon.svg is hand-maintained -- keep its geometry in step with this file")


if __name__ == "__main__":
    main()
