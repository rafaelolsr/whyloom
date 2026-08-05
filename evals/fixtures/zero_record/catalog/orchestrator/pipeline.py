class Pipeline:
    """Ingestion pipeline: extract, build, persist."""
    def __init__(self, store): self.store = store
    def run(self, source): return self.store.persist([source])
