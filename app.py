from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# Store the last received data in memory
last_received_data = []

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

    # Store the latest received measurements
    last_received_data = validated_measurements
    print(f"Data received: {validated_measurements}")

    return jsonify({"message": "Measurements received", "data": validated_measurements}), 200

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

