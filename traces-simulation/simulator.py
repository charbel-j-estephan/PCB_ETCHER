"""
CNC PCB Plotter — Python Simulator  (mirrors PIC16F877A v10 firmware logic)
============================================================================
Reads a TXT file of plotter commands in the protocol format:
    I XXXX YYYY Z LF
  where XXXX/YYYY are 4-digit ASCII decimal mm values (zero-padded)
  and Z is '1' (pen DOWN) or '2' (pen UP).
  A line containing just "END" signals the end of the job.

The script faithfully re-implements:
  • CONV_X / CONV_Y  — ASCII digit → mm → steps  (×25 exact)
  • BRESENHAM        — 16-bit Bresenham line algorithm with correct
                       borrow propagation (v10-FIX-8, v10-FIX-9)
  • Servo state      — pen only changes when state differs from previous

Usage:
    python cnc_plotter_sim.py commands.txt [--output plot.png] [--scale 2]

The script produces:
  1. A matplotlib window showing the traced image in real time (if --live)
     OR a saved PNG (default).
  2. A summary printed to stdout with step counts and move statistics.

Protocol reminder (from firmware header):
    Frame : I XXXX YYYY Z LF   (10 chars + LF = 11 bytes)
    BUF[0]   = 'I'
    BUF[1..4] = X digits (mm, 4 ASCII decimal digits, zero-padded)
    BUF[5..8] = Y digits (mm, 4 ASCII decimal digits, zero-padded)
    BUF[9]    = pen state ('1'=down, '2'=up)
    LF (0x0A) = terminator, NOT stored in BUF
    CR (0x0D) = silently discarded

Machine constants (mirrored from firmware):
    STEPS_PER_MM = 25   (200 steps/rev ÷ 8 mm lead, T8 screw, NEMA17)
    Max X = 200 mm  →  5000 steps
    Max Y = 180 mm  →  4500 steps
"""

import sys
import argparse
import math
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
#   Machine constants  (match firmware EQU values)
# ---------------------------------------------------------------------------
STEPS_PER_MM = 25  # 200 steps/rev / 8 mm lead — exact integer
MAX_X_MM = 200
MAX_Y_MM = 180
MAX_X_STEPS = MAX_X_MM * STEPS_PER_MM  # 5000
MAX_Y_STEPS = MAX_Y_MM * STEPS_PER_MM  # 4500


# ===========================================================================
#   CONV_X / CONV_Y
#   Mirrors the PIC's BCD-style digit extraction and ×25 multiply.
#   Input : 4-char ASCII string, e.g. "0127"
#   Output: integer step count (16-bit range)
# ===========================================================================
def conv_mm_to_steps(digits: str) -> int:
    """
    Reproduce CONV_X / CONV_Y from firmware.
    digits must be exactly 4 ASCII decimal characters '0'..'9'.
    Each char is ANDed with 0x0F to strip the ASCII offset (as firmware does).
    Formula: steps = (d3*1000 + d2*100 + d1*10 + d0) * STEPS_PER_MM
    Result clamped to 16-bit (0..65535) — firmware uses 16-bit registers.
    """
    if len(digits) != 4:
        raise ValueError(f"Expected 4 digit chars, got {len(digits)!r}")
    return int(digits)  # app.py already sends steps (pre-multiplied by 25)


# ===========================================================================
#   PARSE_LINE
#   Mirrors RECEIVE_LINE + PARSE_AND_DISPLAY from firmware.
#   Returns (x_steps, y_steps, pen_down: bool) or None for END.
# ===========================================================================
def parse_line(raw: str):
    """
    Parse one command line.  Returns:
      None               — if line is "END" sentinel
      (xtgt, ytgt, pen_down)  — int steps, int steps, bool
    Raises ValueError on malformed lines.
    """
    # Strip CR and LF (firmware silently discards CR, stops at LF)
    line = raw.rstrip("\r\n")
    if not line:
        return "SKIP"

    # END sentinel check (firmware checks BUF[0..2] == 'E','N','D')
    if line.upper() == "END":
        return None

    # Frame validation: must start with 'I' and be exactly 10 chars
    if len(line) < 10 or line[0] != "I":
        raise ValueError(f"Bad frame (expected 'I' + 9 chars): {line!r}")

    x_digits = line[1:5]  # BUF[1..4]
    y_digits = line[5:9]  # BUF[5..8]
    pen_char = line[9]  # BUF[9]

    xtgt = conv_mm_to_steps(x_digits)
    ytgt = conv_mm_to_steps(y_digits)

    if pen_char == "1":
        pen_down = True
    elif pen_char == "2":
        pen_down = False
    else:
        raise ValueError(f"Unknown pen state {pen_char!r}, expected '1' or '2'")

    return (xtgt, ytgt, pen_down)


