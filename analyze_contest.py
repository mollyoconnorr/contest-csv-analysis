"""Read the contest CSV and write the main report plus a duplicate list."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Iterable

from institution_merge import (
    InstitutionAggregate,
    cluster_institutions,
    collect_potential_duplicates,
    display_country,
    is_us_country,
    normalize_key,
    normalize_text,
)

RANK_ORDER = {
    "unsuccessful": 0,
    "successful participant": 1,
    "honorable mention": 2,
    "meritorious": 3,
    "finalist": 4,
    "outstanding": 5,
}

RANK_ALIASES = {
    "outstanding winner": "outstanding",
}


def parse_rank(value: str | None) -> int:
    """Turn a ranking name into a number we can compare."""
    key = normalize_key(value)
    key = RANK_ALIASES.get(key, key)
    if key in RANK_ORDER:
        return RANK_ORDER[key]
    return -1


def canonical_header(value: str) -> str:
    """Clean up a header name so close matches are easier to find."""
    return "".join(ch for ch in value.casefold() if ch.isascii() and ch.isalnum())


HEADER_ALIASES = {
    "registrationnumber": "registration_number",
    "registernumber": "registration_number",
    "teamnumber": "registration_number",
    "institution": "institution",
    "homeinstitution": "institution",
    "school": "institution",
    "city": "city",
    "stateprovince": "state_province",
    "state": "state_province",
    "province": "state_province",
    "country": "country",
    "facultyadvisor": "faculty_advisor",
    "advisor": "faculty_advisor",
    "problem": "problem_choice",
    "problemchoice": "problem_choice",
    "choice": "problem_choice",
    "finalrankingdesignation": "final_ranking",
    "finalranking": "final_ranking",
    "ranking": "final_ranking",
}


def map_headers(fieldnames: Iterable[str]) -> dict[str, str]:
    """Match the CSV headers to the names the script uses."""
    mapping: dict[str, str] = {}
    for field in fieldnames:
        canonical = HEADER_ALIASES.get(canonical_header(field))
        if canonical:
            mapping[canonical] = field
    return mapping


def build_row(row: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    """Rebuild one CSV row using the column names we want."""
    normalized: dict[str, str] = {}
    for canonical, original in mapping.items():
        normalized[canonical] = normalize_text(row.get(original))
    return normalized


def analyze_csv(
    csv_path: Path,
) -> tuple[list[InstitutionAggregate], list[dict[str, str]], dict[str, int], list[str]]:
    """Read the CSV and collect the stats we need for the report."""
    aggregates: dict[str, InstitutionAggregate] = {}
    us_meritorious_or_better: list[dict[str, str]] = []
    stats = {
        "rows_read": 0,
        "rows_ignored": 0,
        "rows_accepted": 0,
        "rows_missing_ranking": 0,
        "rows_unrecognized_ranking": 0,
        "rows_missing_institution": 0,
    }
    warnings: list[str] = []

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file does not contain a header row.")

        header_map = map_headers(reader.fieldnames)
        unmapped_headers = [
            normalize_text(field)
            for field in reader.fieldnames
            if canonical_header(field) not in HEADER_ALIASES
        ]
        if unmapped_headers:
            # Extra columns are okay, but I still want to know they were there.
            warnings.append(
                "Ignoring unrecognized columns: " + ", ".join(sorted(dict.fromkeys(unmapped_headers)))
            )

        required = {"institution", "final_ranking"}
        missing = required - set(header_map)
        if missing:
            warnings.append(
                "Required columns not found by name: " + ", ".join(sorted(missing))
            )

        for row_number, raw_row in enumerate(reader, start=2):
            if not any(normalize_text(value) for value in raw_row.values()):
                continue
            stats["rows_read"] += 1
            row = build_row(raw_row, header_map)
            institution = row.get("institution", "")
            ranking = row.get("final_ranking", "")
            if not institution:
                stats["rows_ignored"] += 1
                stats["rows_missing_institution"] += 1
                warnings.append(f"Row {row_number}: missing institution name; row ignored.")
                continue

            key = normalize_key(institution)
            aggregate = aggregates.setdefault(key, InstitutionAggregate(key=key))
            aggregate.add_row(row)
            stats["rows_accepted"] += 1

            # Only keep rows for the US award list when the ranking looks right.
            if not ranking:
                stats["rows_missing_ranking"] += 1
                warnings.append(
                    f"Row {row_number}: missing ranking for '{institution}'; counted for institution totals only."
                )
            elif parse_rank(ranking) < 0:
                stats["rows_unrecognized_ranking"] += 1
                warnings.append(
                    f"Row {row_number}: unrecognized ranking '{ranking}' for '{institution}'."
                )

            if ranking and is_us_country(row.get("country")) and parse_rank(ranking) >= RANK_ORDER["meritorious"]:
                us_meritorious_or_better.append(row)

    institutions = cluster_institutions(list(aggregates.values()))
    clustered_count = sum(1 for inst in institutions if len(inst.name_counts) > 1)
    if clustered_count:
        warnings.append(
            f"Detected {clustered_count} merged institution cluster(s) with multiple raw names."
        )
    institutions.sort(key=lambda item: (-item.team_count, item.display_name.casefold()))
    us_meritorious_or_better.sort(
        key=lambda row: (
            normalize_text(row.get("institution")).casefold(),
            normalize_text(row.get("registration_number")).casefold(),
        )
    )
    return institutions, us_meritorious_or_better, stats, warnings


def write_report(
    output_path: Path,
    institutions: list[InstitutionAggregate],
    us_meritorious_or_better: list[dict[str, str]],
    stats: dict[str, int],
    warnings: list[str],
) -> None:
    """Write the main CSV report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_institutions = len(institutions)
    total_teams = sum(inst.team_count for inst in institutions)
    average = (total_teams / total_institutions) if total_institutions else 0.0

    outstanding_institutions = sorted(
        [inst for inst in institutions if inst.outstanding],
        key=lambda item: item.display_name.casefold(),
    )

    fieldnames = [
        "section",
        "record_type",
        "sort_order",
        "item",
        "team_count",
        "registration_number",
        "institution",
        "city",
        "state_province",
        "country",
        "advisor",
        "problem",
        "ranking",
        "metric_value",
        "notes",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 1,
                "item": "Average teams per institution",
                "metric_value": f"{average:.2f}",
            }
        )
        # Put the summary rows at the top so they are easy to spot.
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 2,
                "item": "Rows read",
                "metric_value": stats["rows_read"],
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 3,
                "item": "Rows accepted",
                "metric_value": stats["rows_accepted"],
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 4,
                "item": "Rows ignored",
                "metric_value": stats["rows_ignored"],
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 5,
                "item": "Unique institutions",
                "metric_value": total_institutions,
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 6,
                "item": "Total teams counted",
                "metric_value": total_teams,
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 7,
                "item": "Warnings generated",
                "metric_value": len(warnings),
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 8,
                "item": "Rows missing ranking",
                "metric_value": stats["rows_missing_ranking"],
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 9,
                "item": "Rows with unrecognized ranking",
                "metric_value": stats["rows_unrecognized_ranking"],
            }
        )
        writer.writerow(
            {
                "section": "Summary",
                "record_type": "summary",
                "sort_order": 10,
                "item": "Rows missing institution",
                "metric_value": stats["rows_missing_institution"],
            }
        )

        for index, institution in enumerate(
            sorted(institutions, key=lambda item: (-item.team_count, item.display_name.casefold())),
            start=1,
        ):
            # This row is for one merged institution, not one original CSV row.
            writer.writerow(
                {
                    "section": "Institution Counts",
                    "record_type": "institution",
                    "sort_order": index,
                    "item": institution.display_name,
                    "team_count": institution.team_count,
                    "institution": institution.display_name,
                    "city": institution.city,
                    "state_province": institution.state_province,
                    "country": display_country(institution.country),
                    "notes": "merged institution cluster",
                }
            )

        for index, institution in enumerate(outstanding_institutions, start=1):
            writer.writerow(
                {
                    "section": "Outstanding Institutions",
                    "record_type": "outstanding_institution",
                    "sort_order": index,
                    "item": institution.display_name,
                    "team_count": institution.team_count,
                    "institution": institution.display_name,
                    "city": institution.city,
                    "state_province": institution.state_province,
                    "country": display_country(institution.country),
                }
            )

        for index, row in enumerate(us_meritorious_or_better, start=1):
            writer.writerow(
                {
                    "section": "US Teams",
                    "record_type": "us_team",
                    "sort_order": index,
                    "item": row.get("institution", ""),
                    "registration_number": row.get("registration_number", ""),
                    "institution": row.get("institution", ""),
                    "city": row.get("city", ""),
                    "state_province": row.get("state_province", ""),
                    "country": display_country(row.get("country", "")),
                    "advisor": row.get("faculty_advisor", ""),
                    "problem": row.get("problem_choice", ""),
                    "ranking": row.get("final_ranking", ""),
                }
            )

        for index, warning in enumerate(warnings, start=1):
            writer.writerow(
                {
                    "section": "Warnings",
                    "record_type": "warning",
                    "sort_order": index,
                    "item": warning,
                    "notes": warning,
                }
            )


