import socketio
import base64
import logging
import asyncio
from fastapi import FastAPI
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES
import pickle
import uvicorn
import cv2
import numpy as np
import hashlib

HEIGHT = 720
WIDTH = 1280

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize FastAPI and Socket.IO
app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio, app)

# Initialize RSA for key exchange
rsa_key = RSA.generate(2048)
private_key = rsa_key.export_key()
public_key = rsa_key.publickey().export_key()
shared_secret = None

@sio.event
async def connect(sid, environ):
    logging.info(f"Client connected: {sid}")

@sio.on('key_exchange')
async def handle_key_exchange(sid, data):
    global shared_secret
    try:
        received_data = pickle.loads(data)
        client_public_key = base64.b64decode(received_data['public_key'])
        client_key = RSA.import_key(client_public_key)

        # Generate shared secret
        shared_secret = hashlib.sha256(b"Some predetermined secret").digest()
        cipher_rsa = PKCS1_OAEP.new(client_key)
        encrypted_secret = cipher_rsa.encrypt(shared_secret)

        await sio.emit('key_exchange_response', pickle.dumps({
            'shared_secret': base64.b64encode(encrypted_secret).decode('utf-8')
        }), room=sid)

        asyncio.create_task(capture_and_send_video(sid))
    except Exception as e:
        logging.error(f"Error during key exchange: {e}")

async def capture_and_send_video(sid):
    global shared_secret
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logging.error("Camera not accessible")
        return

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            logging.error("Error reading from camera")
            break

        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        cipher = AES.new(shared_secret, AES.MODE_GCM)
        encrypted_frame, tag = cipher.encrypt_and_digest(frame.tobytes())
        nonce = cipher.nonce

        data = {
            'frame': base64.b64encode(encrypted_frame).decode('utf-8'),
            'nonce': base64.b64encode(nonce).decode('utf-8'),
            'tag': base64.b64encode(tag).decode('utf-8'),
        }
        await sio.emit('video_frame', pickle.dumps(data), room=sid)
        await asyncio.sleep(0.03)
    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8765)
