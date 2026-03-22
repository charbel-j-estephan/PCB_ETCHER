import re
import io
import os
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

# ==========================================================
# CONFIGURATION: 20cm x 18cm WORK AREA
# ==========================================================
MAX_X_MM = 200  # Hard limit: 20 cm
MAX_Y_MM = 180  # Hard limit: 18 cm

# NOTE: Output is in INTEGER MILLIMETRES, not steps.
# The PIC firmware (CONV_X / CONV_Y) multiplies mm x 25
# internally to get steps. Python must NOT pre-multiply.


def parse_gerber_divisor(lines):
    """
    Read %FSLAXijYij*% header and return the raw divisor + unit flag.

    Gerber format Xij:
      i = integer digits
      j = decimal digits
      raw divisor = 10^j

    Returns (divisor: float, unit_inch: bool)
    """
    format_regex = re.compile(r"%FSLA[XY](\d)(\d)")
    unit_inch = False

    for line in lines:
        if "%MOIN%" in line:
            unit_inch = True
        m = format_regex.search(line)
        if m:
            j = int(m.group(2))
            divisor = float(10**j)
            print(
                f"[LOG] Gerber format X{m.group(1)}{m.group(2)} "
                f"-> raw divisor = {divisor:.0f}"
            )
            return divisor, unit_inch

    print("[LOG] No format header found, defaulting divisor=10000")
    return 10000.0, unit_inch


def gcode_to_custom(gerber_text):
    lines = gerber_text.splitlines()

    coord_regex = re.compile(r"([XY])([-+]?\d*\.?\d+)")
    d_code_regex = re.compile(r"D(01|02|03)")

    divisor, unit_inch = parse_gerber_divisor(lines)

    # ----------------------------------------------------------
    # PASS 1: Parse coordinates
    # ----------------------------------------------------------
    raw_points = []
    current_x = 0.0
    current_y = 0.0
    pen_down = False

    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("%") or "G04" in line:
            continue

        d_match = d_code_regex.search(line)
        if d_match:
            code = d_match.group(1)
            pen_down = code == "01" or code == "03"

        coords = dict(coord_regex.findall(line))
        if coords:
            if "X" in coords:
                current_x = float(coords["X"]) / divisor
            if "Y" in coords:
                current_y = float(coords["Y"]) / divisor

            if unit_inch:
                current_x *= 25.4
                current_y *= 25.4

            min_x = min(min_x, current_x)
            max_x = max(max_x, current_x)
            min_y = min(min_y, current_y)
            max_y = max(max_y, current_y)

            raw_points.append({"x": current_x, "y": current_y, "pen": pen_down})

    if not raw_points:
        return "ERROR: NO_DATA"

    design_w = max_x - min_x
    design_h = max_y - min_y

    # ----------------------------------------------------------
    # AUTO-CORRECT: if bounding box is unreasonably small,
    # the divisor was too large. Multiply up by 10 until sane.
    # This fixes the common KiCad X34 quirk where X100000
    # with divisor=10000 gives 10mm instead of 100mm.
    # ----------------------------------------------------------
    correction = 1.0
    while design_w * correction < 0.5 or design_h * correction < 0.5:
        correction *= 10.0
        if correction > 1e7:
            break

    if correction != 1.0:
        print(
            f"[LOG] Auto-correcting by x{correction:.0f} "
            f"(effective divisor = {divisor / correction:.0f})"
        )
        raw_points = [
            {"x": p["x"] * correction, "y": p["y"] * correction, "pen": p["pen"]}
            for p in raw_points
        ]
        min_x *= correction
        max_x *= correction
        min_y *= correction
        max_y *= correction
        design_w = max_x - min_x
        design_h = max_y - min_y

    print(f"[LOG] Final design size : {design_w:.2f} mm x {design_h:.2f} mm")
    print(f"[LOG] Work area         : {MAX_X_MM} mm x {MAX_Y_MM} mm")

    # ----------------------------------------------------------
    # PASS 2: Dimension check
    # ----------------------------------------------------------
    if design_w > MAX_X_MM or design_h > MAX_Y_MM:
        raise ValueError(
            f"Gerber too large! {design_w:.1f} x {design_h:.1f} mm "
            f"exceeds work area {MAX_X_MM} x {MAX_Y_MM} mm."
        )

    # ----------------------------------------------------------
    # PASS 3: Generate instructions in INTEGER MILLIMETRES
    #
    # Frame: I XXXX YYYY Z LF   (10 bytes stored in PIC BUF)
    #   BUF+0   = 'I'
    #   BUF+1-4 = X mm, 4 ASCII decimal digits
    #   BUF+5-8 = Y mm, 4 ASCII decimal digits
    #   BUF+9   = pen state: '1'=down, '2'=up
    #   LF      = terminator, not stored in BUF
    #
    # PIC CONV_X/CONV_Y convert mm to steps (x25) internally.
    # ----------------------------------------------------------
    output_instructions = []

    for pt in raw_points:
        x_mm = pt["x"] - min_x
        y_mm = pt["y"] - min_y

        x_int = int(round(x_mm))
        y_int = int(round(y_mm))

        x_final = max(0, min(MAX_X_MM, x_int))
        y_final = max(0, min(MAX_Y_MM, y_int))

        z_bit = "1" if pt["pen"] else "2"

        instr = f"I{x_final:04d}{y_final:04d}{z_bit}"
        assert len(instr) == 10, f"Frame length error: '{instr}' len={len(instr)}"

        output_instructions.append(instr)

    output_instructions.append("END")

    # Print first 10 lines to server log for debugging
    print("[LOG] First instructions:")
    for line in output_instructions[:10]:
        print(f"  {repr(line)}  len={len(line)}")

    return "\n".join(output_instructions)


# ==========================================================
# FLASK API ENDPOINTS
# ==========================================================


@app.route("/convert", methods=["POST"])
def convert():
    if "gerber" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["gerber"]
    try:
        content = file.read().decode("utf-8", errors="ignore")
        result = gcode_to_custom(content)

        return send_file(
            io.BytesIO(result.encode("utf-8")),
            mimetype="text/plain",
            as_attachment=True,
            download_name="instructions.txt",
        )
    except ValueError as ve:
        print(f"[ERROR] {str(ve)}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        print(f"[CRASH] {str(e)}")
        return jsonify({"error": "Internal Server Error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
