import threading
import queue
import logging
import base64
import pickle
from flask import Flask, render_template, request
from flask_socketio import SocketIO
from quantcrypt.kem import Kyber
from Crypto.Cipher import ChaCha20_Poly1305
import numpy as np
import cv2
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=16)  # Adjust based on CPU cores
# Configure logging
logging.basicConfig(level=logging.CRITICAL, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger().setLevel(logging.CRITICAL)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", engineio_logger=False, max_http_buffer_size=50 * 1024 * 1024, async_mode="threading")

kyber = Kyber()
shared_secrets = {}
stream_list = []
frame_queues = {}
client_streams = {}

# Global toggle for decryption
decrypt_enabled = True

@app.route("/")
def index():
    logging.info("Serving index.html")
    return render_template("index.html")

@socketio.on("connect", namespace="/video")
def handle_connect():
    logging.info("Client connected to /video")
    socketio.emit("stream_list_update", stream_list, namespace="/video")
@socketio.on("disconnect", namespace="/video")
def handle_disconnect():
    global client_streams, stream_list, shared_secrets, frame_queues
    sid = request.sid
    logging.info(f"Client {sid} disconnected from /video")
    if sid in client_streams:
        stream_id = client_streams[sid]
        if stream_id in stream_list:
            stream_list.remove(stream_id)
        if stream_id in shared_secrets:
            del shared_secrets[stream_id]
        if stream_id in frame_queues:
            del frame_queues[stream_id]
        del client_streams[sid]
        socketio.emit("stream_list_update", stream_list, namespace="/video")
         
            
            
@socketio.on("register_stream", namespace="/video")
def register_stream(data):
    global stream_list, client_streams
    stream_id = data["stream_id"]
    if stream_id not in stream_list:
        stream_list.append(stream_id)
        client_streams[request.sid] = stream_id
        logging.info(f"New stream registered: {stream_id} by client {request.sid}")
        socketio.emit("stream_list_update", stream_list, namespace="/video")

        
@socketio.on("get_stream_list", namespace="/video")
def get_stream_list():
    print(stream_list)
    socketio.emit("stream_list_update", stream_list, namespace="/video", to=request.sid)
    
    

@socketio.on("key_exchange", namespace="/video")
def handle_key_exchange(data):
    try:
        client_data = pickle.loads(data)
        client_public_key = base64.b64decode(client_data["public_key"])
        stream_id = client_data["stream_id"]
        logging.debug(f"Key exchange for stream {stream_id} started")

        ciphertext, shared_secret = kyber.encaps(client_public_key)
        shared_secrets[stream_id] = shared_secret
        response = {
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
            "stream_id": stream_id,
        }
        socketio.emit("key_exchange_response", pickle.dumps(response), namespace="/video")
        logging.info(f"Key exchange completed for stream {stream_id}")
    except Exception as e:
        logging.error(f"Error handling key exchange: {e}")

@socketio.on("video_frame", namespace="/video")
def handle_video_frame(data):
    global shared_secrets, frame_queues
    try:
        frame_data = pickle.loads(data)
        stream_id = frame_data["stream_id"]
        shared_secret = shared_secrets.get(stream_id)

        if not shared_secret:
            logging.error(f"No shared secret for stream {stream_id}")
            return

        # Create a queue for the stream if it doesn't exist
        if stream_id not in frame_queues:
            frame_queues[stream_id] = queue.Queue()
            threading.Thread(target=process_frames, args=(stream_id, shared_secret), daemon=True).start()

        # Add the frame data to the stream's queue
        frame_queues[stream_id].put(frame_data)

    except Exception as e:
        logging.error(f"Failed to enqueue frame for stream {stream_id}: {e}")

def process_frames(stream_id, shared_secret):
    global frame_queues, decrypt_enabled
    chacha20_key = shared_secret[:32]
    
    while True:
        frame_data = frame_queues[stream_id].get()
        if frame_data is None:
            break

        if decrypt_enabled:
            # Decrypt and decode normally
            future = executor.submit(decrypt_and_decode_frame, frame_data, chacha20_key)
            frame = future.result()

            if frame is not None:
                frame = cv2.resize(frame, (640, 360))
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    socketio.emit(
                        "broadcast_frame",
                        {
                            "stream_id": stream_id,
                            "frame": base64.b64encode(buffer.tobytes()).decode("utf-8"),
                        },
                        namespace="/video",
                    )
            else:
                logging.error(f"Failed to process frame for stream {stream_id}")
        else:
            # Decryption disabled: generate color static from encrypted data
            try:
                encrypted_frame = base64.b64decode(frame_data["frame"])
                
                width, height = 640, 360
                num_pixels = width * height  # 230,400
                channels = 3  # For color (BGR)
                total_bytes_needed = num_pixels * channels  # 691,200

                # If not enough data, repeat
                if len(encrypted_frame) < total_bytes_needed:
                    repeats = (total_bytes_needed // len(encrypted_frame)) + 1
                    extended_data = (encrypted_frame * repeats)[:total_bytes_needed]
                else:
                    extended_data = encrypted_frame[:total_bytes_needed]

                # Create a color image (BGR) from the bytes
                static_frame = np.frombuffer(extended_data, dtype=np.uint8)
                static_frame = static_frame.reshape((height, width, channels))

                # Encode to JPEG
                ret, buffer = cv2.imencode('.jpg', static_frame)
                if ret:
                    socketio.emit(
                        "broadcast_frame",
                        {
                            "stream_id": stream_id,
                            "frame": base64.b64encode(buffer.tobytes()).decode("utf-8"),
                        },
                        namespace="/video",
                    )
                    logging.info(f"Sent color static frame for stream {stream_id}")
                else:
                    logging.error(f"Failed to encode static frame for stream {stream_id}")
            except Exception as e:
                logging.error(f"Failed to produce static frame: {e}")


def decrypt_and_decode_frame(frame_data, key):
    """Decrypt and decode a single frame."""
    try:
        nonce = base64.b64decode(frame_data["nonce"])
        encrypted_frame = base64.b64decode(frame_data["frame"])
        tag = base64.b64decode(frame_data["tag"])

        cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
        decrypted_frame = cipher.decrypt_and_verify(encrypted_frame, tag)

        frame = np.frombuffer(decrypted_frame, dtype=np.uint8)
        return cv2.imdecode(frame, cv2.IMREAD_COLOR)
    except Exception as e:
        logging.error(f"Failed to decrypt or decode frame: {e}")
        return None

@socketio.on("toggle_decryption", namespace="/video")
def toggle_decryption():
    global decrypt_enabled
    decrypt_enabled = not decrypt_enabled
    logging.info(f"Decryption enabled: {decrypt_enabled}")
    socketio.emit("decryption_status", {"enabled": decrypt_enabled}, namespace="/video")

if __name__ == "__main__":
    logging.info("Starting broadcast server")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
