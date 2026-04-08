using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using NetOffice.OfficeApi.Enums;

namespace DocReaderCli.Readers;

public static class PowerPointReader
{
    private const int DrmPollIntervalMs = 500;
    private const int DrmTimeoutMs = 15_000;

    public static string Read(string filePath)
    {
        using var watchdog = new ProcessWatchdog("POWERPNT");
        dynamic? app = null;
        dynamic? pres = null;

        try
        {
            Console.Error.WriteLine($"[PPTReader] Opening presentation via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath)
            {
                UseShellExecute = true,
                Verb = "open"
            });
            watchdog.DetectNewProcess();

            app = WaitForPowerPointApplication(watchdog.TimeoutMs);
            Console.Error.WriteLine("[PPTReader] Attached to running PowerPoint instance.");
            pres = WaitForPresentation(app, filePath, watchdog.TimeoutMs);
            try { app.Visible = MsoTriState.msoTrue; } catch { }

            Console.Error.WriteLine("[PPTReader] Presentation opened. Checking DRM...");
            WaitForDrmDecryption(pres, watchdog.TimeoutMs);
            Console.Error.WriteLine("[PPTReader] DRM check passed. Reading slides...");

            var sb = new StringBuilder();

            int slideCount = SafeToInt(pres.Slides?.Count);
            for (int slideNum = 1; slideNum <= slideCount; slideNum++)
            {
                sb.AppendLine($"## Slide {slideNum}");
                sb.AppendLine();

                try
                {
                    var slide = pres.Slides[slideNum];
                    ExtractSlide(slide, sb);
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[PPTReader] Error on slide {slideNum}: {ex.Message}");
                }

                sb.AppendLine();
            }

            return sb.ToString();
        }
        finally
        {
            try { pres?.Close(); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static object WaitForPowerPointApplication(int timeoutMs)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try { return GetActiveComObject("PowerPoint.Application"); } catch { }
            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException($"PowerPoint instance was not available after {timeoutMs / 1000}s.");
    }

    private static object WaitForPresentation(object app, string filePath, int timeoutMs)
    {
        dynamic pptApp = app;
        var targetPath = Path.GetFullPath(filePath);
        var sw = Stopwatch.StartNew();

        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                dynamic presentations = pptApp.Presentations;
                int count = SafeToInt(presentations?.Count);
                for (int i = 1; i <= count; i++)
                {
                    try
                    {
                        dynamic candidate = presentations[i];
                        if (PathsMatch(candidate.FullName, targetPath))
                        {
                            Console.Error.WriteLine($"[PPTReader] Presentation attached after {sw.ElapsedMilliseconds}ms.");
                            return candidate;
                        }
                    }
                    catch { }
                }
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        throw new TimeoutException($"Presentation did not appear in PowerPoint after {timeoutMs / 1000}s.");
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

    private static void WaitForDrmDecryption(object pres, int timeoutMs)
    {
        dynamic presentation = pres;
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                if (SafeToInt(presentation.Slides?.Count) > 0)
                {
                    var firstSlide = presentation.Slides[1];
                    if (firstSlide.Shapes.Count >= 0)
                        return;
                }
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        // Allow empty presentations
        try
        {
            if (SafeToInt(presentation.Slides?.Count) == 0)
                return;
        }
        catch { }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s.");
    }

    private static void ExtractSlide(object slideObj, StringBuilder sb)
    {
        dynamic slide = slideObj;
        // Extract title if present
        try
        {
            if (slide.Shapes.HasTitle == MsoTriState.msoTrue)
            {
                var titleText = slide.Shapes.Title?.TextFrame?.TextRange?.Text;
                if (!string.IsNullOrWhiteSpace(titleText))
                {
                    sb.AppendLine($"### {titleText.Trim()}");
                    sb.AppendLine();
                }
            }
        }
        catch { }

        // Extract all text shapes
        int shapeCount = SafeToInt(slide.Shapes?.Count);
        for (int i = 1; i <= shapeCount; i++)
        {
            dynamic shape = slide.Shapes[i];
            try
            {
                if (shape.HasTextFrame == MsoTriState.msoTrue)
                {
                    var text = shape.TextFrame?.TextRange?.Text;
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        // Skip if this is the title (already emitted)
                        try
                        {
                            if (slide.Shapes.HasTitle == MsoTriState.msoTrue &&
                                shape.Name == slide.Shapes.Title?.Name)
                                continue;
                        }
                        catch { }

                        sb.AppendLine(text.Trim());
                        sb.AppendLine();
                    }
                }

                // Extract text from tables in shapes
                if (shape.HasTable == MsoTriState.msoTrue)
                {
                    ExtractTable(shape.Table, sb);
                }
            }
            catch { }
        }

        // Extract notes
        try
        {
            var notes = slide.NotesPage?.Shapes;
            if (notes != null)
            {
                int noteCount = SafeToInt(notes.Count);
                for (int i = 1; i <= noteCount; i++)
                {
                    dynamic noteShape = notes[i];
                    try
                    {
                        if (noteShape.HasTextFrame == MsoTriState.msoTrue)
                        {
                            var noteText = noteShape.TextFrame?.TextRange?.Text;
                            if (!string.IsNullOrWhiteSpace(noteText) &&
                                noteText.Trim().Length > 1) // skip slide number placeholder
                            {
                                sb.AppendLine($"> **Note:** {noteText.Trim()}");
                                sb.AppendLine();
                            }
                        }
                    }
                    catch { }
                }
            }
        }
        catch { }
    }

    private static void ExtractTable(object tableObj, StringBuilder sb)
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
                        cellText = table.Cell(r, c).Shape.TextFrame.TextRange.Text ?? "";
                        cellText = cellText.Replace("|", "\\|").Replace("\n", " ").Replace("\r", "");
                    }
                    catch { }
                    sb.Append($" {cellText} |");
                }
                sb.AppendLine();

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
