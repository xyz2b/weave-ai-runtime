__all__ = [
    "FileChildRunStore",
    "RuntimeFileStoreBundle",
    "TeamFileStoreBundle",
    "assemble_file_store_bundle",
    "assemble_team_file_store_bundle",
]


def __getattr__(name: str):
    if name == "FileChildRunStore":
        from importlib import import_module

        try:
            module = import_module("weavert_stores_file.child_runs")
        except ModuleNotFoundError:
            module = import_module(".child_runs", __name__)
        return module.FileChildRunStore
    if name in {
        "RuntimeFileStoreBundle",
        "TeamFileStoreBundle",
        "assemble_file_store_bundle",
        "assemble_team_file_store_bundle",
    }:
        from importlib import import_module

        try:
            module = import_module("weavert_stores_file.package")
        except ModuleNotFoundError:
            module = import_module(".package", __name__)
        return getattr(module, name)
    raise AttributeError(name)