def write_potential_duplicates(output_path: Path, institutions: list[InstitutionAggregate]) -> None:
    """Write the file that shows which institution names got merged."""
    duplicate_rows = collect_potential_duplicates(institutions)
    fieldnames = [
        "original_institution",
        "merged_to_institution",
        "occurrences",
        "team_count",
        "city",
        "state_province",
        "country",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(duplicate_rows)


def build_parser() -> argparse.ArgumentParser:
    """Set up the command-line options."""
    parser = argparse.ArgumentParser(
        description="Analyze contest CSV data and write a summary report."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="2015.csv",
        help="Input CSV file (default: 2015.csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output files/contest_report.csv",
        help="Output report file (default: output files/contest_report.csv)",
    )
    return parser


def prompt_path(prompt: str, default: str) -> Path:
    """Ask for a path, but let Enter use the default."""
    response = input(f"{prompt} [{default}]: ").strip()
    return Path(response or default)


def main() -> int:
    """Run the program and print a short summary."""
    parser = build_parser()
    args = parser.parse_args()

    print("Contest analysis started. Please wait while the results are being prepared.")

    if len(sys.argv) > 1:
        input_path = Path(args.input)
        output_path = Path(args.output)
    else:
        # If the script is run by itself, ask for the paths instead of making
        # the user type them into the command line.
        print("Contest Analysis")
        print("Press Enter to accept the default path shown in brackets.")
        input_path = prompt_path("Enter the CSV input file", "2015.csv")
        output_path = prompt_path("Enter the report output file", "output files/contest_report.csv")

    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")

    institutions, us_meritorious_or_better, stats, warnings = analyze_csv(input_path)
    write_report(output_path, institutions, us_meritorious_or_better, stats, warnings)
    duplicates_path = output_path.with_name("potential_duplicates.csv")
    write_potential_duplicates(duplicates_path, institutions)

    total_institutions = len(institutions)
    total_teams = sum(inst.team_count for inst in institutions)
    average = (total_teams / total_institutions) if total_institutions else 0.0

    print(f"Wrote report to {output_path}")
    print(f"Wrote potential duplicates to {duplicates_path}")
    print(f"Average teams per institution: {average:.2f}")
    print(f"Rows read: {stats['rows_read']}")
    print(f"Rows accepted: {stats['rows_accepted']}")
    print(f"Rows ignored: {stats['rows_ignored']}")
    print(f"Unique institutions: {total_institutions}")
    print(f"Total teams counted: {total_teams}")
    if warnings:
        print("Warnings:", file=sys.stderr)
        for warning in warnings[:10]:
            print(f"- {warning}", file=sys.stderr)
        if len(warnings) > 10:
            print(f"- ...and {len(warnings) - 10} more", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
