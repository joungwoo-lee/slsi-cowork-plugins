using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using DocUnlockCli.Helpers;
using DocUnlockCli.Models;

namespace DocUnlockCli.Copiers;

/// <summary>
/// Shell-based Excel copier. Opens via shell (DRM auth dialog supported),
/// then transfers sheet data through clipboard into a fresh Excel instance
/// that has no DRM context, and saves from there.
/// </summary>
public static class ExcelCopier
{
    private const int PollIntervalMs = 500;
    private const int DrmForegroundHoldMs = 1500;
    private const int XlPasteAll = -4104;

    public static void Copy(string filePath, string outputPath)
    {
        outputPath = OpenXmlSaver.NormalizeExcelOutputPath(outputPath);
        using var watchdog = new ProcessWatchdog("EXCEL");
        dynamic? app = null;
        dynamic? wb = null;

        try
        {
            // 1. Shell-open the DRM workbook
            Console.Error.WriteLine($"[ExcelCopier] Opening workbook via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath) { UseShellExecute = true, Verb = "open" });
            watchdog.DetectNewProcess();

            app = WaitForExcelApplication(watchdog, watchdog.TimeoutMs);
            Console.Error.WriteLine("[ExcelCopier] Attached to running Excel instance.");
            try { app.DisplayAlerts = false; } catch { }
            try { app.Visible = true; } catch { }
            try { app.ScreenUpdating = true; } catch { }
            try { app.UserControl = true; } catch { }
            try { app.Interactive = true; } catch { }
            ForegroundExcelWindow(watchdog, 5_000);

            wb = WaitForWorkbook(app, filePath, watchdog.TimeoutMs);
            PrepareWorkbookForInteraction(wb);
            ForegroundExcelWindow(watchdog, DrmForegroundHoldMs);

            Console.Error.WriteLine("[ExcelCopier] Workbook opened. Checking DRM...");
            WaitForDrmDecryption(wb, watchdog, watchdog.TimeoutMs);
            var workbookSnapshot = CaptureWorkbook(wb);
            string markdownPath = MarkdownExporter.GetMarkdownPath(outputPath, filePath);
            MarkdownExporter.WriteWorkbookMarkdown(markdownPath, workbookSnapshot);
            Console.Error.WriteLine("[ExcelCopier] DRM check passed. Rebuilding OOXML workbook...");

            OpenXmlSaver.SaveWorkbook(outputPath, workbookSnapshot);

            Console.Error.WriteLine($"[ExcelCopier] Saved: {outputPath}");
        }
        finally
        {
            try { wb?.Close(false); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static object WaitForExcelApplication(ProcessWatchdog watchdog, int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            watchdog.DetectNewProcess();
            try { return GetActiveComObject("Excel.Application"); } catch { }
            try
            {
                if (watchdog.TrackedPid is int pid)
                {
                    var a = GetExcelApplicationFromWindow(pid);
                    if (a != null) { Console.Error.WriteLine("[ExcelCopier] Attached via window handle fallback."); return a; }
                }
            }
            catch { }
            try
            {
                var a = GetExcelApplicationFromAnyWindow();
                if (a != null) { Console.Error.WriteLine("[ExcelCopier] Attached via global window scan fallback."); return a; }
            }
            catch { }
            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Excel instance was not available after {timeoutMs / 1000}s.");
    }

    private static object WaitForWorkbook(object app, string filePath, int timeoutMs)
    {
        dynamic excelApp = app;
        var targetPath = Path.GetFullPath(filePath);
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                dynamic workbooks = excelApp.Workbooks;
                int count = SafeToInt(workbooks?.Count);
                for (int i = 1; i <= count; i++)
                {
                    try
                    {
                        dynamic workbook = workbooks[i];
                        if (PathsMatch(workbook.FullName, targetPath))
                        {
                            Console.Error.WriteLine($"[ExcelCopier] Workbook attached after {sw.ElapsedMilliseconds}ms.");
                            return workbook;
                        }
                    }
                    catch { }
                }
                var pv = TryGetWorkbookFromProtectedView(excelApp, targetPath);
                if (pv != null) { Console.Error.WriteLine("[ExcelCopier] Attached from Protected View."); return pv; }
            }
            catch { }
            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Workbook did not appear in Excel after {timeoutMs / 1000}s.");
    }

    private static void WaitForDrmDecryption(object wb, ProcessWatchdog watchdog, int timeoutMs)
    {
        dynamic workbook = wb;
        var sw = Stopwatch.StartNew();
        int attempt = 0;
        bool focusReleased = false;
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            attempt++;
            try
            {
                var sheets = workbook.Worksheets;
                if (SafeToInt(sheets?.Count) <= 0) { Thread.Sleep(PollIntervalMs); continue; }
                dynamic sheet = sheets[1];
                _ = sheet.Name;
                _ = sheet.UsedRange;
                Console.Error.WriteLine($"[ExcelCopier] DRM check OK on attempt {attempt} ({sw.ElapsedMilliseconds}ms)");
                return;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ExcelCopier] DRM poll attempt {attempt}: {ex.GetType().Name}: {ex.Message}");
            }

            if (!focusReleased && sw.ElapsedMilliseconds >= DrmForegroundHoldMs)
            {
                focusReleased = TryBackgroundExcelWindow(watchdog);
                if (focusReleased)
                    Console.Error.WriteLine($"[ExcelCopier] Released Excel focus after {sw.ElapsedMilliseconds}ms to let DRM finalize.");
            }

            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s. " +
            "Open the file manually to authenticate DRM first, then retry.");
    }

    private static object? TryGetWorkbookFromProtectedView(dynamic excelApp, string targetPath)
    {
        try
        {
            dynamic pvWindows = excelApp.ProtectedViewWindows;
            int count = SafeToInt(pvWindows?.Count);
            for (int i = 1; i <= count; i++)
            {
                try
                {
                    dynamic window = pvWindows[i];
                    string? sourcePath = null;
                    try { sourcePath = window.SourceFullName?.ToString(); } catch { }
                    if (!PathsMatch(sourcePath, targetPath)) continue;
                    try { var w = window.Workbook; if (w != null) return w; } catch { }
                    try { window.Edit(); } catch { }
                }
                catch { }
            }
        }
        catch { }
        return null;
    }

    private static List<ExcelSheetSnapshot> CaptureWorkbook(dynamic workbook)
    {
        var result = new List<ExcelSheetSnapshot>();
        int sheetCount = SafeToInt(workbook.Worksheets?.Count);
        for (int i = 1; i <= sheetCount; i++)
        {
            try
            {
                dynamic sheet = workbook.Worksheets[i];
                string name = SafeToString(sheet.Name, $"Sheet{i}");
                result.Add(new ExcelSheetSnapshot(name, CaptureSheetRows(sheet)));
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ExcelCopier] Warning capturing sheet {i}: {ex.Message}");
            }
        }

        return result;
    }

