"""Helper code for grouping institution names and tracking duplicates."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher


US_COUNTRIES = {
    "us",
    "usa",
    "unitedstates",
    "unitedstatesofamerica",
}


def normalize_text(value: str | None) -> str:
    """Trim text and turn missing values into an empty string."""
    if value is None:
        return ""
    return " ".join(value.strip().split())


def normalize_key(value: str | None) -> str:
    """Make text easier to compare by ignoring case."""
    return normalize_text(value).casefold()


def normalize_compact_key(value: str | None) -> str:
    """Make a comparison key that ignores spaces and punctuation."""
    return "".join(ch for ch in normalize_key(value) if ch.isalnum())


def normalize_match_name(value: str | None) -> str:
    """Clean up institution names so similar ones are easier to match."""
    # Fold case, strip punctuation, and expand a few short forms.
    text = normalize_key(value).replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = []
    for word in text.split():
        if word in {"univ", "univr", "univrsity"}:
            word = "university"
        elif word == "inst":
            word = "institute"
        elif word == "tech":
            word = "technology"
        words.append(word)
    return " ".join(words)


def normalize_country(value: str | None) -> str:
    """Make country text easier to compare."""
    return normalize_compact_key(value)


def is_us_country(value: str | None) -> bool:
    """Check whether the country value means the United States."""
    return normalize_country(value) in US_COUNTRIES


def display_country(value: str) -> str:
    """Show country names in a consistent way."""
    normalized = normalize_country(value)
    if normalized in US_COUNTRIES:
        return "USA"
    return value


def location_key(value: str | None) -> str:
    """Turn a location field into a plain comparison key."""
    return normalize_compact_key(value)


@dataclass
class InstitutionAggregate:
    """Hold the merged data for one institution."""
    key: str
    name_counts: Counter[str] = field(default_factory=Counter)
    city_counts: Counter[str] = field(default_factory=Counter)
    state_counts: Counter[str] = field(default_factory=Counter)
    country_counts: Counter[str] = field(default_factory=Counter)
    team_count: int = 0
    outstanding: bool = False

    def add_row(self, row: dict[str, str]) -> None:
        """Add one CSV row to this institution."""
        institution = normalize_text(row.get("institution"))
        if institution:
            self.name_counts[institution] += 1

        city = normalize_text(row.get("city"))
        if city:
            self.city_counts[city] += 1

        state = normalize_text(row.get("state_province"))
        if state:
            self.state_counts[state] += 1

        country = normalize_text(row.get("country"))
        if country:
            self.country_counts[country] += 1

        self.team_count += 1
        if normalize_key(row.get("final_ranking")) == "outstanding":
            self.outstanding = True

    @staticmethod
    def _best_value(counter: Counter[str]) -> str:
        """Pick the value that shows up the most."""
        if not counter:
            return ""
        return sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))[0][0]

    @property
    def display_name(self) -> str:
        return self._best_value(self.name_counts)

    @property
    def city(self) -> str:
        return self._best_value(self.city_counts)

    @property
    def state_province(self) -> str:
        return self._best_value(self.state_counts)

    @property
    def country(self) -> str:
        return self._best_value(self.country_counts)

    def merge(self, other: "InstitutionAggregate") -> None:
        """Combine another institution record into this one."""
        self.name_counts.update(other.name_counts)
        self.city_counts.update(other.city_counts)
        self.state_counts.update(other.state_counts)
        self.country_counts.update(other.country_counts)
        self.team_count += other.team_count
        self.outstanding = self.outstanding or other.outstanding


def compatible_locations(left: InstitutionAggregate, right: InstitutionAggregate) -> bool:
    """Check whether two institutions look like the same place."""
    # Only merge fuzzy name matches if the location data does not conflict.
    left_country = location_key(left.country)
    right_country = location_key(right.country)
    if left_country and right_country and left_country != right_country:
        return False

    left_state = location_key(left.state_province)
    right_state = location_key(right.state_province)
    if left_state and right_state and left_state != right_state:
        return False

    left_city = location_key(left.city)
    right_city = location_key(right.city)
    if left_city and right_city and left_city != right_city:
        return False

    return True


def should_merge_institutions(left: InstitutionAggregate, right: InstitutionAggregate) -> bool:
    """Decide whether two institution records should be joined together."""
    left_name = normalize_match_name(left.display_name)
    right_name = normalize_match_name(right.display_name)
    if not left_name or not right_name:
        return False

    if left_name == right_name:
        return True

    # This helps catch typos like "Univercity".
    similarity = SequenceMatcher(None, left_name, right_name).ratio()
    if similarity < 0.90:
        return False

    return compatible_locations(left, right)


def cluster_institutions(aggregates: list[InstitutionAggregate]) -> list[InstitutionAggregate]:
    """Group the raw institution records into merged clusters."""
    clusters: list[InstitutionAggregate] = []
    for aggregate in sorted(aggregates, key=lambda item: (normalize_match_name(item.display_name), item.display_name.casefold())):
        merged = False
        for cluster in clusters:
            # Attach each record to the first cluster that fits.
            if should_merge_institutions(cluster, aggregate):
                cluster.merge(aggregate)
                merged = True
                break
        if not merged:
            clusters.append(aggregate)
    return clusters


def collect_potential_duplicates(institutions: list[InstitutionAggregate]) -> list[dict[str, str]]:
    """Make rows that show which institution names were grouped."""
    rows: list[dict[str, str]] = []
    for institution in institutions:
        canonical_name = institution.display_name
        for original_name, occurrences in sorted(
            institution.name_counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        ):
            if normalize_key(original_name) == normalize_key(canonical_name):
                continue
            rows.append(
                {
                    "original_institution": original_name,
                    "merged_to_institution": canonical_name,
                    "occurrences": str(occurrences),
                    "team_count": str(institution.team_count),
                    "city": institution.city,
                    "state_province": institution.state_province,
                    "country": display_country(institution.country),
                }
            )
    rows.sort(
        key=lambda row: (
            row["merged_to_institution"].casefold(),
            row["original_institution"].casefold(),
        )
    )
    return rows
