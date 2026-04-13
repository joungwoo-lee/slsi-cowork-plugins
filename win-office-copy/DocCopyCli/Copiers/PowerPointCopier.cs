using System.Diagnostics;
using System.Runtime.InteropServices;
using DocCopyCli.Helpers;

namespace DocCopyCli.Copiers;

public static class PowerPointCopier
{
    private const int PollIntervalMs = 500;

    public static void Copy(string filePath, string outputPath)
    {
        outputPath = OpenXmlSaver.NormalizePowerPointOutputPath(outputPath);
        using var watchdog = new ProcessWatchdog("POWERPNT");
        dynamic? app = null;
        dynamic? pres = null;

        try
        {
            // 1. Shell-open the DRM presentation
            Console.Error.WriteLine($"[PPTCopier] Opening presentation via shell: {filePath}");
            Process.Start(new ProcessStartInfo(filePath) { UseShellExecute = true, Verb = "open" });
            watchdog.DetectNewProcess();

            app = WaitForPowerPointApplication(watchdog.TimeoutMs);
            Console.Error.WriteLine("[PPTCopier] Attached to running PowerPoint instance.");
            pres = WaitForPresentation(app, filePath, watchdog.TimeoutMs);
            try { app.Visible = -1; /* msoTrue */ } catch { }

            Console.Error.WriteLine("[PPTCopier] Presentation opened. Checking DRM...");
            WaitForDrmDecryption(pres, watchdog.TimeoutMs);
            var slides = CaptureSlidesText(pres);
            string markdownPath = MarkdownExporter.GetMarkdownPath(outputPath, filePath);
            MarkdownExporter.WritePresentationMarkdown(markdownPath, slides);
            Console.Error.WriteLine("[PPTCopier] DRM check passed. Rebuilding PPTX package...");

            OpenXmlSaver.SavePresentation(outputPath, slides);

            Console.Error.WriteLine($"[PPTCopier] Saved: {outputPath}");
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
            Thread.Sleep(PollIntervalMs);
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
                            Console.Error.WriteLine($"[PPTCopier] Presentation attached after {sw.ElapsedMilliseconds}ms.");
                            return candidate;
                        }
                    }
                    catch { }
                }
            }
            catch { }
            Thread.Sleep(PollIntervalMs);
        }
        throw new TimeoutException($"Presentation did not appear in PowerPoint after {timeoutMs / 1000}s.");
    }

    private static void WaitForDrmDecryption(object pres, int timeoutMs)
    {
        dynamic presentation = pres;
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                if (SafeToInt(presentation.Slides?.Count) > 0)
                {
                    _ = presentation.Slides[1].Shapes.Count;
                    return;
                }
            }
            catch { }
            Thread.Sleep(PollIntervalMs);
        }
        try { if (SafeToInt(presentation.Slides?.Count) == 0) return; } catch { }
        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s. " +
            "Open the file manually to authenticate DRM first, then retry.");
    }

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    private static List<string> CaptureSlidesText(dynamic presentation)
    {
        var slides = new List<string>();
        int slideCount = SafeToInt(presentation.Slides?.Count);
        for (int i = 1; i <= slideCount; i++)
        {
            try
            {
                dynamic slide = presentation.Slides[i];
                int shapeCount = SafeToInt(slide.Shapes?.Count);
                var chunks = new List<string>();
                for (int j = 1; j <= shapeCount; j++)
                {
                    try
                    {
                        dynamic shape = slide.Shapes[j];
                        if (shape.HasTextFrame == -1 && shape.TextFrame.HasText == -1)
                        {
                            string text = shape.TextFrame.TextRange.Text?.ToString() ?? string.Empty;
                            if (!string.IsNullOrWhiteSpace(text)) chunks.Add(text.Trim());
                        }
                    }
                    catch { }
                }

                slides.Add(string.Join(Environment.NewLine + Environment.NewLine, chunks));
            }
            catch
            {
                slides.Add(string.Empty);
            }
        }

        return slides;
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
