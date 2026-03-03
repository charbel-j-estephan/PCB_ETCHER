from flask import Flask, request, send_file, jsonify
import subprocess
import tempfile
import os
import shutil
import re

app = Flask(__name__)


def gcode_to_custom(gcode_text):
    lines = gcode_text.splitlines()
    output = []
    pen_down = False
    current_x = 0.0
    current_y = 0.0
    INCH_TO_MM = 25.4

    for line in lines:
        line = line.strip()
        if not line or line.startswith("(") or line.startswith("%"):
            continue

        # Extract Z changes anywhere in the line
        z_match = re.search(r"Z([-\d.]+)", line)
        if z_match:
            z_val = float(z_match.group(1))
            pen_down = z_val < 0

        # Extract X Y coordinates from ANY line that has them
        x_match = re.search(r"X([-\d.]+)", line)
        y_match = re.search(r"Y([-\d.]+)", line)

        if x_match:
            current_x = float(x_match.group(1)) * INCH_TO_MM
        if y_match:
            current_y = float(y_match.group(1)) * INCH_TO_MM

        # Only emit a command if this line has X or Y movement
        if x_match or y_match:
            x_steps = int(round(current_x * 10))
            y_steps = int(round(current_y * 10))
            x_steps = max(0, min(1500, x_steps))
            y_steps = max(0, min(1000, y_steps))
            z_bit = "1" if pen_down else "0"
            output.append(f"I{x_steps:04d}{y_steps:04d}{z_bit}")

    return "\n".join(output)


@app.route("/convert", methods=["POST"])
def convert():
    if "gerber" not in request.files:
        return jsonify({"error": "No gerber file provided"}), 400

    gerber = request.files["gerber"]
    tmpdir = tempfile.mkdtemp()

    try:
        gerber_path = os.path.join(tmpdir, "top.gtl")
        gerber.save(gerber_path)

        result = subprocess.run(
            [
                "pcb2gcode",
                "--front",
                gerber_path,
                "--zwork",
                "-0.1",
                "--zsafe",
                "2",
                "--zchange",
                "2",
                "--mill-feed",
                "500",
                "--mill-speed",
                "0",
                "--offset",
                "0.15",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=tmpdir,
        )

        gcode_path = None
        for f in os.listdir(tmpdir):
            if f.endswith(".ngc") or f.endswith(".gcode"):
                gcode_path = os.path.join(tmpdir, f)
                break

        if not gcode_path:
            return (
                jsonify(
                    {
                        "error": "Conversion failed",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                ),
                500,
            )

        with open(gcode_path, "r") as f:
            gcode_text = f.read()

        custom_format = gcode_to_custom(gcode_text)

        # Debug: return raw gcode if custom is empty
        if not custom_format.strip():
            return (
                jsonify(
                    {
                        "error": "Parser produced no output",
                        "raw_gcode_sample": gcode_text[:2000],
                    }
                ),
                500,
            )

        tmp_out = os.path.join(tmpdir, "output.txt")
        with open(tmp_out, "w") as f:
            f.write(custom_format)

        return send_file(
            tmp_out,
            mimetype="text/plain",
            as_attachment=True,
            download_name="output.txt",
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