    private static IReadOnlyList<IReadOnlyList<string>> CaptureSheetRows(dynamic sheet)
    {
        try
        {
            dynamic usedRange = sheet.UsedRange;
            int rowCount = SafeToInt(usedRange?.Rows?.Count);
            int colCount = SafeToInt(usedRange?.Columns?.Count);
            if (rowCount <= 0 || colCount <= 0) return [];

            object? values = null;
            try { values = usedRange.Value2; } catch { }
            if (values is object[,] matrix)
            {
                var rows = new List<IReadOnlyList<string>>(rowCount);
                for (int row = 1; row <= rowCount; row++)
                {
                    var cells = new List<string>(colCount);
                    for (int col = 1; col <= colCount; col++)
                        cells.Add(CellToString(matrix[row, col]));
                    rows.Add(TrimTrailingEmptyCells(cells));
                }

                return TrimTrailingEmptyRows(rows);
            }

            if (rowCount == 1 && colCount == 1)
                return [[CellToString(values)]];
        }
        catch { }

        return [];
    }

    private static IReadOnlyList<IReadOnlyList<string>> TrimTrailingEmptyRows(List<IReadOnlyList<string>> rows)
    {
        int count = rows.Count;
        while (count > 0 && rows[count - 1].All(string.IsNullOrEmpty)) count--;
        return count == rows.Count ? rows : rows.Take(count).ToList();
    }

    private static IReadOnlyList<string> TrimTrailingEmptyCells(List<string> cells)
    {
        int count = cells.Count;
        while (count > 0 && string.IsNullOrEmpty(cells[count - 1])) count--;
        return count == cells.Count ? cells : cells.Take(count).ToList();
    }

