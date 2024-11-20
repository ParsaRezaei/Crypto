import socketio
import base64
import logging
import pickle
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES
import cv2
import numpy as np
import asyncio

WIDTH = 1280
HEIGHT = 720

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Socket.IO client
sio = socketio.AsyncClient()

# Initialize RSA for key exchange
rsa_key = RSA.generate(2048)
private_key = rsa_key.export_key()
public_key = rsa_key.publickey().export_key()
shared_secret = None

@sio.event
async def connect():
    logging.info("Connected to server")
    # Send public key to the server
    await sio.emit('key_exchange', pickle.dumps({
        'public_key': base64.b64encode(public_key).decode('utf-8')
    }))

@sio.on('key_exchange_response')
async def handle_key_exchange_response(data):
    global shared_secret
    try:
        response = pickle.loads(data)
        encrypted_secret = base64.b64decode(response['shared_secret'])
        # Decrypt shared secret using private key
        cipher_rsa = PKCS1_OAEP.new(RSA.import_key(private_key))
        shared_secret = cipher_rsa.decrypt(encrypted_secret)
        logging.info("Shared secret successfully derived with server.")

    except Exception as e:
        logging.error(f"Error during key exchange: {e}")

@sio.on('video_frame')
async def handle_video_frame(data):
    global shared_secret
    try:
        if not shared_secret:
            logging.error("Shared secret is not established. Ignoring frame.")
            return

        frame_data = pickle.loads(data)
        encrypted_frame = base64.b64decode(frame_data['frame'])
        nonce = base64.b64decode(frame_data['nonce'])
        tag = base64.b64decode(frame_data['tag'])

        # Display encrypted video feed (simulated as noisy frame)
        noisy_frame = np.frombuffer(encrypted_frame[:HEIGHT * WIDTH * 3], dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
        cv2.imshow("Encrypted Video Feed (Client)", noisy_frame)

        # Decrypt using AES-GCM
        cipher = AES.new(shared_secret, AES.MODE_GCM, nonce=nonce)
        decrypted_frame = cipher.decrypt_and_verify(encrypted_frame, tag)

        # Display decrypted video feed
        frame = np.frombuffer(decrypted_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
        cv2.imshow("Decrypted Video Feed (Client)", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            await sio.disconnect()
    except Exception as e:
        logging.error(f"Error processing frame: {e}")

async def main():
    await sio.connect('http://localhost:8765')
    await sio.wait()

if __name__ == '__main__':
    asyncio.run(main())
