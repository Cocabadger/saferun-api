from flask import Flask, request, jsonify

app = Flask(__name__)

@app.post('/webhook/saferun')
def saferun_webhook():
    payload = request.json or {}
    print('SafeRun event:', payload.get('event'), payload.get('change_id'))
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(port=8000)
