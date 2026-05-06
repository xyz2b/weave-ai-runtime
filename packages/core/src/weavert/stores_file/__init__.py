from .._optional_compat import load_optional_attr

__all__ = [
    "FileChildRunStore",
    "RuntimeFileStoreBundle",
    "TeamFileStoreBundle",
    "assemble_file_store_bundle",
    "assemble_team_file_store_bundle",
]

_OPTIONAL_EXPORTS = {
    "FileChildRunStore": ("weavert_stores_file.child_runs", "FileChildRunStore"),
    "RuntimeFileStoreBundle": ("weavert_stores_file.package", "RuntimeFileStoreBundle"),
    "TeamFileStoreBundle": ("weavert_stores_file.package", "TeamFileStoreBundle"),
    "assemble_file_store_bundle": ("weavert_stores_file.package", "assemble_file_store_bundle"),
    "assemble_team_file_store_bundle": (
        "weavert_stores_file.package",
        "assemble_team_file_store_bundle",
    ),
}


def __getattr__(name: str):
    if name in _OPTIONAL_EXPORTS:
        module_name, attr_name = _OPTIONAL_EXPORTS[name]
        return load_optional_attr(
            module_name,
            attr_name,
            surface=f"weavert.stores_file.{name}",
            distribution_names=("weavert-stores-file",),
            source_paths=("packages/framework-packs/integrations/stores-file",),
        )
    raise AttributeError(name)
