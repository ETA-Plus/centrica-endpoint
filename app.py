from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
import json

app = Flask(__name__)

# Store the last received data in memory
last_received_data = []


def _interval_is_finalized(measurement_time, resolution_minutes, now):
    """Return True if the record's interval has fully elapsed relative to `now` (UTC).

    Centrica labels each record by the START of its `resolution`-minute bucket.
    A bucket [t, t + resolution) is only trustworthy once it has closed; before
    that, the export may send an all-zero / partial "forming" bucket. We keep a
    record only when its bucket has closed. Fail-open: if the timestamp can't be
    parsed we keep the record rather than risk dropping real data.
    """
    try:
        raw = measurement_time.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        start = datetime.fromisoformat(raw)
    except (ValueError, AttributeError, TypeError):
        return True

    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    try:
        minutes = int(resolution_minutes)
    except (TypeError, ValueError):
        minutes = 15

    return start + timedelta(minutes=minutes) <= now

@app.route('/')
def index():
    return "Server is up and running", 200

@app.route('/data', methods=['GET', 'POST'])
def handle_data():
    global last_received_data

    if request.method == 'GET':
        return jsonify({
            "message": "Measurements received",
            "data": last_received_data
        }), 200

    # POST request: Log headers and raw request data
    print(f"Request headers: {request.headers}")
    print(f"Raw request data: {request.data}")

    # Attempt to parse JSON data
    if not request.is_json:
        try:
            if request.data:
                data = json.loads(request.data)
            else:
                return jsonify({
                    "error": "Request must contain JSON data",
                    "details": "No data received or Content-Type is not application/json"
                }), 400
        except json.JSONDecodeError:
            return jsonify({
                "error": "Request must contain valid JSON data",
                "details": "Invalid JSON format or missing Content-Type: application/json"
            }), 400
    else:
        data = request.get_json()

    # Validate the top-level 'measurements' list
    if "measurements" not in data or not isinstance(data["measurements"], list):
        return jsonify({
            "error": "Missing or invalid 'measurements' field. It must be a list."
        }), 400

    validated_measurements = []
    for i, item in enumerate(data["measurements"]):
        required_fields = {
            "device_id": (int,),
            "device_name": (str,),
            "measurement_time(UTC)": (str,),
            "resolution(minutes)": (int,),
            "site_id": (int,),
            "site_name": (str,),
            "current(A)": (int, float),
            "voltage(V)": (int, float),
            "power(W)": (int, float),
            "power_factor": (int, float),
            "energy(Wh)": (int, float)
        }

        validated = {}
        for field, expected_type in required_fields.items():
            if field not in item:
                return jsonify({"error": f"Missing required field '{field}' in measurement {i}"}), 400
            if not isinstance(item[field], expected_type):
                return jsonify({
                    "error": f"Field '{field}' in measurement {i} must be a number or string"
                }), 400

            # Normalize field name (e.g., "energy(Wh)" -> "energy")
            normalized_key = field.split('(')[0].strip().lower()
            validated[normalized_key] = item[field]

        validated_measurements.append(validated)

    # Time-guard: only store records whose interval has finalized. Forming
    # buckets (which the export may send as all-zero) are skipped until they
    # close, so the importer picks up the finalized value on a later poll.
    # Purely time-based — a finalized real value, including a genuine 0, is
    # always kept. The POST response still echoes the full received payload.
    now_utc = datetime.now(timezone.utc)
    finalized_measurements = [
        m for m in validated_measurements
        if _interval_is_finalized(m.get("measurement_time"), m.get("resolution"), now_utc)
    ]
    dropped = len(validated_measurements) - len(finalized_measurements)
    if dropped:
        print(f"Time-guard: skipped {dropped} not-yet-finalized measurement(s)")

    # Store the latest finalized measurements
    last_received_data = finalized_measurements
    print(f"Data stored: {finalized_measurements}")

    return jsonify({"message": "Measurements received", "data": validated_measurements}), 200

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

