"""The lists the facility letter form picks from: exporter countries and units.

They are data (etls.countries, etls.units, migration 0039), kept by an admin
through the endpoints in router.py. The form must use an active entry: checked
when a draft is saved (`clean_form()`) and again on Submit (`list_gaps()`), in
case an entry was switched off in between.
"""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit.service import record_event
from app.core.identity.models import User
from app.core.workflow.errors import InvalidValue, NotFound
from app.modules.etls.models import Country, FacilityLetter, Unit
from app.modules.etls.schemas import FacilityLetterForm

Kind = Literal["countries", "units"]
MODELS: dict[str, type[Country] | type[Unit]] = {"countries": Country, "units": Unit}
AUDIT_ENTITY = "etls_list_item"

# The form's field for each list, and how a person names it.
FIELDS = {"countries": ("exporter_country", "Exporter's country"), "units": ("unit", "Unit")}


async def items(session: AsyncSession, kind: Kind, *, active_only: bool = False) -> list[Country | Unit]:
    model = MODELS[kind]
    query = select(model).order_by(model.sort_order, model.name)
    if active_only:
        query = query.where(model.active)
    return list(await session.scalars(query))


async def _find(session: AsyncSession, kind: Kind, name: str) -> Country | Unit | None:
    """The entry with this name, ignoring case ("ghana" is "Ghana"), active or not."""
    model = MODELS[kind]
    return await session.scalar(select(model).where(func.lower(model.name) == name.strip().lower()))


async def clean_form(session: AsyncSession, form: FacilityLetterForm) -> FacilityLetterForm:
    """The form with the list's own spelling of country and unit, or InvalidValue
    if either isn't an active entry. Empty is fine: a draft may have gaps."""
    changes = {}
    problems = []
    for kind, (field, label) in FIELDS.items():
        value = getattr(form, field)
        if value is None:
            continue
        entry = await _find(session, kind, value)
        if entry is None or not entry.active:
            problems.append(f"{label}: '{value}' isn't on the Ministry's list")
        else:
            changes[field] = entry.name
    if problems:
        raise InvalidValue(". ".join(problems) + ".")
    return form.model_copy(update=changes)


async def list_gaps(session: AsyncSession, letter: FacilityLetter) -> list[str]:
    """For Submit: values saved earlier whose entry has since been switched off."""
    gaps = []
    for kind, (field, label) in FIELDS.items():
        value = getattr(letter, field)
        if value is None:
            continue
        entry = await _find(session, kind, value)
        if entry is None or not entry.active:
            gaps.append(f"{label} '{value}' is no longer on the Ministry's list: choose another")
    return gaps


def _require_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise InvalidValue("The name can't be empty.")
    return name


async def add_item(session: AsyncSession, *, actor: User, kind: Kind, name: str) -> Country | Unit:
    """A new entry, at the end of the list."""
    name = _require_name(name)
    if await _find(session, kind, name) is not None:
        raise InvalidValue(f"'{name}' is already on the list (switch it back on if it's off).")
    model = MODELS[kind]
    last = await session.scalar(select(func.max(model.sort_order)))
    entry = model(name=name, sort_order=(last or 0) + 1, active=True)
    session.add(entry)
    await session.flush()  # entry.id for the audit row
    record_event(
        session,
        actor=actor,
        action="etls.list_item_added",
        entity_type=AUDIT_ENTITY,
        entity_id=f"{kind}/{entry.id}",
        details={"list": kind, "name": name},
    )
    await session.commit()
    return entry


async def change_item(
    session: AsyncSession, *, actor: User, kind: Kind, item_id: int, name: str | None, active: bool | None
) -> Country | Unit:
    """Rename an entry, or switch it off or back on. Applications keep the name
    they were saved with."""
    entry = await session.get(MODELS[kind], item_id, with_for_update=True)
    if entry is None:
        raise NotFound("No such entry.")
    changes = {}
    if name is not None:
        name = _require_name(name)
        same = await _find(session, kind, name)
        if same is not None and same.id != entry.id:
            raise InvalidValue(f"'{name}' is already on the list.")
        if name != entry.name:
            changes["name"] = {"from": entry.name, "to": name}
            entry.name = name
    if active is not None and active != entry.active:
        changes["active"] = {"from": entry.active, "to": active}
        entry.active = active
    if changes:
        record_event(
            session,
            actor=actor,
            action="etls.list_item_changed",
            entity_type=AUDIT_ENTITY,
            entity_id=f"{kind}/{entry.id}",
            details={"list": kind, "changes": changes},
        )
        await session.commit()
    return entry
