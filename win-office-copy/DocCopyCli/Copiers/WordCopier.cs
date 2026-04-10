using System.Diagnostics;
using System.Runtime.InteropServices;

namespace DocCopyCli.Copiers;

public static class WordCopier
{
    private const int PollIntervalMs = 500;

    public static void Copy(string filePath, string outputPath)
    {
        using var watchdog = new ProcessWatchdog("WINWORD");
        dynamic? app = null;
        dynamic? doc = null;
        dynamic? freshApp = null;
        dynamic? newDoc = null;

        try
        {
            // 1. Shell-open the DRM document so the DRM agent can authenticate
            Console.Error.WriteLine($"[WordCopier] Opening document via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath) { UseShellExecute = true, Verb = "open" });
            watchdog.DetectNewProcess();

            app = WaitForWordApplication(watchdog.TimeoutMs);
            Console.Error.WriteLine("[WordCopier] Attached to running Word instance.");
            try { app.Visible = true; } catch { }

            doc = WaitForWordDocument(app, filePath, watchdog.TimeoutMs);
            try { doc.Activate(); } catch { }

            Console.Error.WriteLine("[WordCopier] Document opened. Checking DRM...");
            WaitForDrmDecryption(doc, watchdog.TimeoutMs);
            Console.Error.WriteLine("[WordCopier] DRM check passed. Copying content to clipboard...");

            // 2. Copy all content to clipboard while it is decrypted in memory
            doc.Content.Copy();

            // 3. Spin up a completely fresh Word instance (no DRM context)
            Console.Error.WriteLine("[WordCopier] Opening fresh Word instance for DRM-free save...");
            var wordType = Type.GetTypeFromProgID("Word.Application")
                ?? throw new InvalidOperationException("Word.Application COM class not registered.");
            freshApp = Activator.CreateInstance(wordType)
                ?? throw new InvalidOperationException("Failed to create Word.Application COM instance.");

            freshApp.Visible = false;
            freshApp.DisplayAlerts = false;

            // 4. Create a new blank document and paste — the fresh instance has no DRM association
            newDoc = freshApp.Documents.Add();
            newDoc.Content.Paste();
            Console.Error.WriteLine("[WordCopier] Content pasted into fresh document.");

            // 5. Save from the fresh instance — DRM driver will not intercept this
            EnsureDirectory(outputPath);
            int fileFormat = Path.GetExtension(filePath).ToLowerInvariant() == ".doc" ? 0 : 16;
            newDoc.SaveAs2(
                FileName: outputPath,
                FileFormat: fileFormat,
                AddToRecentFiles: false);

            Console.Error.WriteLine($"[WordCopier] Saved: {outputPath}");
        }
        finally
        {
            try { newDoc?.Close(false); } catch { }
            try { freshApp?.Quit(false); } catch { }
            try { doc?.Close(false); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static object WaitForWordApplication(int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try { return GetActiveComObject("Word.Application"); } catch { }
            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Word instance was not available after {timeoutMs / 1000}s.");
    }

    private static object WaitForWordDocument(object app, string filePath, int timeoutMs)
    {
        dynamic wordApp = app;
        var targetPath = Path.GetFullPath(filePath);
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                dynamic docs = wordApp.Documents;
                int count = SafeToInt(docs?.Count);
                for (int i = 1; i <= count; i++)
                {
                    try
                    {
                        dynamic candidate = docs[i];
                        if (PathsMatch(candidate.FullName, targetPath))
                        {
                            Console.Error.WriteLine($"[WordCopier] Document attached after {sw.ElapsedMilliseconds}ms.");
                            return candidate;
                        }
                    }
                    catch { }
                }
            }
            catch { }
            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Document did not appear in Word after {timeoutMs / 1000}s.");
    }

    private static void WaitForDrmDecryption(object doc, int timeoutMs)
    {
        dynamic document = doc;
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                var range = document.Content;
                if (range != null && range.Text != null && range.Text.Trim().Length > 0)
                    return;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[WordCopier] DRM poll: {ex.GetType().Name}: {ex.Message}");
            }
            Thread.Sleep(PollIntervalMs);
        }
        try { if (document.Content?.Text?.Trim().Length == 0) return; } catch { }
        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s. " +
            "Open the document manually to authenticate DRM first, then retry.");
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
}
