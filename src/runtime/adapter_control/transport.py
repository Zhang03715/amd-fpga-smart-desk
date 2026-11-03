"""UART byte transport only; DeskService execution remains on the owner thread.

Dedicated RX avoids waiting for LCD, light frames or TX backpressure. Python
scheduling is not a hard realtime guarantee for a 16-byte AXI UART Lite FIFO.
"""
from collections import deque
from queue import Queue, Empty, Full
import threading


class UARTTransport:
    def __init__(self, uart, rx_limit=65536, tx_limit=128, interval=0.0002):
        self.uart, self.rx_limit, self.interval = uart, rx_limit, interval
        self.rx, self.rx_size = deque(), 0
        self.lock = threading.Lock()
        self.tx = Queue(maxsize=tx_limit)
        self.stopped = threading.Event()
        self.threads = []

    def start(self):
        for target, name in ((self._receive, 'adapter-uart-rx'), (self._transmit, 'adapter-uart-tx')):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def _append(self, item):
        with self.lock:
            if isinstance(item, bytes) and self.rx_size + len(item) > self.rx_limit:
                self.rx.clear()
                self.rx_size = 0
                self.rx.append(IOError('uart_host_rx_overflow'))
                return
            self.rx.append(item)
            if isinstance(item, bytes):
                self.rx_size += len(item)
            # Repeated faults must also remain bounded.
            while len(self.rx) > self.rx_limit:
                old = self.rx.popleft()
                if isinstance(old, bytes):
                    self.rx_size -= len(old)

    def _receive(self):
        while not self.stopped.is_set():
            try:
                data = self.uart.read()
                if data:
                    self._append(data)
                    continue  # Drain bursts before sleeping; Windows timers can round up.
            except Exception as exc:
                self._append(IOError('uart_rx_fault: ' + str(exc)))
                self.stopped.wait(0.01)
            self.stopped.wait(self.interval)

    def _transmit(self):
        while not self.stopped.is_set():
            try:
                payload = self.tx.get(timeout=0.02)
            except Empty:
                continue
            try:
                self.uart.write(payload)
            except Exception as exc:
                self._append(IOError('uart_tx_fault: ' + str(exc)))

    def poll(self):
        with self.lock:
            items = list(self.rx)
            self.rx.clear()
            self.rx_size = 0
        return items

    def write(self, payload):
        try:
            self.tx.put_nowait(bytes(payload))
        except Full:
            raise IOError('uart_host_tx_queue_full') from None

    def close(self):
        self.stopped.set()
        for thread in self.threads:
            thread.join(timeout=1.2)
