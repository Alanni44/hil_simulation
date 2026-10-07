class ICDError(ValueError):
    """A rejection using the frozen ICD error vocabulary, not an ACK."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")
