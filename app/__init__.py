from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("ecube")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

API_VERSION = "1.0.0"