    private static string CellToString(object? value)
    {
        return value switch
        {
            null => string.Empty,
            double d => d.ToString(System.Globalization.CultureInfo.InvariantCulture),
            float f => f.ToString(System.Globalization.CultureInfo.InvariantCulture),
            _ => value.ToString() ?? string.Empty,
        };
    }

    private static string SafeToString(object? value, string fallback = "")
    {
        try { return value?.ToString() ?? fallback; } catch { return fallback; }
    }

    private static object? GetExcelApplicationFromWindow(int pid)
    {
        try
        {
            foreach (IntPtr hwnd in GetProcessWindows(pid))
            {
                var a = TryGetAccessibleObject(hwnd);
                if (a != null) return a;

                IntPtr childHwnd = FindExcelDocumentWindow(hwnd);
                if (childHwnd == IntPtr.Zero) continue;

                a = TryGetAccessibleObject(childHwnd);
                if (a != null) return a;
            }

            return null;
        }
        catch { return null; }
    }

    private static object? GetExcelApplicationFromAnyWindow()
    {
        foreach (var proc in Process.GetProcessesByName("EXCEL"))
        {
            try
            {
                var app = GetExcelApplicationFromWindow(proc.Id);
                if (app != null) return app;
            }
            catch { }
            finally
            {
                try { proc.Dispose(); } catch { }
            }
        }

        return null;
    }

