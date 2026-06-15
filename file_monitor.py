import sys
import time
import logging
import argparse
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent


class FileMonitorHandler(FileSystemEventHandler):
    def __init__(self, logger: logging.Logger, debounce_seconds: float = 1.0):
        self.logger = logger
        self.debounce_seconds = debounce_seconds
        self._pending_timers: dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

    def _debounce(self, file_path: str, event_type: str, callback):
        with self._timers_lock:
            if file_path in self._pending_timers:
                self._pending_timers[file_path].cancel()
            timer = threading.Timer(self.debounce_seconds, self._execute_callback, args=[file_path, event_type, callback])
            self._pending_timers[file_path] = timer
            timer.start()

    def _execute_callback(self, file_path: str, event_type: str, callback):
        with self._timers_lock:
            self._pending_timers.pop(file_path, None)
        callback()

    def cleanup(self):
        with self._timers_lock:
            for timer in self._pending_timers.values():
                timer.cancel()
            self._pending_timers.clear()

    def on_created(self, event):
        if not event.is_directory:
            self.logger.info(f"文件创建: {event.src_path}")

    def on_modified(self, event):
        if not event.is_directory:
            file_path = event.src_path
            self._debounce(
                file_path,
                "modified",
                lambda: self.logger.info(f"文件修改: {file_path}")
            )

    def on_deleted(self, event):
        if not event.is_directory:
            file_path = event.src_path
            with self._timers_lock:
                if file_path in self._pending_timers:
                    self._pending_timers[file_path].cancel()
                    self._pending_timers.pop(file_path, None)
            self.logger.info(f"文件删除: {file_path}")

    def on_moved(self, event):
        if not event.is_directory:
            src_path = event.src_path
            dest_path = event.dest_path
            with self._timers_lock:
                if src_path in self._pending_timers:
                    self._pending_timers[src_path].cancel()
                    self._pending_timers.pop(src_path, None)
            self.logger.info(f"文件重命名: {src_path} -> {dest_path}")


def setup_logger(log_file: str = None) -> logging.Logger:
    logger = logging.getLogger("file_monitor")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def main():
    parser = argparse.ArgumentParser(description="文件监控服务 - 监控指定目录的文件变化")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="要监控的目录路径 (默认: 当前目录)"
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="是否递归监控子目录"
    )
    parser.add_argument(
        "-l", "--log-file",
        dest="log_file",
        help="日志文件路径 (可选)"
    )
    parser.add_argument(
        "-d", "--debounce",
        type=float,
        default=1.0,
        help="防抖时间（秒），同一文件在此时间内的多次修改会被合并 (默认: 1.0)"
    )

    args = parser.parse_args()

    watch_dir = Path(args.directory).resolve()
    if not watch_dir.exists():
        print(f"错误: 目录不存在 - {watch_dir}")
        sys.exit(1)
    if not watch_dir.is_dir():
        print(f"错误: 路径不是目录 - {watch_dir}")
        sys.exit(1)

    logger = setup_logger(args.log_file)
    event_handler = FileMonitorHandler(logger, debounce_seconds=args.debounce)
    observer = Observer()
    observer.schedule(event_handler, str(watch_dir), recursive=args.recursive)

    logger.info(f"开始监控目录: {watch_dir}")
    logger.info(f"递归监控: {'是' if args.recursive else '否'}")
    logger.info(f"防抖时间: {args.debounce} 秒")
    if args.log_file:
        logger.info(f"日志文件: {args.log_file}")
    logger.info("按 Ctrl+C 停止监控...")

    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("接收到停止信号，正在停止监控...")
        observer.stop()
        event_handler.cleanup()

    observer.join()
    logger.info("监控服务已停止")


if __name__ == "__main__":
    main()