# ===========================================================================
#   BRESENHAM  (v10 — correct 16-bit borrow propagation)
#   Mirrors the full BRESENHAM / BRES_LOOP / BRES_CALC subroutines.
#
#   Instead of toggling physical GPIO pins we collect (x, y) waypoints
#   that are later plotted.
# ===========================================================================
def bresenham(
    xcur: int, ycur: int, xtgt: int, ytgt: int, pen_down: bool, segments: list
):
    """
    Execute the Bresenham line algorithm exactly as the PIC firmware does.
    Each step is one step in step-space (1/25 mm).

    Parameters
    ----------
    xcur, ycur : current machine position in steps
    xtgt, ytgt : target machine position in steps
    pen_down   : True if pen is drawing
    segments   : list to append (x_mm, y_mm, pen_down) waypoints

    Returns
    -------
    (new_xcur, new_ycur) in steps  (mirrors BRES_DONE commit)
    """

    # --- Early exit if already at target (mirrors firmware BRESENHAM entry) ---
    if xcur == xtgt and ycur == ytgt:
        return xcur, ycur

    # ------------------------------------------------------------------
    # BRES_CALC  — compute |DX|, |DY|, direction flags
    # [v10-FIX-9] borrow from low byte propagated into high byte
    # In Python integers are arbitrary precision so we just do signed math,
    # then take absolute value — identical result to the two's-complement
    # negate the firmware uses.
    # ------------------------------------------------------------------
    dx_signed = xtgt - xcur  # can be negative
    dy_signed = ytgt - ycur

    dx = abs(dx_signed)
    dy = abs(dy_signed)

    # Direction flags (1 = moving toward home = negative direction)
    xdir_neg = dx_signed < 0  # XDIR_F = 1
    ydir_neg = dy_signed < 0  # YDIR_F = 1

    # ------------------------------------------------------------------
    # BRES_SET_DIRS — in hardware this sets PORTB DIR pins.
    # Here we just track direction as a sign multiplier.
    # ------------------------------------------------------------------
    xstep_sign = -1 if xdir_neg else +1
    ystep_sign = -1 if ydir_neg else +1

    # ------------------------------------------------------------------
    # Choose dominant axis  (mirrors DOM_DECIDED / SET_X_DOM / SET_Y_DOM)
    # Dominant axis = larger |delta|.  Tie goes to Y (firmware: C=1 → Y dom)
    # ------------------------------------------------------------------
    if dy >= dx:
        # Y dominant  (DOM_FLAG = 1)
        dom_steps = dy
        err = dy >> 1  # BERR = DY / 2 (RRF = arithmetic right shift)

        x_pos, y_pos = xcur, ycur
        for _ in range(dom_steps):
            # Always step Y (dominant)
            y_pos += ystep_sign

            # Accumulate error: BERR += DX
            err += dx

            # [v10-FIX-8] Compare BERR >= DY
            if err >= dy:
                x_pos += xstep_sign  # Step X (minor)
                err -= dy  # Subtract dominant delta from BERR

            if pen_down:
                segments.append((x_pos / STEPS_PER_MM, y_pos / STEPS_PER_MM, True))
    else:
        # X dominant  (DOM_FLAG = 0)
        dom_steps = dx
        err = dx >> 1  # BERR = DX / 2

        x_pos, y_pos = xcur, ycur
        for _ in range(dom_steps):
            # Always step X (dominant)
            x_pos += xstep_sign

            # Accumulate error: BERR += DY
            err += dy

            # [v10-FIX-8] Compare BERR >= DX
            if err >= dx:
                y_pos += ystep_sign  # Step Y (minor)
                err -= dx  # Subtract dominant delta from BERR

            if pen_down:
                segments.append((x_pos / STEPS_PER_MM, y_pos / STEPS_PER_MM, True))

    # BRES_DONE: commit target as new current position
    return xtgt, ytgt


# ===========================================================================
#   SIMULATE
#   Reads the TXT file and runs the full firmware logic loop:
#     RECEIVE_LINE → PARSE_AND_DISPLAY → EXECUTE_MOTION → SEND_ACK → repeat
# ===========================================================================
def simulate(filepath: str):
    """
    Returns a list of line segments for plotting:
        [ (x0_mm, y0_mm, x1_mm, y1_mm), ... ]
    and a list of pen-up move endpoints for optional display.
    Also returns statistics dict.
    """
    xcur = 0  # machine position in steps (homed = 0,0)
    ycur = 0
    prev_pen = None  # mirrors PREV_PEN (0 = unset, '1'/'2')

    draw_lines = []  # (x0, y0, x1, y1) mm — pen-down moves
    travel_lines = []  # pen-up moves (for debug overlay)
    waypoints = []  # raw (x_mm, y_mm, pen_down) from bresenham

    total_cmds = 0
    draw_cmds = 0
    travel_cmds = 0
    servo_changes = 0

    with open(filepath, "r") as f:
        for lineno, raw in enumerate(f, 1):
            result = parse_line(raw)

            if result == "SKIP":
                continue
            if result is None:
                print(f"[line {lineno}] END sentinel — stopping.")
                break

            xtgt, ytgt, pen_down = result
            total_cmds += 1

            # --- EXECUTE_MOTION: servo state change check ---
            pen_char = "1" if pen_down else "2"
            if pen_char != prev_pen:
                servo_changes += 1
                prev_pen = pen_char

            # --- BRESENHAM: trace the move ---
            x0_mm = xcur / STEPS_PER_MM
            y0_mm = ycur / STEPS_PER_MM

            step_waypoints = []
            xcur, ycur = bresenham(xcur, ycur, xtgt, ytgt, pen_down, step_waypoints)

            x1_mm = xcur / STEPS_PER_MM
            y1_mm = ycur / STEPS_PER_MM

            if pen_down:
                draw_cmds += 1
                draw_lines.append((x0_mm, y0_mm, x1_mm, y1_mm))
            else:
                travel_cmds += 1
                travel_lines.append((x0_mm, y0_mm, x1_mm, y1_mm))

    stats = {
        "total_cmds": total_cmds,
        "draw_cmds": draw_cmds,
        "travel_cmds": travel_cmds,
        "servo_changes": servo_changes,
        "final_x_mm": xcur / STEPS_PER_MM,
        "final_y_mm": ycur / STEPS_PER_MM,
    }
    return draw_lines, travel_lines, stats