    private static void BackgroundExcelWindow(ProcessWatchdog watchdog, int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            watchdog.DetectNewProcess();
            if (TryBackgroundExcelWindow(watchdog)) return;
            Thread.Sleep(100);
        }
    }

    private static void ForegroundExcelWindow(ProcessWatchdog watchdog, int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            watchdog.DetectNewProcess();
            if (TryForegroundExcelWindow(watchdog)) return;
            Thread.Sleep(100);
        }
    }

    private static bool TryBackgroundExcelWindow(ProcessWatchdog watchdog)
    {
        if (watchdog.TrackedPid is int trackedPid && TryBackgroundProcessWindows(trackedPid))
            return true;

        foreach (var proc in Process.GetProcessesByName("EXCEL"))
        {
            try
            {
                if (TryBackgroundProcessWindows(proc.Id)) return true;
            }
            catch { }
            finally
            {
                try { proc.Dispose(); } catch { }
            }
        }

        return false;
    }

    private static bool TryForegroundExcelWindow(ProcessWatchdog watchdog)
    {
        if (watchdog.TrackedPid is int trackedPid && TryForegroundProcessWindows(trackedPid))
            return true;

        foreach (var proc in Process.GetProcessesByName("EXCEL"))
        {
            try
            {
                if (TryForegroundProcessWindows(proc.Id)) return true;
            }
            catch { }
            finally
            {
                try { proc.Dispose(); } catch { }
            }
        }

        return false;
    }

    private static bool TryBackgroundProcessWindows(int pid)
    {
        bool changed = false;
        foreach (IntPtr hwnd in GetProcessWindows(pid))
        {
            if (hwnd == IntPtr.Zero) continue;

            ShowWindowAsync(hwnd, SwShowMinNoActive);
            changed = true;
        }

        if (!changed) return false;

        IntPtr backgroundTarget = GetBackgroundTargetWindow();
        if (backgroundTarget != IntPtr.Zero)
        {
            ShowWindowAsync(backgroundTarget, SwRestore);
            SetForegroundWindow(backgroundTarget);
        }

        return true;
    }

    private static bool TryForegroundProcessWindows(int pid)
    {
        bool changed = false;
        foreach (IntPtr hwnd in GetProcessWindows(pid))
        {
            if (hwnd == IntPtr.Zero) continue;

            ShowWindowAsync(hwnd, SwRestore);
            SetForegroundWindow(hwnd);
            changed = true;
        }

        return changed;
    }

    private static void PrepareWorkbookForInteraction(dynamic workbook)
    {
        try { workbook.Activate(); } catch { }
        try
        {
            dynamic windows = workbook.Windows;
            int count = SafeToInt(windows?.Count);
            if (count > 0)
            {
                try { windows[1].Visible = true; } catch { }
                try { windows[1].Activate(); } catch { }
            }
        }
        catch { }
    }

    private static IntPtr GetBackgroundTargetWindow()
    {
        IntPtr consoleWindow = GetConsoleWindow();
        if (consoleWindow != IntPtr.Zero && !IsExcelWindow(consoleWindow))
            return consoleWindow;

        IntPtr foregroundWindow = GetForegroundWindow();
        if (foregroundWindow != IntPtr.Zero && !IsExcelWindow(foregroundWindow))
            return foregroundWindow;

        IntPtr shellWindow = GetShellWindow();
        if (shellWindow != IntPtr.Zero && !IsExcelWindow(shellWindow))
            return shellWindow;

        return IntPtr.Zero;
    }

    private static bool IsExcelWindow(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return false;

        try
        {
            GetWindowThreadProcessId(hwnd, out uint pid);
            if (pid != 0)
            {
                using var process = Process.GetProcessById((int)pid);
                if (string.Equals(process.ProcessName, "EXCEL", StringComparison.OrdinalIgnoreCase))
                    return true;
            }
        }
        catch { }

        var sb = new StringBuilder(256);
        int len = GetClassName(hwnd, sb, sb.Capacity);
        string cls = len > 0 ? sb.ToString(0, len) : string.Empty;
        return string.Equals(cls, "XLMAIN", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(cls, "EXCEL7", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(cls, "XLDESK", StringComparison.OrdinalIgnoreCase);
    }

    private static object? TryGetAccessibleObject(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return null;
        Guid iid = typeof(IDispatch).GUID;
        int hr = AccessibleObjectFromWindow(hwnd, NativeObjectId, ref iid, out object? obj);
        return hr == 0 ? obj : null;
    }

    private static IntPtr FindExcelDocumentWindow(IntPtr rootHwnd)
    {
        IntPtr match = IntPtr.Zero;
        EnumChildWindows(rootHwnd, (hwnd, _) =>
        {
            var sb = new StringBuilder(256);
            int len = GetClassName(hwnd, sb, sb.Capacity);
            string cls = len > 0 ? sb.ToString(0, len) : string.Empty;
            if (string.Equals(cls, "EXCEL7", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(cls, "XLDESK", StringComparison.OrdinalIgnoreCase))
            { match = hwnd; return false; }
            return true;
        }, IntPtr.Zero);
        return match;
    }

    private static List<IntPtr> GetProcessWindows(int pid)
    {
        var result = new List<IntPtr>();

        EnumWindows((hwnd, lParam) =>
        {
            GetWindowThreadProcessId(hwnd, out uint windowPid);
            if ((int)windowPid != pid) return true;

            if (!IsWindowVisible(hwnd)) return true;

            var sb = new StringBuilder(256);
            int len = GetClassName(hwnd, sb, sb.Capacity);
            string cls = len > 0 ? sb.ToString(0, len) : string.Empty;
            if (string.Equals(cls, "XLMAIN", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(cls, "EXCEL7", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(cls, "XLDESK", StringComparison.OrdinalIgnoreCase))
            {
                result.Add(hwnd);
            }

            return true;
        }, IntPtr.Zero);

        return result;
    }

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    private static int SafeToInt(object? value)
    {
        try { return Convert.ToInt32(value); } catch { return 0; }
    }

    private static bool PathsMatch(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right)) return false;
        return string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);
    }

    private static object GetActiveComObject(string progId)
    {
        var clsid = Type.GetTypeFromProgID(progId)?.GUID
            ?? throw new COMException($"Could not resolve COM ProgID '{progId}'.");
        int hr = GetActiveObject(ref clsid, IntPtr.Zero, out var obj);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        if (obj == null) throw new COMException($"Active COM object '{progId}' was null.");
        return obj;
    }

    [DllImport("oleaut32.dll")]
    private static extern int GetActiveObject(ref Guid rclsid, IntPtr reserved,
        [MarshalAs(UnmanagedType.IUnknown)] out object obj);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint dwObjectID,
        ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out object? ppvObject);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern IntPtr GetShellWindow();

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    [ComImport, Guid("00020400-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDispatch;

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    private const uint NativeObjectId = 0xFFFFFFF0;
    private const int SwShowMinNoActive = 7;
    private const int SwRestore = 9;
}
