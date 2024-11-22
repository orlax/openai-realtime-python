from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('connect')
def handle_connect():
    try:
        sid = request.sid
        print('Client connected:', sid)
        emit('welcome', {'data': 'Hello world'})
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5500)