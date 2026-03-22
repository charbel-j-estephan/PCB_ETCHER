import sys


def read_commands(filename):
    commands = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("I") and len(line) >= 10:
                if len(line) == 10:
                    x = int(line[1:5])
                    y = int(line[5:9])
                    z = int(line[9])
                    commands.append((x, y, z))
                else:
                    print(f"Skipping unexpected line: {line}")
    return commands


def draw_line(x1, y1, x2, y2):
    """Bresenham line algorithm – returns all integer points on the line."""
    points = []
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x2 > x1 else -1
    sy = 1 if y2 > y1 else -1
    err = dx - dy
    x, y = x1, y1
    while True:
        points.append((x, y))
        if x == x2 and y == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return points


def main():
    commands = read_commands("New Text Document.txt")
    if not commands:
        print("No valid commands found.")
        return
    print(f"Total commands: {len(commands)}")

    # Simulate the drawing
    drawn_points = set()
    prev_x, prev_y = commands[0][0], commands[0][1]  # first command (pen up)
    for i in range(1, len(commands)):
        x, y, z = commands[i]
        if z == 1:
            line_points = draw_line(prev_x, prev_y, x, y)
            drawn_points.update(line_points)
        prev_x, prev_y = x, y

    if not drawn_points:
        print("No drawn points.")
        return

    # Bounding box
    xs = [p[0] for p in drawn_points]
    ys = [p[1] for p in drawn_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    print(f"X range: {min_x}–{max_x}  (width {max_x-min_x+1})")
    print(f"Y range: {min_y}–{max_y}  (height {max_y-min_y+1})")

    # Try matplotlib for a proper plot
    try:
        import matplotlib.pyplot as plt

        x_vals, y_vals = zip(*drawn_points)
        plt.figure(figsize=(10, 8))
        plt.scatter(x_vals, y_vals, s=1, c="black")
        plt.gca().invert_yaxis()  # so that increasing Y goes upward (optional)
        plt.title("Drawn Path")
        plt.xlabel("X")
        plt.ylabel("Y")
        plt.show()
    except ImportError:
        print("Matplotlib not available. Generating ASCII art (scaled).")
        # Scale to fit typical terminal (max 80 columns, 40 rows)
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        scale_x = max(1, width // 80 + 1)
        scale_y = max(1, height // 40 + 1)
        grid_w = (width // scale_x) + 1
        grid_h = (height // scale_y) + 1
        grid = [[" " for _ in range(grid_w)] for _ in range(grid_h)]
        for x, y in drawn_points:
            gx = (x - min_x) // scale_x
            gy = (y - min_y) // scale_y
            grid[gy][gx] = "#"
        # Print rows from top (max Y) to bottom (min Y)
        for row in reversed(grid):
            print("".join(row))


if __name__ == "__main__":
    main()
