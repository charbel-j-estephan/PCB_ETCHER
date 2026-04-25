import re
import os
import math
import uuid
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ==========================================================
# CONFIGURATION: WORK AREA
# ==========================================================
MAX_X_MM    = 250   # Hard limit X mm
MAX_Y_MM    = 220   # Hard limit Y mm
PEN_WIDTH   = 0.4   # mm — pen tip diameter
FILL_STEP   = PEN_WIDTH * 0.5
TRACE_PASSES = 1
MIRROR_X    = True

# NOTE: Output is in INTEGER STEPS (mm × 25).


def parse_gerber_divisor(lines):
    fmt_re = re.compile(r"%FSLA[XY](\d)(\d)")
    unit_inch = False
    for line in lines:
        if "%MOIN%" in line:
            unit_inch = True
        m = fmt_re.search(line)
        if m:
            divisor = float(10 ** int(m.group(2)))
            print(f"[LOG] Gerber format X{m.group(1)}{m.group(2)} -> divisor={divisor:.0f}")
            return divisor, unit_inch
    print("[LOG] No format header found, defaulting divisor=10000")
    return 10000.0, unit_inch


def parse_apertures(lines):
    ap_re = re.compile(r"%ADD(\d+)([CRO]),([^*]+)\*%")
    apertures = {}
    for line in lines:
        m = ap_re.search(line)
        if m:
            num    = int(m.group(1))
            shape  = m.group(2)
            params = [float(x) for x in m.group(3).split("X")]
            apertures[num] = {"shape": shape, "params": params}
            print(f"[LOG] Aperture D{num:02d}: {shape} {params} mm")
    return apertures


def pad_filled_moves(cx, cy, shape, params):
    moves = []

    if shape == "C":
        r = params[0] / 2
        n = max(12, int(2 * math.pi * r / PEN_WIDTH))
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            moves.append((cx + r * math.cos(a), cy + r * math.sin(a), i > 0))
        y = cy - r + FILL_STEP / 2
        go_right = True
        while y <= cy + r:
            hc = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
            if hc > 1e-6:
                if go_right:
                    moves += [(cx - hc, y, False), (cx + hc, y, True)]
                else:
                    moves += [(cx + hc, y, False), (cx - hc, y, True)]
                go_right = not go_right
            y += FILL_STEP
        x = cx - r + FILL_STEP / 2
        go_up = True
        while x <= cx + r:
            vc = math.sqrt(max(0.0, r * r - (x - cx) ** 2))
            if vc > 1e-6:
                moves += (
                    [(x, cy - vc, False), (x, cy + vc, True)]
                    if go_up
                    else [(x, cy + vc, False), (x, cy - vc, True)]
                )
                go_up = not go_up
            x += FILL_STEP

    elif shape == "R":
        w, h   = params[0], params[1]
        x0, y0 = cx - w / 2, cy - h / 2
        x1, y1 = cx + w / 2, cy + h / 2
        for _ in range(2):
            moves += [(x0,y0,False),(x1,y0,True),(x1,y1,True),(x0,y1,True),(x0,y0,True)]
        y = y0 + FILL_STEP
        go_right = True
        while y <= y1 - FILL_STEP / 2:
            moves += ([(x0,y,False),(x1,y,True)] if go_right else [(x1,y,False),(x0,y,True)])
            go_right = not go_right
            y += FILL_STEP
        x = x0 + FILL_STEP
        go_up = True
        while x <= x1 - FILL_STEP / 2:
            moves += ([(x,y0,False),(x,y1,True)] if go_up else [(x,y1,False),(x,y0,True)])
            go_up = not go_up
            x += FILL_STEP

    elif shape == "O":
        w, h = params[0], params[1]
        r    = min(w, h) / 2
        if w >= h:
            rh = (w - h) / 2
            n  = max(8, int(math.pi * r / PEN_WIDTH))
            for i in range(n + 1):
                a = -math.pi / 2 + math.pi * i / n
                moves.append((cx + rh + r * math.cos(a), cy + r * math.sin(a), i > 0))
            moves.append((cx - rh, cy + r, True))
            for i in range(1, n + 1):
                a = math.pi / 2 + math.pi * i / n
                moves.append((cx - rh + r * math.cos(a), cy + r * math.sin(a), True))
            moves.append((cx + rh, cy - r, True))
            y = cy - r + FILL_STEP / 2
            go_right = True
            while y <= cy + r:
                cap    = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
                xl, xr = cx - rh - cap, cx + rh + cap
                moves += ([(xl,y,False),(xr,y,True)] if go_right else [(xr,y,False),(xl,y,True)])
                go_right = not go_right
                y += FILL_STEP
        else:
            rh = (h - w) / 2
            n  = max(8, int(math.pi * r / PEN_WIDTH))
            for i in range(n + 1):
                a = math.pi * i / n
                moves.append((cx + r * math.cos(a), cy + rh + r * math.sin(a), i > 0))
            moves.append((cx - r, cy - rh, True))
            for i in range(1, n + 1):
                a = math.pi + math.pi * i / n
                moves.append((cx + r * math.cos(a), cy - rh + r * math.sin(a), True))
            moves.append((cx + r, cy + rh, True))
            y = cy - rh - r + FILL_STEP / 2
            go_right = True
            while y <= cy + rh + r:
                dy = abs(y - cy)
                if dy <= rh:
                    xl, xr = cx - r, cx + r
                else:
                    cap    = math.sqrt(max(0.0, r * r - (dy - rh) ** 2))
                    xl, xr = cx - cap, cx + cap
                if xr - xl > 1e-6:
                    moves += ([(xl,y,False),(xr,y,True)] if go_right else [(xr,y,False),(xl,y,True)])
                    go_right = not go_right
                y += FILL_STEP

    return moves


