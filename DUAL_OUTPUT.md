# Smart TA dual output enhancement

The existing Render service and `codex/smart-ta-modernization` branch are retained. The existing voice extraction, office matching, road routing, date/time handling and per-leg ROUND_HALF_UP mileage calculation remain in place.

## Claim and division data

`/api/config` derives the division list from distinct `division_name` values in the existing `data/offices.json` (14 divisions, 696 offices). No second division master is maintained. Review and export validate division membership and require employee name, designation and headquarters. Blank optional amounts remain unset. All claim fields are validated by the same Pydantic Claim model.

Generate (`POST /api/generate`) builds both Excel documents and reconciles their serialized amounts. Each download revalidates, generates both formats, and repeats reconciliation before returning any bytes. `POST /api/export?format=existing|official|both` returns one Excel file or a ZIP containing exactly the two files. Filenames include transliterated employee name, division, and claim period. Changes to claim inputs disable downloads until generation is repeated.

## Official template mapping

A sanitized copy of the blank proforma is kept at `data/Official_TA_Proforma.xlsx`. Only blank `Sheet1` is stored in the repository and emitted; the populated example and empty sheet were removed before committing. Template headings, original column widths and existing merges are retained. Allowance labels receive small additional merges in empty cells for legible printing. A3 landscape printing includes B4:Y20, expands with overflow, fits one page wide and repeats rows 4:7.

| Input/result | Official destination |
| --- | --- |
| Employee and division | B4 title |
| Employee and designation | B8, merged B8:B18 |
| Headquarters | C8, merged C8:C18 |
| Basic pay and pay level, if supplied | D8, merged D8:D18 |
| Purpose, if supplied | J8, merged J8:J18 |
| Departure date and time | E8 onward; F8 onward |
| Departure and arrival stations | G8 onward; I8 onward |
| Arrival time | H8 onward |
| Journey kind | K8 onward, current Road mode |
| Means of conveyance, if supplied | L8 onward |
| Actual fare paid | M left blank: mileage entitlement is not an observed fare |
| Distance, existing rate, calculated mileage | N, O, P from row 8 |
| Per-journey total | X, SUM(P,T,W) |
| Remarks / ticket information | Y; long remarks in linked JourneyNotes sheet |
| Overnight arrival date | Y or JourneyNotes |
| Hotel amount supplied by claimant | P14; X14 references P14 |
| Daily allowance amount supplied by claimant | W15; X15 references W15 |
| Personal effects amount supplied by claimant | T16; X16 references T16 |
| Deductions | Negative X17 |
| Balance before advance | X18 = SUM(X8:X17) |
| Advance adjustment | X19 |
| Net payable | X20 = X18-X19 |

Six journey slots are available before row 14. For more than six, insert `journey_count - 6` rows before row 14, extend the original employee/purpose merges and shift all allowance, advance and net cells by that same offset. All up to 100 journeys supported by the original Claim model are retained. Excel dates remain true dates with dd/mm/yy display; times remain true time values with hh:mm display. The full year is retained in the cell value and filenames. Formula recalculation is requested on opening.

The original `JourneyDetails` sheet retains its original ten headers, journey rows and cell formats. `ClaimSummary` is added to that workbook with division, employee and all settlement amounts. Financial parity reads the two serialized workbooks and compares mileage and net settlement, rather than comparing two labels pointing at the same result. Formula injection in employee or journey text is blocked by explicit string cell types.

## Verification

- 52 pytest cases passed, including existing extraction, routing, isolation and journey calculation tests.
- New tests cover 1, 6, 7, 25 and 100 journeys; overflow merge/style/header preservation; optional blank amounts; no example-data leakage; overnight arrival; long remarks; formula-like text; negative/NaN/excess-precision inputs; invalid divisions; generate and all three download options; altered export totals blocked.
- `node --check web/app.js` and `git diff --check` passed.
- Browser check confirmed the new employee details and search/filter/selection of New Delhi Central Division.
- LibreOffice recalculated synthetic 2-journey and 25-journey workbooks to net amounts 501.70 and 3,626.25 respectively, matching the Python claim summary. Both were exported to A3 PDFs for print review; the 25-journey sample occupies two pages with repeated headers.

## Limits

- Existing eligibility logic only calculates road mileage. Hotel, daily allowance, personal effects, deductions and advances are explicitly supplied amounts, not newly invented eligibility calculations. No new government rates or policies are assumed. Daily allowance day/rate and personal-effects weight/rate/distance cells remain blank because the current application does not collect them.
- PDF downloading is not added to the hosted app. The Excel file can be opened and printed/exported to PDF in Excel or LibreOffice; local LibreOffice output was used for print verification.
- The existing missing-time placeholder behavior is preserved. Placeholder times are still visibly disclosed in review and marked as unconfirmed in the official output.
- The original limit is 100 journeys per claim. Division and employee details persist in the current tab, not across a reload or expired session.
- Automated voice tests use mocked provider responses; a new microphone recording against the paid live provider has not been made during this enhancement.
