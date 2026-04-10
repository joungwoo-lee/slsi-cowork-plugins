using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace DocCopyCli.Copiers;

/// <summary>
/// Shell-based Excel copier using COM automation.
/// Opens Excel via the shell (allows DRM authentication dialogs to appear),
/// then saves a DRM-free copy via SaveCopyAs.
/// </summary>
public static class ExcelCopier
{
    private const int PollIntervalMs = 500;

    public static void Copy(string filePath, string outputPath)
    {
        using var watchdog = new ProcessWatchdog("EXCEL");
        dynamic? app = null;
        dynamic? wb = null;

        try
        {
            Console.Error.WriteLine($"[ExcelCopier] Opening workbook via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath)
            {
                UseShellExecute = true,
                Verb = "open"
            });
            watchdog.DetectNewProcess();

            app = WaitForExcelApplication(watchdog, watchdog.TimeoutMs);
            Console.Error.WriteLine("[ExcelCopier] Attached to running Excel instance.");
            try { app.DisplayAlerts = false; } catch { }
            try { app.Visible = true; } catch { }

            wb = WaitForWorkbook(app, filePath, watchdog.TimeoutMs);
            try { wb.Activate(); } catch { }

            Console.Error.WriteLine("[ExcelCopier] Workbook opened. Checking DRM...");
            WaitForDrmDecryption(wb, watchdog.TimeoutMs);
            Console.Error.WriteLine("[ExcelCopier] DRM check passed. Saving copy...");

            EnsureDirectory(outputPath);

            // SaveCopyAs saves the in-memory (DRM-decrypted) content to a new file
            wb.SaveCopyAs(outputPath);

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
            try { return GetActiveComObject("Excel.Application"); } catch { }

            try
            {
                if (watchdog.TrackedPid is int pid)
                {
                    var app = GetExcelApplicationFromWindow(pid);
                    if (app != null)
                    {
                        Console.Error.WriteLine("[ExcelCopier] Attached via window handle fallback.");
                        return app;
                    }
                }
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

                var protectedWb = TryGetWorkbookFromProtectedView(excelApp, targetPath);
                if (protectedWb != null)
                {
                    Console.Error.WriteLine($"[ExcelCopier] Workbook attached from Protected View after {sw.ElapsedMilliseconds}ms.");
                    return protectedWb;
                }
            }
            catch { }

            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Workbook did not appear in Excel after {timeoutMs / 1000}s.");
    }

    private static void WaitForDrmDecryption(object wb, int timeoutMs)
    {
        dynamic workbook = wb;
        var sw = Stopwatch.StartNew();
        int attempt = 0;
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            attempt++;
            try
            {
                var sheets = workbook.Worksheets;
                if (SafeToInt(sheets?.Count) <= 0) { Thread.Sleep(PollIntervalMs); continue; }

                dynamic sheet = sheets[1];
                _ = sheet.Name;

                var used = sheet.UsedRange;
                if (used != null)
                {
                    Console.Error.WriteLine($"[ExcelCopier] DRM check OK on attempt {attempt} ({sw.ElapsedMilliseconds}ms)");
                    return;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ExcelCopier] DRM poll attempt {attempt}: {ex.GetType().Name}: {ex.Message}");
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

                    try { var wb = window.Workbook; if (wb != null) return wb; } catch { }
                    try { window.Edit(); } catch { }
                }
                catch { }
            }
        }
        catch { }
        return null;
    }

    private static object? GetExcelApplicationFromWindow(int pid)
    {
        try
        {
            var proc = Process.GetProcessById(pid);
            proc.Refresh();
            IntPtr hwnd = proc.MainWindowHandle;
            if (hwnd == IntPtr.Zero) return null;

            var app = TryGetAccessibleObject(hwnd);
            if (app != null) return app;

            IntPtr childHwnd = FindExcelDocumentWindow(hwnd);
            if (childHwnd == IntPtr.Zero) return null;
            return TryGetAccessibleObject(childHwnd);
        }
        catch { return null; }
    }

    private static object? TryGetAccessibleObject(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return null;
        Guid iid = typeof(IDispatch).GUID;
        int hr = AccessibleObjectFromWindow(hwnd, NativeObjectId, ref iid, out object? app);
        return (hr == 0) ? app : null;
    }

    private static IntPtr FindExcelDocumentWindow(IntPtr rootHwnd)
    {
        IntPtr match = IntPtr.Zero;
        EnumChildWindows(rootHwnd, (hwnd, _) =>
        {
            var sb = new StringBuilder(256);
            int len = GetClassName(hwnd, sb, sb.Capacity);
            string className = len > 0 ? sb.ToString(0, len) : string.Empty;
            if (string.Equals(className, "EXCEL7", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(className, "XLDESK", StringComparison.OrdinalIgnoreCase))
            {
                match = hwnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return match;
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
    private static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    [ComImport]
    [Guid("00020400-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDispatch;

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    private const uint NativeObjectId = 0xFFFFFFF0;
}
