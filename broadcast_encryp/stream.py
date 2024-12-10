import socketio
import base64
import logging
import argparse
from quantcrypt.kem import Kyber
from Crypto.Cipher import ChaCha20_Poly1305
import pickle
import cv2
import asyncio
import concurrent.futures
import time

logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

parser = argparse.ArgumentParser(description="Stream encrypted video to server")
parser.add_argument('--stream-name', type=str, required=False, help='Unique stream identifier', default="Big Buck Bunny")
parser.add_argument('--source', type=str, required=False, help="Video source: \"camera\" or file path", default=r"C:\Users\Parsa Rezaei\Crypto\broadcast_encryp\videos\BigBuckBunny.mp4")
args = parser.parse_args()

STREAM_NAME = args.stream_name
SOURCE = args.source
SERVER_URL = "http://localhost:5000"
FPS = 30

kyber = Kyber()
client_public_key, client_private_key = kyber.keygen()
shared_secret = None

sio = socketio.AsyncClient(logger=False, engineio_logger=False)


@sio.on('connect', namespace='/video')
async def video_connect():
    logging.info(f"Connected to /video namespace")
    await sio.emit('register_stream', {'stream_id': STREAM_NAME}, namespace='/video')

    await sio.emit('key_exchange', pickle.dumps({
        'public_key': base64.b64encode(client_public_key).decode('utf-8'),
        'stream_id': STREAM_NAME
    }), namespace='/video')


@sio.on('key_exchange_response', namespace='/video')
async def handle_key_exchange_response(data):
    global shared_secret
    try:
        response = pickle.loads(data)
        ciphertext = base64.b64decode(response['ciphertext'])
        shared_secret = kyber.decaps(client_private_key, ciphertext)
        logging.info(f"Shared secret established for stream {STREAM_NAME}")

        # Start video streaming task
        logging.debug("Starting video capture and streaming task")
        asyncio.create_task(capture_and_send_video())
    except Exception as e:
        logging.error(f"Error during key exchange response handling: {e}")


async def capture_and_send_video():
    global shared_secret
    if shared_secret is None:
        logging.error("Shared secret not initialized, cannot start video capture")
        return

    logging.info(f"Starting video capture for stream {STREAM_NAME}")
    cap = cv2.VideoCapture(0 if SOURCE == "camera" else SOURCE)
    if not cap.isOpened():
        logging.error(f"Failed to open video source: {SOURCE}")
        return

    chacha20_key = shared_secret[:32]
    executor = concurrent.futures.ThreadPoolExecutor()

    frame_queue = asyncio.Queue(maxsize=50)  # Limit queue size
    target_frame_time = 1 / FPS  # Time per frame in seconds

    async def producer():
        """Capture frames and add them to the queue."""
        while cap.isOpened():
            start_time = time.time()

            if frame_queue.full():
                await asyncio.sleep(0.01)  # Wait if the queue is full
                continue

            ret, frame = cap.read()
            if not ret:
                logging.info("End of video stream or error reading frame.")
                break

            # Resize frame
            frame = cv2.resize(frame, (1280, 720))
            await frame_queue.put(frame)

            # Wait to match target FPS
            elapsed_time = time.time() - start_time
            wait_time = max(0, target_frame_time - elapsed_time)
            await asyncio.sleep(wait_time)

        await frame_queue.put(None)  # Sentinel to signal end of stream

    async def consumer():
        """Process frames and send them to the server."""
        while True:
            frame = await frame_queue.get()
            if frame is None:
                break

            # Encode and encrypt the frame
            loop = asyncio.get_event_loop()
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                logging.error("Failed to encode frame")
                continue

            cipher = ChaCha20_Poly1305.new(key=chacha20_key)
            encrypted_frame, tag = await loop.run_in_executor(
                executor,
                lambda: cipher.encrypt_and_digest(buffer.tobytes())
            )
            nonce = cipher.nonce  # Extract nonce for decryption

            # Prepare data payload
            data = {
                'stream_id': STREAM_NAME,
                'frame': base64.b64encode(encrypted_frame).decode('utf-8'),
                'nonce': base64.b64encode(nonce).decode('utf-8'),
                'tag': base64.b64encode(tag).decode('utf-8'),
            }

            # Send the frame
            await sio.emit('video_frame', pickle.dumps(data), namespace='/video')
            logging.debug(f"Frame sent for stream {STREAM_NAME}")

    await asyncio.gather(producer(), consumer())

    cap.release()
    cv2.destroyAllWindows()
    logging.info("Video capture stopped")

async def main():
    try:
        await sio.connect(SERVER_URL, namespaces=['/video'])
        await sio.wait()
    except Exception as e:
        logging.error(f"Error during connection: {e}")


if __name__ == '__main__':
    logging.info("Starting video streaming client")
    asyncio.run(main())
