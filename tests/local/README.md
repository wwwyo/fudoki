# Local PRD checks

These checks use the adopted private inputs and the real loopback verification UI. They run separately from the default test suite because they require Orca, restored inputs, a built warehouse/report, a generated PDF layer, and the verification server at `http://127.0.0.1:5174`.

```sh
E2E_TELEMETRY_DISABLED=1 mise exec -- bun test tests/local/fiscal-history.e2e.test.ts
```

The Bun test runner controls an owned Orca browser tab. Each test reloads the page, the suite closes only its own tab, and cleanup verifies that the tab is absent. Fiscal inputs are read-only; no records or credentials are created. Results, the execution SHA, screenshots, and fixture output remain in ignored `.agent/pr-e2e/<sha>-<time>/`.

The `@e2e-dev/web` engine was unavailable under the required seven-day package cooldown when these checks were added. This suite uses Orca and Bun; it does not claim to run that engine or a model.

| PRD criterion                         | Check                                                                                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Fiscal budget history AC1             | HTTP data paths show two actual initial mart lines, three signed changes, ten distinct settlement links, and original row/page references. |
| Fiscal budget history AC2/AC4         | Existing focused fixtures verify time boundaries, separate actuals, missing values/approvals, duplicates, and M:N aggregation.             |
| Fiscal budget history AC3             | Real UI shows both year-end differences and the incomplete scope explicitly.                                                               |
| Verification view AC2                 | Real UI links initial raw/staging rows, isolates issue 3 from issue 6 of the same target, and maps the rotated PDF to its raw row.         |
| Verification view AC3, changed inputs | Real UI displays source units and supplement scope; existing fixtures cover warning attribution.                                           |

The PDF check requires page dimensions of 842×595, a landscape image with a matching ratio, and a selected overlay inside the image that intersects the recorded supplement amount. It does not manually refresh the table after clicking the PDF word.

The suite verifies the current Komae FY2023 pilot (two moku). Full budget histories, business-by-setsu correspondence, public deployment, and hosted CI with private inputs remain outside these checks. Existing dbt integrity tests and Worker availability/build checks provide separate evidence for data preservation and public isolation; this suite does not substitute for them.