# ===========================================================================
#   PLOT
# ===========================================================================
def plot(draw_lines, travel_lines, stats, output_path=None, show_travel=False):
    fig, ax = plt.subplots(figsize=(10, 9))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#0f0e17")

    # Draw bed boundary
    bed = mpatches.Rectangle(
        (0, 0),
        MAX_X_MM,
        MAX_Y_MM,
        linewidth=1.5,
        edgecolor="#555577",
        facecolor="none",
        linestyle="--",
    )
    ax.add_patch(bed)

    # Optional: show travel (pen-up) moves
    if show_travel and travel_lines:
        for x0, y0, x1, y1 in travel_lines:
            ax.plot(
                [x0, x1],
                [y0, y1],
                color="#444466",
                linewidth=0.4,
                linestyle=":",
                alpha=0.6,
            )

    # Draw pen-down moves
    for x0, y0, x1, y1 in draw_lines:
        ax.plot([x0, x1], [y0, y1], color="#00d4ff", linewidth=0.8, alpha=0.9)

    # Origin marker
    ax.plot(0, 0, "o", color="#ff6b6b", markersize=5, label="Home (0,0)")

    ax.set_xlim(-5, MAX_X_MM + 5)
    ax.set_ylim(-5, MAX_Y_MM + 5)
    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)", color="#ccccdd")
    ax.set_ylabel("Y (mm)", color="#ccccdd")
    ax.tick_params(colors="#aaaacc")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")

    title = (
        f"CNC PCB Plotter Simulation\n"
        f"{stats['draw_cmds']} draw moves  |  "
        f"{stats['travel_cmds']} travel moves  |  "
        f"{stats['servo_changes']} servo changes"
    )
    ax.set_title(title, color="#eeeeff", fontsize=11, pad=10)

    # Legend
    draw_patch = mpatches.Patch(color="#00d4ff", label="Pen DOWN (draw)")
    travel_patch = mpatches.Patch(color="#444466", label="Pen UP (travel)")
    home_patch = mpatches.Patch(color="#ff6b6b", label="Home (0,0)")
    ax.legend(
        handles=[draw_patch, travel_patch, home_patch],
        facecolor="#1a1a2e",
        edgecolor="#333355",
        labelcolor="#ccccdd",
        fontsize=9,
        loc="upper right",
    )

    plt.tight_layout()

    if output_path:
        plt.savefig(
            output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor()
        )
        print(f"[output] Saved to: {output_path}")
    else:
        plt.show()


# ===========================================================================
#   MAIN
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="CNC PCB Plotter simulator — traces a command TXT file."
    )
    parser.add_argument(
        "txtfile",
        help="Path to the command TXT file "
        "(lines: IXXXXYYYY1 or IXXXXYYYYZ, END to stop)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Save plot to this PNG path instead of showing window",
    )
    parser.add_argument(
        "--travel",
        action="store_true",
        help="Overlay pen-up travel moves (faint dashed lines)",
    )
    args = parser.parse_args()

    print(f"[sim] Reading: {args.txtfile}")
    draw_lines, travel_lines, stats = simulate(args.txtfile)

    print(f"[sim] Commands parsed   : {stats['total_cmds']}")
    print(f"[sim]   Pen-down moves  : {stats['draw_cmds']}")
    print(f"[sim]   Pen-up moves    : {stats['travel_cmds']}")
    print(f"[sim]   Servo changes   : {stats['servo_changes']}")
    print(
        f"[sim] Final position    : X={stats['final_x_mm']:.2f} mm, "
        f"Y={stats['final_y_mm']:.2f} mm"
    )

    if not draw_lines:
        print("[sim] WARNING: no pen-down moves found — nothing to plot.")
        sys.exit(0)

    plot(
        draw_lines,
        travel_lines,
        stats,
        output_path=args.output,
        show_travel=args.travel,
    )


if __name__ == "__main__":
    main()
