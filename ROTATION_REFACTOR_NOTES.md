# Rotation Refactor Notes

Date: 2026-04-27

## Goal

Refactor CTidyStudio so scan and DOI state stay in canonical world coordinates while view rotations are handled purely as presentation state.

The intended model is:

- `scan.data` never rotates while the app runs
- `DomainOfInterest.origin` and `opposit_point` stay in world/data coordinates
- slice selection stays in world/data coordinates
- 90-degree rotations about principal axes are stored in `AppState._view_rotation`
- views render world data through the current view rotation

## Why This Refactor

The previous approach mixed model mutation and view rotation:

- rotating the scan
- rotating/translating DOI state
- trying to maintain DOI-local coordinates with `local_ref`

That created repeated local/world consistency bugs, especially around:

- `_create_increment_control` bindings for DOI origin
- `origin_coord_in_local_direction`
- `set_origin_component`
- view rotation vs actual model rotation

## Current Direction Agreed

Use canonical world coordinates everywhere in the model, and use view rotation only for rendering and interaction mapping.

This means:

- `AppState` owns `view_changed`
- `AppState` owns `_view_rotation`
- rotation buttons update `_view_rotation`
- `SliceView` derives its current orientation from:
  - its `_initial_orientation`
  - plus `app_state.view_rotation`

## Current Code State

Relevant files:

- `src/ctidystudio/studio.py`
- `src/ctidystudio/data_handling.py`

What has already been changed:

- `AppState` now has `view_changed`
- `AppState` now stores `_view_rotation = R.identity()`
- rotation is being moved away from mutating `scan`
- `SliceView` now stores `_initial_orientation`
- `Orientation` now has `copy()` and in-place `rotate()`

## Known Issues Still Present

These were identified from the latest code state.

### 1. Stale `scan_changed` references still exist

User explicitly decided that `scan_changed` is no longer needed because the scan does not change during runtime.

But current code still references it in `studio.py`:

- `AppState.fire_all_signals()` still calls `self.scan_changed.emit()`
- `SliceView._build_conections()` still connects `self.app_state.scan_changed.connect(self._update_scan_view)`

These references should be removed rather than reintroducing the signal.

### 2. Rotation update bug in `AppState`

Current code uses:

```python
self._view_rotation = rotation_axis.rotate * self._view_rotation
```

But `rotate` is a method on `CardinalDirection`, not the rotation value.

It should use the `rotation` property:

```python
self._view_rotation = rotation_axis.rotation * self._view_rotation
```

### 3. `CardinalDirection.rotate()` is incorrect

Current code in `data_handling.py` uses:

```python
return CardinalDirection(tuple(np.rint(rotation * self.vec)))
```

This should use `rotation.apply(...)`, for example:

```python
rotated_vec = np.rint(rotation.apply(self.vec)).astype(int)
return CardinalDirection(tuple(rotated_vec))
```

### 4. DOI local-frame logic is still part of the old model

`DomainOfInterest` still contains `local_ref`-based logic:

- `move_origin`
- `set_origin_component`
- `origin_coord_in_local_direction`

This belongs to the previous design and likely needs to be removed or replaced once view-based interaction mapping is in place.

In particular, previous debugging found:

- `set_origin_component` breaks for negative mapped axes
- local/world conversion logic was conceptually tangled because the model was carrying orientation state that should now live in the view

## Discussion Outcome About Increment Controls

The conclusion was:

- `_create_increment_control()` is acceptable as a generic widget factory
- the correct abstraction is a generic `IncrementControlBinding`
- target-specific callable creation should live in binder methods like `_bind_doi_origin(...)`

However, the current DOI origin binding still depends on old local-frame semantics:

```python
lambda: self.app_state.doi.origin_coord_in_local_direction(direction)
```

That will likely need to change once DOI movement is defined relative to either:

- world axes, or
- current view axes

## Next Step To Resume From

The next agreed implementation step was:

### Step 5

Make `SliceView._update_scan_view()` use the rotated presentation orientation while still sampling the canonical world scan.

Intent of that step:

- choose the slice axis from current rotated `forward`
- keep reading from `scan.data` in canonical coordinates
- orient the resulting 2D image for display according to current `right` / `up`
- stop relying on the old static orientation assumptions

After that, the next planned step was:

- update DOI overlay drawing and center-preserving rotation behavior to match the new view model

## Important Context For Next Session

- User wants step-by-step guidance, one step per message
- User does not want `scan_changed` reintroduced
- User changed orientation handling to:
  - `Orientation.copy()`
  - in-place `Orientation.rotate()`
  - `SliceView._update_view_orientation()`
- Rotations are limited to 90-degree rotations about principal axes
