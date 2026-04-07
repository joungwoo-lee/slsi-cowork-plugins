using System.Text;
using NetOffice.ExcelApi;
using NetOffice.ExcelApi.Enums;

namespace DocReaderCli.Readers;

public static class ExcelReader
{
    private const int DrmPollIntervalMs = 500;
    private const int DrmTimeoutMs = 15_000;

    public static string Read(string filePath)
    {
        using var watchdog = new ProcessWatchdog("EXCEL");
        Application? app = null;
        Workbook? wb = null;

        try
        {
            app = new Application { Visible = false };
            app.DisplayAlerts = false;
            app.ScreenUpdating = false;
            watchdog.DetectNewProcess();

            wb = app.Workbooks.Open(
                Filename: filePath,
                ReadOnly: true,
                AddToMru: false
            );

            WaitForDrmDecryption(wb, watchdog.TimeoutMs);

            var sb = new StringBuilder();

            foreach (Worksheet sheet in wb.Worksheets)
            {
                try
                {
                    ExtractSheet(sheet, sb);
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[ExcelReader] Error reading sheet '{sheet.Name}': {ex.Message}");
                }
            }

            return sb.ToString();
        }
        finally
        {
            try { wb?.Close(SaveChanges: false); } catch { }
            try { app?.Quit(); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static void WaitForDrmDecryption(Workbook wb, int timeoutMs)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                var sheet = (Worksheet)wb.Worksheets[1];
                var used = sheet.UsedRange;
                if (used != null && used.Rows.Count > 0)
                    return;
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s.");
    }

    private static void ExtractSheet(Worksheet sheet, StringBuilder sb)
    {
        sb.AppendLine($"## Sheet: {sheet.Name}");
        sb.AppendLine();

        var usedRange = sheet.UsedRange;
        if (usedRange == null) return;

        int rowCount = usedRange.Rows.Count;
        int colCount = usedRange.Columns.Count;
        int startRow = usedRange.Row;
        int startCol = usedRange.Column;

        if (rowCount == 0 || colCount == 0) return;

        // Read all values at once for performance
        object[,]? values = null;
        try
        {
            var v = usedRange.Text ?? usedRange.Value;
            if (v is object[,] arr)
                values = arr;
        }
        catch { }

        // Emit as markdown table
        for (int r = 1; r <= rowCount; r++)
        {
            sb.Append("|");
            for (int c = 1; c <= colCount; c++)
            {
                string cellText = "";
                try
                {
                    if (values != null)
                    {
                        cellText = values[r, c]?.ToString() ?? "";
                    }
                    else
                    {
                        var cell = (Range)usedRange.Cells[r, c];
                        cellText = cell.Text?.ToString() ?? cell.Value?.ToString() ?? "";
                    }
                }
                catch { }

                cellText = cellText.Replace("|", "\\|").Replace("\n", " ").Replace("\r", "");
                sb.Append($" {cellText} |");
            }
            sb.AppendLine();

            // Header separator
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
}
