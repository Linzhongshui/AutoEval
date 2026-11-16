"""Compatibility exports; implementation moved to autoeval.catalog.

``python -m autoeval.register_automationbench`` stays the documented CLI entry."""

from autoeval.catalog.register_automationbench import register

__all__ = ["register"]

if __name__ == "__main__":
    import asyncio

    asyncio.run(register())
