# TODO

Improvements, most valuable first.

## Soon

- [ ] **Keep large attributes out of the recorder database.**
  The cheapest hours sensor exposes all of its stored data as state attributes:
  `list`, `next`, `failsafe`, the `active_*` values and `archived` (which grows
  with `retention_days`). Home Assistant records the full attribute set on every
  change. Set `_unrecorded_attributes` for at least `archived`, `next` and
  `list`; the state and templates keep working.
- [ ] **Add CI.** Run pytest, basedpyright, `hassfest` and the HACS validation
  action in a GitHub Actions workflow on every pull request. `.github/` only
  contains `FUNDING.yaml` today.
- [ ] **Raise errors from actions instead of only logging them.**
  `aio_energy_management.clear_data` logs a missing or unknown `unique_id` and
  still succeeds. Raise `ServiceValidationError` so the problem shows in the UI
  and automation traces (Silver rule `action-exceptions`).

## Silver quality scale

- [ ] **Unavailable entities.** Nothing sets `available`; without a price source
  the sensor shows `off`. Mark it unavailable (except while the failsafe is
  active) and log that once (`entity-unavailable`, `log-when-unavailable`).
- [ ] Set `PARALLEL_UPDATES` (`parallel-updates`).
- [ ] Add `diagnostics.py` that dumps the coordinator data (`diagnostics`).
- [ ] Raise test coverage from 85% to 95% or more (`test-coverage`).

## Code health

- [ ] **Split `cheapest_hours/binary_sensor.py` (~1,180 lines).** Move the
  fetching for each price source (Nord Pool, Nord Pool official, Entso-E,
  Strømligning) into a small class behind a shared interface. Also resolves the
  `combine_to_hourly` TODO, which still works on raw dicts instead of
  `HourPrice`.
- [ ] **Stop polling every 30 seconds.** The on/off state only changes at known
  slot times. Schedule those with `async_track_point_in_time` and refetch
  prices on a timer instead.
- [ ] **Deprecate YAML configuration.** It keeps a separate `hass.data` path,
  schemas and tests. Raise a repair issue that suggests moving to the UI, and
  remove YAML support in a later release.
- [ ] Import the integration the same way in all tests: two test files add
  `custom_components` to `sys.path` and import `aio_energy_management.*`.
  Afterwards drop the extra `extraPaths` entry in `pyrightconfig.json`.
- [ ] Add a `pyproject.toml` with ruff configuration; the code has `noqa`
  comments but nothing runs ruff.
- [ ] Rename the "coordinator": it is a store with a calendar flag, not a
  `DataUpdateCoordinator`. Its `# TODO: version migration` for the stored data
  is still open.
- [ ] Give excess solar devices a stable id stored in the entry data. Unique ids
  are now derived from the device name, so renaming a device creates new
  entities. A stable per-device ID stored in the entry data would avoid that.
