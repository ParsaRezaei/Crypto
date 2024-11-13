# Client (rx.py)
import socketio
import base64
import logging
import pickle
from quantcrypt.kem import Kyber
from Crypto.Cipher import ChaCha20_Poly1305
import cv2
import numpy as np
import asyncio

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Socket.IO client
sio = socketio.AsyncClient()

# Initialize Kyber for key exchange
kyber = Kyber()

# Generate client key pair
client_public_key, client_private_key = kyber.keygen()
shared_secret = None

@sio.event
async def connect():
    logging.info("Connected to server")
    # Send client public key to the server
    await sio.emit('key_exchange', pickle.dumps({
        'public_key': base64.b64encode(client_public_key).decode('utf-8')
    }))

# Handle the encapsulated ciphertext from the server and decapsulate
@sio.on('key_exchange_response')
async def handle_key_exchange_response(data):
    global shared_secret
    try:
        # Decode the ciphertext received from the server
        response = pickle.loads(data)
        ciphertext = base64.b64decode(response['ciphertext'])

        # Decapsulate the ciphertext to derive the shared secret
        shared_secret = kyber.decaps(client_private_key, ciphertext)
        logging.info("Shared secret successfully derived with server.")

    except Exception as e:
        logging.error(f"Error during key exchange (decapsulation): {e}")

# Handle incoming encrypted video frames, decrypt, and display
@sio.on('video_frame')
async def handle_video_frame(data):
    global shared_secret
    try:
        if not shared_secret:
            logging.error("Shared secret is not established. Ignoring frame.")
            return

        # Decode and unpack data
        frame_data = pickle.loads(data)
        encrypted_frame = base64.b64decode(frame_data['frame'])
        nonce = base64.b64decode(frame_data['nonce'])
        tag = base64.b64decode(frame_data['tag'])

        # Decrypt frame using shared secret
        chacha20_key = shared_secret[:32]
        cipher = ChaCha20_Poly1305.new(key=chacha20_key, nonce=nonce)
        decrypted_frame = cipher.decrypt_and_verify(encrypted_frame, tag)

        # Convert to NumPy array and reshape for display
        frame = np.frombuffer(decrypted_frame, dtype=np.uint8).reshape((720, 1080, 3))

        # Display the decrypted frame
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
