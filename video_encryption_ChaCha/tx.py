# Server (tx.py)
import socketio
import base64
import logging
import asyncio
from fastapi import FastAPI
from quantcrypt.kem import Kyber
from Crypto.Cipher import ChaCha20_Poly1305
import pickle
import uvicorn
import cv2
import numpy as np

HEIGHT = 720
WIDTH = 1080

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize FastAPI and Socket.IO
app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio, app)

# Initialize Kyber for key exchange
kyber = Kyber()
shared_secret = None

@sio.event
async def connect(sid, environ):
    logging.info(f"Client connected: {sid}")

# Handle key exchange from client
@sio.on('key_exchange')
async def handle_key_exchange(sid, data):
    global shared_secret
    try:
        # Receive client public key
        received_data = pickle.loads(data)
        client_public_key = base64.b64decode(received_data['public_key'])

        # Encapsulate shared secret with client public key
        ciphertext, shared_secret = kyber.encaps(client_public_key)
        logging.info("Shared secret successfully established with client.")

        # Send ciphertext back to client
        await sio.emit('key_exchange_response', pickle.dumps({
            'ciphertext': base64.b64encode(ciphertext).decode('utf-8')
        }), room=sid)

        # Start video capture and encryption task
        asyncio.create_task(capture_and_send_video(sid))

    except Exception as e:
        logging.error(f"Error during key exchange with client: {e}")

# Capture, encrypt, and send video frames
async def capture_and_send_video(sid):
    global shared_secret
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        logging.error("Camera not accessible")
        return

    chacha20_key = shared_secret[:32]

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            logging.error("Error reading from camera")
            break

        # Resize frame
        frame = cv2.resize(frame, (WIDTH, HEIGHT))

        # Encrypt frame
        cipher = ChaCha20_Poly1305.new(key=chacha20_key)
        encrypted_frame, tag = cipher.encrypt_and_digest(frame.tobytes())
        nonce = cipher.nonce

        # Display the encrypted (noisy) frame locally for verification
        noisy_frame = np.frombuffer(encrypted_frame[:WIDTH*HEIGHT*3], dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
        cv2.imshow("Encrypted Video Feed (Server)", noisy_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        # Package data for transmission
        data = {
            'frame': base64.b64encode(encrypted_frame).decode('utf-8'),
            'nonce': base64.b64encode(nonce).decode('utf-8'),
            'tag': base64.b64encode(tag).decode('utf-8'),
        }

        # Send encrypted frame to client
        await sio.emit('video_frame', pickle.dumps(data), room=sid)

        await asyncio.sleep(0.03)  # Control frame rate

    cap.release()
    cv2.destroyAllWindows()

# Run the server
if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8765)
