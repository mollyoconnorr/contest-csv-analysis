# Challenge Problem 6

This folder contains a Python solution for analyzing the 2015 contest results CSV and similar files with the same general layout.

## What it does

The program reads a CSV file and writes two CSV files:

1. One main CSV report with clear sections for:
   - summary stats
   - institution counts
   - outstanding institutions
   - US teams with `Meritorious` ranking or better
   - warnings
2. A `potential_duplicates.csv` file that shows raw institution names and the final institution name they were merged into

It also prints a processing summary to the console and includes the same summary in the output report.

If the input file looks unusual, the script adds warning messages instead of failing immediately when possible. Those warnings are printed to the terminal and also included in the CSV report.

## How institution duplicates are handled

Institution names are grouped case-insensitively, so entries like `MIT` and `mit` are treated as the same institution.

If the same institution appears across multiple rows with partial location data, the script merges the non-empty city, state/province, and country values into one combined institution record.

## Usage

Run the script from this folder:

```bash
python3 analyze_contest.py
```

The program will ask for:

- The CSV input file
- The report output file

Just press Enter to accept the defaults:

- Input: `2015.csv`
- Output: `contest_report.csv`

You can still use command-line arguments if you prefer:

```bash
python3 analyze_contest.py --input 2015.csv --output contest_report.csv
```

## Input expectations

The CSV file should include headers similar to the contest format, such as:

- Registration number
- Home institution
- City
- State/Province
- Country
- Faculty advisor
- Problem choice
- Final ranking designation

The script is flexible about header capitalization and minor header-name differences.

## Duplicate institution handling

Institution records are merged conservatively:

- Exact institution-name matches are combined, ignoring case and punctuation.
- Obvious spelling variations are also combined when the names are highly similar and the location data is compatible.
- Different institutions in the same city are kept separate if their names are genuinely different.

That means entries such as `MIT` and `mit` are treated as one institution, and common typos like `Shanghai Univercity` can be merged with `Shanghai University` when the rest of the location data agrees. But `Shanghai University of Electric Power` stays separate from `Shanghai University` because they are distinct institutions.

## Output files

- `contest_report.csv`: Main analysis report
- `potential_duplicates.csv`: Review file showing original institution names and the merged institution name

The main report now includes a `section` column so each row is grouped more clearly.

## Code layout

- `analyze_contest.py`: CSV parsing, prompt handling, ranking logic, and report writing
- `institution_merge.py`: Institution aggregation, fuzzy matching, clustering, and duplicate review data
