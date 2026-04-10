using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace DocCopyCli.Copiers;

/// <summary>
/// Shell-based Excel copier. Opens via shell (DRM auth dialog supported),
/// then transfers sheet data through clipboard into a fresh Excel instance
/// that has no DRM context, and saves from there.
/// </summary>
public static class ExcelCopier
{
    private const int PollIntervalMs = 500;
    private const int XlPasteAll = -4104;

    public static void Copy(string filePath, string outputPath)
    {
        using var watchdog = new ProcessWatchdog("EXCEL");
        dynamic? app = null;
        dynamic? wb = null;
        dynamic? freshApp = null;
        dynamic? newWb = null;

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

            wb = WaitForWorkbook(app, filePath, watchdog.TimeoutMs);
            try { wb.Activate(); } catch { }

            Console.Error.WriteLine("[ExcelCopier] Workbook opened. Checking DRM...");
            WaitForDrmDecryption(wb, watchdog.TimeoutMs);
            Console.Error.WriteLine("[ExcelCopier] DRM check passed. Transferring sheets to fresh instance...");

            // 2. Spin up a fresh Excel instance (no DRM context)
            var excelType = Type.GetTypeFromProgID("Excel.Application")
                ?? throw new InvalidOperationException("Excel.Application COM class not registered.");
            freshApp = Activator.CreateInstance(excelType)
                ?? throw new InvalidOperationException("Failed to create Excel.Application COM instance.");

            freshApp.Visible = false;
            freshApp.DisplayAlerts = false;
            freshApp.ScreenUpdating = false;
            freshApp.EnableEvents = false;

            // 3. Add new workbook in fresh instance and adjust sheet count
            newWb = freshApp.Workbooks.Add();
            int srcSheetCount = SafeToInt(wb.Worksheets.Count);
            int dstSheetCount = SafeToInt(newWb.Worksheets.Count);

            // Add sheets if needed
            for (int i = dstSheetCount; i < srcSheetCount; i++)
                newWb.Worksheets.Add(After: newWb.Worksheets[newWb.Worksheets.Count]);

            // Remove extra sheets (must keep at least 1)
            for (int i = dstSheetCount; i > srcSheetCount; i--)
            {
                try { ((dynamic)newWb.Worksheets[i]).Delete(); } catch { }
            }

            // 4. Copy each sheet via clipboard into the fresh workbook
            for (int i = 1; i <= srcSheetCount; i++)
            {
                try
                {
                    dynamic srcSheet = wb.Worksheets[i];
                    dynamic dstSheet = newWb.Worksheets[i];

                    try { dstSheet.Name = srcSheet.Name; } catch { }

                    dynamic? usedRange = null;
                    try { usedRange = srcSheet.UsedRange; } catch { }

                    if (usedRange != null)
                    {
                        usedRange.Copy();
                        dstSheet.Activate();
                        dstSheet.Range("A1").PasteSpecial(XlPasteAll);
                        Console.Error.WriteLine($"[ExcelCopier] Sheet {i}/{srcSheetCount}: {srcSheet.Name}");
                    }
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[ExcelCopier] Warning on sheet {i}: {ex.Message}");
                }
            }

            // Clear clipboard to avoid leftover marching ants
            try { freshApp.CutCopyMode = false; } catch { }

            // 5. Save from the fresh instance — DRM driver will not intercept this
            EnsureDirectory(outputPath);
            int fileFormat = Path.GetExtension(filePath).ToLowerInvariant() == ".xls" ? -4143 : 51;
            newWb.SaveAs(
                Filename: outputPath,
                FileFormat: fileFormat,
                AddToMru: false);

            Console.Error.WriteLine($"[ExcelCopier] Saved: {outputPath}");
        }
        finally
        {
            try { newWb?.Close(false); } catch { }
            try { freshApp?.Quit(); } catch { }
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
                    var a = GetExcelApplicationFromWindow(pid);
                    if (a != null) { Console.Error.WriteLine("[ExcelCopier] Attached via window handle fallback."); return a; }
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
                var pv = TryGetWorkbookFromProtectedView(excelApp, targetPath);
                if (pv != null) { Console.Error.WriteLine("[ExcelCopier] Attached from Protected View."); return pv; }
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
                _ = sheet.UsedRange;
                Console.Error.WriteLine($"[ExcelCopier] DRM check OK on attempt {attempt} ({sw.ElapsedMilliseconds}ms)");
                return;
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
                    try { var w = window.Workbook; if (w != null) return w; } catch { }
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
            var a = TryGetAccessibleObject(hwnd);
            if (a != null) return a;
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

    [ComImport, Guid("00020400-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDispatch;

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    private const uint NativeObjectId = 0xFFFFFFF0;
}
