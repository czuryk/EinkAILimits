from flask import Flask, jsonify, make_response
import json
import os

app = Flask(__name__)

def get_file_path(absolute_path, relative_path):
    """
    Helper function to find the file either by its absolute path 
    or its relative path (for local testing).
    """
    if os.path.exists(absolute_path):
        return absolute_path
    
    local_path = os.path.join(os.path.dirname(__file__), relative_path)
    if os.path.exists(local_path):
        return local_path
        
    return None

@app.route('/antigravity', methods=['GET'])
def antigravity():
    """
    This endpoint returns the filtered content of the limits.json file.
    """
    # Task specifies the file is located at /scripts/antigravity/limits.json
    # Trying to get it from the server root (similar to the claude endpoint):
    absolute_path = '/antigravity/limits.json'
    # Local path for testing
    relative_path = 'antigravity/limits.json'
    
    file_to_read = get_file_path(absolute_path, relative_path)
    
    if not file_to_read:
        print(f"[Error] /antigravity: File not found.")
        return make_response(jsonify({"error": "File not found."}), 404)

    try:
        with open(file_to_read, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"[Error] /antigravity: Invalid JSON format in limits file.")
        return make_response(jsonify({"error": "Invalid JSON format in limits file."}), 500)

    if 'models' not in data:
        print(f"[Error] /antigravity: 'models' key is missing in the JSON.")
        return make_response(jsonify({"error": "Invalid JSON format in limits file."}), 500)

    # Form a structure similar to claude.php for easy parsing on ESP32
    response_data = {
        "opus": {
            "utilization": 0.0,
            "resets_at": None
        },
        "gemini": {
            "utilization": 0.0,
            "resets_at": None
        }
    }

    # Extract specific model data
    for model in data.get('models', []):
        if model.get('modelId') == 'claude-opus-4-6-thinking':
            response_data['opus']['utilization'] = float(model.get('usedPercentage', 0))
            response_data['opus']['resets_at'] = model.get('resetDate')
            
        if model.get('modelId') == 'gemini-3.1-pro-high':
            response_data['gemini']['utilization'] = float(model.get('usedPercentage', 0))
            response_data['gemini']['resets_at'] = model.get('resetDate')

    print("[Success] /antigravity: Successfully parsed and served limits.json")
    
    response = jsonify(response_data)
    # Disable caching to always get fresh data
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.route('/claude', methods=['GET'])
def claude():
    """
    This endpoint returns the raw content of the usage.json file.
    """
    # Task specifies the file is located at /scripts/claude/usage.json
    # Trying to get it from the server root:
    absolute_path = '/claude/usage.json'
    # Fallback option if the script and json are in the same folder
    relative_path = 'claude/usage.json'
    
    file_to_read = get_file_path(absolute_path, relative_path)
    
    if not file_to_read:
        print(f"[Error] /claude: File not found {absolute_path}.")
        return make_response(jsonify({"error": f"File not found {absolute_path}."}), 404)

    try:
        with open(file_to_read, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"[Error] /claude: Invalid JSON format in usage file.")
        return make_response(jsonify({"error": "Invalid JSON format."}), 500)

    print("[Success] /claude: Successfully served usage.json")

    response = jsonify(data)
    # Disable caching to always get fresh data
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


if __name__ == '__main__':
    print("=======================================")
    print("Starting Microserver on Port 5000")
    print("Endpoints available:")
    print("  - http://127.0.0.1:5000/antigravity")
    print("  - http://127.0.0.1:5000/claude")
    print("=======================================")
    # Run the Flask app on all available IPs on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
