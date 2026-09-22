"""Single source of truth for the package version.

Read by ``pyproject.toml`` (``dynamic = ["version"]``) without importing the
package, so it must not import anything.
"""

__version__ = "0.1.0"
