using System.Runtime.InteropServices;
using System.Text;
using Excel = Microsoft.Office.Interop.Excel;

namespace DocReaderCli.Readers;

public static class ExcelInteropReader
{
    public static string Read(string filePath)
    {
        Excel.Application? app = null;
        Excel.Workbook? workbook = null;

        try
        {
            Console.Error.WriteLine($"[ExcelInteropReader] Opening workbook with Interop: {filePath}");

            app = new Excel.Application
            {
                Visible = false,
                DisplayAlerts = false,
                ScreenUpdating = false,
                EnableEvents = false,
                AskToUpdateLinks = false
            };

            workbook = app.Workbooks.Open(
                filePath,
                UpdateLinks: 0,
                ReadOnly: true,
                IgnoreReadOnlyRecommended: true,
                AddToMru: false,
                CorruptLoad: Excel.XlCorruptLoad.xlNormalLoad);

            var sb = new StringBuilder();
            int sheetCount = workbook.Worksheets.Count;

            for (int i = 1; i <= sheetCount; i++)
            {
                Excel.Worksheet? sheet = null;
                Excel.Range? usedRange = null;
                try
                {
                    sheet = workbook.Worksheets[i] as Excel.Worksheet;
                    if (sheet == null)
                        continue;

                    sb.AppendLine($"## Sheet: {sheet.Name}");
                    sb.AppendLine();

                    usedRange = sheet.UsedRange;
                    int rowCount = usedRange?.Rows.Count ?? 0;
                    int colCount = usedRange?.Columns.Count ?? 0;
                    if (rowCount == 0 || colCount == 0)
                    {
                        sb.AppendLine();
                        continue;
                    }

                    object? rawValues = null;
                    try { rawValues = usedRange?.Value2; } catch { }

                    for (int r = 1; r <= rowCount; r++)
                    {
                        sb.Append("|");
                        for (int c = 1; c <= colCount; c++)
                        {
                            string cellText = ReadCellText(usedRange, rawValues, r, c);
                            cellText = cellText.Replace("|", "\\|").Replace("\n", " ").Replace("\r", "");
                            sb.Append($" {cellText} |");
                        }
                        sb.AppendLine();

                        if (r == 1)
                        {
                            sb.Append("|");
                            for (int c = 0; c < colCount; c++)
                                sb.Append(" --- |");
                            sb.AppendLine();
                        }
                    }

                    sb.AppendLine();
                }
                finally
                {
                    ReleaseComObject(usedRange);
                    ReleaseComObject(sheet);
                }
            }

            return sb.ToString();
        }
        finally
        {
            try { workbook?.Close(false); } catch { }
            try { app?.Quit(); } catch { }

            ReleaseComObject(workbook);
            ReleaseComObject(app);
        }
    }

    private static string ReadCellText(Excel.Range? usedRange, object? rawValues, int row, int col)
    {
        try
        {
            if (rawValues is object[,] matrix)
                return matrix[row, col]?.ToString() ?? "";

            if (rawValues != null && row == 1 && col == 1)
                return rawValues.ToString() ?? "";
        }
        catch
        {
        }

        Excel.Range? cell = null;
        try
        {
            cell = usedRange?.Cells[row, col] as Excel.Range;
            return cell?.Text?.ToString() ?? cell?.Value2?.ToString() ?? "";
        }
        catch
        {
            return "";
        }
        finally
        {
            ReleaseComObject(cell);
        }
    }

    private static void ReleaseComObject(object? obj)
    {
        try
        {
            if (obj != null && Marshal.IsComObject(obj))
                Marshal.ReleaseComObject(obj);
        }
        catch
        {
        }
    }
}
