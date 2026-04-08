using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace DocReaderCli.Readers;

public static class WordReader
{
    private const int DrmPollIntervalMs = 500;
    private const int DrmTimeoutMs = 15_000;

    public static string Read(string filePath)
    {
        using var watchdog = new ProcessWatchdog("WINWORD");
        dynamic? app = null;
        dynamic? doc = null;

        try
        {
            Console.Error.WriteLine($"[WordReader] Opening document via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath)
            {
                UseShellExecute = true,
                Verb = "open"
            });
            watchdog.DetectNewProcess();

            app = WaitForWordApplication(watchdog.TimeoutMs);
            Console.Error.WriteLine("[WordReader] Attached to running Word instance.");
            try { app.Visible = true; } catch { }

            doc = WaitForWordDocument(app, filePath, watchdog.TimeoutMs);
            try { doc.Activate(); } catch { }

            Console.Error.WriteLine("[WordReader] Document opened. Checking DRM...");
            WaitForDrmDecryption(doc, watchdog.TimeoutMs);
            Console.Error.WriteLine("[WordReader] DRM check passed. Extracting content...");

            var sb = new StringBuilder();
            ExtractContent(doc, sb);
            return sb.ToString();
        }
        finally
        {
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
            try
            {
                return GetActiveComObject("Word.Application");
            }
            catch
            {
            }

            Thread.Sleep(DrmPollIntervalMs);
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
                            Console.Error.WriteLine($"[WordReader] Document attached after {sw.ElapsedMilliseconds}ms.");
                            return candidate;
                        }
                    }
                    catch { }
                }
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException($"Document did not appear in Word after {timeoutMs / 1000}s.");
    }

    private static void WaitForDrmDecryption(object doc, int timeoutMs)
    {
        dynamic document = doc;
        var sw = System.Diagnostics.Stopwatch.StartNew();
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
                Console.Error.WriteLine($"[WordReader] DRM poll: {ex.GetType().Name}: {ex.Message}");
            }

            Thread.Sleep(DrmPollIntervalMs);
        }

        // Allow empty documents to pass (the file opened but has no content)
        try
        {
            if (document.Content?.Text?.Trim().Length == 0)
                return;
        }
        catch { }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s. The document may require manual DRM authentication.");
    }

    private static int SafeToInt(object? value)
    {
        try { return Convert.ToInt32(value); } catch { return 0; }
    }

    private static bool PathsMatch(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
            return false;

        return string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);
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

    private static void ExtractContent(object doc, StringBuilder sb)
    {
        dynamic document = doc;
        int tableIdx = 0;
        var tableRanges = new List<(int Start, int End)>();

        // Pre-collect table ranges to avoid duplicating table text in paragraphs
        int tableCount = SafeToInt(document.Tables?.Count);
        for (int i = 1; i <= tableCount; i++)
        {
            try
            {
                var table = document.Tables[i];
                var r = table.Range;
                if (r != null)
                    tableRanges.Add((r.Start, r.End));
            }
            catch { }
        }

        // Walk paragraphs in document order
        int paraCount = SafeToInt(document.Paragraphs?.Count);
        for (int i = 1; i <= paraCount; i++)
        {
            try
            {
                var para = document.Paragraphs[i];
                var range = para.Range;
                if (range == null) continue;

                int paraStart = range.Start;

                // Check if this paragraph is inside a table
                bool inTable = tableRanges.Any(t => paraStart >= t.Start && paraStart <= t.End);
                if (inTable)
                {
                    // Emit table at first encounter
                    var matchedTable = tableRanges.FindIndex(t => paraStart >= t.Start && paraStart <= t.End);
                    if (matchedTable >= 0 && matchedTable == tableIdx)
                    {
                        EmitTable(document.Tables[tableIdx + 1], sb); // 1-based index
                        tableIdx++;
                    }
                    continue;
                }

                string text = range.Text?.TrimEnd('\r', '\n', '\a') ?? "";
                if (string.IsNullOrWhiteSpace(text)) continue;

                string styleName = "";
                try { styleName = para.Style?.NameLocal?.ToString() ?? para.Style?.ToString() ?? ""; } catch { }

                if (styleName.Contains("Heading 1", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"# {text}");
                else if (styleName.Contains("Heading 2", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"## {text}");
                else if (styleName.Contains("Heading 3", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"### {text}");
                else if (styleName.Contains("Heading", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"#### {text}");
                else
                    sb.AppendLine(text);

                sb.AppendLine();
            }
            catch { }
        }

        // Emit any remaining tables not yet emitted
        for (int i = tableIdx; i < tableCount; i++)
        {
            try { EmitTable(document.Tables[i + 1], sb); } catch { }
        }
    }

    private static void EmitTable(object tableObj, StringBuilder sb)
    {
        try
        {
            dynamic table = tableObj;
            int rows = table.Rows.Count;
            int cols = table.Columns.Count;

            sb.AppendLine();
            for (int r = 1; r <= rows; r++)
            {
                sb.Append("|");
                for (int c = 1; c <= cols; c++)
                {
                    string cellText = "";
                    try
                    {
                        cellText = table.Cell(r, c).Range.Text?
                            .TrimEnd('\r', '\n', '\a', '\x07') ?? "";
                    }
                    catch { }
                    sb.Append($" {cellText} |");
                }
                sb.AppendLine();

                // Header separator after first row
                if (r == 1)
                {
                    sb.Append("|");
                    for (int c = 0; c < cols; c++)
                        sb.Append(" --- |");
                    sb.AppendLine();
                }
            }
            sb.AppendLine();
        }
        catch { }
    }
}
