try:
    from rich.progress import ProgressColumn
    if not hasattr(ProgressColumn, '_table_column'):
        ProgressColumn._table_column = None  # ensure attribute exists even if subclass skips init
except Exception:
    pass
