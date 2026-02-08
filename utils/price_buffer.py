# utils/price_buffer.py

from collections import deque

class PriceBuffer:
    def __init__(self, max_len=60):
        print ("Price Buffer Funcionando")
        self.buffer = deque(maxlen=max_len)

    def add(self, price: float):
        self.buffer.append(price)

    def get_all(self):
        return list(self.buffer)

    def __len__(self):
        return len(self.buffer)

