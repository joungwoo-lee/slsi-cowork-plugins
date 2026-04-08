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
            Console.Error.WriteLine("[ExcelReader] Creating Excel COM instance...");
            app = new Application { Visible = true };
            Console.Error.WriteLine("[ExcelReader] Excel COM instance created OK.");
            app.DisplayAlerts = false;
            app.ScreenUpdating = true;
            watchdog.DetectNewProcess();

            Console.Error.WriteLine($"[ExcelReader] Opening workbook: {filePath}");
            wb = app.Workbooks.Open(
                filePath,       // Filename
                0,              // UpdateLinks (don't update)
                true,           // ReadOnly
                Type.Missing,   // Format
                Type.Missing,   // Password
                Type.Missing,   // WriteResPassword
                Type.Missing,   // IgnoreReadOnlyRecommended
                Type.Missing,   // Origin
                Type.Missing,   // Delimiter
                Type.Missing,   // Editable
                Type.Missing,   // Notify
                Type.Missing,   // Converter
                false           // AddToMru
            );

            try { app.Visible = true; } catch { }
            try { app.UserControl = true; } catch { }
            try { app.Interactive = true; } catch { }
            try { wb.Activate(); } catch { }
            try { wb.Windows[1].Visible = true; } catch { }
            try { wb.Windows[1].Activate(); } catch { }
            try { app.ScreenUpdating = true; } catch { }

            Console.Error.WriteLine("[ExcelReader] Workbook opened. Checking DRM...");
            WaitForDrmDecryption(wb, watchdog.TimeoutMs);
            Console.Error.WriteLine("[ExcelReader] DRM check passed. Reading sheets...");

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
            try { wb?.Close(false); } catch { }
            try { app?.Quit(); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static void WaitForDrmDecryption(Workbook wb, int timeoutMs)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        int attempt = 0;
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            attempt++;
            try
            {
                var sheets = wb.Worksheets;
                if (sheets.Count <= 0)
                {
                    Thread.Sleep(DrmPollIntervalMs);
                    continue;
                }

                var sheet = sheets[1] as Worksheet;
                if (sheet == null)
                {
                    Thread.Sleep(DrmPollIntervalMs);
                    continue;
                }

                _ = sheet.Name;

                var used = sheet.UsedRange;
                if (used == null)
                {
                    Thread.Sleep(DrmPollIntervalMs);
                    continue;
                }

                object? rowCountObj = null;
                try { rowCountObj = used.Rows?.Count; } catch { }

                if (TryGetPositiveCount(rowCountObj, out _) || rowCountObj != null)
                {
                    Console.Error.WriteLine($"[ExcelReader] DRM check OK on attempt {attempt} ({sw.ElapsedMilliseconds}ms)");
                    return;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ExcelReader] DRM poll attempt {attempt}: {ex.GetType().Name}: {ex.Message}");
            }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s.");
    }

    private static bool TryGetPositiveCount(object? value, out int count)
    {
        count = 0;
        if (value == null) return false;

        try
        {
            count = value switch
            {
                int i => i,
                short s => s,
                long l when l <= int.MaxValue => (int)l,
                float f => (int)f,
                double d => (int)d,
                decimal m => (int)m,
                _ => Convert.ToInt32(value)
            };
            return count > 0;
        }
        catch
        {
            return false;
        }
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
                        var cell = (NetOffice.ExcelApi.Range)usedRange.Cells[r, c];
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
