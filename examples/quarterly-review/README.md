# Quarterly review example

Create a Word report, an Excel workbook and a two-slide PowerPoint from the same illustrative quarterly dataset. The files contain editable text, tables and charts; the slide notes are editable. The script also renders a PDF preview of each file with LibreOffice.

From the repository root, install the current checkout and run:

```sh
python3 -m pip install ./office
python3 examples/quarterly-review/create.py /tmp/quarterly-review-example
```

The output directory must not already exist. LibreOffice must be on `PATH` for PDF rendering; `office-use doctor` reports its availability. Change `quarters` in `create.py` to explore the authoring specs. Review each PDF after changing content, including print ranges and chart labels. The figures and narrative are examples, and the report and slides are generated snapshots: editing the workbook later will not update them. The script does not use formulas or require recalculation.

The native chart rendering and document layout can differ across Office applications. PDF previews cover the local LibreOffice rendering, so review the editable files in the target application before distribution.
