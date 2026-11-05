"""Home Assistant selectors used by the config flows, with their types.

HA registers each selector class with ``@SELECTORS.register(...)``, which is
typed to return ``type[Selector]``. Type checkers therefore see every selector
class (and the selectors it creates) as ``Selector[Unknown]``. These factories
have the same names and arguments as the HA classes and restore the types in
one place instead of at every use.
"""

# ruff: noqa: N802 - the factories deliberately keep the HA class names.

from __future__ import annotations

from typing import cast

from homeassistant.helpers import selector as _ha
from homeassistant.helpers.selector import (
    BooleanSelectorConfig,
    EntitySelectorConfig,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    Selector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelectorConfig,
    TextSelectorConfig,
)


def BooleanSelector(
    config: BooleanSelectorConfig | None = None,
) -> Selector[BooleanSelectorConfig]:
    """Create a boolean selector."""
    return cast(Selector[BooleanSelectorConfig], _ha.BooleanSelector(config))  # pyright: ignore[reportUnknownMemberType]


def EntitySelector(
    config: EntitySelectorConfig | None = None,
) -> Selector[EntitySelectorConfig]:
    """Create an entity selector."""
    return cast(Selector[EntitySelectorConfig], _ha.EntitySelector(config))  # pyright: ignore[reportUnknownMemberType]


def NumberSelector(config: NumberSelectorConfig) -> Selector[NumberSelectorConfig]:
    """Create a number selector."""
    return cast(Selector[NumberSelectorConfig], _ha.NumberSelector(config))  # pyright: ignore[reportUnknownMemberType]


def SelectSelector(config: SelectSelectorConfig) -> Selector[SelectSelectorConfig]:
    """Create a select selector."""
    return cast(Selector[SelectSelectorConfig], _ha.SelectSelector(config))  # pyright: ignore[reportUnknownMemberType]


def TemplateSelector(
    config: TemplateSelectorConfig | None = None,
) -> Selector[TemplateSelectorConfig]:
    """Create a template selector."""
    return cast(Selector[TemplateSelectorConfig], _ha.TemplateSelector(config))  # pyright: ignore[reportUnknownMemberType]


def TextSelector(config: TextSelectorConfig | None = None) -> Selector[TextSelectorConfig]:
    """Create a text selector."""
    return cast(Selector[TextSelectorConfig], _ha.TextSelector(config))  # pyright: ignore[reportUnknownMemberType]


__all__ = [
    "BooleanSelector",
    "EntitySelector",
    "EntitySelectorConfig",
    "NumberSelector",
    "NumberSelectorConfig",
    "NumberSelectorMode",
    "SelectOptionDict",
    "SelectSelector",
    "SelectSelectorConfig",
    "SelectSelectorMode",
    "TemplateSelector",
    "TextSelector",
]