def gcode_to_custom(gerber_text):
    lines     = gerber_text.splitlines()
    coord_re  = re.compile(r"([XY])([-+]?\d*\.?\d+)")
    dcode_re  = re.compile(r"D(01|02|03)")
    dsel_re   = re.compile(r"(?:G54)?D(\d+)\*")

    divisor, unit_inch = parse_gerber_divisor(lines)
    apertures          = parse_apertures(lines)

    raw_points  = []
    current_x   = 0.0
    current_y   = 0.0
    pen_down    = False
    current_aperture = None
    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")

    def track(x, y):
        nonlocal min_x, max_x, min_y, max_y
        min_x = min(min_x, x); max_x = max(max_x, x)
        min_y = min(min_y, y); max_y = max(max_y, y)

    for line in lines:
        line = line.strip()
        if not line or line.startswith("%") or "G04" in line:
            continue
        for m in dsel_re.finditer(line):
            anum = int(m.group(1))
            if anum >= 10:
                current_aperture = anum
        d_match = dcode_re.search(line)
        if d_match:
            pen_down = d_match.group(1) == "01"
        coords = dict(coord_re.findall(line))
        if coords:
            if "X" in coords: current_x = float(coords["X"]) / divisor
            if "Y" in coords: current_y = float(coords["Y"]) / divisor
            if unit_inch:
                current_x *= 25.4; current_y *= 25.4
            track(current_x, current_y)
            if d_match and d_match.group(1) == "03":
                raw_points.append({"type":"pad","cx":current_x,"cy":current_y,"ap":current_aperture})
            else:
                raw_points.append({"type":"move","x":current_x,"y":current_y,"pen":pen_down,"src":"trace"})

    if not raw_points:
        return "ERROR: NO_DATA"

    design_w = max_x - min_x
    design_h = max_y - min_y

    correction = 1.0
    while design_w * correction < 1.0 or design_h * correction < 1.0:
        correction *= 10.0
        if correction > 1e9:
            break
    if correction != 1.0:
        print(f"[LOG] Auto-correcting x{correction:.0f}")
        min_x *= correction; max_x *= correction
        min_y *= correction; max_y *= correction
        design_w = max_x - min_x; design_h = max_y - min_y

    print(f"[LOG] Final design: {design_w:.2f} x {design_h:.2f} mm")

    if design_w > MAX_X_MM or design_h > MAX_Y_MM:
        raise ValueError(
            f"Gerber too large! {design_w:.1f} x {design_h:.1f} mm "
            f"exceeds {MAX_X_MM} x {MAX_Y_MM} mm."
        )

    expanded = []
    for pt in raw_points:
        if pt["type"] == "pad":
            cx = pt["cx"] * correction
            cy = pt["cy"] * correction
            ap = apertures.get(pt["ap"])
            if ap:
                for ox, oy, op in pad_filled_moves(cx, cy, ap["shape"], ap["params"]):
                    expanded.append({"x": ox, "y": oy, "pen": op, "src": "pad"})
            else:
                expanded.append({"x": cx, "y": cy, "pen": False, "src": "pad"})
        else:
            expanded.append({
                "x": pt["x"] * correction, "y": pt["y"] * correction,
                "pen": pt["pen"], "src": pt.get("src", "trace"),
            })

    if TRACE_PASSES > 1:
        redundant = []
        i = 0
        while i < len(expanded):
            pt = expanded[i]
            redundant.append(pt)
            if (not pt["pen"] and i+1 < len(expanded)
                    and expanded[i+1]["pen"]
                    and expanded[i+1].get("src") == "trace"):
                j = i + 1
                stroke = []
                while j < len(expanded) and expanded[j]["pen"]:
                    stroke.append(expanded[j]); j += 1
                for _ in range(TRACE_PASSES - 1):
                    redundant.append({"x":stroke[0]["x"],"y":stroke[0]["y"],"pen":False,"src":"travel"})
                    redundant.extend(stroke)
            i += 1
        expanded = redundant

    output_instructions = []
    MARGIN_MM = 2.0
    for pt in expanded:
        x_norm = pt["x"] - min_x
        y_norm = pt["y"] - min_y
        if MIRROR_X:
            x_norm = design_w - x_norm
        x_final = max(0, min(MAX_X_MM * 400, int(round((x_norm + MARGIN_MM) * 400))))
        y_final = max(0, min(MAX_Y_MM * 400, int(round((y_norm + MARGIN_MM) * 400))))
        z_bit   = "1" if pt["pen"] else "2"
        instr   = f"I{x_final:06d}{y_final:06d}{z_bit}"
        assert len(instr) == 14, f"Frame length error: '{instr}'"
        output_instructions.append(instr)

    output_instructions.append("END")

    print("[LOG] First instructions:")
    for ln in output_instructions[:10]:
        print(f"  {repr(ln)}  len={len(ln)}")
    print(f"[LOG] Total: {len(output_instructions) - 1} instructions + END")

    return "\n".join(output_instructions)


