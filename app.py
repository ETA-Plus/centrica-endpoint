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


def _is_all_zero(measurement):
    """Return True if the record is a fully-zeroed dropout block.

    Panoramic Power emits placeholder records with every measured field at 0
    (voltage/current/power/power_factor) for intervals it hasn't settled yet;
    it later overwrites them with the real values. A genuinely idle but
    energized device still reads its line voltage (~230), so this only matches
    the spurious dropout blocks, not real off-periods.
    """
    return (measurement.get("voltage") == 0 and measurement.get("power") == 0
            and measurement.get("current") == 0 and measurement.get("power_factor") == 0)

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

    # Only store trustworthy records: skip not-yet-finalized (forming) buckets
    # and fully-zeroed dropout blocks that the export sends before it settles a
    # value. A genuinely idle device keeps its line voltage, so real off-periods
    # are preserved. The POST response still echoes the full received payload.
    now_utc = datetime.now(timezone.utc)
    kept_measurements = [
        m for m in validated_measurements
        if _interval_is_finalized(m.get("measurement_time"), m.get("resolution"), now_utc)
        and not _is_all_zero(m)
    ]
    dropped = len(validated_measurements) - len(kept_measurements)
    if dropped:
        print(f"Skipped {dropped} not-yet-finalized or all-zero measurement(s)")

    # Store the latest kept measurements
    last_received_data = kept_measurements
    print(f"Data stored: {kept_measurements}")

    return jsonify({"message": "Measurements received", "data": validated_measurements}), 200

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

