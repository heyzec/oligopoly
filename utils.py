DEBUG = True

RED = (1, 0, 0)
GREEN = (0, 1, 0)
BLUE = (0, 0, 1)
BLACK = (0, 0, 0)
MAGENTA = (1, 0, 1)
CYAN = (0, 1, 1)
YELLOW = (1, 1, 0)
ORANGE = (1, 0.5, 0)
PURPLE = (0.5, 0, 0.5)
PINK = (1, 0.75, 0.75)
RAINBOW = [RED, ORANGE, YELLOW, GREEN, BLUE, PURPLE, PINK]

def to_cents(s: str):
    return int(s.replace(',', '').replace('.', ''))  # thousand sep and decimal

def draw(page, rect, color=BLACK):
    page.draw_rect(
        rect,
        color=color,
        width=2               # line width
    )

def show(doc):
    tmpfile = "/tmp/output.pdf"
    doc.save(tmpfile)
    # os.system(f"xdg-open {tmpfile}")
    print(f"===Showing output PDF at {tmpfile}===")
