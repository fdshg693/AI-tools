from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from vscode_profiles.errors import CliError
from vscode_profiles.jsonc import loads

DEFAULT_NAME = "Default"


@dataclass(frozen=True)
class Profile:
    name: str
    location: str | None
    inherits_settings: bool
    settings_path: Path


def load_profiles(user_data_dir: Path) -> list[Profile]:
    ledger_path = user_data_dir / "User" / "globalStorage" / "storage.json"
    if not ledger_path.is_file():
        raise CliError(f"storage.json is missing: {ledger_path}")
    data = _read_json_object(ledger_path, "storage.json")
    if not isinstance(data, dict):
        raise CliError(f"storage.json must be a JSON object: {ledger_path}")
    raw_profiles = data.get("userDataProfiles", [])
    if not isinstance(raw_profiles, list):
        raise CliError(f"userDataProfiles must be a list: {ledger_path}")

    profiles = [
        Profile(
            name=DEFAULT_NAME,
            location=None,
            inherits_settings=False,
            settings_path=user_data_dir / "User" / "settings.json",
        )
    ]
    for entry in raw_profiles:
        profiles.append(_profile_from_entry(user_data_dir, entry))
    _reject_duplicate_names(profiles)
    profiles.sort(key=lambda profile: (profile.name != DEFAULT_NAME, profile.name))
    return profiles


def read_own_settings(profile: Profile) -> dict[str, object]:
    if profile.inherits_settings:
        return {}
    if not profile.settings_path.is_file():
        raise CliError(
            f"settings.json is missing for profile {profile.name!r}: {profile.settings_path}"
        )
    data = _read_json_object(profile.settings_path, "settings.json")
    if not isinstance(data, dict):
        raise CliError(
            "settings.json must be a JSON object for profile "
            f"{profile.name!r}: {profile.settings_path}"
        )
    return data


def _profile_from_entry(user_data_dir: Path, entry: object) -> Profile:
    if not isinstance(entry, dict):
        raise CliError("userDataProfiles entry must be an object")
    name = entry.get("name")
    location = entry.get("location")
    if not isinstance(name, str) or name == "":
        raise CliError("profile entry is missing a name")
    if not isinstance(location, str) or location == "":
        raise CliError(f"profile {name!r} is missing a location")
    flags = entry.get("useDefaultFlags", {})
    if flags is None:
        flags = {}
    if not isinstance(flags, dict):
        raise CliError(f"useDefaultFlags must be an object for profile {name!r}")
    inherits = flags.get("settings", False)
    if not isinstance(inherits, bool):
        raise CliError(f"useDefaultFlags.settings must be a boolean for profile {name!r}")
    return Profile(
        name=name,
        location=location,
        inherits_settings=inherits,
        settings_path=_settings_path(user_data_dir, location, name),
    )


def _settings_path(user_data_dir: Path, location: str, name: str) -> Path:
    profiles_root = (user_data_dir / "User" / "profiles").resolve()
    if Path(location).is_absolute():
        raise CliError(f"profile location escapes the profiles directory: {location} ({name})")
    candidate = (profiles_root / location).resolve()
    if not candidate.is_relative_to(profiles_root):
        raise CliError(f"profile location escapes the profiles directory: {location} ({name})")
    return candidate / "settings.json"


def _reject_duplicate_names(profiles: list[Profile]) -> None:
    by_name: dict[str, list[Profile]] = defaultdict(list)
    for profile in profiles:
        by_name[profile.name].append(profile)
    for name in sorted(by_name):
        group = by_name[name]
        if len(group) < 2:
            continue
        labels = ", ".join(sorted(_location_label(profile) for profile in group))
        raise CliError(f"duplicate profile name {name!r}: {labels}")


def _location_label(profile: Profile) -> str:
    if profile.location is None:
        return "(default)"
    return profile.location


def _read_json_object(path: Path, label: str) -> object:
    try:
        return loads(path.read_text(encoding="utf-8"))
    except CliError as exc:
        raise CliError(f"invalid {label}: {path}: {exc}") from exc
    except OSError as exc:
        raise CliError(f"could not read {label}: {path}: {exc}") from exc
