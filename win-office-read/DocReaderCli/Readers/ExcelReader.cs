using System.Diagnostics;
using System.Runtime.InteropServices;
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
            Console.Error.WriteLine($"[ExcelReader] Opening workbook via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath)
            {
                UseShellExecute = true,
                Verb = "open"
            });
            watchdog.DetectNewProcess();

            app = WaitForExcelApplication(watchdog.TimeoutMs);
            if (app == null)
                throw new TimeoutException("Excel instance attached as null COM object.");

            Console.Error.WriteLine("[ExcelReader] Attached to running Excel instance.");
            app.DisplayAlerts = false;
            app.Visible = true;
            app.ScreenUpdating = true;

            wb = WaitForWorkbook(app, filePath, watchdog.TimeoutMs);
            if (wb == null)
                throw new TimeoutException("Workbook attached as null COM object.");

            try { app.Visible = true; } catch { }
            try { app.UserControl = true; } catch { }
            try { app.Interactive = true; } catch { }
            try { wb.ChangeFileAccess(XlFileAccess.xlReadOnly); } catch { }
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
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static Application WaitForExcelApplication(int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                var app = GetActiveComObject("Excel.Application") as Application;
                if (app != null)
                    return app;
            }
            catch
            {
            }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException($"Excel instance was not available after {timeoutMs / 1000}s.");
    }

    private static Workbook WaitForWorkbook(Application app, string filePath, int timeoutMs)
    {
        var targetPath = Path.GetFullPath(filePath);
        var sw = Stopwatch.StartNew();

        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                foreach (Workbook workbook in app.Workbooks)
                {
                    try
                    {
                        if (PathsMatch(workbook.FullName, targetPath))
                        {
                            Console.Error.WriteLine($"[ExcelReader] Workbook attached after {sw.ElapsedMilliseconds}ms.");
                            return workbook;
                        }
                    }
                    catch
                    {
                    }
                }
            }
            catch
            {
            }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException($"Workbook did not appear in Excel after {timeoutMs / 1000}s.");
    }

    private static bool PathsMatch(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
            return false;

        return string.Equals(
            Path.GetFullPath(left),
            Path.GetFullPath(right),
            StringComparison.OrdinalIgnoreCase);
    }

    private static object GetActiveComObject(string progId)
    {
        var clsid = Type.GetTypeFromProgID(progId)?.GUID
            ?? throw new COMException($"Could not resolve COM ProgID '{progId}'.");

        int hr = GetActiveObject(ref clsid, IntPtr.Zero, out var obj);
        if (hr != 0)
            Marshal.ThrowExceptionForHR(hr);
        if (obj == null)
            throw new COMException($"Active COM object '{progId}' was null.");

        return obj;
    }

    [DllImport("oleaut32.dll")]
    private static extern int GetActiveObject(ref Guid rclsid, IntPtr reserved, [MarshalAs(UnmanagedType.IUnknown)] out object obj);

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
