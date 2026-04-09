using System.Runtime.InteropServices;
using System.Text;

namespace DocReaderCli.Readers;

/// <summary>
/// Reads Excel files via COM Automation using ProgID-based late binding (dynamic).
/// This avoids a hard dependency on the Microsoft.Office.Interop.Excel assembly at
/// runtime, which fails under PublishSingleFile / SelfContained deployments.
/// </summary>
public static class ExcelInteropReader
{
    public static string Read(string filePath)
    {
        dynamic? app = null;
        dynamic? workbook = null;

        using var messageFilter = OleMessageFilter.Register();

        try
        {
            Console.Error.WriteLine($"[ExcelInteropReader] Opening workbook with Interop: {filePath}");

            var excelType = Type.GetTypeFromProgID("Excel.Application")
                ?? throw new InvalidOperationException(
                    "Excel is not installed or 'Excel.Application' COM class is not registered.");

            app = Activator.CreateInstance(excelType)
                ?? throw new InvalidOperationException(
                    "Failed to create Excel.Application COM instance.");

            app.Visible = false;
            app.DisplayAlerts = false;
            app.ScreenUpdating = false;
            app.EnableEvents = false;
            app.AskToUpdateLinks = false;

            workbook = app.Workbooks.Open(
                filePath,
                UpdateLinks: 0,
                ReadOnly: true,
                IgnoreReadOnlyRecommended: true,
                AddToMru: false,
                CorruptLoad: 0 /* xlNormalLoad */);

            var sb = new StringBuilder();
            int sheetCount = (int)workbook.Worksheets.Count;

            for (int i = 1; i <= sheetCount; i++)
            {
                dynamic? sheet = null;
                dynamic? usedRange = null;
                try
                {
                    sheet = workbook.Worksheets[i];
                    if (sheet == null)
                        continue;

                    sb.AppendLine($"## Sheet: {sheet.Name}");
                    sb.AppendLine();

                    usedRange = sheet.UsedRange;
                    int rowCount = usedRange != null ? (int)usedRange.Rows.Count : 0;
                    int colCount = usedRange != null ? (int)usedRange.Columns.Count : 0;
                    if (rowCount == 0 || colCount == 0)
                    {
                        sb.AppendLine();
                        continue;
                    }

                    object? rawValues = null;
                    try { rawValues = usedRange?.Value2; } catch { }

                    for (int r = 1; r <= rowCount; r++)
                    {
                        sb.Append('|');
                        for (int c = 1; c <= colCount; c++)
                        {
                            string cellText = ReadCellText(usedRange, rawValues, r, c);
                            cellText = cellText.Replace("|", "\\|").Replace("\n", " ").Replace("\r", "");
                            sb.Append($" {cellText} |");
                        }
                        sb.AppendLine();

                        if (r == 1)
                        {
                            sb.Append('|');
                            for (int c = 0; c < colCount; c++)
                                sb.Append(" --- |");
                            sb.AppendLine();
                        }
                    }

                    sb.AppendLine();
                }
                finally
                {
                    ReleaseComObject(ref usedRange);
                    ReleaseComObject(ref sheet);
                }
            }

            return sb.ToString();
        }
        finally
        {
            try { workbook?.Close(false); } catch { }
            try { app?.Quit(); } catch { }

            ReleaseComObject(ref workbook);
            ReleaseComObject(ref app);
        }
    }

    private static string ReadCellText(dynamic? usedRange, object? rawValues, int row, int col)
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

        dynamic? cell = null;
        try
        {
            cell = usedRange?.Cells[row, col];
            if (cell == null) return "";
            string? text = null;
            try { text = cell.Text?.ToString(); } catch { }
            if (!string.IsNullOrEmpty(text)) return text!;
            try { text = cell.Value2?.ToString(); } catch { }
            return text ?? "";
        }
        catch
        {
            return "";
        }
        finally
        {
            ReleaseComObject(ref cell);
        }
    }

    private static void ReleaseComObject<T>(ref T? obj) where T : class
    {
        if (obj == null) return;
        try
        {
            if (Marshal.IsComObject(obj))
                Marshal.ReleaseComObject(obj);
        }
        catch
        {
        }
        obj = null;
    }
}
