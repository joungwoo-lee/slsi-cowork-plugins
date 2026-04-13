using System.Diagnostics;
using System.Runtime.InteropServices;
using DocCopyCli.Helpers;

namespace DocCopyCli.Copiers;

public static class PowerPointCopier
{
    private const int PollIntervalMs = 500;

    // ppSaveAs* FileFormat integer constants (no NetOffice dependency needed)
    private static int GetPptFileFormat(string ext) => ext switch
    {
        ".ppt"  => 1,   // ppSaveAsPresentation
        ".pps"  => 9,   // ppSaveAsShow
        ".potx" => 35,  // ppSaveAsOpenXMLTemplate
        ".potm" => 36,  // ppSaveAsOpenXMLTemplateMacroEnabled
        ".pptm" => 25,  // ppSaveAsOpenXMLPresentationMacroEnabled
        ".ppsx" => 33,  // ppSaveAsOpenXMLShow
        _       => 24,  // ppSaveAsOpenXMLPresentation (.pptx, default)
    };

    public static void Copy(string filePath, string outputPath)
    {
        using var watchdog = new ProcessWatchdog("POWERPNT");
        dynamic? app = null;
        dynamic? pres = null;
        dynamic? freshApp = null;
        dynamic? newPres = null;

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
            string markdownPath = MarkdownExporter.GetMarkdownPath(outputPath, filePath);
            MarkdownExporter.WritePresentationMarkdown(markdownPath, CaptureSlidesText(pres));
            Console.Error.WriteLine("[PPTCopier] DRM check passed. Copying slides to fresh instance...");

            // 2. Spin up a fresh PowerPoint instance (no DRM context)
            var pptType = Type.GetTypeFromProgID("PowerPoint.Application")
                ?? throw new InvalidOperationException("PowerPoint.Application COM class not registered.");
            freshApp = Activator.CreateInstance(pptType)
                ?? throw new InvalidOperationException("Failed to create PowerPoint.Application COM instance.");

            // 3. Create a new blank presentation in the fresh instance
            // WithWindow: 0 = msoFalse (hidden)
            newPres = freshApp.Presentations.Add(WithWindow: 0);

            // 4. Copy each slide via clipboard into the fresh presentation
            int slideCount = SafeToInt(pres.Slides?.Count);
            for (int i = 1; i <= slideCount; i++)
            {
                try
                {
                    pres.Slides[i].Copy();
                    newPres.Slides.Paste(i);
                    Console.Error.WriteLine($"[PPTCopier] Slide {i}/{slideCount} copied.");
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[PPTCopier] Warning on slide {i}: {ex.Message}");
                }
            }

            // Remove the blank slide that was added by Presentations.Add() if slides were pasted
            if (slideCount > 0)
            {
                try
                {
                    int newSlideCount = SafeToInt(newPres.Slides?.Count);
                    // Presentations.Add() creates one blank slide at index 1;
                    // pasted slides go in at the specified index pushing it to the end.
                    if (newSlideCount > slideCount)
                        newPres.Slides[newSlideCount].Delete();
                }
                catch { }
            }

            // 5. Save from the fresh instance — DRM driver will not intercept this
            EnsureDirectory(outputPath);
            int fileFormat = GetPptFileFormat(Path.GetExtension(filePath).ToLowerInvariant());
            newPres.SaveAs(FileName: outputPath, FileFormat: fileFormat);

            Console.Error.WriteLine($"[PPTCopier] Saved: {outputPath}");
        }
        finally
        {
            try { newPres?.Close(); } catch { }
            try { freshApp?.Quit(); } catch { }
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
