import subprocess
import time
import psutil
import os
import csv
import sys
import urllib.request

# Adjust these paths as needed
BASE_DIR = r"C:\Users\Parsa Rezaei\Crypto\broadcast_encryp"
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
BROADCAST_SCRIPT = "broadcast.py"
STREAM_SCRIPT = "stream.py"

# URLs for videos to download
video_sources = {
    "BigBuckBunny.mp4": "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "Sintel.mp4": "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
    # Uncomment and add more videos as needed:
    # "TearsOfSteel.mp4": "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
}

streams = [
    {"stream_name": "Big Buck Bunny", "source": os.path.join(VIDEO_DIR, "BigBuckBunny.mp4")},
    {"stream_name": "Sintel", "source": os.path.join(VIDEO_DIR, "Sintel.mp4")},
    # Uncomment and add more streams as needed:
    # {"stream_name": "Tears Of Steel", "source": os.path.join(VIDEO_DIR, "TearsOfSteel.mp4")},
]


def download_video(file_name, url):
    """Download a video file if it doesn't exist."""
    file_path = os.path.join(VIDEO_DIR, file_name)
    if not os.path.exists(file_path):
        print(f"Downloading {file_name}...")
        os.makedirs(VIDEO_DIR, exist_ok=True)
        try:
            urllib.request.urlretrieve(url, file_path)
            print(f"Downloaded {file_name} to {file_path}.")
        except Exception as e:
            print(f"ERROR: Failed to download {file_name}. {e}")
            raise
    else:
        print(f"{file_name} already exists at {file_path}.")
    return file_path


def prepare_videos():
    """Ensure all required videos are downloaded into the VIDEO_DIR."""
    print(f"Ensuring videos are in {VIDEO_DIR}...")
    for file_name, url in video_sources.items():
        download_video(file_name, url)


def run_broadcast():
    """Start broadcast.py and ensure it started properly."""
    print("Starting broadcast.py...")
    broadcast_process = subprocess.Popen(
        [sys.executable, BROADCAST_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=BASE_DIR
    )
    time.sleep(5)
    if broadcast_process.poll() is not None:
        stdout, stderr = broadcast_process.communicate()
        print("ERROR: broadcast.py failed to start properly.")
        if stdout.strip():
            print("broadcast.py stdout:", stdout.strip())
        if stderr.strip():
            print("broadcast.py stderr:", stderr.strip())
        raise RuntimeError("broadcast.py did not start successfully.")
    print("broadcast.py started successfully.")
    return broadcast_process


def run_streams():
    """Start multiple instances of stream.py."""
    print("Starting stream.py instances...")
    stream_processes = []
    for stream in streams:
        stream_name = stream["stream_name"]
        source = stream["source"]
        print(f"Starting stream.py with --stream-name={stream_name} --source={source}")
        process = subprocess.Popen(
            [sys.executable, STREAM_SCRIPT, f"--stream-name={stream_name}", f"--source={source}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=BASE_DIR
        )
        time.sleep(3)
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            print(f"ERROR: stream.py ({stream_name}) failed to start.")
            if stdout.strip():
                print(f"stream.py ({stream_name}) stdout:", stdout.strip())
            if stderr.strip():
                print(f"stream.py ({stream_name}) stderr:", stderr.strip())
            raise RuntimeError(f"stream.py ({stream_name}) did not start successfully.")
        stream_processes.append((process, stream_name))
    return stream_processes


def monitor_performance(processes, csv_writer):
    """Monitor performance of running processes and log to CSV."""
    print("Monitoring performance... Press Ctrl+C to stop.")
    psutil_procs = {}
    for proc, name in processes:
        if proc.poll() is None:
            p = psutil.Process(proc.pid)
            p.cpu_percent(None)
            psutil_procs[proc] = (p, name)

    try:
        while True:
            all_done = True
            running_data = []
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

            for proc, (p, name) in psutil_procs.items():
                if proc.poll() is None:
                    all_done = False
                    cpu = p.cpu_percent(None)
                    mem = p.memory_info().rss / 1024**2
                    running_data.append((proc, name, cpu, mem))

            if not all_done and running_data:
                per_core_usage = psutil.cpu_percent(interval=0, percpu=True)
                for (proc, name, cpu, mem) in running_data:
                    row = [timestamp, proc.pid, name, f"{cpu:.2f}", f"{mem:.2f}"]
                    if per_core_usage:
                        row.extend([f"{core:.2f}" for core in per_core_usage])
                    csv_writer.writerow(row)

            if all_done:
                break
            time.sleep(.1)

    except KeyboardInterrupt:
        print("Performance monitoring interrupted by user.")


def print_process_logs(process, name):
    """Print the stdout and stderr of a finished process."""
    stdout, stderr = process.communicate()
    if stdout.strip():
        print(f"{name} stdout:")
        print(stdout)
    if stderr.strip():
        print(f"{name} stderr:")
        print(stderr)


def main():
    prepare_videos()

    csv_filename = "performance_metrics.csv"
    file_existed = os.path.exists(csv_filename)
    with open(csv_filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        if not file_existed:
            headers = ["timestamp", "process_id", "process_name", "cpu_usage_percent", "memory_mb"]
            core_count = psutil.cpu_count()
            headers.extend([f"cpu_core_{i}_percent" for i in range(core_count)])
            writer.writerow(headers)

        broadcast_process = run_broadcast()
        stream_processes = run_streams()
        monitor_performance([(broadcast_process, "broadcast.py")] + stream_processes, writer)

    print("Shutting down processes...")
    for proc, name in [(broadcast_process, "broadcast.py")] + stream_processes:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()

    print("All processes terminated. Printing logs:")
    print_process_logs(broadcast_process, "broadcast.py")
    for i, (proc, name) in enumerate(stream_processes, start=1):
        print_process_logs(proc, f"stream.py #{i} ({name})")


if __name__ == "__main__":
    main()
