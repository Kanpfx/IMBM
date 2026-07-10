class IterativeMean:
    def __init__(self):
        self.count = 0
        self.mean = 0

    def update(self, new_value):
        self.count += 1
        self.mean += (new_value - self.mean) / self.count

