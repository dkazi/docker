import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class LogFileHandler(FileSystemEventHandler):

    def __init__(self, log_files, backend_url, batch_file="new_logs.txt"):
        self.log_files = log_files
        self.backend_url = backend_url
        self.batch_file = batch_file

        # κρατά offset για κάθε αρχείο
        self.last_sent_size = {file: 0 for file in log_files}

    def on_modified(self, event):

        if event.src_path in self.log_files:
            self.collect_new_logs(event.src_path)

    def collect_new_logs(self, log_file):

        try:
            with open(log_file, "r") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {log_file}: {e}")
            return

        new_size = len(content)

        if new_size > self.last_sent_size[log_file]:

            new_logs = content[self.last_sent_size[log_file]:]
            self.last_sent_size[log_file] = new_size

            self.append_to_batch(log_file, new_logs)

    def append_to_batch(self, log_file, logs):

        try:
            with open(self.batch_file, "a") as batch:
                batch.write(f"\n[{log_file}]\n")
                batch.write(logs)
        except Exception as e:
            print("Error writing batch file:", e)

    def send_batch_to_backend(self):

        if not os.path.exists(self.batch_file):
            return

        if os.path.getsize(self.batch_file) == 0:
            return

        try:
            with open(self.batch_file, "rb") as f:

                files = {"log_file": f}

                response = requests.post(self.backend_url, files=files)

            if response.status_code == 200:

                print("Batch sent successfully")

                # καθαρίζουμε το batch file
                open(self.batch_file, "w").close()

            else:
                print("Failed to send logs:", response.status_code)

        except Exception as e:
            print("Error sending logs:", e)


if __name__ == "__main__":

    # log files που θα παρακολουθούμε
    log_files = [
        "/var/log/app1.log",
        "/var/log/app2.log"
    ]

    backend_url = "http://localhost:5000/receive-logs"

    event_handler = LogFileHandler(log_files, backend_url)

    observer = Observer()

    # schedule watcher για κάθε αρχείο
    for log_file in log_files:

        observer.schedule(
            event_handler,
            path=os.path.dirname(log_file),
            recursive=False
        )

    observer.start()

    try:
        while True:

            # στέλνουμε batch logs κάθε 5 sec
            event_handler.send_batch_to_backend()

            time.sleep(5)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()