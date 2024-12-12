import os
import json
import random
from flask import Flask, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from threading import Thread
from dotenv import load_dotenv
from multiprocessing import Process
from queue import Queue

#package to generate dynamic Agora tokens
from .dynamic_key.RtcTokenBuilder2 import *

from .agent import InferenceConfig, RealtimeKitAgent
from .realtime.struct import ServerVADUpdateParams, Voices
from .serializers import StartAgentRequestBody, StopAgentRequestBody, ValidationError
from .main import run_agent_in_process

# Load environment variables
load_dotenv(override=True)
app_id = os.environ.get("AGORA_APP_ID")
app_cert = os.environ.get("AGORA_APP_CERT")

#agora token expiration times
token_expiration_in_seconds = 3600
privilege_expiration_in_seconds = 3600
join_channel_privilege_expiration_in_seconds = 3600
pub_audio_privilege_expiration_in_seconds = 3600
pub_video_privilege_expiration_in_seconds = 3600
pub_data_stream_privilege_expiration_in_seconds = 3600

# Initialize Flask and Flask-SocketIO
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, debug=True, cors_allowed_origins="*", async_mode='eventlet')

active_channels = {}

#A GLOBAL queue to store messages from the agent
message_queue = Queue()
def emit_messages_from_queue():
    """
    Continuously monitor the queue and emit messages to clients.
    """
    while True:
        try:
            # Get a message from the queue
            message_data = message_queue.get()
            if message_data is None:
                print("Message Data is None, this Thread is gonna stop")
                break  # Stop the thread if a None value is received
            print("Message data: ", message_data)
            sid = message_data['sid']
            message = message_data['message']
            print(f"Emitting message to SID {sid}: {message}")
            socketio.emit('agent_message', message, to=sid)
            socketio.sleep(0)  # Yield control to the event loop
        except Exception as e:
            print(f"Error emitting message from queue: {e}")


@app.route('/')
def index():
    return 'Hello, World!'

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"Client connected: {sid}")

    #when a client connects we want to send a channel, uid and token
    #to the client so that they can join the Agora channel
    #channel and uid should be random?
    channel_name = sid
    uid = random.randint(100000, 999999)
    token = token = RtcTokenBuilder.build_token_with_uid_and_privilege(
        app_id, app_cert, channel_name, uid, token_expiration_in_seconds,
        join_channel_privilege_expiration_in_seconds, pub_audio_privilege_expiration_in_seconds, pub_video_privilege_expiration_in_seconds, pub_data_stream_privilege_expiration_in_seconds)

    emit('welcome', {'channel': channel_name, 'uid': uid, 'token': token})

@socketio.on('start_agent')
def start_agent(info):
    sid = request.sid
    print(f"Starting agent for SID: {sid}")
    try:
        # Parse and validate the incoming JSON data
        print("Info received to starting agent: ", info)
        validated_data = StartAgentRequestBody(**info)
    except ValidationError as e:
        print(f"Validation error: {e.errors()}")
        emit("error", {"data": e.errors()})
        return

    # Extract required parameters
    channel_name = validated_data.channel_name
    uid = validated_data.uid
    language = validated_data.language
    system_instruction = validated_data.system_instruction
    voice = validated_data.voice

    # Ensure the channel is not already active
    if channel_name in active_channels:
        emit('error', {'data': 'Channel is already in use'})
        return

    # Configure the system message
    system_message = system_instruction or """\
    Your knowledge cutoff is 2023-10. You are a helpful, witty, and friendly AI. Act like a human... start the conversation by Saying "Hello what is on your mind today?" or "Hi what are you thinking about?"."""
    
    # Validate voice
    if voice not in Voices.__members__.values():
        emit("error", {"error": f"Invalid voice: {voice}."})
        return

    # Create the inference configuration
    inference_config = InferenceConfig(
        system_message=system_message,
        voice=voice,
        turn_detection=ServerVADUpdateParams(
            type="server_vad", threshold=0.5, prefix_padding_ms=300, silence_duration_ms=200
        ),
    )

    """
    # Create a thread-safe queue for communication
    message_queue = Queue()

    # Define a callback to emit messages back to the client
    def agent_callback(message):
        message_queue.put(message)
    

    def emit_messages_from_queue():
        while True:
            try:
                message = message_queue.get()
                if(message is None):
                    break
                print("Delta Message: ", message)
                socketio.emit('agent_message', message.delta, to=sid)
                socketio.sleep(0)  # Yield control to the event loop
            except Exception as e:
                print(f"Error emitting message: {e}")
    """ 

    # Define the callback function at the top level
    def agent_callback(message, sid):
        try:
            if message is None:
                return
            print("Delta Message: ", sid, message.delta)
            message_queue.put({'sid': sid, 'message': message.delta})
        except Exception as e:
            print(f"Error adding message to queue: {e}")

    #define a function to run the agent:
    def run_agent():
        try:
            run_agent_in_process(app_id, app_cert, channel_name, uid, inference_config, agent_callback)
        finally:
            # Cleanup after the process finishes
            active_channels.pop(channel_name, None)
            message_queue.put(None)  # Signal the queue consumer to stop
            print(f"Agent stopped for channel: {channel_name}")


    #Run the agent using a Process with no parameters.
    process = Thread(target=run_agent)
    
    try:
        emit('agent_started', {'data': 'Agent is starting'})
        active_channels[channel_name] = {
            "thread": process,
            "sid": sid,
            #"queue": message_queue
        }
        process.start()
    except Exception as e:
        print(f"Error starting agent: {e}")
        emit('error', {'data': 'Error starting agent'})
        return
    
    """
    # Run the agent in a background thread
    def run_agent():
        try:
            run_agent_in_process(app_id, app_cert, channel_name, uid, inference_config, agent_callback)
        finally:
            # Cleanup after the process finishes
            active_channels.pop(channel_name, None)
            message_queue.put(None)  # Signal the queue consumer to stop
            print(f"Agent stopped for channel: {channel_name}")

    thread = Thread(target=run_agent, daemon=True)
    thread.start()

    
    """
    

    #socketio.start_background_task(emit_messages_from_queue)

@socketio.on('stop_agent')
def stop_agent(info):
    try:
        # Parse and validate the incoming JSON data
        validated_data = StopAgentRequestBody(**info)
        channel_name = validated_data.channel_name

        # Stop the thread associated with the channel
        process = active_channels.pop(channel_name, None)
        if process and process["thread"].is_alive():
            # Custom logic to stop run_agent_in_process gracefully if needed
            print(f"Stopping agent for channel: {channel_name}")
            process["thread"].terminate()
            emit("agent_stopped", {"data": f"Agent in channel {channel_name} stopped."})
        else:
            emit("error", {"data": f"No active agent for channel: {channel_name}"})
    except ValidationError as e:
        emit("error", {"data": e.errors()})
    except Exception as e:
        emit("error", {"data": str(e)})

# For testing the WebSocket connection
@socketio.on('ping')
def handle_ping(info):
    sid = request.sid
    socketio.emit('pong', to=sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=3000)
    socketio.start_background_task(emit_messages_from_queue)