# ==========================================================
# HELPERS
# ==========================================================

def _valid_job_id(job_id):
    """Accept only 32-char lowercase hex strings (UUID without hyphens)."""
    return (
        job_id
        and len(job_id) == 32
        and all(c in "0123456789abcdef" for c in job_id)
    )

def _job_path(job_id):
    return f"/tmp/{job_id}.txt"


# ==========================================================
# FLASK ENDPOINTS
# ==========================================================

@app.route("/convert", methods=["POST"])
def convert():
    if "gerber" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["gerber"]
    try:
        content = file.read().decode("utf-8", errors="ignore")
        result  = gcode_to_custom(content)

        if result.startswith("ERROR:"):
            return jsonify({"error": result}), 400

        result_bytes = result.encode("utf-8")
        job_id       = uuid.uuid4().hex          # 32-char lowercase hex
        tmp_path     = _job_path(job_id)

        with open(tmp_path, "wb") as f:
            f.write(result_bytes)

        total_cmds  = result.count("\n") - 1     # subtract END line
        total_bytes = len(result_bytes)

        print(f"[LOG] Job {job_id}: {total_bytes} bytes, {total_cmds} cmds -> {tmp_path}")

        return jsonify({
            "job_id":      job_id,
            "total_cmds":  total_cmds,
            "total_bytes": total_bytes,
        })

    except ValueError as ve:
        print(f"[ERROR] {ve}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        print(f"[CRASH] {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route("/fetch", methods=["GET"])
def fetch():
    job_id = request.args.get("job", "")
    if not _valid_job_id(job_id):
        return jsonify({"error": "Invalid job_id"}), 400

    try:
        offset = int(request.args.get("offset", 0))
        length = int(request.args.get("len", 4096))
    except ValueError:
        return jsonify({"error": "Bad offset/len"}), 400

    tmp_path = _job_path(job_id)
    if not os.path.exists(tmp_path):
        print(f"[WARN] /fetch: job {job_id} not found")
        return jsonify({"error": "Job not found — container may have recycled"}), 404

    with open(tmp_path, "rb") as f:
        f.seek(offset)
        data = f.read(length)

    print(f"[LOG] /fetch job={job_id} offset={offset} len={len(data)}")
    return Response(
        data,
        status=200,
        mimetype="text/plain",
        headers={"Content-Length": str(len(data))},
    )


@app.route("/job/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not _valid_job_id(job_id):
        return jsonify({"error": "Invalid job_id"}), 400

    tmp_path = _job_path(job_id)
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
        print(f"[LOG] Deleted job {job_id}")
        return jsonify({"deleted": True})

    print(f"[WARN] DELETE: job {job_id} not found (already deleted?)")
    return jsonify({"deleted": False, "note": "File not found"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
